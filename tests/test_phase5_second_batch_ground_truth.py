import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from evaluation import verify_second_batch as verifier


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/builds/research_1500"
POLICY = ROOT / "config/recovery_policy.json"
RUNS = ROOT / "data/simulations/phase5/phase5_2d"
DATE = "2026-11-15"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SecondBatchGroundTruthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.hashes, cls.ports, cls.services, cls.shipments, cls.plans, cls.ship_by_id, cls.plan_by_ship, cls.service_by_id, cls.port_ids = verifier.load_canonical(DATASET)
        cls.labels = {
            sid: verifier.build_label(sid, DATASET, ROOT / "examples/phase5", POLICY, "test-commit", DATE)
            for sid in verifier.SCENARIOS
        }

    def route_context(self, scenario_id, shipment_id):
        label = self.labels[scenario_id]
        row = next(x for x in label["expected_recovery"] if x["shipment_id"] == shipment_id)
        route = row["reference_routes"][0]["replacement_suffix"]
        return (deepcopy(self.ship_by_id[shipment_id]), deepcopy(self.plan_by_ship[shipment_id]),
                deepcopy(row["recovery_state"]), deepcopy(route), label["hidden_reference_event"]["events"],
                verifier.read_json(POLICY))

    def test_sc001_complete_cohort_and_same_service_rescheduling(self):
        label = self.labels["SC-001"]
        self.assertEqual(7, len(label["expected_impact"]["affected_shipment_ids"]))
        self.assertEqual(1493, label["expected_impact"]["unaffected_shipment_count"])
        counts = verifier.distribution({x["shipment_id"]: x["expected_recovery_status"] for x in label["expected_recovery"]})
        counts["UNCHANGED"] = label["expected_impact"]["unaffected_shipment_count"]
        self.assertEqual({"RECOVERED": 7, "UNCHANGED": 1493}, counts)
        self.assertTrue(all(x["recovery_classification"] == "SAME_SERVICE_RESCHEDULING" for x in label["expected_recovery"]))
        self.assertTrue(all(not x["service_sequence_changed"] and not x["port_sequence_changed"] for x in label["expected_recovery"]))

    def test_sc004_candidate_routes_change_services_and_intermediate_ports(self):
        label = self.labels["SC-004"]
        self.assertEqual(5, len(label["expected_impact"]["affected_shipment_ids"]))
        rows = {x["shipment_id"]: x for x in label["expected_recovery"]}
        self.assertTrue(all(x["recovery_classification"] == "CHANGED_SERVICE_AND_PORT_SEQUENCE" for x in rows.values()))
        route = rows["SHIP-000005"]["reference_routes"][0]
        self.assertNotEqual(route["original_port_sequence"], route["port_sequence"])
        self.assertNotEqual(route["original_service_sequence"], route["service_sequence"])
        nominated = label["independent_calculation"]["additional_route_candidate_checks"][0]
        self.assertEqual(["GBBPT", "NLRTM", "KRPUS", "CNSGH"], nominated["candidate_port_sequence"])
        self.assertEqual(["NLRTM", "SGSIN", "CNSGH"], nominated["original_remaining_port_sequence"])
        self.assertTrue(nominated["original_first_departure_blocked_by_event"])
        self.assertTrue(nominated["deadline_met"])
        self.assertTrue(all(x["result"] == "PASS" for x in nominated["independent_constraint_checks"]))
        self.assertTrue(all(r["deadline_met"] for x in rows.values() for r in x["reference_routes"]))
        self.assertTrue(all(all(c["result"] == "PASS" for c in r["independent_constraint_checks"])
                            for x in rows.values() for r in x["reference_routes"]))

    def test_rejects_invalid_directed_continuity(self):
        shipment, plan, state, route, events, policy = self.route_context("SC-004", "SHIP-000005")
        route[0]["origin_port_id"] = "ARBUE"
        result = verifier.check_route(shipment, plan, state, route, self.service_by_id, events, policy)
        self.assertFalse(result["valid"])
        self.assertIn("FAIL", [x["result"] for x in result["checks"]])

    def test_rejects_departure_inside_service_suspension(self):
        shipment, plan, state, route, events, policy = self.route_context("SC-004", "SHIP-000005")
        route[0]["service_id"] = "SVC-e3ab1786547e47"
        route[0]["origin_port_id"] = "NLRTM"
        route[0]["destination_port_id"] = "SGSIN"
        route[0]["departure_time"] = "2025-01-29T00:00:00Z"
        svc = self.service_by_id[route[0]["service_id"]]
        route[0]["arrival_time"] = verifier.iso(verifier.parse_time(route[0]["departure_time"]) + verifier.exact_duration(svc["transit_days"], verifier.DAY_US, "test transit"))
        result = verifier.check_route(shipment, plan, state, route[:1], self.service_by_id, events, policy)
        active = next(x for x in result["checks"] if x["constraint"] == "ACTIVE_DISRUPTIONS")
        self.assertEqual("FAIL", active["result"])

    def test_rejects_insufficient_transfer_time(self):
        shipment, plan, state, route, events, policy = self.route_context("SC-004", "SHIP-000005")
        route[1]["departure_time"] = "2025-01-24T08:00:00Z"
        svc = self.service_by_id[route[1]["service_id"]]
        route[1]["arrival_time"] = verifier.iso(verifier.parse_time(route[1]["departure_time"]) + verifier.exact_duration(svc["transit_days"], verifier.DAY_US, "test transit"))
        result = verifier.check_route(shipment, plan, state, route, self.service_by_id, events, policy)
        transfer = [x for x in result["checks"] if x["constraint"] == "TRANSFER_READY"]
        self.assertEqual("FAIL", transfer[1]["result"])

    def test_rejects_unsupported_cargo_and_insufficient_capacity(self):
        shipment, plan, state, route, events, policy = self.route_context("SC-004", "SHIP-000005")
        shipment["cargo_class"] = "NOT_SUPPORTED"
        shipment["cargo_teu"] = 999999
        result = verifier.check_route(shipment, plan, state, route, self.service_by_id, events, policy)
        self.assertTrue(any(x["constraint"] == "CARGO_CLASS" and x["result"] == "FAIL" for x in result["checks"]))
        self.assertTrue(any(x["constraint"] == "INDIVIDUAL_CAPACITY" and x["result"] == "FAIL" for x in result["checks"]))

    def test_rejects_deadline_infeasible_route(self):
        shipment, plan, state, route, events, policy = self.route_context("SC-004", "SHIP-000005")
        shipment["delivery_deadline"] = 1
        result = verifier.check_route(shipment, plan, state, route, self.service_by_id, events, policy)
        self.assertFalse(result["deadline_met"])
        self.assertTrue(any(x["constraint"] == "HARD_DEADLINE" and x["result"] == "FAIL" for x in result["checks"]))

    def test_sc008_missed_connection_and_recovery_departure_readiness(self):
        label = self.labels["SC-008"]
        self.assertEqual(3, len(label["expected_impact"]["affected_shipment_ids"]))
        row = next(x for x in label["independent_calculation"]["impact_evidence"] if x["shipment_id"] == "SHIP-000026")
        connection = next(x for x in row["indirect_evidence"] if x["reason_code"] == "UNRESOLVED_CONNECTION")
        self.assertEqual("2025-09-30T12:42:54.72Z", connection["inbound_arrival"])
        self.assertEqual("2025-10-01T00:42:54.72Z", connection["earliest_connection_ready"])
        self.assertEqual("2025-10-01T00:00:00Z", connection["fixed_departure"])
        recovery = next(x for x in label["expected_recovery"] if x["shipment_id"] == "SHIP-000026")
        leg = recovery["reference_routes"][0]["replacement_suffix"][0]
        self.assertEqual("2025-10-08T00:00:00Z", leg["departure_time"])
        self.assertGreaterEqual(verifier.parse_time(leg["departure_time"]), verifier.parse_time(recovery["recovery_state"]["earliest_recovery_time"]))

    def temp_workflow(self, temp):
        root = Path(temp)
        shutil.copytree(ROOT / "examples/phase5", root / "examples/phase5")
        (root / "config").mkdir()
        shutil.copy2(POLICY, root / "config/recovery_policy.json")
        for sid in verifier.SCENARIOS:
            for phase, names in {"phase3": ("shipment_impacts.json", "summary.json"),
                                 "phase4": ("recovery_results.json", "summary.json", "constraint_validation.json")}.items():
                dest = root / "data/simulations/phase5/phase5_2d" / sid / phase
                dest.mkdir(parents=True, exist_ok=True)
                for name in names:
                    shutil.copy2(RUNS / sid / phase / name, dest / name)
        return root, type("Args", (), {
            "dataset": str(DATASET), "policy": "config/recovery_policy.json",
            "scenario_root": "examples/phase5", "ground_truth": "evaluation/ground_truth",
            "comparisons": "evaluation/comparisons", "run_outputs": "data/simulations/phase5/phase5_2d",
            "verification_date": DATE,
        })()

    def test_compare_preserves_ground_truth_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            root, args = self.temp_workflow(temp)
            with mock.patch.object(verifier, "commit_id", return_value="test-commit"):
                verifier.generate(args, root)
                before = {sid: digest(root / args.ground_truth / f"{sid}.json") for sid in verifier.SCENARIOS}
                verifier.generate(args, root)
                self.assertEqual(before, {sid: digest(root / args.ground_truth / f"{sid}.json") for sid in verifier.SCENARIOS})
                self.assertEqual(["SC-004"], verifier.compare(args, root))
                first = {sid: digest(root / args.comparisons / f"{sid}.json") for sid in verifier.SCENARIOS}
                self.assertEqual(before, {sid: digest(root / args.ground_truth / f"{sid}.json") for sid in verifier.SCENARIOS})
                self.assertEqual(["SC-004"], verifier.compare(args, root))
                self.assertEqual(first, {sid: digest(root / args.comparisons / f"{sid}.json") for sid in verifier.SCENARIOS})

    def test_comparison_detects_observed_route_discrepancy(self):
        with tempfile.TemporaryDirectory() as temp:
            root, args = self.temp_workflow(temp)
            with mock.patch.object(verifier, "commit_id", return_value="test-commit"):
                verifier.generate(args, root)
                p4_path = root / args.run_outputs / "SC-004/phase4/recovery_results.json"
                rows = json.loads(p4_path.read_text(encoding="utf-8"))
                target = next(x for x in rows if x["shipment_id"] == "SHIP-000005")
                target["replacement_suffix"][0]["service_id"] = "SVC-not-the-reference"
                p4_path.write_text(json.dumps(rows), encoding="utf-8")
                self.assertIn("SC-004", verifier.compare(args, root))
                result = json.loads((root / args.comparisons / "SC-004.json").read_text(encoding="utf-8"))
                self.assertEqual("MISMATCH", result["comparison_result"])

    def test_generator_does_not_import_or_read_phase3_phase4_modules_or_outputs(self):
        tree = ast.parse((ROOT / "evaluation/verify_second_batch.py").read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        forbidden = ("phase3", "phase4", "recovery_validation")
        self.assertFalse([name for name in imported if any(token in name for token in forbidden)])
        source = (ROOT / "evaluation/verify_second_batch.py").read_text(encoding="utf-8")
        generate_source = source.split("def compare(", 1)[0]
        self.assertNotIn("phase5_2d", generate_source)


if __name__ == "__main__":
    unittest.main()
