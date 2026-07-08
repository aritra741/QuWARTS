# WDIRS Finance Workload Test Suite

## Overview

This test suite orchestrates a complete end-to-end validation of the WDIRS (Workload-Driven Information Extraction from Relational Synthesis) system using the Finance dataset.

The pipeline has two phases:

### Phase 1: Offline Preprocessing
- **Input**: Training queries from `Query/Finance/{Agg, Filter, Select, Mixed}`
- **Process**: 
  1. Workload Lattice Planning (parse SQL, identify tables/predicates/joins)
  2. Text Ingestion (chunk source documents from `source_data/Finance/`)
  3. Programmatic Sieve Synthesis (LLM-generated filtering)
  4. Constrained Global Extraction (batched parallel LLM extraction)
  5. Record Consolidation (entity deduplication + provenance union)
  6. Proactive Entity Resolution (join key canonicalization)
  7. Save & Checkpoint (persist database state)
- **Output**: SQLite database + metadata registry in `results/finance_workload_test/checkpoint/`

### Phase 2: Runtime Testing
- **Input**: Test queries from `Query/Finance/{Subsample, Variations}`
- **Process**:
  - Load preprocessed database
  - Execute test queries via Delta Engine
  - Validate Row Delta (new predicates) and Column Delta (new attributes)
  - Measure query performance and correctness
- **Output**: Test metrics, statistics, and report in `results/finance_workload_test/`

## Files

```
systems/WDIRS/
├── test_finance_workload.py       # Main test orchestrator (this script)
├── wdirs_runner.py                # WDIRS pipeline orchestration
├── data_layer.py                  # SQLAlchemy schema + metadata registry
├── lattice_planner.py             # Workload analysis + MQO
├── sieve_synthesizer.py           # Programmatic sieve generation
├── extractor.py                   # Constrained parallel extraction
├── entity_resolver.py             # Entity resolution + deduplication
├── delta_engine.py                # Runtime delta planning
├── config.py                      # Configuration constants
└── .databases/                    # SQLite database storage

Query/Finance/
├── Agg/                           # Aggregation queries
├── Filter/                        # Filter queries
├── Select/                        # Projection queries
├── Mixed/                         # Combined filter + agg queries
├── Subsample/                     # Test: subset of training queries
└── Variations/                    # Test: variations on training queries

source_data/Finance/
└── finance/                       # 100 unstructured text documents
    ├── 1.txt
    ├── 2.txt
    └── ... 100.txt

results/finance_workload_test/
├── checkpoint/                    # Preprocessed database checkpoint
│   ├── Finance_preprocessed.db
│   └── Finance_preprocessing_stats.json
├── test_metrics.json              # Per-query metrics
├── test_stats.json                # Aggregated statistics
├── TEST_REPORT.md                 # Human-readable report
└── test_execution.log             # Full execution log
```

## Usage

### 1. Prerequisites

**System Requirements:**
- Python 3.8+
- SQLAlchemy (database ORM)
- sentence-transformers (entity resolution embeddings)
- Ollama with qwen2.5:7b-instruct (for LLM extraction)

**Data Requirements:**
- Source documents: `source_data/Finance/finance/*.txt` ✓ (100 documents)
- Training queries: `Query/Finance/{Agg,Filter,Select,Mixed}/*.sql` ✓
- Test queries: `Query/Finance/{Subsample,Variations}/**/*.sql` ✓

### 2. Run the Full Test

```bash
cd /Users/aritramazumder/Documents/UDA-Bench-main/systems/WDIRS

# Run full pipeline (preprocessing + testing)
python test_finance_workload.py
```

### 3. Expected Output

