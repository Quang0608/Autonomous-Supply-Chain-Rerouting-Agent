# Phase 2 expansion report: 1,500 shipments / 33 operational ports

Built from frozen `data/builds/research_1000/` with seed 42. The expansion process hashes the frozen input files before and after, and copies the old shipment, plan, service, and port records as the prefix of the combined arrays.

## Supplier demand and selection

AlMahri contains 16,640 unique normalized direct supplier edges. The frozen base uses 500. Among unused cross-border edges, the audit found 2,168 US-involving, 1,544 China-involving, and 209 US-China overlaps. Restricting both ends to existing or explicitly added gateway coverage yielded 1,781 US candidates and 817 exclusive China candidates. The selection produced 50 US quota edges and 50 China quota edges, with three US-China edges assigned to the US bucket and excluded from the China bucket. Independent membership counts are 50 US and 53 China. All 100 are unique unused original directed edges; 50 link to the monitored manufacturer network. No quota shortfall or rejected selected edge occurred.

The base represents 500 direct edges; the expansion adds 100, resulting in 600 distinct supplier edges across 1,500 shipments. Each new edge generates exactly five shipments. There are 250 shipments in each assigned bucket; 250 new shipments involve the US and 265 involve China (the additional 15 are US-China overlap membership). Selected demand covers 25 ISO alpha-2 countries. Country-to-port values remain modeled gateways rather than company facilities.

## Ports and services

The existing 25 operational ports were retained. Eight verified UN/LOCODE records were added as operational gateways: USNYC, USLAX, USHOU, USTSA, CNNBG, CNSNZ, CNQIN, and CNTXG. This gives 33 operational ports, below the 50-port limit. No additional transshipment-only or other-country ports were needed. The UN/LOCODE maritime function does not prove container-terminal capability.

The canonical reference catalog contains 8,324 coordinate-bearing port records from 26 represented countries. It was derived from the official UNECE UN/LOCODE 2025-1 files, retrieved 2026-10-31; each CSV record carries its source URL, version, retrieval date, license, and source part. The ingestion manifest records the archive SHA-256, duplicate removal count, countries, and port-coordinate coverage. License metadata is `CC BY 4.0 (UN/CEFACT standards; confirm source-specific terms before redistribution)`. The 2025-1 source archive hash is `ad409fc7149b10f98d61190c34d9daf78b78bb8b31464cc66de1a89d09b01b5d`.

The 90 original directed services and their attributes were retained. Thirty-two directed modeled services were added (each new US/China gateway connected in both directions to two existing hubs), for 122 total. All added distances use SeaRoute 1.6.0; service availability, schedules, speeds, capacity, and costs are modeled. The previous 62 AIS-referenced service corridors remain unchanged; no new AIS movement was promoted to a service. The modeled graph has one weakly connected component. All 89 unique new shipment endpoint pairs are reachable; alternative-route coverage is reported in `data/processed/expansion_1500_service_network_report.json`.

## Dataset results

| Measure | Count |
|---|---:|
| Base / new / combined shipments | 1,000 / 500 / 1,500 |
| Base / new / combined route plans | 1,000 / 500 / 1,500 |
| Base / new / combined planned legs | 1,976 / 960 / 2,936 |
| Base / new / combined operational ports | 25 / 8 / 33 |
| Base / new / combined directed services | 90 / 32 / 122 |
| Distinct base / new / combined direct supplier edges | 500 / 100 / 600 |
| New route legs | 1 leg: 40; 2 legs: 460 |
| Combined valid initial plans | 1,500 / 1,500 |

The 1,000 frozen base files are unchanged. Their canonical hashes remain: ports `f00fa3e61752e0060e5e21ff4bc2928888550f987a2100fd65af4b1ee82f7f1a`; services `d8c7e776c7d912b72795c023109ea9cad3a3cce6aa347deef22ec53ace0f3fec`; shipments `99f5130f70db60903a10798a3dc16735f20aa826167a80fabf44120acaf77f59`; plans `13aeb419c387d905f2dd03a2c0e3f86a849054058106572d6eccce983c6ede58`.

