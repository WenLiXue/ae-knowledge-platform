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

from ..core.config import get_settings
from ..db.models.user import User
from ..db.session import get_db
from ..feishu_auth.factory import get_feishu_oauth_client
from . import deps, feishu as auth_feishu, service, sessions

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


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
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    s = get_settings()
    try:
        user = service.process_oauth_callback(
            db, get_feishu_oauth_client(), code, state, s.token_enc_key
        )
    except service.FeishuAuthError as exc:
        raise HTTPException(
            status_code=exc.status, detail={"code": exc.code, "message": exc.message}
        ) from exc
    raw_token = sessions.create_session(db, user.id, s.session_ttl_hours)
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
    sessions.revoke_session(db, raw)
    db.commit()
    resp = JSONResponse({"data": {"ok": True}})
    resp.delete_cookie(key=get_settings().session_cookie_name, path="/")
    return resp


@router.delete("/feishu/binding", status_code=status.HTTP_200_OK)
def unbind_feishu(
    user: User = Depends(deps.get_current_user), db: Session = Depends(get_db)
) -> dict[str, object]:
    try:
        service.unbind_feishu(db, user.id)
    except service.FeishuAuthError as exc:
        raise HTTPException(
            status_code=exc.status, detail={"code": exc.code, "message": exc.message}
        ) from exc
    db.commit()
    return {"data": {"ok": True}}
