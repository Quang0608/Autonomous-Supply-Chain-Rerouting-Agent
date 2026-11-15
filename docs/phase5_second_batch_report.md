# Phase 5.2d - Second Batch Construction and Preliminary Execution Report

**Status:** Preliminary execution only. These observations are outputs of the existing Phase 3/4 tools, not independent ground truth. SC-001 does **not** demonstrate an alternative service sequence and remains unresolved for its intended capability. No ground-truth labels were created.

## A. Construction summary

| Scenario | Candidate selected | Event and exact interval (UTC) | Selection rationale |
|---|---|---|---|
| SC-001 | C-001-A (`SHIP-000001`, `PLAN-SHIP-000001`) | `PORT_CLOSURE`, `SGSIN`, `DEPARTURE`, `[2025-10-01T00:00:00Z, 2025-10-01T01:00:00Z)` | The event contains the candidate L2 departure. This original one-hour fixture is retained because the bounded refinement found no qualifying alternative-route case; its `RECOVERED` results reschedule the original service sequence, so SC-001 remains unresolved for the catalog purpose. |
| SC-004 | C-004-B (`SHIP-000005`, `PLAN-SHIP-000005`) | `SERVICE_SUSPENSION`, `SVC-e3ab1786547e47`, `DEPARTURE_WINDOW`, `[2025-01-22T00:00:00Z, 2025-02-05T01:00:00Z)` | This window includes scheduled departures on Jan 22, Jan 29 and Feb 5. It leaves alternative services available and Phase 4 returned a different, validated route for the nominated shipment. |
| SC-008 | C-008-B (`SHIP-000026`, `PLAN-SHIP-000026`) | `SERVICE_DELAY`, `SVC-35a7482f2af1d0`, `DEPARTURE_WINDOW`, `[2025-09-10T00:00:00Z, 2025-09-10T01:00:00Z)`, `delay_hours: 3` | The window contains the candidate departure. Three hours exceeds the candidate's computed transfer slack and creates an unresolved fixed connection. Phase 4 produced a feasible continuation from that supported recovery state. |

Each scenario has a synthetic notice at `examples/phase5/<SC-ID>/notice.txt` and its structured reference event at `examples/phase5/<SC-ID>/scenario.json`. Notices explicitly state that they are simulated and not authentic advisories. They describe the same target, scope/semantics, dates and delay as the JSON without naming affected shipments or recovery outcomes.

### Candidate exploration

Exploration was bounded to the two documented SC-001 candidates, with three event windows per candidate (the original one-hour probe plus two longer variants). No additional shipment/port combinations were tested: both documented candidates showed the same-service rescheduling pattern, while longer closures increased cohort size and infeasible outcomes. No production behavior or input data was altered to force a result.

#### SC-001 route and schedule inspection

