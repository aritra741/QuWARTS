# QuWARTS Architecture Documentation

**Query Workload Aware Relational Table Synthesis from Unstructured Text**

## System Overview

QuWARTS is a two-phase system for analytical queries—filtering, aggregation, and joins—over unstructured text. In an **offline** phase, a **reference workload** guides schema discovery, table population, entity normalization, and attribute indexing. In an **online** phase, queries run over the materialized tables, with incremental augmentation when a query references attributes outside the reference workload.

## Core Principles

1. **Query workload aware**: Representative SQL workloads steer schema discovery and offline extraction toward query-relevant attributes
2. **Incremental**: Materialize what the workload needs offline; augment online only for unseen attributes or predicates
3. **Cost-optimized**: Minimize expensive LLM calls through caching, sieves, and MQO
4. **Provenance-tracked**: Every row links back to source text for lazy enrichment

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    QuWARTS System Architecture                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                   Phase 1: Offline Synthesis                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Input: Raw Text + SQL Workload                                 │
│     ↓                                                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 1. Workload Lattice Planner (lattice_planner.py)        │  │
│  │    - Parse SQL queries with sqlglot                      │  │
│  │    - Extract tables, columns, predicates                 │  │
│  │    - Build subsumption graph (MQO)                       │  │
│  │    - Identify semantic types                             │  │
│  └──────────────────────────────────────────────────────────┘  │
│     ↓                                                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 2. Text Ingestion (data_layer.py)                       │  │
│  │    - Recursive character splitting (500 tokens)          │  │
│  │    - Store chunks in PostgreSQL                          │  │
│  │    - Index by doc_id and chunk_index                     │  │
│  └──────────────────────────────────────────────────────────┘  │
│     ↓                                                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 3. Sieve Synthesis (sieve_synthesizer.py)               │  │
│  │    - Sample 5 chunks                                     │  │
│  │    - Extract keywords (FlashText)                        │  │
│  │    - Extract patterns (regex)                            │  │
│  │    - Extract entities (spaCy NER)                        │  │
│  │    - Generate Python filter function (LLM)               │  │
│  │    - Refine through testing (3 iterations)               │  │
│  │    - Apply to all chunks → Candidate_Index               │  │
│  └──────────────────────────────────────────────────────────┘  │
│     ↓                                                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 4. Schema Stabilization (extractor.py)                  │  │
│  │    - Sample 50 candidate chunks                          │  │
│  │    - Extract with LLM (no constraints)                   │  │
│  │    - Count key frequencies                               │  │
│  │    - Freeze keys with >20% frequency                     │  │
│  └──────────────────────────────────────────────────────────┘  │
│     ↓                                                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 5. Constrained Extraction (extractor.py)                │  │
│  │    - Batch candidate chunks (5 per batch)                │  │
│  │    - Call Ollama with constrained keys                   │  │
│  │    - Parse JSON responses                                │  │
│  │    - Insert into SQL tables                              │  │
│  │    - Store provenance (row_id → chunk_ids)               │  │
│  │    - Update Metadata_Registry                            │  │
│  └──────────────────────────────────────────────────────────┘  │
│     ↓                                                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 6. Entity Resolution (entity_resolver.py)               │  │
│  │    - Extract mentions from records                       │  │
│  │    - Blocking: Bi-encoder + FAISS (threshold: 0.75)     │  │
│  │    - Matching: Cross-encoder (threshold: 0.95)          │  │
│  │    - Clustering: Union-Find                              │  │
│  │    - Canonicalization: LLM selects canonical form        │  │
│  │    - Build canonical_map (mention → canonical)           │  │
│  │    - Normalize all records                               │  │
│  └──────────────────────────────────────────────────────────┘  │
│     ↓                                                            │
│  Output: Materialized Relational Database                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                   Phase 2: Runtime Execution                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Input: SQL Query                                               │
│     ↓                                                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 1. Query Analysis (delta_engine.py)                     │  │
│  │    - Parse query with sqlglot                            │  │
│  │    - Extract requested columns (π_req)                   │  │
│  │    - Extract predicates (P_req)                          │  │
│  │    - Extract joins                                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│     ↓                                                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 2. Delta Calculation (delta_engine.py)                  │  │
│  │    - Lookup Metadata_Registry                            │  │
│  │    - Check materialization status                        │  │
│  │    - Identify missing columns                            │  │
│  │    - Identify missing predicates                         │  │
│  │    - Determine delta type:                               │  │
│  │      • CACHE_HIT: All data materialized                  │  │
│  │      • ROW_DELTA: Need new rows (new predicates)         │  │
│  │      • COLUMN_DELTA: Need new columns (enrichment)       │  │
│  │      • MIXED_DELTA: Need both                            │  │
│  │      • JOIN_ALIGNMENT: Need join key resolution          │  │
│  └──────────────────────────────────────────────────────────┘  │
│     ↓                                                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 3. Delta Execution (delta_engine.py)                    │  │
│  │                                                             │  │
│  │  Case A: CACHE_HIT                                       │  │
│  │    → Execute SQL directly                                │  │
│  │                                                             │  │
│  │  Case B: ROW_DELTA                                       │  │
│  │    1. Get candidate chunks from Candidate_Index          │  │
│  │    2. Filter by new predicate keywords                   │  │
│  │    3. Extract with LLM (all columns)                     │  │
│  │    4. INSERT new rows                                    │  │
│  │    5. Update Metadata_Registry                           │  │
│  │                                                             │  │
│  │  Case C: COLUMN_DELTA                                    │  │
│  │    1. Get existing row_ids from SQL table                │  │
│  │    2. Lookup Row_Provenance → chunk_ids                  │  │
│  │    3. Retrieve chunks                                    │  │
│  │    4. Extract new columns with LLM                       │  │
│  │    5. UPDATE existing rows                               │  │
│  │    6. Update Metadata_Registry                           │  │
│  │                                                             │  │
│  │  Case D: MIXED_DELTA                                     │  │
│  │    1. Execute ROW_DELTA for new rows                     │  │
│  │    2. Execute COLUMN_DELTA for existing rows             │  │
│  │                                                             │  │
│  │  Case E: JOIN_ALIGNMENT                                  │  │
│  │    1. Extract join key values from both tables           │  │
│  │    2. Run entity resolution on join keys                 │  │
│  │    3. Update tables with canonical forms                 │  │
│  │    4. Execute SQL join                                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│     ↓                                                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 4. Query Execution                                       │  │
│  │    - Execute SQL on materialized data                    │  │
│  │    - Apply canonical map for semantic rewriting          │  │
│  │    - Return results                                      │  │
│  └──────────────────────────────────────────────────────────┘  │
│     ↓                                                            │
│  Output: Query Results                                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Module Details

