# Phase 4 deterministic constrained recovery

**Follow-up status contract (output schema 1.1):** Phase 4 recovery rows use `recovery_status`. `INSUFFICIENT_DATA` is deprecated and is not emitted. Cases where an essential operational fact or supported policy is missing use `OPERATOR_INTERVENTION_REQUIRED`, with a stable `reason_code`, shipment-specific `reason`, non-empty `missing_information`, and `recovery_plan: null`. Other failure statuses retain their existing meanings.

Date: 2026-11-06. Branch: `phase4-deterministic-recovery`. Base: `9e513215e78129d09ac5797a04677dd5078f4cd8` (`origin/main`, containing Phase 3 P0 fix `f815e59a1643ca2909792df1b9eabbc28b891e25`). Dataset manifest: `data/builds/research_1500/dataset_manifest.json`, seed 42, validation passed. The 1,500 shipments, 1,500 plans, 2,936 legs, 33 operational ports, and 122 directed services were observed in the frozen build.

## Input audit and field mapping

| Need | Canonical field | Use |
|---|---|---|
| Shipment identity and endpoints | `shipment_id`, `origin_port_id`, `destination_port_id`, `route_plan_id` | Cohort reconciliation and path endpoints |
| Release and deadline | `release_time`/`release_day`, `delivery_deadline` | Earliest origin readiness and hard latest arrival |
| Cargo and size | `cargo_class`, `cargo_teu` | Individual service compatibility |
| Existing plan | `ordered_legs` with service/port IDs, `planned_departure`, `planned_arrival`, `min_transfer_hours`, `modeled_cost_usd` | Immutable executed prefix and baseline comparison |
| Service direction | `origin_port_id`, `destination_port_id` | Directed graph, no reverse edge inference |
| Modeled departure | `departure_frequency_days` | Periodic departure recurrence anchored to simulation day zero |
| Modeled duration/cost | `transit_days`, `cost_per_teu_usd` | Arrival and cost by shipment TEU |
| Modeled cargo/capacity | `cargo_classes`, `capacity_teu` | Individual shipment checks only |
| Phase 3 evidence | `shipment_impacts`, `no_recovery_outcomes`, cause IDs, leg IDs, conflict times | Recovery state and No Recovery comparison |

The Phase 2 planner's `next_departure` uses integer multiples of service frequency from day zero. Phase 4 uses that same recurrence, recorded as policy `modeled-periodic-v1` in `config/recovery_policy.json`. The fixed UTC epoch remains `2025-01-01T00:00:00Z`. Values describe a simulated network; service presence, schedule availability, cost, and capacity are not verified commercial facts. Historical AIS movement references do not prove a bookable sailing.

Supported constraints: directed continuity, release/readiness, modeled periodic departures, minimum transfer, positive transit, event windows at actual operations, hard deadline, cargo class, individual TEU capacity, no cycles, bounded hops and horizon. Missing essential service frequency, duration, cost, cargo class, or capacity produces `OPERATOR_INTERVENTION_REQUIRED` with reason code `ESSENTIAL_RECOVERY_DATA_MISSING`. Unsupported: residual booked capacity, shared allocation across shipments, vessel/terminal capabilities, real handling slots, inland transport, geographic sea-lane/chokepoint exposure, and real market prices. These are not claimed as enforced.

## Recovery state, algorithm, and objective

The solver calls Phase 3 `analyze` and consumes its validated scenario, per-shipment causes, and No Recovery outcome. Unaffected shipments remain `UNCHANGED`. A delay absorbed by Phase 3 connection slack remains `NO_REROUTE_REQUIRED`. For a missed fixed connection, the last reachable port is the delayed inbound destination; the actual inbound arrival and required transfer determine readiness, and the inbound leg stays in the executed prefix. For a blocked future departure, the decision is made at that departure port no earlier than its planned departure or feasible inbound arrival. Arrival closures with unresolved actual position use `ARRIVAL_CLOSURE_POSITION_UNRESOLVED`; affected transfers without a safe handling/holding/departure policy use `TRANSSHIPMENT_HANDLING_POLICY_UNAVAILABLE`. Both produce `OPERATOR_INTERVENTION_REQUIRED` and no recovery plan. Missing required recovery inputs use `ESSENTIAL_RECOVERY_DATA_MISSING`. Ordinary route absence, deadline infeasibility, and search exhaustion retain `NO_FEASIBLE_ROUTE`, `DEADLINE_INFEASIBLE`, and `SEARCH_LIMIT_REACHED`.

