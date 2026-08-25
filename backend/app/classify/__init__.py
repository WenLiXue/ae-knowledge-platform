"""文档分类器（DD-19 §8）。

- 输入构造 / Prompt / 校验 / 决策 / 短事务编排见各子模块；
- 人工确认 API 见 api_admin.py 与 confirmation.py。
"""

from .config import ClassificationConfig, build_taxonomy, load_classification_config
from .input_builder import build_input_blocks, compute_input_hash
from .schemas import (
    ClassificationInput,
    ClassificationOutput,
    EvidenceBlock,
    FieldEvidence,
)
from .service import (
    ClassificationError,
    ClassificationRunResult,
    IRRELEVANT,
    RELEVANT,
    UNCERTAIN,
    run_classification,
)
from .validator import ValidationIssue, ValidationResult, decide, validate_output

__all__ = [
    "ClassificationConfig",
    "ClassificationError",
    "ClassificationInput",
    "ClassificationOutput",
    "ClassificationRunResult",
    "EvidenceBlock",
    "FieldEvidence",
    "IRRELEVANT",
    "RELEVANT",
    "UNCERTAIN",
    "ValidationIssue",
    "ValidationResult",
    "build_input_blocks",
    "build_taxonomy",
    "compute_input_hash",
    "decide",
    "load_classification_config",
    "run_classification",
    "validate_output",
]
