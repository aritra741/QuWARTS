from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
from difflib import SequenceMatcher

from .comparators import LlmClient
from .config import EvalSettings
from .logging_utils import setup_logger
from .sql_parser import JoinInfo, ParsedQuery
from .utils import normalize_whitespace
from tqdm import tqdm


try:  # optional dependency
    from .text_embedding import TextApiEmbeddings, load_text_model_config  # type: ignore
except Exception:  # pragma: no cover - optional dependency guard
    TextApiEmbeddings = None  # type: ignore
    load_text_model_config = None  # type: ignore


def _safe_ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


class SeekDBClient:
    """
    Minimal in-memory vector index that mimics seekdb-style build/search API.
    Falls back to lexical similarity when embeddings are unavailable.
    """

    def __init__(self, logger_name: str = "semantic_join.seekdb") -> None:
        self.logger = setup_logger(logger_name)
        self.embedding_model = self._load_default_embedding_model()
        self._indices: Dict[int, Dict[str, List]] = {}
        self._next_index = 1

    def _load_default_embedding_model(self) -> Optional[TextApiEmbeddings]:
        if TextApiEmbeddings is None or load_text_model_config is None:
            return None
        try:
            cfg_path = Path(__file__).resolve().parents[3] / "config" / "embedding_model.yaml"
            text_cfg = load_text_model_config(cfg_path)
            return TextApiEmbeddings(
                model_name=text_cfg.get("model"),
                api_base=text_cfg.get("api_base"),
                api_key=text_cfg.get("api_key"),
                batch_size=32,
            )
        except Exception as exc:  # pragma: no cover - environment dependency
            self.logger.warning("Embedding model unavailable, fallback to lexical similarity: %s", exc)
            return None

    def build_index(self, docs: Sequence[str]) -> int:
        index_id = self._next_index
        self._next_index += 1
        if self.embedding_model:
            try:
                embeddings = self.embedding_model.emb_batch(list(docs))
                self._indices[index_id] = {"docs": list(docs), "embeddings": embeddings}
            except Exception as exc:  # pragma: no cover - runtime dependency
                self.logger.warning("Embedding build failed, fallback to lexical: %s", exc)
                self._indices[index_id] = {"docs": list(docs)}
        else:
            self._indices[index_id] = {"docs": list(docs)}
        return index_id

    def search(self, index_id: int, queries: Sequence[str], topk: int) -> List[List[Tuple[int, float]]]:
        index = self._indices.get(index_id)
        if not index:
            return [[] for _ in queries]

        docs: List[str] = index["docs"]
        if self.embedding_model and "embeddings" in index:
            try:
                results: List[List[Tuple[int, float]]] = []
                doc_embs: List[List[float]] = index["embeddings"]
                doc_norms = [self._norm(vec) for vec in doc_embs]
                query_embs = self.embedding_model.emb_batch(list(queries))
                for q_emb in query_embs:
                    q_norm = self._norm(q_emb)
                    scores: List[Tuple[int, float]] = []
                    for doc_idx, (doc_vec, doc_norm) in enumerate(zip(doc_embs, doc_norms)):
                        score = self._cosine(doc_vec, q_emb, doc_norm, q_norm)
                        scores.append((doc_idx, score))
                    top = sorted(scores, key=lambda x: x[1], reverse=True)[:topk]
                    results.append(top)
                return results
            except Exception as exc:  # pragma: no cover - runtime dependency
                self.logger.warning("Embedding search failed, fallback to lexical: %s", exc)

        # lexical fallback
        results = []
        for query in queries:
            scored = [(idx, _safe_ratio(query.lower(), doc.lower())) for idx, doc in enumerate(docs)]
            top = sorted(scored, key=lambda x: x[1], reverse=True)[:topk]
            results.append(top)
        return results

    def _cosine(self, a: Sequence[float], b: Sequence[float], norm_a: float, norm_b: float) -> float:
        if norm_a == 0 or norm_b == 0:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        return dot / (norm_a * norm_b)

    def _norm(self, vec: Sequence[float]) -> float:
        return math.sqrt(sum(v * v for v in vec))


class JoinLLMMatcher:
    """Lightweight LLM/lexical matcher for join keys."""

    def __init__(self, settings: EvalSettings, logger_name: str = "semantic_join.llm") -> None:
        self.llm_client = LlmClient(settings, logger_name=logger_name)

    def is_match(self, left_text: str, right_text: str, description: Optional[str] = None) -> bool:
        l_norm = normalize_whitespace(left_text).lower()
        r_norm = normalize_whitespace(right_text).lower()
        if l_norm == r_norm:
            return True
        if not self.llm_client.can_use_llm:
            return _safe_ratio(l_norm, r_norm) >= 0.85
        return self.llm_client.compare(left_text, right_text, description=description)