Search enumerates only existing directed services, at most three modeled departures per service from each state. It is bounded by four replacement hops, 180 days, 20,000 expansions, 2,000 complete candidates, and 1,000 labels per port/hop. It prunes a new label only when an earlier or equal, cheaper or equal label at the same port has a subset of visited ports. Queue and service order are deterministic. Budget exhaustion yields `SEARCH_LIMIT_REACHED`, even when a diagnostic valid candidate exists.

The objective is hard operational and deadline feasibility, then minimum additional modeled total cost against the original plan, then earliest ETA, fewer replacement legs, and lexicographic service-ID order. Late alternatives are diagnostics under `DEADLINE_INFEASIBLE`; they are never called recovered. `NO_FEASIBLE_ROUTE` means none within this modeled graph, departure limit, and horizon. An affected shipment is never counted twice.

Each complete candidate goes through `recovery_validation.py`, which independently checks prefix identity, service direction, schedule recurrence, chronology, transit time including service delays, event windows, cargo, individual capacity, modeled cost, cycles, destination, horizon, and deadline. Every selected `RECOVERED` candidate has all PASS records. Failed records and evidence remain in `constraint_validation.json`.

Closure and suspension block a candidate departure. Service delay applies only if that departure remains available. A delayed candidate arrival is checked against arrival closures; transfer occupancy uses actual inbound arrival and the proposed next departure. Phase 3 remains the authoritative source for original-plan impacts and No Recovery statuses. Unknown No Recovery ETA for blocked or unresolved cases is retained as null; no avoided-delay claim is made from it.

## Operator-intervention follow-up

Follow-up branch: `phase4-operator-intervention-recovery`, based on updated `origin/main` at `b9db10d`. The result schema and solver version are `1.1` and `phase4-recovery-1.1.0`; the recovery policy schema remains `1.0`.

The `transshipment_closure_unresolved` integration scenario affects three canonical records: `SHIP-000001`, `SHIP-000997`, and `SHIP-EXP-000098`. Each Phase 3 cause identifies the affected first leg and `event_close_sgsin_transfer` at SGSIN. Their planned operations place them at or waiting through the modeled transshipment closure, but the records do not establish actual execution/cargo state or authorize safe waiting, unloading, transfer, or departure. All three therefore require operator intervention. No alternate vessel movement or recovery leg is emitted. The affected count remains three and the Phase 3 outcomes remain `BLOCKED`.

Each intervention result includes `recovery_status`, a stable reason code, a shipment-specific explanation, a non-empty missing-information list, `recovery_plan: null`, and affected leg/event traceability. Result CSVs and comparison outputs use `recovery_status`; the prior `INSUFFICIENT_DATA` label is deprecated and retained only in historical instructions.

## Verification

`python -m unittest discover -s tests -v`: **46 passed** (existing Phase 2 and Phase 3 tests plus Phase 4 coverage). The Phase 4 fixture covers unchanged plans, suspension with a validated alternate, missed-connection position and immutable prefix, arrival closure requiring intervention, half-open closure boundaries, cost versus deadline ranking, late-only alternatives, cargo restrictions, delay-shifted candidate arrival closures, overlapping events, a cyclic graph, missing capacity requiring intervention, search cutoff, no-route classification, canonical three-shipment transshipment intervention, a deliberately invalid candidate rejected by the independent validator, and byte-stable repeated outputs. All six Phase 3 examples were rerun and their event impacts, shipment impacts, no-recovery results, and summaries matched the frozen Phase 3 P0 outputs. Phase 4 outputs for all six scenarios matched byte-for-byte across repeated runs. Phase 2 canonical dataset hashes remain identical to the recorded hashes above. The three selected canonical recoveries passed independent validation; the three operator-intervention results contain no recovery itinerary.

