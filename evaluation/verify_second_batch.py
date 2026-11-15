#!/usr/bin/env python3
"""Independent Phase 5.2e reference calculations for SC-001/004/008.

Generation reads only the frozen canonical records, policy and structured
scenario inputs. It has no dependency on the Phase 3/4 implementation and does
not read saved execution outputs. Comparison is a separate, read-only reference
step that checks saved outputs against those labels.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import subprocess
import sys

VERSION = "phase5-independent-second-batch-1.0.0"
SCENARIOS = ("SC-001", "SC-004", "SC-008")
EPOCH = datetime(2025, 1, 1, tzinfo=timezone.utc)
DAY_US = Decimal(86_400_000_000)
HOUR_US = Decimal(3_600_000_000)
CENT = Decimal("0.01")
ROOT = Path(__file__).resolve().parents[1]


class VerificationError(ValueError):
    """Frozen input assumptions or independently computed evidence failed."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def json_ready(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    return value


def iso(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    rendered = value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    head, frac = rendered[:-1].split(".")
    frac = frac.rstrip("0")
    return f"{head}.{frac}Z" if frac else f"{head}Z"


def parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise VerificationError(f"expected ISO timestamp, got {value!r}")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise VerificationError(f"timestamp lacks a timezone: {value}")
    return result.astimezone(timezone.utc)


def exact_duration(value, unit_us: Decimal, label: str) -> timedelta:
    micros = Decimal(str(value)) * unit_us
    integral = micros.to_integral_value()
    if micros != integral:
        raise VerificationError(f"{label} is finer than timestamp precision: {value}")
    return timedelta(microseconds=int(integral))


def planned_time(day_value) -> datetime:
    return EPOCH + exact_duration(day_value, DAY_US, "planned day offset")


def day_offset(value: datetime) -> Decimal:
    delta = value.astimezone(timezone.utc) - EPOCH
    micros = ((delta.days * 86400 + delta.seconds) * 1_000_000) + delta.microseconds
    return Decimal(micros) / DAY_US


def contains(start: datetime, end: datetime, instant: datetime) -> bool:
    return start <= instant < end


def overlaps(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> bool:
    return start < window_end and window_start < end


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def money_text(value: Decimal) -> str:
    return f"{money(value):.2f}"


def load_canonical(dataset: Path):
    names = ("dataset_manifest.json", "ports.json", "services.json", "shipments.json", "route_plans.json")
    hashes = {name: sha256(dataset / name) for name in names}
    manifest = read_json(dataset / "dataset_manifest.json")
    if manifest.get("validation_status") != "passed":
        raise VerificationError("dataset manifest does not report a passed validation")
    for name in names[1:]:
        if hashes[name] != manifest["canonical_file_sha256"].get(name):
            raise VerificationError(f"canonical hash differs from manifest: {name}")
    ports = read_json(dataset / "ports.json")
    services = read_json(dataset / "services.json")
    shipments = read_json(dataset / "shipments.json")
    plans = read_json(dataset / "route_plans.json")
    if (len(shipments), len(plans), sum(len(p["ordered_legs"]) for p in plans)) != (1500, 1500, 2936):
        raise VerificationError("research_1500 canonical counts do not match 1,500 shipments/plans and 2,936 legs")
    ship_by_id = {x["shipment_id"]: x for x in shipments}
    plan_by_ship = {x["shipment_id"]: x for x in plans}
    service_by_id = {x["service_id"]: x for x in services}
    port_ids = {x["port_id"] for x in ports}
    if len(ship_by_id) != 1500 or len(plan_by_ship) != 1500 or len(service_by_id) != len(services):
        raise VerificationError("duplicate canonical shipment, plan or service identifiers")
    if set(ship_by_id) != set(plan_by_ship):
        raise VerificationError("shipment and plan identifiers do not join completely")
    for plan in plans:
        for leg in plan["ordered_legs"]:
            if leg["service_id"] not in service_by_id:
                raise VerificationError(f"missing service {leg['service_id']} referenced by {plan['route_plan_id']}")
            service = service_by_id[leg["service_id"]]
            if (leg["origin_port_id"], leg["destination_port_id"]) != (service["origin_port_id"], service["destination_port_id"]):
                raise VerificationError(f"planned leg/service endpoint mismatch in {plan['route_plan_id']}")
    return manifest, hashes, ports, services, shipments, plans, ship_by_id, plan_by_ship, service_by_id, port_ids


def load_scenario(scenario_root: Path, sid: str, port_ids: set[str], service_by_id: dict):
    path = scenario_root / sid / "scenario.json"
    scenario = read_json(path)
    if scenario.get("schema_version") != "1.0" or scenario.get("scenario_id") != sid:
        raise VerificationError(f"invalid scenario header for {sid}")
    events = scenario.get("events")
    if not isinstance(events, list) or len(events) != 1:
        raise VerificationError(f"{sid} must contain one reference event")
    event = events[0]
    start, end = parse_time(event["start_time"]), parse_time(event["end_time"])
    if start >= end:
        raise VerificationError(f"{sid} has a non-positive event interval")
    if event["type"] not in {"PORT_CLOSURE", "SERVICE_SUSPENSION", "SERVICE_DELAY"}:
        raise VerificationError(f"{sid} uses an unsupported event type")
    if event["type"] == "PORT_CLOSURE":
        if event.get("target_port_id") not in port_ids or not event.get("affected_operations"):
            raise VerificationError(f"{sid} has an invalid port target or empty operation scope")
    else:
        if event.get("target_service_id") not in service_by_id or event.get("semantics") != "DEPARTURE_WINDOW":
            raise VerificationError(f"{sid} has an invalid service target/semantics")
    if event["type"] == "SERVICE_DELAY" and Decimal(str(event["delay_hours"])) < 0:
        raise VerificationError(f"{sid} has a negative delay")
    return path, scenario, event, start, end


def leg_id(plan: dict, index: int) -> str:
    return f"{plan['route_plan_id']}:L{index + 1}"


def scan_impacts(sid: str, event: dict, start: datetime, end: datetime,
                 shipments: list[dict], plans: list[dict], service_by_id: dict):
    """Reconstruct direct operations and delay propagation from canonical offsets."""
    plan_by_ship = {p["shipment_id"]: p for p in plans}
    impacts = {}
    direct_operations_scanned = 0
    indirect_connections_scanned = 0
    for shipment in shipments:
        plan = plan_by_ship[shipment["shipment_id"]]
        legs = plan["ordered_legs"]
        matched = []
        if event["type"] == "PORT_CLOSURE":
            for i, leg in enumerate(legs):
                direct_operations_scanned += 1
                departure = planned_time(leg["planned_departure"])
                if ("DEPARTURE" in event["affected_operations"]
                        and leg["origin_port_id"] == event["target_port_id"]
                        and contains(start, end, departure)):
                    matched.append({
                        "operation": "DEPARTURE", "reason_code": "PORT_CLOSURE_DEPARTURE_OVERLAP",
                        "leg_id": leg_id(plan, i), "leg_index": i, "service_id": leg["service_id"],
                        "port_id": event["target_port_id"], "planned_time": iso(departure),
                        "direct_or_indirect": "DIRECT",
                    })
        else:
            for i, leg in enumerate(legs):
                direct_operations_scanned += 1
                departure = planned_time(leg["planned_departure"])
                if (leg["service_id"] == event["target_service_id"] and contains(start, end, departure)):
                    if event["type"] == "SERVICE_SUSPENSION":
                        matched.append({
                            "operation": "DEPARTURE", "reason_code": "SERVICE_SUSPENSION_DEPARTURE_OVERLAP",
                            "leg_id": leg_id(plan, i), "leg_index": i, "service_id": leg["service_id"],
                            "port_id": leg["origin_port_id"], "planned_time": iso(departure),
                            "direct_or_indirect": "DIRECT",
                        })
                    elif Decimal(str(event["delay_hours"])) > 0:
                        matched.append({
                            "operation": "DEPARTURE", "reason_code": "SERVICE_DELAY_DEPARTURE_OVERLAP",
                            "leg_id": leg_id(plan, i), "leg_index": i, "service_id": leg["service_id"],
                            "port_id": leg["origin_port_id"], "planned_time": iso(departure),
                            "direct_or_indirect": "DIRECT",
                        })
        if not matched:
            continue
        indirect = []
        if event["type"] == "SERVICE_DELAY":
            # Follow each affected delay leg through its fixed downstream plan.
            for direct in matched:
                i = direct["leg_index"]
                actual_arrival = planned_time(legs[i]["planned_arrival"]) + exact_duration(event["delay_hours"], HOUR_US, "delay hours")
                for next_i in range(i + 1, len(legs)):
                    indirect_connections_scanned += 1
                    next_leg = legs[next_i]
                    fixed_departure = planned_time(next_leg["planned_departure"])
                    minimum_transfer = exact_duration(next_leg.get("min_transfer_hours", 0), HOUR_US, "minimum transfer")
                    ready = actual_arrival + minimum_transfer
                    slack = fixed_departure - ready
                    indirect.append({
                        "operation": "DOWNSTREAM_CONNECTION",
                        "reason_code": "UNRESOLVED_CONNECTION" if slack < timedelta(0) else "RECOVERED_CONNECTION",
                        "leg_id": leg_id(plan, next_i), "leg_index": next_i,
                        "service_id": next_leg["service_id"], "port_id": next_leg["origin_port_id"],
                        "inbound_arrival": iso(actual_arrival), "minimum_transfer_hours": next_leg.get("min_transfer_hours", 0),
                        "earliest_connection_ready": iso(ready), "fixed_departure": iso(fixed_departure),
                        "slack_seconds": Decimal(str(slack.total_seconds())),
                        "direct_or_indirect": "INDIRECT",
                    })
                    if slack < timedelta(0):
                        break
                    # A feasible fixed leg departs on schedule and inherits the same arrival delay.
                    actual_arrival = planned_time(next_leg["planned_arrival"]) + exact_duration(event["delay_hours"], HOUR_US, "delay hours")
        impacts[shipment["shipment_id"]] = {"shipment": shipment, "plan": plan, "direct": matched, "indirect": indirect}
    all_ids = sorted(s["shipment_id"] for s in shipments)
    affected = sorted(impacts)
    return impacts, {
        "plans_scanned": len(plans), "planned_legs_scanned": sum(len(p["ordered_legs"]) for p in plans),
        "direct_operation_instants_scanned": direct_operations_scanned,
        "downstream_connections_reconstructed": indirect_connections_scanned,
        "affected_shipment_count": len(affected), "unaffected_shipment_count": len(all_ids) - len(affected),
    }


def route_state(sid: str, impact: dict, event: dict):
    plan, legs = impact["plan"], impact["plan"]["ordered_legs"]
    directs = sorted(impact["direct"], key=lambda x: (x["leg_index"], x["planned_time"]))
    if sid == "SC-008":
        misses = [x for x in impact["indirect"] if x["reason_code"] == "UNRESOLVED_CONNECTION"]
        if not misses:
            raise VerificationError(f"{plan['shipment_id']} does not independently have a missed connection")
        next_index = misses[0]["leg_index"]
        inbound_index = next_index - 1
        inbound = legs[inbound_index]
        delay = exact_duration(event["delay_hours"], HOUR_US, "delay hours")
        actual_inbound = planned_time(inbound["planned_arrival"]) + delay
        ready = actual_inbound + exact_duration(legs[next_index].get("min_transfer_hours", 0), HOUR_US, "minimum transfer")
        start_index = next_index
        recovery_port = inbound["destination_port_id"]
        state_reason = "MISSED_FIXED_CONNECTION"
        prefix = []
        for i in range(next_index):
            item = dict(legs[i])
            if i == inbound_index:
                item["actual_arrival_time"] = iso(actual_inbound)
            prefix.append(item)
    else:
        first = directs[0]
        start_index = first["leg_index"]
        event_time = parse_time(first["planned_time"])
        recovery_port = legs[start_index]["origin_port_id"]
        if start_index == 0:
            ready = planned_time(impact["shipment"].get("release_time", impact["shipment"]["release_day"]))
        else:
            previous = legs[start_index - 1]
            arrival = planned_time(previous["planned_arrival"])
            transfer = exact_duration(legs[start_index].get("min_transfer_hours", 0), HOUR_US, "minimum transfer")
            ready = arrival + transfer
        ready = max(ready, event_time)
        state_reason = "BLOCKED_FIXED_DEPARTURE"
        prefix = [dict(leg) for leg in legs[:start_index]]
        if start_index:
            prefix[-1]["actual_arrival_time"] = iso(planned_time(legs[start_index - 1]["planned_arrival"]))
    return {
        "shipment_id": plan["shipment_id"], "plan_id": plan["route_plan_id"],
        "completed_leg_count": len(prefix), "recovery_port_id": recovery_port,
        "earliest_recovery_time": iso(ready), "state_reason": state_reason,
        "completed_prefix": prefix, "unexecuted_original_suffix": [dict(x) for x in legs[start_index:]],
        "recovery_leg_index": start_index,
    }


def periodic_departures(ready: datetime, service: dict, policy: dict):
    frequency = Decimal(str(service["departure_frequency_days"]))
    if frequency <= 0:
        raise VerificationError(f"non-positive frequency for {service['service_id']}")
    anchor = Decimal(str(policy["departure_anchor_day"]))
    current_day = day_offset(ready)
    first = ((current_day - anchor) / frequency).to_integral_value(rounding=ROUND_CEILING)
    for step in range(int(policy["departures_per_service"])):
        day = anchor + frequency * (int(first) + step)
        yield EPOCH + exact_duration(day, DAY_US, "periodic departure offset")


def event_blocks_departure(dep: datetime, origin: str, service_id: str, events: list[dict]):
    reasons = []
    for event in events:
        start, end = parse_time(event["start_time"]), parse_time(event["end_time"])
        if (event["type"] == "PORT_CLOSURE" and event["target_port_id"] == origin
                and "DEPARTURE" in event.get("affected_operations", []) and contains(start, end, dep)):
            reasons.append(event["event_id"])
        if (event["type"] == "SERVICE_SUSPENSION" and event["target_service_id"] == service_id
                and contains(start, end, dep)):
            reasons.append(event["event_id"])
    return reasons


def active_delay(dep: datetime, service_id: str, events: list[dict]) -> Decimal:
    delay = Decimal(0)
    for event in events:
        if event["type"] == "SERVICE_DELAY" and event["target_service_id"] == service_id:
            if contains(parse_time(event["start_time"]), parse_time(event["end_time"]), dep):
                delay += Decimal(str(event["delay_hours"]))
    return delay


def check_route(shipment: dict, plan: dict, state: dict, route: list[dict],
                services_by_id: dict, events: list[dict], policy: dict):
    """Validate a route independently from canonical edges and timing rules."""
    checks = []

    def record(code, passed, **evidence):
        checks.append({"constraint": code, "result": "PASS" if passed else "FAIL", **evidence})

    record("MAX_HOPS", len(route) <= int(policy["max_hops"]), actual=len(route), maximum=int(policy["max_hops"]))
    port = state["recovery_port_id"]
    ready = parse_time(state["earliest_recovery_time"])
    seen = {x["origin_port_id"] for x in state["completed_prefix"]}
    if not seen:
        seen.add(port)
    previous_arrival = None
    prefix = state["completed_prefix"]
    if prefix:
        last = prefix[-1]
        previous_arrival = parse_time(last.get("actual_arrival_time", iso(planned_time(last["planned_arrival"]))))
    computed = []
    suffix_cost = Decimal(0)
    invalid = False
    for idx, item in enumerate(route):
        sid = item.get("service_id")
        service = services_by_id.get(sid)
        record("SERVICE_EXISTS", service is not None, leg_index=idx, service_id=sid)
        if service is None:
            invalid = True
            break
        dep = parse_time(item["departure_time"])
        arr = parse_time(item["arrival_time"])
        continuous = item.get("origin_port_id") == port == service["origin_port_id"]
        record("DIRECTED_CONTINUITY", continuous and item.get("destination_port_id") == service["destination_port_id"],
               leg_index=idx, expected_origin=port, actual_origin=item.get("origin_port_id"),
               service_destination=service["destination_port_id"], actual_destination=item.get("destination_port_id"))
        ready_ok = dep >= ready
        record("TRANSFER_READY", ready_ok, leg_index=idx, earliest_departure=iso(ready), departure=iso(dep))
        frequency = Decimal(str(service["departure_frequency_days"]))
        anchor = Decimal(str(policy["departure_anchor_day"]))
        offset = day_offset(dep)
        n = (offset - anchor) / frequency if frequency > 0 else Decimal("NaN")
        modeled = frequency > 0 and n == n.to_integral_value()
        record("MODELED_DEPARTURE", modeled, leg_index=idx, frequency_days=frequency, departure_day_offset=offset)
        duration = exact_duration(service["transit_days"], DAY_US, "transit duration")
        delay = active_delay(dep, sid, events)
        expected_arrival = dep + duration + exact_duration(delay, HOUR_US, "applied service delay")
        record("TRANSIT_DURATION", arr == expected_arrival, leg_index=idx,
               expected_arrival=iso(expected_arrival), supplied_arrival=iso(arr), applied_delay_hours=delay)
        blocked = event_blocks_departure(dep, service["origin_port_id"], sid, events)
        if previous_arrival is not None:
            for event in events:
                if event["type"] == "PORT_CLOSURE" and event.get("target_port_id") == port and "TRANSSHIPMENT" in event.get("affected_operations", []):
                    if overlaps(previous_arrival, dep, parse_time(event["start_time"]), parse_time(event["end_time"])):
                        blocked.append(event["event_id"])
        for event in events:
            if event["type"] == "PORT_CLOSURE" and event.get("target_port_id") == service["destination_port_id"] and "ARRIVAL" in event.get("affected_operations", []):
                if contains(parse_time(event["start_time"]), parse_time(event["end_time"]), arr):
                    blocked.append(event["event_id"])
        record("ACTIVE_DISRUPTIONS", not blocked, leg_index=idx, blocking_event_ids=sorted(set(blocked)))
        cargo_classes = service.get("cargo_classes")
        record("CARGO_CLASS", cargo_classes is not None and shipment["cargo_class"] in cargo_classes,
               leg_index=idx, shipment_class=shipment["cargo_class"], supported_classes=cargo_classes)
        cap = service.get("capacity_teu")
        record("INDIVIDUAL_CAPACITY", cap is not None and Decimal(str(shipment["cargo_teu"])) <= Decimal(str(cap)),
               leg_index=idx, shipment_teu=shipment["cargo_teu"], service_capacity_teu=cap,
               limitation="Individual modeled capacity only; no shared booking availability inferred.")
        edge_cost = money(Decimal(str(service["cost_per_teu_usd"])) * Decimal(str(shipment["cargo_teu"])))
        supplied_cost = money(Decimal(str(item.get("modeled_cost_usd", edge_cost))))
        record("MODELED_COST", supplied_cost == edge_cost, leg_index=idx,
               independently_calculated_usd=money_text(edge_cost), supplied_usd=money_text(supplied_cost))
        no_cycle = service["destination_port_id"] not in seen
        record("NO_CYCLE", no_cycle, leg_index=idx, destination=service["destination_port_id"])
        seen.add(service["destination_port_id"])
        next_item = {
            "service_id": sid, "origin_port_id": service["origin_port_id"],
            "destination_port_id": service["destination_port_id"],
            "departure_time": iso(dep), "arrival_time": iso(arr),
            "modeled_cost_usd": edge_cost,
        }
        computed.append(next_item)
        suffix_cost += edge_cost
        port = service["destination_port_id"]
        previous_arrival = arr
        ready = arr + exact_duration(service.get("min_transfer_hours", 0), HOUR_US, "service minimum transfer")
    record("DESTINATION", port == shipment["destination_port_id"],
           expected=shipment["destination_port_id"], actual=port)
    if computed:
        eta = parse_time(computed[-1]["arrival_time"])
        start = parse_time(state["earliest_recovery_time"])
        record("POLICY_HORIZON", eta <= start + timedelta(days=int(policy["horizon_days"])),
               eta=iso(eta), latest=iso(start + timedelta(days=int(policy["horizon_days"]))))
    else:
        eta = previous_arrival or parse_time(state["earliest_recovery_time"])
    deadline = planned_time(shipment["delivery_deadline"])
    record("HARD_DEADLINE", eta <= deadline, eta=iso(eta), deadline=iso(deadline))
    prefix_cost = Decimal(0)
    original_cost = Decimal(0)
    for idx, item in enumerate(prefix):
        service = services_by_id[item["service_id"]]
        calculated = money(Decimal(str(service["cost_per_teu_usd"])) * Decimal(str(shipment["cargo_teu"])))
        recorded = money(Decimal(str(item["modeled_cost_usd"])))
        record("PRESERVED_PREFIX_COST", calculated == recorded, leg_index=idx,
               service_id=item["service_id"], independently_calculated_usd=money_text(calculated),
               canonical_record_usd=money_text(recorded))
        prefix_cost += calculated
    for idx, item in enumerate(plan["ordered_legs"]):
        service = services_by_id[item["service_id"]]
        calculated = money(Decimal(str(service["cost_per_teu_usd"])) * Decimal(str(shipment["cargo_teu"])))
        recorded = money(Decimal(str(item["modeled_cost_usd"])))
        record("ORIGINAL_PLAN_LEG_COST", calculated == recorded, leg_index=idx,
               service_id=item["service_id"], independently_calculated_usd=money_text(calculated),
               canonical_record_usd=money_text(recorded))
        original_cost += calculated
    total_cost = money(prefix_cost + suffix_cost)
    original_cost = money(original_cost)
    return {
        "valid": all(x["result"] == "PASS" for x in checks), "checks": checks,
        "calculated_suffix": computed, "eta": iso(eta), "deadline": iso(deadline),
        "prefix_cost_usd": money_text(prefix_cost), "suffix_cost_usd": money_text(suffix_cost),
        "total_cost_usd": money_text(total_cost), "original_plan_cost_usd": money_text(original_cost),
        "additional_cost_usd": money_text(total_cost - original_cost),
        "deadline_met": eta <= deadline,
    }


def enumerate_routes(shipment: dict, plan: dict, state: dict, services: list[dict], service_by_id: dict,
                     events: list[dict], policy: dict):
    """Exhaust the configured hop/horizon/departure bounds with a separate DFS."""
    outgoing = {}
    for service in services:
        outgoing.setdefault(service["origin_port_id"], []).append(service)
    for rows in outgoing.values():
        rows.sort(key=lambda s: s["service_id"])
    start = parse_time(state["earliest_recovery_time"])
    horizon = start + timedelta(days=int(policy["horizon_days"]))
    output = []
    stats = {"expanded_states": 0, "complete_routes_checked": 0, "search_limited": False,
             "max_hops": int(policy["max_hops"]), "horizon_days": int(policy["horizon_days"]),
             "departures_per_service": int(policy["departures_per_service"])}
    labels = {}

    def walk(port, ready, path, visited, previous_arrival):
        if stats["search_limited"]:
            return
        if stats["expanded_states"] >= int(policy["max_expansions"]):
            stats["search_limited"] = True
            return
        stats["expanded_states"] += 1
        if port == shipment["destination_port_id"]:
            stats["complete_routes_checked"] += 1
            validated = check_route(shipment, plan, state, path, service_by_id, events, policy)
            if validated["valid"]:
                output.append({"suffix": validated["calculated_suffix"], **validated})
                if len(output) >= int(policy["max_candidates"]):
                    stats["search_limited"] = True
            return
        if len(path) >= int(policy["max_hops"]):
            return
        label_key = (port, len(path))
        labels[label_key] = labels.get(label_key, 0) + 1
        if labels[label_key] > int(policy["max_labels_per_port"]):
            stats["search_limited"] = True
            return
        for service in outgoing.get(port, []):
            dest = service["destination_port_id"]
            if dest in visited:
                continue
            classes = service.get("cargo_classes")
            capacity = service.get("capacity_teu")
            if classes is None or shipment["cargo_class"] not in classes or capacity is None:
                continue
            if Decimal(str(shipment["cargo_teu"])) > Decimal(str(capacity)):
                continue
            for departure in periodic_departures(ready, service, policy):
                if departure < ready or departure > horizon:
                    continue
                if event_blocks_departure(departure, port, service["service_id"], events):
                    continue
                if previous_arrival is not None and any(
                    event["type"] == "PORT_CLOSURE" and event.get("target_port_id") == port
                    and "TRANSSHIPMENT" in event.get("affected_operations", [])
                    and overlaps(previous_arrival, departure, parse_time(event["start_time"]), parse_time(event["end_time"]))
                    for event in events
                ):
                    continue
                delay = active_delay(departure, service["service_id"], events)
                arrival = departure + exact_duration(service["transit_days"], DAY_US, "transit duration") + exact_duration(delay, HOUR_US, "active delay")
                if arrival > horizon:
                    continue
                if any(event["type"] == "PORT_CLOSURE" and event.get("target_port_id") == dest
                       and "ARRIVAL" in event.get("affected_operations", [])
                       and contains(parse_time(event["start_time"]), parse_time(event["end_time"]), arrival)
                       for event in events):
                    continue
                edge_cost = money(Decimal(str(service["cost_per_teu_usd"])) * Decimal(str(shipment["cargo_teu"])))
                leg = {"service_id": service["service_id"], "origin_port_id": port,
                       "destination_port_id": dest, "departure_time": iso(departure),
                       "arrival_time": iso(arrival), "modeled_cost_usd": edge_cost}
                walk(dest, arrival + exact_duration(service.get("min_transfer_hours", 0), HOUR_US, "service transfer"),
                     path + [leg], visited | {dest}, arrival)
                if stats["search_limited"]:
                    return

    walk(state["recovery_port_id"], start, [], frozenset({state["recovery_port_id"]}),
         parse_time(state["completed_prefix"][-1].get("actual_arrival_time", iso(planned_time(state["completed_prefix"][-1]["planned_arrival"]))))
         if state["completed_prefix"] else None)
    output.sort(key=lambda x: (Decimal(x["total_cost_usd"]), x["eta"], len(x["suffix"]), tuple(y["service_id"] for y in x["suffix"])))
    return output, stats


def schedule_candidate_path(shipment: dict, plan: dict, state: dict, service_ids: list[str],
                            service_by_id: dict, events: list[dict], policy: dict):
    """Reconstruct the earliest modeled schedule for an explicit path."""
    ready = parse_time(state["earliest_recovery_time"])
    port = state["recovery_port_id"]
    route = []
    for service_id in service_ids:
        service = service_by_id.get(service_id)
        if service is None:
            raise VerificationError(f"{shipment['shipment_id']}: candidate service does not exist: {service_id}")
        if service["origin_port_id"] != port:
            raise VerificationError(f"{shipment['shipment_id']}: candidate path is discontinuous at {service_id}")
        choices = periodic_departures(ready, service, policy)
        departure = next((d for d in choices if d >= ready and not event_blocks_departure(
            d, port, service_id, events)), None)
        if departure is None:
            raise VerificationError(f"{shipment['shipment_id']}: no permitted modeled departure for {service_id} within configured departure bound")
        delay = active_delay(departure, service_id, events)
        arrival = departure + exact_duration(service["transit_days"], DAY_US, "transit duration") + exact_duration(delay, HOUR_US, "active delay")
        route.append({"service_id": service_id, "origin_port_id": port,
                      "destination_port_id": service["destination_port_id"],
                      "departure_time": iso(departure), "arrival_time": iso(arrival),
                      "modeled_cost_usd": money(Decimal(str(service["cost_per_teu_usd"])) * Decimal(str(shipment["cargo_teu"])))})
        port = service["destination_port_id"]
        ready = arrival + exact_duration(service.get("min_transfer_hours", 0), HOUR_US, "service minimum transfer")
    return route


def independently_find_path(shipment: dict, plan: dict, state: dict, services: list[dict],
                            service_by_id: dict, events: list[dict], policy: dict):
    """Find a feasible directed path by bounded DFS over canonical service records."""
    outgoing = {}
    for service in services:
        outgoing.setdefault(service["origin_port_id"], []).append(service)
    for rows in outgoing.values():
        rows.sort(key=lambda row: row["service_id"])
    stats = {"method": "independent_bounded_directed_path_enumeration", "expanded_states": 0,
             "candidate_paths_checked": 0, "search_limited": False,
             "exhaustive_global_search": False, "max_hops": int(policy["max_hops"]),
             "horizon_days": int(policy["horizon_days"]),
             "departures_per_service": int(policy["departures_per_service"])}
    horizon = parse_time(state["earliest_recovery_time"]) + timedelta(days=int(policy["horizon_days"]))
    result = None

    def walk(port, ready, path, visited, previous_arrival):
        nonlocal result
        if result is not None or stats["search_limited"]:
            return
        if stats["expanded_states"] >= int(policy["max_expansions"]):
            stats["search_limited"] = True
            return
        stats["expanded_states"] += 1
        if port == shipment["destination_port_id"]:
            stats["candidate_paths_checked"] += 1
            checked = check_route(shipment, plan, state, path, service_by_id, events, policy)
            if checked["valid"]:
                result = {**checked, "suffix": checked["calculated_suffix"]}
            return
        if len(path) >= int(policy["max_hops"]):
            return
        for service in outgoing.get(port, []):
            destination = service["destination_port_id"]
            if destination in visited or shipment["cargo_class"] not in (service.get("cargo_classes") or []):
                continue
            capacity = service.get("capacity_teu")
            if capacity is None or Decimal(str(shipment["cargo_teu"])) > Decimal(str(capacity)):
                continue
            departure = next((d for d in periodic_departures(ready, service, policy)
                              if d >= ready and d <= horizon and not event_blocks_departure(
                                  d, port, service["service_id"], events)), None)
            if departure is None:
                continue
            if previous_arrival is not None and any(
                event["type"] == "PORT_CLOSURE" and event.get("target_port_id") == port
                and "TRANSSHIPMENT" in event.get("affected_operations", [])
                and overlaps(previous_arrival, departure, parse_time(event["start_time"]), parse_time(event["end_time"]))
                for event in events
            ):
                continue
            delay = active_delay(departure, service["service_id"], events)
            arrival = departure + exact_duration(service["transit_days"], DAY_US, "transit duration") + exact_duration(delay, HOUR_US, "active delay")
            if arrival > horizon or arrival > planned_time(shipment["delivery_deadline"]):
                continue
            if any(event["type"] == "PORT_CLOSURE" and event.get("target_port_id") == destination
                   and "ARRIVAL" in event.get("affected_operations", [])
                   and contains(parse_time(event["start_time"]), parse_time(event["end_time"]), arrival)
                   for event in events):
                continue
            leg = {"service_id": service["service_id"], "origin_port_id": port,
                   "destination_port_id": destination, "departure_time": iso(departure),
                   "arrival_time": iso(arrival),
                   "modeled_cost_usd": money(Decimal(str(service["cost_per_teu_usd"])) * Decimal(str(shipment["cargo_teu"]))) }
            walk(destination, arrival + exact_duration(service.get("min_transfer_hours", 0), HOUR_US, "service minimum transfer"),
                 path + [leg], visited | {destination}, arrival)
            if result is not None or stats["search_limited"]:
                return

    prefix = state["completed_prefix"]
    previous_arrival = (parse_time(prefix[-1].get("actual_arrival_time", iso(planned_time(prefix[-1]["planned_arrival"]))))
                        if prefix else None)
    walk(state["recovery_port_id"], parse_time(state["earliest_recovery_time"]), [],
         frozenset({state["recovery_port_id"]}), previous_arrival)
    return result, stats


def independently_check_port_sequence(shipment: dict, plan: dict, state: dict, target_ports: list[str],
                                      services: list[dict], service_by_id: dict, events: list[dict], policy: dict):
    """Check a specified port sequence by selecting compatible canonical service edges."""
    if not target_ports or target_ports[0] != state["recovery_port_id"] or target_ports[-1] != shipment["destination_port_id"]:
        raise VerificationError(f"{shipment['shipment_id']}: candidate port sequence has wrong endpoints")
    by_edge = {}
    for service in services:
        by_edge.setdefault((service["origin_port_id"], service["destination_port_id"]), []).append(service)
    for rows in by_edge.values():
        rows.sort(key=lambda row: row["service_id"])
    result = None

    def walk(index, ready, previous_arrival, route, seen_ports):
        nonlocal result
        if result is not None:
            return
        if index == len(target_ports) - 1:
            checked = check_route(shipment, plan, state, route, service_by_id, events, policy)
            if checked["valid"]:
                result = {**checked, "suffix": checked["calculated_suffix"]}
            return
        origin, destination = target_ports[index], target_ports[index + 1]
        for service in by_edge.get((origin, destination), []):
            if destination in seen_ports or shipment["cargo_class"] not in (service.get("cargo_classes") or []):
                continue
            capacity = service.get("capacity_teu")
            if capacity is None or Decimal(str(shipment["cargo_teu"])) > Decimal(str(capacity)):
                continue
            departure = next((d for d in periodic_departures(ready, service, policy)
                              if d >= ready and not event_blocks_departure(d, origin, service["service_id"], events)), None)
            if departure is None:
                continue
            if previous_arrival is not None and any(
                event["type"] == "PORT_CLOSURE" and event.get("target_port_id") == origin
                and "TRANSSHIPMENT" in event.get("affected_operations", [])
                and overlaps(previous_arrival, departure, parse_time(event["start_time"]), parse_time(event["end_time"]))
                for event in events
            ):
                continue
            delay = active_delay(departure, service["service_id"], events)
            arrival = departure + exact_duration(service["transit_days"], DAY_US, "transit duration") + exact_duration(delay, HOUR_US, "active delay")
            edge_cost = money(Decimal(str(service["cost_per_teu_usd"])) * Decimal(str(shipment["cargo_teu"])))
            leg = {"service_id": service["service_id"], "origin_port_id": origin,
                   "destination_port_id": destination, "departure_time": iso(departure),
                   "arrival_time": iso(arrival), "modeled_cost_usd": edge_cost}
            walk(index + 1, arrival + exact_duration(service.get("min_transfer_hours", 0), HOUR_US, "service minimum transfer"),
                 arrival, route + [leg], seen_ports | {destination})
            if result is not None:
                return

    prefix = state["completed_prefix"]
    previous = (parse_time(prefix[-1].get("actual_arrival_time", iso(planned_time(prefix[-1]["planned_arrival"]))))
                if prefix else None)
    walk(0, parse_time(state["earliest_recovery_time"]), previous, [], frozenset({target_ports[0]}))
    return result


def sequence(port_start: str, legs: list[dict]):
    ports = [port_start]
    for leg in legs:
        ports.append(leg["destination_port_id"])
    return ports


def recovery_classification(original_legs: list[dict], prefix: list[dict], suffix: list[dict], start_port: str):
    original_services = [x["service_id"] for x in original_legs]
    full_services = [x["service_id"] for x in prefix] + [x["service_id"] for x in suffix]
    original_ports = [original_legs[0]["origin_port_id"]] + [x["destination_port_id"] for x in original_legs]
    full_legs = prefix + suffix
    full_ports = [full_legs[0]["origin_port_id"]] + [x["destination_port_id"] for x in full_legs] if full_legs else [start_port]
    service_changed = original_services != full_services
    ports_changed = original_ports != full_ports
    if not service_changed:
        return ("SAME_SERVICE_RESCHEDULING" if any(
            i < len(suffix) and suffix[i]["departure_time"] != iso(planned_time(original_legs[len(prefix)+i]["planned_departure"]))
            for i in range(min(len(suffix), len(original_legs)-len(prefix)))
        ) else "SAME_SERVICE_CONTINUATION"), original_services, full_services, original_ports, full_ports, service_changed, ports_changed
    return ("CHANGED_SERVICE_AND_PORT_SEQUENCE" if ports_changed else "CHANGED_SERVICE_SAME_PORT_SEQUENCE",
            original_services, full_services, original_ports, full_ports, service_changed, ports_changed)


def commit_id(root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNAVAILABLE"


def ref(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def event_record(event: dict):
    keys = ("event_id", "type", "target_port_id", "affected_operations", "target_service_id", "semantics", "start_time", "end_time", "delay_hours", "source_type")
    return {k: json_ready(event[k]) for k in keys if k in event}


def build_label(sid: str, dataset: Path, scenario_root: Path, policy_path: Path,
                commit: str, verification_date: str):
    manifest, hashes, ports, services, shipments, plans, ship_by_id, plan_by_ship, service_by_id, port_ids = load_canonical(dataset)
    scenario_path, scenario, event, start, end = load_scenario(scenario_root, sid, port_ids, service_by_id)
    impacts, scope = scan_impacts(sid, event, start, end, shipments, plans, service_by_id)
    policy = read_json(policy_path)
    if policy.get("policy_id") != "modeled-periodic-v1":
        raise VerificationError("unexpected recovery policy id")
    event_impacts = []
    expected_recovery = []
    feasibility_summaries = []
    for ship_id in sorted(impacts):
        impact = impacts[ship_id]
        shipment, plan = impact["shipment"], impact["plan"]
        state = route_state(sid, impact, event)
        if sid == "SC-004":
            selected, search = independently_find_path(shipment, plan, state, services,
                                                        service_by_id, [event], policy)
        else:
            candidate_path = [x["service_id"] for x in state["unexecuted_original_suffix"]]
            candidate_route = schedule_candidate_path(shipment, plan, state, candidate_path,
                                                      service_by_id, [event], policy)
            checked = check_route(shipment, plan, state, candidate_route, service_by_id, [event], policy)
            selected = {**checked, "suffix": checked["calculated_suffix"]} if checked["valid"] else None
            search = {"method": "independent_original_suffix_schedule_check", "candidate_service_ids": candidate_path,
                      "candidate_routes_checked": 1, "exhaustive_global_search": False,
                      "search_limited": False, "max_hops": int(policy["max_hops"]),
                      "horizon_days": int(policy["horizon_days"]),
                      "departures_per_service": int(policy["departures_per_service"])}
        routes = [selected] if selected is not None else []
        if routes:
            selected = routes[0]
            independent_feasibility = "FEASIBLE"
            status = "RECOVERED"
            classification, old_svc, new_svc, old_ports, new_ports, svc_changed, ports_changed = recovery_classification(
                plan["ordered_legs"], state["completed_prefix"], selected["suffix"], state["recovery_port_id"])
            route_record = {
                "route_role": "independently_selected_feasible_candidate_within_configured_bounds",
                "recovery_port_id": state["recovery_port_id"],
                "service_sequence": new_svc, "port_sequence": new_ports,
                "original_service_sequence": old_svc, "original_port_sequence": old_ports,
                "service_sequence_changed": svc_changed, "port_sequence_changed": ports_changed,
                "completed_prefix": state["completed_prefix"], "replacement_suffix": selected["suffix"],
                "modeled_final_eta": selected["eta"], "deadline": selected["deadline"],
                "deadline_met": selected["deadline_met"],
                "cost_calculation": {
                    "rounding": "Each modeled service leg is multiplied by shipment TEU and rounded to cents using decimal ROUND_HALF_UP; total includes preserved prefix.",
                    "prefix_cost_usd": selected["prefix_cost_usd"], "replacement_suffix_cost_usd": selected["suffix_cost_usd"],
                    "modeled_total_cost_usd": selected["total_cost_usd"],
                    "original_itinerary_cost_usd": selected["original_plan_cost_usd"],
                    "additional_modeled_cost_usd": selected["additional_cost_usd"],
                },
                "independent_constraint_checks": selected["checks"],
            }
            if sid == "SC-001" and classification not in {"SAME_SERVICE_RESCHEDULING", "SAME_SERVICE_CONTINUATION"}:
                raise VerificationError(f"SC-001 unexpectedly requires a changed sequence for {ship_id}")
        else:
            raise VerificationError(f"{sid} independent route evidence unresolved for {ship_id}; bounded search diagnostics: {json.dumps(search, sort_keys=True)}")
        direct = impact["direct"]
        indirect = impact["indirect"]
        detail = {
            "shipment_id": ship_id, "plan_id": plan["route_plan_id"],
            "direct_or_indirect": "DIRECT_AND_INDIRECT" if indirect else "DIRECT",
            "direct_leg_ids": sorted({x["leg_id"] for x in direct}),
            "indirect_leg_ids": sorted({x["leg_id"] for x in indirect}),
            "reason_codes": sorted({x["reason_code"] for x in direct + indirect}),
            "direct_evidence": direct, "indirect_evidence": indirect,
        }
        event_impacts.append(detail)
        decision = {
            "shipment_id": ship_id, "expected_recovery_status": status,
            "recovery_classification": classification,
            "independent_feasibility": independent_feasibility,
            "reference_routes": [route_record] if route_record else [],
            "expected_safe_agent_behavior": (
                "Report that the existing itinerary can be rescheduled on its original service sequence; do not claim an alternative route."
                if sid == "SC-001" and status == "RECOVERED" else
                "Recommend a route independently shown feasible under the modeled service, timing, cargo, capacity and deadline constraints; describe route choice as a feasible candidate, not a global optimum."
                if status == "RECOVERED" else
                "Do not present the tested candidate path as feasible; seek another independently checked option or operator review."
            ),
            "recovery_state": state, "route_search_scope": search,
            "service_sequence_changed": svc_changed, "port_sequence_changed": ports_changed,
            "original_service_sequence": old_svc, "selected_service_sequence": new_svc,
            "original_port_sequence": old_ports, "selected_port_sequence": new_ports,
        }
        expected_recovery.append(decision)
        feasibility_summaries.append({"shipment_id": ship_id, "independent_feasibility": independent_feasibility,
                                      "classification": classification, "route_count_in_scope": len(routes),
                                      "search_limited": search["search_limited"]})
    if not impacts:
        raise VerificationError(f"{sid} has no independently affected shipment; this batch scenario requires a nonempty impact cohort")
    if sid == "SC-004" and not any(
        row["independent_feasibility"] == "FEASIBLE"
        and row["classification"] == "CHANGED_SERVICE_AND_PORT_SEQUENCE"
        for row in feasibility_summaries
    ):
        raise VerificationError("SC-004 did not independently establish a feasible changed-service/changed-port route")
    affected_ids = sorted(impacts)
    all_ids = sorted(ship_by_id)
    unaffected_ids = sorted(set(all_ids) - set(affected_ids))
    additional_route_candidate_checks = []
    if sid == "SC-004":
        candidate_id = "SHIP-000005"
        impact = impacts[candidate_id]
        state = route_state(sid, impact, event)
        candidate = independently_check_port_sequence(
            impact["shipment"], impact["plan"], state,
            ["NLRTM", "KRPUS", "CNSGH"], services, service_by_id, [event], policy,
        )
        if candidate is None:
            raise VerificationError("SC-004 nominated NLRTM-KRPUS-CNSGH path failed independent canonical checks")
        old_suffix = state["unexecuted_original_suffix"]
        classification, old_services, new_services, old_ports, new_ports, service_changed, ports_changed = recovery_classification(
            impact["plan"]["ordered_legs"], state["completed_prefix"], candidate["suffix"], state["recovery_port_id"])
        additional_route_candidate_checks.append({
            "shipment_id": candidate_id,
            "candidate_purpose": "Independently check the specifically nominated NLRTM-KRPUS-CNSGH alternative against the original suffix.",
            "original_remaining_service_sequence": [x["service_id"] for x in old_suffix],
            "original_remaining_port_sequence": [old_suffix[0]["origin_port_id"]] + [x["destination_port_id"] for x in old_suffix],
            "original_first_departure": iso(planned_time(old_suffix[0]["planned_departure"])),
            "original_first_departure_blocked_by_event": event_blocks_departure(
                planned_time(old_suffix[0]["planned_departure"]), old_suffix[0]["origin_port_id"], old_suffix[0]["service_id"], [event]),
            "candidate_recovery_classification": classification,
            "candidate_service_sequence": new_services,
            "candidate_port_sequence": new_ports,
            "service_sequence_changed": service_changed,
            "intermediate_port_sequence_changed": ports_changed,
            "replacement_suffix": candidate["suffix"],
            "modeled_final_eta": candidate["eta"],
            "deadline": candidate["deadline"],
            "deadline_met": candidate["deadline_met"],
            "cost_calculation": {"prefix_cost_usd": candidate["prefix_cost_usd"],
                                 "suffix_cost_usd": candidate["suffix_cost_usd"],
                                 "total_cost_usd": candidate["total_cost_usd"],
                                 "original_itinerary_cost_usd": candidate["original_plan_cost_usd"],
                                 "additional_modeled_cost_usd": candidate["additional_cost_usd"]},
            "independent_constraint_checks": candidate["checks"],
            "global_optimality_claimed": False,
        })
    impact_rows = []
    for item in event_impacts:
        impact_rows.append({k: item[k] for k in ("shipment_id", "direct_or_indirect", "direct_leg_ids", "indirect_leg_ids", "reason_codes")})
    notice_path = scenario_root / sid / "notice.txt"
    label = {
        "scenario_id": sid, "label_version": "1.0", "verification_status": "VERIFIED",
        "agent_notice_ref": {"path": f"examples/phase5/{sid}/notice.txt", "sha256": sha256(notice_path)},
        "hidden_reference_event": {"valid_event_expected": True, "events": [event_record(event)],
                                    "unresolved_fields": [], "required_clarification": []},
        "expected_impact": {
            "affected_shipment_ids": affected_ids, "affected_shipments": impact_rows,
            "unaffected_shipment_count": len(unaffected_ids), "unaffected_shipment_ids": unaffected_ids,
            "unaffected_shipments_or_cohort_rule": "Every other shipment in the complete 1,500 shipment/route-plan join after scanning all 2,936 planned leg operations.",
        },
        "expected_recovery": expected_recovery,
        "unaffected_recovery_classification": {"expected_recovery_status": "UNCHANGED", "shipment_count": len(unaffected_ids)},
        "expected_missing_information": [],
        "evidence_refs": [f"{sid}-EVIDENCE-CANONICAL-IMPACT", f"{sid}-EVIDENCE-INDEPENDENT-ROUTE-CALCULATIONS"],
        "independent_calculation": {
            "event_interval_utc": {"start": iso(start), "end": iso(end), "rule": "[start,end)"},
            "source_record_scope": scope, "impact_evidence": event_impacts,
            "recovery_feasibility_summary": feasibility_summaries,
            "additional_route_candidate_checks": additional_route_candidate_checks,
            "recovery_semantics": {
                "SC-001": "Departure closure blocks only departures from SGSIN during the interval; later original-service sailings are allowed. The supported response is same-service rescheduling, not diversion.",
                "SC-004": "Suspension applies only to departures of the targeted service inside the interval; other services remain available. Feasible routes are checked within configured hop, horizon and departure limits.",
                "SC-008": "The delayed inbound leg is preserved in the completed prefix; recovery starts at its destination after transfer readiness. The missed fixed departure is not replayed.",
            }[sid],
        "service_schedule_model": "UTC epoch 2025-01-01; departure times are anchor_day + integer multiples of canonical departure_frequency_days; SC-001/SC-008 check the original remaining suffix while SC-004 enumerates canonical directed service paths and independently schedules the first permitted departure at each step.",
            "cost_method": "Decimal service cost_per_teu_usd multiplied by cargo_teu; each leg rounded to cents with ROUND_HALF_UP; preserved-prefix cost included; no real shared booking cost/availability inferred.",
            "global_optimality": "Not claimed. Feasibility evidence concerns explicitly stated candidate routes checked against configured max_hops, horizon and departure bounds; this is not an exhaustive proof that no other routes exist.",
        },
        "provenance": {
            "dataset_build": "research_1500", "dataset_manifest_sha256": hashes["dataset_manifest.json"],
            "canonical_file_sha256": {k: hashes[k] for k in ("ports.json", "services.json", "shipments.json", "route_plans.json")},
            "recovery_policy_id": policy["policy_id"], "recovery_policy_sha256": sha256(policy_path),
            "scenario_sha256": sha256(scenario_path), "notice_sha256": sha256(notice_path),
            "verification_script_version": VERSION, "verification_script_sha256": sha256(Path(__file__).resolve()),
            "verification_code_commit": commit, "verification_date": verification_date,
        },
        "verification_method": {
            "method": "Independent reconstruction from raw canonical shipment, route-plan, service and port records using Decimal timestamp arithmetic. SC-001/SC-008 preserve the original remaining suffix; SC-004 uses a separate bounded DFS over directed canonical services. All schedule and constraint evidence is recomputed. No Phase 3/4 modules or saved execution outputs are read during generation.",
            "epoch_utc": iso(EPOCH), "interval_rule": "Half-open [start_time, end_time)",
            "author_role": "Student verification against the frozen modeled dataset and stated rules; no maritime expert review claimed.",
        },
        "review_notes": "VERIFIED means the stated event, full impact cohort and listed feasible reference route calculations were independently reproduced under modeled constraints. It does not assert Phase 4 route optimality, real-world vessel availability or shared booking capacity.",
    }
    return label


def generate_labels(dataset: Path, scenario_root: Path, policy_path: Path, commit: str, verification_date: str):
    # Loading once snapshots and validates all canonical records. This code path
    # intentionally has no reference to the execution-output directory.
    labels = [build_label(sid, dataset, scenario_root, policy_path, commit, verification_date) for sid in SCENARIOS]
    return labels


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_ready(value), sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def generate(args, root: Path):
    dataset = (root / args.dataset).resolve()
    scenario_root = (root / args.scenario_root).resolve()
    policy_path = (root / args.policy).resolve()
    output = (root / args.ground_truth).resolve()
    date = args.verification_date
    if not date or len(date) != 10:
        raise VerificationError("generate requires --verification-date YYYY-MM-DD")
    datetime.strptime(date, "%Y-%m-%d")
    before = {x: sha256(dataset / x) for x in ("dataset_manifest.json", "ports.json", "services.json", "shipments.json", "route_plans.json")}
    labels = generate_labels(dataset, scenario_root, policy_path, commit_id(root), date)
    for label in labels:
        write_json(output / f"{label['scenario_id']}.json", label)
        print(f"generated {ref(output / (label['scenario_id'] + '.json'), root)} status={label['verification_status']} affected={len(label['expected_impact']['affected_shipment_ids'])}")
    after = {x: sha256(dataset / x) for x in before}
    if before != after:
        raise RuntimeError("canonical dataset hash changed during independent generation")
    print(json.dumps({"dataset_hashes_unchanged": True, "canonical_hashes": after,
                      "ground_truth_sha256": {sid: sha256(output / f"{sid}.json") for sid in SCENARIOS}}, sort_keys=True, indent=2))


def signature(route: list[dict]):
    return [(x.get("service_id"), x.get("origin_port_id"), x.get("destination_port_id"),
             x.get("departure_time"), x.get("arrival_time")) for x in route]


def compare(args, root: Path):
    dataset = (root / args.dataset).resolve()
    ground_truth = (root / args.ground_truth).resolve()
    run_root = (root / args.run_outputs).resolve()
    comparison_root = (root / args.comparisons).resolve()
    _, dataset_hashes, ports, services, shipments, plans, ship_by_id, plan_by_ship, service_by_id, port_ids = load_canonical(dataset)
    reference_before = {sid: sha256(ground_truth / f"{sid}.json") for sid in SCENARIOS}
    mismatches = []
    summary_rows = []
    for sid in SCENARIOS:
        label_path = ground_truth / f"{sid}.json"
        label_hash = reference_before[sid]
        label = read_json(label_path)
        if label.get("scenario_id") != sid or label.get("verification_status") != "VERIFIED":
            raise VerificationError(f"reference label missing or not verified: {sid}")
        p3_dir, p4_dir = run_root / sid / "phase3", run_root / sid / "phase4"
        p3_imp_path, p3_summary_path = p3_dir / "shipment_impacts.json", p3_dir / "summary.json"
        p4_results_path, p4_summary_path, p4_validation_path = p4_dir / "recovery_results.json", p4_dir / "summary.json", p4_dir / "constraint_validation.json"
        p3_impacts, p3_summary = read_json(p3_imp_path), read_json(p3_summary_path)
        p4_results, p4_summary = read_json(p4_results_path), read_json(p4_summary_path)
        p4_validation = read_json(p4_validation_path)
        reference_ids = label["expected_impact"]["affected_shipment_ids"]
        observed_p3_ids = sorted({x["shipment_id"] for x in p3_impacts})
        p3_membership = reference_ids == observed_p3_ids
        ref_by_id = {x["shipment_id"]: x for x in label["expected_impact"]["affected_shipments"]}
        p3_rows = {x["shipment_id"]: x for x in p3_impacts}
        p3_evidence_comparison = []
        for affected in reference_ids:
            expected = ref_by_id[affected]
            observed = p3_rows.get(affected, {})
            expected_direct = expected.get("direct_leg_ids", [])
            expected_indirect = expected.get("indirect_leg_ids", [])
            expected_reasons = set(expected.get("reason_codes", []))
            observed_reasons = {c.get("reason_code") for c in observed.get("causes", [])}
            item = {
                "shipment_id": affected,
                "direct_leg_ids_agree": expected_direct == observed.get("direct_leg_ids", []),
                "indirect_leg_ids_agree": expected_indirect == observed.get("indirect_leg_ids", []),
                "reason_codes_agree": expected_reasons == observed_reasons,
                "expected_reason_codes": sorted(expected_reasons), "observed_reason_codes": sorted(observed_reasons),
            }
            p3_evidence_comparison.append(item)
        p3_evidence_agrees = all(x["direct_leg_ids_agree"] and x["indirect_leg_ids_agree"] and x["reason_codes_agree"] for x in p3_evidence_comparison)

        p4_by_id = {x["shipment_id"]: x for x in p4_results}
        duplicate_p4_ids = len(p4_by_id) != len(p4_results)
        observed_p4_affected = sorted(x["shipment_id"] for x in p4_results if x.get("recovery_status") != "UNCHANGED")
        p4_membership = not duplicate_p4_ids and observed_p4_affected == reference_ids
        expected_statuses = {sid2: row["expected_recovery_status"] for row in label["expected_recovery"] for sid2 in [row["shipment_id"]]}
        all_ids = label["expected_impact"]["affected_shipment_ids"] + label["expected_impact"]["unaffected_shipment_ids"]
        for shipment_id in label["expected_impact"]["unaffected_shipment_ids"]:
            expected_statuses[shipment_id] = "UNCHANGED"
        status_details = []
        for shipment_id in sorted(set(all_ids) | set(p4_by_id)):
            expected_status = expected_statuses.get(shipment_id)
            observed_status = p4_by_id.get(shipment_id, {}).get("recovery_status")
            if expected_status != observed_status:
                status_details.append({"shipment_id": shipment_id, "expected": expected_status, "observed": observed_status})
        p4_status_agrees = not status_details and len(p4_by_id) == len(all_ids)
        recovery_by_id = {x["shipment_id"]: x for x in label["expected_recovery"]}
        route_comparisons = []
        for shipment_id in reference_ids:
            expected = recovery_by_id[shipment_id]
            observed = p4_by_id.get(shipment_id, {})
            expected_route = expected.get("reference_routes", [{}])[0] if expected.get("reference_routes") else None
            observed_suffix = observed.get("replacement_suffix", [])
            observed_validation = None
            if expected_route is not None and observed.get("recovery_status") == "RECOVERED":
                state = expected["recovery_state"]
                independent = check_route(ship_by_id[shipment_id], plan_by_ship[shipment_id], state,
                                          observed_suffix, service_by_id, label["hidden_reference_event"]["events"],
                                          read_json(root / args.policy))
                observed_validation = {"valid": independent["valid"], "checks": independent["checks"],
                                       "eta": independent["eta"], "total_cost_usd": independent["total_cost_usd"],
                                       "deadline_met": independent["deadline_met"]}
            expected_sig = signature(expected_route["replacement_suffix"]) if expected_route else []
            observed_sig = signature(observed_suffix)
            expected_svc = expected_route["service_sequence"] if expected_route else []
            observed_full = observed.get("full_revised_itinerary", [])
            observed_svc = [x.get("service_id") for x in observed_full]
            expected_ports = expected_route["port_sequence"] if expected_route else []
            observed_ports = ([observed_full[0].get("origin_port_id")] + [x.get("destination_port_id") for x in observed_full]) if observed_full else []
            eta_agrees = expected_route is not None and observed.get("recovered_eta") == expected_route["modeled_final_eta"]
            p4_cost = observed.get("modeled_total_cost_usd")
            cost_agrees = expected_route is not None and p4_cost is not None and abs(Decimal(str(p4_cost)) - Decimal(expected_route["cost_calculation"]["modeled_total_cost_usd"])) <= CENT
            route_comparisons.append({
                "shipment_id": shipment_id, "expected_recovery_classification": expected["recovery_classification"],
                "observed_phase4_status": observed.get("recovery_status"),
                "selected_reference_service_sequence": expected_svc, "observed_full_service_sequence": observed_svc,
                "service_sequence_agrees": expected_svc == observed_svc,
                "selected_reference_port_sequence": expected_ports, "observed_full_port_sequence": observed_ports,
                "port_sequence_agrees": expected_ports == observed_ports,
                "reference_suffix_signature": expected_sig, "observed_suffix_signature": observed_sig,
                "replacement_suffix_exactly_matches_reference": expected_sig == observed_sig,
                "observed_route_independently_feasible": observed_validation["valid"] if observed_validation else False,
                "observed_route_independent_checks": observed_validation,
                "expected_eta": expected_route.get("modeled_final_eta") if expected_route else None,
                "observed_eta": observed.get("recovered_eta"), "eta_agrees": eta_agrees,
                "expected_total_cost_usd": expected_route.get("cost_calculation", {}).get("modeled_total_cost_usd") if expected_route else None,
                "observed_total_cost_usd": p4_cost, "cost_agrees_within_one_cent": cost_agrees,
                "deadline_met_independently": expected_route.get("deadline_met") if expected_route else None,
            })
        route_all_valid = all(x["observed_route_independently_feasible"] for x in route_comparisons)
        route_signature_agrees = all(x["replacement_suffix_exactly_matches_reference"] for x in route_comparisons)
        quantitative_agrees = all(x["eta_agrees"] and x["cost_agrees_within_one_cent"] for x in route_comparisons)
        result = "MATCH"
        if not (p3_membership and p3_evidence_agrees and p4_membership and p4_status_agrees and route_all_valid and quantitative_agrees):
            result = "MISMATCH"
            mismatches.append(sid)
        elif not route_signature_agrees:
            result = "FEASIBLE_ROUTE_DIFFERENCE"
        comp = {
            "comparison_version": "1.0", "scenario_id": sid, "comparison_result": result,
            "reference_label": {"path": ref(label_path, root), "sha256": label_hash,
                                "verification_status": label["verification_status"]},
            "observed_output_hashes": {
                ref(p3_imp_path, root): sha256(p3_imp_path), ref(p3_summary_path, root): sha256(p3_summary_path),
                ref(p4_results_path, root): sha256(p4_results_path), ref(p4_summary_path, root): sha256(p4_summary_path),
                ref(p4_validation_path, root): sha256(p4_validation_path),
            },
            "independent_impact_comparison": {
                "expected_affected_shipment_ids": reference_ids, "observed_phase3_affected_shipment_ids": observed_p3_ids,
                "phase3_membership_agrees": p3_membership, "phase3_leg_and_reason_evidence": p3_evidence_comparison,
                "phase3_evidence_agrees": p3_evidence_agrees,
            },
            "observed_phase3": {"summary": p3_summary},
            "independent_recovery_comparison": {
                "expected_status_distribution": distribution(expected_statuses),
                "observed_status_distribution": p4_summary.get("statuses", {}),
                "affected_membership_agrees": p4_membership, "status_agreement": p4_status_agrees,
                "status_mismatches": status_details, "route_sequence_and_quantitative_results": route_comparisons,
                "all_observed_routes_independently_feasible": route_all_valid,
                "all_selected_reference_route_signatures_agree": route_signature_agrees,
                "all_eta_and_cost_values_agree": quantitative_agrees,
            },
            "observed_phase4": {
                "summary": p4_summary,
                "relevant_results": [{"shipment_id": sid2, "recovery_status": row.get("recovery_status"),
                                      "reason_code": row.get("reason_code"), "reason": row.get("reason"),
                                      "missing_information": row.get("missing_information"),
                                      "recovery_state": row.get("recovery_state"),
                                      "recovery_plan": row.get("recovery_plan"),
                                      "replacement_suffix": row.get("replacement_suffix"),
                                      "full_revised_itinerary": row.get("full_revised_itinerary"),
                                      "recovered_eta": row.get("recovered_eta"),
                                      "modeled_total_cost_usd": row.get("modeled_total_cost_usd"),
                                      "additional_cost_usd": row.get("additional_cost_usd")}
                                     for sid2, row in sorted(p4_by_id.items()) if sid2 in reference_ids],
                "constraint_validation_observed": [x for x in p4_validation if x.get("shipment_id") in reference_ids],
            },
            "limitations": ["Phase 4 statuses and validator records are observed corroboration, not independent labels.",
                            "The independent search is limited by the declared recovery policy bounds; no global optimality is claimed.",
                            "Individual capacity is modeled per shipment and does not establish shared real-world booking availability."],
        }
        write_json(comparison_root / f"{sid}.json", comp)
        summary_rows.append({"scenario_id": sid, "comparison_result": result, "phase3_membership": p3_membership,
                             "phase4_statuses": p4_status_agrees, "all_routes_feasible": route_all_valid,
                             "reference_route_exact": route_signature_agrees})
        print(f"{sid}: {result}; Phase3-membership={p3_membership}; Phase4-status={p4_status_agrees}; routes-feasible={route_all_valid}; exact-reference-route={route_signature_agrees}")
    reference_after = {sid: sha256(ground_truth / f"{sid}.json") for sid in SCENARIOS}
    if reference_before != reference_after:
        raise RuntimeError("comparison modified ground-truth files")
    comparison_hashes = {sid: sha256(comparison_root / f"{sid}.json") for sid in SCENARIOS}
    print(json.dumps({"ground_truth_unchanged": True, "ground_truth_sha256": reference_after,
                      "comparison_sha256": comparison_hashes, "results": summary_rows,
                      "mismatches": mismatches}, sort_keys=True, indent=2))
    return mismatches


def distribution(status_by_id: dict[str, str]):
    counts = {}
    for status in status_by_id.values():
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="calculate independent reference labels")
    cmp = sub.add_parser("compare", help="compare labels with saved Phase 3/4 outputs")
    for cmd in (gen, cmp):
        cmd.add_argument("--dataset", default="data/builds/research_1500")
        cmd.add_argument("--policy", default="config/recovery_policy.json")
        cmd.add_argument("--scenario-root", default="examples/phase5")
        cmd.add_argument("--ground-truth", default="evaluation/ground_truth")
    gen.add_argument("--verification-date", required=True, help="fixed date YYYY-MM-DD for reproducible labels")
    cmp.add_argument("--comparisons", default="evaluation/comparisons")
    cmp.add_argument("--run-outputs", default="data/simulations/phase5/phase5_2d")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "generate":
        generate(args, ROOT)
    else:
        compare(args, ROOT)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, ArithmeticError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
