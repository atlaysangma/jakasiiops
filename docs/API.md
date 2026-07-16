# Headless API

The API listens on `127.0.0.1:8765` by default. Payloads are JSON.

## Onboarding

`POST /onboarding`

```json
{"schema_path":"C:\\path\\to\\schema.json"}
```

`POST /stores/{store_id}/questions/{question_id}/answer`

```json
{"answer":"source.table.column","actor":"owner-1"}
```

## Evidence and events

`POST /stores/{store_id}/evidence`

```json
{
  "kind":"observation",
  "source":"camera-connector",
  "confidence":0.78,
  "payload":{"zone":"receiving_bay","activity":"cartons_unloaded"}
}
```

`POST /stores/{store_id}/events`

```json
{
  "event_type":"receiving",
  "evidence_ids":["evd_...","evd_..."],
  "facts":{
    "product_id":"SKU-TEA-250",
    "cartons":1,
    "pack_size":24,
    "loose_pieces":5,
    "total_base_units":29,
    "destination_id":null,
    "receiver_confirmed":false
  }
}
```

Supported event types: `receiving`, `stock_movement`, `stock_count`, `damage`,
`expiry`, `attendance`, `sale`, `purchase`, and `return`.

`POST /stores/{store_id}/tasks/{task_id}/answer`

```json
{"actor":"godown-staff-14","answer":{"confirmed":true,"received_quantity":29,"location":"GD-A"}}
```

A positive operational confirmation can complete a proof bundle only when the
same event already has linked SQL evidence and nearby camera timing context.
The API does not claim the camera identified the SKU or quantity.

## Action policy

`POST /stores/{store_id}/actions`

```json
{
  "action":"adjust_stock",
  "target":"pos.stock",
  "reason":"Apply confirmed receiving variance",
  "authority":"official_record",
  "reversible":true,
  "data_leaving_device":false,
  "payload":{"product_id":"SKU-TEA-250","delta":5}
}
```

`POST /stores/{store_id}/actions/{action_id}/approve`

```json
{"actor":"owner-1"}
```

Approval records permission; it does not yet execute external mutations. A
future connector executor must accept only approved requests.

## Read endpoints

- `GET /health`
- `GET /stores/{store_id}/status`
- `GET /stores/{store_id}/readiness`
- `GET /stores/{store_id}/questions`
- `GET /stores/{store_id}/tasks`
- `GET /stores/{store_id}/actions`
- `GET /stores/{store_id}/schema` — sanitized metadata catalog; no row samples
- `GET /stores/{store_id}/awareness` — unverified structural role and relationship model
- `GET /stores/{store_id}/snapshot` — source freshness, evidence coverage, and open role work
- `GET /stores/{store_id}/proofs` — strict SQL + camera-context + human-confirmation bundles
- `GET /stores/{store_id}/agent` — latest continuous-agent cycle health and imports
- `GET /stores/{store_id}/memory`
- `GET /stores/{store_id}/audit`
