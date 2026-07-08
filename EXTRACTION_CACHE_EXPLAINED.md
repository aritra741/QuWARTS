# Extraction Cache: Detailed Explanation

This document explains **when** the extraction cache is created, **where** it lives, **why** you see "0 LLM extraction tasks" but still get "33 rows extracted", and how the different cache paths interact.

---

## 1. What Is the Extraction Cache?

The extraction cache stores **LLM extraction results** so that re-extracting the same chunk for the same table (and predicates) can skip the LLM call. Each cached entry is a JSON file containing:

- `chunk_id`
- `records` (extracted rows)
- `schema_keys`
- `extraction_time`
- `error` (if any)

---

## 2. Where Does the Cache Live?

The extractor gets its cache directory from **config at initialization**:

```python
# extractor.py __init__
self.cache_dir = _config.CACHE_DIR / "extractions"
```

So the cache path is always: **`config.CACHE_DIR / "extractions"`**.

### 2.1 Default Config

From `config.py`:

```python
CACHE_DIR = WDIRS_DIR / ".cache"   # = systems/WDIRS/.cache
```

So by default: **`systems/WDIRS/.cache/extractions`**.

### 2.2 During Preprocessing (test_player_workload.py)

Preprocessing **overrides** `config.CACHE_DIR` before creating the runner:

```python
cache_dir = run_dir / ".cache"   # e.g. results/player_workload_preprocess/run_xxx/.cache
config_module.CACHE_DIR = cache_dir
# ... run preprocessing ...
config_module.CACHE_DIR = original_cache   # restored in finally
```

So during preprocessing, extractions are written to:

**`results/player_workload_preprocess/run_YYYYMMDD_HHMMSS/.cache/extractions`**

After preprocessing, the config is restored. The extractor created during preprocessing used the overridden `CACHE_DIR`, so those files stay in the run-specific `.cache` folder.

### 2.3 During Trend Run (test_player_query_awareness_trend.py)

The trend script **does not override** `config.CACHE_DIR`. So the extractor uses the **default**:

**`systems/WDIRS/.cache/extractions`**

### 2.4 Important: Extractor vs Runner Cache

- **Runner's `cache_dir`** (passed as `cache_dir=snapshot_cache` in the trend script) is used for:
  - Attribute index (`attribute_index.json`)
  - Preprocessing results
  - Other runner-specific artifacts

- **Extractor's `cache_dir`** comes from `config.CACHE_DIR` and is **not** passed from the runner. The extractor is created as:

  ```python
  self.extractor = ConstrainedExtractor(self.llm_client)
  ```

  So the extractor always uses whatever `config.CACHE_DIR` is at the moment it is created.

**Result:** The extraction cache and the snapshot cache are **separate**. The extractor does **not** read from `snapshot_cache/extractions` unless you explicitly override `config.CACHE_DIR` to point there before creating the runner.

---

## 3. When Is the Cache Created?

### 3.1 During Preprocessing (extract_batch)

When `extract_batch()` runs (Phase 1 extraction), for each chunk:

1. It checks `_get_cached_result(chunk_id, table_name)`.
2. If not cached, it calls the LLM and extracts.
3. After extraction, it calls `_cache_result(chunk_id, table_name, merged)`.

**Cache key:** `md5(chunk_id + ":" + table_name)`  
Example: `md5("chunk_123:player")` → file `abc123def456.json`

### 3.2 During Row Delta (extract_batch_with_predicates)

When the delta engine runs row delta (e.g. for Q3/Q7 with `draft_pick >= 0`), it calls `extract_batch_with_predicates()`. For each chunk:

1. It builds `cache_key = f"{chunk_id}_{table_name}_{pred_key}"`  
   Example: `"chunk_123_player_draft_pick_>=_0"`
2. It checks `_get_cached_result(cache_key, table_name)`.
3. If not cached, it calls the LLM.
4. After extraction, it calls `_cache_result(cache_key, table_name, merged)`.

**Cache key:** `md5(cache_key + ":" + table_name)`  
Example: `md5("chunk_123_player_draft_pick_>=_0:player")` → file `xyz789.json`

So predicate extraction uses a **predicate-specific** cache key. Preprocessing (no predicates) and row delta (with predicates) use **different** cache keys and do **not** share cache entries.

---

## 4. Why "0 Tasks" But "33 Rows Extracted"?

### 4.1 The "Tasks" Count

In `extract_batch_with_predicates`:

