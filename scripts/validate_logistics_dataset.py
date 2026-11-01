"""Validate the canonical processed dataset; exits nonzero on integrity errors."""
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from maritime.supplier import locate_csv, read_edges
from maritime.data_validation import validate_records
import hashlib

def main(directory, upstream=None, strict=False):
    d=Path(directory)
    load=lambda n:json.loads((d/n).read_text(encoding="utf8"))
    ports,services,shipments,plans=[load(n) for n in ("ports.json","services.json","shipments.json","route_plans.json")]
    edges=read_edges(locate_csv(ROOT,upstream))
    edge_ids={"EDGE-"+hashlib.sha256(json.dumps([r[k] for k in ("Supplier","Customer","Supplier Country","Customer Country","Supplier Industry","Customer Industry")],ensure_ascii=False,separators=(",",":")).encode()).hexdigest()[:16] for r in edges}
    edge_map={"EDGE-"+hashlib.sha256(json.dumps([r[k] for k in ("Supplier","Customer","Supplier Country","Customer Country","Supplier Industry","Customer Industry")],ensure_ascii=False,separators=(",",":")).encode()).hexdigest()[:16]:r for r in edges}
    manifest=load("dataset_manifest.json")
    expected=manifest.get("counts",{}).get("shipments")
    errors=validate_records(ports,services,shipments,plans,edge_map,strict,expected,edge_map)
    if strict and expected==1000 and len(shipments)!=1000:errors.append("Target build must contain exactly 1,000 shipments")
    if errors:
        print("Dataset invalid:"); print("\n".join("- "+e for e in errors)); return 1
    report={"validation_status":"passed","ports":len(ports),"services":len(services),"shipments":len(shipments),"route_plans":len(plans),"planned_legs":sum(len(p.get("ordered_legs",[])) for p in plans)}
    (d/"validation_report.json").write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print(f"Dataset valid: {len(ports)} ports, {len(services)} services, {len(shipments)} shipments, {report['planned_legs']} planned legs")
    return 0
if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--directory",default=str(ROOT/"data"/"processed")); ap.add_argument("--upstream"); ap.add_argument("--strict",action="store_true"); a=ap.parse_args()
    try: sys.exit(main(a.directory,a.upstream,a.strict))
    except (ValueError,FileNotFoundError,KeyError) as e: print(f"ERROR: {e}",file=sys.stderr); sys.exit(2)
