# Phase 5.2c — Independent Ground-Truth Verification (First Three Scenarios)

**Verification date:** 2026-11-15  
**Dataset:** frozen `research_1500`, seed 42, manifest validation passed  
**Verification status:** student-verified against the modeled dataset and stated rules; no maritime expert review is claimed.

## A. Methodology

The independent calculations are implemented in [`evaluation/verify_first_batch.py`](../evaluation/verify_first_batch.py), version `phase5-independent-first-batch-1.0.0`. The `generate` command reads `shipments.json`, `route_plans.json`, `services.json`, `ports.json`, the three structured scenario references, and the recovery policy. It does not import Phase 3, Phase 4, or the recovery validator, and does not read their outputs while deriving labels.

The script reconstructs every planned instant from the UTC epoch `2025-01-01T00:00:00Z` using decimal schedule offsets and microsecond arithmetic. It applies the half-open event rule `[start_time, end_time)`, joins all 1,500 shipments to their plans, and records complete relevant operation scans and intermediate connection arithmetic inside the ground-truth JSON files. The SC-007 calculation walks subsequent fixed legs, adds each next leg's minimum transfer, and compares connection readiness and final ETA with the shipment deadline.

Only after the independent labels were generated did the separate `compare` command read the saved Phase 3/4 artifacts and append a distinct `observed_execution` object to each label. That step does not alter expected event, impact, or recovery fields. The comparison is corroboration, not the basis of the labels.

## B. Per-scenario evidence

### SC-002 — arrival closure at SGSIN

- **Independent scan:** all 1,500 joined route plans and 2,936 planned legs were traversed; all 619 planned arrivals at SGSIN were enumerated. The event window is `[2025-09-26T11:00:00Z, 2025-09-26T12:00:00Z)` and contains one arrival: `SHIP-000001`, plan `PLAN-SHIP-000001`, leg `PLAN-SHIP-000001:L1`, at `2025-09-26T11:15:47.52Z`.
- **Independent affected set:** `{SHIP-000001}`. It is a direct `PORT_CLOSURE_ARRIVAL_OVERLAP` on L1. All other 1,499 joined shipments have no planned SGSIN arrival in this event window.
- **Safe decision:** operator intervention; do not invent an alternate route and do not label the route globally infeasible. Independent alternative recovery feasibility is **UNKNOWN** because the modeled inputs do not establish where the vessel is or authorize an operational action.
- **Missing operational information:** verified vessel position and movement/execution state at the closure time; carrier-authorized diversion options, if any, for reaching or bypassing SGSIN; and a supported arrival, holding, or berthing procedure if waiting or delayed arrival is considered. The policy explicitly states arrival closure handling is unresolved and models neither vessel diversion nor holding.
- The complete 619-arrival enumeration, canonical record references, target/event times, and policy evidence are in `evaluation/ground_truth/SC-002.json`.

### SC-007 — one-hour delay on SVC-35a7482f2af1d0

- **Independent scan:** all 2,936 planned legs were traversed; 64 planned departures on the target service were enumerated. Exactly one departure lies in `[2025-10-01T00:00:00Z, 2025-10-01T01:00:00Z)`: `SHIP-000001`, plan `PLAN-SHIP-000001`, L2, departing at `2025-10-01T00:00:00Z`.
- **Direct delay:** the planned L2 arrival is `2025-10-21T09:42:54.72Z`. Adding 3,600 seconds yields `2025-10-21T10:42:54.72Z`.
- **Downstream connection:** L3 departs NLRTM at `2025-10-22T00:00:00Z` and requires 12 hours of transfer. Earliest readiness is `2025-10-21T22:42:54.72Z`, leaving `4,625.28` seconds, or **1h 17m 5.28s**, before the fixed departure. Before the delay the buffer was `2h 17m 5.28s`; the one-hour delay consumes one hour of it.
- **Final delivery:** with the fixed connection feasible, L3 remains on its planned departure and arrival. Modeled final ETA is `2025-10-24T08:45:44.64Z`; the deadline is `2025-11-01T00:00:00Z`, leaving 7 days, 15h 14m 15.36s. The original itinerary continues feasibly.
- **Independent affected set:** `{SHIP-000001}`. L2 is direct delay impact. L3 is downstream connection evidence (`RECOVERED_CONNECTION` under the documented model rule), not a second shipment and not a replacement route.
- **Safe decision:** retain the original itinerary, report the one-hour delay, and do not generate an alternative recovery route. Alternative-route feasibility is `NOT_APPLICABLE` because rerouting is not required; original-itinerary continuation is independently `FEASIBLE`.
- The full 64-departure scan, precise calculations, downstream leg evidence, and deadline comparison are in `evaluation/ground_truth/SC-007.json`.

