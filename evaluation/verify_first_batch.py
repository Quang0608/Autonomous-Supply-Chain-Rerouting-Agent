#!/usr/bin/env python3
"""Independent, read-only ground-truth calculations for Phase 5.2c.

This script reads raw Phase 2 records and scenario reference JSON. It does not
import Phase 3/4 code. `generate` creates expected labels; `compare` is a later,
separate corroboration step that only reads saved Phase 3/4 outputs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys

VERSION = "phase5-independent-first-batch-1.0.0"
EPOCH = datetime(2025, 1, 1, tzinfo=timezone.utc)
MICROSECONDS_PER_DAY = Decimal(86_400_000_000)
MICROSECONDS_PER_HOUR = Decimal(3_600_000_000)
SCENARIOS = ("SC-002", "SC-007", "SC-012")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def json_ready(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    return value


def timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"expected ISO timestamp string, got {value!r}")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"timestamp must include timezone: {value}")
    return result.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    rendered = value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    head, fraction = rendered[:-1].split(".")
    fraction = fraction.rstrip("0")
    return f"{head}.{fraction}Z" if fraction else f"{head}Z"


def exact_delta(value, unit: Decimal, label: str) -> timedelta:
    micros = Decimal(str(value)) * unit
    integral = micros.to_integral_value()
    if micros != integral:
        raise ValueError(f"{label} cannot be represented at microsecond precision: {value}")
    return timedelta(microseconds=int(integral))


def planned_time(day_value) -> datetime:
    return EPOCH + exact_delta(day_value, MICROSECONDS_PER_DAY, "planned schedule offset")


def hours_delta(hours) -> timedelta:
    return exact_delta(hours, MICROSECONDS_PER_HOUR, "delay/transfer hours")


def seconds(value: timedelta) -> Decimal:
    return Decimal(value.days * 86_400 + value.seconds) + Decimal(value.microseconds) / Decimal(1_000_000)


def duration_text(value: timedelta) -> str:
    total_us = ((value.days * 86_400 + value.seconds) * 1_000_000) + value.microseconds
    sign = "-" if total_us < 0 else ""
    total_us = abs(total_us)
    total_seconds, us = divmod(total_us, 1_000_000)
    hours, rem = divmod(total_seconds, 3600)
    minutes, sec = divmod(rem, 60)
    sec_text = str(sec) + (f".{us:06d}".rstrip("0") if us else "")
    return f"{sign}{hours}h {minutes}m {sec_text}s"


def interval_contains(start: datetime, end: datetime, instant: datetime) -> bool:
    return start <= instant < end


def interval_overlaps(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> bool:
    return start < window_end and window_start < end


def source_records(dataset: Path):
    names = ("dataset_manifest.json", "ports.json", "services.json", "shipments.json", "route_plans.json")
    hashes = {name: sha256(dataset / name) for name in names}
    manifest = read_json(dataset / "dataset_manifest.json")
    if manifest.get("validation_status") != "passed":
        raise ValueError("frozen dataset manifest does not report validation_status=passed")
    if hashes["ports.json"] != manifest["canonical_file_sha256"]["ports.json"]:
        raise ValueError("ports.json hash does not match frozen dataset manifest")
    for name in ("services.json", "shipments.json", "route_plans.json"):
        if hashes[name] != manifest["canonical_file_sha256"][name]:
            raise ValueError(f"{name} hash does not match frozen dataset manifest")

    ports = read_json(dataset / "ports.json")
    services = read_json(dataset / "services.json")
    shipments = read_json(dataset / "shipments.json")
    plans = read_json(dataset / "route_plans.json")
    if len(shipments) != 1500 or len(plans) != 1500 or sum(len(p["ordered_legs"]) for p in plans) != 2936:
        raise ValueError("canonical shipment/plan/leg counts differ from research_1500")
    ship_by_id = {x["shipment_id"]: x for x in shipments}
    plan_by_id = {x["route_plan_id"]: x for x in plans}
    if len(ship_by_id) != len(shipments) or len(plan_by_id) != len(plans):
        raise ValueError("duplicate shipment_id or route_plan_id in canonical records")
    if {s["route_plan_id"] for s in shipments} != set(plan_by_id):
        raise ValueError("shipment/route-plan join is incomplete")
    if any(p["shipment_id"] not in ship_by_id or ship_by_id[p["shipment_id"]]["route_plan_id"] != p["route_plan_id"] for p in plans):
        raise ValueError("route-plan/shipment join is inconsistent")
    return manifest, hashes, ports, services, ship_by_id, plans


def scenario_event(scenario_path: Path, expected_id: str):
    scenario = read_json(scenario_path)
    if scenario.get("scenario_id") != expected_id or len(scenario.get("events", [])) != 1:
        raise ValueError(f"{scenario_path} does not contain the expected single-event scenario")
    event = scenario["events"][0]
    start, end = timestamp(event["start_time"]), timestamp(event["end_time"])
    if start >= end:
        raise ValueError(f"{expected_id} has a non-positive event interval")
    return scenario, event, start, end


def plan_leg_id(plan: dict, index: int) -> str:
    return f"{plan['route_plan_id']}:L{index + 1}"


def leg_record(plan: dict, index: int, leg: dict, operation: str, instant: datetime, matched: bool):
    return {
        "shipment_id": plan["shipment_id"], "plan_id": plan["route_plan_id"],
        "leg_id": plan_leg_id(plan, index), "service_id": leg["service_id"],
        "origin_port_id": leg["origin_port_id"], "destination_port_id": leg["destination_port_id"],
        "operation": operation, "planned_time": iso(instant), "within_event_window": matched,
    }


def provenance(scenario_id, scenario_path, notice_path, dataset_hashes, policy_path, commit, date):
    return {
        "dataset_build": "research_1500", "dataset_manifest_sha256": dataset_hashes["dataset_manifest.json"],
        "canonical_file_sha256": {k: dataset_hashes[k] for k in ("ports.json", "services.json", "shipments.json", "route_plans.json")},
        "recovery_policy_id": read_json(policy_path)["policy_id"], "recovery_policy_sha256": sha256(policy_path),
        "scenario_sha256": sha256(scenario_path), "notice_sha256": sha256(notice_path),
        "verification_script_version": VERSION, "verification_code_commit": commit,
        "verification_script_sha256": sha256(Path(__file__).resolve()),
        "verification_date": date,
    }


def base_label(sid, scenario_path, notice_path, hashes, policy_path, commit, date, scenario, event):
    event_record = {
        "event_id": event["event_id"], "type": event["type"],
        "start_time": event["start_time"], "end_time": event["end_time"],
    }
    if "target_port_id" in event:
        event_record["target_port_id"] = event["target_port_id"]
        event_record["operations"] = event.get("affected_operations", [])
    if "target_service_id" in event:
        event_record["target_service_id"] = event["target_service_id"]
        event_record["semantics"] = event.get("semantics")
    if "delay_hours" in event:
        event_record["delay_hours"] = event["delay_hours"]
    return {
        "scenario_id": sid, "label_version": "1.0", "verification_status": "VERIFIED",
        "agent_notice_ref": {"path": str(notice_path.as_posix()), "sha256": sha256(notice_path)},
        "hidden_reference_event": {
            "valid_event_expected": True, "events": [event_record],
            "unresolved_fields": [], "required_clarification": [],
        },
        "expected_impact": {}, "expected_recovery": [], "expected_missing_information": [],
        "evidence_refs": [], "independent_calculation": {},
        "observed_execution": {
            "comparison_status": "PENDING_SEPARATE_CORROBORATION",
            "phase3": None, "phase4": None,
        },
        "provenance": provenance(sid, scenario_path, notice_path, hashes, policy_path, commit, date),
        "verification_method": {
            "method": "Independent raw-record reconstruction; no Phase 3/Phase 4 modules are imported or called to generate expected labels.",
            "epoch_utc": iso(EPOCH), "interval_rule": "Half-open [start_time, end_time)",
            "author_role": "Student verification against the frozen modeled dataset and stated rules; no maritime expert review claimed.",
        },
        "review_notes": "Independent reference outcome is separate from observed tool execution and from later agent behavior.",
    }


def verify_sc002(dataset, hashes, ports, ship_by_id, plans, policy_path, commit, date):
    sid = "SC-002"
    scenario_path = Path("examples/phase5") / sid / "scenario.json"
    notice_path = scenario_path.with_name("notice.txt")
    scenario, event, start, end = scenario_event(scenario_path, sid)
    if event.get("type") != "PORT_CLOSURE" or event.get("target_port_id") != "SGSIN" or event.get("affected_operations") != ["ARRIVAL"]:
        raise ValueError("SC-002 event does not match the declared arrival closure")
    if "SGSIN" not in {p["port_id"] for p in ports}:
        raise ValueError("SC-002 target port is absent from canonical ports.json")
    arrivals = []
    matches = []
    for plan in plans:
        for index, leg in enumerate(plan["ordered_legs"]):
            if leg["destination_port_id"] != "SGSIN":
                continue
            instant = planned_time(leg["planned_arrival"])
            row = leg_record(plan, index, leg, "ARRIVAL", instant, interval_contains(start, end, instant))
            arrivals.append(row)
            if row["within_event_window"]:
                matches.append(row)
    impacted = sorted({x["shipment_id"] for x in matches})
    affected_labels = []
    for shipment_id in impacted:
        rows = [x for x in matches if x["shipment_id"] == shipment_id]
        affected_labels.append({
            "shipment_id": shipment_id, "direct_or_indirect": "DIRECT",
            "reason_codes": ["PORT_CLOSURE_ARRIVAL_OVERLAP"],
            "leg_ids": sorted({x["leg_id"] for x in rows}),
            "evidence_ids": ["SC-002-EVIDENCE-ARRIVALS"],
        })
    label = base_label(sid, scenario_path, notice_path, hashes, policy_path, commit, date, scenario, event)
    label["expected_impact"] = {
        "affected_shipments": affected_labels,
        "affected_shipment_ids": impacted,
        "unaffected_shipments_or_cohort_rule": "All other shipment IDs among the 1,500 shipment/plan joins in research_1500; every planned SGSIN arrival was enumerated.",
        "unaffected_shipment_count": len(ship_by_id) - len(impacted),
    }
    label["expected_recovery"] = [{
        "shipment_id": shipment_id, "independent_feasibility": "UNKNOWN", "reference_routes": [],
        "expected_safe_agent_behavior": "Request operator intervention; do not propose a replacement route or claim route infeasibility.",
        "reason": "A planned arrival is inside the closure, but the frozen model provides no actual vessel position/movement state at that time and the recovery policy explicitly leaves arrival closure handling unresolved with no vessel diversion or holding modeled.",
        "required_constraints": ["Do not infer vessel position or movement state.", "Do not invent authorized diversion options.", "Do not assume waiting/holding or arrival handling is permitted."],
    } for shipment_id in impacted]
    missing = [
        "Verified vessel position and movement/execution state at the closure time.",
        "Carrier-authorized diversion options, if any, for reaching or bypassing SGSIN.",
        "Supported arrival/holding/berthing procedure if waiting or delayed arrival is being considered.",
    ] if impacted else []
    label["expected_missing_information"] = missing
    label["evidence_refs"] = ["SC-002-EVIDENCE-ARRIVALS", "SC-002-EVIDENCE-POLICY", "SC-002-EVIDENCE-RECORD-JOIN"]
    label["independent_calculation"] = {
        "source_record_scope": {"plans_scanned": len(plans), "planned_legs_scanned": sum(len(p["ordered_legs"]) for p in plans), "target_arrivals_enumerated": len(arrivals)},
        "event_interval_utc": {"start": iso(start), "end": iso(end)},
        "matching_arrivals": matches, "affected_shipment_ids": impacted,
        "evidence": [
            {"evidence_id": "SC-002-EVIDENCE-ARRIVALS", "source_file": "data/builds/research_1500/route_plans.json", "source_record_keys": ["route_plan_id", "shipment_id", "ordered_legs[].destination_port_id", "ordered_legs[].planned_arrival"], "enumerated_arrivals": arrivals},
            {"evidence_id": "SC-002-EVIDENCE-POLICY", "source_file": "config/recovery_policy.json", "source_record_keys": ["arrival_closure_policy"], "value": read_json(policy_path)["arrival_closure_policy"]},
            {"evidence_id": "SC-002-EVIDENCE-RECORD-JOIN", "source_file": "data/builds/research_1500/shipments.json", "source_record_keys": ["shipment_id", "route_plan_id"], "joined_shipments": len(ship_by_id)},
        ],
    }
    label["review_notes"] = "UNKNOWN refers to route recovery feasibility. Intervention is required because the modeled evidence and policy do not support a safe operational action; this is not a finding that no route exists."
    return label


def verify_sc007(dataset, hashes, services, ship_by_id, plans, policy_path, commit, date):
    sid = "SC-007"
    scenario_path = Path("examples/phase5") / sid / "scenario.json"
    notice_path = scenario_path.with_name("notice.txt")
    scenario, event, start, end = scenario_event(scenario_path, sid)
    if event.get("type") != "SERVICE_DELAY" or event.get("target_service_id") != "SVC-35a7482f2af1d0" or event.get("semantics") != "DEPARTURE_WINDOW":
        raise ValueError("SC-007 event does not match the declared service delay")
    delay = hours_delta(event["delay_hours"])
    if delay <= timedelta(0):
        raise ValueError("SC-007 delay must be positive")
    service_ids = {s["service_id"] for s in services}
    if event["target_service_id"] not in service_ids:
        raise ValueError("SC-007 target service is absent from canonical services.json")
    departures = []
    matches = []
    for plan in plans:
        for index, leg in enumerate(plan["ordered_legs"]):
            if leg["service_id"] != event["target_service_id"]:
                continue
            instant = planned_time(leg["planned_departure"])
            row = leg_record(plan, index, leg, "DEPARTURE", instant, interval_contains(start, end, instant))
            row["planned_arrival"] = iso(planned_time(leg["planned_arrival"]))
            departures.append(row)
            if row["within_event_window"]:
                matches.append((plan, index, leg, row))

    affected_by_ship = {}
    connection_evidence = []
    for plan, index, leg, direct_row in matches:
        shipment_id = plan["shipment_id"]
        if shipment_id not in ship_by_id:
            raise ValueError(f"missing shipment record {shipment_id}")
        original_arrival = planned_time(leg["planned_arrival"])
        delayed_arrival = original_arrival + delay
        path = plan["ordered_legs"]
        leg_evidence = [{
            "leg_id": plan_leg_id(plan, index), "kind": "DIRECT_DELAY",
            "reason_code": "SERVICE_DELAY_DEPARTURE_OVERLAP", "planned_departure": iso(planned_time(leg["planned_departure"])),
            "planned_arrival": iso(original_arrival), "delay_hours": event["delay_hours"],
            "delayed_arrival": iso(delayed_arrival),
        }]
        actual_arrival = delayed_arrival
        connection_rows = []
        connection_feasible = True
        for next_index in range(index + 1, len(path)):
            next_leg = path[next_index]
            departure = planned_time(next_leg["planned_departure"])
            transfer = hours_delta(next_leg.get("min_transfer_hours", 0))
            ready = actual_arrival + transfer
            slack = departure - ready
            conn = {
                "from_leg_id": plan_leg_id(plan, next_index - 1), "next_leg_id": plan_leg_id(plan, next_index),
                "transfer_port_id": path[next_index - 1]["destination_port_id"],
                "inbound_arrival": iso(actual_arrival), "minimum_transfer_hours": next_leg.get("min_transfer_hours", 0),
                "earliest_connection_ready": iso(ready), "fixed_next_departure": iso(departure),
                "remaining_slack_seconds": seconds(slack), "remaining_slack_text": duration_text(slack),
                "connection_feasible": ready <= departure,
            }
            connection_rows.append(conn)
            if not conn["connection_feasible"]:
                connection_feasible = False
                leg_evidence.append({"leg_id": plan_leg_id(plan, next_index), "kind": "DOWNSTREAM_CONNECTION", "reason_code": "UNRESOLVED_CONNECTION"})
                break
            leg_evidence.append({"leg_id": plan_leg_id(plan, next_index), "kind": "DOWNSTREAM_CONNECTION", "reason_code": "RECOVERED_CONNECTION"})
            actual_arrival = planned_time(next_leg["planned_arrival"])
        final_eta = actual_arrival if connection_feasible else None
        deadline = planned_time(ship_by_id[shipment_id]["delivery_deadline"])
        deadline_met = final_eta is not None and final_eta <= deadline
        prior_slack = None
        if index + 1 < len(path):
            next_leg = path[index + 1]
            prior_slack = planned_time(next_leg["planned_departure"]) - (original_arrival + hours_delta(next_leg.get("min_transfer_hours", 0)))
        cohort_entry = affected_by_ship.setdefault(shipment_id, {
            "shipment_id": shipment_id, "direct_or_indirect": "DIRECT", "direct_leg_ids": [],
            "indirect_leg_ids": [], "reason_codes": [], "leg_ids": [], "evidence_ids": ["SC-007-EVIDENCE-DEPARTURES", "SC-007-EVIDENCE-PROPAGATION"],
        })
        cohort_entry["direct_leg_ids"].append(plan_leg_id(plan, index))
        cohort_entry["reason_codes"].append("SERVICE_DELAY_DEPARTURE_OVERLAP")
        for downstream in leg_evidence[1:]:
            cohort_entry["indirect_leg_ids"].append(downstream["leg_id"])
            cohort_entry["reason_codes"].append(downstream["reason_code"])
        cohort_entry["leg_ids"] = sorted(set(cohort_entry["direct_leg_ids"] + cohort_entry["indirect_leg_ids"]))
        cohort_entry["direct_leg_ids"] = sorted(set(cohort_entry["direct_leg_ids"]))
        cohort_entry["indirect_leg_ids"] = sorted(set(cohort_entry["indirect_leg_ids"]))
        cohort_entry["reason_codes"] = sorted(set(cohort_entry["reason_codes"]))
        if cohort_entry["indirect_leg_ids"]:
            cohort_entry["direct_or_indirect"] = "DIRECT_AND_INDIRECT"
        connection_evidence.append({
            "shipment_id": shipment_id, "plan_id": plan["route_plan_id"], "direct_leg_id": plan_leg_id(plan, index),
            "service_id": leg["service_id"], "planned_departure": iso(planned_time(leg["planned_departure"])),
            "planned_inbound_arrival": iso(original_arrival), "delayed_arrival": iso(delayed_arrival),
            "delay_seconds": seconds(delay), "pre_delay_connection_buffer_seconds": seconds(prior_slack) if prior_slack is not None else None,
            "pre_delay_connection_buffer_text": duration_text(prior_slack) if prior_slack is not None else None,
            "downstream_connections": connection_rows, "fixed_itinerary_continuable": connection_feasible,
            "modeled_final_eta": iso(final_eta) if final_eta is not None else None,
            "delivery_deadline": iso(deadline), "deadline_met": deadline_met,
            "safe_recovery_decision": "NO_REROUTE_REQUIRED" if connection_feasible and deadline_met else "OPERATOR_REVIEW_OR_REBOOKING_REQUIRED",
            "leg_evidence": leg_evidence,
        })

    impacted = sorted(affected_by_ship)
    affected_labels = [affected_by_ship[s] for s in impacted]
    label = base_label(sid, scenario_path, notice_path, hashes, policy_path, commit, date, scenario, event)
    label["expected_impact"] = {
        "affected_shipments": affected_labels, "affected_shipment_ids": impacted,
        "unaffected_shipments_or_cohort_rule": "Every planned leg using the target service was enumerated; a shipment is directly affected when a planned departure lies in the half-open event window. Other shipment IDs among the 1,500 joined records are unaffected by this event.",
        "unaffected_shipment_count": len(ship_by_id) - len(impacted),
    }
    recoveries = []
    for item in connection_evidence:
        recoveries.append({
            "shipment_id": item["shipment_id"], "independent_feasibility": "NOT_APPLICABLE",
            "original_itinerary_continuation": "FEASIBLE" if item["fixed_itinerary_continuable"] and item["deadline_met"] else "NOT_FEASIBLE_WITHOUT_REBOOKING",
            "reference_routes": [],
            "expected_safe_agent_behavior": "Retain the original itinerary and report the one-hour delay; do not generate an alternative recovery route.",
            "reason": "The delayed arrival plus the next leg's 12-hour minimum transfer remains before its fixed planned departure, and the unchanged downstream schedule meets the delivery deadline.",
            "required_constraints": ["Keep downstream planned departures fixed.", "Apply minimum transfer before the next departure.", "Compare final modeled ETA with shipment delivery deadline."],
        })
    label["expected_recovery"] = recoveries
    label["expected_missing_information"] = []
    label["evidence_refs"] = ["SC-007-EVIDENCE-DEPARTURES", "SC-007-EVIDENCE-PROPAGATION", "SC-007-EVIDENCE-RECORD-JOIN"]
    label["independent_calculation"] = {
        "source_record_scope": {"plans_scanned": len(plans), "planned_legs_scanned": sum(len(p["ordered_legs"]) for p in plans), "target_service_departures_enumerated": len(departures)},
        "event_interval_utc": {"start": iso(start), "end": iso(end)}, "delay_seconds": seconds(delay),
        "matching_departures": [x[3] for x in matches], "affected_shipment_ids": impacted,
        "propagation_and_deadline_calculations": connection_evidence,
        "evidence": [
            {"evidence_id": "SC-007-EVIDENCE-DEPARTURES", "source_file": "data/builds/research_1500/route_plans.json", "source_record_keys": ["route_plan_id", "shipment_id", "ordered_legs[].service_id", "ordered_legs[].planned_departure"], "enumerated_service_departures": departures},
            {"evidence_id": "SC-007-EVIDENCE-PROPAGATION", "source_file": "data/builds/research_1500/route_plans.json", "source_record_keys": ["ordered_legs[].planned_arrival", "ordered_legs[].planned_departure", "ordered_legs[].min_transfer_hours"], "calculations": connection_evidence},
            {"evidence_id": "SC-007-EVIDENCE-RECORD-JOIN", "source_file": "data/builds/research_1500/shipments.json", "source_record_keys": ["shipment_id", "delivery_deadline"], "shipment_records_scanned": len(ship_by_id)},
        ],
    }
    label["review_notes"] = "Direct delay membership, downstream connection evidence, original-itinerary continuation, and alternative-route need are distinct labels. A feasible fixed connection is not an alternative recovery route."
    return label


def verify_sc012(dataset, hashes, ports, ship_by_id, plans, policy_path, commit, date):
    sid = "SC-012"
    scenario_path = Path("examples/phase5") / sid / "scenario.json"
    notice_path = scenario_path.with_name("notice.txt")
    scenario, event, start, end = scenario_event(scenario_path, sid)
    expected_ops = {"ARRIVAL", "DEPARTURE", "TRANSSHIPMENT"}
    if event.get("type") != "PORT_CLOSURE" or event.get("target_port_id") != "ARBUE" or set(event.get("affected_operations", [])) != expected_ops:
        raise ValueError("SC-012 event does not match the declared all-operations closure")
    if "ARBUE" not in {p["port_id"] for p in ports}:
        raise ValueError("SC-012 target port is absent from canonical ports.json")
    arrivals, departures, transfers = [], [], []
    overlap_arrivals, overlap_departures, overlap_transfers = [], [], []
    for plan in plans:
        legs = plan["ordered_legs"]
        for index, leg in enumerate(legs):
            if leg["destination_port_id"] == "ARBUE":
                instant = planned_time(leg["planned_arrival"])
                row = leg_record(plan, index, leg, "ARRIVAL", instant, interval_contains(start, end, instant))
                arrivals.append(row)
                if row["within_event_window"]:
                    overlap_arrivals.append(row)
            if leg["origin_port_id"] == "ARBUE":
                instant = planned_time(leg["planned_departure"])
                row = leg_record(plan, index, leg, "DEPARTURE", instant, interval_contains(start, end, instant))
                departures.append(row)
                if row["within_event_window"]:
                    overlap_departures.append(row)
            if index + 1 < len(legs) and leg["destination_port_id"] == "ARBUE" and legs[index + 1]["origin_port_id"] == "ARBUE":
                inbound = planned_time(leg["planned_arrival"])
                outbound = planned_time(legs[index + 1]["planned_departure"])
                if outbound < inbound:
                    raise ValueError(f"negative transfer occupancy at ARBUE in plan {plan['route_plan_id']}")
                matched = interval_overlaps(inbound, outbound, start, end)
                row = {
                    "shipment_id": plan["shipment_id"], "plan_id": plan["route_plan_id"],
                    "inbound_leg_id": plan_leg_id(plan, index), "outbound_leg_id": plan_leg_id(plan, index + 1),
                    "port_id": "ARBUE", "occupancy_start_inbound_arrival": iso(inbound),
                    "occupancy_end_outbound_departure": iso(outbound), "within_event_window": matched,
                }
                transfers.append(row)
                if matched:
                    overlap_transfers.append(row)
    impacted = sorted({x["shipment_id"] for x in overlap_arrivals + overlap_departures + overlap_transfers})
    label = base_label(sid, scenario_path, notice_path, hashes, policy_path, commit, date, scenario, event)
    label["expected_impact"] = {
        "affected_shipments": [], "affected_shipment_ids": [],
        "unaffected_shipments_or_cohort_rule": "Explicit empty impact set after enumerating all canonical planned arrivals and departures at ARBUE and every consecutive-leg transfer interval at ARBUE across all 1,500 plans.",
        "unaffected_shipment_count": len(ship_by_id),
    }
    label["unaffected_recovery_classification"] = {
        "status": "UNCHANGED", "shipment_count": len(ship_by_id),
        "cohort_rule": "All 1,500 canonical shipment records; no planned operation at ARBUE overlaps the event window.",
        "recovery_plans_expected": 0,
    }
    label["expected_recovery"] = []
    label["expected_missing_information"] = []
    label["evidence_refs"] = ["SC-012-EVIDENCE-ARRIVALS", "SC-012-EVIDENCE-DEPARTURES", "SC-012-EVIDENCE-TRANSFERS", "SC-012-EVIDENCE-RECORD-JOIN"]
    label["independent_calculation"] = {
        "source_record_scope": {"plans_scanned": len(plans), "planned_legs_scanned": sum(len(p["ordered_legs"]) for p in plans)},
        "event_interval_utc": {"start": iso(start), "end": iso(end)},
        "operation_counts": {
            "arrivals_enumerated": len(arrivals), "arrivals_overlapping": len(overlap_arrivals),
            "departures_enumerated": len(departures), "departures_overlapping": len(overlap_departures),
            "transfers_enumerated": len(transfers), "transfers_overlapping": len(overlap_transfers),
            "unique_affected_shipments": len(impacted),
        },
        "affected_shipment_ids": impacted,
        "overlapping_operations": {"arrivals": overlap_arrivals, "departures": overlap_departures, "transfers": overlap_transfers},
        "evidence": [
            {"evidence_id": "SC-012-EVIDENCE-ARRIVALS", "source_file": "data/builds/research_1500/route_plans.json", "source_record_keys": ["ordered_legs[].destination_port_id", "ordered_legs[].planned_arrival"], "enumerated_operations": arrivals},
            {"evidence_id": "SC-012-EVIDENCE-DEPARTURES", "source_file": "data/builds/research_1500/route_plans.json", "source_record_keys": ["ordered_legs[].origin_port_id", "ordered_legs[].planned_departure"], "enumerated_operations": departures},
            {"evidence_id": "SC-012-EVIDENCE-TRANSFERS", "source_file": "data/builds/research_1500/route_plans.json", "source_record_keys": ["ordered_legs[].destination_port_id", "ordered_legs[].planned_arrival", "ordered_legs[].min_transfer_hours", "ordered_legs[].planned_departure"], "method": "Pair consecutive legs where inbound destination and outbound origin both equal ARBUE; test [arrival, next_departure) for strict interval overlap with the closure.", "enumerated_intervals": transfers},
            {"evidence_id": "SC-012-EVIDENCE-RECORD-JOIN", "source_file": "data/builds/research_1500/shipments.json", "source_record_keys": ["shipment_id", "route_plan_id"], "joined_shipments": len(ship_by_id)},
        ],
    }
    if impacted:
        label["verification_status"] = "AMBIGUOUS"
        label["review_notes"] = "Unexpected operation overlap found; investigate before freezing the no-impact label."
    else:
        label["review_notes"] = "The empty impact set is supported by the complete modeled operation scan. All shipments remain unchanged; no recovery action or route is warranted."
    return label


def git_commit(root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNAVAILABLE"


def generate(args, root: Path):
    dataset = (root / args.dataset).resolve()
    policy_path = (root / "config/recovery_policy.json").resolve()
    manifest, hashes, ports, services, ship_by_id, plans = source_records(dataset)
    date = args.verification_date or datetime.now(timezone.utc).date().isoformat()
    if len(date) != 10:
        raise ValueError("--verification-date must use YYYY-MM-DD")
    commit = git_commit(root)
    labels = [
        verify_sc002(dataset, hashes, ports, ship_by_id, plans, policy_path, commit, date),
        verify_sc007(dataset, hashes, services, ship_by_id, plans, policy_path, commit, date),
        verify_sc012(dataset, hashes, ports, ship_by_id, plans, policy_path, commit, date),
    ]
    output = (root / args.ground_truth).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for label in labels:
        path = output / f"{label['scenario_id']}.json"
        path.write_text(json.dumps(json_ready(label), sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"generated {path.relative_to(root)} status={label['verification_status']} impacted={label['expected_impact']['affected_shipment_ids']}")
    after = {name: sha256(dataset / name) for name in hashes}
    if after != hashes:
        raise RuntimeError("canonical dataset changed during verification")
    print(json.dumps({"dataset_hashes_unchanged": True, "canonical_hashes": hashes, "manifest_status": manifest["validation_status"]}, indent=2))


def compare(args, root: Path):
    ground_truth = (root / args.ground_truth).resolve()
    run_root = (root / args.run_outputs).resolve()
    for sid in SCENARIOS:
        label_path = ground_truth / f"{sid}.json"
        label = read_json(label_path)
        if label.get("scenario_id") != sid or label.get("verification_status") not in {"VERIFIED", "AMBIGUOUS", "UNVERIFIABLE"}:
            raise ValueError(f"missing/faulty finalized independent label for {sid}")
        p3_dir, p4_dir = run_root / sid / "phase3", run_root / sid / "phase4"
        p3_impacts = read_json(p3_dir / "shipment_impacts.json")
        p3_summary = read_json(p3_dir / "summary.json")
        p4_results = read_json(p4_dir / "recovery_results.json")
        p4_summary = read_json(p4_dir / "summary.json")
        independent_ids = label["expected_impact"]["affected_shipment_ids"]
        observed_p3_ids = sorted({x["shipment_id"] for x in p3_impacts})
        observed_p4_affected = sorted(x["shipment_id"] for x in p4_results if x["recovery_status"] != "UNCHANGED")
        relevant_p4 = [x for x in p4_results if x["shipment_id"] in independent_ids]
        p3_agrees = independent_ids == observed_p3_ids
        p4_membership_agrees = independent_ids == observed_p4_affected
        p4_statuses = {x["shipment_id"]: x["recovery_status"] for x in relevant_p4}
        observed = {
            "comparison_status": "COMPARED_AFTER_INDEPENDENT_LABEL_GENERATION",
            "phase3": {
                "output_refs": [str((p3_dir / "shipment_impacts.json").relative_to(root)), str((p3_dir / "summary.json").relative_to(root))],
                "output_sha256": {"shipment_impacts.json": sha256(p3_dir / "shipment_impacts.json"), "summary.json": sha256(p3_dir / "summary.json")},
                "affected_shipment_ids": observed_p3_ids, "summary": p3_summary,
                "agrees_with_independent_membership": p3_agrees,
            },
            "phase4": {
                "output_refs": [str((p4_dir / "recovery_results.json").relative_to(root)), str((p4_dir / "summary.json").relative_to(root))],
                "output_sha256": {"recovery_results.json": sha256(p4_dir / "recovery_results.json"), "summary.json": sha256(p4_dir / "summary.json")},
                "non_unchanged_shipment_ids": observed_p4_affected, "status_distribution": p4_summary["statuses"],
                "affected_shipment_statuses": p4_statuses,
                "reason_codes": {x["shipment_id"]: x.get("reason_code") for x in relevant_p4},
                "missing_information": {x["shipment_id"]: x.get("missing_information", []) for x in relevant_p4},
                "recovery_plan": {x["shipment_id"]: x.get("recovery_plan") for x in relevant_p4},
                "agrees_with_independent_membership": p4_membership_agrees,
            },
        }
        label["observed_execution"] = observed
        label_path.write_text(json.dumps(json_ready(label), sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"compared {sid}: Phase3-membership={p3_agrees}; Phase4-membership={p4_membership_agrees}; Phase4-statuses={p4_statuses}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "compare"), help="generate independent labels or append later tool-output corroboration")
    parser.add_argument("--dataset", default="data/builds/research_1500")
    parser.add_argument("--ground-truth", default="evaluation/ground_truth")
    parser.add_argument("--run-outputs", default="data/simulations/phase5/phase5_2b")
    parser.add_argument("--verification-date", help="fixed date YYYY-MM-DD; defaults to current UTC date")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.command == "generate":
        generate(args, root)
    else:
        compare(args, root)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, json.JSONDecodeError, ArithmeticError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
