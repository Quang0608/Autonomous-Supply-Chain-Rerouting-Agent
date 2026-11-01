"""Parse Zenodo AIS date-ship-port trip rows and conservatively map port names."""
import argparse,csv,datetime,hashlib,io,json,re,sys,urllib.request,urllib.error,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DOI="10.5281/zenodo.10783698"
URL="https://zenodo.org/records/10783698/files/triplet_2020.zip?download=1"
ATTRIBUTION="Duvallet, Kerné, Morel and Pigné, Date-Ship-Port triplet data based on AIS data, Zenodo v1 (2024), DOI 10.5281/zenodo.10783698"
MAX_BYTES=100_000_000

def fetch_cached(cache_file):
    path=Path(cache_file);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and 0<path.stat().st_size<=MAX_BYTES:return path.read_bytes()
    part=path.with_suffix(path.suffix+".part")
    for attempt in range(3):
        offset=part.stat().st_size if part.exists() else 0
        headers={"User-Agent":"maritime-reroute-agent/1.0"}
        if offset:headers["Range"]=f"bytes={offset}-"
        req=urllib.request.Request(URL,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=90) as response:
                append=offset and response.status==206
                if not append:offset=0
                mode="ab" if append else "wb"
                with part.open(mode) as f:
                    while True:
                        block=response.read(1024*1024)
                        if not block:break
                        f.write(block)
                        if f.tell()>MAX_BYTES:raise ValueError(f"AIS archive exceeds {MAX_BYTES} byte limit")
            part.replace(path);return path.read_bytes()
        except Exception:
            if attempt==2:raise
            time.sleep(2**attempt)
    raise RuntimeError("AIS download failed")

def norm(s):return re.sub(r"[^a-z0-9]","",(s or "").lower())
def parse_csv(stream,ports):
    # Only unique exact normalized names are mapped; ambiguous names are quarantined.
    by_name={}
    for p in ports:by_name.setdefault(norm(p.get("name")),[]).append(p)
    mapping={k:v[0] for k,v in by_name.items() if k and len({p["port_id"] for p in v})==1}
    counts={"rows":0,"bad_timestamp":0,"bad_vessel":0,"unmatched":0,"ambiguous":0,"invalid_duration":0,"implausible":0,"accepted":0}
    agg={}
    reader=csv.DictReader(io.TextIOWrapper(stream,encoding="utf-8-sig",errors="replace",newline=""),delimiter=";")
    required={"date-out","date-in","mmsi_imo_vessel_mame","PortName_from","PortName_to"}
    if not required.issubset(set(reader.fieldnames or [])):raise ValueError(f"Unexpected AIS schema; required fields missing: {sorted(required-set(reader.fieldnames or []))}")
    for r in reader:
        counts["rows"]+=1
        vessel=(r.get("mmsi_imo_vessel_mame") or "").strip()
        if not vessel or vessel.lower()=="nan":counts["bad_vessel"]+=1;continue
        try: start=datetime.datetime.fromisoformat(r["date-out"]);end=datetime.datetime.fromisoformat(r["date-in"])
        except (ValueError,TypeError):counts["bad_timestamp"]+=1;continue
        hours=(end-start).total_seconds()/3600
        if hours<=0:counts["invalid_duration"]+=1;continue
        if hours>720:counts["implausible"]+=1;continue
        names=[r.get("PortName_from"),r.get("PortName_to")]
        if any(not x or x.strip().lower()=="nan" for x in names):counts["unmatched"]+=1;continue
        ids=[]
        for name in names:
            candidates=by_name.get(norm(name),[])
            if len({p["port_id"] for p in candidates})>1:counts["ambiguous"]+=1;ids=[];break
            pid=mapping.get(norm(name),{}).get("port_id")
            if not pid:counts["unmatched"]+=1;ids=[];break
            ids.append(pid)
        if len(ids)!=2:continue
        if ids[0]==ids[1]:continue
        key=(ids[0],ids[1]);v=agg.setdefault(key,{"vessels":set(),"n":0,"hours":[]})
        v["vessels"].add(vessel);v["n"]+=1;v["hours"].append(hours);counts["accepted"]+=1
    return [{"observed_movement_id":f"AIS-{a}-{b}","origin_port_id":a,"destination_port_id":b,"movement_count":v["n"],"distinct_vessels":len(v["vessels"]),"mean_observed_elapsed_hours":round(sum(v["hours"])/len(v["hours"]),2),"observation_start":"2020-01-01","observation_end":"2020-12-31","source_class":"OBSERVED_AIS_MOVEMENT","vessel_type":"UNKNOWN_GENERAL_VESSEL","mapping_method":"unique exact normalized name to UN/LOCODE name","commercial_service_claim":False} for (a,b),v in sorted(agg.items())],counts

def main(input_path=None,download=False,ports_path=None,out_path=None,cache_path=None):
    ports=list(csv.DictReader(open(ports_path or ROOT/"data/reference/ports.csv",encoding="utf8",newline="")))
    if input_path:payload=Path(input_path).read_bytes();source_file=str(Path(input_path).resolve())
    elif download:
        payload=fetch_cached(cache_path or ROOT/"data/cache/triplet_2020.zip")
        source_file="downloaded from official Zenodo record/cache"
    else:raise ValueError("Provide --input or explicitly request --download")
    if len(payload)>MAX_BYTES:raise ValueError(f"AIS archive exceeds {MAX_BYTES} byte limit")
    z=zipfile.ZipFile(io.BytesIO(payload));entries=[x for x in z.namelist() if x.endswith("triplet_2020.csv")]
    if len(entries)!=1:raise ValueError("Expected exactly one triplet_2020.csv in archive")
    with z.open(entries[0]) as f:rows,counts=parse_csv(f,ports)
    out=Path(out_path or ROOT/"data/processed/observed_port_movements.csv");out.parent.mkdir(parents=True,exist_ok=True)
    fields=list(rows[0]) if rows else ["observed_movement_id","origin_port_id","destination_port_id","movement_count","distinct_vessels","mean_observed_elapsed_hours","observation_start","observation_end","source_class","vessel_type","mapping_method","commercial_service_claim"]
    with out.open("w",newline="",encoding="utf8") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    manifest={"doi":DOI,"url":URL,"attribution":ATTRIBUTION,"license":"Not declared in Zenodo record metadata; redistribution rights require confirmation; derived output is local research use only","access_date":datetime.date.today().isoformat(),"archive_sha256":hashlib.sha256(payload).hexdigest(),"archive_bytes":len(payload),"archive_entry":entries[0],"parser":"scripts/ingest_ais_port_calls.py","parser_parameters":{"delimiter":";","maximum_elapsed_hours":720,"mapping":"unique exact normalized port name; ambiguous/unmatched quarantined"},"counts":counts,"aggregated_directed_movements":len(rows),"source_file":source_file}
    (out.parent/"ais_ingestion_manifest.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print(json.dumps(manifest,indent=2));return manifest
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--input");ap.add_argument("--download",action="store_true");ap.add_argument("--cache");ap.add_argument("--ports");ap.add_argument("--output");a=ap.parse_args()
    try:main(a.input,a.download,a.ports,a.output,a.cache)
    except Exception as e:print(f"ERROR: {e}",file=sys.stderr);sys.exit(2)
