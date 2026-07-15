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
  workflows.py    operational verification rules
  brain.py        headless coordinator and task/action outbox
  storage.py      exact SQLite records and audit log
  memory.py       explainable per-store Markdown vault
  reasoning.py    deterministic and optional local Ollama providers
  actions.py      authority and approval policy gate
  connectors.py   contracts for databases, cameras, apps and future hands
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

