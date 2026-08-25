"""黄金问题检索评测 CLI（DD-19 §18.3 / Phase 5）。

用法（在 backend 目录下，需 docker ae-knowledge-postgres 在线）：
    ./.venv/Scripts/python.exe eval_retrieval.py
    ./.venv/Scripts/python.exe eval_retrieval.py --limit 5 --out reports/retrieval-eval-smoke.json
    ./.venv/Scripts/python.exe eval_retrieval.py --top-k 20 --md

读取《RAG业务黄金问题集》CSV，用当前配置的检索引擎（fake/opensearch）与已入库知识
对每题执行检索，输出 Recall@K / MRR / 证据 Precision / 旧版本误召回率，保存 JSON/MD 报告。
要求来源不在当前知识库的题目标记 SKIP；系统行为题与待入库案件不参与检索评测。
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.db.session import SessionLocal  # noqa: E402
from app.retrieval.eval import evaluate, load_golden, report_to_dict, save_report  # noqa: E402
from app.retrieval.service import build_retrieval_service  # noqa: E402

_DEFAULT_GOLDEN = os.path.join(_BACKEND_DIR, "..", "docs", "RAG业务黄金问题集_V0.1.csv")
_DEFAULT_OUT = os.path.join(_BACKEND_DIR, "reports")


def main() -> None:
    parser = argparse.ArgumentParser(description="黄金问题检索评测")
    parser.add_argument("--golden", default=_DEFAULT_GOLDEN, help="黄金集 CSV 路径")
    parser.add_argument("--out", default=None, help="报告输出路径（默认 reports/retrieval-eval-{日期}.json）")
    parser.add_argument("--limit", type=int, default=0, help="只评测前 N 题（0=全部）")
    parser.add_argument("--top-k", type=int, default=0, help="Recall@K 的 K（0=用融合后候选数）")
    parser.add_argument("--md", action="store_true", help="输出 Markdown 报告（默认 JSON）")
    args = parser.parse_args()

    cases = load_golden(args.golden)
    if args.limit:
        cases = cases[: args.limit]
    print(f"载入黄金题 {len(cases)} 道（{args.golden}）")

    service = build_retrieval_service()
    with SessionLocal() as db:
        report = evaluate(db, service, cases, top_k=args.top_k or None)

    if args.out:
        out_path = args.out
    else:
        os.makedirs(_DEFAULT_OUT, exist_ok=True)
        suffix = ".md" if args.md else ".json"
        out_path = os.path.join(
            _DEFAULT_OUT, f"retrieval-eval-{datetime.date.today().isoformat()}{suffix}"
        )
    saved = save_report(report, out_path, as_markdown=args.md)

    print("----------------------------------------")
    print(f"总题 {report.total} | 已执行 {report.executed} | 跳过 {report.skipped}")
    print(f"Recall@K      = {report.recall_at_k}")
    print(f"MRR           = {report.mrr}")
    print(f"证据 Precision = {report.evidence_precision}")
    print(f"旧版本误召回率  = {report.stale_version_recall_rate}")
    print(f"配置 revision  = {report.retrieval_config_revision}")
    print(f"报告已保存: {saved}")


if __name__ == "__main__":
    main()