**During Execution:**
```
================================================================================
PHASE 1: OFFLINE RELATIONAL SYNTHESIS (Preprocessing)
================================================================================

Initializing WDIRS Runner for Finance
Loading training queries from /Users/.../Query/Finance/Agg/agg_queries_finance.sql
Loading training queries from /Users/.../Query/Finance/Filter/filter_queries_Finan.sql
Loading training queries from /Users/.../Query/Finance/Select/select_queries.sql
Loading training queries from /Users/.../Query/Finance/Mixed/mixed_queries.sql

Collected 81 training queries

Running unified preprocessing pipeline...
✓ Preprocessing complete in 45.23s
  - Tables: ['finance']
  - Chunks: 1250
  - Records: 3456

Saving checkpoint...
✓ Checkpoint saved in 2.15s

================================================================================
PHASE 1 COMPLETE - Total Time: 47.38s
================================================================================

================================================================================
PHASE 2: RUNTIME EXECUTION (Testing)
================================================================================

Loading preprocessed database from /Users/.../results/finance_workload_test/checkpoint/Finance_preprocessed.db

Loaded 28 test queries

Executing Subsample test queries (9 queries)
  ✓ Query_1: 45 rows in 0.234s
  ✓ Query_2: 120 rows in 0.456s
  ...

Executing Variations test queries (19 queries)
  ✓ Query_1: 67 rows in 0.189s
  ✓ Query_2: 98 rows in 0.321s
  ...

================================================================================
PHASE 2 COMPLETE - Total Time: 12.45s
Success Rate: 89.3% (25/28)
================================================================================

================================================================================
OVERALL TEST SUMMARY
================================================================================
Preprocessing: ✓ PASSED
Testing: ✓ PASSED
Results saved to: /Users/.../results/finance_workload_test
================================================================================
```

### 4. Inspect Results

**View Execution Log:**
```bash
cat results/finance_workload_test/test_execution.log
```

**View Test Report:**
```bash
cat results/finance_workload_test/TEST_REPORT.md
```

**Analyze Metrics (JSON):**
```bash
cat results/finance_workload_test/test_metrics.json | jq '.'
cat results/finance_workload_test/test_stats.json | jq '.'
```

**View Checkpoint Statistics:**
```bash
cat results/finance_workload_test/checkpoint/Finance_preprocessing_stats.json | jq '.'
```

## Configuration

All parameters are in `config.py`. Key settings:

```python
# LLM Settings (Ollama)
OLLAMA_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "qwen2.5:7b-instruct"
EXTRACTION_BATCH_SIZE = 10

# Entity Resolution (sentence-transformers)
BI_ENCODER_THRESHOLD = 0.75
CROSS_ENCODER_THRESHOLD = 0.95

# Parallelism
MAX_PARALLEL_REQUESTS = 16
MAX_WORKERS = 4

# Schema Stabilization
SCHEMA_SAMPLE_SIZE = 50
SCHEMA_KEY_FREQUENCY_THRESHOLD = 0.20
```

## Workload Details

### Training Queries (81 total)

| Type | Count | Path | Example |
|------|-------|------|---------|
| Agg | 10 | `Query/Finance/Agg/agg_queries_finance.sql` | `SELECT auditor, MIN(business_segments_num) FROM finance GROUP BY auditor` |
| Filter | 183 | `Query/Finance/Filter/filter_queries_Finan.sql` | `SELECT company_name FROM finance WHERE auditor = 'PKF Littlejohn LLP'` |
| Select | 10 | `Query/Finance/Select/select_queries.sql` | `SELECT earnings_per_share FROM finance` |
| Mixed | 6 | `Query/Finance/Mixed/mixed_queries.sql` | `SELECT auditor, AVG(bussiness_profit) FROM finance WHERE remuneration_policy = 'Performance-based' GROUP BY auditor` |

### Test Queries (28 total)

| Type | Count | Path | Relationship |
|------|-------|------|---------------|
| Subsample | 9 | `Query/Finance/Subsample/*.sql` | Subset of training queries (same predicates) |
| Variations | 19 | `Query/Finance/Variations/**/*.sql` | Variations on training (different aggregations, predicates) |

**Test Strategy:**
- **Subsample**: Validates Row Delta execution (same schema as training)
- **Variations**: Validates Column Delta execution (new columns/aggregations)

## Output Files

### `test_metrics.json`
Per-query metrics for detailed analysis:
```json
[
  {
    "query_id": "Query_1",
    "query_text": "SELECT auditor, MIN(business_segments_num) FROM finance...",
    "query_type": "Subsample",
    "success": true,
    "results_count": 45,
    "delta_type": "CACHE_HIT",
    "execution_time": 0.234,
    "error": null
  },
  ...
]
```

### `test_stats.json`
Aggregated statistics:
```json
{
  "dataset": "Finance",
  "total_queries": 28,
  "successful_queries": 25,
  "failed_queries": 3,
  "success_rate": 0.893,
  "total_time": 12.45,
  "test_results": {
    "Subsample": {
      "total": 9,
      "successful": 9,
      "failed": 0,
      "average_execution_time": 0.245
    },
    "Variations": {
      "total": 19,
      "successful": 16,
      "failed": 3,
      "average_execution_time": 0.187
    }
  },
  ...
}
```

