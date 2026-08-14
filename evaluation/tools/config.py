from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass
class EvalSettings:
    """Global knobs for evaluation."""

    float_tolerance: float = 0.0  # absolute tolerance for float comparison
    multi_value_sep: str = "||"
    llm_provider: str = "none"  # openai/azure/none
    llm_model: Optional[str] = None
    cache_path: Optional[Path] = None
    log_level: str = "INFO"
    semantic_join_enabled: bool = False
    semantic_join_topk: int = 5
    semantic_join_score_threshold: float = 0.0
    semantic_join_max_query: int = 200
    semantic_join_debug_dir: Optional[Path] = None
    semantic_join_vector_prefilter_enabled: bool = True


@dataclass
class Paths:
    """Input/output path conventions."""

    dataset: str
    sql_file: Path
    result_csv: Path
    attributes_file: Optional[Path] = None
    output_dir: Optional[Path] = None
    gt_dir: Optional[Path] = None
    base_dir: Path = field(default_factory=lambda: Path("."))

    def resolve_attributes(self) -> Path:
        if self.attributes_file:
            return Path(self.attributes_file)
        pattern = Path(self.base_dir) / "Query" / self.dataset / "*_attributes.json"
        matches = sorted(pattern.parent.glob(pattern.name))
        if not matches:
            raise FileNotFoundError(f"Attributes json not found under {pattern.parent}")
        return matches[0]

    def resolve_gt_dir(self) -> Path:
        if self.gt_dir:
            return Path(self.gt_dir)
        return Path(self.base_dir) / "Query" / self.dataset

    def resolve_output_dir(self) -> Path:
        if self.output_dir:
            return Path(self.output_dir)
        return Path(self.result_csv).parent / "acc_result"


def load_json(path: Path) -> Dict:
    import json

    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(data: Dict, path: Path) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