### 1. config.py
**Purpose:** Central configuration management

**Key Settings:**
- Database connection (PostgreSQL URI)
- LLM settings (Ollama URL, model)
- Chunking parameters (size, overlap)
- Entity resolution thresholds
- Caching configuration

### 2. data_layer.py
**Purpose:** Database abstraction and state management

**Key Classes:**
- `DataLayer`: Main database interface
- `RecursiveCharacterSplitter`: Text chunking
- `TextChunk`: Chunk data model

**Tables:**
- `raw_chunks`: Text storage
- `metadata_registry`: Completeness tracking
- `row_provenance`: Row → chunk mapping
- `candidate_index`: Sieve results

**Key Operations:**
- Chunk insertion/retrieval
- Metadata updates
- Provenance tracking
- Dynamic table creation

### 3. lattice_planner.py
**Purpose:** Workload analysis and MQO

**Key Classes:**
- `LatticePlanner`: Main planner
- `WorkloadLattice`: Lattice structure
- `TableInfo`, `ColumnInfo`: Schema metadata

**Key Operations:**
- SQL parsing with sqlglot
- Table/column extraction
- Predicate extraction
- Subsumption graph building
- Semantic type identification

**Algorithms:**
- Multi-Query Optimization (MQO)
- Semantic type heuristics
- Predicate subsumption

### 4. sieve_synthesizer.py
**Purpose:** Programmatic filtering synthesis

**Key Classes:**
- `SieveSynthesizer`: Main synthesizer
- `SieveResult`: Synthesis result

