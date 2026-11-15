# Phase 5.2e — Second-Batch Independent Ground-Truth Report

**Verification date:** 2026-11-15 (fixed input to the deterministic generator)  
**Dataset:** frozen `research_1500`  
**Scope:** SC-001, SC-004 and SC-008 only  
**Review status:** student-verified against the frozen modeled dataset; no maritime expert validation is claimed.

## A. Methodology

`evaluation/verify_second_batch.py generate --verification-date 2026-11-15` reads the manifest, canonical ports, services, shipments and route plans, the recovery policy, and the three structured scenario references. It validates those inputs and reconstructs all relevant planned operations from canonical day offsets relative to 2025-01-01 UTC. Timestamp comparisons use timezone-aware UTC values and half-open event intervals `[start,end)`. Decimal arithmetic is retained for modeled durations and money.

Generation imports no Phase 3, Phase 4 or recovery-validator module and does not read the saved execution directory. The independent impact scan joins all 1,500 shipments to all 1,500 route plans and scans all 2,936 planned legs. It derives direct impacts and, for SC-008, follows delayed arrivals through fixed downstream connections. SC-001 and SC-008 independently reschedule the original remaining service suffix. SC-004 uses a separate bounded depth-first enumeration of directed paths from each supported recovery point through canonical services; the first feasible path found is recorded. It also separately checks the specifically nominated `NLRTM → KRPUS → CNSGH` path for `SHIP-000005` against the blocked original `NLRTM → SGSIN → CNSGH` suffix. For each path, the verifier recalculates departure dates, transit, transfer readiness, event conflicts, route continuity, cycles, hop and horizon limits, cargo class, individual modeled capacity, hard deadline, preserved-prefix cost, revised itinerary cost and additional modeled cost. A failed route check stops generation with diagnostics instead of publishing a positive label.

`compare` runs only after reference generation. It reads the saved Phase 3/4 outputs under `data/simulations/phase5/phase5_2d/`, independently rechecks observed replacement suffixes, records output hashes, and writes separate files under `evaluation/comparisons/`. It never edits reference labels. A comparison `MISMATCH` can therefore coexist with a verified feasible reference route; here it identifies route/quantitative disagreement, while the report states separately whether impact membership, recovery statuses and observed route feasibility agree.

The SC-004 DFS is bounded by the configured four-hop, 180-day and 20,000-expansion policy. The selected route is a feasible candidate within that search, not a proof of global route optimality. The calculation checks individual modeled capacity only, not shared vessel-space or booking availability.

## B. SC-001 — SGSIN departure closure

Reference event: `PORT_CLOSURE`, port `SGSIN`, `DEPARTURE`, `[2025-10-01T00:00:00Z, 2025-10-01T01:00:00Z)`. The event start is inclusive, so departures at exactly 00:00 are affected. A closure only blocks departures from SGSIN during this interval; subsequent modeled departures remain available.

The complete scan found seven affected shipments and 1,493 unaffected shipments. Every match is a direct departure at `2025-10-01T00:00:00Z`, with reason `PORT_CLOSURE_DEPARTURE_OVERLAP`; no indirect legs were derived. The full affected cohort and impacted leg/service are:

| Shipment | Affected leg | Service | Independent status | Final ETA | Full revised itinerary cost |
|---|---|---|---|---|---:|
| `SHIP-000001` | `PLAN-SHIP-000001:L2` | `SVC-35a7482f2af1d0` | `RECOVERED` | 2025-10-31 08:45:44.64Z | $4,555.77 |
| `SHIP-000164` | `PLAN-SHIP-000164:L3` | `SVC-37336995968ed1` | `RECOVERED` | 2025-10-10 11:15:47.52Z | $6,061.24 |
| `SHIP-000212` | `PLAN-SHIP-000212:L3` | `SVC-9487ce0240e2d0` | `RECOVERED` | 2025-10-15 19:23:05.28Z | $7,194.68 |
| `SHIP-000630` | `PLAN-SHIP-000630:L2` | `SVC-5c819508b9dd64` | `RECOVERED` | 2025-10-31 03:46:22.08Z | $4,865.07 |
| `SHIP-000997` | `PLAN-SHIP-000997:L2` | `SVC-5c819508b9dd64` | `RECOVERED` | 2025-10-27 22:35:45.6Z | $2,715.12 |
| `SHIP-EXP-000098` | `PLAN-SHIP-EXP-000098:L2` | `SVC-da4bc9ff69bcf4` | `RECOVERED` | 2025-10-10 20:35:22.56Z | $3,010.90 |
| `SHIP-EXP-000339` | `PLAN-SHIP-EXP-000339:L2` | `SVC-EXP-0a46814e21d98e` | `RECOVERED` | 2025-10-14 17:39:41.76Z | $2,187.38 |

