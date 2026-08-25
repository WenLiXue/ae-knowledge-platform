"""飞书 OAuth 认证 API（对齐 DD-08 API-AUTH-004/005/003/006）。

- POST /api/v1/auth/feishu/start：创建一次性 state，返回飞书授权 URL；
- GET /api/v1/auth/feishu/callback：校验 state、换 token、绑定身份、设会话 Cookie；
- GET /api/v1/auth/me：当前用户与飞书绑定状态；
- POST /api/v1/auth/logout：注销会话；
- DELETE /api/v1/auth/feishu/binding：解除飞书绑定（保留用户与已入库知识）。

安全：app_secret/access_token 只在配置与加密存储中；Cookie 仅存随机会话令牌（HttpOnly）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..audit import service as audit_service
from ..audit.context import build_context
from ..core.config import get_settings
from ..db.models.user import User
from ..db.session import get_db
from ..feishu_auth.factory import get_feishu_oauth_client
from . import deps, feishu as auth_feishu, service, sessions

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# 登录失败时操作者未知（未建立会话），用匿名系统快照；不保存任何输入内容
_ANONYMOUS_ACTOR = {
    "actor_type": "SYSTEM",
    "actor_user_id": None,
    "actor_key": "feishu-oauth",
    "actor_name": "未登录",
    "actor_account": None,
}


def _set_session_cookie(response: Response, raw_token: str) -> None:
    s = get_settings()
    response.set_cookie(
        key=s.session_cookie_name,
        value=raw_token,
        httponly=True,
        samesite="lax",
        secure=s.environment == "production",
        max_age=s.session_ttl_hours * 3600,
        path="/",
    )


@router.post("/feishu/start")
def feishu_start(
    redirect_uri: str | None = None, db: Session = Depends(get_db)
) -> dict[str, object]:
    s = get_settings()
    target = redirect_uri or s.feishu_redirect_uri
    data = service.start_oauth(db, get_feishu_oauth_client(), target)
    return {"data": data}


@router.get("/feishu/callback")
def feishu_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    s = get_settings()
    ctx = build_context(request, source_type="WEB")
    try:
        result = service.process_oauth_callback(
            db, get_feishu_oauth_client(), code, state, s.token_enc_key
        )
    except service.FeishuAuthError as exc:
        # 登录失败：独立短事务记录（不覆盖业务错误）；绝不保存输入内容（code/state）
        audit_service.record_failure_independent(
            audit_service.AuditEvent(
                action="auth.login",
                summary=f"飞书登录失败（{exc.code}）",
                actor=dict(_ANONYMOUS_ACTOR),
                context=ctx,
                error_code=exc.code,
            )
        )
        raise HTTPException(
            status_code=exc.status, detail={"code": exc.code, "message": exc.message}
        ) from exc
    user = result.user
    raw_token = sessions.create_session(db, user.id, s.session_ttl_hours)
    # 登录成功事件与业务变更（会话/身份/凭据）同一事务提交，保证原子性
    audit_service.record_success(
        db,
        audit_service.success_event(
            user=user,
            context=ctx,
            action="auth.login",
            summary=f"登录成功（{user.display_name}）",
        ),
    )
    if result.newly_bound:
        audit_service.record_success(
            db,
            audit_service.success_event(
                user=user,
                context=ctx,
                action="auth.feishu.bind",
                summary="绑定飞书账号",
                target_type="USER",
                target_id=str(user.id),
                target_name=user.display_name,
            ),
        )
    db.commit()
    resp = RedirectResponse(url=s.feishu_frontend_redirect_uri, status_code=302)
    _set_session_cookie(resp, raw_token)
    return resp


@router.get("/me")
def auth_me(
    user: User = Depends(deps.get_current_user), db: Session = Depends(get_db)
) -> dict[str, object]:
    return {
        "data": {
            "user_id": str(user.id),
            "display_name": user.display_name,
            "is_admin": user.is_admin,
            "feishu_bound": auth_feishu.has_feishu_binding(db, user.id),
        }
    }


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    raw = request.cookies.get(get_settings().session_cookie_name)
    user = sessions.get_user_by_session(db, raw)
    sessions.revoke_session(db, raw)
    if user is not None:
        audit_service.record_success(
            db,
            audit_service.success_event(
                user=user,
                context=build_context(request),
                action="auth.logout",
                summary=f"退出登录（{user.display_name}）",
            ),
        )
    db.commit()
    resp = JSONResponse({"data": {"ok": True}})
    resp.delete_cookie(key=get_settings().session_cookie_name, path="/")
    return resp


@router.delete("/feishu/binding", status_code=status.HTTP_200_OK)
def unbind_feishu(
    request: Request,
    user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    ctx = build_context(request)
    try:
        service.unbind_feishu(db, user.id)
    except service.FeishuAuthError as exc:
        # 失败事件在业务回滚后用独立短事务写入
        audit_service.record_failure_independent(
            audit_service.failure_event(
                user=user,
                context=ctx,
                action="auth.feishu.unbind",
                summary=f"解除飞书绑定失败（{exc.code}）",
                error_code=exc.code,
                target_type="USER",
                target_id=str(user.id),
                target_name=user.display_name,
            )
        )
        raise HTTPException(
            status_code=exc.status, detail={"code": exc.code, "message": exc.message}
        ) from exc
    audit_service.record_success(
        db,
        audit_service.success_event(
            user=user,
            context=ctx,
            action="auth.feishu.unbind",
            summary="解除飞书绑定",
            target_type="USER",
            target_id=str(user.id),
            target_name=user.display_name,
        ),
    )
    db.commit()
    return {"data": {"ok": True}}
