# Directory Structure

- `database_system_cli/src/fdp/`: US CLI, shared Jobs, EODHD adapter, storage, quality.
- `database_system_cli_cn/src/fdp_cn/`: CN CLI/Menu, catalog, direct Jobs, compatibility worker.
- CN `basis/`, `get_ph_data_from_ts/`, `get_rt_data_from_ts/`, `deal_data/`, and
  controller scripts retain their runtime ownership at the component root.
- `database_app/src/eodhd_codegen_app/`: local API App; no ingestion or schema writes.
- Component `tests/` contains offline tests. Optional CN operator tools belong in
  `tools/verification/`, not the product's top level.

US and CN packages do not import each other. Each uses its own environment and
`j21` entry point. Resolve paths relative to the owning module, not a developer's
home directory. Real configuration remains ignored; examples are credential-free.
