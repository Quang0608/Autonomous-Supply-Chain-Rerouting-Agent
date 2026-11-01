"""Append US/China demand to the frozen 1,000-shipment benchmark."""
from __future__ import annotations
import argparse,csv,hashlib,json,random,sys,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
from maritime.supplier import locate_csv,read_edges,tier_from_manufacturer
from build_logistics_dataset import stable_edge_id,schedule_path
from ingest_unlocode_ports import COUNTRY_TO_ISO
import searoute
import networkx as nx

US_CODES={"USA","US","UNITED STATES","UNITED STATES OF AMERICA"}
CN_CODES={"CN","CHINA","CHN"}
TARGET_PORTS={"US":["USNYC","USLAX","USHOU","USTSA"],"CN":["CNNBG","CNSNZ","CNQIN","CNTXG"]}
TARGET_HUBS={"US":["NLRTM","SGSIN"],"CN":["SGSIN","NLRTM"]}

def normalize_country(value):
    text=(value or "").strip().upper()
    if text in US_CODES:return "US"
    if text in CN_CODES:return "CN"
    return {k.upper():v for k,v in COUNTRY_TO_ISO.items()}.get(text,text)

def target_bucket(edge):
    a,b=normalize_country(edge["Supplier Country"]),normalize_country(edge["Customer Country"])
    us="US" in (a,b) and a!=b;cn="CN" in (a,b) and a!=b
    return us,cn

def require_quotas(report):
    if report["selected_us_bucket"]!=50 or report["selected_china_bucket"]!=50:
        raise RuntimeError(f"Quota shortfall; no combined build: {report['shortfalls']}")

def check_port_limit(total_ports,maximum):
    if total_ports>maximum:raise ValueError(f"Operational port ceiling exceeded: {total_ports} > {maximum}")
    return True

def rank_bucket(candidates,linked,seed):
    """Deterministic greedy selection that favors linked edges and diverse O-Ds."""
    remaining=list(candidates);selected=[];pair_counts={};direction_counts={}
    while remaining and len(selected)<50:
        def score(e):
            a,b=normalize_country(e["Supplier Country"]),normalize_country(e["Customer Country"])
            target="US" if "US" in (a,b) else "CN";other=b if a==target else a
            direction=f"{target}:{'out' if a==target else 'in'}"
            return (int(stable_edge_id(e) in linked),-pair_counts.get((target,other),0),-direction_counts.get(direction,0),hashlib.sha256(f"{seed}:{stable_edge_id(e)}".encode()).hexdigest())
        best=max(remaining,key=score);remaining.remove(best);selected.append(best)
        a,b=normalize_country(best["Supplier Country"]),normalize_country(best["Customer Country"]);target="US" if "US" in (a,b) else "CN";other=b if a==target else a
        pair_counts[(target,other)]=pair_counts.get((target,other),0)+1;direction=f"{target}:{'out' if a==target else 'in'}";direction_counts[direction]=direction_counts.get(direction,0)+1
    return selected

