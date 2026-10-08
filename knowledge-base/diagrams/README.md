# Editable architecture diagrams

[market-eagle-architecture.drawio](market-eagle-architecture.drawio) is the editable, seven-page diagrams.net architecture workbook. Open it with [draw.io / diagrams.net](https://app.diagrams.net/) using **File → Open from → Device**, or with draw.io Desktop. The file uses uncompressed XML with native shapes and connectors, so labels, positions, and relationships remain editable.

| Page | View |
| --- | --- |
| 01 · Context | Researcher, product boundary, external providers |
| 02 · Containers | Collection and research data paths, with Temporal above as a control plane |
| 03 · Collection | Ordered catalog and price ingestion handoffs and their stored outputs |
| 04 · Research | Explorer and later agent over the same analytical boundary |
| 05 · Data ownership | Application entities versus Temporal-owned persistence |
| 06 · Deployment | First homelab placement; dashed backup path is deferred |
| 07 · Workflows | One backfill workflow with chunk activities, plus separate scheduled runs |

Blue identifies application services, teal identifies market facts and deterministic analytics, purple identifies Temporal/agent capabilities, and amber identifies external sources or unresolved external destinations. Dashed relationships indicate later or undecided paths. The diagram distinguishes accepted choices from proposals in page footers.

The workbook uses editable vector symbols beside selected labels: a person for the researcher, a monitor for user-facing workspaces, server racks for API/workers, a clock for Temporal workflows, clouds for external providers, and cylinders for PostgreSQL stores. These are explanatory icons, not additional components.

The Markdown knowledge base remains the source for decision detail. This workbook visualizes [system-architecture.md](../system-architecture.md), [data-model.md](../data-model.md), [workflows.md](../workflows.md), and [operations-and-load.md](../operations-and-load.md). After changing those decisions, update this workbook too.

Run `python build_architecture.py` in this directory to regenerate the native file, then `python render_preview.py` to validate structural IDs, edge endpoints, page bounds, connector/card intersections, and create rough layout previews. The preview renderer is approximate; diagrams.net is authoritative for final rendering.

Generation follows the official [draw.io AI XML guidance](https://www.drawio.com/docs/reference/diagram-generation/) and [C4 multi-page guidance](https://www.drawio.com/docs/diagram-types/c4-modelling/).
