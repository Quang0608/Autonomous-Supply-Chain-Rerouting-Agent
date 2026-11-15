import ast
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from evaluation import verify_first_batch as verifier


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/builds/research_1500"
POLICY = ROOT / "config/recovery_policy.json"
RUNS = ROOT / "data/simulations/phase5/phase5_2b"
VERIFY_DATE = "2026-11-15"


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Phase5GroundTruthTests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.hashes, self.ports, self.services, self.ship_by_id, self.plans = verifier.source_records(DATASET)

    def test_sc007_derives_no_reroute_when_connection_and_deadline_pass(self):
        label = verifier.verify_sc007(
            ROOT / "examples/phase5", self.hashes, self.services, self.ship_by_id,
            self.plans, POLICY, "test-commit", VERIFY_DATE,
        )
        recovery = label["expected_recovery"][0]
        calculation = label["independent_calculation"]["propagation_and_deadline_calculations"][0]
        self.assertEqual("NO_REROUTE_REQUIRED", recovery["expected_recovery_status"])
        self.assertEqual("NO_REROUTE_REQUIRED", calculation["safe_recovery_decision"])
        self.assertTrue(calculation["fixed_itinerary_continuable"])
        self.assertTrue(calculation["deadline_met"])
        self.assertEqual(verifier.Decimal("4625.28"), calculation["downstream_connections"][0]["remaining_slack_seconds"])

    def test_sc007_refuses_missed_fixed_connection(self):
        matches = [(None, None, None, {
            "shipment_id": "SHIP-000001", "leg_id": verifier.SC007_EXPECTED_DIRECT_LEG,
            "service_id": "SVC-35a7482f2af1d0", "operation": "DEPARTURE",
        })]
        calculations = [{"shipment_id": "SHIP-000001", "downstream_connections": [{
            "connection_feasible": False, "remaining_slack_seconds": -1,
        }], "deadline_met": False, "modeled_final_eta": None}]
        with self.assertRaises(verifier.ScenarioAssumptionError) as raised:
            verifier.enforce_sc007_assumptions(
                ["SHIP-000001"], matches, calculations, timedelta(hours=1), "SVC-35a7482f2af1d0",
            )
        self.assertIn("downstream_fixed_connection_feasible", str(raised.exception))
        self.assertIn("remaining_transfer_slack_nonnegative", str(raised.exception))
        self.assertIn("connection_calculations", str(raised.exception))

    def test_sc007_refuses_deadline_infeasible_original_itinerary(self):
        matches = [(None, None, None, {
            "shipment_id": "SHIP-000001", "leg_id": verifier.SC007_EXPECTED_DIRECT_LEG,
            "service_id": "SVC-35a7482f2af1d0", "operation": "DEPARTURE",
        })]
        calculations = [{"shipment_id": "SHIP-000001", "downstream_connections": [{
            "connection_feasible": True, "remaining_slack_seconds": 10,
        }], "deadline_met": False, "modeled_final_eta": "2025-11-02T00:00:00Z"}]
        with self.assertRaises(verifier.ScenarioAssumptionError) as raised:
            verifier.enforce_sc007_assumptions(
                ["SHIP-000001"], matches, calculations, timedelta(hours=1), "SVC-35a7482f2af1d0",
            )
        self.assertIn("final_eta_meets_deadline", str(raised.exception))
        self.assertIn("no_alternative_recovery_route_required", str(raised.exception))

    def test_sc007_refuses_changed_affected_shipment_cohort(self):
        matches = [(None, None, None, {
            "shipment_id": "SHIP-000001", "leg_id": verifier.SC007_EXPECTED_DIRECT_LEG,
            "service_id": "SVC-35a7482f2af1d0", "operation": "DEPARTURE",
        })]
        calculations = [{"shipment_id": "SHIP-000001", "downstream_connections": [{
            "connection_feasible": True, "remaining_slack_seconds": 10,
        }], "deadline_met": True, "modeled_final_eta": "2025-10-24T08:45:44.64Z"}]
        with self.assertRaises(verifier.ScenarioAssumptionError) as raised:
            verifier.enforce_sc007_assumptions(
                ["SHIP-000001", "SHIP-000002"], matches, calculations,
                timedelta(hours=1), "SVC-35a7482f2af1d0",
            )
        self.assertIn("intended_affected_cohort", str(raised.exception))

    def test_sc012_empty_overlap_set_produces_verified_empty_impact(self):
        label = verifier.verify_sc012(
            ROOT / "examples/phase5", self.hashes, self.ports, self.ship_by_id,
            self.plans, POLICY, "test-commit", VERIFY_DATE,
        )
        self.assertEqual("VERIFIED", label["verification_status"])
        self.assertEqual([], label["expected_impact"]["affected_shipment_ids"])
        self.assertEqual([], label["expected_impact"]["affected_shipments"])
        self.assertEqual(1500, label["unaffected_recovery_classification"]["shipment_count"])
        self.assertEqual(0, label["unaffected_recovery_classification"]["recovery_plans_expected"])

    def test_sc012_refuses_no_impact_label_when_overlap_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            scenario_root = Path(temp) / "examples/phase5"
            case_dir = scenario_root / "SC-012"
            case_dir.mkdir(parents=True)
            (case_dir / "notice.txt").write_text("simulated", encoding="utf-8")
            (case_dir / "scenario.json").write_text(json.dumps({
                "schema_version": "1.0", "scenario_id": "SC-012", "events": [{
                    "event_id": "SC-012-E1", "type": "PORT_CLOSURE", "target_port_id": "ARBUE",
                    "start_time": "2025-01-02T00:00:00Z", "end_time": "2025-01-03T00:00:00Z",
                    "affected_operations": ["ARRIVAL", "DEPARTURE", "TRANSSHIPMENT"],
                }],
            }), encoding="utf-8")
            plan = {"shipment_id": "SHIP-X", "route_plan_id": "PLAN-X", "ordered_legs": [{
                "origin_port_id": "VNSGN", "destination_port_id": "ARBUE", "service_id": "SVC-X",
                "planned_departure": 1, "planned_arrival": 1.5,
            }]}
            with self.assertRaises(verifier.ScenarioAssumptionError) as raised:
                verifier.verify_sc012(
                    scenario_root, self.hashes, [{"port_id": "ARBUE"}], {"SHIP-X": {"shipment_id": "SHIP-X"}},
                    [plan], POLICY, "test-commit", VERIFY_DATE,
                )
            diagnostic = json.loads(str(raised.exception).split(": ", 1)[1])
            self.assertEqual(["SHIP-X"], diagnostic["affected_shipment_ids"])
            self.assertNotIn("verification_status", diagnostic)
            self.assertIn("overlapping_arrivals", diagnostic)

    def prepare_temporary_workflow(self, temp_root):
        temp_root = Path(temp_root)
        shutil.copytree(ROOT / "examples/phase5", temp_root / "examples/phase5")
        (temp_root / "config").mkdir()
        shutil.copy2(POLICY, temp_root / "config/recovery_policy.json")
        args = type("Args", (), {
            "dataset": str(DATASET), "policy": "config/recovery_policy.json",
            "scenario_root": "examples/phase5", "ground_truth": "evaluation/ground_truth",
            "comparisons": "evaluation/comparisons", "run_outputs": str(RUNS),
            "verification_date": VERIFY_DATE,
        })()
        return args

    def test_generate_writes_independent_references_without_observed_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.prepare_temporary_workflow(temp)
            with mock.patch.object(verifier, "git_commit", return_value="test-commit"), \
                 mock.patch.object(verifier.subprocess, "run", side_effect=AssertionError("generation must not invoke tools")):
                verifier.generate(args, Path(temp))
            self.assertFalse((Path(temp) / "evaluation/comparisons").exists())
            for sid in verifier.SCENARIOS:
                label = json.loads((Path(temp) / args.ground_truth / f"{sid}.json").read_text(encoding="utf-8"))
                self.assertNotIn("observed_execution", label)
                self.assertEqual("VERIFIED", label["verification_status"])

    def test_compare_does_not_modify_ground_truth_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.prepare_temporary_workflow(temp)
            temp_root = Path(temp)
            with mock.patch.object(verifier, "git_commit", return_value="test-commit"):
                verifier.generate(args, temp_root)
            for sid in verifier.SCENARIOS:
                for phase, files in {
                    "phase3": ("shipment_impacts.json", "summary.json"),
                    "phase4": ("recovery_results.json", "summary.json"),
                }.items():
                    destination = temp_root / args.run_outputs / sid / phase
                    destination.mkdir(parents=True, exist_ok=True)
                    source = RUNS / sid / phase
                    for name in files:
                        (destination / name).write_bytes((source / name).read_bytes())
            before = {sid: file_hash(temp_root / args.ground_truth / f"{sid}.json") for sid in verifier.SCENARIOS}
            self.assertEqual([], verifier.compare(args, temp_root))
            after = {sid: file_hash(temp_root / args.ground_truth / f"{sid}.json") for sid in verifier.SCENARIOS}
            self.assertEqual(before, after)
            sc002 = json.loads((temp_root / args.comparisons / "SC-002.json").read_text(encoding="utf-8"))
            self.assertEqual("PORT_CLOSURE_ARRIVAL_OVERLAP", sc002["phase3_observed"]["impact_evidence"][0]["causes"][0]["reason_code"])
            p4_row = sc002["phase4_observed"]["relevant_results"][0]
            self.assertEqual("ARRIVAL_CLOSURE_POSITION_UNRESOLVED", p4_row["reason_code"])
            self.assertEqual("OPERATOR_INTERVENTION_REQUIRED", p4_row["recovery_status"])
            self.assertIsNone(p4_row["recovery_plan"])
            comparison_bytes = {sid: (temp_root / args.comparisons / f"{sid}.json").read_bytes() for sid in verifier.SCENARIOS}
            self.assertEqual([], verifier.compare(args, temp_root))
            self.assertEqual(before, {sid: file_hash(temp_root / args.ground_truth / f"{sid}.json") for sid in verifier.SCENARIOS})
            self.assertEqual(comparison_bytes, {sid: (temp_root / args.comparisons / f"{sid}.json").read_bytes() for sid in verifier.SCENARIOS})

    def test_independent_generator_does_not_import_phase3_or_phase4(self):
        tree = ast.parse((ROOT / "evaluation/verify_first_batch.py").read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        forbidden = ("phase3", "phase4", "recovery_validation", "maritime")
        self.assertFalse([name for name in imported if any(part in name for part in forbidden)])


if __name__ == "__main__":
    unittest.main()
