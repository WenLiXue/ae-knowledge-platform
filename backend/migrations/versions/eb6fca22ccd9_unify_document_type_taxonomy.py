"""unify document type taxonomy

统一文档类型目录为 DD-19 §4.1 的 12 类稳定 code。

升级策略（DD-19 §4.3）：
1. 保留 requirement/design/fault-analysis/test-report 的主键和 code，更新名称、说明、顺序；
2. 将现有 manual 原位迁移为 operation-manual（迁移前检查引用，存在引用则明确失败）；
3. 以固定 UUID 插入其余 7 个类型；
4. 使用 INSERT ... ON CONFLICT (code) DO UPDATE，使开发库重复数据可收敛；
5. 不删除管理员新增类型；不强制改动已有行的 status（避免静默覆盖管理员停用）；
6. downgrade 只删除本迁移新增且未被引用的记录，并将 operation-manual 恢复为 manual；
   存在引用时 downgrade 明确失败。

Revision ID: eb6fca22ccd9
Revises: 1a2b3c4d5e6f
Create Date: 2026-08-25 14:17:59.844411

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'eb6fca22ccd9'
down_revision: Union[str, Sequence[str], None] = '1a2b3c4d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 12 类正式目录（DD-19 §4.1）。id 为固定 UUID；保留行的 id 不变，缺失行按此补插。
_TAXONOMY = [
    # (id, code, name, description, sort_order)
    ("00000000-0000-0000-0000-000000000036", "product-spec", "产品规格", "硬件规格、参数表、型号清单", 10),
    ("00000000-0000-0000-0000-000000000037", "product-whitepaper", "产品白皮书", "产品定位、架构、能力总览", 20),
    ("00000000-0000-0000-0000-000000000031", "requirement", "需求说明书", "产品或项目需求", 30),
    ("00000000-0000-0000-0000-000000000032", "design", "设计文档", "概要设计、详细设计、开发设计", 40),
    ("00000000-0000-0000-0000-000000000038", "deployment-guide", "部署说明", "安装、部署、升级、环境要求", 50),
    ("00000000-0000-0000-0000-000000000035", "operation-manual", "操作手册", "配置、使用、运维步骤", 60),
    ("00000000-0000-0000-0000-000000000034", "test-report", "测试报告", "测试范围、过程和结论", 70),
    ("00000000-0000-0000-0000-000000000033", "fault-analysis", "故障分析", "故障定位、原因和处理办法", 80),
    ("00000000-0000-0000-0000-000000000039", "seg-case", "SEG 问题案件", "客户问题、处理过程和关闭结论", 90),
    ("00000000-0000-0000-0000-000000000040", "compatibility-list", "兼容性清单", "操作系统、版本、硬件兼容矩阵", 100),
    ("00000000-0000-0000-0000-000000000041", "release-note", "版本说明", "发布说明、变更点、已知问题", 110),
    ("00000000-0000-0000-0000-000000000099", "other", "其他资料", "明确相关但无法归入已知类型", 999),
]

_NEW_CODES = ["product-spec", "product-whitepaper", "deployment-guide",
              "seg-case", "compatibility-list", "release-note", "other"]
_NEW_IDS = ["00000000-0000-0000-0000-000000000036", "00000000-0000-0000-0000-000000000037",
            "00000000-0000-0000-0000-000000000038", "00000000-0000-0000-0000-000000000039",
            "00000000-0000-0000-0000-000000000040", "00000000-0000-0000-0000-000000000041",
            "00000000-0000-0000-0000-000000000099"]


def _rows() -> str:
    return ",\n".join(
        f"('{i}', '{c}', '{n}', '{d}', 'ENABLED', {s})" for i, c, n, d, s in _TAXONOMY
    )


def _in_list(items: list[str]) -> str:
    return ", ".join(f"'{x}'" for x in items)


def upgrade() -> None:
    """统一文档类型目录为 12 类稳定 code。"""
    op.execute(
        f"""
        -- 0) 防御性守卫：任何表引用 document_types 时不允许直接迁移 code（DD-19 §4.3 第 2 条）。
        --    当前知识库无引用表；若未来出现引用，须先更新引用表再修改 code。
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.referential_constraints rc
                WHERE rc.unique_constraint_schema = 'knowledge'
                  AND EXISTS (
                      SELECT 1 FROM information_schema.constraint_column_usage ccu
                      WHERE ccu.constraint_schema = rc.unique_constraint_schema
                        AND ccu.constraint_name = rc.unique_constraint_name
                        AND ccu.table_name = 'document_types'
                  )
            ) THEN
                RAISE EXCEPTION 'blocked: document_types is referenced; '
                                'update referencing tables before taxonomy migration (DD-19 §4.3)';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        -- 1) manual → operation-manual 原位迁移（保留行 id，仅改 code/名称/说明/顺序）。
        --    已存在 operation-manual 时跳过重命名（避免唯一冲突），由下方 upsert 收敛字段。
        UPDATE knowledge.document_types
           SET code = 'operation-manual', name = '操作手册', description = NULL,
               status = 'ENABLED', sort_order = 60
         WHERE code = 'manual'
           AND NOT EXISTS (SELECT 1 FROM knowledge.document_types WHERE code = 'operation-manual');
        """
    )
    op.execute(
        f"""
        -- 2) 12 类正式目录 upsert：已有行保留 id、仅收敛 name/description/sort_order，
        --    不强制改 status（避免静默覆盖管理员停用）；缺失行按固定 UUID 补插（ENABLED）。
        INSERT INTO knowledge.document_types (id, code, name, description, status, sort_order)
        VALUES
            {_rows()}
        ON CONFLICT (code) DO UPDATE
            SET name = EXCLUDED.name,
                description = EXCLUDED.description,
                sort_order = EXCLUDED.sort_order;
        """
    )


def downgrade() -> None:
    """删除本迁移新增的 7 类并恢复 operation-manual → manual；存在引用则明确失败。"""
    op.execute(
        f"""
        -- 0) 存在引用时明确失败，不静默破坏数据（DD-19 §4.3 第 6 条）。
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.referential_constraints rc
                WHERE rc.unique_constraint_schema = 'knowledge'
                  AND EXISTS (
                      SELECT 1 FROM information_schema.constraint_column_usage ccu
                      WHERE ccu.constraint_schema = rc.unique_constraint_schema
                        AND ccu.constraint_name = rc.unique_constraint_name
                        AND ccu.table_name = 'document_types'
                  )
            ) THEN
                RAISE EXCEPTION 'downgrade blocked: document_types is referenced; '
                                'downgrade dependent migrations first (DD-19 §4.3)';
            END IF;
        END $$;
        """
    )
    op.execute(
        f"""
        -- 1) 恢复 operation-manual → manual（仅本迁移原位改名的行，id 固定 000...035）。
        UPDATE knowledge.document_types
           SET code = 'manual', sort_order = 50
         WHERE id = '00000000-0000-0000-0000-000000000035'
           AND code = 'operation-manual';

        -- 2) 删除本迁移新增且未被引用的 7 类：仅按固定 UUID 删除，绝不触碰其他已有行。
        DELETE FROM knowledge.document_types
         WHERE id IN ({_in_list(_NEW_IDS)})
           AND code IN ({_in_list(_NEW_CODES)});
        """
    )
