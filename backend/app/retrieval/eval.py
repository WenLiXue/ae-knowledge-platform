"""黄金问题检索评测（DD-19 §18.3、DD-07 §20）。

读取《RAG 业务黄金问题集》CSV，对每题执行检索并计算：
- Recall@K：正确来源是否进入候选（默认 K=融合后候选数）；
- MRR：第一个正确来源候选的倒数排名；
- 证据 Precision：最终证据来自允许来源的比例；
- 旧版本误召回率：候选是否混入非当前可查询版本（必须为 0）。

报告可保存为 JSON/Markdown，用于跨模型/切片/索引变更的可比较回归（AC-TEST-001）。
只记录 ID/来源/分数/计数，不保存完整问题正文以外的最小快照；题目文本本身是评测输入，
属于可接受记录。
"""

from __future__ import annotations

import csv
import json
import logging
import re
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.knowledge import KnowledgeSource
from .errors import RetrievalError
from .filters import recheck_active_version_ids
from .service import RetrievalService

logger = logging.getLogger(__name__)

# 非文档来源的系统行为题/待入库案件不参与检索评测
_SKIP_REQUIRED_SOURCE = {"业务规则"}
_SKIP_SOURCE_LOCATION = {"待入库", "澄清规则", "无充分来源", "来源冲突规则"}


@dataclass
class GoldenCase:
    case_id: str
    status: str
    category: str
    question_type: str
    question: str
    expected_behavior: str
    key_points: str
    required_source: str
    source_location: str
    forbidden_claims: str = ""


@dataclass
class CaseResult:
    case_id: str
    question: str
    required_source: str
    skipped: bool = False
    skip_reason: str | None = None
    candidate_sources: list[str] = field(default_factory=list)
    evidence_sources: list[str] = field(default_factory=list)
    recall_at_k: bool = False
    mrr: float = 0.0
    evidence_precision: float = 0.0
    candidate_source_precision: float = 0.0
    evidence_count: int = 0
    stale_version_recalled: bool = False
    error_code: str | None = None


@dataclass
class EvalReport:
    cases: list[CaseResult]
    total: int
    executed: int
    skipped: int
    recall_at_k: float
    mrr: float
    evidence_precision: float
    candidate_source_precision: float
    average_evidence_count: float
    stale_version_recall_rate: float
    retrieval_config_revision: int | None = None


