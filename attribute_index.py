"""
Attribute Index for QuWARTS: 2-level index for smart column delta extraction.

During Phase 1 (preprocessing), discovers which attributes are mentioned in each chunk.
During Phase 2 (runtime), maps missing columns to relevant chunks for targeted extraction.
"""

import json
import logging
from typing import Dict, List, Set, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import defaultdict
import difflib

logger = logging.getLogger(__name__)


@dataclass
class AttributeDiscovery:
    """Attributes discovered in a chunk during extraction."""
    chunk_id: str
    table_name: str
    discovered_attributes: List[str]  # Raw attribute names from LLM


@dataclass
class AttributeIndexEntry:
    """Index entry mapping canonical attribute to chunks."""
    canonical_name: str
    variants: Set[str]  # All name variations (e.g., "state", "State Name", "state_name")
    chunk_ids: Set[str]  # Chunks that mention this attribute


class AttributeIndex:
    """
    2-level index for attribute discovery and chunk targeting.
    
    Level 1: chunk_id → [discovered_attributes]
    Level 2: canonical_attribute → [chunk_ids]
    """
    
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir
        # Level 1: chunk → attributes
        self.chunk_to_attrs: Dict[str, Dict[str, List[str]]] = defaultdict(dict)  # table → chunk_id → [attrs]
        # Level 2: attribute → chunks
        self.attr_to_chunks: Dict[str, Dict[str, AttributeIndexEntry]] = defaultdict(dict)  # table → attr → entry
        
    def add_discovery(self, discovery: AttributeDiscovery) -> None:
        """Record attributes discovered in a chunk."""
        table = discovery.table_name
        chunk_id = discovery.chunk_id
        
        # Level 1: store raw discovery
        self.chunk_to_attrs[table][chunk_id] = discovery.discovered_attributes
        
        # Level 2: canonicalize and build inverted index
        for raw_attr in discovery.discovered_attributes:
            canonical = self._canonicalize_attribute(raw_attr)
            
            if canonical not in self.attr_to_chunks[table]:
                self.attr_to_chunks[table][canonical] = AttributeIndexEntry(
                    canonical_name=canonical,
                    variants=set(),
                    chunk_ids=set()
                )
            
            entry = self.attr_to_chunks[table][canonical]
            entry.variants.add(raw_attr)
            entry.chunk_ids.add(chunk_id)
    
    # If an attribute appears in more than this fraction of all indexed chunks for a
    # table, it is too common ("player_name" appears in every player bio) to be useful
    # as a discriminator.  Returning an arbitrary hash-order subset of 9 000 IDs would
    # give the caller a random sample rather than the most relevant chunks; it is better
    # to return [] so the caller falls back to the relevance-ordered candidate list.
    OVERBROAD_THRESHOLD = 0.30

    def find_chunks_for_column(self, table: str, column: str, top_k: int = 100) -> List[str]:
        """
        Find chunks most likely to contain data for a missing column.

        Returns an empty list when the attribute is over-broad (appears in more than
        OVERBROAD_THRESHOLD of all indexed chunks), allowing the caller to fall back
        to the relevance-sorted candidate list instead of receiving an arbitrary subset.

        Args:
            table: Table name
            column: Missing column name (e.g., "state_name")
            top_k: Maximum chunks to return

        Returns:
            List of chunk_ids, ordered by chunk_id (stable/deterministic), or [] when
            the attribute is over-broad or not found.
        """
        if table not in self.attr_to_chunks:
            logger.warning(f"No attribute index for table '{table}'")
            return []

        total_indexed = len(self.chunk_to_attrs.get(table, {}))

        def _check_and_return(entry: "AttributeIndexEntry", label: str) -> List[str]:
            """Return sorted chunk IDs unless the attribute is over-broad."""
            n = len(entry.chunk_ids)
            if total_indexed > 0 and n / total_indexed > self.OVERBROAD_THRESHOLD:
                logger.info(
                    f"[AttributeIndex] Skipping over-broad attribute '{label}' "
                    f"for table '{table}': {n}/{total_indexed} chunks "
                    f"({n/total_indexed:.0%} > {self.OVERBROAD_THRESHOLD:.0%} threshold)"
                )
                return []
            # Return a stable, deterministic ordering so results are reproducible.
            chunks = sorted(entry.chunk_ids)[:top_k]
            logger.info(
                f"[AttributeIndex] '{column}' → '{label}' "
                f"({n} chunks, returning top {len(chunks)})"
            )
            return chunks

        # Find best matching attribute
        canonical_query = self._canonicalize_attribute(column)

        # Try exact match first
        if canonical_query in self.attr_to_chunks[table]:
            entry = self.attr_to_chunks[table][canonical_query]
            return _check_and_return(entry, canonical_query)

        # Fuzzy match on canonical names
        candidates = list(self.attr_to_chunks[table].keys())
        matches = difflib.get_close_matches(canonical_query, candidates, n=3, cutoff=0.6)

        if not matches:
            logger.warning(f"[AttributeIndex] No match for column '{column}' in table '{table}'")
            return []

        best_match = matches[0]
        entry = self.attr_to_chunks[table][best_match]
        sim = difflib.SequenceMatcher(None, canonical_query, best_match).ratio()
        logger.info(
            f"[AttributeIndex] Fuzzy match: '{column}' → '{best_match}' "
            f"(similarity={sim:.2f})"
        )
        return _check_and_return(entry, best_match)
    
    def get_coverage_stats(self, table: str) -> Dict[str, int]:
        """Get statistics about attribute coverage for a table."""
        if table not in self.attr_to_chunks:
            return {}
        
        stats = {}
        for canonical, entry in self.attr_to_chunks[table].items():
            stats[canonical] = len(entry.chunk_ids)
        
        return stats
    
    def save(self, path: Path) -> None:
        """Save index to disk."""
        data = {
            'chunk_to_attrs': dict(self.chunk_to_attrs),
            'attr_to_chunks': {
                table: {
                    attr: {
                        'canonical_name': entry.canonical_name,
                        'variants': list(entry.variants),
                        'chunk_ids': list(entry.chunk_ids)
                    }
                    for attr, entry in entries.items()
                }
                for table, entries in self.attr_to_chunks.items()
            }
        }
        
        path.write_text(json.dumps(data, indent=2))
        logger.info(f"Saved attribute index to {path}")
    
    @classmethod
    def load(cls, path: Path) -> 'AttributeIndex':
        """Load index from disk."""
        if not path.exists():
            logger.warning(f"Attribute index not found at {path}, creating new")
            return cls()
        
        data = json.loads(path.read_text())
        index = cls()
        
        # Restore chunk_to_attrs
        index.chunk_to_attrs = defaultdict(dict, data['chunk_to_attrs'])
        
        # Restore attr_to_chunks
        for table, entries in data['attr_to_chunks'].items():
            index.attr_to_chunks[table] = {}
            for attr, entry_data in entries.items():
                index.attr_to_chunks[table][attr] = AttributeIndexEntry(
                    canonical_name=entry_data['canonical_name'],
                    variants=set(entry_data['variants']),
                    chunk_ids=set(entry_data['chunk_ids'])
                )
        
        logger.info(f"Loaded attribute index from {path} ({len(index.attr_to_chunks)} tables)")
        return index
    
    @staticmethod
    def _canonicalize_attribute(attr: str) -> str:
        """
        Canonicalize attribute name for fuzzy matching.
        
        Examples:
            "State" → "state"
            "State Name" → "state_name"
            "state-name" → "state_name"
            "StateOfResidence" → "state_of_residence"
        """
        # Lowercase
        canonical = attr.lower().strip()
        
        # Replace spaces and hyphens with underscores
        canonical = canonical.replace(' ', '_').replace('-', '_')
        
        # Insert underscores before capitals in camelCase (e.g., "stateName" → "state_name")
        result = []
        for i, char in enumerate(canonical):
            if char.isupper() and i > 0 and result[-1] != '_':
                result.append('_')
            result.append(char.lower())
        canonical = ''.join(result)
        
        # Remove multiple consecutive underscores
        while '__' in canonical:
            canonical = canonical.replace('__', '_')
        
        # Strip leading/trailing underscores
        canonical = canonical.strip('_')
        
        return canonical
