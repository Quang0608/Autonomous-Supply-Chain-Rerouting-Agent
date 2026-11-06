import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from src.maritime.phase4 import policy_at, recover, write_outputs
from src.maritime.recovery_validation import checks_for_route
from src.maritime.phase3 import load_json

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/"tests/fixtures/phase4/minimal"
POLICY = ROOT/"config/recovery_policy.json"


def event(event_id, kind, start, end, **target):
    return {"event_id": event_id, "type": kind, "start_time": start, "end_time": end, **target}


def scenario(*events):
    return {"schema_version": "1.0", "scenario_id": "phase4-synthetic", "events": list(events)}


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.policy = policy_at(POLICY)

    def run_case(self, *events, dataset=FIXTURE, policy=None):
        return recover(dataset, scenario(*events), policy or self.policy)

    def test_unaffected_is_unchanged(self):
        result = self.run_case(event("future","PORT_CLOSURE","2040-01-01T00:00:00Z","2040-01-02T00:00:00Z",
                                     target_port_id="P-A",affected_operations=["DEPARTURE"]))
        row = result["recovery_results"][0]
        self.assertEqual(("SHIP-1","UNCHANGED","2025-01-04T00:00:00Z"),
                         (row["shipment_id"],row["status"],row["recovered_eta"]))
        self.assertEqual(0,result["summary"]["attempted"])

    def test_suspension_selects_valid_alternate_and_ties_lexically(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        result = self.run_case(suspension)
        row = result["recovery_results"][0]
        self.assertEqual("RECOVERED",row["status"])
        self.assertEqual(["S-AD","S-DC"],[x["service_id"] for x in row["replacement_suffix"]])
        self.assertEqual("2025-01-04T00:00:00Z",row["recovered_eta"])
        self.assertEqual(2.0,row["additional_cost_usd"])
        self.assertTrue(any(all(c["result"] == "PASS" for c in record["checks"])
                            for record in result["constraint_validation"]))

    def test_missed_connection_preserves_prefix_and_port(self):
        delay = event("late-ab","SERVICE_DELAY","2025-01-02T00:00:00Z","2025-01-03T00:00:00Z",
                      target_service_id="S-AB",delay_hours=48)
        result = self.run_case(delay)
        state = result["recovery_states"][0]
        self.assertEqual(["PLAN-1:L1"],state["completed_leg_ids"])
        self.assertEqual("P-B",state["recovery_port_id"])
        self.assertEqual("2025-01-05T00:00:00Z",state["earliest_recovery_time"])
        row = result["recovery_results"][0]
        self.assertEqual("RECOVERED",row["status"])
        self.assertEqual(["S-BC"],[x["service_id"] for x in row["replacement_suffix"]])
        self.assertEqual("2025-01-06T00:00:00Z",row["recovered_eta"])

    def test_arrival_closure_has_no_diversion_policy(self):
        closure = event("closed-b","PORT_CLOSURE","2025-01-03T00:00:00Z","2025-01-04T00:00:00Z",
                        target_port_id="P-B",affected_operations=["ARRIVAL"])
        row = self.run_case(closure)["recovery_results"][0]
        self.assertEqual("INSUFFICIENT_DATA",row["status"])
        self.assertIsNone(row["recovered_eta"])

    def test_search_limit_and_no_route_are_distinct(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        limited = dict(self.policy,max_expansions=1)
        self.assertEqual("SEARCH_LIMIT_REACHED",self.run_case(suspension,policy=limited)["recovery_results"][0]["status"])
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            for name in ("dataset_manifest.json","ports.json","services.json","shipments.json","route_plans.json"):
                shutil.copyfile(FIXTURE/name,dataset/name)
            services = [s for s in load_json(dataset/"services.json") if s["service_id"] in ("S-AB","S-BC")]
            (dataset/"services.json").write_text(json.dumps(services),encoding="utf-8")
            row = self.run_case(suspension,dataset=dataset)["recovery_results"][0]
        self.assertEqual("NO_FEASIBLE_ROUTE",row["status"])

    def test_independent_validator_rejects_wrong_direction(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        result = self.run_case(suspension)
        row = result["recovery_results"][0]
        bad = copy.deepcopy(row["replacement_suffix"])
        bad[0]["origin_port_id"] = "P-C"
        checks = checks_for_route(load_json(FIXTURE/"shipments.json")[0],
                                  load_json(FIXTURE/"route_plans.json")[0],
                                  result["recovery_states"][0],bad,load_json(FIXTURE/"services.json"),
                                  result["scenario"],self.policy)
        self.assertIn("DIRECTED_CONTINUITY",[c["constraint"] for c in checks if c["result"] == "FAIL"])

    def test_closure_start_blocks_and_end_allows_later_departure(self):
        closure = event("close-a","PORT_CLOSURE","2025-01-02T00:00:00Z","2025-01-03T00:00:00Z",
                        target_port_id="P-A",affected_operations=["DEPARTURE"])
        row = self.run_case(closure)["recovery_results"][0]
        self.assertEqual("RECOVERED",row["status"])
        self.assertEqual("2025-01-03T00:00:00Z",row["replacement_suffix"][0]["departure_time"])
        self.assertEqual("2025-01-05T00:00:00Z",row["recovered_eta"])

    def test_hard_deadline_prefers_costlier_timely_route(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            for name in ("dataset_manifest.json","ports.json","services.json","shipments.json","route_plans.json"):
                shutil.copyfile(FIXTURE/name,dataset/name)
            services = load_json(dataset/"services.json")
            for svc in services:
                if svc["service_id"] == "S-DC":
                    svc["transit_days"] = 5
                if svc["service_id"] in ("S-AE","S-EC"):
                    svc["cost_per_teu_usd"] = 3
            (dataset/"services.json").write_text(json.dumps(services),encoding="utf-8")
            row = self.run_case(suspension,dataset=dataset)["recovery_results"][0]
        self.assertEqual("RECOVERED",row["status"])
        self.assertEqual(["S-AE","S-EC"],[x["service_id"] for x in row["replacement_suffix"]])
        self.assertEqual("2025-01-04T00:00:00Z",row["recovered_eta"])

    def test_unsupported_capacity_is_insufficient_data(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            for name in ("dataset_manifest.json","ports.json","services.json","shipments.json","route_plans.json"):
                shutil.copyfile(FIXTURE/name,dataset/name)
            services = load_json(dataset/"services.json")
            del services[0]["capacity_teu"]
            (dataset/"services.json").write_text(json.dumps(services),encoding="utf-8")
            row = self.run_case(suspension,dataset=dataset)["recovery_results"][0]
        self.assertEqual("INSUFFICIENT_DATA",row["status"])

    def test_only_late_alternatives_are_deadline_infeasible(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            for name in ("dataset_manifest.json","ports.json","services.json","shipments.json","route_plans.json"):
                shutil.copyfile(FIXTURE/name,dataset/name)
            ships = load_json(dataset/"shipments.json")
            ships[0]["delivery_deadline"] = 2.5
            (dataset/"shipments.json").write_text(json.dumps(ships),encoding="utf-8")
            row = self.run_case(suspension,dataset=dataset)["recovery_results"][0]
        self.assertEqual("DEADLINE_INFEASIBLE",row["status"])
        self.assertIsNone(row["recovered_eta"])
        self.assertIsNotNone(row["late_diagnostic"])

    def test_repeat_outputs_are_byte_stable(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            write_outputs(FIXTURE,scenario(suspension),POLICY,Path(one))
            write_outputs(FIXTURE,scenario(suspension),POLICY,Path(two))
            for name in ("scenario_manifest.json","recovery_states.json","recovery_results.json",
                         "recovery_results.csv","constraint_validation.json","summary.json"):
                self.assertEqual((Path(one)/name).read_bytes(),(Path(two)/name).read_bytes(),name)


if __name__ == "__main__":
    unittest.main()
