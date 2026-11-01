# Maritime Reroute Agent — Current Stage and Phase 2 Results

**Status:** Phase 2 dataset expansion is complete. The repository is ready to move into Phase 3: temporal maritime disruptions and deterministic recovery. Phase 3 implementation is not present in the current project results reviewed for this summary.

## Current project stage

The project has progressed from a small offline pilot to a reproducible, shipment-centered maritime dataset built on the AlMahri supply-chain graph. Phase 2 extended the frozen 1,000-shipment dataset to a combined 1,500-shipment benchmark while preserving the original base build.

The primary result is `data/builds/research_1500/` (seed 42). Its manifest reports successful validation and records the before/after hashes for the frozen base. A repeated seed-42 build is available in `data/builds/research_1500_repeat/` with matching canonical output hashes. `data/builds/research_1500_seed43/` is a separate seed-43 variation; its route-plan and shipment hashes differ, as expected.

## Phase 2 results

| Measure | Base | Added in Phase 2 | Combined |
|---|---:|---:|---:|
| Synthetic shipments | 1,000 | 500 | 1,500 |
| Initial route plans | 1,000 | 500 | 1,500 |
| Planned legs (seed 42) | 1,976 | 960 | 2,936 |
| Operational ports | 25 | 8 | 33 |
| Directed modeled services | 90 | 32 | 122 |
| Distinct source supplier edges | 500 | 100 | 600 |

- The 100 additional supplier edges are distinct, unused, directed relationships from the original 16,640-edge AlMahri source. The selection met the requested 50 US-bucket and 50 China-bucket quotas. Three US–China overlaps were assigned to the US bucket, so China membership including overlaps is 53.
- Each new source edge generated five synthetic shipments: 250 assigned to each quota bucket. The new sample includes 250 shipments involving the US and 265 involving China; these country-involvement totals include overlap.
- Eight UN/LOCODE gateways were added: USNYC, USLAX, USHOU, USTSA, CNNBG, CNSNZ, CNQIN, and CNTXG. The build remains below the 50-operational-port cap.
- The added 32 directed services are modeled connections. Their SeaRoute distances describe modeled marine paths; they do not establish the availability of a commercial liner service. The original 90 services were retained.
- All 89 unique new shipment origin–destination port pairs were reported reachable and had an alternative path. The combined seed-42 dataset manifest reports validation passed, and the Phase 2 report records two successful idempotent imports into an isolated Neo4j test instance.

## Reproducibility and validation evidence

The seed-42 Phase 2 build and its repeat have matching canonical hashes for ports, services, shipments, and route plans. The frozen `research_1000` base hashes matched before and after expansion. The seed-43 manifest also reports validation passed and demonstrates a different shipment/plan realization; it contains 2,946 total planned legs (970 additional), compared with 2,936 for the seed-42 build. These are different seeded outputs, not competing counts for the same build.

The existing Phase 2 report records 16 passing unit tests and successful standalone validation and Neo4j import checks. Those commands were not rerun while preparing this summary; these results are attributed to the report and build artifacts.

## Current limitations

- Supplier–customer links are inherited source relationships, not verified shipment records.
- Country gateways are modeled location proxies, not supplier or customer facilities.
- Route availability, schedules, capacity, cost, and service frequency are modeled. AIS references are historical movement evidence and do not verify a current commercial service.
- Port codes and coordinates do not establish container-terminal capability. Commercial schedules, actual prices, facility locations, and real cargo demand remain unverified.
- The dataset contains feasible initial plans, but this phase does not implement temporal disruption handling, recovery optimization, an LLM routing agent, or independent ground truth.

## Next phase

Phase 3 should use the canonical Phase 2 dataset to model time-windowed port and service disruptions, detect affected planned legs using their departure and arrival times, and produce deterministic recovery routes subject to shipment deadlines and the modeled network constraints. Evaluation should use an independent reference solver before any result is described as ground truth.

## Project references

- Detailed expansion methods, counts, checks, Neo4j queries, and data limitations: [`phase2_1500_shipments_report.md`](phase2_1500_shipments_report.md)
- Phase 2 network and 1,000-shipment base report: [`phase2_1000_shipments_report.md`](phase2_1000_shipments_report.md)
- Current next-phase instructions: [`CODEX_NEXT_PHASE_INSTRUCTIONS.md`](../CODEX_NEXT_PHASE_INSTRUCTIONS.md)
- Seed-42 combined build: [`research_1500`](../data/builds/research_1500/)
- Seed-43 variation manifest: [`research_1500_seed43/dataset_manifest.json`](../data/builds/research_1500_seed43/dataset_manifest.json)
