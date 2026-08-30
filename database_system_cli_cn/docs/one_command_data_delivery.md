# J21 One-Command Data Delivery And Cloud Contract

Updated: 2026-08-30

## Decision

The public bootstrap command installs an immutable release built from a
cleaned database. It does not call Tushare, EODHD, a preserved getter, or any
other provider API.

```bash
j21 init cn --years 5
j21 init us --years 5
j21 init all --years 5
```

`all` means CN plus US market products. It never means “execute every
provider getter”. Provider access is an advanced operator workflow:

```bash
j21 source cn list --eligible
j21 source cn run --endpoint daily --from 2026-08-01 --to 2026-08-30
j21 source cn run --all-eligible --from 2026-08-01 --to 2026-08-30
j21 source cn index-pit --phase all
```

This contract was aligned with Codex task
`019f4a91-3996-79f3-9eb2-8befd30c1142`. It is the target public design; the
current project-local provider commands remain available while the
repository-level launcher and data-bundle installer are implemented.

## Product Boundary

Only one repository-level package may ultimately register the public `j21`
executable. Today both Python projects register that name, which is an
installation conflict and must not become the routing mechanism.

| Owner | Responsibility |
| --- | --- |
| repository `j21` launcher | route `cn`, `us`, and `all`; aggregate child run status |
| `database_system_cli_cn` | Tushare/A-share rules, `a_share`, `system_cn`, Shenwan and index PIT |
| `database_system_cli` | US providers/rules, `us_share`, `system`, ticker identity lifecycle |
| shared core contract | Job/result/progress fields, bundle manifest and task fingerprints |

The market products must not import each other, write each other's schemas,
or share provider-specific business logic. A cross-market run links child
runs by identifier:

```text
orchestration_run_id
  -> cn_child_run_id
  -> us_child_run_id
```

## User Contract

The minimum public surface is:

```bash
j21 init <cn|us|all> --years N [--profile core|research|full]
j21 update <cn|us|all>
j21 status [--run-id RUN_ID]
j21 verify <cn|us|all>
j21 menu
```

- `research` is the default profile.
- `--years N` is resolved from the release's last complete market date, not
  the client's wall clock.
- Reference/dimension tables are installed completely even when facts are
  limited to N years.
- PIT data includes source intervals that began before the requested window
  but remained effective inside it.
- An identical unfinished task fingerprint resumes automatically.
- `--new-run` creates a new execution record, but natural keys still prevent
  duplicated published data.
- A non-empty target database is rejected by default. Replacement requires an
  explicit destructive option and confirmation.
- No provider token or API key is required or read by `init`.

## J21 Data Bundle V1

A release is immutable and independently verifiable. Do not distribute one
multi-gigabyte opaque SQL dump or expose the production MySQL server.

```text
releases/<release_id>/
├── manifest.json
├── manifest.sig
├── contracts/
│   └── datasets.json
├── schema/
│   └── <dataset>.sql
├── data/
│   └── dataset=<key>/year=<yyyy>/part-*.tsv.gz
└── audit/
    ├── quality-summary.json
    └── lineage.jsonl
```

The first MySQL installer uses UTF-8 `tsv.gz` chunks (`\N` means SQL NULL)
because each chunk can be downloaded, verified and loaded independently.
`manifest.json` declares each file's format, so future Parquet releases do not
change the Job or checkpoint contract.

### Manifest identity

```text
package_format_version
package_id
release_id
release_type                 # snapshot | delta
base_release_id              # required for delta
market                       # cn | us
profile                      # core | research | full
created_at_utc
as_of_date
schema_version
data_contract_version
minimum_app_version
mysql_min_version
license_policy_id
source_snapshot_id           # backup/replica snapshot identity, never a password
datasets[]
```

### Dataset contract

```text
dataset_key
target_schema
table_name
asset_type
is_pit
natural_key[]
partition_key[]
scope_policy                 # full_reference | date_window | pit_boundary_complete
date_from
date_to
row_count
duplicate_key_count
quality_status
ddl_path
ddl_sha256
schema_fingerprint
files[]
```

Each file declares:

```text
part_id
partition
path
format
compression
sha256
compressed_bytes
uncompressed_bytes
rows
min_key
max_key
min_date
max_date
```

The manifest has a detached Ed25519 signature. SHA-256 alone is insufficient,
because an attacker could replace both a file and an unsigned manifest.

PIT releases preserve real `effective_from`, `effective_to`, and/or
`as_of_date` fields from the dataset contract. Monthly index weights remain
monthly snapshots; the delivery layer never expands them into invented daily
rows.

## Install State Machine And Resume

```text
resolve channel/release
-> validate application, schema and license policy
-> create or resume task fingerprint
-> download one chunk with range resume
-> verify manifest signature and chunk SHA-256
-> create staging schema/table
-> import chunk and commit its checkpoint
-> validate counts, natural keys, PIT bounds and quality rules
-> atomically publish
-> record installed release
```

