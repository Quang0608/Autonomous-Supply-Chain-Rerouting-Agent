# Phase 3 temporal disruption simulation

## Audit and frozen baseline

The Phase 2 canonical JSON fields were inspected before implementation. `ports.json` identifies ports by `port_id`; services by `service_id`; shipments by `shipment_id`; plans by `route_plan_id`; plans contain ordered legs with `service_id`, directed port IDs, `planned_departure`, and `planned_arrival`. The day fields and planned-leg times are numeric offsets, not ISO timestamps. Shipment release/deadline are stored as both day offsets and aliases. The Neo4j importer uses `Port.id`, `ServiceLeg.id`, `Shipment.id`, `RoutePlan.id`, `PlannedLeg.id`, and `HAS_PLAN`, `HAS_LEG`, `USES_SERVICE`, `DEPARTS_FROM`, and `ARRIVES_AT` relationships. The importer stores leg times as `depart_day` and `arrive_day`.

Verified `research_1500` manifest counts: 1,500 shipments, 1,500 plans, 2,936 legs, 33 operational ports, and 122 directed services. Captured SHA-256 before edits:

| File | SHA-256 |
|---|---|
| `ports.json` | `d6c5eb8baf1499e322283771acc208ccba2a6a1eefdb7bdc4b85467179f713ed` |
| `services.json` | `e39e0e5ec162e469a96c379ba8b0b52fcd29ba41960ccbc7dc9518455a727bc0` |
| `shipments.json` | `5b22521748fa2ee68e38bcad5464e58f0e326d42b29e47a8b4f38a3864524e95` |
| `route_plans.json` | `d2e2fef7184ab0b957369ff9c3dd442e6e052a0131d5901ad1400234564740cf` |

All `data/builds/` files were hashed before edits, including `research_1000`, both repeat builds, the pilot, and seed 43. Phase 3 reads only `research_1500` canonical inputs; it writes scenario outputs separately under the ignored `data/simulations/phase3/` tree. Recheck the four canonical hashes after implementation using `Get-FileHash -Algorithm SHA256 data/builds/research_1500/*.json` (PowerShell wildcard syntax is supported).

## Schedule and event semantics

The source records do not provide calendar schedules. The simulator derives calendar timestamps in memory and in scenario evidence from the fixed UTC epoch `2025-01-01T00:00:00Z`; numeric day `d` maps to epoch plus `d * 24 hours`. This preserves all frozen records and makes examples deterministic while clearly labeling the schedule as derived. ISO event timestamps must carry an explicit timezone and are normalized to UTC. All event intervals use half-open `[start, end)` bounds.

- `PORT_CLOSURE` targets an existing `port_id` and selected `ARRIVAL`, `DEPARTURE`, and/or `TRANSSHIPMENT` operations. Arrival and departure are checked at their planned instants. Transfer occupancy is the interval from the inbound planned arrival to the next planned departure at that transfer port.
- `SERVICE_SUSPENSION` checks departures in the event interval. A traversal that began before the event is not considered suspended by this policy.
- `SERVICE_DELAY` applies its positive `delay_hours` to a leg whose planned departure is in the event interval. Each downstream departure remains fixed. The delayed arrival is tested against that departure and its minimum transfer; feasible slack absorbs the inbound delay, while an infeasible connection is `UNRESOLVED_CONNECTION` and stops ETA resolution.
- Arrival and transfer closures are evaluated at the dynamically determined arrival time. A closure or suspension blocks a departure; simultaneous delay events remain in the evidence with `effect_applied: false`. Other event causes are preserved and shipments are counted once.

The event validator enforces schema version 1.0, unique event IDs, existing port/service targets, supported event types, timezone-aware timestamps, positive intervals, valid operations, and positive nonzero delays. The machine-readable schema is [`phase3_disruption_schema.json`](phase3_disruption_schema.json).

## No-recovery policy and output contract

This is a passive baseline, not a route optimizer. The simulator preserves baseline plans and does not introduce services, ports, capacity, or rebooking. A detected reachable port closure or service suspension is `BLOCKED` because the model does not represent an operational wait/rebooking policy. An infeasible delayed transfer is `UNRESOLVED_CONNECTION`. A delay that remains feasible is `DELAYED` unless the resolved final ETA exceeds the hard delivery deadline, in which case it is `DEADLINE_MISSED`. Unaffected shipments retain their canonical plan and ETA. Missing facts are not converted into precise ETAs.