- C-001-A is `SHIP-000001` (3 TEU, `GENERAL_CONTAINER`, deadline `2025-11-01T00:00:00Z`). Its completed prefix reaches SGSIN; its original downstream sequence is `SVC-35a7482f2af1d0` (SGSIN->NLRTM, 20.4048 days, $920.63/TEU) then `SVC-52b237e002da4b` (NLRTM->DKAAR, 2.3651 days, $297.18/TEU). Both are weekly, 12-hour transfer minimum, 5,000-TEU capacity and accept the shipment cargo class. A directed graph alternative exists via `SVC-d8c15c43fb15b4` (SGSIN->AEQWE), `SVC-c3c15085c46051` (AEQWE->NLRTM), then `SVC-52b237e002da4b`. Its modeled first two costs alone are $530.16 and $752.42/TEU, plus $297.18/TEU for the final leg. All are weekly, 12-hour transfer minima, 5,000-TEU capacity and cargo compatible. The alternative is graph connectivity only; Phase 4 did not select it in the tested windows. Under the modeled 7-day anchored departures, a projection beginning at Oct 8 would sail SGSIN->AEQWE Oct 8 and arrive Oct 17 02:33:30.24Z; the next legs would depart Oct 22 and Nov 12, with final ETA Nov 14 08:45:44.64Z, after the Nov 1 deadline. The original downstream services cost $1,217.81/TEU combined; this alternative costs $1,579.76/TEU before any additional transfer effects. This is a candidate-screening calculation, not an independent reference label.
- C-001-B is `SHIP-000003` (2 TEU, `GENERAL_CONTAINER`, deadline `2025-07-18T00:00:00Z`). Its completed prefix reaches NLRTM; its original downstream service is `SVC-534311f36a1cb7` (NLRTM->DEHAM, 1.7231 days, $274.99/TEU). A directed graph alternative exists via `SVC-52b237e002da4b` (NLRTM->DKAAR) and `SVC-c8d78b347bad30` (DKAAR->DEHAM), with modeled costs $297.18 and $288.98/TEU. These services are also weekly, 12-hour transfer minima, 5,000-TEU capacity and cargo compatible. For the original one-hour window, the alternative can first depart NLRTM Jul 9, reach DKAAR Jul 11 08:45:44.64Z, then depart Jul 16 and reach DEHAM Jul 18 03:04:10.56Z, after the Jul 18 00:00Z deadline. The two-leg alternative costs $586.16/TEU versus $274.99/TEU for the original direct service. Under the tested windows, Phase 4 kept the cheaper direct service when it could meet deadline; extended closure cases produced infeasible statuses rather than selecting that alternative. These are schedule/cost screening calculations, not independent reference labels.
- Phase 4 uses the configured 7-day departure frequency anchored at simulation day 0. For these two ports, all inspected outgoing modeled services have a 7-day frequency. A port closure therefore blocks departures of all those services during the interval; after reopening, the original service is available on the same weekly cadence. A longer interval does not selectively remove the original service while leaving other departures available.

| Candidate/probe | Event window (UTC, half-open) | Phase 3 affected | Phase 4 statuses (all 1,500 shipments) | Changed selected service sequences? |
|---|---|---:|---|---|
| C-001-A original | SGSIN `[2025-10-01 00:00, 2025-10-01 01:00)` | 7 | 7 `RECOVERED`, 1,493 `UNCHANGED` | No (0 of 7) |
| C-001-A 7-day | SGSIN `[2025-10-01 00:00, 2025-10-08 00:00:01)` | 10 | 8 `RECOVERED`, 2 `DEADLINE_INFEASIBLE`, 1,490 `UNCHANGED` | No (0 of 8); nominated shipment is `DEADLINE_INFEASIBLE` |
| C-001-A 14-day | SGSIN `[2025-10-01 00:00, 2025-10-15 00:00:01)` | 17 | 10 `RECOVERED`, 7 `NO_FEASIBLE_ROUTE`, 1,483 `UNCHANGED` | No (0 of 10); nominated shipment is `NO_FEASIBLE_ROUTE` |
| C-001-B original | NLRTM `[2025-07-02 00:00, 2025-07-02 01:00)` | 15 | 15 `RECOVERED`, 1,485 `UNCHANGED` | No (0 of 15) |
| C-001-B 7-day | NLRTM `[2025-07-02 00:00, 2025-07-09 00:00:01)` | 32 | 28 `RECOVERED`, 4 `DEADLINE_INFEASIBLE`, 1,468 `UNCHANGED` | No (0 of 28); nominated shipment resumes same service on Jul 16 |
| C-001-B 14-day | NLRTM `[2025-07-02 00:00, 2025-07-16 00:00:01)` | 47 | 27 `RECOVERED`, 15 `NO_FEASIBLE_ROUTE`, 5 `DEADLINE_INFEASIBLE`, 1,453 `UNCHANGED` | No (0 of 27); nominated shipment is `NO_FEASIBLE_ROUTE` |

For each probe, service-sequence comparison used each selected full revised itinerary versus the original full itinerary, not timestamps alone. Every changed-sequence count is zero. Probe outputs are retained locally under `data/simulations/phase5/phase5_2d/refinement_probes/` and are preliminary tool observations.

