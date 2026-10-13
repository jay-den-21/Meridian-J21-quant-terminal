# Backend Guidelines

Public products are independent: US ingestion under `database_system_cli`, CN
ingestion under `database_system_cli_cn`, and the read-only API App under
`database_app`. Read the component's AGENTS and PROJECT before editing.

## Pre-Development Checklist

- [Directory structure](directory-structure.md)
- [Quality](quality-guidelines.md)
- [Logging](logging-guidelines.md)
- [Provider endpoints](provider-endpoint-contracts.md), when changing provider code
- [Ingest jobs](ingest-job-contracts.md), when changing CLI/Menu/Job contracts
- [Asset/research contracts](asset-research-contracts.md), when changing storage/reads

## Quality Check

Run component-local offline tests and relevant lint checks. US schema edits also
require migration tests. Never use private sibling projects as test prerequisites.
