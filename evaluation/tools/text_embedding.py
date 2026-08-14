from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

import litellm
import yaml


class TextApiEmbeddings:
    def __init__(
        self,
        model_name: str,
        api_base: str | None = None,
        api_key: str | None = None,
        emb_dim: int | None = None,
        batch_size: int = 32,
        max_input_chars: int = 8190,
    ) -> None:
        self.model_name = model_name
        self.api_base = api_base
        self.api_key = api_key
        self.batch_size = batch_size
        self.max_input_chars = max_input_chars
        self.emb_dim = emb_dim if emb_dim is not None else self._probe_emb_dim()

    def _probe_emb_dim(self) -> int:
        response = litellm.embedding(
            model=self.model_name,
            input=["probe"],
            api_base=self.api_base,
            api_key=self.api_key,
        )
        first_emb = response.data[0]["embedding"]
        return len(first_emb)

    def get_emb_dim(self) -> int:
        return self.emb_dim

    def get_emb_model_name(self) -> str:
        return self.model_name

    def _truncate_if_needed(self, text: str) -> str:
        if len(text) > self.max_input_chars:
            return text[: self.max_input_chars]
        return text

    def emb(self, text: str) -> List[float]:
        clean_text = self._truncate_if_needed(text)
        response = litellm.embedding(
            model=self.model_name,
            input=[clean_text],
            api_base=self.api_base,
            api_key=self.api_key,
        )
        return response.data[0]["embedding"]

    def emb_batch(self, text_list: Sequence[str]) -> List[List[float]]:
        all_embeddings: List[List[float]] = []
        for start in range(0, len(text_list), self.batch_size):
            batch = text_list[start : start + self.batch_size]
            clean_batch = [self._truncate_if_needed(text) for text in batch]
            response = litellm.embedding(
                model=self.model_name,
                input=clean_batch,
                api_base=self.api_base,
                api_key=self.api_key,
            )
            for record in response.data:
                all_embeddings.append(record["embedding"])
        return all_embeddings


def load_text_model_config(config_path: Path) -> dict:
    with config_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if "text" not in cfg:
        raise ValueError(f"Missing 'text' section in config: {config_path}")
    return cfg["text"]


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config_path = repo_root / "config" / "embedding_model.yaml"
    text_cfg = load_text_model_config(config_path)

    embeddings = TextApiEmbeddings(
        model_name=text_cfg.get("model"),
        api_base=text_cfg.get("api_base"),
        api_key=text_cfg.get("api_key"),
        batch_size=32,
        max_input_chars=8190,
    )

    sample = "OpenDocDB embedding quick check."
    single_vector = embeddings.emb(sample)
    print(f"Model: {embeddings.get_emb_model_name()}")
    print(f"Embedding dimension: {embeddings.get_emb_dim()}")
    print(f"Single text embedding length: {len(single_vector)}")
    print(f"Single embedding preview (first 6 values): {single_vector[:6]}")

    batch_texts = [
        "第一条测试文本，用于批量验证。",
        "Second sample text for batch embedding.",
        "Litellm client demo for AiHubMix embeddings.",
    ]
    batch_vectors = embeddings.emb_batch(batch_texts)
    print(f"Batch size: {len(batch_vectors)}; each vector length: {len(batch_vectors[0]) if batch_vectors else 0}")
    print(
        "Batch embedding previews (first 3 values each): "
        f"{[vec[:3] for vec in batch_vectors]}"
    )


if __name__ == "__main__":
    main()
