# Phase 5.2c — Independent Ground-Truth Verification (First Three Scenarios)

**Verification date:** 2026-11-15  
**Dataset:** frozen `research_1500`, seed 42, manifest validation passed  
**Verification status:** student-verified against the modeled dataset and stated rules; no maritime expert review is claimed.

## Workflow and separation

The independent verifier is [`evaluation/verify_first_batch.py`](../evaluation/verify_first_batch.py), version `phase5-independent-first-batch-1.0.0`. It reads raw Phase 2 shipments, route plans, services, ports, the scenario reference JSON, and recovery policy. It does not import Phase 3, Phase 4, or the recovery validator to calculate expected outcomes. It reconstructs planned timestamps from the UTC epoch `2025-01-01T00:00:00Z` using decimal schedule offsets and microsecond arithmetic, and applies half-open intervals `[start_time, end_time)`.

Run the independent label generator from the repository root with a fixed date:

```powershell
python evaluation/verify_first_batch.py generate --verification-date 2026-11-15
```

`generate` reads only the frozen data, policy, notices, and scenario references. It writes only `evaluation/ground_truth/`; it does not read Phase 3/4 run outputs. Ground-truth JSON contains the hidden reference event, independent labels, calculations, evidence, and provenance only.

After label generation, run the separate corroboration command:

```powershell
python evaluation/verify_first_batch.py compare
```

`compare` reads the ground-truth labels and saved `data/simulations/phase5/phase5_2b/` outputs. It writes only `evaluation/comparisons/`. Each comparison records the reference file SHA-256, observed output hashes, membership agreement, complete Phase 4 status agreement against independently derived shipment decisions, and relevant reasons, missing information, and recovery plan data. It records mismatches and exits unsuccessfully if any are found. It checks reference hashes before and after comparison and never writes ground-truth files. Comparison artifacts contain no wall-clock timestamps.

## Independent calculations and outcomes

### SC-002 — SGSIN arrival closure

- Scanned all 1,500 joined plans and 2,936 legs; enumerated **619** planned arrivals at SGSIN.
- The interval `[2025-09-26T11:00:00Z, 2025-09-26T12:00:00Z)` contains one arrival: `SHIP-000001`, `PLAN-SHIP-000001:L1`, `2025-09-26T11:15:47.52Z`.
- Independent affected set: `{SHIP-000001}`. All other 1,499 joined shipments have no planned SGSIN arrival in the event interval.
- Safe decision: **operator intervention**. Do not invent a replacement route or call the route infeasible. Recovery feasibility is `UNKNOWN`: the model provides no vessel position or movement state and the policy leaves arrival-closure handling unresolved, with no diversion or holding modeled.
- Missing facts/policy: verified vessel position and movement/execution state at closure time; carrier-authorized diversion options, if any; and a supported arrival, holding, or berthing procedure if waiting or delayed arrival is considered.

The complete 619-arrival scan, event evidence, joins, and policy reference are in `evaluation/ground_truth/SC-002.json`.

### SC-007 — one-hour delay on SVC-35a7482f2af1d0

- Scanned all 2,936 planned legs and enumerated **64** planned departures on the target service. Exactly one is in `[2025-10-01T00:00:00Z, 2025-10-01T01:00:00Z)`: `SHIP-000001`, `PLAN-SHIP-000001:L2`, departing at `2025-10-01T00:00:00Z`.
- Direct effect: planned L2 arrival `2025-10-21T09:42:54.72Z` plus 3,600 seconds gives `2025-10-21T10:42:54.72Z`.
- Downstream connection: L3 departs NLRTM at `2025-10-22T00:00:00Z` with a 12-hour minimum transfer. Earliest readiness is `2025-10-21T22:42:54.72Z`; remaining slack is **4,625.28 seconds (1h 17m 5.28s)**. The slack is nonnegative and the fixed connection is feasible.
- Final ETA remains `2025-10-24T08:45:44.64Z`, before the `2025-11-01T00:00:00Z` deadline by 7 days, 15h 14m 15.36s.
- Independent affected set: `{SHIP-000001}`. L2 is direct delay impact; L3 is downstream connection evidence, not another shipment or a replacement recovery route.
- Safe decision: **`NO_REROUTE_REQUIRED`**, derived only after all fail-safe checks pass. The original itinerary continuation is feasible; alternative-route feasibility is `NOT_APPLICABLE` because no reroute is required.

#### SC-007 fail-safe assumptions

Before assigning `VERIFIED` or a no-reroute label, the verifier checks that (1) the affected cohort is exactly `{SHIP-000001}`, (2) its only matched direct event is the intended service delay on `PLAN-SHIP-000001:L2`, (3) the event delay is exactly one hour, (4) a downstream fixed connection exists and is feasible, (5) every calculated remaining transfer slack is nonnegative, and (6) the final modeled ETA meets the delivery deadline. “No alternative recovery route required” is derived from the feasible fixed continuation and on-time delivery. If any check fails, generation raises `ScenarioAssumptionError` with the failed check names, cohort, and calculation diagnostics; no label is written. It never falls back to a hardcoded no-reroute conclusion.

### SC-012 — all-operations ARBUE closure

- Scanned all 1,500 plans and 2,936 legs, enumerating **8** planned arrivals, **4** planned departures, and **0** consecutive-leg transfer intervals at ARBUE.
- Overlaps in `[2025-01-01T00:00:00Z, 2025-01-02T00:00:00Z)`: 0 arrivals, 0 departures, 0 transfers; affected set is explicitly empty.
- Expected recovery classification: all 1,500 shipments `UNCHANGED`; zero recovery plans.

