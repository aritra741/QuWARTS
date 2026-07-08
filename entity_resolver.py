"""
Proactive Entity Resolution for QuWARTS.
Implements blocking and matching with sentence transformers and cross-encoders.
"""

import json
import logging
import pickle
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass
from collections import defaultdict
import numpy as np

from sentence_transformers import SentenceTransformer, CrossEncoder
import faiss

from config import (
    BI_ENCODER_MODEL,
    CROSS_ENCODER_MODEL,
    BI_ENCODER_THRESHOLD,
    CROSS_ENCODER_THRESHOLD,
    TOP_K_CANDIDATES,
    CACHE_DIR
)

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class EntityMention:
    """Represents a mention of an entity."""
    mention_id: str
    value: str
    table_name: str
    column_name: str
    semantic_type: str
    record_id: Optional[str] = None

@dataclass
class EntityCluster:
    """Represents a cluster of entity mentions."""
    cluster_id: int
    canonical_form: str
    mentions: List[EntityMention]
    confidence: float

@dataclass
class ResolutionResult:
    """Result of entity resolution."""
    canonical_map: Dict[str, str]  # mention_value -> canonical_form
    clusters: List[EntityCluster]
    total_mentions: int
    total_clusters: int


# ============================================================================
# Union-Find Data Structure
# ============================================================================

class UnionFind:
    """Union-Find (Disjoint Set Union) for clustering."""
    
    def __init__(self, n: int):
        """Initialize with n elements."""
        self.parent = list(range(n))
        self.rank = [0] * n
    
    def find(self, x: int) -> int:
        """Find root of x with path compression."""
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]
    
    def union(self, x: int, y: int) -> bool:
        """Union two sets. Returns True if they were merged."""
        root_x = self.find(x)
        root_y = self.find(y)
        
        if root_x == root_y:
            return False
        
        # Union by rank
        if self.rank[root_x] < self.rank[root_y]:
            self.parent[root_x] = root_y
        elif self.rank[root_x] > self.rank[root_y]:
            self.parent[root_y] = root_x
        else:
            self.parent[root_y] = root_x
            self.rank[root_x] += 1
        
        return True
    
    def get_clusters(self) -> Dict[int, List[int]]:
        """Get all clusters as dict of root -> members."""
        clusters = defaultdict(list)
        for i in range(len(self.parent)):
            root = self.find(i)
            clusters[root].append(i)
        return dict(clusters)


# ============================================================================
# Entity Resolver
# ============================================================================