**Key Operations:**
- Sample analysis (spaCy NER, FlashText, regex)
- LLM code generation
- Iterative refinement
- Sieve application

**Tools:**
- spaCy: Named entity recognition
- FlashText: Fast keyword matching
- Regex: Pattern matching
- LLM: Code synthesis

### 5. extractor.py
**Purpose:** LLM-based data extraction

**Key Classes:**
- `ConstrainedExtractor`: Main extractor
- `OllamaClient`: LLM client
- `ExtractionResult`: Extraction output

**Key Operations:**
- Schema stabilization
- Batched extraction
- JSON parsing
- Caching
- Lazy enrichment

**Prompt Engineering:**
- Constrained key extraction
- Normalization instructions
- Null handling
- Format specification

### 6. entity_resolver.py
**Purpose:** Entity resolution and canonicalization

**Key Classes:**
- `EntityResolver`: Main resolver
- `UnionFind`: Clustering data structure
- `EntityMention`, `EntityCluster`: Data models

**Key Operations:**
- Blocking (bi-encoder + FAISS)
- Matching (cross-encoder)
- Clustering (Union-Find)
- Canonicalization (LLM)
- Query rewriting

**Models:**
- Bi-encoder: all-MiniLM-L6-v2 (384-dim)
- Cross-encoder: ms-marco-MiniLM-L-6-v2
- FAISS: IndexFlatIP (cosine similarity)

### 7. delta_engine.py
**Purpose:** Incremental query execution

**Key Classes:**
- `DeltaEngine`: Main engine
- `DeltaPlan`: Execution plan
- `DeltaType`: Delta type enum

**Key Operations:**
- Query analysis
- Delta calculation
- Row delta execution
- Column delta execution
- Join alignment

**Delta Types:**
1. **CACHE_HIT**: No extraction needed
2. **ROW_DELTA**: Extract new rows
3. **COLUMN_DELTA**: Enrich existing rows
4. **MIXED_DELTA**: Both row and column
5. **JOIN_ALIGNMENT**: Resolve join keys

### 8. quwarts_runner.py
**Purpose:** Main orchestration and CLI

**Key Classes:**
- `QuWARTSRunner`: Main runner
- `PreprocessingResult`, `QueryResult`: Result models

**Key Operations:**
- Full preprocessing pipeline
- Query execution
- Statistics reporting
- Cache management

**CLI Commands:**
```bash
python quwarts_runner.py <dataset> --preprocess
python quwarts_runner.py <dataset> --query "SELECT ..."
python quwarts_runner.py <dataset> --stats
python quwarts_runner.py <dataset> --clear-cache
```

## Data Flow

### Preprocessing Flow

```
Text Files
    ↓ [RecursiveCharacterSplitter]
Raw_Chunks (PostgreSQL)
    ↓ [SieveSynthesizer]
Candidate_Index
    ↓ [ConstrainedExtractor]
Extracted Records (JSON)
    ↓ [EntityResolver]
Normalized Records
    ↓ [DataLayer]
SQL Tables + Metadata_Registry + Row_Provenance
```

### Query Execution Flow

```
SQL Query
    ↓ [DeltaEngine.analyze_query]
DeltaPlan
    ↓ [DeltaEngine.execute_delta]
    ├─ CACHE_HIT → SQL Execution
    ├─ ROW_DELTA → Extract New Rows → SQL Execution
    ├─ COLUMN_DELTA → Enrich Rows → SQL Execution
    ├─ MIXED_DELTA → Extract + Enrich → SQL Execution
    └─ JOIN_ALIGNMENT → Resolve Keys → SQL Execution
    ↓
Query Results
```

## Key Algorithms

### 1. Recursive Character Splitting
```python
def split_text(text, chunk_size, overlap, separators):
    if not separators:
        return split_by_length(text, chunk_size)
    
    separator = separators[0]
    splits = text.split(separator)
    
    chunks = []
    current = ""
    
    for split in splits:
        if len(current + split) <= chunk_size:
            current += split + separator
        else:
            chunks.append(current)
            if len(split) > chunk_size:
                chunks.extend(split_text(split, chunk_size, overlap, separators[1:]))
                current = ""
            else:
                current = split + separator
    
    if current:
        chunks.append(current)
    
    return add_overlap(chunks, overlap)
```

