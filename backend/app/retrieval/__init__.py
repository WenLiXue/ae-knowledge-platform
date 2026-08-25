"""检索服务（DD-19 §12）：独立 Retrieval Service，返回可解释证据，不生成答案。"""

from .config import RetrievalConfig, load_retrieval_config
from .core import Candidate, evidence_status, rrf_fuse, select_evidence, sort_final
from .errors import RetrievalError
from .filters import VersionRef, recheck_active_version_ids, resolve_active_versions, validate_filters
from .query_plan import build_query_plan
from .schemas import EvidenceItem, QueryPlan, RetrievalFilters
from .service import RetrievalResult, RetrievalService, build_retrieval_service

__all__ = [
    "Candidate",
    "EvidenceItem",
    "QueryPlan",
    "RetrievalConfig",
    "RetrievalError",
    "RetrievalFilters",
    "RetrievalResult",
    "RetrievalService",
    "VersionRef",
    "build_query_plan",
    "build_retrieval_service",
    "evidence_status",
    "load_retrieval_config",
    "recheck_active_version_ids",
    "resolve_active_versions",
    "rrf_fuse",
    "select_evidence",
    "sort_final",
    "validate_filters",
]
