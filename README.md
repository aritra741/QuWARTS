# QuWARTS

**Query Workload Aware Relational Table Synthesis from Unstructured Text**

QuWARTS answers analytical SQL queries—filters, aggregations, and joins—over a corpus of unstructured documents. A *reference workload* guides an offline synthesis pass that discovers a schema, extracts tables, and normalizes entities. Online queries then run over the materialized tables, with incremental extraction only when a query mentions an attribute that was not in the reference workload.

The system targets high answer quality without paying per-query extraction cost at runtime.

## How it works

```
Documents + reference SQL workload
        │
        ▼
  Offline synthesis
    schema discovery → table population → entity normalization → attribute index
        │
        ▼
  Materialized SQLite tables
        │
        ▼
  Online query
    cache hit → execute SQL
    unseen attribute → index lookup → extract → augment → execute SQL
```

| Stage | Role | Module |
|---|---|---|
| Schema discovery | Infer tables, attributes, and keys from the workload | `quwarts.lattice_planner` |
| Table population | Extract values from relevant document chunks | `quwarts.extractor`, `quwarts.sieve_synthesizer` |
| Entity normalization | Map synonymous mentions to a canonical form | `quwarts.entity_resolver` |
| Attribute index | Locate chunks that mention attributes outside the workload | `quwarts.attribute_index` |
| Online execution | Run SQL, or extract a column/row delta when needed | `quwarts.delta_engine`, `quwarts.runner` |

## Dataset

This repository includes the **NBA Players** corpus from UDA-Bench:

| Path | Contents |
|---|---|
| `source_data/Player/` | 216 documents (141 players, 30 teams, 16 owners, 29 cities) |
| `Query/Player/` | Reference and held-out SQL workloads |
| `Data/Player/` | Ground-truth tables (`player.db` and CSVs) |

## Requirements

- Python 3.9+
- [Ollama](https://ollama.ai/) with `qwen2.5:7b-instruct`

Storage is local **SQLite**. No database server is required.

## Installation

```bash
git clone https://github.com/aritra741/QuWARTS.git
cd QuWARTS

python3 -m venv venv
source venv/bin/activate
pip install -e .
python -m spacy download en_core_web_sm

# Terminal 1
ollama serve

# Terminal 2
ollama pull qwen2.5:7b-instruct
```

`./setup.sh` performs the same steps interactively.

## Usage

### Command line

```bash
# Offline synthesis from a reference workload
python -m quwarts Player --preprocess --workload Query/Player/

# Online query
python -m quwarts Player --query "SELECT name, team FROM player WHERE age > 30"

# Materialized-table statistics
python -m quwarts Player --stats
```

### Python API

```python
from quwarts import QuWARTSRunner

runner = QuWARTSRunner("Player")
runner.preprocess(workload_path="Query/Player/")
result = runner.execute_query(
    "SELECT name, location, championship "
    "FROM player JOIN team ON player.team = team.name "
    "WHERE age > 30"
)
runner.close()
```

## Reproducing paper experiments

```bash
# Offline synthesis on the NBA Players workload
python experiments/preprocess_player.py

# Held-out query-awareness trend
python experiments/eval_query_awareness.py
```

Outputs go under `results/`. Plot helper: `experiments/plot_trend.py`.

## Repository layout

```
quwarts/           # installable package
experiments/       # Player evaluation scripts
source_data/       # NBA documents
Query/             # SQL workloads
Data/              # ground-truth tables
evaluation/        # UDA-Bench metrics harness
tests/             # unit tests
```

```bash
pytest tests/
```

## Citation

If you use QuWARTS, please cite the VLDB paper.

## License

MIT. See [LICENSE](LICENSE).