def audit_selection(edges,base_shipments,base_endpoints,seed=42):
    used={s.get("supplier_edge_id",s.get("source_supplier_edge_id")) for s in base_shipments}
    endpoint_iso={normalize_country(r[c]):r[k] for r in base_endpoints for c,k in (("supplier_country","origin_iso2"),("customer_country","destination_iso2"))}
    depths=tier_from_manufacturer(edges);linked={stable_edge_id(e) for e in edges if e["Supplier"] in depths and e["Customer"] in depths and depths[e["Supplier"]]==depths[e["Customer"]]+1}
    unique={stable_edge_id(e):e for e in edges};unused=[e for eid,e in unique.items() if eid not in used and normalize_country(e["Supplier Country"])!=normalize_country(e["Customer Country"])]
    us_all=[e for e in unused if target_bucket(e)[0]];cn_all=[e for e in unused if target_bucket(e)[1]];overlap={stable_edge_id(e) for e in us_all if target_bucket(e)[1]}
    covered=[]
    for e in unused:
        a,b=normalize_country(e["Supplier Country"]),normalize_country(e["Customer Country"])
        # Both ends must map to the frozen gateway set, except expanded target countries.
        if (a=="US" or a=="CN" or a in endpoint_iso) and (b=="US" or b=="CN" or b in endpoint_iso):covered.append(e)
    covered_ids={stable_edge_id(e) for e in covered}
    us=[e for e in us_all if stable_edge_id(e) in covered_ids]
    cn=[e for e in cn_all if stable_edge_id(e) in covered_ids and stable_edge_id(e) not in overlap]
    chosen_us=rank_bucket(us,linked,seed);chosen_cn=rank_bucket(cn,linked,seed+1)
    selected=chosen_us+chosen_cn
    record_rows=[]
    for bucket,rows in (("US",chosen_us),("CN",chosen_cn)):
        for e in rows:
            a,b=normalize_country(e["Supplier Country"]),normalize_country(e["Customer Country"])
            record_rows.append({"supplier_edge_id":stable_edge_id(e),"bucket":bucket,"supplier":e["Supplier"],"customer":e["Customer"],"supplier_country":e["Supplier Country"],"customer_country":e["Customer Country"],"supplier_country_code":a,"customer_country_code":b,"supplier_industry":e["Supplier Industry"],"customer_industry":e["Customer Industry"],"manufacturer_linked":stable_edge_id(e) in linked,"direction":f"{a}->{b}","source_class":"ALMAHRI_DIRECT_SUPPLIESTO"})
    report={"supplier_edges_read":len(edges),"base_supplier_edges_used":len(used),"unused_cross_border_edges":len(unused),"eligible_us_cross_border_unused":len(us_all),"eligible_china_cross_border_unused":len(cn_all),"eligible_us_china_overlap":len(overlap),"gateway_covered_us_candidates":len(us),"gateway_covered_china_exclusive_candidates":len(cn),"selected_new_edges":len(selected),"selected_us_bucket":len(chosen_us),"selected_china_bucket":len(chosen_cn),"selected_us_membership_including_overlap":sum(target_bucket(e)[0] for e in selected),"selected_china_membership_including_overlap":sum(target_bucket(e)[1] for e in selected),"selected_overlap_count":sum(target_bucket(e)[0] and target_bucket(e)[1] for e in selected),"selected_linked_to_monitored_manufacturer":sum(stable_edge_id(e) in linked for e in selected),"country_coverage_iso2":sorted({normalize_country(e[k]) for e in selected for k in ("Supplier Country","Customer Country")}),"direction_counts":{f"{a}->{b}":sum(x["direction"]==f"{a}->{b}" for x in record_rows) for a,b in sorted({tuple(x["direction"].split("->")) for x in record_rows})},"shortfalls":{"US":max(0,50-len(chosen_us)),"China":max(0,50-len(chosen_cn))},"selection_policy":"50 US bucket edges and 50 China bucket edges; US-China overlap is assigned to US and excluded from China; prefer monitored-manufacturer links and country/direction diversity; only original distinct unused direct edges with both endpoints covered by existing or target gateway countries.","unselected_reason_counts":{"outside_gateway_country_coverage":len(unused)-len(covered),"base_edge_already_used":len(used)}}
    return report,record_rows

def make_service(a,b,pmap,cfg,source_class="MODELED_SERVICE_EXPANSION"):
    route=searoute.searoute([float(pmap[a]["longitude"]),float(pmap[a]["latitude"])],[float(pmap[b]["longitude"]),float(pmap[b]["latitude"])],units="naut",speed_knot=cfg["vessel_speed_knots"])
    nm=float(route["properties"]["length"])
    if nm<=0:raise ValueError(f"SeaRoute returned invalid nautical-mile distance for {a}->{b}")
    sid="SVC-EXP-"+hashlib.sha256(f"{a}>{b}".encode()).hexdigest()[:14];days=nm/(24*cfg["vessel_speed_knots"])+cfg["port_handling_days"]
    return {"service_id":sid,"origin_port_id":a,"destination_port_id":b,"direction":"DIRECTED","source_class":source_class,"source_type":"modeled","service_evidence":"Synthetic expansion corridor; SeaRoute provides navigable distance only, not service availability","source_reference":"CODEX_PHASE2_EXPANSION_1500_SHIPMENTS_50_PORTS.md; config/maritime_network.json","source_version":"SeaRoute 1.6.0","distance_nm":round(nm,3),"distance_method":"SeaRoute maritime network, nautical miles","transit_days":round(days,4),"transit_method":"distance_nm/(24*vessel_speed_knots)+port_handling_days","vessel_speed_knots":cfg["vessel_speed_knots"],"port_handling_days":cfg["port_handling_days"],"departure_frequency_days":cfg["departure_frequency_days"],"min_transfer_hours":cfg["minimum_transfer_hours"],"cost_per_teu_usd":round(cfg["fixed_service_cost_usd"]+nm*cfg["cost_per_teu_usd_per_nm"],2),"cost_units":round(cfg["fixed_service_cost_usd"]+nm*cfg["cost_per_teu_usd_per_nm"],2),"cost_method":"fixed_service_cost_usd + distance_nm*cost_per_teu_usd_per_nm","capacity_teu":cfg["capacity_teu"],"cargo_classes":cfg["cargo_classes"],"source_url":"https://github.com/eurostat/searoute","modeled_from_observed_ref":"","observed_movement_count":0,"commercial_service_claim":False}

