"""Deterministic, bounded maritime recovery over the Phase 2 modeled graph."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
import csv
import hashlib
import heapq
import json
from pathlib import Path

from .phase3 import analyze, day_time, iso, load_json, parse_time, _inside, _overlap
from .recovery_validation import checks_for_route

VERSION = "phase4-recovery-1.1.0"
SCHEMA = "1.1"
POLICY_SCHEMA = "1.0"
RECOVERY_STATUSES = (
    "UNCHANGED", "NO_REROUTE_REQUIRED", "RECOVERED", "NO_FEASIBLE_ROUTE",
    "DEADLINE_INFEASIBLE", "OPERATOR_INTERVENTION_REQUIRED", "SEARCH_LIMIT_REACHED",
)


def policy_at(path: Path) -> dict:
    policy = load_json(path)
    if policy.get("schema_version") != POLICY_SCHEMA or any(int(policy[k]) <= 0 for k in (
        "max_hops", "horizon_days", "departures_per_service", "max_expansions",
        "max_candidates", "max_labels_per_port"
    )):
        raise ValueError("invalid recovery policy")
    return policy


def departures(service: dict, ready, policy: dict):
    frequency = Decimal(str(service["departure_frequency_days"]))
    if frequency <= 0:
        raise ValueError("service frequency must be positive")
    start = Decimal(str((ready - day_time(0)).total_seconds())) / Decimal(86400)
    anchor = Decimal(str(policy["departure_anchor_day"]))
    first = int(((start - anchor) / frequency).to_integral_value(rounding=ROUND_CEILING))
    for n in range(first, first + policy["departures_per_service"]):
        yield day_time(float(anchor + frequency * n))


def recovery_state(shipment, plan, impact, no_recovery, scenario):
    """Locate the first actionable disruption without changing completed legs."""
    legs = plan["ordered_legs"]
    causes = impact["causes"]
    unresolved = next((c for c in causes if c["reason_code"] == "UNRESOLVED_CONNECTION"), None)
    blocking_departures = [c for c in causes if c["operation"] == "DEPARTURE" and c["event_type"] in (
        "PORT_CLOSURE", "SERVICE_SUSPENSION"
    )]
    first_departure = min(blocking_departures, key=lambda c: (c["conflict_time"], c["leg_id"], c["event_id"])) if blocking_departures else None
    first_action_time = min((c["conflict_time"] for c in (unresolved, first_departure) if c), default=None)
    unsupported_closures = [c for c in causes if c["event_type"] == "PORT_CLOSURE"
                            and c["operation"] in ("ARRIVAL", "TRANSSHIPMENT")
                            and (first_action_time is None or c["conflict_time"] <= first_action_time)]
    if unsupported_closures:
        cause = min(unsupported_closures, key=lambda c: (c["conflict_time"], c["leg_id"], c["event_id"]))
        if cause["operation"] == "ARRIVAL":
            code = "ARRIVAL_CLOSURE_POSITION_UNRESOLVED"
            missing = [
                f"Actual position and movement state for shipment {shipment['shipment_id']} at arrival closure {cause['event_id']}",
                f"Carrier-authorized diversion options for reaching or bypassing port {cause['target_entity_id']}",
            ]
            explanation = (f"Shipment {shipment['shipment_id']} has a planned arrival at closed port "
                           f"{cause['target_entity_id']}; its actual position and authorized diversion options are unknown.")
        else:
            code = "TRANSSHIPMENT_HANDLING_POLICY_UNAVAILABLE"
            missing = [
                f"Actual cargo and vessel state for shipment {shipment['shipment_id']} at port {cause['target_entity_id']}",
                f"Supported handling policy and authorization for waiting, unloading, transfer, or departure during closure {cause['event_id']}",
            ]
            explanation = (f"Shipment {shipment['shipment_id']} has an affected transshipment at "
                           f"{cause['target_entity_id']}; the model cannot establish whether it can safely remain, be handled, or depart.")
        return None, {"reason_code": code, "reason": explanation,
                      "missing_information": missing,
                      "affected_leg_ids": sorted({c["leg_id"] for c in unsupported_closures}),
                      "event_ids": sorted({c["event_id"] for c in unsupported_closures})}
    if unresolved:
        index = int(unresolved["leg_id"].rsplit(":L", 1)[1]) - 1
        inbound_arrival = parse_time(unresolved["conflict_time"])
        ready = inbound_arrival + timedelta(hours=float(legs[index].get("min_transfer_hours", 0)))
        reason = "MISSED_FIXED_CONNECTION"
        ids = sorted({c["event_id"] for c in causes if c["reason_code"] == "UNRESOLVED_CONNECTION"})
    else:
        if not blocking_departures:
            relevant = sorted(causes, key=lambda c: (c["conflict_time"], c["leg_id"], c["event_id"]))
            event_ids = sorted({c["event_id"] for c in relevant})
            leg_ids = sorted({c["leg_id"] for c in relevant})
            return None, {"reason_code": "SAFE_RECOVERY_STATE_UNDETERMINED",
                          "reason": f"Shipment {shipment['shipment_id']} is disrupted, but the available event evidence does not establish a safe recovery starting state.",
                          "missing_information": ["Verified shipment position and execution state at the disruption time",
                                                  "Supported operational decision policy for the detected disruption"],
                          "affected_leg_ids": leg_ids, "event_ids": event_ids}
        first = first_departure
        index = int(first["leg_id"].rsplit(":L", 1)[1]) - 1
        arrival = day_time(shipment.get("release_time", shipment["release_day"])) if index == 0 else day_time(legs[index-1]["planned_arrival"])
        if index:
            delayed_events = {c["event_id"] for c in causes if c["leg_id"] == f'{plan["route_plan_id"]}:L{index}'
                              and c["reason_code"] == "SERVICE_DELAY_DEPARTURE_OVERLAP"
                              and c.get("effect_applied", True)}
            arrival += timedelta(hours=sum(float(e["delay_hours"]) for e in scenario["events"]
                                       if e["event_id"] in delayed_events))
        transfer = timedelta(hours=float(legs[index].get("min_transfer_hours", 0))) if index else timedelta()
        ready = max(arrival + transfer, parse_time(first["conflict_time"]))
        reason = "BLOCKED_FIXED_DEPARTURE"
        ids = sorted({c["event_id"] for c in blocking_departures if c["leg_id"] == first["leg_id"]})
    completed = [f'{plan["route_plan_id"]}:L{i+1}' for i in range(index)]
    prefix = [dict(legs[i], leg_id=completed[i]) for i in range(index)]
    state = {
        "shipment_id": shipment["shipment_id"], "completed_leg_ids": completed,
        "executed_prefix": prefix, "recovery_port_id": legs[index]["origin_port_id"],
        "earliest_recovery_time": iso(ready),
        "first_disruption_event_ids": ids, "position_confidence": "MODELED_PORT_STATE",
        "state_reason": reason, "unexecuted_original_suffix": legs[index:],
    }
    if unresolved:
        state["recovery_port_id"] = legs[index-1]["destination_port_id"]
        state["executed_prefix"][-1]["actual_arrival_time"] = iso(inbound_arrival)
    elif index:
        state["executed_prefix"][-1]["actual_arrival_time"] = iso(arrival)
    return state, None


def _search(shipment, state, services, scenario, policy):
    by_origin = {}
    for service in services:
        by_origin.setdefault(service["origin_port_id"], []).append(service)
    for value in by_origin.values():
        value.sort(key=lambda x: x["service_id"])
    start = parse_time(state["earliest_recovery_time"])
    horizon = start + timedelta(days=policy["horizon_days"])
    queue = [(0.0, iso(start), (), 0, state["recovery_port_id"], [], frozenset((state["recovery_port_id"],)))]
    sequence = 0
    candidates, expansions = [], 0
    labels = {}
    frontiers = {state["recovery_port_id"]: [(0.0, start, frozenset((state["recovery_port_id"],)))]}
    limited = False
    while queue:
        if expansions >= policy["max_expansions"] or len(candidates) >= policy["max_candidates"]:
            limited = True
            break
        cost, ready_text, ids, _, port, path, visited = heapq.heappop(queue)
        expansions += 1
        ready = parse_time(ready_text)
        if port == shipment["destination_port_id"]:
            candidates.append({"replacement_suffix": path, "modeled_cost_usd": round(cost, 2),
                               "eta": iso(parse_time(path[-1]["arrival_time"])) if path else ready_text})
            continue
        if len(path) >= policy["max_hops"]:
            continue
        label_key = (port, len(path))
        labels[label_key] = labels.get(label_key, 0) + 1
        if labels[label_key] > policy["max_labels_per_port"]:
            limited = True
            continue
        for svc in by_origin.get(port, []):
            dest = svc["destination_port_id"]
            if dest in visited:
                continue
            if svc.get("cargo_classes") is not None and shipment["cargo_class"] not in svc["cargo_classes"]:
                continue
            if svc.get("capacity_teu") is not None and float(shipment["cargo_teu"]) > float(svc["capacity_teu"]):
                continue
            for dep in departures(svc, ready, policy):
                if dep < ready or dep > horizon:
                    continue
                blocking = []
                delays = []
                for event in scenario["events"]:
                    if event["type"] == "PORT_CLOSURE" and event["target_port_id"] == port:
                        if "DEPARTURE" in event["affected_operations"] and _inside(dep, event):
                            blocking.append(event["event_id"])
                        if path and "TRANSSHIPMENT" in event["affected_operations"] and _overlap(
                            parse_time(path[-1]["arrival_time"]), dep, event
                        ):
                            blocking.append(event["event_id"])
                        if not path and state["executed_prefix"] and "TRANSSHIPMENT" in event["affected_operations"]:
                            inbound = state["executed_prefix"][-1]
                            inbound_time = parse_time(inbound.get("actual_arrival_time", iso(day_time(inbound["planned_arrival"]))))
                            if _overlap(inbound_time, dep, event):
                                blocking.append(event["event_id"])
                    if event.get("target_service_id") == svc["service_id"] and _inside(dep, event):
                        if event["type"] == "SERVICE_SUSPENSION":
                            blocking.append(event["event_id"])
                        elif event["type"] == "SERVICE_DELAY":
                            delays.append(event)
                if blocking:
                    continue
                arr = dep + timedelta(days=float(svc["transit_days"]),
                                      hours=sum(float(e["delay_hours"]) for e in delays))
                if arr > horizon:
                    continue
                if any(e["type"] == "PORT_CLOSURE" and e["target_port_id"] == dest
                       and "ARRIVAL" in e["affected_operations"] and _inside(arr, e)
                       for e in scenario["events"]):
                    continue
                edge_cost = float(svc["cost_per_teu_usd"]) * float(shipment["cargo_teu"])
                leg = {"service_id": svc["service_id"], "origin_port_id": port,
                       "destination_port_id": dest, "departure_time": iso(dep), "arrival_time": iso(arr),
                       "modeled_cost_usd": round(edge_cost, 2),
                       "applied_delay_event_ids": sorted(e["event_id"] for e in delays)}
                new_cost = cost + edge_cost
                next_ready = arr if dest == shipment["destination_port_id"] else arr + timedelta(hours=float(svc.get("min_transfer_hours", 0)))
                new_visited = visited | {dest}
                frontier = frontiers.setdefault(dest, [])
                if any(old_cost <= new_cost and old_ready <= next_ready and old_visited <= new_visited
                       for old_cost, old_ready, old_visited in frontier):
                    continue
                frontier[:] = [(old_cost, old_ready, old_visited)
                               for old_cost, old_ready, old_visited in frontier
                               if not (new_cost <= old_cost and next_ready <= old_ready and new_visited <= old_visited)]
                frontier.append((new_cost, next_ready, new_visited))
                sequence += 1
                heapq.heappush(queue, (new_cost, iso(next_ready), ids + (svc["service_id"],), sequence,
                                       dest, path + [leg], new_visited))
    return candidates, {"expansions": expansions, "candidates": len(candidates), "search_limited": limited}


def recover(dataset_dir: Path, scenario_raw: dict, policy: dict):
    scenario, impacts, no_recovery, phase3 = analyze(dataset_dir, scenario_raw)
    shipments = load_json(dataset_dir / "shipments.json")
    plans = load_json(dataset_dir / "route_plans.json")
    services = load_json(dataset_dir / "services.json")
    if len(shipments) == 1500 and (len(plans), len(services)) != (1500, 122):
        raise ValueError("canonical dataset count mismatch")
    by_plan = {p["route_plan_id"]: p for p in plans}
    by_impact = {x["shipment_id"]: x for x in impacts}
    by_no = {x["shipment_id"]: x for x in no_recovery}
    results, states, validations = [], [], []
    diagnostics = {"expansions": 0, "candidates": 0, "attempted": 0}
    for shipment in sorted(shipments, key=lambda x: x["shipment_id"]):
        sid = shipment["shipment_id"]
        plan = by_plan[shipment["route_plan_id"]]
        no = by_no[sid]
        impact = by_impact.get(sid)
        common = {"shipment_id": sid, "plan_id": plan["route_plan_id"],
                  "no_recovery_status": no["status"], "original_plan": plan["ordered_legs"],
                  "original_eta": no["original_eta"], "no_recovery_eta": no["baseline_eta"],
                  "affected_leg_ids": sorted({leg for leg in ((impact or {}).get("direct_leg_ids", []) + (impact or {}).get("indirect_leg_ids", []))}),
                  "deadline": no["deadline"], "event_ids": sorted({
                      c["event_id"] for c in impact["causes"] if c["event_id"]
                  }) if impact else []}
        if impact is None:
            results.append(dict(common, recovery_status="UNCHANGED", reason_code="NO_PHASE3_IMPACT",
                                recovered_eta=no["baseline_eta"], replacement_suffix=[]))
            continue
        if no["status"] == "DELAYED" and no["baseline_eta"] is not None:
            results.append(dict(common, recovery_status="NO_REROUTE_REQUIRED", reason_code="FIXED_CONNECTION_RECOVERED",
                                recovered_eta=no["baseline_eta"], replacement_suffix=[]))
            continue
        if no["status"] == "DEADLINE_MISSED" and no["baseline_eta"] is not None:
            results.append(dict(common, recovery_status="DEADLINE_INFEASIBLE",
                                reason_code="ARRIVAL_AFTER_DEADLINE_WITH_NO_IN_TRANSIT_DIVERSION",
                                recovered_eta=None, replacement_suffix=[], late_diagnostic_eta=no["baseline_eta"]))
            continue
        state, intervention = recovery_state(shipment, plan, impact, no, scenario)
        if intervention:
            results.append(dict(common, recovery_status="OPERATOR_INTERVENTION_REQUIRED",
                                reason_code=intervention["reason_code"], reason=intervention["reason"],
                                missing_information=intervention["missing_information"], recovery_plan=None,
                                affected_leg_ids=sorted(set(common["affected_leg_ids"]) | set(intervention["affected_leg_ids"])),
                                event_ids=sorted(set(common["event_ids"]) | set(intervention["event_ids"])),
                                recovered_eta=None))
            continue
        states.append(state)
        diagnostics["attempted"] += 1
        missing = []
        required_service_fields = ("departure_frequency_days", "transit_days", "cost_per_teu_usd", "cargo_classes", "capacity_teu")
        for service in services:
            missing.extend(f"Service {service.get('service_id', '<unknown>')} is missing {field}"
                           for field in required_service_fields if field not in service or service[field] is None)
        required_shipment_fields = ("cargo_class", "cargo_teu", "delivery_deadline")
        missing.extend(f"Shipment {sid} is missing {field}"
                       for field in required_shipment_fields if field not in shipment or shipment[field] is None)
        if missing:
            results.append(dict(common, recovery_status="OPERATOR_INTERVENTION_REQUIRED",
                                reason_code="ESSENTIAL_RECOVERY_DATA_MISSING",
                                reason=f"Shipment {sid} cannot be evaluated safely because required recovery data is missing.",
                                missing_information=missing, recovery_plan=None,
                                recovered_eta=None))
            continue
        candidates, stats = _search(shipment, state, services, scenario, policy)
        diagnostics["expansions"] += stats["expansions"]
        diagnostics["candidates"] += stats["candidates"]
        valid, late = [], []
        for candidate in candidates:
            checks = checks_for_route(shipment, plan, state, candidate["replacement_suffix"], services, scenario, policy)
            record = {"shipment_id": sid, "candidate_service_ids": [
                x["service_id"] for x in candidate["replacement_suffix"]
            ], "checks": checks}
            validations.append(record)
            failures = [x["constraint"] for x in checks if x["result"] != "PASS"]
            if not failures:
                valid.append(candidate)
            elif failures == ["HARD_DEADLINE"]:
                late.append(candidate)
        rank = lambda x: (x["modeled_cost_usd"], x["eta"], len(x["replacement_suffix"]),
                          tuple(y["service_id"] for y in x["replacement_suffix"]))
        if stats["search_limited"]:
            results.append(dict(common, recovery_status="SEARCH_LIMIT_REACHED", reason_code="SEARCH_LIMIT_REACHED",
                                recovery_state=state, replacement_suffix=[], recovered_eta=None,
                                validated_candidate_diagnostic=min(valid, key=rank) if valid else None))
        elif valid:
            best = min(valid, key=rank)
            prefix_cost = sum(float(x.get("modeled_cost_usd", 0)) for x in state["executed_prefix"])
            original_cost = plan.get("total_cost_usd")
            revised_cost = round(prefix_cost + best["modeled_cost_usd"], 2)
            results.append(dict(common, recovery_status="RECOVERED", reason_code="VALIDATED_ALTERNATE",
                                recovery_state=state, executed_prefix=state["executed_prefix"],
                                unexecuted_original_suffix=state["unexecuted_original_suffix"],
                                replacement_suffix=best["replacement_suffix"],
                                full_revised_itinerary=state["executed_prefix"] + best["replacement_suffix"],
                                recovered_eta=best["eta"], deadline_met=True, modeled_total_cost_usd=revised_cost,
                                additional_delay_hours=round((parse_time(best["eta"]) - parse_time(no["original_eta"])).total_seconds()/3600, 6),
                                additional_cost_usd=round(revised_cost - float(original_cost), 2) if original_cost is not None else None))
        else:
            status = "SEARCH_LIMIT_REACHED" if stats["search_limited"] else (
                "DEADLINE_INFEASIBLE" if late else "NO_FEASIBLE_ROUTE"
            )
            results.append(dict(common, recovery_status=status, reason_code=status,
                                recovery_state=state, replacement_suffix=[], recovered_eta=None,
                                late_diagnostic=min(late, key=rank) if late else None))
    counts = {status: sum(x["recovery_status"] == status for x in results) for status in RECOVERY_STATUSES}
    summary = {"schema_version": SCHEMA, "scenario_id": scenario["scenario_id"],
               "total_shipments": len(shipments), "affected_shipments": len(impacts),
               "attempted": diagnostics["attempted"], "statuses": counts,
               "no_recovery_statuses": {status: sum(x["status"] == status for x in no_recovery)
                                        for status in sorted({x["status"] for x in no_recovery})},
               "independent_validation_pass": sum(all(c["result"] == "PASS" for c in x["checks"]) for x in validations),
               "independent_validation_fail": sum(any(c["result"] == "FAIL" for c in x["checks"]) for x in validations),
               "search_diagnostics": diagnostics}
    assert len(results) == len(shipments) == sum(counts.values())
    return {"scenario": scenario, "phase3_impacts": impacts, "no_recovery": no_recovery,
            "phase3_report": phase3, "recovery_states": states, "recovery_results": results,
            "constraint_validation": validations, "summary": summary}


def write_outputs(dataset_dir: Path, scenario_raw: dict, policy_path: Path, out_dir: Path):
    policy = policy_at(policy_path)
    result = recover(dataset_dir, scenario_raw, policy)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": SCHEMA, "solver_version": VERSION,
                "scenario_id": result["scenario"]["scenario_id"],
                "dataset_manifest_sha256": hashlib.sha256((dataset_dir/"dataset_manifest.json").read_bytes()).hexdigest(),
                "canonical_file_sha256": {name: hashlib.sha256((dataset_dir/name).read_bytes()).hexdigest()
                                          for name in ("ports.json","services.json","shipments.json","route_plans.json")},
                "scenario_sha256": hashlib.sha256(json.dumps(scenario_raw,sort_keys=True).encode()).hexdigest(),
                "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
                "policy": policy, "simulation_epoch": iso(day_time(0)),
                "limitations": ["Modeled periodic departures and costs, not carrier bookings",
                                "Individual shipment capacity only; no shared residual capacity",
                                "Maritime graph only; no geographic chokepoints or inland legs"]}
    files = {"scenario_manifest.json": manifest,
             "phase3_input_impact_reference.json": {
                 "scenario_id": result["scenario"]["scenario_id"], "impacts": result["phase3_impacts"]},
             "recovery_states.json": result["recovery_states"],
             "recovery_results.json": result["recovery_results"],
             "constraint_validation.json": result["constraint_validation"],
             "comparison_no_recovery.json": [
                 {"shipment_id": row["shipment_id"], "no_recovery_status": row["status"],
                  "no_recovery_eta": row["baseline_eta"],
                  "recovery_status": recovered["recovery_status"], "recovered_eta": recovered.get("recovered_eta"),
                  "additional_cost_usd": recovered.get("additional_cost_usd"),
                  "additional_delay_hours": recovered.get("additional_delay_hours")}
                 for row, recovered in zip(result["no_recovery"], result["recovery_results"])
             ],
             "summary.json": result["summary"]}
    for name, value in files.items():
        (out_dir/name).write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (out_dir/"recovery_results.csv").open("w",encoding="utf-8",newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=["shipment_id","recovery_status","reason_code","reason",
                                                   "missing_information","recovery_plan","original_eta",
                                                   "no_recovery_eta","recovered_eta","deadline","affected_leg_ids","event_ids"])
        writer.writeheader()
        for row in result["recovery_results"]:
            writer.writerow({k: json.dumps(row.get(k)) if k in ("event_ids", "affected_leg_ids", "missing_information", "recovery_plan") else row.get(k) for k in writer.fieldnames})
    return result["summary"]
