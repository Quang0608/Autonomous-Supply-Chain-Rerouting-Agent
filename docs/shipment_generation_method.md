# Shipment generation method

The fixed seed selects 500 distinct direct AlMahri supplier/customer rows, preferring edges linked within four upstream tiers to BMW, Mercedes-Benz, or Tesla. Each eligible edge generates at most two distinct synthetic demands, yielding 1,000 records. Each shipment carries a stable hash ID for its exact six-column supplier edge and the source CSV checksum. No product is inferred from industry.

Country fields resolve to deterministic UN/LOCODE gateway proxies; a port is not asserted to be a physical company facility. Cargo class is general container, TEU is seeded 1–4, release day is sampled over days 0–365, and priority is sampled from LOW/STANDARD/HIGH. The planner performs deterministic cost-first path search with periodic modeled departures and transfer times, rejects hard-deadline failures, and requires a valid directed itinerary. Deadlines are the feasible baseline arrival plus a seeded 7/14/30-day buffer. There are no recovery routes in this phase.

The output records selected-edge share, per-edge cap, distributions, route plans and checksums. Exact source edge identity, service references, leg continuity, schedule feasibility, capacity, delivery deadline and cost totals are validated. If the eligible service graph cannot produce exactly the requested shipment count, the command exits nonzero rather than returning a partial benchmark.
