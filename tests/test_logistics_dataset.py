import csv, json, tempfile, unittest
import io
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
from build_logistics_dataset import build
from maritime.data_validation import validate_records
from ingest_unlocode_ports import parse_coordinates
from ingest_ais_port_calls import parse_csv

class LogisticsDatasetTests(unittest.TestCase):
    def test_unlocode_coordinate_normalization(self):
        self.assertEqual(parse_coordinates("4230N 00131E"),(42.5,1.516667))
        self.assertEqual(parse_coordinates("1651S 04203W"),(-16.85,-42.05))
        self.assertEqual(parse_coordinates(""),(None,None))

    def test_ais_parser_maps_only_unique_exact_port_names(self):
        ports=[{"port_id":"AAA","name":"Port Alpha"},{"port_id":"BBB","name":"Port Beta"},{"port_id":"BBB2","name":"Port Beta"}]
        data=("date-out;date-in;mmsi_imo_vessel_mame;PortName_from;PortName_to\n"
              "2020-01-01 00:00:00;2020-01-01 02:00:00;V1;Port Alpha;Port Beta\n"
              "2020-01-02 00:00:00;2020-01-02 02:00:00;V1;Port Alpha;Unknown\n").encode()
        rows,counts=parse_csv(io.BytesIO(data),ports)
        self.assertEqual(rows,[])
        self.assertEqual(counts["ambiguous"],1)
        self.assertEqual(counts["unmatched"],1)
    def fixture(self, root):
        upstream=root/"edges.csv"
        with upstream.open("w",newline="",encoding="utf8") as f:
            w=csv.writer(f); w.writerow(["Supplier","Supplier Industry","Supplier Country","Customer","Customer Industry","Customer Country"])
            w.writerow(["Supplier A","Auto","Japan","Customer B","Auto","Germany"])
        return upstream

    def test_e2e_is_seed_deterministic_and_links_direct_edge(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); upstream=self.fixture(root)
            a=build("synthetic-dev",1,13,str(upstream),out_dir=root/"a")
            b=build("synthetic-dev",1,13,str(upstream),out_dir=root/"b")
            for name in ("ports.json","services.json","shipments.json","route_plans.json","dataset_manifest.json"):
                self.assertEqual((root/"a"/name).read_bytes(),(root/"b"/name).read_bytes())
            sh=json.loads((root/"a"/"shipments.json").read_text())[0]
            self.assertTrue(sh["supplier_edge_id"].startswith("EDGE-"))
            self.assertEqual(a["counts"]["shipments"],b["counts"]["shipments"])

    def test_parallel_services_and_route_connectivity(self):
        ports=[{"port_id":"A","latitude":None,"longitude":None,"verified":False},{"port_id":"B","latitude":None,"longitude":None,"verified":False}]
        services=[{"service_id":"s1","origin_port_id":"A","destination_port_id":"B","direction":"DIRECTED","transit_days":2,"cost_units":1},{"service_id":"s2","origin_port_id":"A","destination_port_id":"B","direction":"DIRECTED","transit_days":3,"cost_units":2}]
        self.assertEqual(len({s["service_id"] for s in services}),2)
        ship=[{"shipment_id":"x","supplier_edge_id":"edge","origin_port_id":"A","destination_port_id":"B","release_day":0,"deadline_day":4,"route_plan_id":"p"}]
        plan=[{"route_plan_id":"p","service_ids":["missing"],"transit_days":2,"cost_units":1}]
        self.assertTrue(any("unknown service" in e for e in validate_records(ports,services,ship,plan,{"edge"})))

    def test_validator_rejects_coordinates_costs_and_disconnected_legs(self):
        ports=[{"port_id":"A","latitude":91,"longitude":0,"verified":True},{"port_id":"B","latitude":0,"longitude":0,"verified":True},{"port_id":"C","latitude":0,"longitude":0,"verified":True}]
        services=[{"service_id":"s1","origin_port_id":"A","destination_port_id":"B","direction":"DIRECTED","transit_days":1,"cost_units":-1},{"service_id":"s2","origin_port_id":"C","destination_port_id":"B","direction":"DIRECTED","transit_days":1,"cost_units":0}]
        ship=[{"shipment_id":"x","supplier_edge_id":"edge","origin_port_id":"A","destination_port_id":"B","release_day":0,"deadline_day":1,"route_plan_id":"p"}]
        plan=[{"route_plan_id":"p","service_ids":["s1","s2"],"transit_days":2,"cost_units":-1}]
        errors=" ".join(validate_records(ports,services,ship,plan,{"edge"}))
        self.assertIn("invalid latitude",errors); self.assertIn("negative cost",errors); self.assertIn("disconnected",errors); self.assertIn("impossible",errors)

    def test_strict_mode_requires_reference_files(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); upstream=self.fixture(root)
            with self.assertRaises(FileNotFoundError): build("strict",1,1,str(upstream),reference_dir=root/"ref",out_dir=root/"out")

if __name__=="__main__": unittest.main()