def expand(base_dir=None,additional_pairs=100,additional_shipments=500,max_ports=50,seed=42,output=None):
    base=Path(base_dir or ROOT/"data/builds/research_1000");out=Path(output or ROOT/"data/builds/research_1500")
    if additional_pairs!=100 or additional_shipments!=500:raise ValueError("This expansion contract requires 100 additional edges and 500 shipments")
    if not 25<=max_ports<=50:raise ValueError("max-operational-ports must be between current 25 and 50")
    base_files={n:(base/n).read_bytes() for n in ("ports.json","services.json","shipments.json","route_plans.json","dataset_manifest.json")}
    base_hashes={n:hashlib.sha256(v).hexdigest() for n,v in base_files.items()}
    base_ports=json.loads(base_files["ports.json"]);base_services=json.loads(base_files["services.json"]);base_ships=json.loads(base_files["shipments.json"]);base_plans=json.loads(base_files["route_plans.json"])
    if len(base_ships)!=1000 or len(base_plans)!=1000:raise ValueError("Frozen base must contain exactly 1,000 shipments and plans")
    edges=read_edges(locate_csv(ROOT));endpoints=list(csv.DictReader((ROOT/"data/processed/selected_port_endpoints.csv").open(encoding="utf8",newline="")))
    demand,selected=audit_selection(edges,base_ships,endpoints,seed)
    require_quotas(demand)
    if demand["selected_us_bucket"]!=50 or demand["selected_china_bucket"]!=50:raise RuntimeError(f"Quota shortfall; eligible USA {demand['gateway_covered_us_candidates']}, China exclusive {demand['gateway_covered_china_exclusive_candidates']}")
    proc=ROOT/"data/processed";proc.mkdir(parents=True,exist_ok=True)
    (proc/"expansion_1500_demand_audit.json").write_text(json.dumps({**demand,"selected_edges":selected},sort_keys=True,indent=2)+"\n",encoding="utf8")
    current_catalog=list(csv.DictReader((ROOT/"data/reference/ports.csv").open(encoding="utf8",newline="")));catalog={p["port_id"]:p for p in current_catalog};pmap={p["port_id"]:p for p in base_ports}
    baseline_operational={v for s in base_services for v in (s["origin_port_id"],s["destination_port_id"])}
    base_country_port={}
    for e in endpoints:
        base_country_port.setdefault(normalize_country(e["supplier_country"]),e["origin_port_id"]);base_country_port.setdefault(normalize_country(e["customer_country"]),e["destination_port_id"])
    added_ids=[x for group in TARGET_PORTS.values() for x in group]
    missing=[x for x in added_ids if x not in catalog]
    if missing:raise ValueError("Missing official UN/LOCODE ports required for expansion: "+", ".join(missing))
    expanded_operational=baseline_operational|set(added_ids)
    check_port_limit(len(expanded_operational),max_ports)
    add_ports=[{**catalog[x],"verified":catalog[x]["verified"].lower()=="true","latitude":float(catalog[x]["latitude"]),"longitude":float(catalog[x]["longitude"])} for x in added_ids]
    (proc/"expansion_1500_port_selection_report.json").write_text(json.dumps({"baseline_operational_ports":len(baseline_operational),"added_us_ports":TARGET_PORTS["US"],"added_china_ports":TARGET_PORTS["CN"],"added_other_country_ports":[],"transshipment_only_ports":[],"added_operational_ports":len(added_ids),"total_operational_ports":len(expanded_operational),"maximum":max_ports,"reference_records_country_count":len({p["country_code"] for p in current_catalog}),"port_selection_rule":"Small set of well-known gateway-code candidates only where IDs exist in ingested UNECE 2025-1 records; UN/LOCODE maritime function is not container capability evidence.","rejected_candidates":missing,"gateway_assumption":"Country gateway proxy, not company facility; no inland location inference."},sort_keys=True,indent=2)+"\n",encoding="utf8")
    cfg=json.loads((ROOT/"config/maritime_network.json").read_text(encoding="utf8"));new_services=[]
    for bucket,portids in TARGET_PORTS.items():
        for portid in portids:
            for hub in TARGET_HUBS[bucket]:
                if hub not in pmap:raise ValueError(f"Existing hub {hub} missing from frozen port catalog")
                for a,b in ((portid,hub),(hub,portid)):new_services.append(make_service(a,b,{**pmap,portid:catalog[portid]},cfg))
    combined_services=base_services+new_services;service_ids=[s["service_id"] for s in combined_services]
    if len(service_ids)!=len(set(service_ids)):raise ValueError("Expansion produced duplicate service IDs")
    service_by_id={s["service_id"]:s for s in combined_services};combined_portmap={**pmap,**{p["port_id"]:p for p in add_ports}}
    # Match partner countries only to gateways from the frozen endpoint set.
    pair_endpoints=[]
    for r in selected:
        bucket=r["bucket"];a,b=r["supplier_country_code"],r["customer_country_code"]
        origin=a;dest=b
        if bucket=="US":
            target_idx=int(hashlib.sha256(f"{seed}:{r['supplier_edge_id']}".encode()).hexdigest()[:8],16)%len(TARGET_PORTS["US"])
            if origin=="US":op=TARGET_PORTS["US"][target_idx];dp=base_country_port.get(dest)
            else:op=base_country_port.get(origin);dp=TARGET_PORTS["US"][target_idx]
        else:
            target_idx=int(hashlib.sha256(f"{seed}:{r['supplier_edge_id']}".encode()).hexdigest()[:8],16)%len(TARGET_PORTS["CN"])
            if origin=="CN":op=TARGET_PORTS["CN"][target_idx];dp=base_country_port.get(dest)
            else:op=base_country_port.get(origin);dp=TARGET_PORTS["CN"][target_idx]
        if not op or not dp:raise ValueError(f"No gateway assignment for selected edge {r['supplier_edge_id']}: {origin}->{dest}")
        pair_endpoints.append({**r,"origin_port_id":op,"destination_port_id":dp,"origin_assumption":"country gateway model; not supplier facility","destination_assumption":"country gateway model; not customer facility"})
    ships=[];plans=[];rejected={}
    edge_source={stable_edge_id(e):e for e in edges}
    for pair in pair_endpoints:
        for repeat in range(5):
            n=len(ships)+1;sid=f"SHIP-EXP-{n:06d}";pid="PLAN-"+sid;srng=random.Random(f"{seed}:{pair['supplier_edge_id']}:{repeat}:expand")
            release=srng.randint(0,365);teu=srng.randint(1,4);route=schedule_path(pair["origin_port_id"],pair["destination_port_id"],combined_services,release,release+365,teu)
            if not route:rejected["no_feasible_route"] = rejected.get("no_feasible_route",0)+1;continue
            ids,legs,cost=route;arrival=legs[-1]["planned_arrival"];deadline=math.ceil(arrival+srng.choice([7,14,30]));source=edge_source[pair["supplier_edge_id"]]
            ships.append({"shipment_id":sid,"supplier_edge_id":pair["supplier_edge_id"],"source_supplier_edge_id":pair["supplier_edge_id"],"supplier":source["Supplier"],"customer":source["Customer"],"supplier_country":source["Supplier Country"],"customer_country":source["Customer Country"],"origin_port_id":pair["origin_port_id"],"destination_port_id":pair["destination_port_id"],"origin_assumption":pair["origin_assumption"],"destination_assumption":pair["destination_assumption"],"location_source_class":"MODELED_COUNTRY_GATEWAY","cargo_class":"GENERAL_CONTAINER","cargo_teu":teu,"priority":srng.choice(["LOW","STANDARD","HIGH"]),"release_time":release,"release_day":release,"delivery_deadline":deadline,"deadline_day":deadline,"route_plan_id":pid,"source_class":"SYNTHETIC_EXPANSION_SHIPMENT_FROM_ALMAHRI_SUPPLIESTO","expansion_bucket":pair["bucket"],"provenance":{"supplier_edge_id":pair["supplier_edge_id"],"upstream_csv_sha256":hashlib.sha256(locate_csv(ROOT).read_bytes()).hexdigest(),"expansion_seed":seed,"expansion_batch_edge_id":pair["supplier_edge_id"],"logistics":"modeled gateway and services"}})
            plans.append({"route_plan_id":pid,"plan_id":pid,"shipment_id":sid,"plan_version":1,"status":"INITIAL","service_ids":ids,"ordered_legs":legs,"transit_days":round(arrival-release,6),"estimated_arrival":arrival,"cost_units":round(cost,2),"total_cost_usd":round(cost,2),"source_class_counts":{c:sum(service_by_id[i]["source_class"]==c for i in ids) for c in sorted({service_by_id[i]["source_class"] for i in ids})}})
    if len(ships)!=500:raise RuntimeError(f"Generation failed: {len(ships)}/500 new shipments; rejected={rejected}")
    new_edge_ids={x["supplier_edge_id"] for x in selected};base_edge_ids={s["supplier_edge_id"] for s in base_ships}
    if new_edge_ids&base_edge_ids:raise ValueError("Expansion supplier edges overlap frozen 1,000 base")
    all_ships=base_ships+ships;all_plans=base_plans+plans
    # Keep base port records byte-equivalent as objects; append only newly required references.
    port_map={p["port_id"]:p for p in base_ports};
    for p in add_ports:
        port_map.setdefault(p["port_id"],p)
    all_ports=base_ports+[p for pid,p in port_map.items() if pid not in {q["port_id"] for q in base_ports}]
    if all_ships[:1000]!=base_ships or all_plans[:1000]!=base_plans or all_ports[:len(base_ports)]!=base_ports or combined_services[:len(base_services)]!=base_services:
        raise RuntimeError("Expansion changed frozen base canonical records")
    edge_ids={stable_edge_id(e) for e in edges}
    from maritime.data_validation import validate_records
    errors=validate_records(all_ports,combined_services,all_ships,all_plans,edge_ids,strict=True,expected_count=1500,original_edges={stable_edge_id(e):e for e in edges})
    if errors:raise ValueError("Combined dataset validation failed: "+"; ".join(errors[:30]))
    op_count=len({v for s in combined_services for v in (s["origin_port_id"],s["destination_port_id"])})
    check_port_limit(op_count,max_ports)
    out.mkdir(parents=True,exist_ok=True)
    files={"ports.json":all_ports,"services.json":combined_services,"shipments.json":all_ships,"route_plans.json":all_plans}
    for name,data in files.items():(out/name).write_text(json.dumps(data,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    newleg=sum(len(p["ordered_legs"]) for p in plans);legdist={str(n):sum(len(p["ordered_legs"])==n for p in plans) for n in sorted({len(p["ordered_legs"]) for p in plans})}
    hashes={n:hashlib.sha256((out/n).read_bytes()).hexdigest() for n in files}
    manifest={"generator_version":"2.1.0","seed":seed,"base_build":"research_1000","base_hashes_before":base_hashes,"base_hashes_after":{n:hashlib.sha256((base/n).read_bytes()).hexdigest() for n in base_files},"base_unchanged":base_hashes=={n:hashlib.sha256((base/n).read_bytes()).hexdigest() for n in base_files},"counts":{"base_shipments":len(base_ships),"additional_shipments":len(ships),"total_shipments":len(all_ships),"base_plans":len(base_plans),"additional_plans":len(plans),"total_plans":len(all_plans),"base_legs":sum(len(p.get("ordered_legs",[])) for p in base_plans),"additional_legs":newleg,"total_legs":sum(len(p.get("ordered_legs",[])) for p in all_plans),"base_operational_ports":len(baseline_operational),"additional_operational_ports":len(expanded_operational-baseline_operational),"total_operational_ports":op_count,"base_services":len(base_services),"additional_services":len(new_services),"total_services":len(combined_services),"distinct_base_edges":len(base_edge_ids),"distinct_new_edges":len(new_edge_ids),"distinct_total_edges":len(base_edge_ids|new_edge_ids)},"new_edge_buckets":{"US":sum(x["bucket"]=="US" for x in selected),"China":sum(x["bucket"]=="CN" for x in selected),"US_membership_including_overlap":sum(target_bucket(edge_source[x["supplier_edge_id"]])[0] for x in selected),"China_membership_including_overlap":sum(target_bucket(edge_source[x["supplier_edge_id"]])[1] for x in selected),"US_CN_overlap":sum(target_bucket(edge_source[x["supplier_edge_id"]])[0] and target_bucket(edge_source[x["supplier_edge_id"]])[1] for x in selected)},"new_shipments_by_bucket":{"US":sum(x["expansion_bucket"]=="US" for x in ships),"China":sum(x["expansion_bucket"]=="CN" for x in ships)},"new_shipments_involving_country":{"US":sum("US" in (normalize_country(x["supplier_country"]),normalize_country(x["customer_country"])) for x in ships),"China":sum("CN" in (normalize_country(x["supplier_country"]),normalize_country(x["customer_country"])) for x in ships)},"new_plan_leg_distribution":legdist,"validation_status":"passed","canonical_file_sha256":hashes,"rejections":rejected}
    (out/"dataset_manifest.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n",encoding="utf8")
    graph=nx.DiGraph();graph.add_nodes_from(expanded_operational);graph.add_edges_from((x["origin_port_id"],x["destination_port_id"]) for x in combined_services)
    selected_od={(x["origin_port_id"],x["destination_port_id"]) for x in pair_endpoints};connected=0;with_alt=0
    for a,b in sorted(selected_od):
        if not nx.has_path(graph,a,b):continue
        connected+=1
        try:
            paths=nx.shortest_simple_paths(graph,a,b);next(paths)
            try:next(paths);with_alt+=1
            except StopIteration:pass
        except (nx.NetworkXNoPath,nx.NodeNotFound):pass
    svc_report={"old_directed_services":len(base_services),"new_directed_services":len(new_services),"total_directed_services":len(combined_services),"ais_supported_service_count":sum(bool(x.get("modeled_from_observed_ref")) for x in combined_services),"modeled_service_count":sum("MODELED_SERVICE" in x.get("source_class","") for x in combined_services),"operational_ports":op_count,"base_operational_ports":len(baseline_operational),"new_operational_ports":op_count-len(baseline_operational),"service_ids_added":[x["service_id"] for x in new_services],"selected_new_od_port_pairs":len(selected_od),"selected_new_od_pairs_reachable":connected,"selected_new_od_pairs_with_alternative_path":with_alt,"directed_network_density":round(len(combined_services)/(op_count*(op_count-1)),5),"weakly_connected_components":nx.number_weakly_connected_components(graph),"distance_method":"SeaRoute 1.6.0 marine network; modeled availability only","ais_coverage_note":"No new observed AIS movements were used; old AIS references remain unchanged.","limitation":"AIS evidence remains separate from service availability; expansion corridors are synthetic modeled services."}
    (proc/"expansion_1500_service_network_report.json").write_text(json.dumps(svc_report,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print(json.dumps(manifest,indent=2));return manifest

if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--base-build",default=str(ROOT/"data/builds/research_1000"));ap.add_argument("--additional-pairs",type=int,default=100);ap.add_argument("--additional-shipments",type=int,default=500);ap.add_argument("--max-operational-ports",type=int,default=50);ap.add_argument("--seed",type=int,default=42);ap.add_argument("--output",default=str(ROOT/"data/builds/research_1500"));a=ap.parse_args()
    try:expand(a.base_build,a.additional_pairs,a.additional_shipments,a.max_operational_ports,a.seed,a.output)
    except Exception as e:print(f"ERROR: {e}",file=sys.stderr);sys.exit(2)
