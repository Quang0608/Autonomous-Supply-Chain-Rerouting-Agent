# Phase 5.2b — First Three Benchmark Scenarios

## Status and scope

This is a preliminary construction and execution report for SC-002, SC-007, and SC-012 only. It records Phase 3/4 observations, not independently verified ground truth. All three cases remain **UNVERIFIED** for final benchmark scoring. Scenario artifacts separate the simulated notice for future agent input from its structured reference event; the reference JSON must be withheld from agents during later evaluation.

The working tree was on `phase5-evaluation-benchmark` at commit `9bbecf82a87158568031c7e9554ac981542a8593` (`data reconnaissance and candidate identification`, 2026-11-15). The schedule uses the implementation's simulated UTC epoch, `2025-01-01T00:00:00Z`; the notices explicitly identify themselves as simulated and not authentic advisories.

## A. Scenario construction summary

| Scenario / candidate | Notice and structured event | Target and interval | Selection rationale |
|---|---|---|---|
| SC-002 / C-002-A | `examples/phase5/SC-002/notice.txt`; `examples/phase5/SC-002/scenario.json` | Port `SGSIN`; `2025-09-26T11:00:00Z` to `2025-09-26T12:00:00Z`; `ARRIVAL` only | The positive one-hour interval contains the canonical planned arrival of `SHIP-000001` at `2025-09-26T11:15:47.52Z`. It describes an arrival restriction and makes no claim about position, diversion, waiting, or cargo handling. |
| SC-007 / C-007-A | `examples/phase5/SC-007/notice.txt`; `examples/phase5/SC-007/scenario.json` | Service `SVC-35a7482f2af1d0`; departure window `2025-10-01T00:00:00Z` to `2025-10-01T01:00:00Z`; `SERVICE_DELAY`, 1 hour | The half-open window contains the candidate's planned departure at `2025-10-01T00:00:00Z`. The one-hour delay is less than the independently calculated connection buffer for the next leg. |
| SC-012 / C-012-A | `examples/phase5/SC-012/notice.txt`; `examples/phase5/SC-012/scenario.json` | Port `ARBUE`; `2025-01-01T00:00:00Z` to `2025-01-02T00:00:00Z`; `ARRIVAL`, `DEPARTURE`, and `TRANSSHIPMENT` | A fresh scan of all 2,936 planned legs found no arrival/departure instant or transfer interval at ARBUE overlapping this one-day window. ARBUE is present in canonical `ports.json` (Buenos Aires) and is a modeled service endpoint. |

SC-002's canonical planned arrival is stored as a fractional numeric day, so the implementation converts it to `.52Z` seconds precision. This is within the notice's stated 11:00–12:00 UTC interval. For SC-007, the transfer from the inbound arrival (`2025-10-21T09:42:54.72Z`) to the next planned departure (`2025-10-22T00:00:00Z`) is 14h 17m 5.28s. Subtracting the recorded 12-hour minimum transfer gives 2h 17m 5.28s (about 2.2848 hours) of slack; the selected one-hour delay is below that buffer by about 1.2848 hours.

## B. Validation

Both existing CLI validation interfaces accepted all three fixtures:

- `scripts/phase3_simulation.py validate-scenario` passed SC-002, SC-007, and SC-012, including target existence checks.
- `scripts/phase4_recovery.py validate-scenario` passed all three as well.
- Each event has a unique ID, supported type, timezone-aware timestamps, and a positive-duration interval. All notice event fields agree with the matching structured JSON. SC-007 explicitly states the same target service, one-hour delay, and departure applicability window as its JSON.
- The fixture fields satisfy the applicable conditions in `docs/phase3_disruption_schema.json` by inspection. A separate JSON Schema engine was not available in this Python environment (`jsonschema` is not installed); the existing Phase 3 and Phase 4 semantic validators were run directly.

The documented schema and implementation differ in several defaults/bounds: the schema requires `affected_operations` for a closure and `semantics` for a service event, while `validate_scenario` defaults those fields; the schema permits `delay_hours: 0` and the implementation also accepts zero, although Phase 3 records an impact only for a delay greater than zero. The implementation enforces timezone awareness and `start < end`; those conditions are not fully captured by the schema's declared fields alone. These fixtures use explicit scope/semantics, positive delays, timezone-aware timestamps, and positive intervals, avoiding those ambiguities.

## C. Preliminary execution observations

The existing CLI tools were run against `data/builds/research_1500`; Phase 3 output is under `data/simulations/phase5/phase5_2b/<SC-ID>/phase3/` and Phase 4 output under the corresponding `phase4/` directory. The generated run files are local and ignored by Git.

### SC-002 — arrival closure

- **Phase 3:** 1 of 1,500 shipments affected; direct 1, indirect 0; 1 disrupted leg. The complete observed cohort is `SHIP-000001` only. Cause: `PORT_CLOSURE_ARRIVAL_OVERLAP`, event `SC-002-E1`, leg `PLAN-SHIP-000001:L1`, operation `ARRIVAL`, conflict time `2025-09-26T11:15:47.52Z`. No-recovery status is `BLOCKED` (`NO_RECOVERY_POLICY_BLOCKED_OPERATION`); baseline ETA is unknown/null for this blocked result.
- **Phase 4:** `OPERATOR_INTERVENTION_REQUIRED` 1, `UNCHANGED` 1,499; all other statuses 0. The affected result has `reason_code: ARRIVAL_CLOSURE_POSITION_UNRESOLVED`, no recovery plan, and asks for actual position/movement state and carrier-authorized diversion options. It does not invent a vessel position or diversion.
- **Observation:** The intended intervention behavior was observed. The Phase 3/4 result is still only tool evidence, not an independent label.

