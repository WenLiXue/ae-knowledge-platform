"""Skill import and enablement administration routes."""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...auth.deps import get_current_admin
from ...db.models.capability import AgentSkill
from ...db.models.user import User
from ...db.session import get_db
from ..capability.serializers import skill_dict
from ..capability.skill_parser import parse_skill_document
from .schemas import EnabledPatch, SkillCreate

router = APIRouter(tags=["admin-agent-capabilities"])


@router.post("/skills", status_code=201)
def create_skill(data: SkillCreate, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    try:
        front_name, front_description = parse_skill_document(data.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "SKILL_INVALID", "message": str(exc)}) from exc
    if front_name != data.name or front_description != data.description:
        raise HTTPException(status_code=422, detail={"code": "SKILL_METADATA_MISMATCH", "message": "请求字段必须与 SKILL.md frontmatter 一致"})
    if db.execute(select(AgentSkill).where(AgentSkill.name == data.name)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail={"code": "SKILL_EXISTS", "message": "技能名称已存在"})
    row = AgentSkill(name=data.name, description=data.description, content=data.content, version=data.version, enabled=data.enabled, created_by=admin.id)
    db.add(row); db.commit(); db.refresh(row)
    return {"data": skill_dict(row)}


@router.post("/skills/import", status_code=201)
async def import_skill(file: UploadFile = File(...), db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    if not file.filename or not file.filename.lower().endswith(".md"):
        raise HTTPException(status_code=422, detail={"code": "SKILL_FILE_INVALID", "message": "只能导入 .md 技能文件"})
    raw = await file.read()
    try:
        content = raw.decode("utf-8"); name, description = parse_skill_document(content)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "SKILL_INVALID", "message": str(exc)}) from exc
    if db.execute(select(AgentSkill).where(AgentSkill.name == name)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail={"code": "SKILL_EXISTS", "message": "技能名称已存在"})
    row = AgentSkill(name=name, description=description, content=content, created_by=admin.id)
    db.add(row); db.commit(); db.refresh(row)
    return {"data": skill_dict(row)}


@router.patch("/skills/{skill_id}")
def set_skill_enabled(skill_id: uuid.UUID, data: EnabledPatch, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    row = db.get(AgentSkill, skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "SKILL_NOT_FOUND", "message": "技能不存在"})
    row.enabled = data.enabled; db.commit()
    return {"data": skill_dict(row)}
