# Phase 3 P0 correctness verification

Date: 2026-11-06

Branch: `phase3-temporal-disruptions`

Dataset: frozen `data/builds/research_1500`

## Scope and code paths

The audit covered the existing temporal simulator only. No Phase 4, LLM, geographic chokepoints, or dataset generation work was performed.

- `src/maritime/phase3.py::validate_scenario`: event types, timezone normalization, target IDs, half-open intervals, and delay values.
- `src/maritime/phase3.py::analyze`: direct event matching against planned departures, chronological arrival/transfer checks, unresolved connection handling, event evidence, final ETA and deadline status, affected-shipment counting, and summary counts.
- `src/maritime/phase3.py::write_outputs`: deterministic output files and run timestamp isolation.
- `scripts/phase3_simulation.py::main`: canonical dataset/scenario loading and simulation entrypoint.
- `tests/test_phase3.py` and `tests/fixtures/phase3/minimal/`: existing Phase 3 boundary fixture and the added synthetic regression cases.
- All six scenario files under `examples/phase3/`.

## Bugs found and minimal reproductions

### Upstream delay was always added to the final ETA

The previous implementation accumulated an inbound service delay across every later leg. In the minimal fixture, leg 1 arrives at day 12, leg 2 departs at day 14, and leg 2 requires 12 transfer hours. A one-hour delay produces arrival at day 12 plus one hour, still before the fixed departure minus the transfer requirement. The old result added one hour to the final ETA anyway. The corrected result records a `RECOVERED_CONNECTION`, preserves the planned leg 2 departure, and keeps the final ETA at `2025-01-17T00:00:00Z`.

### ETA and deadline were calculated from the sum of events, not the resolved itinerary

With a one-hour delay on leg 1 and a two-hour delay on leg 2, the previous ETA calculation summed both delays. The actual leg 1 delay fits within connection slack; only leg 2's delay affects the final ETA. The corrected ETA is `2025-01-17T02:00:00Z`. A synthetic deadline at `2025-01-17T01:12:00Z` correctly produces `DEADLINE_MISSED` from that resolved ETA.

### Dynamic operation times were not checked against closures

In the minimal fixture, leg 1's planned arrival at TEST-B is `2025-01-13T00:00:00Z`. A two-hour service delay moves the actual arrival to `2025-01-13T02:00:00Z`. A TEST-B arrival closure in `[01:00, 03:00)` was missed when only planned arrival time was checked. The corrected result emits the closure event at the shifted timestamp and marks the shipment `BLOCKED`.

### Simultaneous event evidence was discarded

Previously, when a departure closure and service delay hit the same leg, the delay event was removed from the cause list. The corrected output preserves both event IDs and marks the delay `effect_applied: false` with `precedence: DEPARTURE_BLOCKED`. The synthetic overlap case also combines two closures, a suspension, and a delay on one departure; it produces one affected shipment with all four IDs.

## Fixes and resulting semantics

- Affected departures may be delayed by their explicit service-delay policy. All downstream departures remain at their planned times.
- Arrivals are resolved in leg order. Each connection is feasible when actual inbound arrival plus the next leg's minimum transfer time is less than or equal to the planned next departure.
- Feasible slack absorbs the inbound delay. The evidence records the recovered connection, and the delay does not leak into subsequent ETA calculations.
- An infeasible connection emits `UNRESOLVED_CONNECTION`, retains the causal service-delay event ID and actual arrival timestamp, and stops arrival/ETA resolution beyond that connection. No later sailing is invented.
- Reachable arrival and transfer closures are evaluated at actual arrival times. Transfer occupancy is checked only when its start precedes the fixed next departure.
- Simultaneous closure/suspension precedence suppresses a service delay's effect while preserving that delay event in the evidence.
- Final ETA is derived from the last temporally resolved leg. Deadline comparison uses this ETA. Blocked or unresolved outcomes have no asserted final ETA.
- Event causes are de-duplicated by leg, event ID, and operation. A shipment remains one row in impacts and is counted once regardless of its event count.

## Synthetic regression cases

`python -m unittest discover -s tests -v` passed all 28 tests, including the existing Phase 2/pilot tests and Phase 3 tests for:

- [start,end) departure and arrival boundaries;
- feasible inbound delay, exact recovered ETA, and infeasible transfer timestamp;
- three-leg itinerary stopping at the first unresolved connection;
- independent service delays on two legs, exact direct leg IDs, event IDs, final ETA, and deadline result;
- delay-shifted arrival entering a closure interval at an exact timestamp;
- overlapping closures, service suspension, and service delay on one departure with all event IDs;
- closures on separate legs, one shipment row, and exact impacted leg IDs;
- no-impact events, invalid input, and repeat-output byte determinism.

Repeat-output verification compares every deterministic JSON/CSV output byte-for-byte; only the run manifest contains its intentionally variable run timestamp.

## Canonical Phase 2 data integrity

The four canonical input files match the pre-audit hashes recorded in `docs/phase3_temporal_disruption_report.md`:

| File | SHA-256 before | SHA-256 after | Result |
|---|---|---|---|
| `ports.json` | `d6c5eb8baf1499e322283771acc208ccba2a6a1eefdb7bdc4b85467179f713ed` | `d6c5eb8baf1499e322283771acc208ccba2a6a1eefdb7bdc4b85467179f713ed` | unchanged |
| `services.json` | `e39e0e5ec162e469a96c379ba8b0b52fcd29ba41960ccbc7dc9518455a727bc0` | `e39e0e5ec162e469a96c379ba8b0b52fcd29ba41960ccbc7dc9518455a727bc0` | unchanged |
| `shipments.json` | `5b22521748fa2ee68e38bcad5464e58f0e326d42b29e47a8b4f38a3864524e95` | `5b22521748fa2ee68e38bcad5464e58f0e326d42b29e47a8b4f38a3864524e95` | unchanged |
| `route_plans.json` | `d2e2fef7184ab0b957369ff9c3dd442e6e052a0131d5901ad1400234564740cf` | `d2e2fef7184ab0b957369ff9c3dd442e6e052a0131d5901ad1400234564740cf` | unchanged |

## Example scenarios

All six examples were run through `scripts/phase3_simulation.py simulate-no-recovery` against `research_1500`. Each output accounted for all 1,500 shipments exactly once.

| Scenario | Affected | Status counts of note |
|---|---:|---|
| `overlapping_disruptions` | 1 | BLOCKED 1 |
| `port_closure_affected` | 1 | BLOCKED 1 |
| `port_closure_no_impact` | 0 | UNAFFECTED 1,500 |
| `service_delay` | 1 | DELAYED 1; recovered connection |
| `service_suspension` | 1 | BLOCKED 1 |
| `transshipment_closure_unresolved` | 3 | BLOCKED 3 |

## Git record

- Fix commit: `PENDING`
- Push: `PENDING`

P0 status is considered passed only after the full unittest suite, all six example runs, canonical hashes, and deterministic-output checks succeed.