### SC-007 — absorbed service delay

- **Phase 3:** 1 of 1,500 shipments affected; direct 1, indirect 1; 2 disrupted legs. The complete observed cohort is `SHIP-000001` only. Its direct cause is `SERVICE_DELAY_DEPARTURE_OVERLAP` on `PLAN-SHIP-000001:L2`. Phase 3 also reports `RECOVERED_CONNECTION` on L3 with 1.0 propagated delay hour. The fixed connection remains feasible; the no-recovery status is `DELAYED` (`MODELED_DELAY_PROPAGATED`), and the final ETA remains `2025-10-24T08:45:44.64Z`.
- **Phase 4:** `NO_REROUTE_REQUIRED` 1, `UNCHANGED` 1,499; all other statuses 0. The affected result's reason code is `FIXED_CONNECTION_RECOVERED`; the recovered ETA equals baseline and it emits no replacement suffix/recovery plan.
- **Cohort check:** A full scan of all canonical planned legs for target service departures within `[2025-10-01T00:00:00Z, 2025-10-01T01:00:00Z)` found one qualifying departure, belonging to `SHIP-000001`. No other shipment using the service was in the selected event window.
- **Observation:** The intended no-reroute behavior was observed. Phase 3 marks both the delayed inbound leg and the downstream connection as impacts even though the one-hour delay fits within connection slack; this is recorded as connection-handling evidence, not a discrepancy in the expected no-reroute decision.

### SC-012 — no-impact port closure

- **Phase 3:** 0 affected; 1,500 unaffected; 0 disrupted legs. The observed affected-shipment set is empty.
- **Phase 4:** `UNCHANGED` 1,500; every other status 0. No recovery plans were fabricated or emitted.
- **Independent pre-run operation scan:** 0 arrival instants, departure instants, or transfer occupancy intervals at ARBUE overlapped the half-open interval `[2025-01-01T00:00:00Z, 2025-01-02T00:00:00Z)`.
- **Observation:** The intended no-impact behavior was observed in this execution. The scan and tool output do not make this a final verified ground-truth case.

## D. Input provenance

Frozen source: `data/builds/research_1500/dataset_manifest.json`, seed 42, generator 2.1.0, validation `passed`; 1,500 shipments, 1,500 route plans, 2,936 planned legs, 122 services, and 33 modeled operational ports. Manifest SHA-256: `b2323fc9c0b3d251bb234346157770e66746eaeaed4c51063a3cd59b9759ff46`.

| Canonical input | SHA-256 before and after execution | Match to manifest |
|---|---|---|
| `ports.json` | `d6c5eb8baf1499e322283771acc208ccba2a6a1eefdb7bdc4b85467179f713ed` | Yes |
| `services.json` | `e39e0e5ec162e469a96c379ba8b0b52fcd29ba41960ccbc7dc9518455a727bc0` | Yes |
| `shipments.json` | `5b22521748fa2ee68e38bcad5464e58f0e326d42b29e47a8b4f38a3864524e95` | Yes |
| `route_plans.json` | `d2e2fef7184ab0b957369ff9c3dd442e6e052a0131d5901ad1400234564740cf` | Yes |

Recovery policy: `config/recovery_policy.json`, policy ID `modeled-periodic-v1`, SHA-256 `93e8627763eb40e6872e437fa5c56ffd1b7e41607bbb52bc40c1e19757040ef0`. Phase 3 version is `phase3-temporal-1.0.0`; Phase 4 version is `phase4-recovery-1.1.0`.

| Artifact | SHA-256 |
|---|---|
| SC-002 notice | `6c08ff2d5eb3f7e15d762ac793fb09e8da424b48f74e4a33ec364fdbd4973a80` |
| SC-002 scenario JSON | `72676b7a62648e4bdb721f04d0f256944f43e9d6fa8186397023186bfe9310f0` |
| SC-007 notice | `9768ddf2b7cb3a488a6d9b32ca9f6e89e61d185332d83990e55bbfba5f9bd0cf` |
| SC-007 scenario JSON | `f31cd628ab219ea42c5225e2b1f0e34ab0410792ad89f3bc4752f3f7b3fcf222` |
| SC-012 notice | `8d3c6a71864cda47f031094b2027c0c09daf8ca0c07587be0ab69c57ba0a27b9` |
| SC-012 scenario JSON | `8edefa490ff1bc9c75b47886d3518e945469cdc20204397abba2016ee92e949f` |

## E. Remaining verification for Phase 5.2c

- Independently reconcile Phase 3 impact membership, per-leg causes, operation times, and propagated connection behavior against a separately implemented calculation for each case.
- Independently verify recovery labels and the intervention boundary for SC-002. Confirm modeled feasibility assumptions independently; do not treat Phase 4 output as the label source. SC-007's non-reroute decision and SC-012's full no-impact set also need independent evidence.
- Decide whether the observed SC-007 distinction between a propagated one-hour delay and `RECOVERED_CONNECTION` is represented clearly enough for the later scoring rubric.
- Freeze and review the notices/reference events and their hashes as separate agent-input and evaluator-only artifacts. Preserve the structured JSON as hidden from evaluated agents.
- Resolve any schema/implementation contract documentation mismatch as a reporting/protocol issue before scoring; this milestone did not change production semantics or policies.

No final ground-truth labels were created. The remaining 12 scenario IDs were not implemented, no agents or benchmark runner were added, and no 45-run evaluation was executed.
