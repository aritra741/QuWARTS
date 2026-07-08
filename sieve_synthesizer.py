"""
Programmatic Sieve Synthesis for WDIRS.
Generates filtering functions using spaCy, FlashText, and regex.
"""

import json
import logging
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Iterator, Tuple, Set, Optional, Callable, Any
from dataclasses import dataclass
from pathlib import Path

from flashtext import KeywordProcessor
import spacy

from config import (
    SIEVE_SAMPLE_SIZE,
    SIEVE_REFINEMENT_ITERATIONS,
    SIEVE_TEST_SIZE,
    SIEVE_DIR
)

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class SieveResult:
    """Result of sieve synthesis."""
    table_name: str
    sieve_function: str  # Python code as string
    accuracy: float
    keywords: List[str]
    patterns: List[str]
    entity_types: List[str]


# ============================================================================
# Sieve Synthesizer
# ============================================================================

class SieveSynthesizer:
    """
    Synthesizes programmatic sieves for filtering relevant chunks.
    Uses spaCy for NER, FlashText for keywords, and regex for patterns.
    """
    
    def __init__(self, llm_client, spacy_model: str = "en_core_web_sm"):
        """
        Initialize sieve synthesizer.
        
        Args:
            llm_client: LLM client for code generation
            spacy_model: spaCy model to use
        """
        self.llm_client = llm_client
        
        # Load spaCy model - REQUIRED, no fallback
        try:
            self.nlp = spacy.load(spacy_model)
            logger.info(f"Loaded spaCy model: {spacy_model}")
        except OSError as e:
            logger.error(f"spaCy model {spacy_model} not found. Please install it with: python -m spacy download {spacy_model}")
            raise RuntimeError(f"Required spaCy model '{spacy_model}' not found. Install it with: python -m spacy download {spacy_model}") from e
        
        # Create sieve directory
        SIEVE_DIR.mkdir(parents=True, exist_ok=True)
    
    def synthesize_sieve(
        self,
        table_name: str,
        schema: Dict[str, str],
        sample_chunks: List[str],
        positive_examples: Optional[List[str]] = None
    ) -> SieveResult:
        """
        Synthesize a sieve function for a table.
        
        Args:
            table_name: Name of the table
            schema: Column schema (column_name -> semantic_type)
            sample_chunks: Sample text chunks for synthesis
            positive_examples: Optional positive examples
            
        Returns:
            SieveResult with synthesized function
        """
        logger.info(f"Synthesizing sieve for table: {table_name}")
        
        # Step 1: Analyze sample chunks to extract patterns
        keywords, patterns, entity_types = self._analyze_samples(
            sample_chunks,
            schema
        )
        
        # Step 2: Generate initial sieve function using LLM
        sieve_code = self._generate_sieve_code(
            table_name,
            schema,
            keywords,
            patterns,
            entity_types
        )
        
        # Step 3: Refine sieve through iterative testing
        refined_code, accuracy = self._refine_sieve(
            sieve_code,
            sample_chunks,
            positive_examples
        )
        
        # Step 4: Save sieve to file
        self._save_sieve(table_name, refined_code)
        
        result = SieveResult(
            table_name=table_name,
            sieve_function=refined_code,
            accuracy=accuracy,
            keywords=keywords,
            patterns=patterns,
            entity_types=entity_types
        )
        
        logger.info(f"Sieve synthesis complete for {table_name} (accuracy: {accuracy:.2%})")
        
        return result
    
    def _analyze_samples(
        self,
        sample_chunks: List[str],
        schema: Dict[str, str]
    ) -> tuple[List[str], List[str], List[str]]:
        """
        Discover domain vocabulary and patterns from sample chunks.

        Domain-agnostic strategy
        ────────────────────────
        Keywords are derived from two sources that require no manual
        configuration and work for any domain:

          1. Schema column names and their natural-language variations.
             These come directly from the workload SQL and represent the
             fields the dataset cares about (e.g. "company_name" →
             "company name", "companies"; "net_profit_or_loss" →
             "net profit or loss", "profit", "loss").

          2. Frequent domain nouns from sample chunks.
             spaCy POS-tags the samples and counts non-stop-word nouns
             that appear in at least two chunks.  These are domain
             vocabulary words (e.g. "revenue", "dividend", "diagnosis",
             "prescription") — NOT named-entity values (which are too
             specific and would only match one particular entity).
             Named entities are explicitly excluded so the sieve catches
             ALL entities in the domain, not just the ones that happen to
             appear in the 50 sample chunks.

        spaCy runs ONCE here at synthesis time.  The generated sieve
        bakes the resulting keyword list into a module-level FlashText
        processor, so scanning the full corpus costs only a fast
        substring search — no NLP inference at scan time.
        """
        from collections import Counter as _Counter

        keywords: set = set()
        patterns: set = set()
        entity_types: set = set()  # kept for prompt context only

        # ── 1. Schema column variations ───────────────────────────────────────
        # Column names are guaranteed domain signals for any dataset.
        for col_name in schema:
            for variation in self._generate_column_variations(col_name):
                keywords.add(variation.lower())

        # ── 2. Frequent domain nouns from sample chunks ───────────────────────
        # Count nouns/adjectives across all samples.  We use the lemma so
        # "revenues" and "revenue" map to the same entry.
        # Named entities (ent_type_ != "") are excluded — they're too
        # specific to individual entities and would under-cover the domain.
        noun_counts: _Counter = _Counter()
        for chunk in sample_chunks:
            doc = self.nlp(chunk)

            # Collect entity type labels for the prompt (informational only).
            for ent in doc.ents:
                entity_types.add(ent.label_)

            for token in doc:
                if (
                    token.pos_ in {"NOUN", "PROPN", "ADJ"}
                    and not token.is_stop
                    and not token.is_punct
                    and not token.ent_type_   # skip named entity surface forms
                    and len(token.text) > 3
                ):
                    noun_counts[token.lemma_.lower()] += 1

        # Keep nouns that appear in at least 2 different chunks — single
        # occurrences are noise; frequent ones are domain vocabulary.
        min_freq = max(2, len(sample_chunks) // 10)
        for noun, count in noun_counts.most_common(60):
            if count >= min_freq:
                keywords.add(noun)

        # ── 3. Structural patterns present in samples ─────────────────────────
        # These are domain-agnostic regex patterns for common data formats.
        # Only added when actually observed in the sample, so a medical
        # corpus without money amounts won't get the money pattern.
        _CANDIDATE_PATTERNS = {
            r'\d{1,2}/\d{1,2}/\d{2,4}',
            r'\d{4}-\d{2}-\d{2}',
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}\b',
            r'\b[A-Z]{2,5}:\s*[A-Z0-9]+\b',   # exchange/ticker codes
            r'[\$£€¥]\s*\d[\d,]*(?:\.\d+)?',   # monetary values (any currency)
            r'\b\d+(?:\.\d+)?\s*%',             # percentages
            r'\b[A-Z]\d{3,}\b',                 # IDs / codes
        }
        for pattern in _CANDIDATE_PATTERNS:
            for chunk in sample_chunks:
                if re.search(pattern, chunk):
                    patterns.add(pattern)
                    break

        return list(keywords), list(patterns), list(entity_types)
    
    def _generate_column_variations(self, column_name: str) -> List[str]:
        """Generate variations of column name."""
        variations = [column_name]
        
        # Split by underscore
        parts = column_name.split('_')
        if len(parts) > 1:
            variations.append(' '.join(parts))
            variations.append(''.join(p.capitalize() for p in parts))
        
        # Add singular/plural
        if column_name.endswith('s'):
            variations.append(column_name[:-1])
        else:
            variations.append(column_name + 's')
        
        return variations
    
    def _generate_sieve_code(
        self,
        table_name: str,
        schema: Dict[str, str],
        keywords: List[str],
        patterns: List[str],
        entity_types: List[str]
    ) -> str:
        """Generate sieve function code using LLM."""
        prompt = f"""Generate a Python module that filters text chunks for a database table.
The module must define a module-level keyword processor and an `is_relevant(text)` function.

Table: {table_name}
Schema: {json.dumps(schema, indent=2)}

Keywords that indicate relevance: {', '.join(keywords[:30])}
Regex patterns that indicate relevance: {', '.join(patterns[:10])}

STRICT REQUIREMENTS:
1. Use ONLY FlashText for keyword matching and `re` for regex — do NOT import or use spaCy.
   spaCy NER is too slow for large corpora; keyword + regex matching is sufficient here.
2. Build the KeywordProcessor ONCE at MODULE LEVEL (outside the function), not inside it.
   Building it inside the function recreates it on every call, which is extremely slow.
3. The function must be conservative: prefer false positives over false negatives.
4. Return True if the text likely contains data for this table, False otherwise.
5. Use correct Python syntax — no bare `any(bool_value)`, always check for None before iterating.

Required structure (follow this exactly):
```python
import re
from flashtext import KeywordProcessor

# Build keyword processor ONCE at module level
_kp = KeywordProcessor(case_sensitive=False)
_kp.add_keywords_from_list(["keyword1", "keyword2", "keyword3"])

# Compile regex patterns ONCE at module level
_PATTERNS = [re.compile(r'pattern1', re.IGNORECASE), re.compile(r'pattern2', re.IGNORECASE)]

def is_relevant(text: str) -> bool:
    if not text or not text.strip():
        return False
    # Fast keyword check
    if _kp.extract_keywords(text):
        return True
    # Regex check
    for pat in _PATTERNS:
        if pat.search(text):
            return True
    return False
```

Replace the placeholder keywords and patterns with real ones for the '{table_name}' table.
Generate ONLY the Python code, no explanations.
"""
        
        try:
            response = self.llm_client.generate(
                prompt,
                max_tokens=1000,
                temperature=0.2
            )
            
            # Extract code from response
            code = self._extract_code(response)
            
            # Validate syntax
            try:
                compile(code, '<string>', 'exec')
            except SyntaxError as e:
                logger.error(f"Generated code has syntax error: {e}")
                raise RuntimeError(f"LLM generated code with syntax error: {e}") from e
            
            # Test the code on a sample chunk to catch runtime errors
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    f.write(code)
                    temp_file = f.name
                
                import importlib.util
                spec = importlib.util.spec_from_file_location("test_sieve", temp_file)
                test_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(test_module)
                
                # Test with sample text
                test_text = "This is a test chunk with some data."
                _ = test_module.is_relevant(test_text)
                
                # Clean up
                Path(temp_file).unlink()
                
            except Exception as e:
                logger.error(f"Generated code has runtime error: {e}")
                raise RuntimeError(f"LLM generated code with runtime error: {e}") from e
            
            return code
        
        except Exception as e:
            logger.error(f"Error generating sieve code: {e}")
            raise RuntimeError(f"Failed to generate sieve code: {e}") from e
    
    def _extract_code(self, response: str) -> str:
        """Extract Python code from LLM response."""
        # Look for code blocks
        code_pattern = r'```python\n(.*?)\n```'
        match = re.search(code_pattern, response, re.DOTALL)
        
        if match:
            return match.group(1)
        
        # If no code block, try to find function definition
        func_pattern = r'(def is_relevant.*?)(?=\n\ndef|\Z)'
        match = re.search(func_pattern, response, re.DOTALL)
        
        if match:
            return match.group(1)
        
        # If no code block or function found, the LLM response is malformed
        logger.error(f"Could not extract code from LLM response: {response[:200]}")
        raise ValueError("LLM did not return valid Python code")
    
    def _refine_sieve(
        self,
        sieve_code: str,
        test_chunks: List[str],
        positive_examples: Optional[List[str]] = None
    ) -> tuple[str, float]:
        """
        Refine sieve through iterative testing.
        
        Returns:
            (refined_code, accuracy)
        """
        current_code = sieve_code
        best_accuracy = 0.0
        
        for iteration in range(SIEVE_REFINEMENT_ITERATIONS):
            # Test current sieve
            accuracy, errors = self._test_sieve(
                current_code,
                test_chunks,
                positive_examples
            )
            
            logger.debug(f"Iteration {iteration + 1}: accuracy = {accuracy:.2%}")
            
            if accuracy > best_accuracy:
                best_accuracy = accuracy
            
            # If accuracy is good enough, stop
            if accuracy >= 0.8:
                break
            
            # If we have errors, try to refine
            if errors and iteration < SIEVE_REFINEMENT_ITERATIONS - 1:
                current_code = self._refine_with_errors(current_code, errors)
        
        return current_code, best_accuracy
    
    def _test_sieve(
        self,
        sieve_code: str,
        test_chunks: List[str],
        positive_examples: Optional[List[str]] = None
    ) -> tuple[float, List[str]]:
        """
        Test sieve function on test chunks.
        
        Returns:
            (accuracy, error_messages)
        """
        try:
            # Create temporary file with sieve code
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.py',
                delete=False
            ) as f:
                f.write(sieve_code)
                temp_file = f.name
            
            # Import and test
            import importlib.util
            spec = importlib.util.spec_from_file_location("sieve_module", temp_file)
            sieve_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sieve_module)
            
            is_relevant = sieve_module.is_relevant
            
            # Test on chunks
            correct = 0
            total = len(test_chunks)
            errors = []
            
            for chunk in test_chunks:
                try:
                    result = is_relevant(chunk)
                    
                    # If we have positive examples, check against them
                    if positive_examples:
                        should_be_relevant = any(
                            pos in chunk for pos in positive_examples
                        )
                        if result == should_be_relevant:
                            correct += 1
                    else:
                        # Without ground truth, assume function works
                        correct += 1
                
                except Exception as e:
                    errors.append(f"Error on chunk: {str(e)}")
            
            accuracy = correct / total if total > 0 else 0.0
            
            # Clean up
            Path(temp_file).unlink()
            
            return accuracy, errors
        
        except Exception as e:
            logger.error(f"Error testing sieve: {e}")
            return 0.0, [str(e)]
    
    def _refine_with_errors(
        self,
        sieve_code: str,
        errors: List[str]
    ) -> str:
        """Refine sieve code based on errors."""
        prompt = f"""The following Python sieve function has errors. Fix them.

Current code:
```python
{sieve_code}
```

Errors:
{chr(10).join(f"- {e}" for e in errors[:5])}

Generate the corrected Python code. Return ONLY the code, no explanations.
"""
        
        try:
            response = self.llm_client.generate(
                prompt,
                max_tokens=1000,
                temperature=0.1
            )
            
            refined_code = self._extract_code(response)
            return refined_code
        
        except Exception as e:
            logger.error(f"Error refining sieve: {e}")
            return sieve_code
    
    def _save_sieve(self, table_name: str, sieve_code: str) -> None:
        """Save sieve function to file."""
        sieve_file = SIEVE_DIR / f"{table_name}_sieve.py"
        
        with open(sieve_file, 'w') as f:
            f.write(sieve_code)
        
        logger.info(f"Saved sieve to {sieve_file}")
    
    def load_sieve(self, table_name: str) -> Optional[Callable]:
        """Load sieve function from file."""
        sieve_file = SIEVE_DIR / f"{table_name}_sieve.py"
        
        if not sieve_file.exists():
            logger.warning(f"Sieve file not found: {sieve_file}")
            return None
        
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                f"{table_name}_sieve",
                str(sieve_file)
            )
            sieve_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sieve_module)
            
            return sieve_module.is_relevant
        
        except Exception as e:
            logger.error(f"Error loading sieve: {e}")
            return None
    
    def apply_sieve(
        self,
        table_name: str,
        chunks: List[str]
    ) -> List[int]:
        """
        Apply sieve to chunks and return indices of relevant chunks.
        
        Args:
            table_name: Name of the table
            chunks: List of text chunks
            
        Returns:
            List of indices of relevant chunks
        """
        # Load sieve
        is_relevant = self.load_sieve(table_name)
        
        if is_relevant is None:
            logger.warning(f"No sieve found for {table_name}, returning all chunks")
            return list(range(len(chunks)))
        
        # Apply sieve
        relevant_indices = []
        
        errors_count = 0
        max_errors = 10  # Allow some errors before failing completely
        
        for idx, chunk in enumerate(chunks):
            try:
                if is_relevant(chunk):
                    relevant_indices.append(idx)
            except Exception as e:
                errors_count += 1
                logger.warning(f"Error applying sieve to chunk {idx}: {e}")
                
                # If too many errors, the sieve is broken
                if errors_count > max_errors:
                    logger.error(f"Sieve failed on {errors_count} chunks, aborting")
                    raise RuntimeError(f"Sieve function is broken: {e}") from e
                
                # Include chunk if sieve fails (conservative)
                relevant_indices.append(idx)
        
        logger.info(f"Sieve filtered {len(chunks)} chunks to {len(relevant_indices)} relevant chunks")
        
        return relevant_indices

    def apply_sieve_streamed(
        self,
        table_name: str,
        page_iterator: Iterator[List[Tuple[str, str]]],
        total_chunks: int,
        max_workers: int = 32,
    ) -> List[str]:
        """
        Apply the sieve to the full corpus without loading it all into RAM.

        Args:
            table_name:     Name of the table whose sieve to apply.
            page_iterator:  Iterator that yields pages of (chunk_id, text) tuples
                            (e.g. from DataLayer.stream_chunks_paged()).
            total_chunks:   Total corpus size — used only for ETA logging.
            max_workers:    ThreadPoolExecutor width.  spaCy and regex both
                            release the GIL so threads give near-linear speedup.

        Returns:
            List of chunk_id strings that passed the sieve.
        """
        is_relevant = self.load_sieve(table_name)
        if is_relevant is None:
            logger.warning(
                f"[Sieve] No sieve found for '{table_name}' — accepting all chunks"
            )
            return [cid for page in page_iterator for cid, _ in page]

        relevant_ids: List[str] = []
        scanned = 0
        errors = 0
        MAX_ERRORS = 100
        t_start = time.time()

        for page in page_iterator:
            page_hits: List[str] = []

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_to_cid = {
                    pool.submit(is_relevant, text): cid
                    for cid, text in page
                }
                for fut in as_completed(future_to_cid):
                    cid = future_to_cid[fut]
                    try:
                        if fut.result():
                            page_hits.append(cid)
                    except Exception as exc:
                        errors += 1
                        page_hits.append(cid)  # conservative: include on error
                        if errors > MAX_ERRORS:
                            raise RuntimeError(
                                f"[Sieve] '{table_name}' sieve failed on "
                                f"{errors} chunks: {exc}"
                            ) from exc

            relevant_ids.extend(page_hits)
            scanned += len(page)

            elapsed = time.time() - t_start
            rate = scanned / elapsed if elapsed > 0 else 1
            remaining = total_chunks - scanned
            eta_min = (remaining / rate) / 60 if rate > 0 else 0
            logger.info(
                f"[Sieve] '{table_name}': {scanned:,}/{total_chunks:,} scanned "
                f"({rate:,.0f} chunks/s) → {len(relevant_ids):,} candidates "
                f"| ETA {eta_min:.1f} min"
            )

        logger.info(
            f"[Sieve] '{table_name}' complete: "
            f"{total_chunks:,} → {len(relevant_ids):,} candidates "
            f"({len(relevant_ids)/max(total_chunks,1)*100:.1f}% pass rate) "
            f"in {(time.time()-t_start)/60:.1f} min"
        )
        return relevant_ids


# ============================================================================
# Utility Functions
# ============================================================================

def create_keyword_processor(keywords: List[str]) -> KeywordProcessor:
    """Create FlashText keyword processor."""
    processor = KeywordProcessor()
    processor.add_keywords_from_list(keywords)
    return processor


def extract_entities(text: str, nlp) -> Dict[str, List[str]]:
    """Extract named entities from text using spaCy."""
    doc = nlp(text)
    entities = {}
    
    for ent in doc.ents:
        if ent.label_ not in entities:
            entities[ent.label_] = []
        entities[ent.label_].append(ent.text)
    
    return entities


def match_patterns(text: str, patterns: List[str]) -> List[str]:
    """Match regex patterns in text."""
    matches = []
    
    for pattern in patterns:
        found = re.findall(pattern, text, re.IGNORECASE)
        matches.extend(found)
    
    return matches