Synthetic worked example: `SHIP-1` originally uses `S-AB,S-BC` for modeled cost 2 and ETA `2025-01-04T00:00:00Z`. Suspension `suspend-ab` blocks `S-AB` through the modeled deadline window. The solver selects `S-AD,S-DC`, modeled cost 4, ETA `2025-01-04T00:00:00Z`, deadline `2025-01-07T00:00:00Z`, additional modeled cost 2. Equal-cost `S-AE,S-EC` loses the lexicographic tie. The independent checks all pass for the selected path.

### Canonical Phase 4 integration

Each scenario reconciled exactly 1,500 unique shipment IDs:

| Phase 3 example | Affected | Attempted | Recovered | Unchanged | No reroute | Operator intervention required | Validator pass/fail candidates |
|---|---:|---:|---:|---:|---:|---:|---:|
| overlapping_disruptions | 1 | 1 | 1 | 1,499 | 0 | 0 | 1/1 |
| port_closure_affected | 1 | 1 | 1 | 1,499 | 0 | 0 | 1/1 |
| port_closure_no_impact | 0 | 0 | 0 | 1,500 | 0 | 0 | 0/0 |
| service_delay | 1 | 0 | 0 | 1,499 | 1 | 0 | 0/0 |
| service_suspension | 1 | 1 | 1 | 1,499 | 0 | 0 | 1/1 |
| transshipment_closure_unresolved | 3 | 0 | 0 | 1,497 | 0 | 3 | 0/0 |

Across these examples: `NO_FEASIBLE_ROUTE`, `DEADLINE_INFEASIBLE`, and `SEARCH_LIMIT_REACHED` are zero; the synthetic suite exercises route absence and search cutoff. The three selected canonical recoveries passed independent validation. Candidate failures in those runs are late alternatives, not selected recommendations. Six separate CLI measurements were 585–682 ms (median about 606 ms, nearest-rank p95 about 682 ms), including Python startup, file reads, search, and output writes. Wall-clock measurements are excluded from deterministic artifacts.

Repeated synthetic outputs were byte-identical, including the manifest; Phase 4 does not write a run timestamp. Two complete six-scenario canonical runs produced 48 files each, with zero SHA-256 differences.

### Frozen canonical hashes

All four input hashes matched the Phase 3 P0 report before work and after tests and six example runs:

| File | Before and after SHA-256 |
|---|---|
| `ports.json` | `d6c5eb8baf1499e322283771acc208ccba2a6a1eefdb7bdc4b85467179f713ed` |
| `services.json` | `e39e0e5ec162e469a96c379ba8b0b52fcd29ba41960ccbc7dc9518455a727bc0` |
| `shipments.json` | `5b22521748fa2ee68e38bcad5464e58f0e326d42b29e47a8b4f38a3864524e95` |
| `route_plans.json` | `d2e2fef7184ab0b957369ff9c3dd442e6e052a0131d5901ad1400234564740cf` |

## Files and limits

Added: `src/maritime/phase4.py`, `src/maritime/recovery_validation.py`, `scripts/phase4_recovery.py`, `config/recovery_policy.json`, `tests/test_phase4.py`, `tests/fixtures/phase4/minimal/`, `requirements.txt`, and this report. Updated: `README.md`. No canonical files, Neo4j nodes, AIS raw material, or AlMahri source data were changed. Phase 4 uses only existing modeled service IDs; it adds no geographic chokepoints, LLM, dashboard, or independent research ground truth.

Future Phase 5 evaluation should use independently defined scenarios and licensed operational references. A later LLM Baseline C should call this same `recover` and `checks_for_route` interface and route universe, then compare its decisions with Baseline B.

Feature commit: `45b3ab156dd8959fe450d87928fd9b9f5eff0a77` (`feat: implement Phase 4 deterministic constrained shipment recovery`). Push to `origin/phase4-deterministic-recovery` succeeded; the branch tracks the remote. This report update records that push after it completed.
