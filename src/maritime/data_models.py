"""Standard-library records used by the canonical logistics dataset."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Port:
    port_id: str
    name: str
    country: str
    latitude: float | None
    longitude: float | None
    source: str
    source_reference: str
    verified: bool
    source_class: str


@dataclass(frozen=True)
class ServiceConnection:
    service_id: str
    origin_port_id: str
    destination_port_id: str
    direction: str
    service_evidence: str
    source_reference: str
    source_class: str
    distance_nm: float
    distance_method: str
    transit_days: float
    transit_method: str
    departure_frequency_days: float
    min_transfer_hours: float
    cost_per_teu_usd: float
    capacity_teu: int
    cargo_classes: tuple[str, ...]


@dataclass(frozen=True)
class PlannedLeg:
    sequence: int
    service_id: str
    origin_port_id: str
    destination_port_id: str
    planned_departure: float
    planned_arrival: float
    modeled_cost_usd: float


@dataclass(frozen=True)
class RoutePlan:
    route_plan_id: str
    shipment_id: str
    ordered_legs: tuple[PlannedLeg, ...]
    total_cost_usd: float
    estimated_arrival: float


@dataclass(frozen=True)
class Shipment:
    shipment_id: str
    supplier_edge_id: str
    origin_port_id: str
    destination_port_id: str
    release_time: float
    delivery_deadline: float
    cargo_teu: int
    source_class: str
    initial_plan_id: str
