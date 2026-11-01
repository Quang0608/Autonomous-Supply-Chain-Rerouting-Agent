"""Integrity checks for canonical logistics JSON records."""
from __future__ import annotations


def validate_records(ports, services, shipments, route_plans, supplier_edge_ids, strict=False, expected_count=None, original_edges=None):
    errors = []
    port_ids = [p.get("port_id") for p in ports]
    if len(set(port_ids)) != len(port_ids) or any(not x for x in port_ids):
        errors.append("Port IDs must be unique and non-empty")
    known = set(port_ids)
    service_ids = [s.get("service_id") for s in services]
    if len(set(service_ids)) != len(service_ids) or any(not x for x in service_ids):
        errors.append("Service IDs must be unique and non-empty")
    service_map = {s.get("service_id"): s for s in services}
    for p in ports:
        lat, lon = p.get("latitude"), p.get("longitude")
        verified = p.get("verified") is True
        if strict and not verified:
            errors.append(f"Port {p.get('port_id')} is not verified")
        if strict and (not p.get("source_url") or not p.get("dataset_version") or not p.get("retrieved_date") or not p.get("license")):
            errors.append(f"Port {p.get('port_id')} lacks source URL/version/retrieval/license provenance")
        if lat is None or lon is None:
            if verified or strict:
                errors.append(f"Port {p.get('port_id')} has missing coordinates")
        elif not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180):
            errors.append(f"Port {p.get('port_id')} has invalid latitude/longitude")
    for s in services:
        sid = s.get("service_id")
        a, b = s.get("origin_port_id"), s.get("destination_port_id")
        if a not in known or b not in known:
            errors.append(f"Service {sid} references an unknown port")
        if a == b:
            errors.append(f"Service {sid} is a self-loop")
        if float(s.get("transit_days", 0)) <= 0:
            errors.append(f"Service {sid} has nonpositive transit_days")
        if float(s.get("cost_units", -1)) < 0:
            errors.append(f"Service {sid} has negative cost_units")
        if s.get("direction") != "DIRECTED":
            errors.append(f"Service {sid} must declare direction=DIRECTED")
        if strict and (not s.get("source_class") or not s.get("source_reference") or not s.get("distance_method")):
            errors.append(f"Service {sid} lacks source class, reference, or distance method")
        if strict and float(s.get("distance_nm", 0)) <= 0:
            errors.append(f"Service {sid} has nonpositive distance_nm")
        if strict and float(s.get("departure_frequency_days", 0)) <= 0:
            errors.append(f"Service {sid} has invalid departure schedule")
        if strict and float(s.get("capacity_teu", 0)) <= 0:
            errors.append(f"Service {sid} has invalid capacity")
        if strict and s.get("source_class")=="OBSERVED_AIS_MOVEMENT":
            errors.append(f"AIS movement {sid} cannot be represented as a commercial service")
    plans = {p.get("route_plan_id"): p for p in route_plans}
    if len(plans) != len(route_plans):
        errors.append("Route plan IDs must be unique")
    seen_shipments = set()
    for sh in shipments:
        sid = sh.get("shipment_id")
        if sid in seen_shipments:
            errors.append(f"Duplicate shipment ID {sid}")
        seen_shipments.add(sid)
        if sh.get("supplier_edge_id") not in supplier_edge_ids:
            errors.append(f"Shipment {sid} references unknown supplier_edge_id")
        if original_edges and sh.get("supplier_edge_id") in original_edges:
            edge=original_edges[sh["supplier_edge_id"]]
            if sh.get("supplier")!=edge["Supplier"] or sh.get("customer")!=edge["Customer"]:
                errors.append(f"Shipment {sid} supplier/customer differ from original direct edge")
        plan = plans.get(sh.get("route_plan_id"))
        if not plan:
            errors.append(f"Shipment {sid} references missing route plan")
            continue
        if plan.get("shipment_id")!=sid:errors.append(f"Route plan {plan.get('route_plan_id')} references a different shipment")
        ids = plan.get("service_ids", [])
        if not ids:
            errors.append(f"Route plan {plan.get('route_plan_id')} has no services")
            continue
        route = [service_map.get(i) for i in ids]
        if any(x is None for x in route):
            errors.append(f"Route plan {plan.get('route_plan_id')} references unknown service ID")
            continue
        for left, right in zip(route, route[1:]):
            if left["destination_port_id"] != right["origin_port_id"]:
                errors.append(f"Route plan {plan.get('route_plan_id')} has disconnected or reversed legs")
                break
        detailed=plan.get("ordered_legs",[])
        if len(detailed)!=len(route):errors.append(f"Route plan {plan.get('route_plan_id')} ordered leg count mismatch")
        for ix,leg in enumerate(detailed):
            if leg.get("sequence")!=ix+1:errors.append(f"Route plan {plan.get('route_plan_id')} legs are out of order")
            if ix<len(route) and leg.get("service_id")!=route[ix].get("service_id"):errors.append(f"Route plan {plan.get('route_plan_id')} leg service mismatch")
            if leg.get("planned_arrival",0)<=leg.get("planned_departure",0):errors.append(f"Route plan {plan.get('route_plan_id')} has invalid leg times")
            if ix<len(route) and (leg.get("origin_port_id")!=route[ix].get("origin_port_id") or leg.get("destination_port_id")!=route[ix].get("destination_port_id")):
                errors.append(f"Route plan {plan.get('route_plan_id')} leg endpoints differ from directed service")
            if ix<len(route) and float(sh.get("cargo_teu",0))>float(route[ix].get("capacity_teu",float("inf"))):
                errors.append(f"Shipment {sid} exceeds service capacity")
            if ix<len(route) and sh.get("cargo_class") not in route[ix].get("cargo_classes",[sh.get("cargo_class")]):
                errors.append(f"Shipment {sid} uses a service incompatible with cargo class")
            if ix<len(route) and strict:
                freq=float(route[ix].get("departure_frequency_days",0))
                if freq and abs(leg.get("planned_departure",0)/freq-round(leg.get("planned_departure",0)/freq))>1e-4:
                    errors.append(f"Route plan {plan.get('route_plan_id')} misses periodic departure")
            if ix and leg.get("planned_departure",0)<detailed[ix-1].get("planned_arrival",0)+float(leg.get("min_transfer_hours",0))/24-1e-5:
                errors.append(f"Route plan {plan.get('route_plan_id')} violates transfer/departure timing")
        if route[0]["origin_port_id"] != sh.get("origin_port_id") or route[-1]["destination_port_id"] != sh.get("destination_port_id"):
            errors.append(f"Route plan {plan.get('route_plan_id')} endpoints do not match shipment")
        if sh.get("origin_port_id") == sh.get("destination_port_id"):
            errors.append(f"Shipment {sid} origin and destination must differ")
        arrival = sh.get("release_day", 0) + plan.get("transit_days", 0)
        if plan.get("transit_days", 0) <= 0 or arrival > sh.get("deadline_day", -1):
            errors.append(f"Shipment {sid} has impossible transit time or deadline")
        if detailed and (detailed[-1]["planned_arrival"]>sh.get("deadline_day",-1) or detailed[0]["planned_departure"]<sh.get("release_day",0)):
            errors.append(f"Shipment {sid} violates release/deadline schedule")
        expected_cost=round(sum(float(l.get("modeled_cost_usd",0)) for l in detailed),2)
        if detailed and abs(expected_cost-float(plan.get("total_cost_usd",expected_cost)))>0.02:
            errors.append(f"Route plan {plan.get('route_plan_id')} total cost mismatch")
    if expected_count is not None and len(shipments)!=expected_count:errors.append(f"Expected exactly {expected_count} shipments, got {len(shipments)}")
    if len(plans)!=len(shipments):errors.append("Every shipment must have exactly one route plan")
    return errors
