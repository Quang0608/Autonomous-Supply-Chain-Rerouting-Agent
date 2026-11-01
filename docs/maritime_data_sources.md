# Maritime data sources and boundaries

## Ports

The port catalog is filtered from UNECE UN/LOCODE production release 2025-1, downloaded from the [official publication archive](https://unlocode.unece.org/publications/). Port identifiers are the published ISO alpha-2 country code plus three-character location code. Published degree/minute coordinates are normalized to decimal degrees without geographic interpolation. Archive checksum, date, source URL, release and stated CC BY 4.0 attribution are preserved in `data/reference/ports_ingestion_manifest.json` and on each port row. UN/LOCODE's maritime function does not prove container-terminal capacity. Port gateways are simulation assumptions, not supplier/customer facility locations.

## AIS evidence

The optional source is Duvallet et al., [Date-Ship-Port triplet data based on AIS data](https://zenodo.org/records/10783698), v1 (2024), DOI 10.5281/zenodo.10783698. Zenodo describes date/ship/port associations and names AISHUB, NOAA MarineCadastre and DMA.DK as underlying sources. Its record did not expose a license value at retrieval; verify rights before redistributing source or derived data. The parser records this gap. Names are mapped only by unique exact normalized name to a UN/LOCODE name. Ambiguous and unmatched records are excluded. AIS links represent historical general-vessel movement, never a liner schedule, container service or bookable route.

## Maritime distance

SeaRoute 1.6.0 ([Eurostat project](https://github.com/eurostat/searoute)) estimates navigable maritime path length from port coordinates. Its paths do not prove commercial service availability. Current service definitions are explicitly modeled and use those paths for distance only. No schedule, capacity or cost is sourced from AIS.