The empty impact set and unaffected cohort derive from the calculated overlap set. If any overlap is found, the verifier raises `ScenarioAssumptionError` with the shipment IDs and overlapping operation evidence before writing a label. It does not emit an empty affected set, an all-unchanged classification, or `VERIFIED` for a changed candidate. The complete operation scans are retained in `evaluation/ground_truth/SC-012.json`.

## Comparison with saved Phase 3/4 observations

| Scenario | Independent reference | Phase 3 observed | Phase 4 observed | Comparison |
|---|---|---|---|---|
| SC-002 | `{SHIP-000001}`; intervention required; route feasibility unknown | Same set; `PORT_CLOSURE_ARRIVAL_OVERLAP`; no-recovery `BLOCKED` | Affected shipment `OPERATOR_INTERVENTION_REQUIRED`; 1,499 `UNCHANGED`; reason `ARRIVAL_CLOSURE_POSITION_UNRESOLVED`; plan null | Match |
| SC-007 | `{SHIP-000001}`; one-hour delay, fixed connection feasible, deadline met, `NO_REROUTE_REQUIRED` | Same set; `SERVICE_DELAY_DEPARTURE_OVERLAP` on L2 and `RECOVERED_CONNECTION` on L3; one shipment-level `DELAYED` | Affected shipment `NO_REROUTE_REQUIRED`; 1,499 `UNCHANGED`; reason `FIXED_CONNECTION_RECOVERED` | Match |
| SC-012 | Empty affected set; all 1,500 unchanged | Empty set; all 1,500 `UNAFFECTED` | All 1,500 `UNCHANGED`; other statuses zero | Match |

The comparison JSONs preserve observed reasons, missing-information fields, and relevant recovery-plan values separately from independent labels. No differences were found. In SC-007, two Phase 3 leg-level causes still correspond to one affected shipment and do not imply an alternative route.

## Regression tests and reproducibility

Focused tests are in `tests/test_phase5_ground_truth.py`. They cover successful SC-007 derivation, missed-connection and deadline-infeasible refusal, SC-012 empty-set and overlap behavior, separate comparison output, reference-file immutability, deterministic repeated outputs, and absence of Phase 3/4 imports or tool invocation in label generation.

Commands used:

```powershell
python -m unittest tests.test_phase5_ground_truth -v
python -m unittest discover -s tests -v
python evaluation/verify_first_batch.py generate --verification-date 2026-11-15
python evaluation/verify_first_batch.py compare
```

Results: **9 focused tests passed; 55 tests passed in the full project suite.** Generation and comparison were repeated with identical inputs/date. Ground-truth and comparison hashes were identical across repetitions. The `compare` command reported `ground_truth_unchanged: true` and `mismatches: []`. No observed execution fields are present in ground-truth files.

## Provenance and hashes

Manifest `data/builds/research_1500/dataset_manifest.json` SHA-256: `b2323fc9c0b3d251bb234346157770e66746eaeaed4c51063a3cd59b9759ff46`; seed 42, generator 2.1.0, validation `passed`. Canonical inputs remained unchanged:

| Canonical file | SHA-256 |
|---|---|
| `ports.json` | `d6c5eb8baf1499e322283771acc208ccba2a6a1eefdb7bdc4b85467179f713ed` |
| `services.json` | `e39e0e5ec162e469a96c379ba8b0b52fcd29ba41960ccbc7dc9518455a727bc0` |
| `shipments.json` | `5b22521748fa2ee68e38bcad5464e58f0e326d42b29e47a8b4f38a3864524e95` |
| `route_plans.json` | `d2e2fef7184ab0b957369ff9c3dd442e6e052a0131d5901ad1400234564740cf` |

Recovery policy `modeled-periodic-v1` SHA-256: `93e8627763eb40e6872e437fa5c56ffd1b7e41607bbb52bc40c1e19757040ef0`. Repository commit at verification: `d8c8400bcf536c6d09d933780562ab3e659751ee`. Verifier SHA-256: `399ba4d124004c38dc92b23391967e77a575d18bead78086564fba8c8f38c19c`.

| Scenario | Ground-truth SHA-256 | Comparison SHA-256 |
|---|---|---|
| SC-002 | `e8268dbc2cfd92b1f22246c2877a703766fe99e177e47d4a8ddee38560472d61` | `d6d18d05259543439d4111e39b6d115a1ef5cd423cc5963675575b63cf9d570f` |
| SC-007 | `c63a90ca7d370adf9b19e994d422f21f930e6cd413c840fd0d50a5a01a704a1a` | `d5b8e7d30d66f4731486e3049e113f047ca489af1499ee270d88e777898fbb37` |
| SC-012 | `6f442e4dae7ecd194f6616b73f1bf4316f8bd43168e12d958236002b7f5865b6` | `ca19c9f478dcda5e8e1328337c30ced0eec9cc3780215aab1aeb2368d5e26c0b` |

Each comparison record contains the corresponding reference hash and hashes of the Phase 3 impact/summary and Phase 4 recovery/summary files. Comparison outputs are deterministic and have no dynamic timestamp.

## Final status and limitations

SC-002, SC-007, and SC-012 remain **VERIFIED** for their event, impact, and safe-decision labels under the frozen modeled rules. SC-002 alternative-route feasibility remains `UNKNOWN`; the intervention label is not route infeasibility. SC-007 verifies continuation of the original itinerary, not route optimality or commercial bookability. SC-012's zero transfer-interval count reflects the frozen plan representation. All schedules are synthetic offsets, and these results are not expert-validated or claims about real maritime operations. No dataset, Phase 3/4 implementation, policy, notice, or scenario JSON was modified; no additional scenario was created and Phase 5.2d was not started.
