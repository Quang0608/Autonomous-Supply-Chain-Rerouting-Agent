"""Create demand-driven modeled maritime corridors using SeaRoute distances."""
import argparse,csv,hashlib,json,sys
from pathlib import Path
import networkx as nx
ROOT=Path(__file__).resolve().parents[1]
try:import searoute
except ImportError:searoute=None

def build(seed=42,allow_modeled=False,ports_path=None,endpoints_path=None,ais_path=None,reference_path=None):
    if not allow_modeled:raise ValueError("No fully verified liner-service file is present. Pass --allow-modeled-services to explicitly build modeled services.")
    if searoute is None:raise RuntimeError("Install searoute==1.6.0 to calculate navigable maritime distance")
    portsfile=Path(ports_path or ROOT/"data/reference/ports.csv");epfile=Path(endpoints_path or ROOT/"data/processed/selected_port_endpoints.csv");
    ports=list(csv.DictReader(portsfile.open(encoding="utf8",newline="")));endpoints=list(csv.DictReader(epfile.open(encoding="utf8",newline="")));pmap={p["port_id"]:p for p in ports}
    cfg=json.loads((ROOT/"config/maritime_network.json").read_text(encoding="utf8")); operational={e[k] for e in endpoints for k in ("origin_port_id","destination_port_id")}
    hubs=[h for h in cfg["hubs"] if h in pmap];operational.update(hubs)
    regions={"Asia":{"CN","JP","KR","VN","IN","MY","SG","TH"},"Europe":{"DE","GB","BE","DK","FR","IT","NL","NO","ES","SE"},"Middle East":{"AE"},"Africa":{"ZA"},"South America":{"AR","BR"},"Oceania":{"AU"},"North America":{"CA","MX","US"}}
    regional={"Asia":"SGSIN","Europe":"NLRTM","Middle East":"AEQWE","Africa":"ZADUR","South America":"ARBUE","Oceania":"SGSIN","North America":"NLRTM"}
    country_hub={cc:regional[r] for r,codes in regions.items() for cc in codes}
    pairs=set()
    for e in endpoints:
        for portkey,cckey in (("origin_port_id","origin_iso2"),("destination_port_id","destination_iso2")):
            h=country_hub.get(e[cckey]);p=e[portkey]
            if h in pmap and h!=p:pairs.add((p,h));pairs.add((h,p))
    backbone=[("SGSIN","AEQWE"),("AEQWE","NLRTM"),("SGSIN","ZADUR"),("ZADUR","ARBUE"),("ARBUE","NLRTM"),("ZADUR","NLRTM")]
    for a,b in backbone:
        if a in pmap and b in pmap:pairs.update(((a,b),(b,a)))
    obs={}
    ap=Path(ais_path or ROOT/"data/processed/observed_port_movements.csv")
    if ap.exists():
        with ap.open(encoding="utf8",newline="") as f:
            for r in csv.DictReader(f):
                a,b=r["origin_port_id"],r["destination_port_id"]
                if a in operational and b in operational and a!=b:
                    obs[(a,b)]=r
                    pairs.add((a,b))
    services=[];failures=[]
    for a,b in sorted(pairs):
        try:
            route=searoute.searoute([float(pmap[a]["longitude"]),float(pmap[a]["latitude"])],[float(pmap[b]["longitude"]),float(pmap[b]["latitude"])],units="naut",speed_knot=cfg["vessel_speed_knots"])
            nm=float(route["properties"]["length"])
            if nm<=0:raise ValueError("nonpositive SeaRoute length")
        except Exception as ex:failures.append({"origin":a,"destination":b,"reason":str(ex)});continue
        movement=obs.get((a,b));sid="SVC-"+hashlib.sha256(f"{a}>{b}".encode()).hexdigest()[:14]
        days=nm/(24*cfg["vessel_speed_knots"])+cfg["port_handling_days"]
        services.append({"service_id":sid,"origin_port_id":a,"destination_port_id":b,"direction":"DIRECTED","service_evidence":"Explicit modeled corridor; SeaRoute only supplies navigable distance, not service evidence","source_reference":"config/maritime_network.json; SeaRoute 1.6.0"+("; Zenodo AIS DOI 10.5281/zenodo.10783698" if movement else ""),"source_version":"searoute==1.6.0","source_class":"MODELED_SERVICE_FROM_AIS" if movement else "MODELED_SERVICE","distance_nm":round(nm,3),"distance_method":"SeaRoute maritime network, nautical miles","transit_days":round(days,4),"transit_method":"distance_nm/(24*vessel_speed_knots)+port_handling_days","vessel_speed_knots":cfg["vessel_speed_knots"],"port_handling_days":cfg["port_handling_days"],"departure_frequency_days":cfg["departure_frequency_days"],"min_transfer_hours":cfg["minimum_transfer_hours"],"cost_per_teu_usd":round(cfg["fixed_service_cost_usd"]+nm*cfg["cost_per_teu_usd_per_nm"],2),"cost_method":"fixed_service_cost_usd + distance_nm*cost_per_teu_usd_per_nm","capacity_teu":cfg["capacity_teu"],"cargo_classes":json.dumps(cfg["cargo_classes"]),"source_url":"https://github.com/eurostat/searoute","modeled_from_observed_ref":movement["observed_movement_id"] if movement else "","observed_movement_count":int(movement["movement_count"]) if movement else 0,"commercial_service_claim":False})
    out=Path(reference_path) if reference_path else ROOT/"data/reference/service_connections.csv";out.parent.mkdir(parents=True,exist_ok=True)
    fields=list(services[0]) if services else []
    with out.open("w",newline="",encoding="utf8") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(services)
    g=nx.DiGraph();g.add_nodes_from(operational);g.add_edges_from((s["origin_port_id"],s["destination_port_id"]) for s in services)
    demand_pairs={(e["origin_port_id"],e["destination_port_id"]) for e in endpoints};alt=0;connected=0
    for a,b in sorted(demand_pairs):
        if nx.has_path(g,a,b):
            connected+=1
            try:
                gen=nx.shortest_simple_paths(g,a,b)
                next(gen)
                try:next(gen);alt+=1
                except StopIteration:pass
            except (nx.NetworkXNoPath,nx.NodeNotFound):pass
    report={"operational_port_count":len(operational),"endpoint_ports":len({e[k] for e in endpoints for k in ("origin_port_id","destination_port_id")}),"transshipment_ports":sorted(set(hubs)-{e[k] for e in endpoints for k in ("origin_port_id","destination_port_id")}),"modeled_services":len(services),"ais_movement_backed_modeled_services":sum(bool(s["modeled_from_observed_ref"]) for s in services),"observed_movement_records_input":len(obs),"demand_country_pairs":len(demand_pairs),"demand_pairs_connected":connected,"demand_pairs_with_alternative_path":alt,"weakly_connected_components":nx.number_weakly_connected_components(g),"failed_searoute_pairs":failures,"source_class_counts":{c:sum(s["source_class"]==c for s in services) for c in sorted({s["source_class"] for s in services})},"model_parameters":cfg,"distance_model":"SeaRoute maritime network (not commercial service evidence)","ais_license_notice":"Zenodo record did not declare license; AIS movements are evidence-only and not included as service schedules."}
    (ROOT/"data/processed/service_network_report.json").write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print(json.dumps({k:v for k,v in report.items() if k!="failed_searoute_pairs"},indent=2));return report
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--allow-modeled-services",action="store_true");ap.add_argument("--seed",type=int,default=42);ap.add_argument("--ports");ap.add_argument("--endpoints");ap.add_argument("--ais");ap.add_argument("--reference-output");a=ap.parse_args()
    try:build(a.seed,a.allow_modeled_services,a.ports,a.endpoints,a.ais,a.reference_output)
    except Exception as e:print(f"ERROR: {e}",file=sys.stderr);sys.exit(2)