### SC-012 — all-operations closure at ARBUE

- **Independent scan:** all 1,500 plans and 2,936 planned legs were traversed. The scan enumerated 8 planned arrivals at ARBUE, 4 planned departures, and 0 consecutive-leg transfer occupancy intervals at ARBUE. There were 0 arrival overlaps, 0 departure overlaps, and 0 transfer overlaps with `[2025-01-01T00:00:00Z, 2025-01-02T00:00:00Z)`.
- **Independent affected set:** explicitly empty (`[]`); 1,500 shipments remain outside the affected set. ARBUE is present in the frozen canonical port file.
- **Safe decision:** no recovery action; all 1,500 shipments remain `UNCHANGED`; no recovery plans should be generated.
- The complete arrival, departure, and transfer scans and overlap counts are in `evaluation/ground_truth/SC-012.json`.

## C. Comparison with Phase 3/4 observations

The right-hand values below are saved Phase 5.2b outputs read only after independent calculations were finalized. Full summary objects, affected IDs, selected reasons/statuses, and SHA-256 output references are recorded under each label's `observed_execution` field.

| Scenario | Independent affected set and decision | Observed Phase 3 | Observed Phase 4 | Result |
|---|---|---|---|---|
| SC-002 | `{SHIP-000001}`; intervention, no route proposal; feasibility unknown | Same set; direct cause `PORT_CLOSURE_ARRIVAL_OVERLAP`; no-recovery `BLOCKED` | `OPERATOR_INTERVENTION_REQUIRED` for the shipment; 1,499 `UNCHANGED`; reason `ARRIVAL_CLOSURE_POSITION_UNRESOLVED`; plan null | Membership and safe decision agree. Intervention reflects missing position/policy information, not route infeasibility. |
| SC-007 | `{SHIP-000001}`; direct L2 delay and feasible L3 connection; keep original itinerary | Same set; direct `SERVICE_DELAY_DEPARTURE_OVERLAP` on L2 and downstream `RECOVERED_CONNECTION` on L3; no-recovery `DELAYED` | `NO_REROUTE_REQUIRED` for the shipment; 1,499 `UNCHANGED`; reason `FIXED_CONNECTION_RECOVERED` | Membership and safe decision agree. Phase 3's two leg-level records correctly remain one affected shipment and do not constitute a replacement route. |
| SC-012 | Empty set; all 1,500 unchanged; no recovery plan | Empty impact set; all 1,500 `UNAFFECTED` | All 1,500 `UNCHANGED`; all other statuses zero | Full operation scan and both observed outputs agree. |

No affected-set or safe-decision discrepancy was found. The comparison validates consistency between separate raw-record calculations and prior tool observations; it does not upgrade the tool outputs into the independent method.

## D. Discrepancies and limitations

- **SC-002 feasibility remains unknown.** The model supports a verified operator-intervention label because it lacks actual vessel movement state and supported arrival/diversion handling. It does not establish that no alternate route exists, and no alternate route was independently searched or labeled infeasible.
- **SC-007 has both shipment-level and leg-level descriptions.** The direct L2 delay makes one shipment affected. L3 records that the fixed connection remains feasible after the required transfer; that is downstream evidence, not a new disrupted shipment or a rebooking plan.
- **SC-012 transfer scope is empty in this dataset.** The script looked for consecutive legs whose inbound destination and next outbound origin are both ARBUE; it found none. Arrivals and departures were still exhaustively enumerated and checked separately.
- Schedule times are derived from synthetic numeric offsets and a fixed epoch, not actual sailing schedules. The port closure and service delay are synthetic, not authentic maritime advisories. This is verification against the frozen modeled dataset and stated rules only; it is not maritime expert validation or a claim about real operations.
- No alternative-route enumeration was necessary for SC-007 or SC-012. Any later scenario requiring a positive recovery-route feasibility label needs its own independent graph/timing/constraint analysis.