| Other candidate/probe | Observation | Selection decision |
|---|---|---|
| C-004-A, one-hour suspension of `SVC-534311f36a1cb7` on Jul 2 | The initial 2-shipment cohort resumes that same service on Jul 9. | Rejected as a weak alternative-route case. |
| C-004-A, Jul 2 through Jul 16 00:00:01 suspension | 13 affected; 10 `RECOVERED` and 3 `DEADLINE_INFEASIBLE`. `SHIP-000003` did use a different route via FRLEH, but the cohort had mixed outcomes. | Not selected; C-004-B gives a smaller cohort with all impacted cases recovered. |
| C-004-B, selected suspension | 5 affected; 5 `RECOVERED`; four use different service sequences, including nominated `SHIP-000005`. | Selected. |
| C-008-A, three-hour delay on Oct 1 departure | 1 affected and `RECOVERED`; suffix rebooks the same original downstream service on a later sailing. | Not selected; C-008-B gives a three-shipment cohort while preserving the same supported missed-connection behavior. |
| C-008-B, selected three-hour delay | 3 affected and 3 `RECOVERED`; all replacement suffixes use the original downstream service IDs on later modeled sailings. | Selected as a missed-connection recovery case, with no claim of a new service sequence. |

## B. Validation

Both existing scenario validators passed for all three final fixtures:

- `python scripts/phase3_simulation.py validate-scenario --dataset data/builds/research_1500 --scenario examples/phase5/SC-00X/scenario.json`
- `python scripts/phase4_recovery.py validate-scenario --dataset data/builds/research_1500 --scenario examples/phase5/SC-00X/scenario.json --policy config/recovery_policy.json`

Phase 3 confirmed each canonical target ID exists. The notice-to-JSON checks confirmed:

- SC-001 notice says SGSIN departures are restricted for the one-hour interval; JSON is `PORT_CLOSURE` with `affected_operations: ["DEPARTURE"]`.
- SC-004 notice identifies only the named service's departure suspension and interval; JSON uses `SERVICE_SUSPENSION` and `DEPARTURE_WINDOW`.
- SC-008 notice identifies a three-hour journey delay for departures of the named service in the one-hour window; JSON uses `SERVICE_DELAY`, `DEPARTURE_WINDOW`, and `delay_hours: 3`.

Intervals are positive-duration and interpreted half-open by the implementation. SC-004's end is one hour after the Feb 5 scheduled departure, so that departure is included. The suspension targets only the named service; it does not globally remove that service after the event window.

## C. Observed shipment impacts

These are Phase 3 tool observations, not independent labels.

### SC-001

- Phase 3 summary: 7 affected (7 direct, 0 indirect), 7 disrupted legs, all no-recovery statuses `BLOCKED`; 1,493 unaffected.
- Complete affected set: `SHIP-000001`, `SHIP-000164`, `SHIP-000212`, `SHIP-000630`, `SHIP-000997`, `SHIP-EXP-000098`, `SHIP-EXP-000339`.
- Each cause is `PORT_CLOSURE_DEPARTURE_OVERLAP` on the listed leg/service at `SGSIN`, `2025-10-01T00:00:00Z`.

| Shipment | Affected leg | Service |
|---|---|---|
| SHIP-000001 | PLAN-SHIP-000001:L2 | SVC-35a7482f2af1d0 |
| SHIP-000164 | PLAN-SHIP-000164:L3 | SVC-37336995968ed1 |
| SHIP-000212 | PLAN-SHIP-000212:L3 | SVC-9487ce0240e2d0 |
| SHIP-000630 | PLAN-SHIP-000630:L2 | SVC-5c819508b9dd64 |
| SHIP-000997 | PLAN-SHIP-000997:L2 | SVC-5c819508b9dd64 |
| SHIP-EXP-000098 | PLAN-SHIP-EXP-000098:L2 | SVC-da4bc9ff69bcf4 |
| SHIP-EXP-000339 | PLAN-SHIP-EXP-000339:L2 | SVC-EXP-0a46814e21d98e |

### SC-004

- Phase 3 summary: 5 affected (5 direct, 0 indirect), 5 disrupted legs, all no-recovery statuses `BLOCKED`; 1,495 unaffected.
- Complete affected set: `SHIP-000005`, `SHIP-000320`, `SHIP-000417`, `SHIP-000637`, `SHIP-000930`.
- All causes are `SERVICE_SUSPENSION_DEPARTURE_OVERLAP` on L2 of `SVC-e3ab1786547e47`. The observed scheduled conflict times are Jan 22 (three shipments), Jan 29 (one shipment) and Feb 5 (one shipment).

