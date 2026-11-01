# Canonical logistics data model

Canonical UTF-8 JSON outputs are `ports.json`, `services.json`, `shipments.json`, `route_plans.json`, and `dataset_manifest.json`. Every entity has a stable primary ID. Port reference inputs retain UN/LOCODE IDs, source URL, release, retrieval date and license. Operational ports are the 25 country gateway endpoints/hubs selected by the demand audit; the full 6,775-row verified coordinate-bearing reference catalog is retained in canonical `ports.json`.

`ServiceConnection` records are directed and may have parallel IDs. A service stores nautical-mile distance and method, modeled transit duration, periodic departure interval, minimum transfer, modeled USD/TEU cost, simulated capacity, cargo classes, source class and provenance. `OBSERVED_AIS_MOVEMENT` is never used as a service class. Corridors with mapped historical movement are labeled `MODELED_SERVICE_FROM_AIS`, with a separate movement reference.

Each synthetic `Shipment` stores a direct AlMahri supplier edge ID and exact company pair, gateway assumptions, cargo class/TEU/priority, release time, deadline and plan ID. `RoutePlan.ordered_legs` stores the service ID, directed endpoints, sequence, planned departure/arrival and modeled cost. Plans are initial itineraries only. Validation checks supplier identity, source provenance, port/service IDs, direction, route continuity, periodic departures, transfer times, cargo capacity and compatibility, hard deadlines and total cost.

`MODELED_COUNTRY_GATEWAY` is a port-level country proxy, not a physical facility. No facility location is inferred. The service graph and operational schedule/cost/capacity attributes are explicit synthetic model assumptions. See `config/maritime_network.json` and [service model](maritime_service_model.md).
