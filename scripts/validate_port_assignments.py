"""Check that selected supplier countries resolve to sourced, coordinate-bearing ports."""
import argparse,csv,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src"));sys.path.insert(0,str(ROOT/"scripts"))
from maritime.supplier import locate_csv,read_edges,choose_pairs
from maritime.network import COUNTRY_PORT
from ingest_unlocode_ports import COUNTRY_TO_ISO

def validate(count,seed,upstream=None,ports_file=None):
    path=Path(ports_file) if ports_file else ROOT/"data/reference/ports.csv"
    with path.open(encoding="utf8",newline="") as f: ports=list(csv.DictReader(f))
    by_code={}
    for p in ports: by_code.setdefault(p["country_code"],[]).append(p)
    source=locate_csv(ROOT,upstream); edges=read_edges(source)
    selected,coverage=choose_pairs(edges,set(COUNTRY_PORT),count,seed)
    missing=[]; assignments=[]
    for e in selected:
        pair={}
        for side,key in (("origin","Supplier Country"),("destination","Customer Country")):
            code=COUNTRY_TO_ISO.get(e[key]); candidates=by_code.get(code,[]) if code else []
            candidates=[p for p in candidates if p.get("verified","").lower()=="true" and p.get("latitude") and p.get("longitude")]
            if not candidates:missing.append(f"{e[key]} has no verified coordinate-bearing UNECE port")
            else:pair[side]=sorted(candidates,key=lambda p:p["port_id"])[0]
        if len(pair)==2:
            a,b=pair["origin"],pair["destination"]
            assignments.append({"supplier":e["Supplier"],"customer":e["Customer"],"origin_port_id":a["port_id"],"origin_country_code":a["country_code"],"origin_latitude":a["latitude"],"origin_longitude":a["longitude"],"destination_port_id":b["port_id"],"destination_country_code":b["country_code"],"destination_latitude":b["latitude"],"destination_longitude":b["longitude"]})
    if missing: print("Invalid assignments:\n"+"\n".join(sorted(set(missing))),file=sys.stderr);return 1
    print(f"Port assignments valid: {len(assignments)} / {count}; every endpoint is a sourced coordinate-bearing port in the supplier/customer country.")
    print(f"Manufacturer-chain coverage: {coverage['selected_linked_to_manufacturer']} / {coverage['selected_pairs']}")
    return 0
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--shipments",type=int,default=20);ap.add_argument("--seed",type=int,default=42);ap.add_argument("--upstream");ap.add_argument("--ports-file");a=ap.parse_args()
    sys.exit(validate(a.shipments,a.seed,a.upstream,a.ports_file))