### SC-008

- Phase 3 summary: 3 affected, all directly affected on L2 and indirectly affected on L3; 6 disrupted leg records; 3 no-recovery statuses `UNRESOLVED_CONNECTION`; 1,497 unaffected.
- Complete affected set: `SHIP-000026`, `SHIP-000424`, `SHIP-000741`.
- Every direct cause is `SERVICE_DELAY_DEPARTURE_OVERLAP` on L2 of `SVC-35a7482f2af1d0`; every downstream cause is `UNRESOLVED_CONNECTION` on L3, with propagated delay 3 hours.
- For nominated `SHIP-000026`, planned arrival was `2025-09-30T09:42:54.72Z`, next planned departure was `2025-10-01T00:00:00Z`, and minimum transfer was 12 hours. Original transfer slack was `2:17:05.28`. A three-hour delay makes the connection-ready time `2025-10-01T00:42:54.72Z`, which misses the fixed departure by `00:42:54.72`. The same modeled arrival/departure timing applies to the other affected cohort members.

## D. Observed recovery outcomes

Phase 4 status distributions count all 1,500 shipments. `RECOVERED` and route-validation results are preliminary outputs of the existing implementation and are not claims of independent feasibility verification or global optimality.

| Scenario | UNCHANGED | RECOVERED | Other statuses | Selected recovered plans validated |
|---|---:|---:|---:|---|
| SC-001 | 1,493 | 7 | 0 | 7/7 selected plans PASS. Search diagnostics contain 8 PASS and 1 FAIL across candidate evaluations; a rejected candidate failure is not a selected plan failure. |
| SC-004 | 1,495 | 5 | 0 | 5/5 selected plans PASS. Search diagnostics contain 40 PASS and 19 FAIL across candidate evaluations; selected plans all PASS. |
| SC-008 | 1,497 | 3 | 0 | 3/3 selected plans PASS; search diagnostics 3 PASS, 0 FAIL. |

### SC-001 - recovered itineraries retain the original service sequences

All impacted shipments' selected replacement suffixes use the same service IDs as their original downstream suffixes. They depart on the next modeled sailing, `2025-10-08T00:00:00Z`; the service sequence does not change. This is a delayed continuation, not the intended alternative-route result.

| Shipment | Replacement suffix (service: departure -> arrival, UTC) | Original ETA -> Phase 4 ETA | Modeled total cost (additional) | Deadline |
|---|---|---|---:|---|
| SHIP-000001 | SVC-35a7482f2af1d0: Oct 8 00:00 -> Oct 28 09:42:54.72; SVC-52b237e002da4b: Oct 29 00:00 -> Oct 31 08:45:44.64 | Oct 24 08:45:44.64 -> Oct 31 08:45:44.64 | $4,555.77 ($0) | Nov 1 00:00 |
| SHIP-000164 | SVC-37336995968ed1: Oct 8 00:00 -> Oct 10 11:15:47.52 | Oct 3 11:15:47.52 -> Oct 10 11:15:47.52 | $6,061.24 ($0) | Nov 3 00:00 |
| SHIP-000212 | SVC-9487ce0240e2d0: Oct 8 00:00 -> Oct 15 19:23:05.28 | Oct 8 19:23:05.28 -> Oct 15 19:23:05.28 | $7,194.68 ($0) | Oct 23 00:00 |
| SHIP-000630 | SVC-5c819508b9dd64: Oct 8 00:00 -> Oct 27 22:35:45.60; SVC-6652d23b5ce744: Oct 29 00:00 -> Oct 31 03:46:22.08 | Oct 24 03:46:22.08 -> Oct 31 03:46:22.08 | $4,865.07 ($0) | Nov 8 00:00 |
| SHIP-000997 | SVC-5c819508b9dd64: Oct 8 00:00 -> Oct 27 22:35:45.60 | Oct 20 22:35:45.60 -> Oct 27 22:35:45.60 | $2,715.12 ($0) | Nov 20 00:00 |
| SHIP-EXP-000098 | SVC-da4bc9ff69bcf4: Oct 8 00:00 -> Oct 10 20:35:22.56 | Oct 3 20:35:22.56 -> Oct 10 20:35:22.56 | $3,010.90 ($0) | Oct 11 00:00 |
| SHIP-EXP-000339 | SVC-EXP-0a46814e21d98e: Oct 8 00:00 -> Oct 14 17:39:41.76 | Oct 7 17:39:41.76 -> Oct 14 17:39:41.76 | $2,187.38 ($0) | Oct 22 00:00 |