## E. Provenance

Manifest `data/builds/research_1500/dataset_manifest.json` has SHA-256 `b2323fc9c0b3d251bb234346157770e66746eaeaed4c51063a3cd59b9759ff46`; it identifies seed 42, generator 2.1.0, and validation `passed`. Canonical file hashes remained unchanged during label generation:

| File | SHA-256 |
|---|---|
| `ports.json` | `d6c5eb8baf1499e322283771acc208ccba2a6a1eefdb7bdc4b85467179f713ed` |
| `services.json` | `e39e0e5ec162e469a96c379ba8b0b52fcd29ba41960ccbc7dc9518455a727bc0` |
| `shipments.json` | `5b22521748fa2ee68e38bcad5464e58f0e326d42b29e47a8b4f38a3864524e95` |
| `route_plans.json` | `d2e2fef7184ab0b957369ff9c3dd442e6e052a0131d5901ad1400234564740cf` |

Policy `modeled-periodic-v1` (`config/recovery_policy.json`) SHA-256: `93e8627763eb40e6872e437fa5c56ffd1b7e41607bbb52bc40c1e19757040ef0`. Repository commit used: `3a7d7d65b87037fd18e31d06a3eefc2d164c8870`.

| Scenario | Scenario JSON SHA-256 | Notice SHA-256 | Ground-truth JSON SHA-256 after separate comparison |
|---|---|---|---|
| SC-002 | `72676b7a62648e4bdb721f04d0f256944f43e9d6fa8186397023186bfe9310f0` | `6c08ff2d5eb3f7e15d762ac793fb09e8da424b48f74e4a33ec364fdbd4973a80` | `5c6793f0d2f607e3ac196b475e6b5d89a3f581cadeb7017eb84df53322ee3229` |
| SC-007 | `f31cd628ab219ea42c5225e2b1f0e34ab0410792ad89f3bc4752f3f7b3fcf222` | `9768ddf2b7cb3a488a6d9b32ca9f6e89e61d185332d83990e55bbfba5f9bd0cf` | `c4c33dcc1895d21d31e612cbc39785033fbe4ce0fcd25cd8352298cddca933ba` |
| SC-012 | `8edefa490ff1bc9c75b47886d3518e945469cdc20204397abba2016ee92e949f` | `8d3c6a71864cda47f031094b2027c0c09daf8ca0c07587be0ab69c57ba0a27b9` | `06335bdc2f46813e1e60a4e2c6d2710e0c051ac3e9f2869563da3e00c17eff2c` |

Verifier SHA-256: `9feb6b53e7448c89cd33e1ca78a4b94c56e97aa92349aea5605c44c7deddc66a`. The independent `generate` followed by separate `compare` sequence was repeated twice with the same date; all three final ground-truth JSON hashes were identical across repetitions. The script records source file/record keys and complete operation evidence in the labels themselves.

## F. Final verification status

| Scenario | Status | Basis |
|---|---|---|
| SC-002 | **VERIFIED** | Complete arrival scan establishes the affected shipment and arrival time. Model policy/input gaps establish safe intervention and no invented route; alternative-route feasibility remains explicitly `UNKNOWN`. |
| SC-007 | **VERIFIED** | Complete target-service departure scan, exact delay propagation, fixed-transfer calculation, and deadline comparison establish one affected shipment with a feasible original itinerary and no reroute requirement. |
| SC-012 | **VERIFIED** | Complete canonical arrival/departure/transfer scan finds zero overlapping operations and supports an explicitly empty impact set and 1,500 unchanged shipments. |

`VERIFIED` here applies to the event, impact, and safe-decision labels stated above under the modeled rules. It does not claim real-world operational validity, global route optimality, or expert review. No remaining scenario IDs were created, and no Phase 5.2d or later work was started.
