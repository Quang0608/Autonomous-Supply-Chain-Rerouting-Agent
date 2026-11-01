"""Select original AlMahri edges and resolve port-level country gateway assumptions."""
import argparse,csv,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src"));sys.path.insert(0,str(ROOT/"scripts"))
from maritime.supplier import locate_csv,read_edges,choose_pairs
from ingest_unlocode_ports import COUNTRY_TO_ISO
PREF={"AU":"AUMEL","BR":"BRSSZ","CA":"","CN":"CNSGH","DE":"DEHAM","GB":"GBSOU","IN":"INNSA","JP":"JPYOK","KR":"KRPUS","VN":"VNSGN","SG":"SGSIN","ZA":"ZADUR","AR":"ARBUE","NL":"NLRTM","AE":"AEQWE","BE":"BEANR","DK":"DKAAR","FR":"FRLEH","IT":"ITGOA","ES":"ESVLC","SE":"SEGOT","NO":"NOOSL","MY":"MYPKG","TH":"THLCH","MX":""}
def stable_edge_id(r):return "EDGE-"+hashlib.sha256(json.dumps([r[k] for k in ("Supplier","Customer","Supplier Country","Customer Country","Supplier Industry","Customer Industry")],ensure_ascii=False,separators=(",",":")).encode()).hexdigest()[:16]
def main(pairs=500,seed=42,upstream=None,ports_file=None):
    edges=read_edges(locate_csv(ROOT,upstream));port_file=Path(ports_file or ROOT/"data/reference/ports.csv")
    ports=list(csv.DictReader(port_file.open(encoding="utf8",newline="")));bycc={}
    for p in ports:bycc.setdefault(p["country_code"],[]).append(p)
    selected,coverage=choose_pairs(edges,set(COUNTRY_TO_ISO),pairs,seed);endpoints=[];ineligible=[];matrix={}
    for r in selected:
        ids=[];resolved=[]
        for side,countrykey in (("origin","Supplier Country"),("destination","Customer Country")):
            country=r[countrykey];cc=COUNTRY_TO_ISO.get(country);cands=bycc.get(cc,[])
            pref=PREF.get(cc);p=next((x for x in cands if x["port_id"]==pref),None)
            if p is None and cands:p=sorted(cands,key=lambda x:(0 if any(w in x["name"].lower() for w in ("port","harbour","terminal")) else 1,x["port_id"]))[0]
            if p is None:ids=[];break
            ids.append(p["port_id"]);resolved.append(p)
        if len(ids)!=2 or ids[0]==ids[1]:
            ineligible.append({"supplier_edge_id":stable_edge_id(r),"supplier":r["Supplier"],"customer":r["Customer"],"reason":"missing country port candidate or same gateway"});continue
        row={"supplier_edge_id":stable_edge_id(r),"supplier":r["Supplier"],"customer":r["Customer"],"supplier_country":r["Supplier Country"],"customer_country":r["Customer Country"],"supplier_industry":r["Supplier Industry"],"customer_industry":r["Customer Industry"],"tier":r.get("tier",""),"linked_to_manufacturer":r.get("linked_to_manufacturer",False),"origin_port_id":ids[0],"destination_port_id":ids[1],"origin_port_name":resolved[0]["name"],"destination_port_name":resolved[1]["name"],"origin_iso2":resolved[0]["country_code"],"destination_iso2":resolved[1]["country_code"],"origin_assumption":"country-level gateway proxy; not a verified supplier facility","destination_assumption":"country-level gateway proxy; not a verified customer facility","source_class":"MODELED_COUNTRY_GATEWAY"}
        endpoints.append(row);key=f"{row['origin_iso2']}->{row['destination_iso2']}";m=matrix.setdefault(key,{"supplier_edge_count":0,"endpoint_port_pairs":set(),"manufacturer_linked_edges":0});m["supplier_edge_count"]+=1;m["endpoint_port_pairs"].add((ids[0],ids[1]));m["manufacturer_linked_edges"]+=bool(row["linked_to_manufacturer"])
    out=ROOT/"data/processed";out.mkdir(parents=True,exist_ok=True)
    with (out/"selected_port_endpoints.csv").open("w",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=list(endpoints[0]) if endpoints else ["supplier_edge_id"]);w.writeheader();w.writerows(endpoints)
    with (out/"selected_supplier_pairs.csv").open("w",newline="",encoding="utf8") as f:
        pairfields=["supplier_edge_id","Supplier","Customer","Supplier Country","Customer Country","Supplier Industry","Customer Industry","tier","linked_to_manufacturer"]
        w=csv.DictWriter(f,fieldnames=pairfields);w.writeheader();w.writerows([{"supplier_edge_id":r["supplier_edge_id"],"Supplier":r["supplier"],"Customer":r["customer"],"Supplier Country":r["supplier_country"],"Customer Country":r["customer_country"],"Supplier Industry":r["supplier_industry"],"Customer Industry":r["customer_industry"],"tier":r["tier"],"linked_to_manufacturer":r["linked_to_manufacturer"]} for r in endpoints])
    with (out/"ineligible_pairs.csv").open("w",newline="",encoding="utf8") as f:w=csv.DictWriter(f,fieldnames=["supplier_edge_id","supplier","customer","reason"]);w.writeheader();w.writerows(ineligible)
    for x in matrix.values():x["endpoint_port_pair_count"]=len(x["endpoint_port_pairs"]);x["endpoint_port_pairs"]=[list(p) for p in sorted(x["endpoint_port_pairs"])]
    report={"supplier_relationships_read":len(edges),"selected_candidate_edges":len(selected),"eligible_edges_with_port_assignments":len(endpoints),"ineligible_edges":len(ineligible),"ineligible_by_reason":{"missing country port candidate or same gateway":len(ineligible)},"manufacturer_selection_coverage":coverage,"distinct_endpoint_ports":len({x["origin_port_id"] for x in endpoints}|{x["destination_port_id"] for x in endpoints}),"demand_matrix":matrix,"selection_rule":"prefer configured country gateway UN/LOCODE if present; otherwise deterministic name/codelist order among maritime-function ports with published coordinates","limitations":["UN/LOCODE maritime function does not prove container capability","country port is a modeled gateway proxy and not a company facility"]}
    (out/"maritime_demand_audit.json").write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf8");print(json.dumps({k:v for k,v in report.items() if k!="demand_matrix"},indent=2));return endpoints
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--pairs",type=int,default=500);ap.add_argument("--seed",type=int,default=42);ap.add_argument("--upstream");ap.add_argument("--ports");a=ap.parse_args();main(a.pairs,a.seed,a.upstream,a.ports)