### SC-004 - validated alternative services for four of five cases

`SHIP-000005`, the nominated candidate, is rerouted from its original NLRTM -> SGSIN -> CNSGH sequence to NLRTM -> KRPUS -> CNSGH. Four affected shipments use different service sequences; `SHIP-000930` waits for the original NLRTM -> SGSIN service after the suspension window and then continues as planned. Every selected plan meets its shown deadline and its selected validator checks are PASS.

| Shipment | Replacement suffix (service: departure -> arrival, UTC) | Original ETA -> Phase 4 ETA | Modeled total cost (additional) | Deadline |
|---|---|---|---:|---|
| SHIP-000005 | SVC-d132cd5e4d7b5a NLRTM -> KRPUS: Jan 22 00:00 -> Feb 17 06:19:17.76; SVC-eec16d7fc4cfb0 KRPUS -> CNSGH: Feb 19 00:00 -> Feb 21 02:03:33.12 | Feb 18 02:58:24.96 -> Feb 21 02:03:33.12 | $3,409.06 (+$125.84) | Mar 21 00:00 |
| SHIP-000320 | SVC-d132cd5e4d7b5a NLRTM -> KRPUS: Jan 22 00:00 -> Feb 17 06:19:17.76; SVC-d6b84373237ec5 KRPUS -> JPYOK: Feb 19 00:00 -> Feb 21 12:32:24 | Feb 19 19:23:05.28 -> Feb 21 12:32:24 | $3,439.24 (+$39.64) | Feb 27 00:00 |
| SHIP-000417 | SVC-d132cd5e4d7b5a NLRTM -> KRPUS: Jan 29 00:00 -> Feb 24 06:19:17.76; SVC-d6b84373237ec5 KRPUS -> JPYOK: Feb 26 00:00 -> Feb 28 12:32:24 | Feb 26 19:23:05.28 -> Feb 28 12:32:24 | $7,594.92 (+$79.28) | Mar 6 00:00 |
| SHIP-000637 | SVC-d132cd5e4d7b5a NLRTM -> KRPUS: Jan 22 00:00 -> Feb 17 06:19:17.76; SVC-d6b84373237ec5 KRPUS -> JPYOK: Feb 19 00:00 -> Feb 21 12:32:24 | Feb 19 19:23:05.28 -> Feb 21 12:32:24 | $7,273.96 (+$79.28) | Mar 22 00:00 |
| SHIP-000930 | SVC-e3ab1786547e47 NLRTM -> SGSIN: Feb 12 00:00 -> Mar 4 09:42:54.72; SVC-c88aa6c1b50312 SGSIN -> CNSGH: Mar 5 00:00 -> Mar 11 02:58:24.96 | Mar 4 02:58:24.96 -> Mar 11 02:58:24.96 | $6,573.04 ($0) | Mar 19 00:00 |

### SC-008 - missed fixed connections recovered by later same-service sailings

The Phase 4 recovery state starts after the delayed inbound leg; it does not replace vessel movement or claim a different service sequence. All three replacement suffixes use the same downstream service IDs as the original plans, but depart on Oct 8 rather than the missed Oct 1 connection. All selected plans pass the existing validator, remain before deadline and have no modeled additional cost.