def load_golden(path: str | Path) -> list[GoldenCase]:
    """解析黄金集 CSV（含表头 case_id,status,category,question_type,user_question,...）。"""
    cases: list[GoldenCase] = []
    with open(path, encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            cases.append(
                GoldenCase(
                    case_id=(row.get("case_id") or "").strip(),
                    status=(row.get("status") or "").strip(),
                    category=(row.get("category") or "").strip(),
                    question_type=(row.get("question_type") or "").strip(),
                    question=(row.get("user_question") or "").strip(),
                    expected_behavior=(row.get("expected_behavior") or "").strip(),
                    key_points=(row.get("expected_key_points") or "").strip(),
                    required_source=(row.get("required_source") or "").strip(),
                    source_location=(row.get("source_location") or "").strip(),
                    forbidden_claims=(row.get("forbidden_claims") or "").strip(),
                )
            )
    return [c for c in cases if c.case_id]


_TITLE_SUFFIX_RE = re.compile(r"\.(?:docx?|pdf|xlsx?|pptx?|csv|txt|md)$", re.IGNORECASE)
_COPY_SUFFIX_RE = re.compile(
    r"\s*(?:\((?:副本|copy)?\s*\d+\)|（(?:副本|copy)?\s*\d+）)\s*$",
    re.IGNORECASE,
)


def _normalize_title(value: str) -> str:
    """将黄金集来源名和真实文档名归一化为可比较的稳定键。

    飞书附件经常带有书名号/方括号、空格、下划线、文件扩展名和 ``(1)``
    之类的副本后缀。这里仅消除这些展示差异，并统一 FAQ 的中英文写法；不做
    任意模糊匹配，避免把名称相近但内容不同的文档当成同一来源。
    """
    text = unicodedata.normalize("NFKC", value or "").strip().casefold()
    text = _TITLE_SUFFIX_RE.sub("", text)
    text = _COPY_SUFFIX_RE.sub("", text)
    text = re.sub(r"[\s_\-—–·•/\\\[\]【】()（）《》〈〉]+", "", text)
    return text.replace("常见问题", "faq")


def _title_match(a: str, b: str) -> bool:
    left = _normalize_title(a)
    right = _normalize_title(b)
    return bool(left and right and (left in right or right in left))


def _resolve_source_ids(db: Session, required_source: str) -> list[uuid.UUID]:
    rows = db.execute(
        select(KnowledgeSource).where(KnowledgeSource.status == "QUERYABLE")
    ).scalars().all()
    return [s.id for s in rows if _title_match(required_source, s.display_name)]


def evaluate(
    db: Session,
    service: RetrievalService,
    cases: list[GoldenCase],
    *,
    top_k: int | None = None,
) -> EvalReport:
    """对每题执行检索并计算指标。跳过：未确认、系统行为（业务规则）、待入库案件、
    或要求来源不在当前知识库。"""
    active_version_ids = recheck_active_version_ids(db)
    results: list[CaseResult] = []
    last_config_revision: int | None = None

    for case in cases:
        result = CaseResult(
            case_id=case.case_id,
            question=case.question,
            required_source=case.required_source,
        )
        if case.status != "confirmed":
            result.skipped, result.skip_reason = True, "status 未确认"
            results.append(result)
            continue
        if case.required_source in _SKIP_REQUIRED_SOURCE or case.source_location in _SKIP_SOURCE_LOCATION:
            result.skipped, result.skip_reason = True, "系统行为/待入库，不参与检索评测"
            results.append(result)
            continue

        allowed_ids = _resolve_source_ids(db, case.required_source)
        if not allowed_ids:
            result.skipped, result.skip_reason = True, "要求来源不在当前知识库"
            results.append(result)
            continue
        allowed = {str(sid) for sid in allowed_ids}

        try:
            retrieval = service.retrieve(db, case.question)
            last_config_revision = retrieval.config_revision
        except RetrievalError as exc:
            result.error_code = exc.code
            result.skipped = True
            result.skip_reason = f"检索失败: {exc.code}"
            results.append(result)
            continue

        candidates = retrieval.ordered_candidates
        evidence = retrieval.evidence
        k = top_k if top_k and top_k > 0 else len(candidates)
        candidates = candidates[:k]

        result.candidate_sources = list(dict.fromkeys(c.source_id for c in candidates))
        result.evidence_sources = [str(ev.source_id) for ev in evidence]
        result.evidence_count = len(evidence)
        if candidates:
            result.candidate_source_precision = sum(1 for c in candidates if c.source_id in allowed) / len(candidates)

        first_allowed_rank = next(
            (rank for rank, c in enumerate(candidates, start=1) if c.source_id in allowed), None
        )
        result.recall_at_k = first_allowed_rank is not None
        result.mrr = 1.0 / first_allowed_rank if first_allowed_rank else 0.0
        if evidence:
            result.evidence_precision = (
                sum(1 for ev in evidence if str(ev.source_id) in allowed) / len(evidence)
            )
        result.stale_version_recalled = any(c.version_id not in active_version_ids for c in candidates)
        results.append(result)

    executed = [r for r in results if not r.skipped]
    recall_at_k = _mean(r.recall_at_k for r in executed) if executed else 0.0
    mrr = _mean(r.mrr for r in executed) if executed else 0.0
    precision = _mean(r.evidence_precision for r in executed) if executed else 0.0
    candidate_precision = _mean(r.candidate_source_precision for r in executed) if executed else 0.0
    average_evidence_count = _mean(r.evidence_count for r in executed) if executed else 0.0
    stale_rate = (
        sum(1 for r in executed if r.stale_version_recalled) / len(executed) if executed else 0.0
    )
    return EvalReport(
        cases=results,
        total=len(results),
        executed=len(executed),
        skipped=len(results) - len(executed),
        recall_at_k=round(recall_at_k, 4),
        mrr=round(mrr, 4),
        evidence_precision=round(precision, 4),
        candidate_source_precision=round(candidate_precision, 4),
        average_evidence_count=round(average_evidence_count, 4),
        stale_version_recall_rate=round(stale_rate, 4),
        retrieval_config_revision=last_config_revision,
    )


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def report_to_dict(report: EvalReport) -> dict:
    return {
        "summary": {
            "total": report.total,
            "executed": report.executed,
            "skipped": report.skipped,
            "recall_at_k": report.recall_at_k,
            "mrr": report.mrr,
            "evidence_precision": report.evidence_precision,
            "candidate_source_precision": report.candidate_source_precision,
            "average_evidence_count": report.average_evidence_count,
            "stale_version_recall_rate": report.stale_version_recall_rate,
            "retrieval_config_revision": report.retrieval_config_revision,
        },
        "cases": [asdict(c) for c in report.cases],
    }


def report_to_markdown(report: EvalReport) -> str:
    lines = [
        "# 黄金问题检索评测报告",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 总题数 | {report.total} |",
        f"| 已执行 | {report.executed} |",
        f"| 跳过 | {report.skipped} |",
        f"| Recall@K | {report.recall_at_k} |",
        f"| MRR | {report.mrr} |",
        f"| 证据 Precision | {report.evidence_precision} |",
        f"| 候选来源 Precision@K | {report.candidate_source_precision} |",
        f"| 平均最终证据数 | {report.average_evidence_count} |",
        f"| 旧版本误召回率 | {report.stale_version_recall_rate} |",
        "",
        "## 明细",
        "",
        "| 题号 | 结果 | Recall | MRR | 证据Precision | 旧版本误召回 | 原因 |",
        "|---|---|---|---|---|---|---|",
    ]
    for case in report.cases:
        if case.skipped:
            lines.append(
                f"| {case.case_id} | 跳过 | - | - | - | - | {case.skip_reason} |"
            )
        else:
            lines.append(
                f"| {case.case_id} | {'通过' if case.recall_at_k else '未通过'} | "
                f"{int(case.recall_at_k)} | {case.mrr:.3f} | {case.evidence_precision:.2f} | "
                f"{int(case.stale_version_recalled)} | - |"
            )
    return "\n".join(lines) + "\n"


def save_report(report: EvalReport, out_path: str | Path, *, as_markdown: bool = False) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = report_to_markdown(report) if as_markdown else json.dumps(
        report_to_dict(report), ensure_ascii=False, indent=2
    )
    path.write_text(content, encoding="utf-8")
    return path
