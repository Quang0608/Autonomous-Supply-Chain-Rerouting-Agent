"""Generate canonical, deterministic synthetic shipment and initial-plan records."""
from __future__ import annotations
import argparse,csv,hashlib,json,random,subprocess,sys,math
from pathlib import Path
import heapq
from collections import defaultdict,deque
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src"));sys.path.insert(0,str(ROOT/"scripts"))
from maritime.supplier import locate_csv,read_edges,choose_pairs
from maritime.data_validation import validate_records
from audit_maritime_demand import main as audit,stable_edge_id
from maritime.network import COUNTRY_PORT,build_network,shortest_path
VERSION="2.0.0"

def next_departure(t,frequency):return math.ceil((t-1e-12)/frequency)*frequency
def schedule_path(origin,destination,services,release_day,deadline_day,cargo_teu):
    adjacency={}
    for s in services:adjacency.setdefault(s["origin_port_id"],[]).append(s)
    # Deterministic cost-first bounded path search. Each candidate path is
    # scheduled leg-by-leg and rejected if it misses the hard deadline.
    q=[(0.0,(),origin,[])];visited=set();max_legs=5
    while q:
        cost,ids,node,legs=heapq.heappop(q)
        if node==destination and ids:
            if legs[-1]["planned_arrival"]<=deadline_day:return list(ids),legs,cost
            continue
        if len(ids)>=max_legs:continue
        state=(node,ids)
        if state in visited:continue
        visited.add(state)
        available=release_day if not legs else legs[-1]["planned_arrival"]+float(legs[-1]["min_transfer_hours"])/24
        for s in sorted(adjacency.get(node,[]),key=lambda x:x["service_id"]):
            nxt=s["destination_port_id"]
            if nxt in [origin]+[x["destination_port_id"] for x in legs]:continue
            dep=next_departure(available,float(s["departure_frequency_days"]))
            arr=dep+float(s["transit_days"])
            leg={"sequence":len(legs)+1,"service_id":s["service_id"],"origin_port_id":node,"destination_port_id":nxt,"planned_departure":round(dep,6),"planned_arrival":round(arr,6),"modeled_cost_usd":round(float(s["cost_per_teu_usd"])*cargo_teu,2),"min_transfer_hours":float(s["min_transfer_hours"])}
            edge_cost=leg["modeled_cost_usd"]
            heapq.heappush(q,(cost+edge_cost,ids+(s["service_id"],),nxt,legs+[leg]))
    return None