| Shipment | Replacement suffix (service: departure -> arrival, UTC) | Original ETA -> Phase 4 ETA | Modeled total cost (additional) | Deadline |
|---|---|---|---:|---|
| SHIP-000026 | SVC-deda6d6189fe29 NLRTM -> ESPNY: Oct 8 00:00 -> Oct 13 03:08:47.04 | Oct 6 03:08:47.04 -> Oct 13 03:08:47.04 | $6,961.92 ($0) | Oct 14 00:00 |
| SHIP-000424 | SVC-ef695c2f893320 NLRTM -> GBBPT: Oct 8 00:00 -> Oct 10 06:28:56.64 | Oct 3 06:28:56.64 -> Oct 10 06:28:56.64 | $1,641.61 ($0) | Oct 11 00:00 |
| SHIP-000741 | SVC-ef695c2f893320 NLRTM -> GBBPT: Oct 8 00:00 -> Oct 10 06:28:56.64 | Oct 3 06:28:56.64 -> Oct 10 06:28:56.64 | $6,566.44 ($0) | Nov 3 00:00 |

## E. Limitations and Phase 5.2e requirements

- **SC-001 does not qualify as an alternative-route recovery scenario.** Six windows across C-001-A and C-001-B produced zero selected plans with changed service sequences. The fixture remains the original one-hour C-001-A event and is a closure/rescheduling feasibility example only. Phase 5.2e must not label it as alternative-route recovery. A future catalog revision could change SC-001 to test accurate classification of same-service rescheduling versus alternative routing, but that purpose change requires review.
- **SC-004 has strong preliminary route evidence**, including a different service sequence for the nominated shipment and four of five affected cases. Phase 5.2e must independently reconstruct all affected departures and each route leg's timing, continuity, transfer readiness, capacity, costs and deadline. Phase 4's bounded search and validator do not establish global optimality or independent ground truth.
- **SC-008 recovers by rebooking the same downstream services.** The missing fixed connection is clearly observed and Phase 4 returns feasible later sailings, but this cohort does not demonstrate changed service IDs. Phase 5.2e should verify delayed arrivals, connection readiness, replacement departure times, costs and deadlines independently, and preserve this distinction.
- Candidate-search diagnostics include rejected route candidates with validator failures for SC-001 and SC-004. These do not correspond to the selected recovered plans; the exact selected service sequences were matched to passing validation rows. Reported status and validation counts remain observations of the existing tool only.
- No independent ground-truth labels or independent reference-route calculations have been created for this refinement. Existing Phase 4 validator PASS results establish only that the implementation accepted its selected route under its own modeled checks; they do not provide independent reference evidence. Phase 5.2e remains responsible for independent route and impact verification. No maritime expert validation was performed; these are preliminary student-workflow executions against the frozen modeled dataset.

## F. Provenance

- Dataset: frozen `research_1500` at `data/builds/research_1500/`; manifest and four canonical source files matched the manifest before and after execution.
- Manifest SHA-256: `b2323fc9c0b3d251bb234346157770e66746eaeaed4c51063a3cd59b9759ff46`.
- Canonical file SHA-256 values:

| File | SHA-256 |
|---|---|
| ports.json | `d6c5eb8baf1499e322283771acc208ccba2a6a1eefdb7bdc4b85467179f713ed` |
| services.json | `e39e0e5ec162e469a96c379ba8b0b52fcd29ba41960ccbc7dc9518455a727bc0` |
| shipments.json | `5b22521748fa2ee68e38bcad5464e58f0e326d42b29e47a8b4f38a3864524e95` |
| route_plans.json | `d2e2fef7184ab0b957369ff9c3dd442e6e052a0131d5901ad1400234564740cf` |

- Recovery policy: `config/recovery_policy.json`, policy ID `modeled-periodic-v1`, SHA-256 `93e8627763eb40e6872e437fa5c56ffd1b7e41607bbb52bc40c1e19757040ef0`.
- Code version for SC-001 refinement probes and final rerun: commit `cd388e12ff1b95d8598be9082ccfb7bcc8fecbe4`, branch `phase5-evaluation-benchmark`. SC-004/SC-008 preliminary runs were recorded at `4007bf6204d1bf628c8e0771a12326b140bfb62a`; a direct commit comparison confirms the Phase 3/4 scripts, implementations, validator and recovery policy are identical between these commits.
- The only change to each notice was its first-line separator (`?` to ASCII `-`); SC-004 and SC-008 notice bodies and all three scenario JSON files are unchanged. The scenario JSON hashes below therefore remain as before.
- Notice and structured-event SHA-256 values:

