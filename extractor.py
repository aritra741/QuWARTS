"""
Constrained Global Extraction for QuWARTS.
Implements LLM-based extraction with schema stabilization and batching.
"""

import json
import logging
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
from collections import Counter
import hashlib

import requests
from openai import OpenAI

from token_counter import GLOBAL_COUNTER, count_tokens
from attribute_index import AttributeIndex, AttributeDiscovery

from config import (
    OLLAMA_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    OLLAMA_MAX_RETRIES,
    OLLAMA_RETRY_DELAY,
    EXTRACTION_BATCH_SIZE,
    EXTRACTION_TEMPERATURE,
    EXTRACTION_MAX_TOKENS,
    COLUMN_BATCH_SIZE,
    CHUNK_BATCH_SIZE,
    SCHEMA_SAMPLE_SIZE,
    SCHEMA_KEY_FREQUENCY_THRESHOLD,
    CACHE_DIR
)

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class ExtractionResult:
    """Result of extraction from a chunk."""
    chunk_id: str
    records: List[Dict[str, Any]]
    schema_keys: Set[str]
    extraction_time: float
    error: Optional[str] = None
    # Parallel to `records`: per-record {col: exact_quote_from_chunk}.
    # Used by _validate_record for span-grounding instead of value matching.
    # None when the LLM did not return span-grounded output.
    spans: Optional[List[Dict[str, str]]] = None


@dataclass
class StabilizedSchema:
    """Stabilized schema with frozen keys."""
    table_name: str
    frozen_keys: Set[str]
    key_frequencies: Dict[str, float]
    sample_size: int


# ============================================================================
# LLM Client
# ============================================================================

