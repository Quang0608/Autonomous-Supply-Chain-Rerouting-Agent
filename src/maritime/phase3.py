"""Deterministic temporal disruption analysis over canonical Phase 2 files."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path

SCHEMA_VERSION = "1.0"
EPOCH = datetime(2025, 1, 1, tzinfo=timezone.utc)
EVENT_TYPES = {"PORT_CLOSURE", "SERVICE_SUSPENSION", "SERVICE_DELAY"}
OPERATIONS = {"ARRIVAL", "DEPARTURE", "TRANSSHIPMENT"}


class ScenarioError(ValueError):
    """A scenario is malformed or targets an entity outside its dataset."""


def parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ScenarioError("timestamps must be ISO 8601 strings with a timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScenarioError(f"invalid ISO 8601 timestamp: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ScenarioError(f"timestamp must include a timezone: {value}")
    return parsed.astimezone(timezone.utc)


def day_time(day: float) -> datetime:
    return EPOCH + timedelta(days=float(day))


def iso(value: datetime) -> str:
    rendered = value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if "." not in rendered:
        return rendered
    head, fraction = rendered[:-1].split(".")
    fraction = fraction.rstrip("0")
    return f"{head}.{fraction}Z" if fraction else f"{head}Z"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_scenario(scenario: dict, ports: list[dict], services: list[dict]) -> dict:
    if not isinstance(scenario, dict) or scenario.get("schema_version") != SCHEMA_VERSION:
        raise ScenarioError(f"schema_version must be {SCHEMA_VERSION}")
    if not scenario.get("scenario_id") or not isinstance(scenario.get("scenario_id"), str):
        raise ScenarioError("scenario_id must be a non-empty string")
    events = scenario.get("events")
    if not isinstance(events, list) or not events:
        raise ScenarioError("events must be a non-empty array")
    port_ids = {p["port_id"] for p in ports}
    service_ids = {s["service_id"] for s in services}
    seen = set()
    normalized = []
    for event in events:
        if not isinstance(event, dict):
            raise ScenarioError("each event must be an object")
        eid = event.get("event_id")
        if not isinstance(eid, str) or not eid or eid in seen:
            raise ScenarioError("event_id values must be unique non-empty strings")
        seen.add(eid)
        kind = event.get("type")
        if not isinstance(kind, str) or kind not in EVENT_TYPES:
            raise ScenarioError(f"unsupported event type: {kind}")
        start, end = parse_time(event.get("start_time")), parse_time(event.get("end_time"))
        if start >= end:
            raise ScenarioError(f"event {eid} interval must have positive duration")
        row = dict(event, start_time=iso(start), end_time=iso(end))
        if kind == "PORT_CLOSURE":
            target = event.get("target_port_id")
            if not isinstance(target, str) or target not in port_ids:
                raise ScenarioError(f"unknown target port: {target}")
            ops = event.get("affected_operations", sorted(OPERATIONS))
            if not isinstance(ops, list) or not ops or any(not isinstance(op, str) for op in ops) or not set(ops) <= OPERATIONS:
                raise ScenarioError(f"event {eid} has invalid affected_operations")
            row["affected_operations"] = sorted(set(ops))
        else:
            target = event.get("target_service_id")
            if not isinstance(target, str) or target not in service_ids:
                raise ScenarioError(f"unknown target service: {target}")
            semantics = event.get("semantics", "DEPARTURE_WINDOW")
            if semantics != "DEPARTURE_WINDOW":
                raise ScenarioError("service suspension/delay semantics must be DEPARTURE_WINDOW")
            row["semantics"] = semantics
            if kind == "SERVICE_DELAY":
                delay = event.get("delay_hours")
                if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay < 0:
                    raise ScenarioError(f"event {eid} delay_hours must be nonnegative")
                row["delay_hours"] = float(delay)
        normalized.append(row)
    return {**scenario, "events": normalized}


def _inside(t: datetime, event: dict) -> bool:
    return parse_time(event["start_time"]) <= t < parse_time(event["end_time"])


def _overlap(start: datetime, end: datetime, event: dict) -> bool:
    return start < parse_time(event["end_time"]) and parse_time(event["start_time"]) < end


def analyze(dataset_dir: Path, scenario_raw: dict) -> tuple[dict, list[dict], list[dict], dict]:
    ports = load_json(dataset_dir / "ports.json")
    services = load_json(dataset_dir / "services.json")
    shipments = load_json(dataset_dir / "shipments.json")
    plans = load_json(dataset_dir / "route_plans.json")
    scenario = validate_scenario(scenario_raw, ports, services)
    service_by_id = {x["service_id"]: x for x in services}
    plan_by_id = {x["route_plan_id"]: x for x in plans}
    impact_rows, outcome_rows = [], []
    earliest = latest = None
    for shipment in sorted(shipments, key=lambda x: x["shipment_id"]):
        plan = plan_by_id[shipment["route_plan_id"]]
        legs = plan["ordered_legs"]
        direct, indirect, causes = [], [], []
        delayed = {}
        for index, leg in enumerate(legs):
            dep, arr = day_time(leg["planned_departure"]), day_time(leg["planned_arrival"])
            service = service_by_id[leg["service_id"]]
            for event in scenario["events"]:
                hit = False
                reason = None
                target_id = event.get("target_port_id", event.get("target_service_id"))
                if event["type"] == "PORT_CLOSURE":
                    target = event["target_port_id"]
                    ops = event["affected_operations"]
                    if "DEPARTURE" in ops and leg["origin_port_id"] == target and _inside(dep, event):
                        hit, reason = True, "PORT_CLOSURE_DEPARTURE_OVERLAP"
                    elif "ARRIVAL" in ops and leg["destination_port_id"] == target and _inside(arr, event):
                        hit, reason = True, "PORT_CLOSURE_ARRIVAL_OVERLAP"
                    elif "TRANSSHIPMENT" in ops and index < len(legs)-1 and leg["destination_port_id"] == target:
                        transfer_end = day_time(legs[index+1]["planned_departure"])
                        if _overlap(arr, transfer_end, event):
                            hit, reason = True, "PORT_CLOSURE_TRANSFER_OCCUPANCY_OVERLAP"
                elif service["service_id"] == event.get("target_service_id") and _inside(dep, event) and (event["type"] != "SERVICE_DELAY" or event["delay_hours"] > 0):
                    hit = True
                    reason = "SERVICE_SUSPENSION_DEPARTURE_OVERLAP" if event["type"] == "SERVICE_SUSPENSION" else "SERVICE_DELAY_DEPARTURE_OVERLAP"
                if hit:
                    direct.append((index, event, reason, target_id, dep if "DEPARTURE" in (reason or "") else arr))
        # A closure controls the same leg departure when it overlaps a delay event.
        closure_indexes = {i for i, e, reason, _, _ in direct if e["type"] == "PORT_CLOSURE" and "DEPARTURE" in reason}
        direct = [x for x in direct if not (x[1]["type"] == "SERVICE_DELAY" and x[0] in closure_indexes)]
        for index, event, _, _, _ in direct:
            if event["type"] == "SERVICE_DELAY":
                delayed[index] = delayed.get(index, 0.0) + event["delay_hours"]
        # Propagate modeled delay through the existing itinerary only. Never rebook a missed connection.
        cumulative = 0.0
        direct_indexes = {x[0] for x in direct}
        for index, leg in enumerate(legs):
            if index in delayed:
                cumulative += delayed[index]
            if cumulative and index not in direct_indexes:
                dep = day_time(leg["planned_departure"])
                prev_arr = day_time(legs[index-1]["planned_arrival"]) + timedelta(hours=cumulative) if index else dep
                min_transfer = float(leg.get("min_transfer_hours", 0))
                if index and prev_arr + timedelta(hours=min_transfer) > dep:
                    indirect.append((index, leg, "UNRESOLVED_CONNECTION", cumulative))
                elif index:
                    indirect.append((index, leg, "CASCADED_ARRIVAL_DELAY", cumulative))
        causes = []
        for index, event, reason, target, when in direct:
            item = {"event_id": event["event_id"], "target_entity_id": target,
                    "event_type": event["type"], "leg_id": f'{plan["route_plan_id"]}:L{index+1}',
                    "service_id": legs[index]["service_id"], "operation": ("DEPARTURE" if "DEPARTURE" in reason else "ARRIVAL" if "ARRIVAL" in reason else "TRANSSHIPMENT"),
                    "conflict_time": iso(when), "reason_code": reason}
            if item not in causes: causes.append(item)
            earliest = min(earliest, when) if earliest else when
            latest = max(latest, when) if latest else when
        for index, leg, reason, hours in indirect:
            causes.append({"event_id": next((e["event_id"] for e in scenario["events"] if e["type"] == "SERVICE_DELAY"), ""),
                           "target_entity_id": leg["service_id"], "event_type": "SERVICE_DELAY",
                           "leg_id": f'{plan["route_plan_id"]}:L{index+1}', "service_id": leg["service_id"],
                           "operation": "DOWNSTREAM_CONNECTION", "conflict_time": iso(day_time(leg["planned_departure"])),
                           "reason_code": reason, "propagated_delay_hours": round(hours, 6)})
        if direct or indirect:
            direct_ids = sorted({x[0] for x in direct})
            indirect_ids = sorted({x[0] for x in indirect})
            direct_legs = sorted({f'{plan["route_plan_id"]}:L{i+1}' for i in direct_ids})
            indirect_legs = sorted({f'{plan["route_plan_id"]}:L{i+1}' for i in indirect_ids})
            impact_rows.append({"shipment_id": shipment["shipment_id"], "plan_id": plan["route_plan_id"],
                "directly_affected": bool(direct), "indirectly_affected": bool(indirect),
                "direct_leg_ids": direct_legs, "indirect_leg_ids": indirect_legs,
                "original_eta": iso(day_time(plan["estimated_arrival"])),
                "deadline": iso(day_time(shipment["delivery_deadline"])), "causes": causes})
            status = "BLOCKED" if any(x["event_type"] in ("PORT_CLOSURE", "SERVICE_SUSPENSION") for x in causes) else "DELAYED"
            if any(x["reason_code"] == "UNRESOLVED_CONNECTION" for x in causes): status = "UNRESOLVED_CONNECTION"
            elif status == "DELAYED" and any(x["reason_code"] == "CASCADED_ARRIVAL_DELAY" for x in causes): status = "DELAYED"
            if status == "DELAYED" and any(x["reason_code"] == "SERVICE_DELAY_DEPARTURE_OVERLAP" for x in causes):
                event = next(e for e in scenario["events"] if e["type"] == "SERVICE_DELAY" and any(c["event_id"] == e["event_id"] for c in causes))
                new_eta = day_time(plan["estimated_arrival"]) + timedelta(hours=event["delay_hours"])
                if new_eta > day_time(shipment["delivery_deadline"]): status = "DEADLINE_MISSED"
            eta = iso(day_time(plan["estimated_arrival"]) + timedelta(hours=sum(delayed.values()))) if status in ("DELAYED", "DEADLINE_MISSED") else None
            if status == "BLOCKED": reason = "NO_RECOVERY_POLICY_BLOCKED_OPERATION"
            elif status == "UNRESOLVED_CONNECTION": reason = "REBOOKING_POLICY_NOT_MODELED"
            elif status == "DEADLINE_MISSED": reason = "PROPAGATED_ETA_EXCEEDS_DEADLINE"
            else: reason = "MODELED_DELAY_PROPAGATED"
        else:
            status, reason, eta = "UNAFFECTED", "NO_OPERATION_TIME_OVERLAP", iso(day_time(plan["estimated_arrival"]))
        outcome_rows.append({"shipment_id": shipment["shipment_id"], "plan_id": plan["route_plan_id"],
            "status": status, "original_eta": iso(day_time(plan["estimated_arrival"])), "baseline_eta": eta,
            "deadline": iso(day_time(shipment["delivery_deadline"])), "reason_code": reason,
            "direct_impact": bool(direct), "indirect_impact": bool(indirect)})
    run_manifest = {"schema_version": SCHEMA_VERSION, "scenario_id": scenario["scenario_id"],
        "software_version": "phase3-temporal-1.0.0",
        "dataset_dir": str(dataset_dir), "dataset_manifest_sha256": hashlib.sha256((dataset_dir/"dataset_manifest.json").read_bytes()).hexdigest(),
        "scenario_sha256": hashlib.sha256(json.dumps(scenario_raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "schedule_derivation": {"epoch_utc": iso(EPOCH), "numeric_day_unit": "24 hours", "service_suspension_semantics": "departure time in half-open event interval", "delay_semantics": "delay applied to affected departures; propagated against fixed downstream departures"},
        "counts": {"shipments": len(shipments), "plans": len(plans), "legs": sum(len(p["ordered_legs"]) for p in plans)}}
    statuses = {s: sum(x["status"] == s for x in outcome_rows) for s in ("UNAFFECTED", "DELAYED", "DEADLINE_MISSED", "BLOCKED", "UNRESOLVED_CONNECTION", "OUTCOME_UNDETERMINED")}
    summary = {"scenario_id": scenario["scenario_id"], "total_shipments": len(shipments),
        "directly_affected": sum(x["directly_affected"] for x in impact_rows),
        "indirectly_affected": sum(x["indirectly_affected"] for x in impact_rows),
        "affected_shipments": len(impact_rows), "unaffected": len(shipments)-len(impact_rows),
        "disrupted_legs": len({leg for x in impact_rows for leg in x["direct_leg_ids"]+x["indirect_leg_ids"]}),
        "no_recovery_statuses": statuses, "status_percentages": {k: round(v*100/len(shipments), 4) for k,v in statuses.items()},
        "earliest_affected_operation": iso(earliest) if earliest else None, "latest_affected_operation": iso(latest) if latest else None,
        "event_types": sorted({e["type"] for e in scenario["events"]}),
        "blocked_count": statuses["BLOCKED"], "unresolved_count": statuses["UNRESOLVED_CONNECTION"]}
    return scenario, impact_rows, outcome_rows, {"manifest":run_manifest,"summary":summary}


def write_outputs(dataset_dir: Path, scenario_raw: dict, out_dir: Path, seed: int = 42) -> dict:
    scenario, impacts, outcomes, reports = analyze(dataset_dir, scenario_raw)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = dict(reports["manifest"], seed=seed, run_id=scenario["scenario_id"], run_utc=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
    files = {"scenario_manifest.json":manifest, "event_impacts.json":{"scenario_id":scenario["scenario_id"],"impacts":impacts},
             "shipment_impacts.json":impacts, "no_recovery_outcomes.json":outcomes, "summary.json":reports["summary"]}
    for name, value in files.items(): (out_dir/name).write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    import csv
    for name, rows in (("shipment_impacts.csv", impacts), ("no_recovery_outcomes.csv", outcomes)):
        keys = list(rows[0]) if rows else (["shipment_id","plan_id","directly_affected","indirectly_affected","direct_leg_ids","indirect_leg_ids","original_eta","deadline","causes"] if name.startswith("shipment") else ["shipment_id","plan_id","status","original_eta","baseline_eta","deadline","reason_code","direct_impact","indirect_impact"])
        with (out_dir/name).open("w",encoding="utf-8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
            for row in rows: writer.writerow({k:json.dumps(v,sort_keys=True) if isinstance(v,(list,dict)) else v for k,v in row.items()})
    return reports["summary"]
