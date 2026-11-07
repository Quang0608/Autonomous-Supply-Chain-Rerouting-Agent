"""Independent checks for Phase 4 proposed maritime itineraries."""
from __future__ import annotations

from datetime import timedelta

from .phase3 import day_time, iso, parse_time, _inside, _overlap


def checks_for_route(shipment, plan, state, suffix, services, scenario, policy):
    """Return PASS/FAIL/UNSUPPORTED records; callers accept only all PASS."""
    checks = []
    def check(code, ok, **evidence):
        checks.append({"constraint": code, "result": "PASS" if ok else "FAIL", **evidence})

    by_id = {s["service_id"]: s for s in services}
    expected_port = state["recovery_port_id"]
    ready = parse_time(state["earliest_recovery_time"])
    seen = {expected_port}
    prefix = state["executed_prefix"]
    immutable = len(prefix) == len(state["completed_leg_ids"])
    for i, item in enumerate(prefix):
        immutable = immutable and item["leg_id"] == f'{plan["route_plan_id"]}:L{i+1}'
        immutable = immutable and all(item.get(k) == plan["ordered_legs"][i].get(k) for k in (
            "service_id", "origin_port_id", "destination_port_id", "planned_departure",
            "planned_arrival", "modeled_cost_usd"
        ))
    check("PREFIX_IMMUTABLE", immutable)
    check("MAX_HOPS", len(suffix) <= policy["max_hops"])
    total_cost = 0.0
    for i, leg in enumerate(suffix):
        svc = by_id.get(leg["service_id"])
        check("SERVICE_EXISTS", svc is not None, leg=i, service_id=leg["service_id"])
        if svc is None:
            continue
        dep, arr = parse_time(leg["departure_time"]), parse_time(leg["arrival_time"])
        check("DIRECTED_CONTINUITY", expected_port == leg["origin_port_id"] == svc["origin_port_id"]
              and leg["destination_port_id"] == svc["destination_port_id"], leg=i)
        check("CHRONOLOGY", dep >= ready and arr > dep, leg=i)
        freq = float(svc["departure_frequency_days"])
        day = (dep - day_time(0)).total_seconds() / 86400
        anchor = float(policy["departure_anchor_day"])
        n = round((day - anchor) / freq) if freq > 0 else 0
        check("MODELED_DEPARTURE", freq > 0 and abs(day - (anchor + n * freq)) < 1e-7, leg=i)
        delay = sum(float(e["delay_hours"]) for e in scenario["events"]
                    if e["type"] == "SERVICE_DELAY" and e["target_service_id"] == svc["service_id"] and _inside(dep, e))
        expected_arr = dep + timedelta(days=float(svc["transit_days"]), hours=delay)
        check("TRANSIT_DURATION", abs((arr - expected_arr).total_seconds()) < 0.1, leg=i)
        blocked = []
        for event in scenario["events"]:
            if event["type"] == "SERVICE_SUSPENSION" and event["target_service_id"] == svc["service_id"] and _inside(dep, event):
                blocked.append(event["event_id"])
            if event["type"] == "PORT_CLOSURE":
                ops = event["affected_operations"]
                port = event["target_port_id"]
                if (port == svc["origin_port_id"] and "DEPARTURE" in ops and _inside(dep, event)) or (
                    port == svc["destination_port_id"] and "ARRIVAL" in ops and _inside(arr, event)):
                    blocked.append(event["event_id"])
                if i and port == svc["origin_port_id"] and "TRANSSHIPMENT" in ops and _overlap(
                    parse_time(suffix[i-1]["arrival_time"]), dep, event
                ):
                    blocked.append(event["event_id"])
                if i == 0 and prefix and port == svc["origin_port_id"] and "TRANSSHIPMENT" in ops:
                    inbound = parse_time(prefix[-1].get("actual_arrival_time", iso(day_time(prefix[-1]["planned_arrival"]))))
                    if _overlap(inbound, dep, event):
                        blocked.append(event["event_id"])
        check("ACTIVE_EVENTS", not blocked, leg=i, blocking_event_ids=sorted(set(blocked)))
        cargo = svc.get("cargo_classes")
        if cargo is None:
            checks.append({"constraint": "CARGO_CLASS", "result": "UNSUPPORTED", "leg": i})
        else:
            check("CARGO_CLASS", shipment["cargo_class"] in cargo, leg=i)
        capacity = svc.get("capacity_teu")
        if capacity is None:
            checks.append({"constraint": "INDIVIDUAL_CAPACITY", "result": "UNSUPPORTED", "leg": i})
        else:
            check("INDIVIDUAL_CAPACITY", float(shipment["cargo_teu"]) <= float(capacity), leg=i)
        cost = float(svc["cost_per_teu_usd"]) * float(shipment["cargo_teu"])
        total_cost += cost
        check("MODELED_COST", abs(float(leg["modeled_cost_usd"]) - cost) < 0.011, leg=i)
        check("NO_CYCLE", svc["destination_port_id"] not in seen, leg=i)
        seen.add(svc["destination_port_id"])
        expected_port = svc["destination_port_id"]
        ready = arr + timedelta(hours=float(svc.get("min_transfer_hours", 0)))
    check("DESTINATION", expected_port == shipment["destination_port_id"])
    if suffix:
        check("HORIZON", parse_time(suffix[-1]["arrival_time"]) <= parse_time(state["earliest_recovery_time"]) +
              timedelta(days=policy["horizon_days"]))
        check("HARD_DEADLINE", parse_time(suffix[-1]["arrival_time"]) <= day_time(shipment["delivery_deadline"]))
    else:
        check("HARD_DEADLINE", ready <= day_time(shipment["delivery_deadline"]))
    return checks
