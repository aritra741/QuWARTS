# QuWARTS

**Query Workload Aware Relational Table Synthesis from Unstructured Text**

## Overview

QuWARTS supports **analytical queries**—filtering, aggregation, and joins—over unstructured text by synthesizing relational tables in an **offline** phase guided by a **reference workload**, then executing queries **online** over the materialized tables.

The key idea is that offline extraction should be aware of expected query patterns (from historical or representative workloads). That workload guidance helps QuWARTS:

1. **Discover a query-intent-aligned schema** with the attributes needed for accurate answers
2. **Populate tables** from the document corpus while keeping extraction cost low
3. **Normalize entities and values** so joins and predicates work across documents (e.g., mapping "Lakers" and "Los Angeles Lakers" to a canonical team name)
4. **Index attributes** so queries referencing attributes outside the reference workload can still be answered without rebuilding the database

Compared with per-query extraction (high accuracy, high latency/cost) and query-unaware offline extraction (low latency/cost, low accuracy), QuWARTS targets **high accuracy with low query-time latency and cost**.

## System architecture

QuWARTS operates in two phases:

### Phase 1: Offline data extraction

```
Unstructured documents + reference workload
  → Schema discovery
  → Data population
  → Entity normalization
  → Attribute indexing
  → Synthesized relational tables
```

| Component | Role | Implementation |
|---|---|---|
| **Schema discovery** | Infer tables, attributes, relationships, and primary keys from the workload | `lattice_planner.py`, `extractor.py` |
| **Data population** | Extract values from relevant document chunks into tables | `extractor.py`, `sieve_synthesizer.py` (chunk filtering); Evaporate-style fallback in `entity_anchor.py` |
| **Entity normalization** | Resolve synonymous entity mentions to canonical forms | `entity_resolver.py` (bi-encoder + cross-encoder) |
| **Attribute indexing** | Map document chunks to mentioned attributes for later online augmentation | `attribute_index.py` |

### Phase 2: Online query processing

Queries whose attributes are already materialized run directly over the precomputed tables. When a query references an **unseen attribute**, QuWARTS consults the attribute index, extracts the missing values online, augments the table, and then executes the query (`delta_engine.py`, `quwarts_runner.py`).

## Example: UDA-Bench NBA

A typical setup uses the **NBA dataset from UDA-Bench** with the **NBA Players workload**:

- **Reference workload:** training queries used during offline preprocessing
- **Test queries:** held-out preset queries for evaluation
- **LLM:** `qwen2.5:7b-instruct` via Ollama
- **Entity resolution:** configurable; defaults to sentence-transformer–based resolution in `entity_resolver.py`

## Installation

### Prerequisites

- Python 3.9+
- [Ollama](https://ollama.ai/) with `qwen2.5:7b-instruct`

### Quick setup

```bash
git clone https://github.com/aritra741/QuWARTS.git
cd QuWARTS

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# Terminal 1
ollama serve

# Terminal 2
ollama pull qwen2.5:7b-instruct
```

Or run `./setup.sh` for an interactive setup.

Storage defaults to a local **SQLite** database (see `config.py`); no separate database server is required.

## Usage

### NBA / Player workload

```bash
# Offline preprocessing with the Player reference workload
python test_player_workload.py

# Query-awareness evaluation on held-out queries
python test_player_query_awareness_trend.py
```

### General CLI

```bash
# Offline preprocessing
python quwarts_runner.py Player --preprocess --workload Query/Player/

# Online query execution
python quwarts_runner.py Player --query "SELECT name, team FROM player WHERE age > 30"

# Statistics
python quwarts_runner.py Player --stats
```

### Python API

```python
from quwarts_runner import QuWARTSRunner

runner = QuWARTSRunner("Player")
result = runner.preprocess(workload_path="Query/Player/")
query_result = runner.execute_query(
    "SELECT name, location, championship FROM player JOIN team ON player.team = team.name WHERE age > 30"
)
runner.close()
```

## Repository layout

| Path | Description |
|---|---|
| `quwarts_runner.py` | Main orchestration entry point |
| `lattice_planner.py` | Workload parsing and schema planning |
| `extractor.py` | LLM-based table population |
| `entity_resolver.py` | Entity normalization |
| `attribute_index.py` | Attribute-to-chunk index for online augmentation |
| `delta_engine.py` | Online query execution and table augmentation |
| `test_player_workload.py` | NBA Player preprocessing script |
| `test_player_query_awareness_trend.py` | Held-out query evaluation |

## Interactive demo UI

The browser-based demo interface is implemented as a Next.js frontend in the companion **Q-ANSWER** project (not included in this repository).

## Contact

Please open a GitHub issue for questions.