All seven independently checked routes retain the complete original service and port sequences and take a later permitted sailing. Their modeled itinerary totals equal the original totals (additional modeled cost $0.00 for each); all hard deadlines pass. This is **same-service rescheduling**, not a changed-service or changed-port reroute. The safe behavior is to recognize and explain a feasible delayed continuation, without inventing vessel diversion. Phase 4 independently observed seven `RECOVERED` and 1,493 `UNCHANGED`; its selected suffixes, ETAs and costs match these checks exactly.

## C. SC-004 — NLRTM service suspension

Reference event: `SERVICE_SUSPENSION`, target `SVC-e3ab1786547e47`, `DEPARTURE_WINDOW`, `[2025-01-22T00:00:00Z, 2025-02-05T01:00:00Z)`. The independently enumerated direct departure cohort is five shipments: `SHIP-000005` (Jan 22), `SHIP-000320` (Jan 22), `SHIP-000417` (Jan 29), `SHIP-000637` (Jan 22), and `SHIP-000930` (Feb 5), all on `L2` and all with `SERVICE_SUSPENSION_DEPARTURE_OVERLAP`. The interval end is exclusive, but the Feb 5 00:00 departure is inside the interval. There are no indirect legs. The other 1,495 shipments are unaffected.

For each affected shipment, the independent verifier preserved the completed prefix and enumerated canonical directed services from the recovery point. All five selected paths pass independent service existence, directed continuity, periodic departure, transfer, event, cargo, individual capacity, cycle, hop, horizon, cost and deadline checks. All are classified `CHANGED_SERVICE_AND_PORT_SEQUENCE`; the paths below are feasible examples selected within the bounded DFS, not globally optimal routes.

| Shipment | Independent replacement port suffix | Independent final ETA | Original total | Revised total | Additional modeled cost |
|---|---|---|---|---:|---:|
| `SHIP-000005` | `NLRTM → NOOSL → DEHAM → SGSIN → CNSGH` | 2025-03-11 02:58:24.96Z | $3,283.22 | $4,490.26 | $1,207.04 |
| `SHIP-000320` | `NLRTM → FRLEH → SGSIN → JPYOK` | 2025-02-26 19:23:05.28Z | $3,399.60 | $3,907.28 | $507.68 |
| `SHIP-000417` | `NLRTM → FRLEH → SGSIN → JPYOK` | 2025-03-05 19:23:05.28Z | $7,515.64 | $8,531.00 | $1,015.36 |
| `SHIP-000637` | `NLRTM → NOOSL → DEHAM → SGSIN → JPYOK` | 2025-03-12 19:23:05.28Z | $7,194.68 | $9,608.76 | $2,414.08 |
| `SHIP-000930` | `NLRTM → DEHAM → SGSIN → CNSGH` | 2025-03-18 02:58:24.96Z | $6,573.04 | $7,753.40 | $1,180.36 |

The preliminary Phase 4 observations also report all five as `RECOVERED` and the remaining 1,495 as `UNCHANGED`. Phase 4 selected different feasible routes: `SHIP-000005` via `KRPUS → CNSGH`; `SHIP-000320`, `SHIP-000417` and `SHIP-000637` via `KRPUS → JPYOK`; and `SHIP-000930` on the original `NLRTM → SGSIN → CNSGH` service suffix after suspension expiry. The existing Phase 4 validator records a PASS for the selected route of each affected shipment (5/5), and independent checks of those observed routes also pass.

The explicitly nominated `SHIP-000005` route `NLRTM → KRPUS → CNSGH` was independently reconstructed as `SVC-d132cd5e4d7b5a` departing Jan 22 and arriving KRPUS Feb 17 06:19:17.76Z, followed by `SVC-eec16d7fc4cfb0` departing Feb 19 and arriving CNSGH Feb 21 02:03:33.12Z. It meets the Mar 21 deadline. Its full itinerary cost is $3,409.06 versus the $3,283.22 baseline, an additional modeled cost of $125.84. Both route legs and the preserved prefix pass the independent checks. The original remaining sequence begins with the Jan 22 `SVC-e3ab1786547e47` departure, which is directly blocked by the event; it cannot be replayed at its planned time. The nominated alternative changes both services and the intermediate port from SGSIN to KRPUS.

