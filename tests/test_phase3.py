import copy
import json
from pathlib import Path
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
        _, hit, outcomes, _ = self.analyze(scenario(event("short","SERVICE_DELAY","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_service_id="TEST-SVC-AB",delay_hours=1)))
        self.assertEqual("DELAYED",outcomes[0]["status"])
        self.assertEqual("2025-01-17T01:00:00Z",outcomes[0]["baseline_eta"])

    def test_multiple_causes_deduplicated_and_closure_wins_delay(self):
        _, hit, _, _ = self.analyze(scenario(
            event("closure","PORT_CLOSURE","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_port_id="TEST-A",affected_operations=["DEPARTURE"]),
            event("delay","SERVICE_DELAY","2025-01-11T00:00:00Z","2025-01-12T00:00:00Z",target_service_id="TEST-SVC-AB",delay_hours=24)))
        self.assertEqual(1,len(hit))
        self.assertEqual(["closure"],[x["event_id"] for x in hit[0]["causes"]])

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
