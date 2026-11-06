import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from src.maritime.phase3 import ScenarioError, analyze, load_json, validate_scenario, write_outputs

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase3/minimal"


def event(event_id, kind, start, end, **kwargs):
    return {"event_id":event_id,"type":kind,"start_time":start,"end_time":end,**kwargs}


def scenario(*events):
    return {"schema_version":"1.0","scenario_id":"synthetic-test","events":list(events)}


class Phase3Tests(unittest.TestCase):
    def setUp(self):
        self.ports = load_json(FIXTURE / "ports.json")
        self.services = load_json(FIXTURE / "services.json")

    def analyze(self, value):
        return analyze(FIXTURE, value)

    def test_departure_overlap_and_boundary(self):
        sc, impacts, outcomes, _ = self.analyze(scenario(event("e1","PORT_CLOSURE","2025-01-11T00:00:00Z","2025-01-11T01:00:00Z",target_port_id="TEST-A",affected_operations=["DEPARTURE"])))
        self.assertEqual(["TEST-SHIP-1"],[x["shipment_id"] for x in impacts])
        self.assertEqual("PORT_CLOSURE_DEPARTURE_OVERLAP",impacts[0]["causes"][0]["reason_code"])
        # Half-open end excludes the exact departure timestamp.
        _, impacts, outcomes, _ = self.analyze(scenario(event("e2","PORT_CLOSURE","2025-01-10T00:00:00Z","2025-01-11T00:00:00Z",target_port_id="TEST-A",affected_operations=["DEPARTURE"])))
        self.assertEqual([], impacts)
        self.assertEqual("UNAFFECTED",outcomes[0]["status"])
        # A closure after departure does not invalidate an already completed operation.
        _, impacts, _, _ = self.analyze(scenario(event("e3","PORT_CLOSURE","2025-01-11T01:00:00Z","2025-01-12T00:00:00Z",target_port_id="TEST-A",affected_operations=["DEPARTURE"])))
        self.assertEqual([],impacts)

    def test_arrival_start_included_and_end_excluded(self):
        _, hit, _, _ = self.analyze(scenario(event("e1","PORT_CLOSURE","2025-01-13T00:00:00Z","2025-01-14T00:00:00Z",target_port_id="TEST-B",affected_operations=["ARRIVAL"])))
        _, miss, _, _ = self.analyze(scenario(event("e2","PORT_CLOSURE","2025-01-12T00:00:00Z","2025-01-13T00:00:00Z",target_port_id="TEST-B",affected_operations=["ARRIVAL"])))
        self.assertEqual("PORT_CLOSURE_ARRIVAL_OVERLAP",hit[0]["causes"][0]["reason_code"])
        self.assertEqual([],miss)

    def test_service_suspension_and_delay_cascade(self):
        _, hit, _, _ = self.analyze(scenario(event("sus","SERVICE_SUSPENSION","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_service_id="TEST-SVC-AB")))
        self.assertEqual("SERVICE_SUSPENSION_DEPARTURE_OVERLAP",hit[0]["causes"][0]["reason_code"])
        _, hit, outcomes, _ = self.analyze(scenario(event("delay","SERVICE_DELAY","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_service_id="TEST-SVC-AB",delay_hours=72)))
        self.assertEqual(["TEST-PLAN-1:L2"],hit[0]["indirect_leg_ids"])
        self.assertEqual("UNRESOLVED_CONNECTION",outcomes[0]["status"])
        unresolved = next(c for c in hit[0]["causes"] if c["reason_code"] == "UNRESOLVED_CONNECTION")
        self.assertEqual("delay",unresolved["event_id"])
        self.assertEqual("2025-01-16T00:00:00Z",unresolved["conflict_time"])
        self.assertIsNone(outcomes[0]["baseline_eta"])
        _, hit, outcomes, _ = self.analyze(scenario(event("short","SERVICE_DELAY","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_service_id="TEST-SVC-AB",delay_hours=1)))
        self.assertEqual("DELAYED",outcomes[0]["status"])
        self.assertEqual("2025-01-17T00:00:00Z",outcomes[0]["baseline_eta"])
        self.assertEqual("RECOVERED_CONNECTION",next(c["reason_code"] for c in hit[0]["causes"] if c["operation"] == "DOWNSTREAM_CONNECTION"))

    def test_multiple_causes_deduplicated_and_closure_wins_delay(self):
        _, hit, _, _ = self.analyze(scenario(
            event("closure","PORT_CLOSURE","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_port_id="TEST-A",affected_operations=["DEPARTURE"]),
            event("delay","SERVICE_DELAY","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_service_id="TEST-SVC-AB",delay_hours=24)))
        self.assertEqual(1,len(hit))
        self.assertEqual(["closure","delay"],[x["event_id"] for x in hit[0]["causes"]])
        self.assertFalse(hit[0]["causes"][1]["effect_applied"])

    def test_multiple_leg_delays_use_actual_final_eta_and_deadline(self):
        delay_first = event("delay-first","SERVICE_DELAY","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_service_id="TEST-SVC-AB",delay_hours=1)
        delay_second = event("delay-second","SERVICE_DELAY","2025-01-15T00:00:00Z","2025-01-16T00:00:00Z",target_service_id="TEST-SVC-BC",delay_hours=2)
        _, impacts, outcomes, _ = self.analyze(scenario(delay_first,delay_second))
        self.assertEqual(["TEST-SHIP-1"],[x["shipment_id"] for x in impacts])
        self.assertEqual(["TEST-PLAN-1:L1","TEST-PLAN-1:L2"],impacts[0]["direct_leg_ids"])
        self.assertEqual(["delay-first","delay-second"],[x["event_id"] for x in impacts[0]["causes"] if x["operation"] == "DEPARTURE"])
        self.assertEqual("2025-01-17T02:00:00Z",outcomes[0]["baseline_eta"])
        self.assertEqual("DELAYED",outcomes[0]["status"])

        # The deadline comparison uses the resolved ETA (02:00), not the
        # sum of all disruptions added to the original ETA (03:00).
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            for name in ("dataset_manifest.json","ports.json","services.json","shipments.json","route_plans.json"):
                shutil.copyfile(FIXTURE/name,dataset/name)
            ships = load_json(dataset/"shipments.json")
            ships[0]["delivery_deadline"] = 16.05  # 2025-01-17 01:12 UTC
            (dataset/"shipments.json").write_text(json.dumps(ships),encoding="utf-8")
            _, _, deadline_outcomes, _ = analyze(dataset,scenario(delay_first,delay_second))
        self.assertEqual("2025-01-17T02:00:00Z",deadline_outcomes[0]["baseline_eta"])
        self.assertEqual("DEADLINE_MISSED",deadline_outcomes[0]["status"])

    def test_shifted_arrival_is_checked_against_closure_interval(self):
        delay = event("inbound-delay","SERVICE_DELAY","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_service_id="TEST-SVC-AB",delay_hours=2)
        closure = event("shifted-arrival-closure","PORT_CLOSURE","2025-01-13T01:00:00Z","2025-01-13T03:00:00Z",target_port_id="TEST-B",affected_operations=["ARRIVAL"])
        _, impacts, outcomes, _ = self.analyze(scenario(delay,closure))
        self.assertEqual(["TEST-SHIP-1"],[x["shipment_id"] for x in impacts])
        cause = next(c for c in impacts[0]["causes"] if c["event_id"] == "shifted-arrival-closure")
        self.assertEqual("PORT_CLOSURE_ARRIVAL_OVERLAP",cause["reason_code"])
        self.assertEqual("2025-01-13T02:00:00Z",cause["conflict_time"])
        self.assertEqual("BLOCKED",outcomes[0]["status"])
        self.assertIsNone(outcomes[0]["baseline_eta"])

    def test_unresolved_connection_stops_cascade_before_third_leg(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            for name in ("dataset_manifest.json","ports.json","services.json","shipments.json","route_plans.json"):
                shutil.copyfile(FIXTURE/name,dataset/name)
            ports = load_json(dataset/"ports.json")
            ports.append({"port_id":"TEST-D","name":"Test D"})
            (dataset/"ports.json").write_text(json.dumps(ports),encoding="utf-8")
            services = load_json(dataset/"services.json")
            services.append({"service_id":"TEST-SVC-CD","origin_port_id":"TEST-C","destination_port_id":"TEST-D"})
            (dataset/"services.json").write_text(json.dumps(services),encoding="utf-8")
            plans = load_json(dataset/"route_plans.json")
            plans[0]["ordered_legs"].append({"sequence":3,"service_id":"TEST-SVC-CD","origin_port_id":"TEST-C","destination_port_id":"TEST-D","planned_departure":20,"planned_arrival":22,"min_transfer_hours":12})
            plans[0]["estimated_arrival"] = 22
            (dataset/"route_plans.json").write_text(json.dumps(plans),encoding="utf-8")
            delay = event("long-delay","SERVICE_DELAY","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_service_id="TEST-SVC-AB",delay_hours=72)
            _, impacts, outcomes, _ = analyze(dataset,scenario(delay))
        self.assertEqual(["TEST-PLAN-1:L2"],impacts[0]["indirect_leg_ids"])
        self.assertEqual(["TEST-PLAN-1:L1"],impacts[0]["direct_leg_ids"])
        self.assertEqual("UNRESOLVED_CONNECTION",outcomes[0]["status"])
        self.assertIsNone(outcomes[0]["baseline_eta"])

    def test_multiple_closures_and_suspension_preserve_event_ids_once(self):
        closure_a = event("close-a","PORT_CLOSURE","2025-01-11T00:00:00Z","2025-01-11T02:00:00Z",target_port_id="TEST-A",affected_operations=["DEPARTURE"])
        closure_b = event("close-b","PORT_CLOSURE","2025-01-11T00:00:00Z","2025-01-11T03:00:00Z",target_port_id="TEST-A",affected_operations=["DEPARTURE"])
        suspension = event("suspend-ab","SERVICE_SUSPENSION","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_service_id="TEST-SVC-AB")
        delay = event("delay-ab","SERVICE_DELAY","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_service_id="TEST-SVC-AB",delay_hours=4)
        _, impacts, outcomes, summary = self.analyze(scenario(closure_a,closure_b,suspension,delay))
        self.assertEqual(1,len(impacts))
        self.assertEqual({"close-a","close-b","suspend-ab","delay-ab"},{c["event_id"] for c in impacts[0]["causes"]})
        self.assertEqual("BLOCKED",outcomes[0]["status"])
        self.assertEqual(1,summary["summary"]["affected_shipments"])

    def test_closures_on_different_legs_do_not_duplicate_shipment(self):
        first = event("close-first","PORT_CLOSURE","2025-01-11T00:00:00Z","2025-01-11T01:00:00Z",target_port_id="TEST-A",affected_operations=["DEPARTURE"])
        second = event("close-second","PORT_CLOSURE","2025-01-15T00:00:00Z","2025-01-15T01:00:00Z",target_port_id="TEST-B",affected_operations=["DEPARTURE"])
        _, impacts, outcomes, result = self.analyze(scenario(first,second))
        self.assertEqual(1,len(impacts))
        self.assertEqual(["TEST-PLAN-1:L1","TEST-PLAN-1:L2"],impacts[0]["direct_leg_ids"])
        self.assertEqual({"close-first","close-second"},{c["event_id"] for c in impacts[0]["causes"]})
        self.assertEqual(1,result["summary"]["affected_shipments"])
        self.assertEqual("BLOCKED",outcomes[0]["status"])

    def test_no_impact_port_is_valid(self):
        _, hit, outcomes, result = self.analyze(scenario(event("e","PORT_CLOSURE","2025-01-01T00:00:00Z","2025-01-02T00:00:00Z",target_port_id="TEST-NONE")))
        self.assertEqual([],hit)
        self.assertEqual("UNAFFECTED",outcomes[0]["status"])
        self.assertEqual(0,result["summary"]["affected_shipments"])

    def test_rejects_bad_targets_times_intervals_and_delay(self):
        malformed = [
            event("e","PORT_CLOSURE","2025-01-01","2025-01-02Z",target_port_id="TEST-A"),
            event("e","PORT_CLOSURE","2025-01-02T00:00:00Z","2025-01-02T00:00:00Z",target_port_id="TEST-A"),
            event("e","PORT_CLOSURE","2025-01-01T00:00:00Z","2025-01-02T00:00:00Z",target_port_id="missing"),
            event("e","PORT_CLOSURE","2025-01-01T00:00:00Z","2025-01-02T00:00:00Z",target_port_id=["TEST-A"]),
            event("e",["PORT_CLOSURE"],"2025-01-01T00:00:00Z","2025-01-02T00:00:00Z",target_port_id="TEST-A"),
            event("e","SERVICE_DELAY","2025-01-01T00:00:00Z","2025-01-02T00:00:00Z",target_service_id="TEST-SVC-AB",delay_hours=-1),
        ]
        for bad in malformed:
            with self.subTest(event=bad), self.assertRaises(ScenarioError): validate_scenario(scenario(bad),self.ports,self.services)
        duplicate = event("same","PORT_CLOSURE","2025-01-01T00:00:00Z","2025-01-02T00:00:00Z",target_port_id="TEST-A")
        with self.assertRaises(ScenarioError): validate_scenario(scenario(duplicate,copy.deepcopy(duplicate)),self.ports,self.services)
        zero = event("zero","SERVICE_DELAY","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_service_id="TEST-SVC-AB",delay_hours=0)
        _, hit, outcomes, _ = self.analyze(scenario(zero))
        self.assertEqual([],hit)
        self.assertEqual("UNAFFECTED",outcomes[0]["status"])

    def test_canonical_outputs_repeat_except_run_manifest_timestamp(self):
        sc = scenario(event("e","PORT_CLOSURE","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_port_id="TEST-A",affected_operations=["DEPARTURE"]))
        before = {name:(FIXTURE/name).read_bytes() for name in ("ports.json","services.json","shipments.json","route_plans.json")}
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            write_outputs(FIXTURE,sc,Path(one));write_outputs(FIXTURE,sc,Path(two))
            for name in ("event_impacts.json","shipment_impacts.json","no_recovery_outcomes.json","summary.json","shipment_impacts.csv","no_recovery_outcomes.csv"):
                self.assertEqual((Path(one)/name).read_bytes(),(Path(two)/name).read_bytes(),name)
        self.assertEqual(before,{name:(FIXTURE/name).read_bytes() for name in before})


if __name__ == "__main__":
    unittest.main()
