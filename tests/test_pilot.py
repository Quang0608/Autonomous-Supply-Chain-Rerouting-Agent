import tempfile
import unittest
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from maritime.network import shortest_path, build_network
from maritime.supplier import read_edges, tier_from_manufacturer, choose_pairs
from maritime.models import validate_dataset

class PilotTests(unittest.TestCase):
    def test_blocked_port_routes_around(self):
        _,network=build_network()
        original=shortest_path("CNSHA","DEHAM",network)
        self.assertIsNotNone(original)
        alt=shortest_path("CNSHA","DEHAM",network,{"SGSIN"})
        self.assertIsNotNone(alt)
        self.assertNotIn("SGSIN",alt["ports"])
    def test_blocked_endpoints_are_invalid(self):
        _,network=build_network()
        self.assertIsNone(shortest_path("CNSHA","DEHAM",network,{"CNSHA"}))
    def test_tiers_are_upstream(self):
        edges=[{"Supplier":"Supplier B","Customer":"Supplier A"},
               {"Supplier":"Supplier A","Customer":"Tesla Inc"}]
        t=tier_from_manufacturer(edges)
        self.assertEqual(t["Supplier A"],1)
        self.assertEqual(t["Supplier B"],2)
    def test_source_csv_and_selection(self):
        with tempfile.TemporaryDirectory() as td:
            csv=Path(td)/"clean.csv"
            csv.write_text("Supplier,Supplier Industry,Supplier Country,Customer,Customer Industry,Customer Country\n"
                           "A,Automotive,Japan,Tesla Inc,Automotive,Germany\n",encoding="utf8")
            rows=read_edges(csv)
            selected,report=choose_pairs(rows,{"Japan","Germany"},2,42)
            self.assertEqual(len(selected),1)
            self.assertTrue(selected[0]["linked_to_manufacturer"])

    def test_dataset_validation_accepts_minimal_synthetic_fixture(self):
        ports = [{"id": "AAA", "name": "Port A"}, {"id": "BBB", "name": "Port B"}]
        services = [{"from": "AAA", "to": "BBB", "transit_days": 3, "cost_units": 100}]
        shipments = [{"shipment_id": "S1", "cargo_teu": 1, "release_day": 0,
                      "deadline_day": 5, "original_route": {"ports": ["AAA", "BBB"],
                      "transit_days": 3, "cost_units": 100}}]
        validate_dataset(ports, services, shipments,
                         {"port_id": "AAA", "start_day": 0, "end_day": 2})

    def test_dataset_validation_rejects_unknown_route_port(self):
        ports = [{"id": "AAA", "name": "Port A"}, {"id": "BBB", "name": "Port B"}]
        shipments = [{"shipment_id": "S1", "cargo_teu": 1, "release_day": 0,
                      "deadline_day": 5, "original_route": {"ports": ["AAA", "ZZZ"],
                      "transit_days": 3, "cost_units": 100}}]
        with self.assertRaisesRegex(ValueError, "invalid route"):
            validate_dataset(ports, [], shipments,
                             {"port_id": "AAA", "start_day": 0, "end_day": 2})

if __name__=="__main__":unittest.main()
