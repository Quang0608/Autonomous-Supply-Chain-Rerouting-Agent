"""Ingest UNECE UN/LOCODE 2025-1 port locations; no coordinate inference."""
import argparse, csv, datetime, hashlib, io, json, re, sys, urllib.request, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from maritime.supplier import locate_csv, read_edges, choose_pairs
from maritime.network import COUNTRY_PORT

SOURCE_URL="https://opensource.unicc.org/un/unece/uncefact/vocab-locode/-/jobs/artifacts/2025-1/download?job=package-release"
VERSION="2025-1"
LICENSE="CC BY 4.0 (UN/CEFACT standards; confirm source-specific terms before redistribution)"
COUNTRY_TO_ISO={"Argentina":"AR","Australia":"AU","Belgium":"BE","Brazil":"BR","Canada":"CA","China":"CN","Denmark":"DK","France":"FR","Germany":"DE","India":"IN","Italy":"IT","Japan":"JP","Malaysia":"MY","Mexico":"MX","Netherlands":"NL","Norway":"NO","Singapore":"SG","South Africa":"ZA","South Korea":"KR","Republic of Korea":"KR","Spain":"ES","Sweden":"SE","Thailand":"TH","United Arab Emirates":"AE","United Kingdom":"GB","Vietnam":"VN","United States":"US","United States of America":"US","USA":"US"}
HEADERS=["change","country_code","location_code","name","name_ascii","subdivision","function","status","date","iata","coordinates","remarks"]

def parse_coordinates(value):
    m=re.fullmatch(r"(\d{2})(\d{2})([NS]) (\d{3})(\d{2})([EW])",(value or "").strip())
    if not m:return None,None
    lat=int(m[1])+int(m[2])/60; lon=int(m[4])+int(m[5])/60
    if m[3]=="S":lat=-lat
    if m[6]=="W":lon=-lon
    if not (-90<=lat<=90 and -180<=lon<=180):return None,None
    return round(lat,6),round(lon,6)

def convert(archive_bytes, selected_countries, retrieved_date):
    z=zipfile.ZipFile(io.BytesIO(archive_bytes)); records=[]; country_names={}; missing_coords=0
    parts=[n for n in z.namelist() if re.search(r"UNLOCODE CodeListPart[123]\.csv$",n)]
    if len(parts)!=3: raise ValueError("UNECE archive must contain all three official codelist CSV parts")
    for name in sorted(parts):
        text=z.read(name).decode("utf-8-sig",errors="replace")
        for row in csv.reader(io.StringIO(text)):
            if len(row)<12:continue
            row=(row+([""]*12))[:12]
            _,cc,loc,nm,ascii_name,subdiv,func,status,_,_,coord,_=row
            if cc and not loc and nm.startswith("."):
                country_names[cc]=nm[1:].strip().title();continue
            if not cc or not loc or not nm.strip():continue
            if not func.startswith("1"):continue
            lat,lon=parse_coordinates(coord)
            if lat is None or lon is None:missing_coords+=1;continue
            records.append((cc,loc,nm.strip(),lat,lon,status.strip(),name))
    codes={iso for c in selected_countries if (iso:=COUNTRY_TO_ISO.get(c))}
    unknown=sorted(set(selected_countries)-set(COUNTRY_TO_ISO))
    if unknown: raise ValueError("No verified ISO mapping configured for selected supplier countries: "+", ".join(unknown))
    out=[]
    for cc,loc,name,lat,lon,status,part in records:
        if cc not in codes:continue
        out.append({"port_id":cc+loc,"name":name,"country":country_names.get(cc,cc),"latitude":lat,"longitude":lon,"source":"UNECE UN/LOCODE","source_reference":f"{VERSION}:{part}","verified":True,"source_class":"REFERENCE_PORT","country_code":cc,"location_code":loc,"source_url":SOURCE_URL,"dataset_version":VERSION,"retrieved_date":retrieved_date,"license":LICENSE})
    out.sort(key=lambda p:(p["country_code"],p["port_id"],p["name"],p["source_reference"]))
    unique={}
    for p in out:unique.setdefault(p["port_id"],p)
    return list(unique.values()),{"selected_country_codes":sorted(codes),"selected_countries":sorted(selected_countries),"matched_port_rows":len(out),"matched_ports":len(unique),"duplicate_port_id_rows_removed":len(out)-len(unique),"maritime_entries_missing_coordinates_in_source":missing_coords,"unmatched_country_codes":sorted(codes-{r["country_code"] for r in out})}

def ingest(upstream=None, seed=42, count=20, archive_path=None, output=None, include_countries=None):
    source=locate_csv(ROOT,upstream); edges=read_edges(source)
    countries=set(COUNTRY_PORT)
    chosen,coverage=choose_pairs(edges,countries,count,seed)
    selected={x[k] for x in chosen for k in ("Supplier Country","Customer Country")}
    today=datetime.date.today().isoformat()
    if archive_path:
        payload=Path(archive_path).read_bytes(); source_url=SOURCE_URL
    else:
        req=urllib.request.Request(SOURCE_URL,headers={"User-Agent":"maritime-reroute-agent/1.0"})
        with urllib.request.urlopen(req,timeout=60) as response:payload=response.read()
        source_url=SOURCE_URL
    selected.update(include_countries or [])
    ports,report=convert(payload,selected,today)
    for p in ports:p["source_url"]=source_url
    report.update({"dataset_version":VERSION,"retrieved_date":today,"license":LICENSE,"archive_sha256":hashlib.sha256(payload).hexdigest(),"supplier_coverage":coverage})
    dest=Path(output) if output else ROOT/"data"/"reference"/"ports.csv"
    dest.parent.mkdir(parents=True,exist_ok=True)
    fields=["port_id","name","country","latitude","longitude","source","source_reference","verified","source_class","country_code","location_code","source_url","dataset_version","retrieved_date","license"]
    with dest.open("w",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(ports)
    (dest.parent/"ports_ingestion_manifest.json").write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print(json.dumps(report,indent=2));return report

if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--upstream");ap.add_argument("--seed",type=int,default=42);ap.add_argument("--shipments",type=int,default=20);ap.add_argument("--archive");ap.add_argument("--output");ap.add_argument("--include-country",action="append",default=[]);a=ap.parse_args()
    try:ingest(a.upstream,a.seed,a.shipments,a.archive,a.output,a.include_country)
    except Exception as e:print(f"ERROR: {e}",file=sys.stderr);sys.exit(2)