The comparison is `MISMATCH` because the independently enumerated reference routes and Phase 4 selected routes differ in service/port sequence, ETA and modeled cost. This is not an impact-cohort or recovery-status disagreement, and it does not establish that either route is globally optimal. The observed Phase 4 routes are independently feasible; the independent reference routes are also feasible and meet their deadlines. Phase 5.2e preserves both sets of evidence rather than treating one feasible path as the only correct route.

## D. SC-008 — delayed service and missed connection

Reference event: `SERVICE_DELAY`, service `SVC-35a7482f2af1d0`, `DEPARTURE_WINDOW`, `[2025-09-10T00:00:00Z, 2025-09-10T01:00:00Z)`, delay 3 hours. The complete scan found `SHIP-000026`, `SHIP-000424` and `SHIP-000741`; each has a direct `L2` delay impact and an indirect unresolved fixed connection on `L3`. The other 1,497 shipments are unaffected.

For `SHIP-000026`, the independently reconstructed planned inbound arrival is 2025-09-30 09:42:54.72Z. Adding the three-hour delay gives 12:42:54.72Z; adding the 12-hour minimum transfer gives readiness at 2025-10-01 00:42:54.72Z. The fixed downstream departure is 2025-10-01 00:00:00Z, so it is missed by 42 minutes 54.72 seconds. Before disruption, the transfer buffer was 2 hours 17 minutes 5.28 seconds. Its replacement is the next modeled `SVC-deda6d6189fe29` departure on Oct 8 at 00:00Z, arriving Oct 13 at 03:08:47.04Z. Its independently calculated full itinerary cost is $6,961.92, equal to the baseline, and it meets the shipment deadline.

For `SHIP-000424` and `SHIP-000741`, the fixed connection likewise has readiness at Oct 1 00:42:54.72Z versus departure at Oct 1 00:00Z. Their later `SVC-ef695c2f893320` sailing on Oct 8 arrives Oct 10 at 06:28:56.64Z. Full itinerary totals are $1,641.61 and $6,566.44, respectively, each equal to baseline. All three are `SAME_SERVICE_RESCHEDULING` of the downstream suffix after a genuinely missed connection; no service diversion is asserted. Phase 4 status, service sequence, port sequence, ETA and cost agree for all three.

## E. Independent versus observed execution

| Scenario | Independent affected set size | Phase 3 membership and cause/leg evidence | Independent recovery labels | Observed Phase 4 distribution | Comparison |
|---|---:|---|---|---|---|
| SC-001 | 7 | Agrees for all 7 direct departure overlaps | 7 feasible same-service reschedules | 7 `RECOVERED`, 1,493 `UNCHANGED` | `MATCH` |
| SC-004 | 5 | Agrees for all 5 direct suspension overlaps | 5 feasible changed-service/port candidate paths | 5 `RECOVERED`, 1,495 `UNCHANGED` | `MISMATCH`: routes, ETAs and costs differ; observed routes are independently feasible |
| SC-008 | 3 | Agrees for all 3 direct delays and indirect missed connections | 3 feasible later-sailing recoveries | 3 `RECOVERED`, 1,497 `UNCHANGED` | `MATCH` |

The comparison records preserve the observed Phase 3 summary, impact reasons/leg IDs, Phase 4 summary, per-affected-shipment reasons, recovery states and plans, validator rows, independently checked observed routes, ETAs, costs, route-sequence agreement and output hashes. A comparison result is not used to generate or revise any ground-truth label.

## F. Tests and reproducibility

Focused tests:

```powershell
python -m unittest tests.test_phase5_second_batch_ground_truth -v
```

The 11 focused tests cover complete cohorts, SC-001 rescheduling, SC-004 changed-route feasibility, route continuity, suspension overlap, minimum transfer, cargo/capacity, deadline, SC-008 missed-connection arithmetic/readiness, ground-truth immutability, repeated deterministic generation/comparison, mismatch detection, and the absence of Phase 3/4 imports or execution-output reads during generation.

