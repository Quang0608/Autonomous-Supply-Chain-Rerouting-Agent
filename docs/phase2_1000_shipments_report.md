# Phase 2 completion report: maritime network and 1,000 shipments

Generated with seed 42 from the existing AlMahri source graph, UNECE UN/LOCODE 2025-1, and SeaRoute 1.6.0 distances. Counts below are read from the build manifest and ingestion reports, not estimates.

## Counts and coverage

| Measure | Result |
|---|---:|
| Original AlMahri direct supplier edges | 16,640 |
| Eligible international direct edges before 500-pair selection | 3,294 |
| Selected candidate / eligible port assignments | 500 / 500 (0 ineligible) |
| Selected manufacturer-network-connected edges | 426 / 500 |
| UN/LOCODE reference rows with coordinates before dedupe | 6,788 |
| Unique verified UN/LOCODE references retained | 6,775 (13 duplicate IDs removed) |
| Countries covered by selected demand | 25 |
| Operational endpoint ports | 25 |
| Additional transshipment-only ports | 0 (configured hubs coincide with endpoint gateways) |
| AIS rows / retained mapped rows / aggregated movements | 645,581 / 54,534 / 4,074 |
| Modeled services / AIS-backed modeled corridors | 90 / 62 |
| Modeled-only services | 28 |
| Demand port pairs connected / with alternative path | 159 / 143 |
| Synthetic shipments / unique source edges | 1,000 / 500 |
| Initial route plans / planned legs | 1,000 / 1,976 |
| Initial plans meeting all validation constraints | 1,000 (100%) |

Each supplier edge supplies two shipments maximum. Top-10-edge share is 2%; median and maximum shipments per represented edge are both 2. Cargo demand distribution is TEU 1: 240, 2: 246, 3: 263, 4: 251; all cargo is synthetic general container. Route leg count distribution is 1 leg: 252, 2 legs: 520, 3 legs: 228. Priority counts: HIGH 317, LOW 366, STANDARD 317. All shipments meet their generated hard deadlines.

Manufacturer ancestry overlaps: BMW 223 represented direct edges / 446 shipments; Mercedes-Benz 372 / 744; Tesla 233 / 466. These counts overlap when an edge is in more than one target's upstream graph. The AlMahri extract names `BMW Brilliance Automotive Ltd` as its BMW target, which is included in the BMW ancestry calculation.

## Evidence and assumptions

- Ports come from UNECE UN/LOCODE release 2025-1. 13 duplicate location-code rows were deterministically removed. A further 5,767 maritime-function entries in the full source lacked coordinates and were excluded. Port metadata includes the source URL, release, access date, and license declaration; see `data/reference/ports_ingestion_manifest.json`.
- AIS archive: Duvallet et al., Zenodo v1 / DOI `10.5281/zenodo.10783698`, downloaded as a 32,453,859-byte archive; SHA-256 `6d5f1273ba98024ea485dc639f8a1c1ea425b83bb95e01d725cb54a8c4aa5ec0`. Exact unique normalized port names were mapped; unmatched (527,019), ambiguous (424), invalid-duration (27,668), and over-30-day (35,936) rows were excluded. Only 62 aggregated AIS movements intersected operational corridors. Zenodo's record did not declare a license, so this is an unresolved redistribution rights issue.
- AIS movements are not service schedules. The 62 `MODELED_SERVICE_FROM_AIS` connections are separate modeled services with a movement reference. All 90 services use SeaRoute distance; speed, service frequency, handling, transfer, simulated capacity and cost are model parameters in `config/maritime_network.json`.
- Country gateways are modeled proxies, not supplier/customer facilities. UN/LOCODE maritime-function records do not guarantee container capability. No true manufacturing locations, bookable liner routes, actual schedules, quotations, or cargo contracts are known.

## Reproducibility and checks

Commands used:

```powershell
python -m unittest discover -s tests -v
python scripts/bootstrap_pilot.py --shipments 20 --seed 42
python scripts/audit_maritime_demand.py --pairs 500 --seed 42
python scripts/ingest_ais_port_calls.py --input <downloaded-triplet_2020.zip>
python scripts/build_service_network.py --allow-modeled-services --seed 42
python scripts/build_logistics_dataset.py --mode strict --allow-modeled-services --shipments 20 --seed 42 --out-dir data/builds/pilot_20
python scripts/validate_logistics_dataset.py --directory data/builds/pilot_20 --strict
python scripts/build_logistics_dataset.py --mode strict --allow-modeled-services --shipments 1000 --seed 42 --out-dir data/builds/research_1000
python scripts/validate_logistics_dataset.py --directory data/builds/research_1000 --strict
```

All 12 unit tests passed. Both generated datasets passed standalone validation. Identical seed/input reruns produced identical SHA-256 hashes for all four canonical JSON files. 1,000-shipment hashes: ports `f00fa3e61752e0060e5e21ff4bc2928888550f987a2100fd65af4b1ee82f7f1a`; services `d8c7e776c7d912b72795c023109ea9cad3a3cce6aa347deef22ec53ace0f3fec`; shipments `99f5130f70db60903a10798a3dc16735f20aa826167a80fabf44120acaf77f59`; route plans `13aeb419c387d905f2dd03a2c0e3f86a849054058106572d6eccce983c6ede58`.

Neo4j was reachable. Canonical import was executed twice with `MERGE`; both passes reported 16,640 `suppliesTo` edges, 1,000 shipments, 1,000 plans, 1,976 planned legs, and all 1,000 shipments connected through the exact direct supplier edge. The same edge count on both runs verifies the importer did not duplicate or remove supplier relationships.

## Readiness

The 1,000 initial itineraries are structurally valid and reproducible for future temporal-disruption engineering. They are a hybrid synthetic benchmark, not evidence of commercially available transport. The AIS license, container-port capability of gateways, facility locations, commercial schedules/capacity/prices, and real shipment demand remain unresolved. This phase deliberately does not implement the LLM agent, temporal disruption engine, dashboard, or independent Ground Truth.