### `TEST_REPORT.md`
Human-readable markdown report with:
- Phase 1 summary (duration, status, step breakdown)
- Phase 2 summary (total queries, success rate, per-type results)
- Query execution details (first 15 queries)

## Troubleshooting

### Issue: "No source documents found"
**Cause**: `source_data/Finance/` is empty
**Solution**: Verify Finance documents exist in `source_data/Finance/finance/*.txt`

### Issue: "Ollama is not running"
**Solution**: Start Ollama:
```bash
ollama serve
# In another terminal:
ollama pull qwen2.5:7b-instruct
```

### Issue: "No training queries collected"
**Cause**: Query files not found
**Solution**: Verify files exist:
```bash
ls -la Query/Finance/{Agg,Filter,Select,Mixed}/*.sql
```

### Issue: Preprocessing timeout
**Cause**: LLM extraction is slow on CPU
**Solution**: Check Ollama is using GPU (CUDA/Metal)

### Issue: "Checkpoint not found"
**Cause**: Preprocessing failed silently
**Solution**: Check log file for errors:
```bash
tail -100 results/finance_workload_test/test_execution.log
```

## Architecture Notes

### WDIRS Pipeline

```
Query Workload
     ↓
[Step 1] Lattice Planning (parse SQL, identify tables/cols/preds)
     ↓
[Step 2] Text Ingestion (chunk documents → raw_chunks table)
     ↓
[Step 3] Sieve Synthesis (LLM generates is_relevant(chunk))
     ↓
[Step 4] Constrained Extraction (parallel LLM: extract rows from relevant chunks)
     ↓
[Step 5] Record Consolidation (dedup rows by identity, merge provenance)
     ↓
[Step 6] Entity Resolution (canonicalize join keys via embeddings)
     ↓
[Step 7] Checkpoint (save DB + metadata registry)
     ↓
SQLite Database (finance table + metadata_registry + row_provenance)
     ↓
[Phase 2] Runtime Query Execution
     ↓
Delta Engine (analyze query → check metadata_registry → execute delta if needed)
     ↓
Results
```

### Delta Engine (Phase 2)

For each runtime query:

1. **Analyze Query**: Extract tables, columns, predicates
2. **Lookup Metadata Registry**: Check if columns/predicates are FULL or PARTIAL
3. **Classify Delta**:
   - **CACHE_HIT**: All columns and predicates already extracted → execute SQL directly
   - **ROW_DELTA**: New predicate values → extract rows for new predicates + insert
   - **COLUMN_DELTA**: New columns → lookup row_provenance, trigger targeted LLM extraction, UPDATE
4. **Execute SQL**: Return results

## Performance Expectations

| Phase | Component | Time (Typical) | Notes |
|-------|-----------|----------------|-------|
| P1 | Ingestion | 2-5s | Sequential file reading |
| P1 | Sieve Synthesis | 5-10s | 1 LLM call per table |
| P1 | Extraction | 20-40s | Parallel 16 requests, depends on chunk count |
| P1 | Consolidation | 2-5s | In-memory deduplication |
| P1 | Entity Resolution | 2-3s | sentence-transformers |
| P1 | **Total** | **40-70s** | Dominated by extraction |
| P2 | Query Exec (CACHE_HIT) | 0.1-0.5s | Direct SQL |
| P2 | Query Exec (ROW_DELTA) | 0.5-2s | LLM extraction required |
| P2 | Query Exec (COLUMN_DELTA) | 0.5-2s | Targeted LLM extraction |
| P2 | **Total (28 queries)** | **10-20s** | Mix of delta types |

## Next Steps

- [ ] Profile extraction bottleneck (LLM latency vs. batching)
- [ ] Experiment with larger batch sizes for parallel requests
- [ ] Implement adaptive sieve refinement based on false negative rate
- [ ] Add benchmark against ground truth (if available)
- [ ] Extend to other datasets (SyntheticPlayer, etc.)

## References

See `systems/WDIRS/` for implementation details:
- `wdirs_runner.py`: Main orchestration logic
- `data_layer.py`: Schema + metadata registry design
- `lattice_planner.py`: Workload analysis (MQO)
- `delta_engine.py`: Runtime delta planning