def build(mode="strict",shipments_count=20,seed=42,upstream=None,reference_dir=None,out_dir=None,allow_modeled_services=False):
    if mode=="synthetic-dev":return build_synthetic_dev(shipments_count,seed,upstream,out_dir)
    if mode!="strict":raise ValueError("mode must be strict or synthetic-dev")
    if shipments_count<1:raise ValueError("shipments must be positive")
    ref=Path(reference_dir) if reference_dir else ROOT/"data/reference";out=Path(out_dir) if out_dir else ROOT/"data/processed"
    source=locate_csv(ROOT,upstream);edges=read_edges(source);refports=list(csv.DictReader((ref/"ports.csv").open(encoding="utf8",newline="")))
    ports=[{**p,"latitude":float(p["latitude"]),"longitude":float(p["longitude"]),"verified":p["verified"].lower()=="true"} for p in refports]
    servicefile=ref/"service_connections.csv"
    if not servicefile.exists():raise FileNotFoundError(f"Missing {servicefile}; run build_service_network.py --allow-modeled-services")
    if not allow_modeled_services:raise ValueError("Modeled services require explicit --allow-modeled-services")
    with servicefile.open(encoding="utf8",newline="") as f:services=list(csv.DictReader(f))
    for s in services:
        for field in ("transit_days","distance_nm","cost_per_teu_usd","departure_frequency_days","min_transfer_hours","capacity_teu","vessel_speed_knots","port_handling_days"):s[field]=float(s[field])
        s["direction"]="DIRECTED";s["cost_units"]=s["cost_per_teu_usd"]
        try:s["cargo_classes"]=json.loads(s["cargo_classes"])
        except (TypeError,json.JSONDecodeError):pass
    endpoint_file=ROOT/"data/processed/selected_port_endpoints.csv"
    if not endpoint_file.exists():audit(max(500,shipments_count//2),seed,upstream,ref/"ports.csv")
    with endpoint_file.open(encoding="utf8",newline="") as f:endpoints=list(csv.DictReader(f))
    endpoint_by_edge={r["supplier_edge_id"]:r for r in endpoints}
    original={stable_edge_id(r):r for r in edges}
    candidates=[(eid,row) for eid,row in sorted(endpoint_by_edge.items()) if eid in original]
    if not candidates:raise ValueError("No source-verified supplier edges have port endpoints")
    rng=random.Random(seed);rng.shuffle(candidates)
    max_per_edge=2;needed=math.ceil(shipments_count/max_per_edge)
    if len(candidates)<needed:raise ValueError(f"Only {len(candidates)} eligible direct edges; need {needed} at max {max_per_edge} shipments/edge")
    candidates=candidates[:needed]
    portmap={p["port_id"]:p for p in ports};service_by_id={s["service_id"]:s for s in services}
    if any(s["source_class"].startswith("MODELED") for s in services) and not allow_modeled_services:raise ValueError("Modeled links present without explicit opt-in")
    ships=[];plans=[];rejections={};eid_counts={}
    for eid,ep in candidates:
        if len(ships)>=shipments_count:break
        for repeat in range(max_per_edge):
            if len(ships)>=shipments_count:break
            sid=f"SHIP-{len(ships)+1:06d}";pid="PLAN-"+sid
            # Stable independent per-shipment RNG avoids order coupling.
            srng=random.Random(f"{seed}:{eid}:{repeat}");release=srng.randint(0,365);teu=srng.randint(1,4);priority=srng.choice(["STANDARD","HIGH","LOW"])
            nominal=schedule_path(ep["origin_port_id"],ep["destination_port_id"],services,release,release+180,teu)
            if not nominal:rejections["no_feasible_itinerary_or_deadline"] = rejections.get("no_feasible_itinerary_or_deadline",0)+1;continue
            service_ids,legs,cost=nominal;arrival=legs[-1]["planned_arrival"];deadline=math.ceil(arrival+srng.choice([7,14,30]))
            source_edge=original[eid];ships.append({"shipment_id":sid,"supplier_edge_id":eid,"source_supplier_edge_id":eid,"supplier":source_edge["Supplier"],"customer":source_edge["Customer"],"supplier_country":source_edge["Supplier Country"],"customer_country":source_edge["Customer Country"],"origin_port_id":ep["origin_port_id"],"destination_port_id":ep["destination_port_id"],"origin_assumption":ep["origin_assumption"],"destination_assumption":ep["destination_assumption"],"location_source_class":"MODELED_COUNTRY_GATEWAY","cargo_class":"GENERAL_CONTAINER","cargo_teu":teu,"priority":priority,"release_time":release,"release_day":release,"delivery_deadline":deadline,"deadline_day":deadline,"source_class":"SYNTHETIC_SHIPMENT_FROM_ALMAHRI_SUPPLIESTO","route_plan_id":pid,"provenance":{"supplier_edge_id":eid,"upstream_csv_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"logistics":"modeled services; no facility inference"}})
            plans.append({"route_plan_id":pid,"plan_id":pid,"shipment_id":sid,"plan_version":1,"status":"INITIAL","service_ids":service_ids,"ordered_legs":legs,"transit_days":round(arrival-release,6),"estimated_arrival":arrival,"cost_units":round(cost,2),"total_cost_usd":round(cost,2),"source_class_counts":{c:sum(service_by_id[i]["source_class"]==c for i in service_ids) for c in sorted({service_by_id[i]["source_class"] for i in service_ids})}})
            eid_counts[eid]=eid_counts.get(eid,0)+1
    if len(ships)!=shipments_count:raise RuntimeError(f"Generation stopped at {len(ships)}/{shipments_count}; rejected: {rejections}")
    edges_by_id=set(original)
    errors=validate_records(ports,services,ships,plans,edges_by_id,strict=True,expected_count=shipments_count,original_edges=original)
    if errors:raise ValueError("Dataset validation failed: "+"; ".join(errors))
    out.mkdir(parents=True,exist_ok=True)
    files={"ports.json":ports,"services.json":services,"shipments.json":ships,"route_plans.json":plans}
    for name,data in files.items():(out/name).write_text(json.dumps(data,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    counts={"supplier_relationships":len(edges),"ports_reference":len(refports),"operational_ports":len({p for s in services for p in (s["origin_port_id"],s["destination_port_id"])}),"services":len(services),"observed_movements":len(list(csv.DictReader((ROOT/"data/processed/observed_port_movements.csv").open(encoding="utf8")))) if (ROOT/"data/processed/observed_port_movements.csv").exists() else 0,"shipments":len(ships),"route_plans":len(plans),"planned_legs":sum(len(p["ordered_legs"]) for p in plans),"distinct_supplier_edges":len(eid_counts)}
    shas={n:hashlib.sha256((out/n).read_bytes()).hexdigest() for n in files}
    manifest={"generator_version":VERSION,"git_commit":_git_commit(),"seed":seed,"mode":"strict","modeled_services_opt_in":True,"counts":counts,"source_checksums":{"almahri_csv_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"ports_csv_sha256":hashlib.sha256((ref/"ports.csv").read_bytes()).hexdigest(),"service_connections_sha256":hashlib.sha256(servicefile.read_bytes()).hexdigest()},"ais_doi":"10.5281/zenodo.10783698","ais_archive_sha256":json.loads((ROOT/"data/processed/ais_ingestion_manifest.json").read_text()).get("archive_sha256") if (ROOT/"data/processed/ais_ingestion_manifest.json").exists() else None,"unece_release":"2025-1","network_model":json.loads((ROOT/"config/maritime_network.json").read_text()),"supplier_edge_concentration":{"top_10_share":round(sum(sorted(eid_counts.values(),reverse=True)[:10])/len(ships),4),"median_shipments_per_edge":2,"max_shipments_per_edge":max(eid_counts.values())},"manufacturer_coverage":_target_edge_coverage(edges,ships),"shipment_distributions":{"cargo_teu":{str(n):sum(x["cargo_teu"]==n for x in ships) for n in sorted({x["cargo_teu"] for x in ships})},"priority":{k:sum(x["priority"]==k for x in ships) for k in sorted({x["priority"] for x in ships})},"country_pairs":len({(x["supplier_country"],x["customer_country"]) for x in ships}),"initial_plan_validity":1.0,"arrival_deadline_pass_rate":1.0},"source_class_breakdown":{"planned_legs":{c:sum(n for p in plans for sc,n in p["source_class_counts"].items() if sc==c) for c in sorted({sc for p in plans for sc in p["source_class_counts"]})},"services":{c:sum(s["source_class"]==c for s in services) for c in sorted({s["source_class"] for s in services})}},"canonical_file_sha256":shas,"validation_status":"passed","rejections":rejections}
    (out/"dataset_manifest.json").write_text(json.dumps(manifest,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return manifest

def build_synthetic_dev(count,seed,upstream,out_dir):
    """Backward-compatible prior Phase 2 prototype pipeline."""
    source=locate_csv(ROOT,upstream);edges=read_edges(source);selected,coverage=choose_pairs(edges,set(COUNTRY_PORT),max(count,15),seed)
    ports,graph=build_network();rng=random.Random(seed);ships=[];plans=[]
    for pair in selected:
        if len(ships)>=count:break
        a=COUNTRY_PORT[pair["Supplier Country"]][0];b=COUNTRY_PORT[pair["Customer Country"]][0]
        route=shortest_path(a,b,graph)
        if not route:continue
        sid=f"SHIP-{len(ships)+1:04d}";pid="PLAN-"+sid;teu=rng.randint(1,3)
        ships.append({"shipment_id":sid,"supplier_edge_id":stable_edge_id(pair),"supplier":pair["Supplier"],"customer":pair["Customer"],"supplier_country":pair["Supplier Country"],"customer_country":pair["Customer Country"],"cargo_class":"GENERAL_CONTAINER_SYNTHETIC","release_day":0,"deadline_day":int(route["transit_days"]+14),"cargo_teu":teu,"original_route":route,"route_plan_id":pid,"source_class":"SYNTHETIC_SHIPMENT_FROM_ALMAHRI_SUPPLIESTO"})
        plans.append({"route_plan_id":pid,"shipment_id":sid,"service_ids":[f"SVC-{x}-{y}" for x,y in zip(route["ports"],route["ports"][1:])],"transit_days":route["transit_days"],"cost_units":route["cost_units"]})
    if len(ships)!=count:raise RuntimeError(f"Legacy synthetic-dev generated {len(ships)}/{count} shipments")
    out=Path(out_dir) if out_dir else ROOT/"data/processed";out.mkdir(parents=True,exist_ok=True)
    data={"ports.json":list(ports.values()),"services.json":[{"service_id":f"SVC-{a}-{b}","origin_port_id":a,"destination_port_id":b,"direction":"DIRECTED","transit_days":v["transit_days"],"cost_units":v["cost_units"],"source_class":v["source_class"],"source_reference":"legacy network.py"} for (a,b),v in sorted(graph.items())],"shipments.json":ships,"route_plans.json":plans}
    for n,v in data.items():(out/n).write_text(json.dumps(v,sort_keys=True,indent=2)+"\n",encoding="utf8")
    manifest={"generator_version":VERSION,"mode":"synthetic-dev","seed":seed,"counts":{"supplier_relationships":len(edges),"ports":len(ports),"services":len(graph),"shipments":len(ships),"route_plans":len(plans)},"selection_coverage":coverage,"validation_status":"legacy smoke only"}
    (out/"dataset_manifest.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n",encoding="utf8")
    return manifest

def _git_commit():
    try:return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
    except Exception:return None

def _target_edge_coverage(edges,shipments):
    suppliers=defaultdict(set)
    for r in edges:suppliers[r["Customer"]].add(r["Supplier"])
    targets={"BMW":("BMW AG","BMW Group","BMW Brilliance Automotive Ltd"),"Mercedes-Benz":("Mercedes-Benz Group AG",),"Tesla":("Tesla Inc",)}
    result={}
    for label,names in targets.items():
        depth={n:0 for n in names};q=deque(names)
        while q:
            c=q.popleft()
            if depth[c]>=4:continue
            for s in sorted(suppliers[c]):
                if s not in depth:depth[s]=depth[c]+1;q.append(s)
        eids={stable_edge_id(r) for r in edges if r["Supplier"] in depth and r["Customer"] in depth and depth[r["Supplier"]]==depth[r["Customer"]]+1}
        represented={x["supplier_edge_id"] for x in shipments}
        result[label]={"source_graph_edges_within_four_tiers":len(eids),"represented_direct_edges":len(eids & represented),"generated_shipments":sum(x["supplier_edge_id"] in eids for x in shipments)}
    return result
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--upstream");ap.add_argument("--seed",type=int,default=42);ap.add_argument("--shipments",type=int,default=20);ap.add_argument("--mode",choices=["strict","synthetic-dev"],default="strict");ap.add_argument("--reference-dir");ap.add_argument("--out-dir");ap.add_argument("--allow-modeled-services",action="store_true");a=ap.parse_args()
    try:print(json.dumps(build(a.mode,a.shipments,a.seed,a.upstream,a.reference_dir,a.out_dir,a.allow_modeled_services),indent=2))
    except Exception as e:print(f"ERROR: {e}",file=sys.stderr);sys.exit(2)