```python
# Build groups of uncached chunks
for chunk, chunk_id in zip(chunks, chunk_ids):
    cache_key = f"{chunk_id}_{table_name}_{pred_key}"
    cached = self._get_cached_result(cache_key, table_name)
    if cached:
        pre_cached.append(cached)
        continue
    # ... add to groups for LLM extraction ...

total_tasks = len(groups) * n_batches
```

If **all** chunks hit the cache, then:

- `groups` is empty (no chunks need LLM extraction).
- `total_tasks = 0 * n_batches = 0`.

So you see **"0 tasks"** in the logs.

### 4.2 The "Rows Extracted" Count

The cached results are still returned and used:

```python
all_results: List[ExtractionResult] = list(pre_cached)
# ... plus any newly extracted results ...
return all_results
```

The delta engine then inserts these records into the DB:

```python
for result in results:
    # ... upsert result.records into the table ...
    total_rows += len(inserted)
```

So even with 0 LLM tasks, you still get **33 rows extracted** (or whatever the cached records contain).

### 4.3 Summary Flow

1. Row delta needs data for ~95 chunks (e.g. for `player` with `draft_pick >= 0`).
2. For each chunk, `_get_cached_result()` finds a cached file.
3. All 95 chunks → `pre_cached`, `groups` empty → **0 tasks**.
4. Cached records are returned and inserted into the DB → **33 rows extracted**.

---

## 5. Where Do the Cache Hits Come From?

Since preprocessing and row delta use **different** cache keys, preprocessing cache **cannot** satisfy row-delta lookups.

The 0-task behavior happens when the extractor finds cache in **`systems/WDIRS/.cache/extractions`** (the default path). That can only be populated by:

1. **A previous run of the trend script** that executed row delta for the same query (same chunks, same table, same predicates). Those runs wrote to the default `.cache/extractions`.
2. **A previous run of player workload test** (or similar) that used the default `config.CACHE_DIR` and triggered row delta.

So: **0 tasks = all chunks were already cached from an earlier run** that used the default cache path.

---

## 6. Snapshot vs Extractor Cache (Current Behavior)

The trend script creates:

- `snapshot/cache_snapshot` – copy of preprocessing run’s `.cache` (includes `extractions`).
- `snapshot/extractions_snapshot` – copy of `source_cache/extractions`.

The extractor, however, uses `config.CACHE_DIR / "extractions"` = **`systems/WDIRS/.cache/extractions`**, which is **not** the snapshot.

So:

- The snapshot extraction cache is **not used** by the extractor unless `config.CACHE_DIR` is overridden to point at the snapshot before the runner is created.
- The 0-task behavior comes from the **default** `.cache/extractions`, not from the snapshot.

---

## 7. Cache Key Design (Predicate vs Non-Predicate)

| Scenario                    | Cache key used in lookup/store                    | File name                          |
|----------------------------|---------------------------------------------------|------------------------------------|
| Preprocessing (extract_batch) | `chunk_id`, `table_name`                         | `md5(chunk_id:table_name).json`    |
| Row delta (with predicates) | `chunk_id_table_name_pred_key`, `table_name`      | `md5(composite:table_name).json`   |

So:

- Preprocessing and row delta do **not** share cache entries.
- Different predicates (e.g. `draft_pick >= 0` vs `draft_pick > 5`) use different cache entries.

---

## 8. How to Get "Cold" Extraction (No Cache)

To force fresh LLM extraction and avoid cache hits:

1. **Delete the extraction cache** before running:
   ```bash
   rm -rf systems/WDIRS/.cache/extractions/*
   ```

2. **Or** use a run-specific cache by overriding `config.CACHE_DIR` in the trend script (similar to preprocessing) before creating the runner.

---

## 9. Summary

| Question                         | Answer                                                                 |
|---------------------------------|------------------------------------------------------------------------|
| When is the cache created?      | During preprocessing (`extract_batch`) and during row delta (`extract_batch_with_predicates`). |
| Where does it live?             | `config.CACHE_DIR/extractions` (default: `systems/WDIRS/.cache/extractions`). |
| Why 0 tasks but rows extracted? | All chunks hit cache → no LLM calls → 0 tasks; cached records are still inserted → rows extracted. |
| Where do cache hits come from?   | Previous runs that used the default cache path and did row delta for the same query. |
| Does preprocessing cache help row delta? | No. Different cache keys (no predicates vs with predicates). |
| Does the snapshot extraction cache get used? | No, unless `config.CACHE_DIR` is overridden to the snapshot. |
