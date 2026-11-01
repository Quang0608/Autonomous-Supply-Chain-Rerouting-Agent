"""Create a minimal pilot based on actual AlMahri direct supplier edges.

No Neo4j and no LLM required. Outputs are exploratory, NOT scientific ground truth.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import random
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from maritime.supplier import locate_csv, read_edges, choose_pairs
from maritime.network import COUNTRY_PORT, build_network, shortest_path
from maritime.models import validate_dataset


def dump_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def build_pilot(upstream, count: int, seed: int):
    csv_file = locate_csv(ROOT, upstream)
    edges = read_edges(csv_file)
    source_sha256 = hashlib.sha256(csv_file.read_bytes()).hexdigest()
    selected, report = choose_pairs(edges, set(COUNTRY_PORT), limit=max(15, count), seed=seed)
    if not selected:
        raise RuntimeError("No supported international supplier pairs. Add geographic coverage to COUNTRY_PORT.")
    out = ROOT / "data" / "processed"
    out.mkdir(parents=True, exist_ok=True)
    cols = ["Supplier", "Supplier Country", "Customer", "Customer Country",
            "Supplier Industry", "Customer Industry", "tier", "linked_to_manufacturer"]
    with (out/"selected_supplier_pairs.csv").open("w",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction="ignore")
        w.writeheader(); w.writerows(selected)
    provenance = {
        "dataset_id": "ALMAHRI_PILOT_SYNTHETIC_LOGISTICS",
        "generator": "scripts/bootstrap_pilot.py",
        "seed": seed,
        "upstream": {"name": "AlMahri supplychainKG_clean.csv", "path": str(csv_file),
                     "sha256": source_sha256, "relationship_semantics": "original suppliesTo edge"},
        "synthetic_fields": ["ports gateway mapping", "service availability", "transit days",
                             "cost units", "shipment", "route schedule", "disruption"],
        "limitations": "A supplier edge does not establish a real transaction or shipment; modeled services are not verified.",
    }
    dump_json(out / "supplier_audit.json", {**report, "provenance": provenance})

    ports, services=build_network()
    dump_json(out/"ports.json", list(ports.values()))
    dump_json(out/"services.json", list(services.values()))
    rng=random.Random(seed)
    shipments=[]
    for n in range(count):
        pair=selected[n%len(selected)]
        a=COUNTRY_PORT[pair["Supplier Country"]][0]
        b=COUNTRY_PORT[pair["Customer Country"]][0]
        if a==b:
            continue
        route=shortest_path(a,b,services)
        if route is None:
            continue
        shipments.append({
            "shipment_id":f"SHIP-{len(shipments)+1:04d}",
            "supplier":pair["Supplier"], "customer":pair["Customer"],
            "supplier_country":pair["Supplier Country"],
            "customer_country":pair["Customer Country"],
            "supplier_tier":pair["tier"],
            "cargo_class":"GENERAL_CONTAINER_SYNTHETIC",
            "release_day":0, "deadline_day":int(route["transit_days"]+14),
            "cargo_teu":rng.randint(1,3),
            "original_route":route,
            "source_class":"SYNTHETIC_SHIPMENT_FROM_ALMAHRI_SUPPLIESTO",
            "provenance": {"upstream_sha256": source_sha256, "relationship_source": "AlMahri suppliesTo",
                           "logistics_source": "synthetic development data", "seed": seed}
        })
    if not shipments:
        raise RuntimeError("No valid shipments generated: inspect selected supplier pairs.")
    dump_json(out/"shipments.json",shipments)

    # Pick an intermediate port whose closure affects the most shipment plans
    # while allowing at least one reroute. Do NOT close the shipment origin.
    candidates=Counter(p for s in shipments for p in s["original_route"]["ports"][1:-1])
    chosen=None
    for p,_ in candidates.most_common():
        feasible=sum(bool(shortest_path(s["original_route"]["ports"][0],
                                        s["original_route"]["ports"][-1],services,{p}))
                     for s in shipments if p in s["original_route"]["ports"][1:-1])
        if feasible:
            chosen=p;break
    if chosen is None:
        raise RuntimeError("No reroutable intermediate-port closure in this sample. Adjust selected pairs or network.")
    scenario={"scenario_id":"PILOT_001","parent_almahri_scenario_id":None,
              "type":"PORT_CLOSURE","port_id":chosen,
              "start_day":0,"end_day":45,
              "note":"Independent pilot logistics variant, not a claim about an AlMahri article"}
    validate_dataset(list(ports.values()), list(services.values()), shipments, scenario)
    scenario["provenance"] = {"source": "synthetic development data", "seed": seed,
                              "upstream_sha256": source_sha256}
    dump_json(ROOT/"data"/"scenarios"/"PILOT_001.json",scenario)
    impacted=[]; recovery=[]
    for shipment in shipments:
        original=shipment["original_route"]["ports"]
        # Every leg is scheduled after day 0 and before day 45 in the pilot.
        if chosen not in original:
            continue
        impacted.append(shipment["shipment_id"])
        alt=shortest_path(original[0],original[-1],services,{chosen})
        recovery.append({"shipment_id":shipment["shipment_id"],
                         "status": "FEASIBLE" if alt and alt["transit_days"]<=shipment["deadline_day"] else "INFEASIBLE",
                         "alternative_route":alt,"deadline_day":shipment["deadline_day"]})
    provisional={"scenario_id":"PILOT_001","is_independent_ground_truth":False,
                 "note":"Provisional reference from SAME routing function; independently verify before evaluation.",
                 "affected_shipments":impacted,"recovery":recovery}
    dump_json(ROOT/"data"/"scenarios"/"PILOT_001_provisional_reference.json",provisional)
    print(f"Input supplier relationships: {len(edges)}")
    print(f"Selected pairs: {len(selected)} (connected to monitored firm: {report['selected_linked_to_manufacturer']})")
    print(f"Generated shipments: {len(shipments)}")
    print(f"Modeled network: {len(ports)} ports, {len(services)} directed service edges")
    print(f"Closed intermediate port: {chosen} ({ports[chosen]['name']})")
    print(f"Impacted shipments: {len(impacted)}")
    print(f"Provisional feasible recovery: {sum(x['status']=='FEASIBLE' for x in recovery)} / {len(recovery)}")
    print(f"Files: {out} and {ROOT/'data'/'scenarios'}")

if __name__ == "__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--upstream", help="Path to AlMahri clone or its cleaned CSV")
    ap.add_argument("--shipments",type=int,default=20)
    ap.add_argument("--seed",type=int,default=42)
    a=ap.parse_args()
    if a.shipments<1:
        ap.error("--shipments must be >=1")
    build_pilot(a.upstream,a.shipments,a.seed)