The durable unit identity is:

```text
release_id + dataset_key + partition + sha256
```

Completed identical units become `reused`. A delta whose `base_release_id`
does not equal the locally installed release becomes `held`; it is never
silently skipped or applied to the wrong base.

The parent run can reuse `system_cn.ingestion_task_run` with
`job_name=dataset_install`, `source=j21_delivery`, `api_calls=0`, and a
checkpoint containing:

```text
manifest_sha256
requested_market/profile/years
resolved_from/resolved_to
phase                         # download|verify|stage|import|validate|publish|complete
staging_schema
parts_total/parts_completed
bytes_downloaded
rows_loaded
validation_summary
publish_state
```

A separate part ledger records status, hashes, expected/loaded rows and retry
counts for each chunk. Importing a chunk and marking it complete use the same
short MySQL transaction. Publish DDL may implicitly commit, so recovery also
compares the published table fingerprint with the manifest before deciding
whether to retry a rename.

Provider ingestion and bundle installation never share one run. A global
market-writer lock prevents the direct Job, compatibility getters, PIT
publisher and installer from writing `a_share` concurrently.

## MySQL Bootstrap

The installer first connects to MySQL's administrative database, creates
`a_share` and `system_cn` when permitted, then reconnects to the target. This
avoids the current failure mode where a URL naming a not-yet-created
`a_share` database cannot establish the first connection.

Every table is created from release-owned DDL captured from the clean release
database. The catalog alone is not a complete DDL source for all legacy
tables. DDL hashes and schema fingerprints are therefore release artifacts,
not guesses generated from partial endpoint metadata.

## Unified Run States

```text
Run:  planned | running | success | partial_failed | held | failed | cancelled
Unit: pending | running | success | reused | held | failed | cancelled
Data: pending | published | held | quarantined
Dry run: dry_run
```

Shared result fields are:

```text
contract_version, job_key, job_version, run_id, parent_run_id,
task_fingerprint, market, source_mode, source, dataset_keys, scope,
parameters, parameter_sources, phase, status, checkpoint,
rows_fetched, rows_matched, rows_inserted, rows_rejected, rows_unmatched,
api_calls, work_units_total, work_units_completed, work_units_failed,
failures, metrics, error_message
```

CLI, Menu, Daily automation, Skill and MCP adapters call the same Job. Menu
must not shell out to CLI. MCP stays read-only unless write capability and
confirmation are explicitly enabled.

## Licensing Gate

The current Tushare service terms provide a personal, non-transferable data
license. Cleaning data does not automatically create redistribution rights.
Therefore:

- a public J21 bundle may contain only data for which J21 has explicit
  redistribution rights;
- before those rights exist, the public channel offers a synthetic or
  redistributable demo bundle;
- a private/BYO channel may install data under the user's own applicable
  provider license and entitlement;
- release authorization, download audit and `license_policy_id` are mandatory
  before any commercial data channel is enabled.

This gate limits what may be published; it does not change the installer,
manifest, signature or checkpoint architecture.

Provider evidence for this boundary:

- [Tushare points and independent-entitlement table](https://tushare.pro/document/1?doc_id=290)
  separates standard-point APIs from minute, US daily and news permissions.
- [Tushare data service agreement](https://tushare.pro/document/1?doc_id=405)
  describes the current personal service license as non-transferable and
  non-commercial. Redistribution therefore requires a separate written grant,
  not an inference from data cleaning.

## Minimal Cloud Path

1. Keep MySQL as the current query and task-ledger database.
2. Build releases from a consistent read replica or database backup snapshot,
   not a long transaction on the writer.
3. Store immutable bundles in S3, R2 or MinIO with versioning, encryption,
   lifecycle policy and signed URLs.
4. Store the signing private key and database secrets in KMS/Secret Manager;
   clients contain only the verification public key.
5. Move serving/control tables to managed MySQL over TLS.
6. Run the same resumable Job in stateless workers. Clients never receive the
   production database credentials and cloud workers never connect directly
   to a user's local database.
7. Add a cloud query service or Parquet-first historical tier only after
   measured demand. Kafka, Kubernetes, a lakehouse rewrite and dual writes are
   intentionally outside the first cloud release.

## Implementation Order

1. Finish the shared 10,000-point endpoint catalog and CLI/Menu execution.
2. Introduce one repository-level `j21` launcher and uniquely named internal
   market entry points without sibling imports.
3. Add a closed manifest parser/signature verifier and dry-run planner.
4. Add resumable download and the part ledger.
5. Add staging import, validation and publish recovery.
6. Build a demo release and pass corruption/disconnect/resume tests.
7. Enable an external data channel only after redistribution rights and
   entitlement enforcement are documented.
