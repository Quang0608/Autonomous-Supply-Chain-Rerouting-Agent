"""Validated domain models for the shipment-centered pilot dataset."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Port:
    id: str
    name: str
    source_class: str = "REAL_PORT_NAME__GATEWAY_MODELED"


@dataclass(frozen=True)
class ServiceLeg:
    id: str
    from_port: str
    to_port: str
    transit_days: int
    cost_units: int
    source_class: str = "SYNTHETIC_SERVICE"


@dataclass(frozen=True)
class RoutePlan:
    id: str
    status: str
    ports: tuple[str, ...]
    transit_days: int
    cost_units: int


@dataclass(frozen=True)
class Shipment:
    id: str
    supplier: str
    customer: str
    supplier_country: str
    customer_country: str
    cargo_class: str
    cargo_teu: int
    release_day: int
    deadline_day: int
    route: RoutePlan
    source_class: str


@dataclass(frozen=True)
class Disruption:
    id: str
    type: str
    port_id: str
    start_day: int
    end_day: int
    source_class: str = "SYNTHETIC_PILOT"


def validate_dataset(ports: list[dict[str, Any]], services: list[dict[str, Any]],
                     shipments: list[dict[str, Any]], disruption: dict[str, Any]) -> None:
    """Reject incomplete or internally inconsistent generated datasets."""
    port_ids = [p.get("id") for p in ports]
    if not ports or any(not x for x in port_ids) or len(set(port_ids)) != len(port_ids):
        raise ValueError("Ports must have unique, non-empty ids")
    known_ports = set(port_ids)
    service_ids = set()
    for service in services:
        sid = service.get("id") or f"{service.get('from')}__{service.get('to')}"
        if sid in service_ids:
            raise ValueError(f"Duplicate service id: {sid}")
        service_ids.add(sid)
        if service.get("from") not in known_ports or service.get("to") not in known_ports:
            raise ValueError(f"Service {sid} references an unknown port")
        if service.get("transit_days", 0) <= 0 or service.get("cost_units", -1) < 0:
            raise ValueError(f"Service {sid} has invalid time or cost")
    shipment_ids = set()
    for shipment in shipments:
        sid = shipment.get("shipment_id")
        route = shipment.get("original_route") or {}
        route_ports = route.get("ports") or []
        if not sid or sid in shipment_ids:
            raise ValueError("Shipments must have unique, non-empty ids")
        shipment_ids.add(sid)
        if len(route_ports) < 2 or any(p not in known_ports for p in route_ports):
            raise ValueError(f"Shipment {sid} has an invalid route")
        if shipment.get("cargo_teu", 0) <= 0 or shipment.get("release_day", -1) < 0:
            raise ValueError(f"Shipment {sid} has invalid cargo or release day")
        if shipment.get("deadline_day", -1) < shipment["release_day"] + route.get("transit_days", 0):
            raise ValueError(f"Shipment {sid} deadline precedes its modeled arrival")
    if disruption.get("port_id") not in known_ports:
        raise ValueError("Disruption references an unknown port")
    if disruption.get("start_day", -1) < 0 or disruption.get("end_day", -1) <= disruption.get("start_day", -1):
        raise ValueError("Disruption window must be a non-empty positive interval")
