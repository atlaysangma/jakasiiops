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

1. Inspect authorized schema metadata and limited representative samples.
2. Normalize names and rank candidate canonical mappings.
3. Automatically accept only strong, validated mappings.
4. Ask temporary questions for missing or uncertain important meanings.
5. Allow a human to correct a plausible but wrong proposal.
6. Write the approved store profile and readiness report.
7. Reopen questions when future schema/connectors change.

The legacy fixture intentionally catches an incorrect purchase mapping. This is
recorded as an onboarding correction rather than hidden.

## Evidence and verification

Evidence kinds never collapse into each other:

- `observation`: camera/event/visual evidence;
- `system_record`: database, POS, purchase or app record;
- `human_confirmation`: role-authorized response;
- `manager_decision`: approval or operating decision.

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