Full project test command (the repository's tests are discovered from `tests/`):

```powershell
python -m unittest discover -s tests -v
```

The full suite passed. `python -m unittest discover -v` found no tests because this repository requires `-s tests`; `pytest` is not installed and no dependency was added.

Reproducible command sequence:

```powershell
python evaluation/verify_second_batch.py generate --verification-date 2026-11-15
python evaluation/verify_second_batch.py compare
```

Repeated runs with the same input date and execution files produced byte-identical reference and comparison files. Comparison left reference hashes unchanged. Ground-truth SHA-256:

| File | SHA-256 |
|---|---|
| `evaluation/ground_truth/SC-001.json` | `daacf7d5ceb71001eb2add04d869c70abd0e204b59269a7d2d82f0c21d160ca7` |
| `evaluation/ground_truth/SC-004.json` | `1558838119ae149d6d571e7c6acae45180e71993f6099ba739e76804f8300310` |
| `evaluation/ground_truth/SC-008.json` | `448ea89b129098bb2f21de79636c6f7005d45b35067ac89015e3dcbd829dcf79` |

Comparison SHA-256:

| File | SHA-256 |
|---|---|
| `evaluation/comparisons/SC-001.json` | `6d9f319fb034f4cdf4a5131f9c8d41fb0d04fac6116a2524140162bb6bf2db7c` |
| `evaluation/comparisons/SC-004.json` | `3d84222883c5e89c2643f6b4df7fdd7a51e308399f46fce4ce0d21be2b21badd` |
| `evaluation/comparisons/SC-008.json` | `b55a2c07329dfbf34ac7c3339fdabde1aebf6284a894aca0f431bc8255dc23f4` |

## G. Provenance

Dataset manifest SHA-256: `b2323fc9c0b3d251bb234346157770e66746eaeaed4c51063a3cd59b9759ff46`. Canonical file hashes, checked against the manifest before/after generation:

| Canonical file | SHA-256 |
|---|---|
| `ports.json` | `d6c5eb8baf1499e322283771acc208ccba2a6a1eefdb7bdc4b85467179f713ed` |
| `services.json` | `e39e0e5ec162e469a96c379ba8b0b52fcd29ba41960ccbc7dc9518455a727bc0` |
| `shipments.json` | `5b22521748fa2ee68e38bcad5464e58f0e326d42b29e47a8b4f38a3864524e95` |
| `route_plans.json` | `d2e2fef7184ab0b957369ff9c3dd442e6e052a0131d5901ad1400234564740cf` |

Recovery policy `modeled-periodic-v1` SHA-256: `93e8627763eb40e6872e437fa5c56ffd1b7e41607bbb52bc40c1e19757040ef0`. Verification script version `phase5-independent-second-batch-1.0.0`, SHA-256 `b216dbef9f804d32d59e0cb886383304a9084c2d3f8324adebde154329e3dd4d`. Source commit recorded in each label: `61fd9357c3723430c4d8a4cb36ed64d87b843f7b`.

| Scenario | Structured scenario SHA-256 | Notice SHA-256 |
|---|---|---|
| SC-001 | `d241a6ffe68f04d081e20c0e3b3a63c18dfe73325ce22dd491f7e86497d1faa9` | `3bac6de84ea89eb4c3594fba3c7ad0c3963625d9fcd2c65c3db602f31e3e81ab` |
| SC-004 | `4af112de3e82b2a0aff46f5af26b15f5ef3453d464e5a771c53b161e0e8f8bd7` | `d61d3525b1677b939482c04a9dfdb8e40e6860c10cb4716d62b49c66e4279c3b` |
| SC-008 | `600f348491469d086133dc6d86f8c33e06fbb39fec5dd41e9437a49d1bb040c6` | `5d0a61f06bedb91d7845cac2c201f39970222cfd106f12213d045772706b901d` |

Observed Phase 3/4 output hashes are stored per file in the three comparison records. Ground truth is stored separately from agent-facing notices; later agents must receive only `notice.txt`, never these reference labels.

## H. Limitations and final verification status

| Scenario | Status | Evidence supporting status |
|---|---|---|
| SC-001 | `VERIFIED` | Complete canonical departure scan; all seven same-service replacement suffixes independently scheduled, costed and checked against constraints and deadlines. It does not demonstrate alternative-route recovery. |
| SC-004 | `VERIFIED` | Complete suspension scan; five independently enumerated feasible changed-service/port itineraries meet deadlines. Phase 4 chose different routes, also independently feasible; no global-optimality claim is made. |
| SC-008 | `VERIFIED` | Complete direct/indirect cohort; all three transfer failures independently computed and later same-service replacement departures, ETAs, costs and deadlines checked. |

Schedules are synthetic model records, not real shipping timetables. Per-shipment modeled capacity is not evidence of real booking availability. The SC-004 paths are feasible candidates, not global optima; its route-selection difference from Phase 4 remains explicitly recorded in the comparison. No additional scenarios were produced.