### 2. Union-Find with Path Compression
```python
def find(x):
    if parent[x] != x:
        parent[x] = find(parent[x])  # Path compression
    return parent[x]

def union(x, y):
    root_x = find(x)
    root_y = find(y)
    
    if root_x == root_y:
        return False
    
    # Union by rank
    if rank[root_x] < rank[root_y]:
        parent[root_x] = root_y
    elif rank[root_x] > rank[root_y]:
        parent[root_y] = root_x
    else:
        parent[root_y] = root_x
        rank[root_x] += 1
    
    return True
```

### 3. Schema Stabilization
```python
def stabilize_schema(table, schema, samples):
    all_keys = []
    
    for chunk in samples:
        records = extract_without_constraints(chunk, table, schema)
        for record in records:
            all_keys.extend(record.keys())
    
    key_counts = Counter(all_keys)
    total = len(all_keys)
    
    frozen_keys = {
        key for key, count in key_counts.items()
        if count / total >= 0.20  # 20% threshold
    }
    
    # Ensure all schema columns are frozen
    frozen_keys.update(schema.keys())
    
    return frozen_keys
```

### 4. Delta Calculation
```python
def calculate_delta(query, metadata_registry):
    tables = extract_tables(query)
    columns = extract_columns(query)
    predicates = extract_predicates(query)
    
    missing_columns = []
    missing_predicates = []
    
    for table in tables:
        for column in columns[table]:
            if not is_materialized(table, column):
                missing_columns.append(column)
        
        for predicate in predicates[table]:
            if not is_materialized(table, predicate):
                missing_predicates.append(predicate)
    
    if not missing_columns and not missing_predicates:
        return CACHE_HIT
    elif missing_columns and missing_predicates:
        return MIXED_DELTA
    elif missing_columns:
        return COLUMN_DELTA
    elif missing_predicates:
        return ROW_DELTA
```

## Performance Considerations

### Bottlenecks
1. **LLM Calls**: Slowest operation (~2-3s per chunk)
2. **Entity Resolution**: O(n²) comparisons without blocking
3. **Database I/O**: Chunk retrieval for enrichment

### Optimizations
1. **Caching**: Cache extraction results by chunk hash
2. **Batching**: Process 5 chunks per LLM call
3. **Blocking**: Use FAISS for O(log n) similarity search
4. **Indexing**: B-tree on doc_id, GIN on JSONB
5. **Provenance**: Enables lazy enrichment without re-scanning

### Scalability
- **Chunks**: Can handle ~1M chunks (tested)
- **Records**: Limited by PostgreSQL (100M+ rows)
- **Mentions**: FAISS scales to 10M+ vectors
- **Queries**: Sub-second for cache hits, seconds for deltas

## Error Handling

### LLM Failures
- Retry with exponential backoff (3 attempts)
- Fallback to empty extraction on parse errors
- Log malformed responses for debugging

### Database Errors
- Transaction rollback on failures
- Graceful degradation (skip problematic chunks)
- Detailed error logging

### Sieve Synthesis Failures
- Fallback to keyword-only sieve
- Return all chunks if sieve fails (conservative)

## Future Enhancements

### Performance
- [ ] Distributed processing (Ray/Dask)
- [ ] GPU acceleration for embeddings
- [ ] Streaming extraction for large documents
- [ ] Query result caching

### Features
- [ ] Multi-language support
- [ ] Incremental schema evolution
- [ ] Confidence scores for extractions
- [ ] Active learning for sieve refinement
- [ ] Web UI for monitoring

### Robustness
- [ ] Better error recovery
- [ ] Checkpoint/resume for long runs
- [ ] Data validation and quality metrics
- [ ] Automated testing with synthetic data

## References

- **sqlglot**: SQL parsing and transpilation
- **sentence-transformers**: Semantic embeddings
- **FAISS**: Fast similarity search
- **spaCy**: NLP and NER
- **FlashText**: Fast keyword extraction
- **Ollama**: Local LLM serving
- **PostgreSQL**: Relational database with JSONB

---

**Version:** 1.0.0  
**Last Updated:** February 2026
