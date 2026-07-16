# JAKASII Ops

JAKASII Ops is a headless, self-onboarding operational brain for physical
businesses. **JAKASII means “left hand” in Garo**: an intelligent second hand
for an owner.

It discovers an authorized store schema, proposes a common operational model,
asks a human only about unsafe ambiguities, writes a store-owned memory, and
routes operational exceptions to the right role. It keeps camera observations,
database records, human confirmations, and manager decisions separate instead
of pretending that every AI inference is a business fact.

This repository is the new OpenAI Build Week 2026 implementation. The SMM POS,
camera collector, boss app, staff app, and customer app existed before the
event and are **not** presented as hackathon work. They will connect through
the contracts and JSON API in this repository.

**Hackathon track:** Work & Productivity  
**Supported platforms:** Windows, Linux, and macOS with Python 3.11+  
**License:** MIT

## What works now

- Two-schema autonomous onboarding demonstration: one deliberately messy
  legacy SQL-style export and one clean JSON-style store.
- Mapping proposals, temporary clarification questions, human corrections,
  verified store profiles, and a visible readiness report.
- Canonical, safety-first workflows for receiving, purchase normalization,
  godown-to-shelf movement, stock counts, damage, expiry, attendance, sales,
  and returns.
- Role-routed verification tasks for DEO, godown staff, shelf staff, and
  managers.
- Separate evidence records for camera observations, system facts, human
  confirmations, and manager decisions.
- SQLite exact-state/audit storage and an Obsidian-compatible Markdown memory
  for every store.
- A policy gate that allows local memory, holds external/system/official
  changes for approval, and rejects prohibited actions.
- A localhost-only headless JSON API. No dashboard is included.
- Offline deterministic reasoning plus an optional local Ollama adapter.
- Live SQL Server catalog discovery with table sizes, declared relationships,
  inferred operational roles, and unverified join hypotheses.
- Authorized local camera-system discovery: channel registry, device-port
  reachability, and existing collector SQLite schemas without DVR credentials.
- Deduplicated ingestion of safe camera-event metadata as observations; frames,
  snapshot paths, RTSP URLs, and official stock changes remain outside this step.
- Optional Firestore staff-role discovery that requests only the `role` field and
  stores aggregate counts—never UIDs, names, emails, photos, or attendance locations.
- Privacy-minimized ingestion of collector human labels and SQL facts as distinct
  human-confirmation and system-record evidence.
- A learned-schema SQL cycle that derives recent purchase/sale line queries from
  awareness roles, inferred joins, and mappings—without embedded store table names.
- An operational snapshot that reports source freshness, evidence coverage,
  uncorroborated records, and open work by role without copying evidence payloads.
- A continuous headless store agent that periodically rescans schemas, polls all
  authorized evidence sources, runs workflows, refreshes memory, and isolates
  connector failures so one unavailable system does not stop the store loop.

## Quick start

Python 3.11 or newer is required.

```powershell
cd C:\Users\atlay\jakasiiops
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
jakasii-ops --data-root data demo --fixture legacy_mart
jakasii-ops --data-root data demo --fixture modern_shop
```

Install the optional Firestore adapter only on a machine authorized to inspect
staff-role metadata:

```powershell
python -m pip install -e ".[firestore]"
```

The legacy demo intentionally proposes the wrong purchase-quantity column
(`BillQty`). The human corrects it to the receiving quantity field, and that
correction becomes verified store memory. This tests failure recovery instead
of presenting a hardcoded perfect mapping.

## Run as a headless service

