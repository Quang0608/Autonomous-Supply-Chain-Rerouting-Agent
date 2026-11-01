# Maritime Reroute Agent

An offline research pipeline for extending AlMahri's supply-chain knowledge graph with a reproducible, shipment-centered maritime network. The current checked-in work covers the Phase 2 dataset pipeline; temporal disruption and recovery experiments are the next phase.

## Phase 2 result

The seed-42 Phase 2 build generated a combined benchmark with **1,500 synthetic shipments, 1,500 initial route plans, 33 operational ports, 122 modeled directed services, and 2,936 planned legs**. The expansion adds 500 shipments linked to 100 additional distinct AlMahri supplier-customer edges. The frozen 1,000-shipment base is preserved by the build procedure.

The generated records are intentionally not included in this repository. The repository contains the generation and validation code, schemas, provenance documentation, and sample CSV schemas. This keeps source data with unresolved redistribution terms and reproducible build outputs out of Git. The detailed counts, checks, and archived seed-42 hashes are in [`docs/phase2_1500_shipments_report.md`](docs/phase2_1500_shipments_report.md); a current stage summary is in [`docs/current_stage_summary_phase2.md`](docs/current_stage_summary_phase2.md).

These are synthetic logistics records, not observed shipments. AlMahri supplier edges are inherited source relationships; country gateways and service availability are modeled assumptions. AIS references indicate historical movements, not commercial liner schedules. See [data provenance](docs/data_provenance.md), [maritime sources](docs/maritime_data_sources.md), and [service assumptions](docs/maritime_service_model.md).

## Repository contents

- `src/maritime/`: source graph access, network logic, data models, and validators.
- `scripts/`: port/AIS ingestion, demand audits, service-network generation, shipment builds, validation, and optional Neo4j import.
- `tests/`: unit and pipeline tests.
- `config/`: modeled network parameters.
- `docs/`: data model, provenance, method, phase reports, and current stage summary.
- `data/reference/*.sample.csv`: schema examples only. Full reference catalogs, local inputs, intermediate data, and generated builds are excluded from Git.

## Inputs and prerequisites

Use Python 3.10 or later. The strict dataset pipeline uses NetworkX and SeaRoute:

```powershell
python -m pip install networkx searoute==1.6.0
```

The AlMahri input CSV is not bundled. Place an authorized copy at `../almahri-upstream/dataset/supplychainKG_clean.csv`, or pass the upstream directory with `--upstream` to scripts that support it. Do not redistribute that file unless its license permits it.

The UN/LOCODE port catalog is downloaded by the ingestion script from the official UNECE 2025-1 archive. The AIS source is optional for a modeled-only network, but the historical Phase 2 build used AIS movement references when constructing part of its modeled service network. The Zenodo source record did not declare a license; confirm rights before downloading or using it. Neither AIS nor SeaRoute establishes commercial service availability. Input and output licensing details are in `docs/data_provenance.md` and `docs/maritime_data_sources.md`.

## Rebuild the seed-42 Phase 2 dataset

Run from the repository root. The commands write local inputs and outputs under `data/`, which are ignored by Git.

```powershell
# Build the UN/LOCODE reference catalog for the seed-42 supplier sample.
python scripts/ingest_unlocode_ports.py --seed 42 --shipments 500

# Audit and assign country-level gateway assumptions to the same sample.
python scripts/audit_maritime_demand.py --pairs 500 --seed 42

# Optional: ingest historical AIS movements. Check the source license before use.
python scripts/ingest_ais_port_calls.py --download

# Build explicitly modeled services; SeaRoute supplies distances only.
python scripts/build_service_network.py --allow-modeled-services --seed 42

# Generate and validate the frozen 1,000-shipment base.
python scripts/build_logistics_dataset.py --mode strict --allow-modeled-services --shipments 1000 --seed 42 --out-dir data/builds/research_1000
python scripts/validate_logistics_dataset.py --directory data/builds/research_1000 --strict

# Refresh the reference catalog with US gateways for the expansion.
python scripts/ingest_unlocode_ports.py --seed 42 --shipments 500 --include-country USA

# Add 500 shipments on 100 new direct supplier edges, preserving the base.
python scripts/expand_maritime_dataset.py --base-build data/builds/research_1000 --additional-pairs 100 --additional-shipments 500 --max-operational-ports 50 --seed 42 --output data/builds/research_1500
python scripts/validate_logistics_dataset.py --directory data/builds/research_1500 --strict
```

The expansion requires 50 US-bucket and 50 China-bucket edges from the original directed supplier relationships and fails if the required quotas or route constraints cannot be met. Gateway locations are country-level assumptions, not verified company facilities. The 50-port argument is a maximum operational-port count.

Expected seed-42 combined counts: 1,500 shipments, 1,500 plans, 2,936 planned legs, 33 operational ports, 122 directed services, and 600 distinct supplier edges (500 base plus 100 new). Validation should report `passed`.

The report records canonical hashes for the archived seed-42 result. Regenerated hashes can differ when the source archive, source CSV, retrieval metadata, dependencies, or platform differ. Compare exact hashes only when the same input snapshots and generator environment are used; counts and validation are the primary cross-environment checks.

## Optional Neo4j import

The canonical importer uses stable IDs and `MERGE`; it does not clear the database. Use an isolated development database and review its connection settings before import. After installing the Neo4j Python driver and setting credentials, run:

```powershell
python -m pip install neo4j
$env:NEO4J_PASSWORD = "your-local-development-password"
docker compose up -d
python scripts/import_neo4j.py --canonical --data-dir data/builds/research_1500
```

The Compose service exposes the local Neo4j browser on port 7474 and Bolt on 7687. Do not use the example Compose default password for a shared or production database. Importer behavior and example Cypher queries are documented in [`docs/phase2_1500_shipments_report.md`](docs/phase2_1500_shipments_report.md).

## Limitations and next phase

The model does not represent confirmed physical facilities, booked liner services, actual schedules, market prices, or allocated shared capacity. The current phase creates feasible initial route plans; it does not implement time-windowed disruptions, recovery optimization, an LLM routing agent, or independent ground truth. Phase 3 should add temporal disruption detection and deterministic recovery over the canonical dataset, then compare against an independent reference solver.