For the combined build, canonical SHA-256: ports `d6c5eb8baf1499e322283771acc208ccba2a6a1eefdb7bdc4b85467179f713ed`; services `e39e0e5ec162e469a96c379ba8b0b52fcd29ba41960ccbc7dc9518455a727bc0`; shipments `5b22521748fa2ee68e38bcad5464e58f0e326d42b29e47a8b4f38a3864524e95`; plans `d2e2fef7184ab0b957369ff9c3dd442e6e052a0131d5901ad1400234564740cf`.

## Commands and checks

```powershell
python -m unittest discover -s tests -v
python scripts/ingest_unlocode_ports.py --seed 42 --shipments 500 --include-country USA
python scripts/expand_maritime_dataset.py --base-build data/builds/research_1000 --additional-pairs 100 --additional-shipments 500 --max-operational-ports 50 --seed 42 --output data/builds/research_1500
python scripts/validate_logistics_dataset.py --directory data/builds/research_1500 --strict
python scripts/import_neo4j.py --canonical --data-dir data/builds/research_1500
```

All 16 tests passed. The standalone validator reports 6,779 reference port rows, 122 services, 1,500 shipments, 1,500 plans, and 2,936 legs with no validation errors. A repeat with seed 42 produced identical canonical hashes. A seed 43 build produced a different shipment hash and 2,946 planned legs, demonstrating seeded variation.

An isolated Neo4j 5.26 test container (`maritime-phase2-expansion-neo4j-test`, host ports 7475/7688, volume `maritime-phase2-expansion-neo4j-data`) imported the combined build twice. Both runs reported: 16,640 `suppliesTo` edges; 1,500 shipments (1,000 base + 500 expansion); 1,500 plans; 2,936 planned legs; 33 operational ports; 122 imported services; and 1,500 shipments linked to their original direct `suppliesTo` edge.

Useful Neo4j queries (labels and relationships match `scripts/import_neo4j.py`):

```cypher
// Operational ports only (the Port catalog also contains non-operational reference rows)
MATCH (:ServiceLeg)-[:DEPARTS_FROM]->(p:Port)
RETURN DISTINCT p.id AS unlocode, p.name, p.country, p.country_code ORDER BY p.country_code, p.id;
```

```cypher
// Shipment endpoints whose port is in the US or China
MATCH (s:Shipment)-[:ORIGIN_PORT]->(o:Port), (s)-[:DESTINATION_PORT]->(d:Port)
WHERE o.country_code IN ['US','CN'] OR d.country_code IN ['US','CN']
RETURN o.country_code, d.country_code, count(DISTINCT s) AS shipments ORDER BY o.country_code, d.country_code;
```

```cypher
// Supplier-company source-country distribution (country is source company metadata)
MATCH (supplier:Company)-[:ORIGINATES]->(s:Shipment)-[:DELIVERED_TO]->(customer:Company)
MATCH (supplier)-[:locatedIn]->(country:Country)
RETURN country.name, count(DISTINCT s) AS shipments ORDER BY shipments DESC;
```

```cypher
// Orphans and direct-source lineage integrity
MATCH (s:Shipment)
OPTIONAL MATCH (supplier:Company)-[:ORIGINATES]->(s)
OPTIONAL MATCH (s)-[:DELIVERED_TO]->(customer:Company)
OPTIONAL MATCH (supplier)-[edge:suppliesTo]->(customer)
WITH s, supplier, customer, edge WHERE supplier IS NULL OR customer IS NULL OR edge IS NULL
RETURN s.id AS orphan_or_unlinked_shipment;
```

## Limitations

AlMahri relationships are inherited evidence, not historical shipments. US and China gateways are modeled location assumptions. Added corridors are modeled transport services whose sea distances use SeaRoute; neither UN/LOCODE maritime function nor SeaRoute establishes container capability or commercial service availability. AIS evidence/license limitations remain those documented in `docs/maritime_data_sources.md`. The model does not reserve shared capacity or provide verified schedules or prices. This work adds no Phase 3 disruptions or LLM agent.
