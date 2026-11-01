"""Non-destructive importer for original AlMahri supplier edges + pilot overlays.

Requires: python -m pip install neo4j
Run only against your development Neo4j database. Uses MERGE; does NOT clear nodes.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from maritime.supplier import locate_csv, read_edges


def read_json(path):
    with path.open(encoding="utf8") as f:
        return json.load(f)


def batched(items, n=500):
    for start in range(0,len(items),n):
        yield items[start:start+n]


def main(upstream: str | None, canonical: bool = False, data_dir: str | None = None):
    try:
        from neo4j import GraphDatabase
    except ImportError as e:
        raise SystemExit("Install the Neo4j driver first: python -m pip install neo4j") from e
    uri=os.getenv("NEO4J_URI", "bolt://localhost:7687")
    username=os.getenv("NEO4J_USERNAME", "neo4j")
    password=os.getenv("NEO4J_PASSWORD")
    if not password:
        raise SystemExit("Set NEO4J_PASSWORD in your shell before running. Never commit it.")
    proc=Path(data_dir) if data_dir else ROOT / "data" / "processed"
    shipments=read_json(proc/"shipments.json")
    ports=read_json(proc/"ports.json")
    services=read_json(proc/"services.json")
    original_edges=read_edges(locate_csv(ROOT,upstream))
    orig_rows=[dict(supplier=r["Supplier"], customer=r["Customer"],
                    supplier_country=r["Supplier Country"], customer_country=r["Customer Country"],
                    supplier_industry=r["Supplier Industry"], customer_industry=r["Customer Industry"])
               for r in original_edges]
    driver=GraphDatabase.driver(uri,auth=(username,password))
    driver.verify_connectivity()
    try:
        with driver.session() as session:
            for constraint in [
                'CREATE CONSTRAINT company_name IF NOT EXISTS FOR (c:Company) REQUIRE c.name IS UNIQUE',
                'CREATE CONSTRAINT country_name IF NOT EXISTS FOR (c:Country) REQUIRE c.name IS UNIQUE',
                'CREATE CONSTRAINT port_id IF NOT EXISTS FOR (p:Port) REQUIRE p.id IS UNIQUE',
                'CREATE CONSTRAINT service_id IF NOT EXISTS FOR (s:ServiceLeg) REQUIRE s.id IS UNIQUE',
                'CREATE CONSTRAINT shipment_id IF NOT EXISTS FOR (s:Shipment) REQUIRE s.id IS UNIQUE',
                'CREATE CONSTRAINT plan_id IF NOT EXISTS FOR (p:RoutePlan) REQUIRE p.id IS UNIQUE',
                'CREATE CONSTRAINT leg_id IF NOT EXISTS FOR (l:PlannedLeg) REQUIRE l.id IS UNIQUE',
                'CREATE CONSTRAINT disruption_id IF NOT EXISTS FOR (d:Disruption) REQUIRE d.id IS UNIQUE'
            ]:
                session.run(constraint).consume()
            original_query='''
                UNWIND $rows AS r
                MERGE (s:Company {name:r.supplier})
                ON CREATE SET s.industry=r.supplier_industry
                MERGE (c:Company {name:r.customer})
                ON CREATE SET c.industry=r.customer_industry
                MERGE (sc:Country {name:r.supplier_country})
                MERGE (cc:Country {name:r.customer_country})
                MERGE (s)-[:locatedIn]->(sc)
                MERGE (c)-[:locatedIn]->(cc)
                MERGE (s)-[:suppliesTo]->(c)
            '''
            for group in batched(orig_rows):
                session.run(original_query,rows=group).consume()
            if canonical:
                ports=read_json(proc/"ports.json")
                services=read_json(proc/"services.json")
                shipments=read_json(proc/"shipments.json")
                plans=read_json(proc/"route_plans.json")
                session.run('''UNWIND $rows AS r MERGE (p:Port {id:r.port_id})
                    SET p.name=r.name,p.country=r.country,p.latitude=r.latitude,p.longitude=r.longitude,
                        p.verified=r.verified,p.source_class=r.source_class,p.source_reference=r.source_reference,
                        p.source_url=r.source_url,p.dataset_version=r.dataset_version,
                        p.retrieved_date=r.retrieved_date,p.license=r.license,
                        p.country_code=r.country_code,p.location_code=r.location_code''',rows=ports).consume()
                session.run('''UNWIND $rows AS r MATCH (a:Port {id:r.origin_port_id})
                    MATCH (b:Port {id:r.destination_port_id}) MERGE (s:ServiceLeg {id:r.service_id})
                    SET s.transit_days=r.transit_days,s.cost_units=r.cost_units,s.source_class=r.source_class,
                        s.provenance=r.source_reference,s.direction=r.direction,s.source_type=r.source_type,
                        s.source_version=r.source_version,s.source_url=r.source_url,
                        s.distance_nm=r.distance_nm,s.distance_method=r.distance_method,
                        s.transit_method=r.transit_method,s.departure_frequency_days=r.departure_frequency_days,
                        s.min_transfer_hours=r.min_transfer_hours,s.cost_per_teu_usd=r.cost_per_teu_usd,
                        s.cost_method=r.cost_method,s.capacity_teu=r.capacity_teu,
                        s.cargo_classes=r.cargo_classes,s.modeled_from_observed_ref=r.modeled_from_observed_ref,
                        s.observed_movement_count=r.observed_movement_count,
                        s.commercial_service_claim=r.commercial_service_claim,s.service_evidence=r.service_evidence
                    MERGE (s)-[:DEPARTS_FROM]->(a) MERGE (s)-[:ARRIVES_AT]->(b)''',rows=services).consume()
                shipment_query='''UNWIND $rows AS r MATCH (o:Port {id:r.origin_port_id})
                    MATCH (d:Port {id:r.destination_port_id}) MATCH (supplier:Company {name:r.supplier})
                    MATCH (customer:Company {name:r.customer}) MATCH (supplier)-[:suppliesTo]->(customer)
                    MERGE (s:Shipment {id:r.shipment_id})
                    SET s.source_class=r.source_class,s.supplier_edge_id=r.supplier_edge_id,
                        s.release_day=r.release_day,s.deadline_day=r.deadline_day,s.cargo_teu=r.cargo_teu,
                        s.provenance=r.provenance,s.cargo_class=r.cargo_class,s.priority=r.priority,
                        s.supplier_country=r.supplier_country,s.customer_country=r.customer_country,
                        s.expansion_bucket=r.expansion_bucket,s.location_source_class=r.location_source_class
                    MERGE (supplier)-[:ORIGINATES]->(s) MERGE (s)-[:DELIVERED_TO]->(customer)
                    MERGE (s)-[:ORIGIN_PORT]->(o) MERGE (s)-[:DESTINATION_PORT]->(d)'''
                neo_shipments=[{**x,"provenance":json.dumps(x.get("provenance",{}),sort_keys=True)} for x in shipments]
                for group in batched(neo_shipments): session.run(shipment_query,rows=group).consume()
                for p in plans:
                    session.run('''MATCH (s:Shipment {id:$shipment}) MERGE (p:RoutePlan {id:$id})
                        SET p.transit_days=$days,p.cost_units=$cost,p.source_class=$source,
                            p.status=$status,p.plan_version=$version,p.estimated_arrival=$arrival
                        MERGE (s)-[:HAS_PLAN]->(p)''',shipment=p["shipment_id"],id=p["route_plan_id"],days=p["transit_days"],cost=p["total_cost_usd"],source=p.get("source_class","SYNTHETIC_INITIAL_PLAN"),status=p.get("status","INITIAL"),version=p.get("plan_version",1),arrival=p["estimated_arrival"]).consume()
                    for seq, planned in enumerate(p.get("ordered_legs",[]),1):
                        service_id=planned["service_id"]
                        session.run('''MATCH (p:RoutePlan {id:$plan}) MATCH (s:ServiceLeg {id:$service})
                            MERGE (l:PlannedLeg {id:$id}) SET l.sequence=$seq,l.depart_day=$depart,l.arrive_day=$arrive,
                                l.cost_usd=$cost,l.source_class='CANONICAL_DATASET'
                            MERGE (p)-[:HAS_LEG]->(l) MERGE (l)-[:USES_SERVICE]->(s)''',plan=p["route_plan_id"],service=service_id,id=f'{p["route_plan_id"]}:L{seq}',seq=seq,depart=planned["planned_departure"],arrive=planned["planned_arrival"],cost=planned["modeled_cost_usd"]).consume()
                actual=session.run('''MATCH (s:Shipment) WHERE s.id IN $ids RETURN count(DISTINCT s) AS shipments''',ids=[x["shipment_id"] for x in shipments]).single()["shipments"]
                expected=len(shipments)
                if actual<expected:raise RuntimeError(f"Canonical import attached only {actual}/{expected} shipments; one or more supplier/port references did not match")
                ids=[x["shipment_id"] for x in shipments];plan_ids=[x["route_plan_id"] for x in plans]
                base_ids=[x["shipment_id"] for x in shipments if x["shipment_id"].startswith("SHIP-") and not x["shipment_id"].startswith("SHIP-EXP-")]
                expansion_ids=[x["shipment_id"] for x in shipments if x["shipment_id"].startswith("SHIP-EXP-")]
                service_ids=[x["service_id"] for x in services]
                counts={"supply_edges":session.run("MATCH ()-[r:suppliesTo]->() RETURN count(r) AS n").single()["n"],
                        "shipments":session.run("MATCH (s:Shipment) WHERE s.id IN $ids RETURN count(s) AS n",ids=ids).single()["n"],
                        "base_shipments":session.run("MATCH (s:Shipment) WHERE s.id IN $ids RETURN count(s) AS n",ids=base_ids).single()["n"],
                        "expansion_shipments":session.run("MATCH (s:Shipment) WHERE s.id IN $ids RETURN count(s) AS n",ids=expansion_ids).single()["n"],
                        "plans":session.run("MATCH (p:RoutePlan) WHERE p.id IN $ids RETURN count(p) AS n",ids=plan_ids).single()["n"],
                        "planned_legs":session.run("MATCH (p:RoutePlan)-[:HAS_LEG]->(l:PlannedLeg) WHERE p.id IN $ids RETURN count(l) AS n",ids=plan_ids).single()["n"],
                        "operational_ports":session.run("MATCH (:ServiceLeg)-[:DEPARTS_FROM]->(p:Port) RETURN count(DISTINCT p) AS n").single()["n"],
                        "services":session.run("MATCH (s:ServiceLeg) WHERE s.id IN $ids RETURN count(s) AS n",ids=service_ids).single()["n"],
                        "shipments_with_original_suppliesTo_edge":session.run("MATCH (a:Company)-[:ORIGINATES]->(s:Shipment)-[:DELIVERED_TO]->(b:Company) MATCH (a)-[:suppliesTo]->(b) WHERE s.id IN $ids RETURN count(DISTINCT s) AS n",ids=ids).single()["n"]}
                if counts["shipments"]!=expected or counts["plans"]!=expected:raise RuntimeError(f"Canonical import count mismatch: {counts}")
                if counts["shipments_with_original_suppliesTo_edge"]!=expected:raise RuntimeError(f"Not all imported shipments preserve their direct original supplier edge: {counts}")
                if canonical and len(shipments)==1500 and (counts["base_shipments"]!=1000 or counts["expansion_shipments"]!=500 or counts["operational_ports"]>50 or counts["services"]!=len(services)):
                    raise RuntimeError(f"Expansion Neo4j parity check failed: {counts}")
                print("Canonical Neo4j import complete (MERGE; idempotent count snapshot):",counts)
                return
            session.run('''
                UNWIND $rows AS row
                MERGE (p:Port {id:row.id})
                SET p.name=row.name,p.source_class=row.source_class
            ''',rows=ports).consume()
            service_rows=[{**s, "id":s["from"]+"__"+s["to"]} for s in services]
            session.run('''
                UNWIND $rows AS row
                MATCH (a:Port {id:row['from']})
                MATCH (b:Port {id:row['to']})
                MERGE (s:ServiceLeg {id:row.id})
                SET s.transit_days=row.transit_days,s.cost_units=row.cost_units,
                    s.source_class=row.source_class
                MERGE (s)-[:DEPARTS_FROM]->(a)
                MERGE (s)-[:ARRIVES_AT]->(b)
            ''',rows=service_rows).consume()
            shipment_query='''
                UNWIND $rows AS row
                MATCH (s:Company {name:row.supplier})
                MATCH (c:Company {name:row.customer})
                MATCH (s)-[:suppliesTo]->(c)
                MERGE (ship:Shipment {id:row.id})
                SET ship.cargo_class=row.cargo_class, ship.cargo_teu=row.cargo_teu,
                    ship.release_day=row.release_day, ship.deadline_day=row.deadline_day,
                    ship.source_class=row.source_class, ship.provenance=row.provenance
                MERGE (s)-[:ORIGINATES]->(ship)
                MERGE (ship)-[:DELIVERED_TO]->(c)
                MERGE (plan:RoutePlan {id:row.plan_id})
                SET plan.status='ORIGINAL', plan.transit_days=row.transit_days,
                    plan.cost_units=row.cost_units
                MERGE (ship)-[:HAS_PLAN]->(plan)
            '''
            shipment_rows=[]
            planned_legs=[]
            for x in shipments:
                route=x["original_route"]
                shipment_rows.append({"id":x["shipment_id"],"supplier":x["supplier"],
                                      "customer":x["customer"],"cargo_class":x["cargo_class"],
                                      "cargo_teu":x["cargo_teu"],"release_day":x["release_day"],
                                      "deadline_day":x["deadline_day"],"source_class":x["source_class"],
                                      "provenance":json.dumps(x.get("provenance", {}), sort_keys=True),
                                      "plan_id":"PLAN-"+x["shipment_id"],
                                      "transit_days":route["transit_days"],"cost_units":route["cost_units"]})
                t=x["release_day"]
                service_map={(s["from"],s["to"]):s for s in services}
                for sequence,(a,b) in enumerate(zip(route["ports"],route["ports"][1:]),start=1):
                    service=service_map[(a,b)]
                    planned_legs.append({"id":f"{x['shipment_id']}:L{sequence}","plan_id":"PLAN-"+x["shipment_id"],
                                         "service_id":a+"__"+b,"sequence":sequence,
                                         "depart_day":t,"arrive_day":t+service["transit_days"]})
                    t+=service["transit_days"]
            for group in batched(shipment_rows):
                session.run(shipment_query,rows=group).consume()
            session.run('''
                UNWIND $rows AS row
                MATCH (p:RoutePlan {id:row.plan_id})
                MATCH (s:ServiceLeg {id:row.service_id})
                MERGE (l:PlannedLeg {id:row.id})
                SET l.sequence=row.sequence,l.depart_day=row.depart_day,l.arrive_day=row.arrive_day
                MERGE (p)-[:HAS_LEG]->(l)
                MERGE (l)-[:USES_SERVICE]->(s)
            ''',rows=planned_legs).consume()
            scenario=read_json(ROOT/"data"/"scenarios"/"PILOT_001.json")
            session.run('''
                MATCH (p:Port {id:$target})
                MERGE (d:Disruption {id:$id})
                SET d.type=$type,d.start_day=$start_day,d.end_day=$end_day,
                    d.source_class='SYNTHETIC_PILOT',d.provenance=$provenance
                MERGE (d)-[:AFFECTS]->(p)
            ''',target=scenario["port_id"],id=scenario["scenario_id"],type=scenario["type"],
                    start_day=scenario["start_day"],end_day=scenario["end_day"],
                    provenance=json.dumps(scenario.get("provenance", {}), sort_keys=True)).consume()
            counts=session.run('''
                MATCH (s:Shipment) WITH count(s) AS n_shipments
                MATCH (p:Port) WITH n_shipments,count(p) AS n_ports
                MATCH (l:PlannedLeg) RETURN n_shipments,n_ports,count(l) AS n_legs
            ''').single()
            print("Neo4j import complete (MERGE; no database deletion):",dict(counts))
            print("Caution: all added shipment schedules, service availability and costs are synthetic.")
    finally:
        driver.close()

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--upstream",help="Path to AlMahri repo or supplychainKG_clean.csv")
    ap.add_argument("--canonical",action="store_true",help="Import canonical ports/services/shipments/route_plans JSON")
    ap.add_argument("--data-dir",help="Dataset output directory (defaults to data/processed)")
    args=ap.parse_args()
    main(args.upstream,args.canonical,args.data_dir)