```powershell
jakasii-ops --data-root data serve --host 127.0.0.1 --port 8765
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

Start onboarding from synthetic/exported schema metadata:

```powershell
$body = @{ schema_path = "C:\Users\atlay\jakasiiops\fixtures\legacy_mart\schema.json" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/onboarding -ContentType application/json -Body $body
```

Useful read endpoints:

```text
GET /stores/{store_id}/status
GET /stores/{store_id}/readiness
GET /stores/{store_id}/questions
GET /stores/{store_id}/tasks
GET /stores/{store_id}/actions
GET /stores/{store_id}/schema
GET /stores/{store_id}/awareness
GET /stores/{store_id}/snapshot
GET /stores/{store_id}/agent
GET /stores/{store_id}/memory
GET /stores/{store_id}/audit
```

Write endpoints are listed in [docs/API.md](docs/API.md). The server binds to
localhost by default and currently has no network authentication; do not expose
it outside a trusted machine.

## Reasoning providers

The core works without an API key:

```powershell
jakasii-ops --provider deterministic --data-root data demo
```

If Ollama is installed, ambiguous mapping proposals and summaries can use a
local model:

```powershell
jakasii-ops --provider ollama --model qwen2.5:7b --data-root data demo
```

OpenAI is intentionally not wired yet because Codex promotional credits and
OpenAI API billing are separate. A future OpenAI provider will implement the
same `ReasoningProvider` boundary after a usable API credential is deliberately
configured. No API secret belongs in source control or store memory.

## Discover a live SQL Server schema

For a local main-server installation, JAKASII can first discover both connection
scopes without receiving a database name or camera folder:

```powershell
jakasii-ops --data-root data bootstrap-store `
  --store-id your_store `
  --store-name "Your Store"

jakasii-ops --data-root C:\JakasiiData auto-watch-store `
  --store-id your_store `
  --store-name "Your Store"
```

The bounded bootstrap checks accessible local SQL Server instances, enumerates
user databases with a fixed metadata query, ranks their generic operational
roles, and scans approved local roots for compatible camera-channel JSON. By
default the approved root is the current user's home folder, with depth/file
limits and exclusions for AppData, Git, virtual environments, and
`node_modules`. It never returns camera passwords, RTSP URLs, business rows, or
credential contents. A staff credential still requires explicit authorization
through the option or environment because JAKASII must not search for secrets.

On a Windows host with `sqlcmd` installed, JAKASII can inspect an authorized
database through the current Windows account:

```powershell
jakasii-ops --data-root data onboard-sqlserver `
  --server localhost `
  --database YourDatabase `
  --store-id your_store `
  --store-name "Your Store"
```

The connector runs fixed `sys.tables`/`sys.columns` catalog queries, discovers
all user tables and columns, then sends that raw metadata through the same
mapping and readiness engine used by fixture onboarding. It does not contain
store-specific table names, execute arbitrary SQL, modify the source database,
or sample business rows during automatic discovery. Any unresolved meaning is
returned as a setup question instead of being silently accepted. The metadata
catalog is retained in local SQLite and `store-memory/<store>/Learning/` without
row samples, passwords, or authentication tokens.

After discovery, JAKASII can validate a small allowlist of high-impact meanings
using aggregate shape checks only:

```powershell
jakasii-ops --data-root data validate-sql-mappings `
  --server localhost `
  --database YourDatabase `
  --store-id your_store `
  --store-name "Your Store"
```

These checks retain only counts and ratios such as null coverage, uniqueness,
positive-value coverage, and structural-role confidence. They do not return or
persist product codes, row values, names, prices, amounts, or personal fields.
Weak or empty meanings stay unresolved for a human instead of being guessed.

## Discover a complete store setup

Point JAKASII at an authorized SQL database and the existing local camera
collector directory. These are connection scopes, not schema hints:

```powershell
jakasii-ops --data-root data onboard-store `
  --server localhost `
  --database YourDatabase `
  --camera-root C:\path\to\camera-collector `
  --staff-service-account C:\secure\firebase-credential.json `
  --store-id your_store `
  --store-name "Your Store"
```

JAKASII scans the SQL catalog, declared relationships, table sizes, camera
channel configuration, device-port reachability, compatible local camera event
schemas, and (when authorized) aggregate staff routing roles. It creates
`Learning/Store-Awareness.md` plus a structured JSON artifact containing role
and relationship hypotheses. The service-account path and contents are never
persisted. An authorized camera or staff connector may declare the exact
meaning of its own fields through a semantic contract; SQL meanings still need
strong aggregate validation or human confirmation.

Import new observation metadata from the existing collector:

```powershell
jakasii-ops --data-root data ingest-camera-events `
  --camera-root C:\path\to\camera-collector `
  --store-id your_store

jakasii-ops --data-root data awareness your_store
```

The event adapter imports channel, time, detector and count metadata only. It
does not import images or snapshot paths, log in to the DVR, or turn an
observation into a stock transaction. Live RTSP collection remains the job of
the shop's authorized camera collector.

Import already-verified collector labels and SQL facts without merging their
truth categories:

```powershell
jakasii-ops --data-root data ingest-verified-operations `
  --collector-root C:\path\to\camera-collector `
  --store-id your_store
```

This adapter drops staff identities, names, free-text notes, monetary amounts,
and raw source document IDs. It keeps only the minimum operational fields and a
short hash that can detect repeated source records locally.

After onboarding, let JAKASII derive a bounded read-only transaction plan from
its learned model and route newly observed lines through the workflows:

```powershell
jakasii-ops --data-root data run-sql-cycle `
  --server localhost `
  --database YourDatabase `
  --store-id your_store `
  --store-name "Your Store" `
  --limit 5

jakasii-ops --data-root data snapshot your_store --window-minutes 15
jakasii-ops --data-root data proofs your_store --window-minutes 15
```

The cycle selects only product code, quantity, pack size, destination, and
timestamp. Source record identifiers are hashed before persistence. Customer,
supplier, staff, product-name, price, and amount fields are not selected.
Unconfirmed mappings keep resulting events in `needs_verification`; successful
query execution is not treated as proof of business meaning.

The proof report is stricter than the snapshot. It becomes
`evidence_complete` only when one operational event has an exact linked SQL
record, a camera observation inside the time window, and a positive answer to
the role-routed staff task. It never claims that camera timing identified the
product or quantity, and it never treats the bundle as an official stock write.

## Run continuously on a store server

`watch-store` combines onboarding, camera polling, verified-label polling, SQL
mapping validation, fact discovery, workflow routing, deduplication and
snapshot refresh. Omit
`--max-cycles` for continuous operation:

```powershell
jakasii-ops --data-root C:\JakasiiData watch-store `
  --server localhost `
  --database YourDatabase `
  --camera-root C:\path\to\camera-collector `
  --staff-service-account C:\secure\firebase-credential.json `
  --store-id your_store `
  --store-name "Your Store" `
  --poll-seconds 30 `
  --rescan-seconds 3600
```

On its first production start, watch mode records source cursors without
creating evidence, events, or tasks for old rows. Only records appearing after
that baseline are acted on. Use `--backfill-existing` deliberately when a
historical review is wanted; the deterministic demo and one-shot
`run-sql-cycle` remain available for judge testing.

Each cycle persists a privacy-safe health record available at
`GET /stores/{store_id}/agent`. Credential paths, connection secrets and raw
connector error messages are excluded. The agent remains read-only toward SQL,
Firestore and camera systems; official actions still require approval through
the existing policy boundary.

For a real Windows store deployment, build and transfer the offline package
instead of running the development checkout directly. The installer creates an
isolated runtime, registers a disabled user-scoped scheduled task, and requires
an explicit review/start step. See
[docs/MAIN_SERVER_DEPLOYMENT.md](docs/MAIN_SERVER_DEPLOYMENT.md). A laptop that
does not have the live camera collector is a build/test machine, not a
production watcher.

Camera configuration and live camera runtime are different states. The agent
checks a sanitized collector heartbeat and event-store freshness every cycle.
If the collector is stopped or stale, it says that fresh physical proof is
unavailable and creates one deduplicated `pending_approval` action asking the
owner to authorize and start the collector. That action never contains or asks
JAKASII to store DVR/database secret values.

Inspect and approve the request locally when the owner is ready:

```powershell
jakasii-ops --data-root C:\JakasiiData actions your_store
jakasii-ops --data-root C:\JakasiiData approve-action your_store action_... `
  --actor owner
```

Approval alone does not supply a password. On the next agent start/cycle, the
generic manifest launcher executes only an approved collector action and only
when every required environment variable is available to that process. It uses
no shell, accepts only a relative Python entry point inside the discovered
collector root, and persists no secret value.

Provision the required value through a hidden prompt on the store PC—not chat,
source code, JSON, or a batch file:

```powershell
jakasii-ops --data-root C:\JakasiiData configure-camera-access `
  --store-id your_store `
  --store-name "Your Store"
```

The command autonomously rediscovers the collector manifest and writes each
required secret to the current Windows user's Credential Manager. Output and
audit state contain variable names only. `auto-watch-store` reads available
values into process memory and passes them to the approved collector child;
the values never enter JAKASII SQLite, Markdown memory, logs, or action payloads.

## Trust rules

1. A camera event is an observation, not a stock transaction.
2. A POS/SQL row is a system record, not proof that physical work happened.
3. Important mappings are either strongly validated or confirmed by a human.
4. Official stock, attendance, purchase, and transaction changes require an
   authorized human approval.
5. JAKASII never grants itself wider filesystem, browser, computer, or database
   authority.
6. Every evidence record, task, answer, action request, and approval is audited.

## Repository map

```text
src/jakasii_ops/
  onboarding.py   schema discovery, mapping, questions, readiness
  awareness.py    structural store roles, relationships and capability model
  workflows.py    operational verification rules
  brain.py        headless coordinator and task/action outbox
  storage.py      exact SQLite records and audit log
  memory.py       explainable per-store Markdown vault
  reasoning.py    deterministic and optional local Ollama providers
  actions.py      authority and approval policy gate
  connectors.py   contracts for databases, cameras, apps and future hands
  validation.py   aggregate-only SQL mapping verification
  situational.py  evidence coverage and operational snapshots
  proof.py        strict real-operation evidence bundles
  agent.py        continuous failure-isolated store loop
  bootstrap.py    bounded autonomous local connection discovery
  api.py           localhost JSON service
fixtures/          two synthetic, independently shaped stores
tests/             onboarding, workflows, evidence and policy tests
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the system boundary and
[docs/API.md](docs/API.md) for integration examples.

## Hackathon demonstration

The three-minute proof is:

```text
unfamiliar store schema
→ discover operational concepts
→ expose and correct an unsafe mapping
→ produce a verified readiness report
→ combine synthetic camera observation with purchase record
→ detect missing destination and receiving confirmation
→ route precise tasks to DEO and godown staff
→ leave an evidence-linked audit trail and store memory
```

The full product covers all operational workflows listed above. The receiving
and godown exception is the clearest end-to-end proof, not the limit of the
architecture.

## How Codex and GPT-5.6 contributed

The product direction, store workflows, safety boundaries, and the decision to
keep observations separate from confirmed business facts came from Atlay's
experience operating physical retail systems. Codex with GPT-5.6 was used as a
collaborative engineering agent during the Build Week submission period to:

- turn that operational model into the canonical event, evidence, task,
  authority, onboarding, and memory architecture;
- implement the headless Python service, synthetic fixtures, tests, API, and
  documentation;
- challenge unsafe assumptions—for example, refusing to treat camera activity
  as an exact stock transaction;
- test two independently structured schemas and expose a plausible but wrong
  `BillQty` purchase mapping instead of hiding it;
- run a threaded end-to-end API test, identify a real SQLite worker-thread
  defect, implement locking, and add a regression test.

Atlay made the key product decisions: JAKASII Ops must work across stores,
onboarding is only the beginning, all official business changes require human
authority, existing store apps should be reused, and receiving/godown work is
the first concrete proof. Codex accelerated implementation and verification;
it did not replace the owner's domain judgment.

The current runtime uses deterministic reasoning and optionally a local Ollama
model. Codex/GPT-5.6 was the required Build Week development agent. An OpenAI
runtime provider remains a deliberate extension because promotional Codex
credits are separate from Platform API billing.

## New work versus prior systems

Created during OpenAI Build Week in this repository:

- universal schema discovery and mapping;
- temporary onboarding questions and correction learning;
- readiness reports and store-owned memory;
- the verified evidence/event/task model;
- operational workflow rules and authority-gated actions;
- the headless API, fixtures, tests, and documentation.

Pre-existing and not claimed as Build Week work:

- Sangma Megha Mart POS and databases;
- SMM camera collector;
- existing staff, boss/admin, and customer applications;
- earlier JAKASII research experiments.

See [HACKATHON.md](HACKATHON.md) for the compliance checklist and remaining
submission artifacts.
