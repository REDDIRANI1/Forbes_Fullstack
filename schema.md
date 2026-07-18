# Rate Tracker Schema

## `rates_ingestionbatch`

One row represents a source import identity. `source` identifies the adapter and `source_identifier` is its stable content identity; their unique constraint lets a retry resume the same batch rather than create an indistinguishable second attempt. Counters and status provide operational visibility without scanning rate rows.

## `rates_rawraterecord`

Each source row is preserved as JSON before its normalized form is accepted or rejected. `parse_status` and `parse_error` make invalid records replayable. `(batch_id, source_row_number)` is unique, so a repeated batch cannot duplicate its raw positions. `raw_batch_parse_idx (batch_id, parse_status)` supports batch diagnostics and targeted replay.

## `rates_raterecord`

This is the queryable rate fact. It has a one-to-one source raw record, a case-folded `provider_name`, `rate_type`, four-decimal fixed-precision `rate_value`, `effective_date`, and source `ingested_at`. The positive-value check rejects invalid financial rates.

`unique_normalized_rate_fact (provider_name, rate_type, effective_date, rate_value)` defines one logical rate fact. It preserves a changed value on the same date while rejecting the same normalized fact from a retry or duplicated source row. The original source records remain available through `RawRateRecord` even if their normalized fact conflicts.

## Query Support

| Query | Index | Rationale |
| --- | --- | --- |
| Latest rate per provider without a type filter | `rate_latest_provider_idx (provider_name, effective_date DESC, ingested_at DESC, id DESC)` | Supports deterministic newest-row selection within each provider. |
| Latest rate per provider after `type` filtering | `rate_latest_type_idx (rate_type, provider_name, effective_date DESC, ingested_at DESC, id DESC)` | Narrows to the requested type before selecting one row per provider. |
| History for provider/type | `rate_history_lookup_idx (provider_name, rate_type, effective_date DESC)` | Supports ordered provider/type time series lookups. |
| Records ingested in a 24-hour window | `rate_ingested_at_idx (ingested_at)` | Supports bounded timestamp range scans. |
| Failed/replayable source rows | `raw_batch_parse_idx (batch_id, parse_status)` | Locates failed or pending rows for one batch. |

The deliberate compromise is canonicalizing providers only by case-folding input. The raw payload keeps the supplied spelling; a production provider registry can later supply official display labels and aliases.
