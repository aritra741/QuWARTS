# QuWARTS Finance Workload Test - Quick Start Guide

## 30-Second Setup

### 1. Install Dependencies

```bash
# Required packages
pip install matplotlib sentence-transformers sqlalchemy

# Optional but recommended
pip install requests tqdm
```

### 2. Start Ollama (for LLM extraction)

```bash
# Terminal 1: Start Ollama service
ollama serve

# Terminal 2: Download model (if not already present)
ollama pull qwen2.5:7b-instruct
```

### 3. Run the Test

```bash
cd /Users/aritramazumder/Documents/QuWARTS

# Run full test (preprocessing + testing + report generation)
python test_finance_workload.py

# Or run in background
nohup python test_finance_workload.py > test_output.log 2>&1 &
```

## What Gets Generated

When the test completes, you'll find in `results/finance_workload_test/`:

```
results/finance_workload_test/
├── test_execution.log              # Full execution log with timestamps
├── TEST_REPORT.md                  # Human-readable markdown report
├── test_metrics.json               # Per-query detailed metrics
├── test_stats.json                 # Aggregated statistics
├── preprocessing_stats.json        # Preprocessing phase statistics
│
├── chart_agg.png                   # ✨ Aggregation query analysis
├── chart_filter.png                # ✨ Filter query analysis
├── chart_select.png                # ✨ Select query analysis
├── chart_mixed.png                 # ✨ Mixed query analysis
├── chart_summary.png               # ✨ Overall test results summary
│
└── checkpoint/
    ├── Finance_preprocessed.db     # Preprocessed database checkpoint
    └── Finance_preprocessing_stats.json
```

## Viewing Results

### View the Report

```bash
# Open markdown report
cat results/finance_workload_test/TEST_REPORT.md

# Or in VS Code
code results/finance_workload_test/TEST_REPORT.md
```

### View the Charts

```bash
# Open charts in default image viewer
open results/finance_workload_test/chart_*.png

# Or view individual charts
open results/finance_workload_test/chart_summary.png
open results/finance_workload_test/chart_agg.png
open results/finance_workload_test/chart_filter.png
open results/finance_workload_test/chart_select.png
open results/finance_workload_test/chart_mixed.png
```

### Analyze JSON Results

```bash
# View test statistics
python -m json.tool results/finance_workload_test/test_stats.json

# View detailed metrics (first 5 queries)
python -m json.tool results/finance_workload_test/test_metrics.json | head -50

# Count successful queries
cat results/finance_workload_test/test_stats.json | jq '.successful_queries'

# Get success rate
cat results/finance_workload_test/test_stats.json | jq '.success_rate'
```

## Expected Output Timeline

```
Phase 1: Preprocessing (40-70 seconds)
  └─ Ingestion: 2-5s
  └─ Sieve Synthesis: 5-10s
  └─ Extraction: 20-40s (LLM intensive)
  └─ Consolidation: 2-5s
  └─ Entity Resolution: 2-3s
  └─ Checkpoint: 1-2s

Phase 2: Testing (10-20 seconds)
  └─ Load Database: 1-2s
  └─ Execute 28 test queries: 5-15s
  └─ Generate Charts: 2-5s
  └─ Generate Report: 1-2s

Total Time: ~60-90 seconds ⏱️
```

## Key Charts Generated

### 1. `chart_agg.png` - Aggregation Queries
- Success vs Failure bar chart
- Execution time per query
- Result row count per query
- Delta type pie chart (CACHE_HIT, ROW_DELTA, COLUMN_DELTA)

### 2. `chart_filter.png` - Filter Queries
- Same format as Agg
- Shows filter-specific performance characteristics

### 3. `chart_select.png` - Select Queries
- Projection query performance
- Result set sizes

### 4. `chart_mixed.png` - Mixed Queries
- Combined filter + aggregation performance

### 5. `chart_summary.png` - Overall Summary
- Success rate comparison across test types (Subsample vs Variations)
- Average execution time by test type
- Helps identify which test category needs optimization

## What Each Metric Means

In the JSON outputs, each query has:

```json
{
  "query_id": "Query_1",
  "query_text": "SELECT auditor, MIN(business_segments_num) FROM finance...",
  "query_type": "Subsample",              // Which test category
  "success": true,                        // Query executed successfully
  "results_count": 45,                    // Rows returned
  "delta_type": "CACHE_HIT",              // CACHE_HIT | ROW_DELTA | COLUMN_DELTA
  "execution_time": 0.234,                // Seconds
  "error": null                           // Error message if failed
}
```

**Delta Types:**
- `CACHE_HIT`: All columns/predicates already extracted → direct SQL
- `ROW_DELTA`: New predicate values → extract + insert new rows
- `COLUMN_DELTA`: New columns → targeted extraction + update
- `ERROR`: Query execution failed

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Ollama is not running" | Start Ollama with `ollama serve` |
| "No source documents found" | Verify `source_data/Finance/finance/` has .txt files |
| "ModuleNotFoundError: matplotlib" | `pip install matplotlib` |
| Charts not generated | Check matplotlib is installed; non-fatal if missing |
| Test execution is slow | Check if Ollama is using GPU (CUDA/Metal) |
| Database error | Delete `.databases/Finance.db` and retry |

## Example Commands

### Run and monitor progress
```bash
python test_finance_workload.py | tee full_output.txt
tail -f results/finance_workload_test/test_execution.log
```

### Extract specific statistics
```bash
# Success rate
jq '.success_rate' results/finance_workload_test/test_stats.json

# Total time
jq '.total_time' results/finance_workload_test/test_stats.json

# Queries by type
jq '.test_results | keys' results/finance_workload_test/test_stats.json

# Failed query details
jq '.[] | select(.success==false)' results/finance_workload_test/test_metrics.json
```

### Compare multiple runs
```bash
# Copy results to timestamped directory
cp -r results/finance_workload_test results/finance_workload_test_$(date +%Y%m%d_%H%M%S)

# Run again
python test_finance_workload.py

# Compare metrics
diff results/finance_workload_test_20260219_143022/test_stats.json \
     results/finance_workload_test/test_stats.json
```

## Next Steps

1. **Optimize Performance**: If execution is slow, profile which step takes longest
   - Check `preprocessing_stats.json` for preprocessing bottlenecks
   - Check `test_stats.json` for query execution bottlenecks

2. **Extend Test Coverage**: Add more test queries to `Query/Finance/Variations/`

3. **Run on Other Datasets**: Adapt this script for `SyntheticPlayer` or custom datasets

4. **Benchmark Against Ground Truth**: Compare extracted data with known correct results

5. **Scale Up**: Increase `MAX_PARALLEL_REQUESTS` in `config.py` if GPU headroom available

---

**For detailed architecture and configuration options, see `README_TEST_FINANCE.md`**
