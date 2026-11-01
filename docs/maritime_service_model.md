# Maritime service model

`config/maritime_network.json` holds the frozen model parameters. The demand audit supplies country gateway endpoints; the operational graph includes those ports and the configured transshipment hubs only. Candidate corridors are sparse endpoint-to-regional-hub spokes and a fixed documented hub backbone. It is not a complete graph.

Each directed service has a stable ID, directed endpoints, source class, SeaRoute nautical-mile distance and method, transit time, periodic departure interval, minimum transfer time, modeled USD/TEU cost, simulated capacity and supported cargo class. Formulae:

- `transit_days = distance_nm / (24 * vessel_speed_knots) + port_handling_days`
- `cost_usd = fixed_service_cost_usd + distance_nm * cost_per_teu_usd_per_nm`
- departures occur every configured `departure_frequency_days`; onward services cannot depart before arrival plus minimum transfer time.

`MODELED_SERVICE_FROM_AIS` means a separately modeled service corridor whose directed endpoints also have an exact-name-mapped AIS movement reference. The historical movement itself remains separate evidence and is not represented as a schedule. All service availability, frequency, capacity, and cost values are synthetic assumptions. A service is enabled in strict generation only with explicit `--allow-modeled-services`.