| Scenario | notice.txt | scenario.json |
|---|---|---|
| SC-001 | `3bac6de84ea89eb4c3594fba3c7ad0c3963625d9fcd2c65c3db602f31e3e81ab` | `d241a6ffe68f04d081e20c0e3b3a63c18dfe73325ce22dd491f7e86497d1faa9` |
| SC-004 | `d61d3525b1677b939482c04a9dfdb8e40e6860c10cb4716d62b49c66e4279c3b` | `4af112de3e82b2a0aff46f5af26b15f5ef3453d464e5a771c53b161e0e8f8bd7` |
| SC-008 | `5d0a61f06bedb91d7845cac2c201f39970222cfd106f12213d045772706b901d` | `600f348491469d086133dc6d86f8c33e06fbb39fec5dd41e9437a49d1bb040c6` |

- Preliminary outputs are local/ignored under `data/simulations/phase5/phase5_2d/<SC-ID>/`. Each scenario contains Phase 3 `shipment_impacts.json`, `event_impacts.json`, `no_recovery_outcomes.json`, and `summary.json`; Phase 4 `recovery_results.json`, `constraint_validation.json`, `recovery_states.json`, and `summary.json`.
- Final SC-001 Phase 3/4 outputs were rerun after refinement and match the original one-hour fixture observations; hashes follow. SC-004/SC-008 outputs were not rerun or changed.
- Key output hashes (SHA-256):

| Scenario | Output file | SHA-256 |
|---|---|---|
| SC-001 | phase3/summary.json | `41bed69cd4ba8fb0f13eda13b1b05a1ae7a2d99df1ea042a8ecebec71c64e612` |
| SC-001 | phase3/shipment_impacts.json | `04183480c4cb01d3918290eff763d1c1f4499178c1ed51587c0f62ff64c7f575` |
| SC-001 | phase4/summary.json | `c495a465fcc10305b526611daade60509e55fef860b57ea25c4234e6e9128332` |
| SC-001 | phase4/recovery_results.json | `359f57ac67b44604eb64fd327840b608d2f9fff0be96a92c5952b74ff451dec2` |
| SC-001 | phase4/constraint_validation.json | `e99febafb9f4454bbd85243a3460bc66d09390322473df5d966bbc54e16d47df` |
| SC-004 | phase3/summary.json | `e1ef9a3288c2ed13161bc113e4b4ec4cd55975be260d505e7f2ac313ce6746ed` |
| SC-004 | phase3/shipment_impacts.json | `78ffcbae96aa1164e02982748f7a2dc363c01d807889e0915e76bf5dd64aae55` |
| SC-004 | phase4/summary.json | `e341f2c1bb969d3489a76c6d88067d78afae3865e8dd36a61c313ba9011bc7b5` |
| SC-004 | phase4/recovery_results.json | `f588155df3f9c9385398aa35d3eec3c4196a8c277ba05df71aa9ac42f2dd4475` |
| SC-004 | phase4/constraint_validation.json | `f05d5bfcc229392acc68798722713a746393951ba7110fcb1482aa9dd3ba8fd` |
| SC-008 | phase3/summary.json | `0ea8d1afe128833b891c2c8d562c6ef945af35313cbaa37d837fd3c98f4952af` |
| SC-008 | phase3/shipment_impacts.json | `3329b1602f1751406524f08c8f93cf2e1c3cff34be3245bf47a68cf55d48898b` |
| SC-008 | phase4/summary.json | `3766d2a702f4981a5579a35b58aebbceb1f0442df93cb7739dab6b3cfd89a1c9` |
| SC-008 | phase4/recovery_results.json | `56d3cc595d5f5218406b76c30552edafffb6731401019c71ebffc22b86d7abf6` |
| SC-008 | phase4/constraint_validation.json | `b3ab3d09702b6944a07ae4c138214c223b585bb49d633e3d313ab68308ac99ff` |
