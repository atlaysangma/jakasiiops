# OpenAI Build Week 2026

## Entry

- Project: **JAKASII Ops**
- Track: **Work & Productivity**
- Entrant: individual
- Submission deadline: **July 21, 2026 at 5:00 PM Pacific Time**
- Repository license: **MIT**

## Submission-ready repository requirements

- [x] Working, installable project
- [x] Public-repository-compatible source tree
- [x] Relevant open-source license
- [x] README setup and run instructions
- [x] Synthetic sample data
- [x] Judge-testable deterministic demo without paid services
- [x] Codex/GPT-5.6 collaboration explanation
- [x] Key human product and engineering decisions documented
- [x] Pre-existing work separated from new Build Week work
- [x] Supported platforms stated
- [x] Automated tests and GitHub Actions workflow
- [ ] Public YouTube demo shorter than three minutes
- [ ] Demo audio explains what was built and how Codex/GPT-5.6 was used
- [ ] Devpost project description completed
- [ ] `/feedback` Codex Session ID entered in Devpost
- [ ] Final repository URL entered in Devpost

The unchecked items are submission-form or video artifacts and must not be
fabricated inside the repository.

## One-command judge demo

After installing the package with `python -m pip install -e .`:

```text
jakasii-ops --data-root judge-data demo --fixture legacy_mart
```

Expected proof:

1. JAKASII inspects an unfamiliar, deliberately messy schema.
2. It proposes mappings and exposes uncertainty.
3. A human corrects the unsafe purchase-quantity mapping.
4. All five readiness checks pass.
5. Camera observation and purchase-system evidence remain separate.
6. A receiving event with no destination creates a DEO task.
7. Missing receiver corroboration creates a godown-staff task.
8. SQLite audit state and Markdown store memory are written locally.

Run the second independently shaped fixture to show the core is not hardcoded:

```text
jakasii-ops --data-root judge-data-modern demo --fixture modern_shop
```

## Three-minute video outline

- **0:00–0:20 — Problem:** Small businesses have cameras, POS records, and
  staff updates, but no affordable integration layer that understands how work
  actually moves through the store.
- **0:20–1:05 — Autonomous onboarding:** Inspect the legacy fixture, show the
  wrong `BillQty` proposal, correct it, and show readiness turn green.
- **1:05–2:15 — Operational proof:** Ingest synthetic unloading observation and
  purchase record, show missing destination and receiving confirmation, and
  route tasks to DEO and godown staff.
- **2:15–2:40 — Trust:** Show evidence types, approval boundary, audit entries,
  and store memory.
- **2:40–2:58 — Codex/GPT-5.6:** Explain that Codex with GPT-5.6 turned Atlay's
  domain model into the tested headless service and found/fixed the threaded
  database defect.

Use only synthetic footage/data. Do not show live staff, customers, CCTV,
credentials, production database records, third-party music, or unlicensed
assets.

## Product boundary

JAKASII Ops is the new headless brain. Existing POS, camera, staff, boss, and
customer systems are future connector targets and are not included or claimed
as hackathon implementation.

