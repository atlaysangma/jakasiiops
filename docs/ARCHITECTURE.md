# Architecture

## Boundary

JAKASII Ops is the operational brain. It does not replace a shop's POS,
database, CCTV/NVR, boss app, staff app, or customer app.

```text
authorized databases/files/APIs     normalized camera events
               \                         /
                schema + evidence adapters
                           |
                onboarding and mappings
                           |
          structural awareness + relationship hypotheses
                           |
        exact SQLite state + explainable Markdown memory
                           |
            workflow engine and verification layer
                           |
               task outbox + action policy gate
                           |
                 existing boss/staff applications
```

## Canonical operational concepts

- stores, zones, godowns, shelves, counters and camera channels;
- products, SKUs, pack sizes, cartons, loose pieces and base units;
- staff, roles, shifts and approved badge identifiers;
- purchases, receiving, sales, counts, movements, returns, damage and expiry;
- observations, system records, confirmations, decisions, tasks and actions.

An ambiguous string such as `24*1` is normalized before use. For example:
`pack_size=24`, `cartons=1`, `loose_pieces=5`, `total_base_units=29`.

## Onboarding state

Before onboarding, the optional local bootstrapper can enumerate accessible
SQL Server user databases through one fixed `sys.databases` query and score
each database from schema-only operational role coverage. It independently
finds compatible camera collectors under a bounded approved filesystem root.
The selection contains connection coordinates and structural counts only; it
does not contain database rows, camera passwords, stream URLs, or discovered
credentials. Secret-bearing staff access is never auto-searched and still
requires an explicit authorized path or environment setting.

1. Inspect authorized schema metadata; request bounded representative samples
   only when an ambiguity cannot be resolved safely from metadata.
2. Normalize names and rank candidate canonical mappings.
3. Automatically accept exact authorized connector contracts and mappings
   proven by strong aggregate SQL shape checks.
4. Ask temporary questions for missing or uncertain important meanings.
5. Allow a human to correct a plausible but wrong proposal.
6. Write the approved store profile and readiness report.
7. Reopen questions when future schema/connectors change.

The legacy fixture intentionally catches an incorrect purchase mapping. This is
recorded as an onboarding correction rather than hidden.

The SQL Server adapter uses Windows authentication and fixed catalog `SELECT`
queries. Live lexical matches remain hypotheses. A narrow validator may promote
product identity and quantitative meanings only when structural-role confidence
and aggregate null/uniqueness/sign ratios cross conservative thresholds. It
stores counts and ratios, never sampled row values. Ambiguous pack conversion
or empty destination fields remain questions. A human can always confirm or
correct the result. The complete metadata catalog is retained locally without
business-row samples or credentials.

Composite onboarding can add an authorized local camera-system scope. JAKASII
discovers a safe channel registry, probes only the configured device port, and
inspects compatible collector SQLite schemas in read-only mode. It ignores DVR
user/password fields, RTSP URLs, snapshots, video and event-row content during
schema discovery. Because this connector owns its generated registry, it can
declare the exact camera-zone field through an authorized semantic contract.

An optional Firestore connector requests only the `role` field from the
authorized `userstaff` collection. It persists aggregate normalized role counts
and a virtual routing schema; it never persists UIDs, names, emails, photos,
attendance coordinates, service-account contents, or credential paths. The
connector similarly declares only its own aggregate `role` field as the
staff-routing semantic contract; that trust does not extend to unrelated
database fields.

## Store awareness

The awareness layer infers unverified roles such as product catalog, sale and
purchase headers/details, inventory stock, movements, damage/expiry, staff,
camera registry and camera events. It uses table names, column signatures,
primary keys, row counts, declared foreign keys and shared identifier
hypotheses. Report/configuration tables receive a confidence penalty.

Awareness is deliberately a hypothesis layer. It can guide the next inspection
or setup question, but it cannot authorize joins, business calculations or
official changes by itself. Confirmed mappings survive later rescans while
missing or changed fields reopen questions.

## Evidence and verification

Evidence kinds never collapse into each other:

- `observation`: camera/event/visual evidence;
- `system_record`: database, POS, purchase or app record;
- `human_confirmation`: role-authorized response;
- `manager_decision`: approval or operating decision.