class EntityResolver:
    """
    Implements proactive entity resolution using:
    1. Bi-Encoder for blocking (fast similarity search)
    2. Cross-Encoder for matching (accurate comparison)
    3. Union-Find for clustering
    """
    
    def __init__(
        self,
        llm_client=None,
        bi_encoder_model: str = BI_ENCODER_MODEL,
        cross_encoder_model: str = CROSS_ENCODER_MODEL
    ):
        """Initialize entity resolver."""
        self.llm_client = llm_client
        
        # Load models - fail hard if download/network issues
        logger.info(f"Loading bi-encoder: {bi_encoder_model}")
        self.bi_encoder = SentenceTransformer(bi_encoder_model)
        
        logger.info(f"Loading cross-encoder: {cross_encoder_model}")
        self.cross_encoder = CrossEncoder(cross_encoder_model)
        
        # Cache
        import config as _config
        self.cache_dir = _config.CACHE_DIR / "entity_resolution"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Resolution cache
        self.canonical_maps: Dict[str, Dict[str, str]] = {}
    
    # ========================================================================
    # Main Resolution Pipeline
    # ========================================================================
    
    def resolve_entities(
        self,
        mentions: List[EntityMention],
        semantic_type: Optional[str] = None
    ) -> ResolutionResult:
        """
        Resolve entity mentions to canonical forms.
        
        Args:
            mentions: List of entity mentions
            semantic_type: Optional semantic type filter
            
        Returns:
            ResolutionResult with canonical map and clusters
        """
        logger.info(f"Resolving {len(mentions)} entity mentions")
        
        # Filter by semantic type if specified
        if semantic_type:
            mentions = [m for m in mentions if m.semantic_type == semantic_type]
            logger.info(f"Filtered to {len(mentions)} mentions of type {semantic_type}")
        
        if len(mentions) == 0:
            return ResolutionResult(
                canonical_map={},
                clusters=[],
                total_mentions=0,
                total_clusters=0
            )
        
        # Step 1: Blocking with bi-encoder
        blocks = self._blocking_phase(mentions)
        logger.info(f"Blocking produced {len(blocks)} blocks")
        
        # Step 2: Matching with cross-encoder
        clusters = self._matching_phase(mentions, blocks)
        logger.info(f"Matching produced {len(clusters)} clusters")
        
        # Step 3: Canonicalization with LLM
        canonical_clusters = self._canonicalization_phase(clusters, mentions)
        
        # Step 4: Build canonical map
        canonical_map = self._build_canonical_map(canonical_clusters, mentions)
        
        result = ResolutionResult(
            canonical_map=canonical_map,
            clusters=canonical_clusters,
            total_mentions=len(mentions),
            total_clusters=len(canonical_clusters)
        )
        
        logger.info(f"Resolution complete: {len(mentions)} mentions -> {len(canonical_clusters)} clusters")
        
        return result
    
    def _blocking_phase(self, mentions: List[EntityMention]) -> Dict[int, List[int]]:
        """
        Blocking phase: Use bi-encoder to find similar mentions.
        Returns blocks as dict of representative_idx -> [similar_indices]
        """
        # Extract unique values
        values = [m.value for m in mentions]
        
        # Encode with bi-encoder
        logger.info("Encoding mentions with bi-encoder...")
        embeddings = self.bi_encoder.encode(
            values,
            convert_to_numpy=True,
            show_progress_bar=False
        )
        
        # Normalize embeddings
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        
        # Build FAISS index
        dimension = embeddings.shape[1]
        index = faiss.IndexFlatIP(dimension)  # Inner product (cosine similarity)
        index.add(embeddings.astype('float32'))
        
        # Search for similar mentions
        logger.info("Searching for similar mentions...")
        k = min(TOP_K_CANDIDATES, len(mentions))
        similarities, indices = index.search(embeddings.astype('float32'), k)
        
        # Build blocks using Union-Find
        uf = UnionFind(len(mentions))
        
        for i in range(len(mentions)):
            for j, sim in zip(indices[i], similarities[i]):
                if i != j and sim >= BI_ENCODER_THRESHOLD:
                    uf.union(i, j)
        
        # Get clusters
        blocks = uf.get_clusters()
        
        return blocks
    
    def _matching_phase(
        self,
        mentions: List[EntityMention],
        blocks: Dict[int, List[int]]
    ) -> Dict[int, List[int]]:
        """
        Matching phase: Use cross-encoder to refine blocks.
        Returns refined clusters.
        """
        refined_clusters = {}
        
        for block_id, block_indices in blocks.items():
            if len(block_indices) == 1:
                # Single mention, no need to match
                refined_clusters[block_id] = block_indices
                continue
            
            # Get mention values
            block_values = [mentions[i].value for i in block_indices]
            
            # Build pairs for cross-encoder
            pairs = []
            pair_indices = []
            
            for i in range(len(block_indices)):
                for j in range(i + 1, len(block_indices)):
                    pairs.append([block_values[i], block_values[j]])
                    pair_indices.append((i, j))
            
            if not pairs:
                refined_clusters[block_id] = block_indices
                continue
            
            # Score pairs with cross-encoder
            scores = self.cross_encoder.predict(pairs)
            
            # Build refined clusters using Union-Find
            uf = UnionFind(len(block_indices))
            
            for (i, j), score in zip(pair_indices, scores):
                if score >= CROSS_ENCODER_THRESHOLD:
                    uf.union(i, j)
            
            # Get refined clusters
            sub_clusters = uf.get_clusters()
            
            # Map back to original indices
            for sub_cluster_id, sub_cluster in sub_clusters.items():
                original_indices = [block_indices[i] for i in sub_cluster]
                new_id = f"{block_id}_{sub_cluster_id}"
                refined_clusters[new_id] = original_indices
        
        return refined_clusters
    
    def _canonicalization_phase(
        self,
        clusters: Dict[Any, List[int]],
        mentions: List[EntityMention]
    ) -> List[EntityCluster]:
        """
        Canonicalization phase: Determine canonical form for each cluster.
        """
        canonical_clusters = []
        
        for cluster_id, cluster_indices in clusters.items():
            # Get mention values
            cluster_values = [mentions[i].value for i in cluster_indices]
            cluster_mentions = [mentions[i] for i in cluster_indices]
            
            # Determine canonical form
            if len(cluster_values) == 1:
                canonical_form = cluster_values[0]
                confidence = 1.0
            else:
                canonical_form, confidence = self._select_canonical_form(cluster_values)
            
            # Create cluster
            entity_cluster = EntityCluster(
                cluster_id=hash(str(cluster_id)),
                canonical_form=canonical_form,
                mentions=cluster_mentions,
                confidence=confidence
            )
            
            canonical_clusters.append(entity_cluster)
        
        return canonical_clusters
    
    def _select_canonical_form(
        self,
        values: List[str]
    ) -> Tuple[str, float]:
        """
        Select canonical form from a list of values.
        Uses LLM if available, otherwise uses heuristics.
        """
        # Use LLM if available
        if self.llm_client:
            canonical, confidence = self._llm_canonical_form(values)
            return canonical, confidence
        else:
            # No LLM available - use heuristics
            return self._heuristic_canonical_form(values)
    
    def _llm_canonical_form(
        self,
        values: List[str]
    ) -> Tuple[str, float]:
        """Use LLM to select canonical form."""
        values_str = "\n".join([f"- {v}" for v in values])
        
        prompt = f"""Given these variations of the same entity, select the most canonical (standard) form.

Variations:
{values_str}

Respond with ONLY the canonical form, nothing else.
"""
        
        response = self.llm_client.generate(
            prompt,
            max_tokens=50,
            temperature=0.0
        )
        
        canonical = response.strip()
        
        # Check if response is one of the values
        if canonical in values:
            confidence = 0.95
        else:
            # LLM generated a new form
            confidence = 0.85
        
        return canonical, confidence
    
    def _heuristic_canonical_form(
        self,
        values: List[str]
    ) -> Tuple[str, float]:
        """Use heuristics to select canonical form."""
        # Prefer longest value (usually most complete)
        canonical = max(values, key=len)
        confidence = 0.7
        
        return canonical, confidence
    
    def _build_canonical_map(
        self,
        clusters: List[EntityCluster],
        mentions: List[EntityMention]
    ) -> Dict[str, str]:
        """Build canonical map from clusters."""
        canonical_map = {}
        
        for cluster in clusters:
            for mention in cluster.mentions:
                # Normalize key (lowercase)
                key = mention.value.lower().strip()
                canonical_map[key] = cluster.canonical_form
        
        return canonical_map
    
    # ========================================================================
    # Cross-Table Resolution
    # ========================================================================
    
    def resolve_across_tables(
        self,
        table_mentions: Dict[str, List[EntityMention]]
    ) -> Dict[str, ResolutionResult]:
        """
        Resolve entities across multiple tables.
        
        Args:
            table_mentions: Dict of table_name -> mentions
            
        Returns:
            Dict of table_name -> ResolutionResult
        """
        logger.info(f"Resolving entities across {len(table_mentions)} tables")
        
        # Group mentions by semantic type
        type_mentions = defaultdict(list)
        
        for table_name, mentions in table_mentions.items():
            for mention in mentions:
                type_mentions[mention.semantic_type].append(mention)
        
        # Resolve each semantic type
        results = {}
        
        for semantic_type, mentions in type_mentions.items():
            logger.info(f"Resolving {len(mentions)} mentions of type {semantic_type}")
            
            result = self.resolve_entities(mentions, semantic_type)
            
            # Store result by semantic type
            results[semantic_type] = result
        
        # Build per-table results
        table_results = {}
        
        for table_name in table_mentions.keys():
            # Combine results for this table
            combined_map = {}
            
            for semantic_type, result in results.items():
                combined_map.update(result.canonical_map)
            
            table_results[table_name] = ResolutionResult(
                canonical_map=combined_map,
                clusters=[],
                total_mentions=len(table_mentions[table_name]),
                total_clusters=0
            )
        
        return table_results
    
    # ========================================================================
    # JIT Join Alignment
    # ========================================================================
    
    def align_join_keys(
        self,
        left_values: List[str],
        right_values: List[str],
        left_table: str,
        right_table: str,
        join_column: str
    ) -> Dict[str, str]:
        """
        Align join keys between two tables using entity resolution.
        
        Args:
            left_values: Values from left table
            right_values: Values from right table
            left_table: Name of left table
            right_table: Name of right table
            join_column: Name of join column
            
        Returns:
            Canonical map for join alignment
        """
        logger.info(f"Aligning join keys for {left_table}.{join_column} <-> {right_table}.{join_column}")
        
        # Create mentions
        mentions = []
        
        for value in left_values:
            mentions.append(EntityMention(
                mention_id=f"{left_table}_{value}",
                value=value,
                table_name=left_table,
                column_name=join_column,
                semantic_type="JOIN_KEY"
            ))
        
        for value in right_values:
            mentions.append(EntityMention(
                mention_id=f"{right_table}_{value}",
                value=value,
                table_name=right_table,
                column_name=join_column,
                semantic_type="JOIN_KEY"
            ))
        
        # Resolve
        result = self.resolve_entities(mentions)
        
        logger.info(f"Join alignment complete: {len(mentions)} values -> {result.total_clusters} clusters")
        
        return result.canonical_map
    
    # ========================================================================
    # Caching
    # ========================================================================
    
    def save_resolution(
        self,
        table_name: str,
        result: ResolutionResult
    ) -> None:
        """Save resolution result to cache."""
        cache_file = self.cache_dir / f"{table_name}_resolution.pkl"
        
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(result, f)
            
            logger.info(f"Saved resolution for {table_name}")
        
        except Exception as e:
            logger.warning(f"Error saving resolution: {e}")
    
    def load_resolution(
        self,
        table_name: str
    ) -> Optional[ResolutionResult]:
        """Load resolution result from cache."""
        cache_file = self.cache_dir / f"{table_name}_resolution.pkl"
        
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'rb') as f:
                result = pickle.load(f)
            
            logger.info(f"Loaded resolution for {table_name}")
            return result
        
        except Exception as e:
            logger.warning(f"Error loading resolution: {e}")
            return None
    
    # ========================================================================
    # Query Rewriting
    # ========================================================================
    
    def rewrite_query_values(
        self,
        query: str,
        canonical_map: Dict[str, str]
    ) -> str:
        """
        Rewrite query to use canonical forms.
        
        Args:
            query: SQL query string
            canonical_map: Mapping of values to canonical forms
            
        Returns:
            Rewritten query
        """
        rewritten = query
        
        # Replace each value with its canonical form
        for mention, canonical in canonical_map.items():
            # Case-insensitive replacement in WHERE clauses
            import re
            
            # Pattern for string literals
            pattern = rf"['\"]({re.escape(mention)})['\"]"
            replacement = f"'{canonical}'"
            
            rewritten = re.sub(
                pattern,
                replacement,
                rewritten,
                flags=re.IGNORECASE
            )
        
        return rewritten


# ============================================================================
# Utility Functions
# ============================================================================

def extract_mentions_from_records(
    records: List[Dict[str, Any]],
    table_name: str,
    schema: Dict[str, str]
) -> List[EntityMention]:
    """Extract entity mentions from records."""
    mentions = []
    
    for record_idx, record in enumerate(records):
        for col_name, value in record.items():
            if value is None or value == "":
                continue
            
            semantic_type = schema.get(col_name, "OTHER")
            
            mention = EntityMention(
                mention_id=f"{table_name}_{record_idx}_{col_name}",
                value=str(value),
                table_name=table_name,
                column_name=col_name,
                semantic_type=semantic_type,
                record_id=str(record_idx)
            )
            
            mentions.append(mention)
    
    return mentions


def apply_canonical_map(
    records: List[Dict[str, Any]],
    canonical_map: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Apply canonical map to records."""
    normalized_records = []
    
    for record in records:
        normalized = {}
        
        for key, value in record.items():
            if value is None or value == "":
                normalized[key] = value
            else:
                # Normalize key
                value_key = str(value).lower().strip()
                
                # Lookup canonical form
                canonical = canonical_map.get(value_key, value)
                normalized[key] = canonical
        
        normalized_records.append(normalized)
    
    return normalized_records