@dataclass
class SemanticPair:
    left_index: int
    right_index: int
    score: float


class SemanticJoinExecutor:
    """Execute exact join + semantic augmentation, returning augmented tables."""

    def __init__(
        self,
        settings: EvalSettings,
        attributes: Mapping,
        logger_name: str = "semantic_join",
    ) -> None:
        self.settings = settings
        self.attributes = attributes
        self.logger = setup_logger(logger_name)
        self.vector_client = (
            SeekDBClient(logger_name=f"{logger_name}.seekdb") if settings.semantic_join_vector_prefilter_enabled else None
        )
        self.matcher = JoinLLMMatcher(settings=settings, logger_name=f"{logger_name}.llm")

    def augment_tables(self, parsed_query: ParsedQuery, tables: Mapping[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        working: Dict[str, pd.DataFrame] = {table: df.copy() for table, df in tables.items()}
        if not parsed_query.joins:
            return working

        for join in parsed_query.joins:
            left_df = working.get(join.left_table)
            right_df = working.get(join.right_table)
            if left_df is None or right_df is None:
                continue
            updated_left, updated_right = self._augment_single_join(join, left_df, right_df)
            working[join.left_table] = updated_left
            working[join.right_table] = updated_right
        return working

    def _augment_single_join(
        self, join: JoinInfo, left_df: pd.DataFrame, right_df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        left_df = left_df.copy()
        right_df = right_df.copy()

        left_keys = join.left_keys
        right_keys = join.right_keys

        left_texts = [self._join_value_as_text(row, join.left_table, left_keys) for _, row in left_df.iterrows()]
        right_texts = [self._join_value_as_text(row, join.right_table, right_keys) for _, row in right_df.iterrows()]

        exact_pairs = {
            (i, j)
            for i, l in enumerate(left_texts)
            for j, r in enumerate(right_texts)
            if normalize_whitespace(l).lower() == normalize_whitespace(r).lower()
        }

        doc_side, _ = self._choose_sides(left_df, right_df)
        if doc_side == "left":
            doc_texts, query_texts = left_texts, right_texts
            doc_keys, query_keys = left_keys, right_keys
            doc_table, query_table = join.left_table, join.right_table
            doc_df, query_df = left_df, right_df
        else:
            doc_texts, query_texts = right_texts, left_texts
            doc_keys, query_keys = right_keys, left_keys
            doc_table, query_table = join.right_table, join.left_table
            doc_df, query_df = right_df, left_df

        candidates = self._generate_candidates(doc_texts, query_texts)
        hits: List[SemanticPair] = []

        total_pairs = sum(len(lst) for lst in candidates)
        llm_pairs = total_pairs - len(exact_pairs)
        progress = tqdm(total=llm_pairs, desc="LLM join match", unit="pair")
        description = self._build_join_description(doc_table, doc_keys, query_table, query_keys)
        for q_idx, doc_candidates in enumerate(candidates):
            if self.settings.semantic_join_max_query and q_idx >= self.settings.semantic_join_max_query:
                break
            for d_idx, score in doc_candidates:
                if doc_side == "left":
                    left_idx, right_idx = d_idx, q_idx
                else:
                    left_idx, right_idx = q_idx, d_idx
                if (left_idx, right_idx) in exact_pairs:
                    continue
                l_text = left_texts[left_idx]
                r_text = right_texts[right_idx]
                if score < self.settings.semantic_join_score_threshold:
                    progress.update(1)
                    continue
                if self.matcher.is_match(l_text, r_text, description=description):
                    hits.append(SemanticPair(left_index=left_idx, right_index=right_idx, score=score))
                progress.update(1)
        progress.close()

        if self.settings.semantic_join_debug_dir:
            self._dump_debug(
                join=join,
                candidates=candidates,
                hits=hits,
                left_texts=left_texts,
                right_texts=right_texts,
                doc_texts=doc_texts,
                query_texts=query_texts,
            )

        if not hits:
            return left_df, right_df

        if doc_side == "left":
            left_df = self._append_augmented_rows(left_df, right_df, hits, left_keys, right_keys, target="left")
        else:
            right_df = self._append_augmented_rows(right_df, left_df, hits, right_keys, left_keys, target="right")

        return left_df, right_df

    def _append_augmented_rows(
        self,
        target_df: pd.DataFrame,
        source_df: pd.DataFrame,
        hits: Sequence[SemanticPair],
        target_keys: Sequence[str],
        source_keys: Sequence[str],
        target: str,
    ) -> pd.DataFrame:
        new_rows: List[pd.Series] = []
        for pair in hits:
            target_idx, source_idx = (pair.left_index, pair.right_index) if target == "left" else (pair.right_index, pair.left_index)
            base_row = target_df.iloc[target_idx].copy()
            source_row = source_df.iloc[source_idx]
            for t_key, s_key in zip(target_keys, source_keys):
                if t_key in base_row and s_key in source_row:
                    base_row[t_key] = source_row[s_key]
            new_rows.append(base_row)
        if new_rows:
            target_df = pd.concat([target_df, pd.DataFrame(new_rows)], ignore_index=True)
        return target_df

    def _generate_candidates(self, doc_texts: Sequence[str], query_texts: Sequence[str]) -> List[List[Tuple[int, float]]]:
        if self.vector_client:
            index_id = self.vector_client.build_index(doc_texts)
            return self.vector_client.search(index_id, query_texts, topk=self.settings.semantic_join_topk)

        # No vector client: brute-force lexical topK
        candidates: List[List[Tuple[int, float]]] = []
        for q in query_texts:
            scored = [(idx, _safe_ratio(q.lower(), d.lower())) for idx, d in enumerate(doc_texts)]
            top = sorted(scored, key=lambda x: x[1], reverse=True)[: self.settings.semantic_join_topk]
            candidates.append(top)
        return candidates

    def _choose_sides(self, left_df: pd.DataFrame, right_df: pd.DataFrame) -> Tuple[str, str]:
        if len(left_df) >= len(right_df):
            return "left", "right"
        return "right", "left"

    def _join_value_as_text(self, row: pd.Series, table: str, keys: Sequence[str]) -> str:
        values = []
        for key in keys:
            val = row.get(key, "")
            if isinstance(val, float) and math.isnan(val):
                val = ""
            values.append(normalize_whitespace(str(val)))
        text = " [SEP] ".join(values).strip()
        return text if text else "<EMPTY>"

    def _build_join_description(
        self, left_table: str, left_keys: Sequence[str], right_table: str, right_keys: Sequence[str]
    ) -> str:
        lines: List[str] = []
        for table, keys in ((left_table, left_keys), (right_table, right_keys)):
            table_meta = self.attributes.get(table, {})
            for key in keys:
                meta = table_meta.get(key) if isinstance(table_meta, Mapping) else None
                desc = meta.get("description") if meta else None
                if desc:
                    lines.append(f"{table}.{key}: {desc}")
        return "\n".join(lines)

    def _dump_debug(
        self,
        join: JoinInfo,
        candidates: Sequence[Sequence[Tuple[int, float]]],
        hits: Sequence[SemanticPair],
        left_texts: Sequence[str],
        right_texts: Sequence[str],
        doc_texts: Sequence[str],
        query_texts: Sequence[str],
    ) -> None:
        debug_dir = Path(self.settings.semantic_join_debug_dir)
        debug_dir.mkdir(parents=True, exist_ok=True)

        cand_rows = []
        for q_idx, cand_list in enumerate(candidates):
            for d_idx, score in cand_list:
                cand_rows.append(
                    {
                        "query_index": q_idx,
                        "doc_index": d_idx,
                        "score": score,
                        "query_text": query_texts[q_idx] if q_idx < len(query_texts) else "",
                        "doc_text": doc_texts[d_idx] if d_idx < len(doc_texts) else "",
                    }
                )
        hits_rows = [
            {
                "left_index": pair.left_index,
                "right_index": pair.right_index,
                "score": pair.score,
                "left_text": left_texts[pair.left_index] if pair.left_index < len(left_texts) else "",
                "right_text": right_texts[pair.right_index] if pair.right_index < len(right_texts) else "",
            }
            for pair in hits
        ]

        cand_df = pd.DataFrame(cand_rows)
        hit_df = pd.DataFrame(hits_rows)
        cand_df.to_csv(debug_dir / f"{join.left_table}_{join.right_table}_candidates.csv", index=False)
        hit_df.to_csv(debug_dir / f"{join.left_table}_{join.right_table}_hits.csv", index=False)