class OllamaClient:
    """Client for Ollama LLM API."""
    
    def __init__(
        self,
        base_url: str = OLLAMA_URL,
        model: str = OLLAMA_MODEL,
        timeout: int = OLLAMA_TIMEOUT
    ):
        """Initialize Ollama client."""
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        
        # Initialize OpenAI client (Ollama uses OpenAI-compatible API)
        self.client = OpenAI(
            base_url=base_url,
            api_key="ollama"  # Ollama doesn't require real API key
        )
        
        logger.info(f"Initialized Ollama client: {base_url} with model {model}")
    
    def generate(
        self,
        prompt: str,
        max_tokens: int = EXTRACTION_MAX_TOKENS,
        temperature: float = EXTRACTION_TEMPERATURE,
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Generate completion from Ollama.
        
        Args:
            prompt: User prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            system_prompt: Optional system prompt
            
        Returns:
            Generated text
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        for attempt in range(OLLAMA_MAX_RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=self.timeout
                )

                content = response.choices[0].message.content

                # Precise counting only: use complete server usage, otherwise
                # tokenize both prompt and completion with the strict tokenizer.
                usage = getattr(response, "usage", None)
                prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
                completion_tokens = (
                    getattr(usage, "completion_tokens", None) if usage else None
                )

                if prompt_tokens is not None and completion_tokens is not None:
                    recorded_in = int(prompt_tokens)
                    recorded_out = int(completion_tokens)
                elif prompt_tokens is not None and getattr(usage, "total_tokens", None) is not None:
                    recorded_in = usage.prompt_tokens
                    recorded_out = int(usage.total_tokens) - int(usage.prompt_tokens)
                else:
                    # If Ollama does not provide full usage, require local precise
                    # tokenizer for both prompt and completion.
                    input_text = " ".join(m["content"] for m in messages)
                    input_tok = count_tokens(input_text)
                    recorded_in = input_tok
                    recorded_out = count_tokens(content or "")

                GLOBAL_COUNTER.record(
                    input_tokens=recorded_in,
                    output_tokens=recorded_out,
                )

                return content

            except Exception as e:
                logger.warning(f"Ollama API error (attempt {attempt + 1}/{OLLAMA_MAX_RETRIES}): {e}")

                if attempt < OLLAMA_MAX_RETRIES - 1:
                    time.sleep(OLLAMA_RETRY_DELAY)
                else:
                    raise

        raise Exception("Failed to get response from Ollama after retries")


# ============================================================================
# Extractor
# ============================================================================

class ConstrainedExtractor:
    """
    Implements constrained global extraction with schema stabilization.
    """
    
    def __init__(self, llm_client: Optional[OllamaClient] = None, attribute_index: Optional[AttributeIndex] = None):
        """Initialize extractor."""
        import config as _config
        self.llm_client = llm_client or OllamaClient()
        self.cache_dir = _config.CACHE_DIR / "extractions"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Schema cache
        self.stabilized_schemas: Dict[str, StabilizedSchema] = {}
        
        # Attribute index for smart column delta
        self.attribute_index = attribute_index or AttributeIndex(cache_dir=_config.CACHE_DIR)
    
    # ========================================================================
    # Schema Stabilization
    # ========================================================================
    
    def stabilize_schema(
        self,
        table_name: str,
        schema: Dict[str, str],
        sample_chunks: List[str]
    ) -> StabilizedSchema:
        """
        Stabilize schema by extracting from sample chunks and freezing common keys.
        
        Args:
            table_name: Name of the table
            schema: Initial schema (column_name -> semantic_type)
            sample_chunks: Sample chunks for schema discovery
            
        Returns:
            StabilizedSchema with frozen keys
        """
        logger.info(f"Stabilizing schema for {table_name} with {len(sample_chunks)} samples")
        
        # Extract from sample chunks
        all_keys = []
        
        for chunk in sample_chunks[:SCHEMA_SAMPLE_SIZE]:
            try:
                # Extract without constraints to discover keys
                result = self._extract_single_chunk(
                    chunk,
                    table_name,
                    schema,
                    constrained_keys=None
                )
                
                # Collect keys from all records
                for record in result.records:
                    if isinstance(record, dict):
                        all_keys.extend(record.keys())
            
            except Exception as e:
                logger.warning(f"Error extracting from sample chunk: {e}")
        
        # Calculate key frequencies
        key_counts = Counter(all_keys)
        total_records = len(all_keys)
        
        key_frequencies = (
            {
                key: count / total_records
                for key, count in key_counts.items()
            }
            if total_records > 0
            else {}
        )
        
        # Freeze keys above threshold
        frozen_keys = {
            key for key, freq in key_frequencies.items()
            if freq >= SCHEMA_KEY_FREQUENCY_THRESHOLD
        }
        
        # Ensure all schema columns are frozen
        frozen_keys.update(schema.keys())
        
        stabilized = StabilizedSchema(
            table_name=table_name,
            frozen_keys=frozen_keys,
            key_frequencies=key_frequencies,
            sample_size=len(sample_chunks)
        )
        
        # Cache stabilized schema
        self.stabilized_schemas[table_name] = stabilized
        
        logger.info(f"Stabilized schema for {table_name}: {len(frozen_keys)} frozen keys")
        logger.debug(f"Frozen keys: {frozen_keys}")
        
        return stabilized
    
    def get_stabilized_schema(self, table_name: str) -> Optional[StabilizedSchema]:
        """Get cached stabilized schema."""
        return self.stabilized_schemas.get(table_name)
    
    # ========================================================================
    # Extraction
    # ========================================================================

    # Semantic types that map to numeric SQL columns.
    _NUMERIC_SEM_TYPES: Set[str] = {"MONEY", "QUANTITY", "QUANTITY_COUNT"}
    # Subset of numeric types that represent discrete cumulative counts
    # (e.g., tallies of events, items, or achievements) rather than continuous measures.
    _COUNT_SEM_TYPES: Set[str] = {"QUANTITY_COUNT"}

    def _build_schema_desc(
        self,
        schema: Dict[str, str],
        keys_to_use,
        normalization_hints: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        """
        Build the schema description block for an extraction prompt.

        Each column line carries:
          - Output type tag (text / numeric) so the LLM knows the JSON type.
          - Normalization examples when the workload has equality predicates
            for that column.

        Normalization examples are ALWAYS framing examples, never allowlists.
        The workload may contain both a filtered query (WHERE country = 'USA')
        and an unrestricted one (SELECT country FROM …).  In that case the LLM
        must still extract every country value it finds — the hints only tell it
        *how to write* values that are variants of a known form (e.g. write
        "USA" not "United States", "The United States", or "U.S.").  The
        instruction is: normalize to the example form when the meaning matches,
        but never skip values that have no matching example.
        """
        lines = []
        for col_name in keys_to_use:
            sem_type = schema.get(col_name, "OTHER")
            is_count = sem_type in self._COUNT_SEM_TYPES
            is_numeric = sem_type in self._NUMERIC_SEM_TYPES
            type_tag = "numeric, count" if is_count else ("numeric" if is_numeric else "text")

            hints = (normalization_hints or {}).get(col_name, [])
            if hints:
                quoted = ", ".join(
                    str(h) if is_numeric else f'"{h}"' for h in hints
                )
                # Framing: examples for output format, not an exhaustive list.
                # "United States" → "USA", "one thousand" → 1000.
                # Still extract every value found, even those not in the examples.
                if is_count:
                    hint_note = (
                        f" — total count examples: [{quoted}]. "
                        f"Extract the TOTAL cumulative count of discrete items/events."
                    )
                elif is_numeric:
                    hint_note = (
                        f" — output/unit examples: [{quoted}]. "
                        f"If the source presents the same quantity in multiple units "
                        f"or scales, output the value in the same unit convention as "
                        f"these examples. Extract ALL values you find, not only the "
                        f"ones in this list."
                    )
                else:
                    hint_note = (
                        f" — output format examples: [{quoted}]. "
                        f"If the text uses a synonym, abbreviation, or alias for one "
                        f"of these examples, write the example form exactly "
                        f"(e.g. write \"{hints[0]}\" not a paraphrase). "
                        f"Extract ALL values you find, not only the ones in this list."
                    )
            else:
                if is_count:
                    hint_note = (
                        " — extract the TOTAL cumulative count of discrete items/events "
                        "as a number."
                    )
                else:
                    hint_note = ""

            lines.append(f"  - {col_name} ({type_tag}){hint_note}")
        return "\n".join(lines)

    def _build_generic_example(
        self,
        schema: Dict[str, str],
        keys_to_use,
        n_passages: int,
    ) -> str:
        """Build a simple DocETL-style JSON shape example."""
        col_list = list(keys_to_use)
        text_col = next(
            (c for c in col_list if schema.get(c, "OTHER") not in self._NUMERIC_SEM_TYPES),
            col_list[0] if col_list else "field_A",
        )
        num_col = next(
            (c for c in col_list if schema.get(c, "OTHER") in self._NUMERIC_SEM_TYPES),
            None,
        )
        parts = [f'"{text_col}": "<text value or null>"']
        if num_col:
            parts.append(f'"{num_col}": 123')
        record_example = "{" + ", ".join(parts) + "}"
        return (
            f'{{"passage_1": [{record_example}], '
            f'"passage_2": [], ..., "passage_{n_passages}": []}}'
        )

    def _build_multi_chunk_prompt(
        self,
        chunk_texts: List[str],
        table_name: str,
        schema: Dict[str, str],
        constrained_keys: Optional[Set[str]] = None,
        normalization_hints: Optional[Dict[str, List[str]]] = None,
        entity_col: Optional[str] = None,
    ) -> str:
        """
        Build a single prompt that asks the LLM to extract from N passages at once.

        The LLM returns a JSON object keyed by "passage_1" … "passage_N".  Each
        value is the same JSON array format as the single-chunk prompts.  This
        amortises per-request overhead (HTTP round-trip, KV-cache setup) across
        N chunks instead of paying it N times.

        Query-awareness
        ───────────────
        The schema description includes per-column type tags (text / numeric)
        and, when the workload has equality predicates, the exact literal values
        those predicates expect — so 'USA', 'one thousand', 'United States' all
        get normalised to the query-expected form at extraction time, not via a
        post-processing heuristic.
        """
        keys_to_use = constrained_keys if constrained_keys else schema.keys()

        # Schema description: annotated with output type and query-expected values.
        schema_desc = self._build_schema_desc(schema, keys_to_use, normalization_hints)

        entity_section = self._build_entity_section(entity_col)

        passage_blocks = "\n\n".join(
            f"=== Passage {i + 1} ===\n{text}"
            for i, text in enumerate(chunk_texts)
        )

        n = len(chunk_texts)
        example_keys = self._build_generic_example(schema, keys_to_use, n)
        format_contract = (
            "OUTPUT FORMAT (MANDATORY): Return ONLY JSON. "
            "Top-level must be an object with keys passage_1..passage_N. "
            "Each passage key maps to an array of plain record objects."
        )

        # Numeric type rule — surfaced explicitly so the 7B model internalises it.
        has_numeric = any(
            schema.get(c, "OTHER") in self._NUMERIC_SEM_TYPES for c in keys_to_use
        )
        has_count = any(
            schema.get(c, "OTHER") in self._COUNT_SEM_TYPES for c in keys_to_use
        )
        numeric_rule = (
            "- Numeric columns: always return a JSON number (e.g. 1000000), "
            "NEVER a text string (e.g. NOT \"one million\", NOT \"£1.2m\").\n"
            if has_numeric else ""
        )
        count_rule = (
            "- Count columns (marked 'numeric, count'): extract the TOTAL cumulative "
            "count of discrete items or events. If the text lists individual items "
            "(e.g., 'products A, B, and C'), count them and return the total (3). "
            "Return the count, not individual identifiers or timestamps.\n"
            if has_count else ""
        )
        scalar_rule = (
            "- Every field must be a single scalar value (string/number/null), "
            "never a list/array and never a nested object. "
            "For text and regular numeric fields: if multiple candidates are mentioned, "
            "prefer explicitly current or present-tense facts "
            "(e.g. 'currently', 'is with', 'as of now'); if no current cue "
            "exists, choose the most recent value mentioned; if still ambiguous, choose "
            "the first clear canonical value. "
            "For 'numeric, count' fields: see the count rule above — return "
            "the total count, not individual identifiers.\n"
        )

        return (
            f'Extract structured data for table "{table_name}" from each passage below.\n\n'
            f"{format_contract}\n\n"
            f"Schema (extract ONLY these fields — do not add any other fields):\n"
            f"{schema_desc}\n"
            f"{entity_section}\n\n"
            f"Rules:\n"
            f"- Return a JSON object with keys passage_1 … passage_{n}.\n"
            f"- Each value is a JSON array of record objects ([] if nothing found).\n"
            f"- Record fields must be plain scalar values (string/number/null), not nested objects.\n"
            f"- Use null (never empty string) for any absent value.\n"
            f"- For any value that requires time-relative calculation, use reference year 2025.\n"
            f"{numeric_rule}"
            f"{count_rule}"
            f"{scalar_rule}"
            f"- If a passage discusses multiple entities, return one record per entity.\n\n"
            f"Format example: {example_keys}\n\n"
            f"{passage_blocks}\n\n"
            f"{format_contract}\n"
            f"Return ONLY the JSON object, no other text."
        )

    def _parse_multi_chunk_response(
        self,
        response: str,
        chunk_ids: List[str],
        constrained_keys: Optional[Set[str]] = None,
        extraction_time: float = 0.0,
    ) -> List[ExtractionResult]:
        """
        Parse the multi-chunk LLM response into one ExtractionResult per chunk.

        Tries to decode the response as a JSON object keyed by "passage_N".
        Falls back to an empty result for any missing or unparseable passage.
        """
        results: List[ExtractionResult] = []
        parsed: Dict[str, Any] = {}

        # Strip markdown fences if present
        clean = response.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:])
            clean = clean.rstrip("`").strip()

        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            # Try extracting a JSON object from anywhere in the response
            import re as _re
            m = _re.search(r"\{.*\}", clean, _re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group())
                except json.JSONDecodeError:
                    pass

        for i, chunk_id in enumerate(chunk_ids):
            key = f"passage_{i + 1}"
            raw_records = parsed.get(key, [])

            if not isinstance(raw_records, list):
                raw_records = []

            records: List[Dict[str, Any]] = []
            spans_list: List[Dict[str, str]] = []

            for rec in raw_records:
                if not isinstance(rec, dict):
                    continue
                # Unpack span-grounded format: each field may be
                #   {"value": <val>, "span": "<quote>"}  OR a plain scalar
                #   (older LLM responses / Pass-1 single-column calls).
                flat_record: Dict[str, Any] = {}
                span_record: Dict[str, str] = {}
                for col, cell in rec.items():
                    if isinstance(cell, dict) and "value" in cell:
                        flat_record[col] = cell.get("value")
                        raw_span = cell.get("span")
                        if raw_span and isinstance(raw_span, str):
                            span_record[col] = raw_span
                    else:
                        # Plain scalar — treat as value with no span evidence.
                        flat_record[col] = cell

                # Apply constrained_keys filter
                if constrained_keys:
                    flat_record = {
                        k: v for k, v in flat_record.items()
                        if k in constrained_keys or k == "_entity"
                    }
                    span_record = {k: v for k, v in span_record.items() if k in constrained_keys}

                records.append(flat_record)
                spans_list.append(span_record)

            schema_keys: Set[str] = set()
            for rec in records:
                schema_keys.update(rec.keys())

            results.append(ExtractionResult(
                chunk_id=chunk_id,
                records=records,
                schema_keys=schema_keys,
                extraction_time=extraction_time / max(len(chunk_ids), 1),
                spans=spans_list if spans_list else None,
            ))

        return results

    def _extract_chunk_group_safe(
        self,
        chunk_texts: List[str],
        chunk_ids: List[str],
        table_name: str,
        schema: Dict[str, str],
        constrained_keys: Optional[Set[str]] = None,
        normalization_hints: Optional[Dict[str, List[str]]] = None,
        entity_col: Optional[str] = None,
    ) -> List[ExtractionResult]:
        """
        Thread-safe wrapper: build prompt for N chunks, call LLM once, parse response.

        Returns one ExtractionResult per chunk in chunk_ids.
        On error, returns empty ExtractionResult objects with the error string.
        """
        import time as _time
        start = _time.time()
        try:
            prompt = self._build_multi_chunk_prompt(
                chunk_texts, table_name, schema,
                constrained_keys, normalization_hints, entity_col,
            )
            response = self.llm_client.generate(
                prompt,
                max_tokens=EXTRACTION_MAX_TOKENS,
                temperature=EXTRACTION_TEMPERATURE,
            )
            elapsed = _time.time() - start
            results = self._parse_multi_chunk_response(
                response, chunk_ids, constrained_keys, elapsed
            )
            for er in results:
                er.records = self._normalize_records_for_schema(er.records, schema)
            return results
        except Exception as e:
            logger.error(
                f"Error extracting chunk group "
                f"{chunk_ids}: {e}"
            )
            elapsed = _time.time() - start
            return [
                ExtractionResult(
                    chunk_id=cid,
                    records=[],
                    schema_keys=set(),
                    extraction_time=elapsed / max(len(chunk_ids), 1),
                    error=str(e),
                )
                for cid in chunk_ids
            ]

    # ========================================================================
    
    def _split_schema_into_batches(
        self,
        schema: Dict[str, str],
        constrained_keys: Optional[Set[str]],
        normalization_hints: Optional[Dict[str, List[str]]],
        col_batch_size: Optional[int] = None,
    ) -> List[tuple]:
        """
        Split a wide schema into column batches of at most `col_batch_size`
        (defaults to the global COLUMN_BATCH_SIZE setting).

        Pass a value larger than len(schema) to disable batching and send all
        columns in a single LLM call — safe for entity-first extraction where
        the context is already focused on one specific entity.

        Returns a list of (col_batch_schema, batch_constrained_keys,
        batch_normalization_hints) tuples.
        """
        batch_size = col_batch_size if col_batch_size is not None else COLUMN_BATCH_SIZE
        items = list(schema.items())
        batches = []
        for i in range(0, len(items), batch_size):
            col_batch = dict(items[i : i + batch_size])
            batch_ck = (
                constrained_keys & col_batch.keys()
                if constrained_keys
                else None
            )
            batch_nh = (
                {k: v for k, v in normalization_hints.items() if k in col_batch}
                if normalization_hints
                else None
            )
            batches.append((col_batch, batch_ck, batch_nh))
        return batches

    def _merge_column_batches(
        self,
        chunk_id: str,
        batch_map: Dict[int, ExtractionResult],
        total_batches: int,
    ) -> ExtractionResult:
        """
        Merge partial ExtractionResults from column-batch LLM calls.

        Merge strategy:
        - If all non-empty batches return the same number of records, zip them
          by position (record 0 from batch 0 + record 0 from batch 1 = merged
          record 0).
        - If counts differ (LLM returned different numbers of entities for
          different column groups), use the largest batch as the base and merge
          in additional fields from other batches at matching positions.  Any
          batch records beyond the base length are appended as partial records.
        """
        records_per_batch: List[List[Dict[str, Any]]] = []
        total_time = 0.0
        last_error: Optional[str] = None

        for batch_idx in range(total_batches):
            if batch_idx not in batch_map:
                continue
            result = batch_map[batch_idx]
            total_time += result.extraction_time
            if result.error:
                last_error = result.error
                continue
            if result.records:
                records_per_batch.append(result.records)

        if not records_per_batch:
            return ExtractionResult(
                chunk_id=chunk_id,
                records=[],
                schema_keys=set(),
                extraction_time=total_time,
                error=last_error,
            )

        counts = [len(r) for r in records_per_batch]

        if all(c == counts[0] for c in counts):
            # Happy path: all batches agree on entity count — zip by position.
            merged_records = []
            for idx in range(counts[0]):
                merged: Dict[str, Any] = {}
                for batch_records in records_per_batch:
                    merged.update(batch_records[idx])
                merged_records.append(merged)
        else:
            # Counts disagree — use the largest batch as base, merge others in
            # by position, and append any overflow records as partial entries.
            base = max(records_per_batch, key=len)
            merged_records = [dict(r) for r in base]
            for batch_records in records_per_batch:
                if batch_records is base:
                    continue
                for i, record in enumerate(batch_records):
                    if i < len(merged_records):
                        for k, v in record.items():
                            if k not in merged_records[i]:
                                merged_records[i][k] = v
                    else:
                        merged_records.append(dict(record))

        schema_keys: Set[str] = set()
        for record in merged_records:
            schema_keys.update(record.keys())

        return ExtractionResult(
            chunk_id=chunk_id,
            records=merged_records,
            schema_keys=schema_keys,
            extraction_time=total_time,
            error=last_error,
        )

    def extract_batch(
        self,
        chunks: List[str],
        chunk_ids: List[str],
        table_name: str,
        schema: Dict[str, str],
        constrained_keys: Optional[Set[str]] = None,
        normalization_hints: Optional[Dict[str, List[str]]] = None,
        entity_col: Optional[str] = None,
        col_batch_size_override: Optional[int] = None,
    ) -> List[ExtractionResult]:
        """
        Extract data from all chunks using chunk-group × column-batch parallelism.

        Two-dimensional batching strategy:
          - CHUNK_BATCH_SIZE chunks are sent in one LLM call (multi-passage prompt).
            This amortises per-request overhead across N chunks.
          - COLUMN_BATCH_SIZE columns are sent per call so the 7B model stays in
            its reliable extraction range.

        For C chunks and K column batches, total LLM calls =
          ceil(C / CHUNK_BATCH_SIZE) × K
        vs the previous ceil(C / 1) × K.  The speedup is CHUNK_BATCH_SIZE × overhead_ratio.

        Merging: results from all K column-batch calls for the same chunk are
        merged by _merge_column_batches before being returned.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from config import MAX_PARALLEL_REQUESTS

        col_batches = self._split_schema_into_batches(
            schema, constrained_keys, normalization_hints,
            col_batch_size=col_batch_size_override,
        )
        n_col_batches = len(col_batches)

        # Split chunks into groups of CHUNK_BATCH_SIZE, skipping cached ones.
        pre_cached: List[ExtractionResult] = []
        # chunk_id -> {col_batch_idx -> ExtractionResult}
        chunk_batch_map: Dict[str, Dict[int, ExtractionResult]] = {}

        # Build groups of uncached chunks
        groups: List[tuple] = []   # [(chunk_texts, chunk_ids_in_group)]
        current_texts: List[str] = []
        current_ids: List[str] = []

        for chunk, chunk_id in zip(chunks, chunk_ids):
            cached = self._get_cached_result(chunk_id, table_name)
            if cached:
                pre_cached.append(cached)
                continue
            chunk_batch_map[chunk_id] = {}
            current_texts.append(chunk)
            current_ids.append(chunk_id)
            if len(current_texts) == CHUNK_BATCH_SIZE:
                groups.append((list(current_texts), list(current_ids)))
                current_texts.clear()
                current_ids.clear()

        if current_texts:   # remainder group
            groups.append((current_texts, current_ids))

        total_tasks = len(groups) * n_col_batches
        logger.info(
            f"Extracting {len(chunks)} chunks for '{table_name}': "
            f"{len(groups)} chunk-groups of ≤{CHUNK_BATCH_SIZE}, "
            f"{n_col_batches} column batch(es) of ≤{COLUMN_BATCH_SIZE} "
            f"= {total_tasks} LLM calls, {MAX_PARALLEL_REQUESTS} workers"
            + (f", entity_col='{entity_col}'" if entity_col else "")
        )

        future_to_key: Dict = {}
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as executor:
            for group_texts, group_ids in groups:
                for batch_idx, (col_batch, batch_ck, batch_nh) in enumerate(col_batches):
                    if len(group_texts) == 1:
                        future = executor.submit(
                            self._extract_single_chunk_safe,
                            group_texts[0], group_ids[0], table_name,
                            col_batch, batch_ck, batch_nh, entity_col,
                        )
                    else:
                        future = executor.submit(
                            self._extract_chunk_group_safe,
                            group_texts, group_ids, table_name,
                            col_batch, batch_ck, batch_nh, entity_col,
                        )
                    future_to_key[future] = (group_ids, batch_idx)

            completed = 0
            for future in as_completed(future_to_key):
                group_ids, batch_idx = future_to_key[future]
                completed += 1
                if completed % 100 == 0 or completed == total_tasks:
                    logger.info(f"  {completed}/{total_tasks} tasks done")
                try:
                    raw_result = future.result()
                    group_results = (
                        [raw_result] if isinstance(raw_result, ExtractionResult)
                        else raw_result
                    )
                    for er in group_results:
                        chunk_batch_map[er.chunk_id][batch_idx] = er
                except Exception as e:
                    logger.error(f"Error in group {group_ids} batch {batch_idx}: {e}")
                    for cid in group_ids:
                        chunk_batch_map[cid][batch_idx] = ExtractionResult(
                            chunk_id=cid,
                            records=[],
                            schema_keys=set(),
                            extraction_time=0.0,
                            error=str(e),
                        )

        # Merge column batches per chunk and cache the unified result.
        all_results: List[ExtractionResult] = list(pre_cached)
        for chunk_id, batch_map in chunk_batch_map.items():
            merged = self._merge_column_batches(chunk_id, batch_map, n_col_batches)
            self._cache_result(chunk_id, table_name, merged)
            all_results.append(merged)

        return all_results
    
    def _extract_single_chunk_safe(
        self,
        chunk: str,
        chunk_id: str,
        table_name: str,
        schema: Dict[str, str],
        constrained_keys: Optional[Set[str]] = None,
        normalization_hints: Optional[Dict[str, List[str]]] = None,
        entity_col: Optional[str] = None,
    ) -> ExtractionResult:
        """Thread-safe wrapper for single chunk extraction."""
        try:
            result = self._extract_single_chunk(
                chunk,
                table_name,
                schema,
                constrained_keys,
                normalization_hints,
                entity_col,
            )
            result.chunk_id = chunk_id
            return result
        except Exception as e:
            logger.error(f"Error in chunk {chunk_id}: {e}")
            return ExtractionResult(
                chunk_id=chunk_id,
                records=[],
                schema_keys=set(),
                extraction_time=0.0,
                error=str(e)
            )
    
    def extract_batch_with_predicates(
        self,
        chunks: List[str],
        chunk_ids: List[str],
        table_name: str,
        schema: Dict[str, str],
        constrained_keys: Optional[Set[str]] = None,
        predicates: Optional[List[str]] = None,
        normalization_hints: Optional[Dict[str, List[str]]] = None,
        entity_col: Optional[str] = None,
    ) -> List[ExtractionResult]:
        """
        Extract data matching specific predicates (used by delta engine row-delta).

        Uses the same column-batching strategy as extract_batch to keep each
        LLM call within the 7B model's reliable range (≤ COLUMN_BATCH_SIZE keys).
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from config import MAX_PARALLEL_REQUESTS

        col_batches = self._split_schema_into_batches(
            schema, constrained_keys, normalization_hints
        )
        n_batches = len(col_batches)
        pred_key = "_".join(sorted(predicates or []))

        pre_cached: List[ExtractionResult] = []
        chunk_batch_map: Dict[str, Dict[int, ExtractionResult]] = {}
        future_to_key: Dict = {}

        logger.info(
            f"Extracting {len(chunks)} chunks for '{table_name}' with predicates: "
            f"{n_batches} column batch(es) of ≤{COLUMN_BATCH_SIZE} cols each, "
            f"{MAX_PARALLEL_REQUESTS} parallel workers"
        )

        # Build chunk groups (same pattern as extract_batch)
        groups: List[tuple] = []
        current_texts: List[str] = []
        current_ids: List[str] = []

        for chunk, chunk_id in zip(chunks, chunk_ids):
            cache_key = f"{chunk_id}_{table_name}_{pred_key}"
            cached = self._get_cached_result(cache_key, table_name)
            if cached:
                pre_cached.append(cached)
                continue
            chunk_batch_map[chunk_id] = {}
            current_texts.append(chunk)
            current_ids.append(chunk_id)
            if len(current_texts) == CHUNK_BATCH_SIZE:
                groups.append((list(current_texts), list(current_ids)))
                current_texts.clear()
                current_ids.clear()

        if current_texts:
            groups.append((current_texts, current_ids))

        total_tasks = len(groups) * n_batches
        logger.info(
            f"  {len(groups)} chunk-groups × {n_batches} col-batches = {total_tasks} tasks"
        )

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as executor:
            for group_texts, group_ids in groups:
                for batch_idx, (col_batch, batch_ck, batch_nh) in enumerate(col_batches):
                    # For predicate extraction we still use the per-chunk method so
                    # predicate filtering is applied inside the call.  We wrap it
                    # in a group loop to stay consistent with the new architecture.
                    future = executor.submit(
                        self._extract_chunk_group_safe,
                        group_texts, group_ids, table_name,
                        col_batch, batch_ck, batch_nh, entity_col,
                    )
                    future_to_key[future] = (group_ids, batch_idx)

            completed = 0
            for future in as_completed(future_to_key):
                group_ids_fut, batch_idx = future_to_key[future]
                completed += 1
                if completed % 100 == 0 or completed == total_tasks:
                    logger.info(f"  {completed}/{total_tasks} tasks done")
                try:
                    group_results = future.result()
                    for er in group_results:
                        chunk_batch_map[er.chunk_id][batch_idx] = er
                except Exception as e:
                    logger.error(f"Error group {group_ids_fut} batch {batch_idx}: {e}")
                    for cid in group_ids_fut:
                        chunk_batch_map[cid][batch_idx] = ExtractionResult(
                            chunk_id=cid,
                            records=[],
                            schema_keys=set(),
                            extraction_time=0.0,
                            error=str(e),
                        )

        all_results: List[ExtractionResult] = list(pre_cached)
        for chunk_id, batch_map in chunk_batch_map.items():
            merged = self._merge_column_batches(chunk_id, batch_map, n_batches)
            cache_key = f"{chunk_id}_{table_name}_{pred_key}"
            self._cache_result(cache_key, table_name, merged)
            all_results.append(merged)

        return all_results
    
    def _extract_single_chunk_with_predicates(
        self,
        chunk: str,
        chunk_id: str,
        table_name: str,
        schema: Dict[str, str],
        constrained_keys: Optional[Set[str]] = None,
        predicates: Optional[List[str]] = None,
        normalization_hints: Optional[Dict[str, List[str]]] = None,
        entity_col: Optional[str] = None,
    ) -> ExtractionResult:
        """Extract data matching specific predicates."""
        start_time = time.time()
        
        # Build extraction prompt with predicate filtering
        prompt = self._build_extraction_prompt_with_predicates(
            chunk,
            table_name,
            schema,
            constrained_keys,
            predicates,
            normalization_hints,
            entity_col,
        )
        
        # Call extraction model, then run a dedicated JSON-repair pass if needed.
        parse_keys = (
            [k for k in schema.keys() if k in constrained_keys]
            if constrained_keys
            else list(schema.keys())
        )
        response = self.llm_client.generate(
            prompt,
            max_tokens=EXTRACTION_MAX_TOKENS,
            temperature=EXTRACTION_TEMPERATURE,
        )
        try:
            records = self._parse_extraction_response(response, constrained_keys, parse_keys)
        except ValueError as first_error:
            repaired = self._repair_extraction_response(response, parse_keys)
            try:
                records = self._parse_extraction_response(repaired, constrained_keys, parse_keys)
            except ValueError as repair_error:
                raise ValueError(
                    "Failed to parse extraction output after JSON repair pass: "
                    f"initial_error={first_error}; repair_error={repair_error}"
                )
        records = self._normalize_records_for_schema(records, schema)
        
        # Filter records by predicates if specified
        if predicates and records:
            records = self._filter_records_by_predicates(records, predicates)
        
        # Collect schema keys
        schema_keys = set()
        for record in records:
            schema_keys.update(record.keys())
        
        extraction_time = time.time() - start_time
        
        return ExtractionResult(
            chunk_id=chunk_id,
            records=records,
            schema_keys=schema_keys,
            extraction_time=extraction_time
        )
    
    def _build_extraction_prompt_with_predicates(
        self,
        chunk: str,
        table_name: str,
        schema: Dict[str, str],
        constrained_keys: Optional[Set[str]] = None,
        predicates: Optional[List[str]] = None,
        normalization_hints: Optional[Dict[str, List[str]]] = None,
        entity_col: Optional[str] = None,
    ) -> str:
        """Build extraction prompt with predicate filtering."""
        keys_to_use = constrained_keys if constrained_keys else schema.keys()
        schema_desc = self._build_schema_desc(schema, keys_to_use, normalization_hints)

        predicate_str = ""
        if predicates:
            predicate_str = (
                "\nIMPORTANT: Only extract records that match ALL of these conditions:\n"
                + "".join(f"  - {p}\n" for p in predicates)
                + "Do NOT extract records that don't match these conditions.\n"
            )

        has_numeric = any(
            schema.get(c, "OTHER") in self._NUMERIC_SEM_TYPES for c in keys_to_use
        )
        has_count = any(
            schema.get(c, "OTHER") in self._COUNT_SEM_TYPES for c in keys_to_use
        )
        numeric_rule = (
            "- Numeric columns: return a JSON number (e.g. 1000000), "
            "NEVER a text string.\n"
            if has_numeric else ""
        )
        count_rule = (
            "- Count columns (marked 'numeric, count'): extract the TOTAL cumulative "
            "count of discrete items/events. If the text lists individual items, "
            "count them and return the total. Return the count, not identifiers.\n"
            if has_count else ""
        )
        entity_section = self._build_entity_section(entity_col)

        format_contract = (
            "OUTPUT FORMAT (MANDATORY): Return ONLY a JSON array of objects. "
            "No markdown, no prose, no code fences."
        )

        prompt = (
            f'Extract data from the following text for table "{table_name}".\n\n'
            f"{format_contract}\n\n"
            f"Schema (extract ONLY these fields):\n{schema_desc}\n"
            f"{predicate_str}"
            f"{entity_section}\n\n"
            f"Rules:\n"
            f"- Return a JSON array of objects, one per entity found.\n"
            f"- Use null (not empty string) for any absent value.\n"
            f"- If no matching data is found, return [].\n"
            f"- For any value that requires time-relative calculation, use reference year 2025.\n"
            f"{numeric_rule}"
            f"{count_rule}"
            f"\nText:\n{chunk}\n\n"
            f"{format_contract}\n"
            f"Output (JSON only):"
        )
        return prompt
    
    def _filter_records_by_predicates(
        self,
        records: List[Dict[str, Any]],
        predicates: List[str]
    ) -> List[Dict[str, Any]]:
        """Filter extracted records by predicates."""
        filtered = []
        
        for record in records:
            matches_all = True
            
            for pred in predicates:
                # Parse predicate (e.g., "age > 25")
                parts = pred.split()
                if len(parts) >= 3:
                    col = parts[0]
                    op = parts[1]
                    val_str = ' '.join(parts[2:]).strip("'\"")
                    
                    if col in record:
                        record_val = record[col]
                        
                        try:
                            # Try numeric comparison
                            if op == '>':
                                if not (float(record_val) > float(val_str)):
                                    matches_all = False
                                    break
                            elif op == '<':
                                if not (float(record_val) < float(val_str)):
                                    matches_all = False
                                    break
                            elif op == '>=':
                                if not (float(record_val) >= float(val_str)):
                                    matches_all = False
                                    break
                            elif op == '<=':
                                if not (float(record_val) <= float(val_str)):
                                    matches_all = False
                                    break
                            elif op == '=' or op == '==':
                                if str(record_val).lower() != val_str.lower():
                                    matches_all = False
                                    break
                            elif op == '!=' or op == '<>':
                                if str(record_val).lower() == val_str.lower():
                                    matches_all = False
                                    break
                        except (ValueError, TypeError):
                            # String comparison fallback
                            if op == '=' or op == '==':
                                if str(record_val).lower() != val_str.lower():
                                    matches_all = False
                                    break
                            elif op == '!=' or op == '<>':
                                if str(record_val).lower() == val_str.lower():
                                    matches_all = False
                                    break
                    else:
                        # Column not in record, doesn't match
                        matches_all = False
                        break
            
            if matches_all:
                filtered.append(record)
        
        return filtered
    
    def _extract_single_chunk(
        self,
        chunk: str,
        table_name: str,
        schema: Dict[str, str],
        constrained_keys: Optional[Set[str]] = None,
        normalization_hints: Optional[Dict[str, List[str]]] = None,
        entity_col: Optional[str] = None,
    ) -> ExtractionResult:
        """Extract data from a single chunk."""
        start_time = time.time()
        parse_keys = (
            [k for k in schema.keys() if k in constrained_keys]
            if constrained_keys
            else list(schema.keys())
        )
        subchunks = self._split_text_for_iterative_extraction(chunk, max_tokens=500)

        if len(subchunks) == 1:
            # Build extraction prompt
            prompt = self._build_extraction_prompt(
                chunk,
                table_name,
                schema,
                constrained_keys,
                normalization_hints,
                entity_col,
            )

            # Call extraction model, then run a dedicated JSON-repair pass if needed.
            response = self.llm_client.generate(
                prompt,
                max_tokens=EXTRACTION_MAX_TOKENS,
                temperature=EXTRACTION_TEMPERATURE,
            )
            try:
                records = self._parse_extraction_response(response, constrained_keys, parse_keys)
            except ValueError as first_error:
                repaired = self._repair_extraction_response(response, parse_keys)
                try:
                    records = self._parse_extraction_response(repaired, constrained_keys, parse_keys)
                except ValueError as repair_error:
                    raise ValueError(
                        "Failed to parse extraction output after JSON repair pass: "
                        f"initial_error={first_error}; repair_error={repair_error}"
                    )
            records = self._normalize_records_for_schema(records, schema)
        else:
            records = self._extract_single_chunk_iterative(
                subchunks=subchunks,
                table_name=table_name,
                schema=schema,
                constrained_keys=constrained_keys,
                normalization_hints=normalization_hints,
                entity_col=entity_col,
            )
        
        # Collect schema keys
        schema_keys = set()
        for record in records:
            schema_keys.update(record.keys())
        
        extraction_time = time.time() - start_time
        
        return ExtractionResult(
            chunk_id="",  # Will be set by caller
            records=records,
            schema_keys=schema_keys,
            extraction_time=extraction_time
        )

    def _split_text_for_iterative_extraction(
        self,
        text: str,
        max_tokens: int = 500,
    ) -> List[str]:
        """Split long text into whitespace-token chunks for iterative extraction."""
        words = text.split()
        if len(words) <= max_tokens:
            return [text]
        chunks: List[str] = []
        for i in range(0, len(words), max_tokens):
            chunks.append(" ".join(words[i : i + max_tokens]))
        return chunks

    @staticmethod
    def _is_missing_value(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            s = value.strip().lower()
            return s in {"", "null", "none", "unknown", "n/a"}
        return False

    @staticmethod
    def _normalize_for_match(text: str) -> str:
        return " ".join(text.lower().replace(",", "").split())

    def _value_grounded_in_text(self, value: Any, chunk_text: str) -> bool:
        """
        Require extracted/replacement values to be evidenced in the current chunk.
        This prevents iterative refinement from "improving" values via hallucination.
        """
        if value is None:
            return True
        raw_text = chunk_text or ""
        if not raw_text:
            return False

        text_lc = raw_text.lower()
        text_norm = self._normalize_for_match(raw_text)

        # Numeric grounding: match either exact surface form or comma-stripped form.
        if isinstance(value, (int, float)):
            candidates = {str(value)}
            if isinstance(value, int):
                candidates.add(f"{value:,}")
            else:
                candidates.add(f"{value:.1f}")
                candidates.add(f"{value:.2f}")
                candidates.add(f"{value:.3f}")
            for c in candidates:
                c_lc = c.lower()
                if c_lc in text_lc:
                    return True
                if self._normalize_for_match(c_lc) in text_norm:
                    return True
            return False

        s = str(value).strip()
        if not s:
            return False
        s_lc = s.lower()
        if s_lc in text_lc:
            return True
        return self._normalize_for_match(s_lc) in text_norm

    def _parse_update_object_response(
        self,
        response: str,
        allowed_keys: List[str],
    ) -> Dict[str, Any]:
        """Parse a repair/update JSON object response for iterative extraction."""
        try:
            json_match = self._extract_json(response)
            payload = json.loads(json_match) if json_match else json.loads(response)
        except Exception:
            return {}

        if isinstance(payload, list):
            payload = payload[0] if payload and isinstance(payload[0], dict) else {}
        if not isinstance(payload, dict):
            return {}
        return {k: v for k, v in payload.items() if k in allowed_keys}

    def _build_refinement_prompt(
        self,
        chunk_text: str,
        table_name: str,
        current_values: Dict[str, Any],
        remaining_keys: List[str],
        normalization_hints: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        """Build prompt for iterative chunk-by-chunk refinement."""
        populated_lines = []
        for k, v in current_values.items():
            if not self._is_missing_value(v):
                populated_lines.append(f"- {k}: {v}")
        populated_block = "\n".join(populated_lines) if populated_lines else "- (none)"
        remaining_block = ", ".join(remaining_keys) if remaining_keys else "(none)"
        hint_lines: List[str] = []
        for k in remaining_keys:
            vals = (normalization_hints or {}).get(k, [])
            if vals:
                hint_lines.append(f"- {k}: examples {vals}")
        hints_block = (
            "Normalization hints from workload predicates:\n"
            + "\n".join(hint_lines)
            + "\n\n"
            if hint_lines else ""
        )
        return (
            f"You are refining one structured record for table '{table_name}' from a long document.\n\n"
            f"Already populated values:\n{populated_block}\n\n"
            f"Remaining keys needing values:\n{remaining_block}\n\n"
            f"{hints_block}"
            "From the new text chunk below, return a JSON object with:\n"
            "1) values for any remaining keys you can find, and\n"
            "2) replacements for already populated keys only if this chunk has a more accurate,\n"
            "   more specific, or more temporally current value.\n\n"
            "Rules:\n"
            "- Return ONLY a JSON object (or {} if no updates).\n"
            "- Every value must be a single scalar (string/number/null), never lists.\n"
            "- For any value that requires time-relative calculation, use reference year 2025.\n"
            "- If normalization hints are provided for a key, use the same output convention "
            "(including numeric unit/scale convention) as those examples.\n"
            "- Prefer present-tense/current statements over historical lists.\n\n"
            f"Text chunk:\n{chunk_text}\n\n"
            "Output (JSON only):"
        )

    def _extract_single_chunk_iterative(
        self,
        subchunks: List[str],
        table_name: str,
        schema: Dict[str, str],
        constrained_keys: Optional[Set[str]] = None,
        normalization_hints: Optional[Dict[str, List[str]]] = None,
        entity_col: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Iterative extraction over 500-token subchunks with running updates."""
        parse_keys = (
            [k for k in schema.keys() if k in constrained_keys]
            if constrained_keys
            else list(schema.keys())
        )
        if not subchunks:
            return []

        # Seed extraction from first 500-token chunk.
        prompt0 = self._build_extraction_prompt(
            subchunks[0],
            table_name,
            schema,
            constrained_keys,
            normalization_hints,
            entity_col,
        )
        response0 = self.llm_client.generate(
            prompt0,
            max_tokens=EXTRACTION_MAX_TOKENS,
            temperature=EXTRACTION_TEMPERATURE,
        )
        try:
            seed_records = self._parse_extraction_response(response0, constrained_keys, parse_keys)
        except ValueError:
            repaired0 = self._repair_extraction_response(response0, parse_keys)
            seed_records = self._parse_extraction_response(repaired0, constrained_keys, parse_keys)
        seed_records = self._normalize_records_for_schema(seed_records, schema)

        current: Dict[str, Any] = {}
        if seed_records:
            for k, v in seed_records[0].items():
                current[k] = v

        # Refine with each subsequent chunk.
        for sub in subchunks[1:]:
            remaining = [k for k in parse_keys if self._is_missing_value(current.get(k))]
            refine_prompt = self._build_refinement_prompt(
                chunk_text=sub,
                table_name=table_name,
                current_values=current,
                remaining_keys=remaining,
                normalization_hints=normalization_hints,
            )
            refine_resp = self.llm_client.generate(
                refine_prompt,
                max_tokens=min(1024, EXTRACTION_MAX_TOKENS),
                temperature=0.0,
            )
            updates = self._parse_update_object_response(refine_resp, parse_keys)
            for k, v in updates.items():
                normalized = self._normalize_cell_value(v, schema.get(k, "OTHER"))
                if self._is_missing_value(normalized):
                    continue
                # Accept only grounded values from this chunk.
                if not self._value_grounded_in_text(normalized, sub):
                    continue
                current[k] = normalized

        # Keep only constrained keys and non-empty record.
        if constrained_keys:
            current = {k: v for k, v in current.items() if k in constrained_keys}
        has_any = any(not self._is_missing_value(v) for v in current.values())
        return [current] if has_any else []
    
    def _build_normalization_section(
        self,
        normalization_hints: Optional[Dict[str, List[str]]]
    ) -> str:
        """
        Build the normalization section of the extraction prompt.

        normalization_hints maps column_name → list of expected literal values
        taken directly from the SQL workload predicates (e.g. {'country': ['USA', 'Canada']}).
        The LLM must output exactly those strings, regardless of how the source text
        phrases them ('United States' → 'USA', 'Kanada' → 'Canada', etc.).
        """
        if not normalization_hints:
            return ""

        lines = ["\nOutput format examples (normalization guidance):"]
        for col, literals in sorted(normalization_hints.items()):
            quoted = ", ".join(f'"{v}"' for v in literals)
            lines.append(
                f'  - Column "{col}": when the text uses a synonym, abbreviation, '
                f"or alias for one of [{quoted}], write that exact form. "
                f"Still extract ALL values you find — these are format examples, "
                f"not an exhaustive list of allowed values."
            )
        return "\n".join(lines)

    def _build_entity_section(self, entity_col: Optional[str]) -> str:
        """
        Build the entity-routing section of an extraction prompt.

        When entity_col is set, every record the LLM returns must include
        a special `_entity` key whose value is the entity_col value for that
        record.  This key is used after extraction to route each record to the
        correct database row (UPDATE existing row or INSERT new row) and is
        then stripped before writing to the DB.
        """
        if not entity_col:
            return ""
        return (
            f"\nEntity routing (MANDATORY — never omit):\n"
            f'Every record MUST include a field "_entity" whose value is the '
            f'"{entity_col}" of the entity being described. '
            f"If the text discusses multiple entities, return a separate record for each.\n"
            f'Example: {{"_entity": "<{entity_col} value>", "other_col": "..."}}'
        )

    def _build_extraction_prompt(
        self,
        chunk: str,
        table_name: str,
        schema: Dict[str, str],
        constrained_keys: Optional[Set[str]] = None,
        normalization_hints: Optional[Dict[str, List[str]]] = None,
        entity_col: Optional[str] = None,
    ) -> str:
        """Build extraction prompt for LLM."""
        keys_to_use = constrained_keys if constrained_keys else schema.keys()
        schema_desc = self._build_schema_desc(schema, keys_to_use, normalization_hints)

        has_numeric = any(
            schema.get(c, "OTHER") in self._NUMERIC_SEM_TYPES for c in keys_to_use
        )
        has_count = any(
            schema.get(c, "OTHER") in self._COUNT_SEM_TYPES for c in keys_to_use
        )
        numeric_rule = (
            "- Numeric columns: return a JSON number (e.g. 1000000), "
            "NEVER a text string (e.g. NOT \"one million\").\n"
            if has_numeric else ""
        )
        count_rule = (
            "- Count columns (marked 'numeric, count'): extract the TOTAL cumulative "
            "count of discrete items/events. If the text lists individual items, "
            "count them and return the total. Return the count, not identifiers.\n"
            if has_count else ""
        )
        scalar_rule = (
            "- Every field must be a single scalar value (string/number/null), "
            "never a list/array and never a nested object. "
            "For text and regular numeric fields: if multiple candidates are mentioned, "
            "prefer explicitly current or present-tense facts "
            "(e.g. 'currently', 'is with', 'plays for', 'as of now'); if no current cue "
            "exists, choose the most recent value mentioned; if still ambiguous, choose "
            "the first clear canonical value. "
            "For 'numeric, count' fields: see the count rule above — return "
            "the total count, not individual identifiers.\n"
        )
        entity_section = self._build_entity_section(entity_col)

        format_contract = (
            "OUTPUT FORMAT (MANDATORY): Return ONLY a JSON array of objects. "
            "No markdown, no prose, no code fences."
        )

        prompt = (
            f'Extract structured data from the following text for table "{table_name}".\n\n'
            f"{format_contract}\n\n"
            f"Schema (extract ONLY these fields):\n{schema_desc}\n"
            f"{entity_section}\n\n"
            f"Rules:\n"
            f"- Return a JSON array of objects, one per entity found.\n"
            f"- Use null (not empty string) for any value that is not present.\n"
            f"- If no matching data is found, return an empty array [].\n"
            f"- For any value that requires time-relative calculation, use reference year 2025.\n"
            f"{numeric_rule}"
            f"{count_rule}"
            f"{scalar_rule}"
            f"\nText:\n{chunk}\n\n"
            f"{format_contract}\n"
            f"Return ONLY the JSON array, no other text."
        )
        return prompt

    def discover_attributes_from_chunk(
        self,
        chunk: str,
        chunk_id: str,
        table_name: str
    ) -> List[str]:
        """
        Ask LLM what other attributes about the table are mentioned in this chunk.
        This builds the attribute index for smart column delta.
        
        Returns:
            List of attribute names mentioned in the chunk (e.g., ["state", "population", "mayor"])
        """
        prompt = (
            f'You are analyzing text to discover what ATTRIBUTE NAMES (column names/keys) about "{table_name}" are mentioned.\n\n'
            f"TEXT:\n{chunk}\n\n"
            f"TASK: List the NAMES of all attributes/properties/fields about {table_name} discussed in the text.\n"
            f"Return attribute NAMES (keys), NOT values.\n\n"
            f"RULES:\n"
            f"- Return ONLY attribute names (column headers), NOT the actual data values\n"
            f"- Use snake_case for attribute names (e.g., 'birth_date', 'team_name', 'population')\n"
            f"- Include implicit attributes (e.g., if text mentions 'born in 1990', include 'birth_date')\n"
            f"- If text says 'the city has 2 million people', return 'population' (NOT '2 million')\n"
            f"- If text says 'founded in 1995', return 'founded_year' (NOT '1995')\n"
            f"- Do NOT include entity names or specific values, only the attribute type names\n"
            f"- Include attributes even if the text doesn't provide complete data\n"
            f"- If no attributes are found, return an empty array []\n\n"
            f"OUTPUT FORMAT: Return ONLY a JSON array of attribute name strings, no other text.\n"
            f'Example input: "The Lakers were founded in 1947 and are located in Los Angeles"\n'
            f'Example output: ["team_name", "founded_year", "location"]\n\n'
            f"Return ONLY the JSON array, no markdown, no code fences:"
        )
        
        try:
            response = self.llm_client.generate(
                prompt,
                max_tokens=300,  # Attribute list should be short
                temperature=0.0
            )
            
            # Parse response
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
                response = response.strip()
            
            attributes = json.loads(response)
            
            if not isinstance(attributes, list):
                logger.warning(f"Attribute discovery returned non-list for chunk {chunk_id}: {attributes}")
                return []
            
            # Filter to strings only
            attributes = [str(a) for a in attributes if isinstance(a, str)]
            
            logger.debug(f"Discovered {len(attributes)} attributes in chunk {chunk_id}: {attributes}")
            return attributes
            
        except Exception as e:
            logger.warning(f"Error discovering attributes for chunk {chunk_id}: {e}")
            return []

    def _normalize_records_for_schema(
        self,
        records: List[Dict[str, Any]],
        schema: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """Normalize records to schema-compatible scalar values."""
        out: List[Dict[str, Any]] = []
        for record in records:
            normalized: Dict[str, Any] = {}
            for col, val in record.items():
                sem_type = schema.get(col, "OTHER")
                normalized[col] = self._normalize_cell_value(val, sem_type)
            out.append(normalized)
        return out

    def _normalize_cell_value(self, value: Any, sem_type: str) -> Any:
        """Collapse list-like outputs to single scalar values."""
        if value is None:
            return None

        def _first_nonempty(items: List[Any]) -> Any:
            for item in items:
                s = str(item).strip()
                if s:
                    return item
            return None

        # Unwrap stringified JSON arrays.
        if isinstance(value, str):
            s = value.strip()
            if s.startswith("[") and s.endswith("]"):
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        value = parsed
                except Exception:
                    pass

        # Universal scalar policy: collapse any list-like value to one scalar.
        if isinstance(value, list):
            picked = _first_nonempty(value)
            return str(picked).strip() if picked is not None else None
        if isinstance(value, str):
            return value.strip() or None
        return value

    def _repair_extraction_response(
        self,
        malformed_output: str,
        expected_keys: List[str],
    ) -> str:
        """Ask the model to reformat malformed extraction output into valid JSON."""
        keys_hint = ", ".join(expected_keys) if expected_keys else "(no explicit keys)"
        repair_prompt = (
            "Reformat the following malformed extraction output into strict JSON.\n\n"
            "Requirements:\n"
            "- Return ONLY a JSON array.\n"
            "- Every array item MUST be a JSON object.\n"
            f"- Object keys should come from: {keys_hint}.\n"
            "- Keep all recoverable information.\n"
            "- If a value is missing, use null.\n"
            "- Do NOT include markdown, comments, or extra text.\n\n"
            f"Malformed output:\n{malformed_output}"
        )
        return self.llm_client.generate(
            repair_prompt,
            max_tokens=EXTRACTION_MAX_TOKENS,
            temperature=0.0,
        )
    
    def _parse_extraction_response(
        self,
        response: str,
        constrained_keys: Optional[Set[str]] = None,
        expected_keys: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Parse LLM extraction response."""
        try:
            # Try to find JSON in response
            json_match = self._extract_json(response)
            
            if json_match:
                records = json.loads(json_match)
            else:
                # Try parsing entire response
                records = json.loads(response)
            
            # Validate records
            if not isinstance(records, list):
                logger.warning("Extraction response is not a list, wrapping in list")
                records = [records]

            # Strict parsing: only object rows are accepted. We can unwrap
            # stringified JSON, but we do not do positional coercion.
            dict_records: List[Dict[str, Any]] = []
            unresolved: List[Any] = []
            for r in records:
                if isinstance(r, dict):
                    dict_records.append(r)
                    continue

                # String that itself is JSON object/list.
                if isinstance(r, str):
                    s = r.strip()
                    if (s.startswith("{") and s.endswith("}")) or (
                        s.startswith("[") and s.endswith("]")
                    ):
                        try:
                            parsed_inner = json.loads(s)
                            if isinstance(parsed_inner, dict):
                                dict_records.append(parsed_inner)
                            elif isinstance(parsed_inner, list):
                                list_unresolved = 0
                                for item in parsed_inner:
                                    if isinstance(item, dict):
                                        dict_records.append(item)
                                    else:
                                        list_unresolved += 1
                                if list_unresolved > 0:
                                    unresolved.append(r)
                            else:
                                unresolved.append(r)
                        except Exception:
                            unresolved.append(r)
                    else:
                        unresolved.append(r)
                else:
                    unresolved.append(r)

            if unresolved:
                sample = unresolved[:3]
                logger.error(
                    "Unresolved non-object records in extraction response: count=%d sample=%r",
                    len(unresolved),
                    sample,
                )
                raise ValueError(
                    "Extraction response contained non-object record(s). "
                    f"count={len(unresolved)} expected_keys={expected_keys} sample={sample!r}"
                )

            records = dict_records
            
            # Filter keys if constrained
            if constrained_keys:
                filtered_records = []
                for record in records:
                    filtered = {
                        k: v for k, v in record.items()
                        if k in constrained_keys
                    }
                    if filtered:
                        filtered_records.append(filtered)
                records = filtered_records
            
            return records
        
        except json.JSONDecodeError as e:
            snippet = response if len(response) <= 4000 else response[:4000] + "...<truncated>"
            logger.warning(
                "Malformed extraction JSON (will trigger repair pass): %s | response_len=%d | response=%r",
                e,
                len(response),
                snippet,
            )
            raise ValueError(f"JSON decode failed: {e}")
    
    def _extract_json(self, text: str) -> Optional[str]:
        """Extract first balanced JSON array/object from text."""
        start = None
        start_char = ""
        for i, ch in enumerate(text):
            if ch in "[{":
                start = i
                start_char = ch
                break
        if start is None:
            return None

        end_char = "]" if start_char == "[" else "}"
        stack = []
        in_string = False
        escape = False

        for j in range(start, len(text)):
            ch = text[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch in "[{":
                stack.append(ch)
            elif ch in "]}":
                if not stack:
                    return None
                opener = stack.pop()
                if (opener == "[" and ch != "]") or (opener == "{" and ch != "}"):
                    return None
                if not stack:
                    # Completed the outermost JSON payload.
                    if ch == end_char:
                        return text[start : j + 1]
                    # If outer payload started with array/object, but ended with the
                    # other token, keep scanning for a valid close.
        return None
    
    # ========================================================================
    # Caching
    # ========================================================================
    
    def _get_cache_key(self, chunk_id: str, table_name: str) -> str:
        """Generate cache key."""
        return hashlib.md5(f"{chunk_id}:{table_name}".encode()).hexdigest()
    
    def _get_cached_result(
        self,
        chunk_id: str,
        table_name: str
    ) -> Optional[ExtractionResult]:
        """Get cached extraction result."""
        cache_key = self._get_cache_key(chunk_id, table_name)
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                
                return ExtractionResult(
                    chunk_id=data['chunk_id'],
                    records=data['records'],
                    schema_keys=set(data['schema_keys']),
                    extraction_time=data['extraction_time'],
                    error=data.get('error')
                )
            
            except Exception as e:
                logger.warning(f"Error loading cached result: {e}")
        
        return None
    
    def _cache_result(
        self,
        chunk_id: str,
        table_name: str,
        result: ExtractionResult
    ) -> None:
        """Cache extraction result."""
        cache_key = self._get_cache_key(chunk_id, table_name)
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        try:
            data = {
                'chunk_id': result.chunk_id,
                'records': result.records,
                'schema_keys': list(result.schema_keys),
                'extraction_time': result.extraction_time,
                'error': result.error
            }
            
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
        
        except Exception as e:
            logger.warning(f"Error caching result: {e}")
    
    # ========================================================================
    # Lazy Enrichment
    # ========================================================================
    
    def enrich_records(
        self,
        records: List[Dict[str, Any]],
        chunk_ids: List[str],
        chunks: List[str],
        table_name: str,
        schema: Dict[str, str],
        new_columns: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Enrich existing records with new columns (lazy enrichment).
        
        Args:
            records: Existing records
            chunk_ids: Chunk IDs for each record
            chunks: Text chunks for each record
            table_name: Name of the table
            schema: Full schema including new columns
            new_columns: List of new columns to extract
            
        Returns:
            Enriched records
        """
        logger.info(f"Enriching {len(records)} records with columns: {new_columns}")
        
        enriched_records = []
        
        for record, chunk_id, chunk in zip(records, chunk_ids, chunks):
            # Build prompt for enrichment
            prompt = self._build_enrichment_prompt(
                chunk,
                table_name,
                schema,
                record,
                new_columns
            )
            
            # Call LLM
            try:
                response = self.llm_client.generate(
                    prompt,
                    max_tokens=500,
                    temperature=EXTRACTION_TEMPERATURE
                )
                
                # Parse response
                new_values = self._parse_enrichment_response(response, new_columns)
                
                # Merge with existing record
                enriched = {**record, **new_values}
                enriched_records.append(enriched)
            
            except Exception as e:
                logger.error(f"Error enriching record: {e}")
                # Keep original record with null values for new columns
                enriched = {**record}
                for col in new_columns:
                    enriched[col] = None
                enriched_records.append(enriched)
            
            # Rate limiting
            time.sleep(0.5)
        
        return enriched_records
    
    def _build_enrichment_prompt(
        self,
        chunk: str,
        table_name: str,
        schema: Dict[str, str],
        existing_record: Dict[str, Any],
        new_columns: List[str]
    ) -> str:
        """Build enrichment prompt."""
        # Show existing data
        existing_data = json.dumps(existing_record, indent=2)
        
        # Show new columns to extract
        new_cols_desc = "\n".join([
            f"  - {col} ({schema.get(col, 'unknown')})"
            for col in new_columns
        ])
        
        prompt = f"""We already have this data from the text:
{existing_data}

Now extract these additional fields from the same text:
{new_cols_desc}

Text:
{chunk}

Return a JSON object with ONLY the new fields. Use null if not found.

Example format:
{{"new_field1": "value", "new_field2": null}}

Return ONLY the JSON object, no other text.
"""
        
        return prompt
    
    def _parse_enrichment_response(
        self,
        response: str,
        new_columns: List[str]
    ) -> Dict[str, Any]:
        """Parse enrichment response."""
        try:
            json_match = self._extract_json(response)
            
            if json_match:
                data = json.loads(json_match)
            else:
                data = json.loads(response)
            
            # Filter to only new columns
            filtered = {
                k: v for k, v in data.items()
                if k in new_columns
            }
            
            return filtered
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse enrichment response: {e}")
            return {col: None for col in new_columns}


# ============================================================================
# Utility Functions
# ============================================================================

def normalize_value(value: Any, semantic_type: str) -> Any:
    """Normalize extracted value based on semantic type."""
    if value is None or value == "":
        return None
    
    # String normalization
    if isinstance(value, str):
        value = value.strip()
        
        # Normalize common variations
        if semantic_type == "PERSON":
            # Capitalize names
            value = value.title()
        
        elif semantic_type == "DATE":
            # Could add date parsing here
            pass
        
        elif semantic_type == "CODE":
            # Uppercase codes
            value = value.upper()
    
    return value
