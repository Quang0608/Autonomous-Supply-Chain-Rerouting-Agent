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
TRANS_FIXTURE = ROOT/"tests/fixtures/phase4/transshipment_closure"
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
                         (row["shipment_id"],row["recovery_status"],row["recovered_eta"]))
        self.assertEqual(0,result["summary"]["attempted"])

    def test_suspension_selects_valid_alternate_and_ties_lexically(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        result = self.run_case(suspension)
        row = result["recovery_results"][0]
        self.assertEqual("RECOVERED",row["recovery_status"])
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
        self.assertEqual("RECOVERED",row["recovery_status"])
        self.assertEqual(["S-BC"],[x["service_id"] for x in row["replacement_suffix"]])
        self.assertEqual("2025-01-06T00:00:00Z",row["recovered_eta"])

    def test_arrival_closure_has_no_diversion_policy(self):
        closure = event("closed-b","PORT_CLOSURE","2025-01-03T00:00:00Z","2025-01-04T00:00:00Z",
                        target_port_id="P-B",affected_operations=["ARRIVAL"])
        row = self.run_case(closure)["recovery_results"][0]
        self.assertEqual("OPERATOR_INTERVENTION_REQUIRED",row["recovery_status"])
        self.assertIn("SHIP-1",row["reason"])
        self.assertTrue(row["missing_information"])
        self.assertIsNone(row["recovery_plan"])
        self.assertIsNone(row["recovered_eta"])
        self.assertEqual(["PLAN-1:L1"],row["affected_leg_ids"])
        self.assertEqual(["closed-b"],row["event_ids"])

    def test_canonical_transshipment_closure_requires_operator_for_all_three_shipments(self):
        dataset = TRANS_FIXTURE
        scenario_path = ROOT/"examples/phase3/transshipment_closure_unresolved.json"
        raw = load_json(scenario_path)
        result = recover(dataset, raw, self.policy)
        rows = {row["shipment_id"]: row for row in result["recovery_results"]
                if row["recovery_status"] == "OPERATOR_INTERVENTION_REQUIRED"}
        expected = {"SHIP-000001", "SHIP-000997", "SHIP-EXP-000098"}
        self.assertEqual(expected,set(rows))
        self.assertEqual(3,result["summary"]["affected_shipments"])
        self.assertEqual(3,result["summary"]["statuses"]["OPERATOR_INTERVENTION_REQUIRED"])
        plans = {p["shipment_id"]: p for p in load_json(dataset/"route_plans.json")}
        impacts = {item["shipment_id"]: item for item in result["phase3_impacts"]}
        for shipment_id,row in rows.items():
            self.assertEqual("TRANSSHIPMENT_HANDLING_POLICY_UNAVAILABLE",row["reason_code"],shipment_id)
            self.assertIn(shipment_id,row["reason"])
            self.assertTrue(row["missing_information"],shipment_id)
            self.assertIsNone(row["recovery_plan"],shipment_id)
            self.assertEqual(["event_close_sgsin_transfer"],row["event_ids"])
            self.assertEqual([f"PLAN-{shipment_id}:L1"],row["affected_leg_ids"])
            self.assertNotIn("replacement_suffix",row)
            cause = impacts[shipment_id]["causes"][0]
            self.assertEqual(("TRANSSHIPMENT","event_close_sgsin_transfer","SGSIN"),
                             (cause["operation"],cause["event_id"],cause["target_entity_id"]))
            first_leg = plans[shipment_id]["ordered_legs"][0]
            next_leg = plans[shipment_id]["ordered_legs"][1]
            self.assertEqual("SGSIN",first_leg["destination_port_id"])
            self.assertEqual("SGSIN",next_leg["origin_port_id"])

    def test_infeasible_and_limited_search_statuses_are_not_operator_intervention(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            for name in ("dataset_manifest.json","ports.json","services.json","shipments.json","route_plans.json"):
                shutil.copyfile(FIXTURE/name,dataset/name)
            services = [s for s in load_json(dataset/"services.json") if s["service_id"] in ("S-AB","S-BC")]
            (dataset/"services.json").write_text(json.dumps(services),encoding="utf-8")
            no_route = self.run_case(suspension,dataset=dataset)["recovery_results"][0]
        self.assertEqual("NO_FEASIBLE_ROUTE",no_route["recovery_status"])
        self.assertNotEqual("OPERATOR_INTERVENTION_REQUIRED",no_route["recovery_status"])

    def test_search_limit_and_no_route_are_distinct(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        limited = dict(self.policy,max_expansions=1)
        limited_row = self.run_case(suspension,policy=limited)["recovery_results"][0]
        self.assertEqual("SEARCH_LIMIT_REACHED",limited_row["recovery_status"])
        self.assertNotEqual("OPERATOR_INTERVENTION_REQUIRED",limited_row["recovery_status"])
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            for name in ("dataset_manifest.json","ports.json","services.json","shipments.json","route_plans.json"):
                shutil.copyfile(FIXTURE/name,dataset/name)
            services = [s for s in load_json(dataset/"services.json") if s["service_id"] in ("S-AB","S-BC")]
            (dataset/"services.json").write_text(json.dumps(services),encoding="utf-8")
            row = self.run_case(suspension,dataset=dataset)["recovery_results"][0]
        self.assertEqual("NO_FEASIBLE_ROUTE",row["recovery_status"])

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
        self.assertEqual("RECOVERED",row["recovery_status"])
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
        self.assertEqual("RECOVERED",row["recovery_status"])
        self.assertEqual(["S-AE","S-EC"],[x["service_id"] for x in row["replacement_suffix"]])
        self.assertEqual("2025-01-04T00:00:00Z",row["recovered_eta"])

    def test_unsupported_capacity_requires_operator_intervention(self):
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
        self.assertEqual("OPERATOR_INTERVENTION_REQUIRED",row["recovery_status"])
        self.assertEqual("ESSENTIAL_RECOVERY_DATA_MISSING",row["reason_code"])
        self.assertIn("SHIP-1",row["reason"])
        self.assertTrue(row["missing_information"])
        self.assertIsNone(row["recovery_plan"])

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
        self.assertEqual("DEADLINE_INFEASIBLE",row["recovery_status"])
        self.assertNotEqual("OPERATOR_INTERVENTION_REQUIRED",row["recovery_status"])
        self.assertIsNone(row["recovered_eta"])
        self.assertIsNotNone(row["late_diagnostic"])

    def test_slack_absorbs_delay_without_reroute(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            for name in ("dataset_manifest.json","ports.json","services.json","shipments.json","route_plans.json"):
                shutil.copyfile(FIXTURE/name,dataset/name)
            plans = load_json(dataset/"route_plans.json")
            plans[0]["ordered_legs"][1]["planned_departure"] = 3
            plans[0]["ordered_legs"][1]["planned_arrival"] = 4
            plans[0]["estimated_arrival"] = 4
            (dataset/"route_plans.json").write_text(json.dumps(plans),encoding="utf-8")
            delay = event("short-ab","SERVICE_DELAY","2025-01-02T00:00:00Z","2025-01-03T00:00:00Z",
                          target_service_id="S-AB",delay_hours=1)
            result = self.run_case(delay,dataset=dataset)
        row = result["recovery_results"][0]
        self.assertEqual("NO_REROUTE_REQUIRED",row["recovery_status"])
        self.assertEqual("2025-01-05T00:00:00Z",row["recovered_eta"])
        self.assertEqual(0,result["summary"]["attempted"])

    def test_cargo_restriction_rejects_cheaper_edge(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            for name in ("dataset_manifest.json","ports.json","services.json","shipments.json","route_plans.json"):
                shutil.copyfile(FIXTURE/name,dataset/name)
            services = load_json(dataset/"services.json")
            for svc in services:
                if svc["service_id"] == "S-AD":
                    svc["cost_per_teu_usd"] = 0.1
                    svc["cargo_classes"] = ["REFRIGERATED"]
            (dataset/"services.json").write_text(json.dumps(services),encoding="utf-8")
            row = self.run_case(suspension,dataset=dataset)["recovery_results"][0]
        self.assertEqual("RECOVERED",row["recovery_status"])
        self.assertEqual(["S-AE","S-EC"],[x["service_id"] for x in row["replacement_suffix"]])

    def test_delay_shifted_candidate_arrival_avoids_closure(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        delay = event("delay-ad","SERVICE_DELAY","2025-01-02T00:00:00Z","2025-01-03T00:00:00Z",
                      target_service_id="S-AD",delay_hours=24)
        closure = event("close-d","PORT_CLOSURE","2025-01-04T00:00:00Z","2025-01-05T00:00:00Z",
                        target_port_id="P-D",affected_operations=["ARRIVAL"])
        row = self.run_case(suspension,delay,closure)["recovery_results"][0]
        self.assertEqual("RECOVERED",row["recovery_status"])
        self.assertEqual(["S-AE","S-EC"],[x["service_id"] for x in row["replacement_suffix"]])

    def test_cyclic_graph_terminates_without_revisiting_port(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            for name in ("dataset_manifest.json","ports.json","services.json","shipments.json","route_plans.json"):
                shutil.copyfile(FIXTURE/name,dataset/name)
            services = load_json(dataset/"services.json")
            services.append({"service_id":"S-DA","origin_port_id":"P-D","destination_port_id":"P-A",
                             "departure_frequency_days":1,"transit_days":1,"min_transfer_hours":0,
                             "cost_per_teu_usd":0.1,"capacity_teu":10,"cargo_classes":["GENERAL_CONTAINER"]})
            (dataset/"services.json").write_text(json.dumps(services),encoding="utf-8")
            result = self.run_case(suspension,dataset=dataset)
        row = result["recovery_results"][0]
        self.assertEqual("RECOVERED",row["recovery_status"])
        ports = [row["replacement_suffix"][0]["origin_port_id"]] + [
            x["destination_port_id"] for x in row["replacement_suffix"]]
        self.assertEqual(len(ports),len(set(ports)))

    def test_overlapping_departure_events_retained_once(self):
        closure = event("close-a","PORT_CLOSURE","2025-01-02T00:00:00Z","2025-01-03T00:00:00Z",
                        target_port_id="P-A",affected_operations=["DEPARTURE"])
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-03T00:00:00Z",
                           target_service_id="S-AB")
        delay = event("delay-ab","SERVICE_DELAY","2025-01-02T00:00:00Z","2025-01-03T00:00:00Z",
                      target_service_id="S-AB",delay_hours=12)
        result = self.run_case(closure,suspension,delay)
        self.assertEqual(1,result["summary"]["affected_shipments"])
        self.assertEqual({"close-a","suspend-ab","delay-ab"},
                         set(result["recovery_results"][0]["event_ids"]))
        self.assertEqual(1,len(result["recovery_results"]))

    def test_repeat_outputs_are_byte_stable(self):
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-02T00:00:00Z","2025-01-07T00:00:00Z",
                           target_service_id="S-AB")
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            write_outputs(FIXTURE,scenario(suspension),POLICY,Path(one))
            write_outputs(FIXTURE,scenario(suspension),POLICY,Path(two))
            for name in ("scenario_manifest.json","recovery_states.json","recovery_results.json",
                         "recovery_results.csv","constraint_validation.json","summary.json"):
                self.assertEqual((Path(one)/name).read_bytes(),(Path(two)/name).read_bytes(),name)
            result_bytes = (Path(one)/"recovery_results.json").read_bytes()
            self.assertNotIn(b"INSUFFICIENT_DATA",result_bytes)
            self.assertNotIn(b'"status"',result_bytes)
            self.assertIn(b'"recovery_status"',result_bytes)


if __name__ == "__main__":
    unittest.main()