Each run writes `scenario_manifest.json`, `event_impacts.json`, `shipment_impacts.json`, `shipment_impacts.csv`, `no_recovery_outcomes.json`, `no_recovery_outcomes.csv`, and `summary.json`. Deterministic files are byte-stable for identical inputs; run UTC is isolated to `scenario_manifest.json`. The manifest records dataset manifest and scenario hashes, counts, software version, and schedule semantics. Summary counts include affected/unaffected, direct/indirect, disrupted legs, status percentages, event types, and earliest/latest impacted operation.

## Engineering examples

`examples/phase3/` contains six small scenarios using actual IDs from the current seed-42 canonical data: affected departure closure, zero-impact port closure, directed service suspension, finite service delay, overlapping closure/suspension, and a transfer-occupancy closure whose downstream handling/recovery outcome is not modeled. These are deterministic software fixtures only. They do not adapt the AlMahri cases and do not constitute independent ground truth.

The synthetic unit fixture under `tests/fixtures/phase3/minimal/` uses TEST-prefixed entities and covers interval boundaries, two-leg delay propagation, unresolved transfers, closure precedence, no-impact events, bad inputs, and byte-stable outputs.

## Neo4j integration

No disruption data is imported into Neo4j in this phase. The current canonical algorithm is file-backed and does not require a live database. For manual read-only inspection against a Phase 2 import, convert UTC timestamps to day offsets from the epoch and use the existing node/relationship model. Example departure closure query:

```cypher
MATCH (s:Shipment)-[:HAS_PLAN]->(p:RoutePlan)-[:HAS_LEG]->(l:PlannedLeg)-[:USES_SERVICE]->(svc:ServiceLeg)-[:DEPARTS_FROM]->(port:Port)
WHERE port.id = $port_id AND l.depart_day >= $start_day AND l.depart_day < $end_day
RETURN s.id AS shipment_id, p.id AS plan_id, l.id AS leg_id, svc.id AS service_id,
       port.id AS port_id, l.depart_day AS departure_day
ORDER BY shipment_id, leg_id;
```

The query is read-only and uses the actual Phase 2 schema. Neo4j persistence/idempotency was not exercised because this implementation does not persist Phase 3 nodes.

## Verification record

- Branch: `phase3-temporal-disruptions`; baseline commit: `ce36352`.
- Phase 3 implementation commit: `039e0e7ab5d65b9c096b4cc770790fb63e0fdb49`.
- `python -m unittest discover -s tests -v`: all 23 tests passed (16 existing Phase 2/pilot tests and 7 Phase 3 tests).
- All six example scenarios passed `validate-scenario` against `research_1500` IDs and ran against all 1,500 shipments. Impacts: affected departure closure 1; zero-impact closure 0; service suspension 1; service delay 1 (one shipment with an unresolved downstream transfer); overlapping closure/suspension 1; transfer occupancy closure 3. In each run affected plus unaffected equals 1,500.
- The Phase 3 unit suite checks exact impact IDs/reason codes, interval boundaries, no-impact and zero-delay behavior, cascade outcomes, closure precedence, invalid inputs, stable output bytes, and that file-backed analysis leaves the input fixture unchanged.
- `git diff --check` passed. Hashes for all files across `data/builds/` match the pre-edit capture, including all four canonical `research_1500` records and the frozen `research_1000` baseline. The report's table lists the combined build's canonical record hashes.
- The documented dependency `searoute==1.6.0` was missing in the environment and was installed to run the existing expansion tests. No project dependency file or Phase 2 source was changed.
- Neo4j persistence was not implemented or run; Phase 3 analysis is file-backed. A read-only Cypher inspection query is documented above.
- Remote: `https://github.com/Quang0608/Autonomous-Supply-Chain-Rerouting-Agent.git` (no credentials embedded). Push of `phase3-temporal-disruptions` to `origin` succeeded and the branch tracks `origin/phase3-temporal-disruptions`.
- Suggested pull request title: `Implement Phase 3 temporal maritime disruption simulation`.
- Suggested pull request summary: Add validated time-window disruption scenarios, deterministic operation-level impact evidence, no-recovery outcomes, canonical-data examples, and boundary/regression tests while preserving all Phase 2 builds.

## Phase 4 handoff

Phase 4 can consume the validated event schema and impact evidence as optimizer inputs. Before making calendar-specific operational claims, replace or calibrate the fixed-epoch derived schedule layer with a licensed, sufficiently detailed schedule source. Keep synthetic engineering cases separate from the later independent evaluation set.