The local verified-operation adapter maintains this separation when consuming
an existing collector: verified labels become `human_confirmation`, while SQL
facts become `system_record`. Personal fields, notes, amounts, product names,
and raw business document IDs are removed before ingestion.

The learned-schema SQL operational adapter is a later, explicitly authorized
read stage. It chooses purchase/sale header, line and product tables from the
awareness model; chooses joins from declared or high-confidence inferred
relationships; and chooses product, quantity and pack fields from canonical
mappings. The generated query is bounded and read-only. It excludes names,
people, prices and amounts, hashes source record IDs, and marks every result as
a candidate system fact when its mappings remain unconfirmed.

The situational snapshot never copies evidence payloads. It reports counts,
last-seen timestamps, open tasks by role, and temporal camera/system coverage.
A nearby camera observation is labelled `temporal_cooccurrence_only` and never
promoted to physical verification.

The operation-proof layer adds a stricter completion gate. For one event it
requires an exact linked `system_record`, a camera observation within the
configured time window, and a positive answer to an operational role's task.
Negative confirmation marks the bundle `disputed`; missing camera context or
confirmation keeps it incomplete. The artifact contains IDs, timestamps,
roles and claim boundaries, not evidence payloads. Even an
`evidence_complete` bundle states that camera timing did not identify the SKU
or quantity and that JAKASII did not write an official business record.

## Continuous store agent

The headless agent performs a bounded cycle: rescan when due, poll camera
observations, poll verified collector evidence, derive recent SQL facts, route
new events, write the operational snapshot and proof report, and persist cycle
health. Connector
failures are isolated by component and only the exception type is retained;
raw error text may contain private infrastructure details and is discarded.
External sources remain read-only. A repeated cycle is expected to import zero
records until a genuinely new source event appears.

The agent separately inspects camera runtime health. A discovered camera schema
does not mean the collector is live. Sanitized heartbeat age and event-store
age produce `running`, `stale_heartbeat`, `stale_event_store`, `not_running`,
or `unmonitored`; raw errors and paths are excluded. A non-live state creates
one deduplicated, approval-gated request to authorize/start the collector. It
cannot collect or embed the required secrets itself.

An optional `jakasii.camera_collector.v1` manifest lets an existing collector
declare a relative Python entry point, health file, and required environment
variable names. The generic launcher accepts no shell command or absolute/
escaping script path. It runs only after the matching action is `approved`,
requires the secrets to already exist in the process environment, and records
only launch state/PID—not environment values. This is a connector hand, not
permission for JAKASII to invent or retrieve credentials.

`configure-camera-access` provides the human boundary through a no-echo local
prompt. Required values are saved as Generic Credentials in the current
Windows user's Credential Manager under a store/variable namespace. On later
startup the agent hydrates missing required environment variables in memory,
returns only available/missing names, and passes values solely to the approved
collector child. Credential values are never part of settings, audit details,
Markdown, JSON artifacts, action records, or CLI output.

The first production cycle primes connector cursors by default. Existing
camera, verified-label and SQL identifiers are remembered without creating old
evidence, events or staff tasks. Historical processing is an explicit
`--backfill-existing` mode so installing the agent cannot flood a business with
stale work.

Operational events reference evidence IDs. Conflicts or missing steps create
verification tasks. Answering a task creates new confirmation evidence; it does
not rewrite the original observation.

## Authority

- Observe and local store memory may run automatically inside approved scope.
- External reversible work, system changes, and official records wait for an
  explicit approval.
- Credential extraction, audit disabling, and secret authority expansion are
  prohibited and cannot be approved.
- This repository currently creates and approves action requests but does not
  execute system-changing hands. Executors will be added connector by connector
  with the policy gate in front of them.

## Persistence

SQLite is the exact local source for evidence, events, mappings, questions,
tasks, actions, settings, and audit records. Markdown is the readable memory
layer. It never stores API credentials, raw biometrics, continuous CCTV, or
production customer/staff records.

## Reasoning

Deterministic inference is the offline baseline. Ollama is an optional local
reasoning adapter. OpenAI will later implement the same provider interface for
better schema reasoning, vision interpretation, summaries and tool selection.
No provider is permitted to turn an uncertain inference directly into an
official business record.
