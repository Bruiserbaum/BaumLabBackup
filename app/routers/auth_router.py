import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import jwt as jose_jwt, JWTError
from pydantic import BaseModel

from auth import (
    create_access_token,
    generate_totp_qr,
    generate_totp_secret,
    get_current_user,
    hash_password,
    verify_password,
    verify_totp,
)
from config import (
    SECRET_KEY, ALGORITHM,
    AUTHENTIK_HEADER_AUTH,
    OIDC_ENABLED, OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_REDIRECT_URI,
)
from database import User, get_db

router = APIRouter()

# ── OIDC discovery cache ──────────────────────────────────────────────────────
_oidc_discovery: dict = {}


def _get_oidc_discovery() -> dict:
    global _oidc_discovery
    if _oidc_discovery:
        return _oidc_discovery
    url = OIDC_ISSUER + ".well-known/openid-configuration"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    _oidc_discovery = resp.json()
    return _oidc_discovery


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TOTPVerifyRequest(BaseModel):
    code: str


@router.post("/login")
def login(req: LoginRequest, db=Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if user.totp_enabled:
        if not req.totp_code:
            return {"totp_required": True, "access_token": ""}
        if not verify_totp(user.totp_secret, req.totp_code):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code")

    token = create_access_token({"sub": user.username})
    return {"totp_required": False, "access_token": token}


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "totp_enabled": current_user.totp_enabled,
        "is_admin": current_user.is_admin,
    }


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    user = db.query(User).filter(User.id == current_user.id).first()
    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    user.password_hash = hash_password(req.new_password)
    db.commit()
    return {"message": "Password changed successfully"}


@router.post("/totp/setup")
def totp_setup(current_user: User = Depends(get_current_user), db=Depends(get_db)):
    user = db.query(User).filter(User.id == current_user.id).first()
    secret = generate_totp_secret()
    user.totp_secret = secret
    db.commit()
    qr_code = generate_totp_qr(user.username, secret)
    return {"secret": secret, "qr_code": qr_code}


@router.post("/totp/confirm")
def totp_confirm(
    req: TOTPVerifyRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user.totp_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP setup not started")
    if not verify_totp(user.totp_secret, req.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")
    user.totp_enabled = True
    db.commit()
    return {"message": "TOTP enabled successfully"}


@router.post("/totp/disable")
def totp_disable(
    req: TOTPVerifyRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP is not enabled")
    if not verify_totp(user.totp_secret, req.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")
    user.totp_enabled = False
    user.totp_secret = None
    db.commit()
    return {"message": "TOTP disabled successfully"}


# ── OIDC / Authentik SSO ──────────────────────────────────────────────────────

@router.get("/config")
def auth_config():
    """Public endpoint — returns which auth methods are available."""
    return {"oidc_enabled": OIDC_ENABLED, "header_auth_enabled": AUTHENTIK_HEADER_AUTH}


@router.get("/header-login")
def header_login(request: Request, db=Depends(get_db)):
    """Called by the frontend on page load when Authentik forward auth is active.
    Reads X-authentik-username injected by NPM and issues a local JWT, creating a
    user account on first visit. Requires AUTHENTIK_HEADER_AUTH=true."""
    if not AUTHENTIK_HEADER_AUTH:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Header auth is not enabled")
    username = request.headers.get("X-authentik-username", "").strip()
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No Authentik header present")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        user = User(username=username, password_hash="", is_admin=False)
        db.add(user)
        db.commit()
        db.refresh(user)
    token = create_access_token({"sub": user.username})
    return {"access_token": token}


@router.get("/oidc/login")
def oidc_login():
    """Redirect the browser to Authentik's authorization endpoint."""
    if not OIDC_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OIDC is not enabled")
    expire = datetime.utcnow() + timedelta(minutes=10)
    state = jose_jwt.encode(
        {"nonce": secrets.token_urlsafe(16), "exp": expire},
        SECRET_KEY, algorithm=ALGORITHM,
    )
    discovery = _get_oidc_discovery()
    params = urlencode({
        "response_type": "code",
        "client_id": OIDC_CLIENT_ID,
        "redirect_uri": OIDC_REDIRECT_URI,
        "scope": "openid profile email",
        "state": state,
    })
    return RedirectResponse(f"{discovery['authorization_endpoint']}?{params}", status_code=302)


@router.get("/oidc/callback")
def oidc_callback(
    code: str = None,
    state: str = None,
    error: str = None,
    db=Depends(get_db),
):
    """Authentik redirects here after login. Exchange code, find/create user, issue JWT."""
    if error:
        return RedirectResponse(f"/?oidc_error={error}")
    if not code or not state:
        return RedirectResponse("/?oidc_error=missing_params")

    # Verify CSRF state
    try:
        jose_jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return RedirectResponse("/?oidc_error=invalid_state")

    # Exchange code for tokens + fetch userinfo
    try:
        discovery = _get_oidc_discovery()
        with httpx.Client(timeout=10) as client:
            token_resp = client.post(
                discovery["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": OIDC_REDIRECT_URI,
                    "client_id": OIDC_CLIENT_ID,
                    "client_secret": OIDC_CLIENT_SECRET,
                },
            )
            token_resp.raise_for_status()
            access_token = token_resp.json()["access_token"]

            userinfo_resp = client.get(
                discovery["userinfo_endpoint"],
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_resp.raise_for_status()
            userinfo = userinfo_resp.json()
    except Exception:
        return RedirectResponse("/?oidc_error=token_exchange_failed")

    sub = userinfo.get("sub")
    if not sub:
        return RedirectResponse("/?oidc_error=no_sub")

    # Find or create local user
    user = db.query(User).filter(User.oidc_sub == sub).first()
    if not user:
        preferred = userinfo.get("preferred_username") or userinfo.get("email") or sub
        username = preferred
        counter = 1
        while db.query(User).filter(User.username == username).first():
            username = f"{preferred}_{counter}"
            counter += 1
        user = User(username=username, password_hash="", oidc_sub=sub, is_admin=False)
        db.add(user)
        db.commit()
        db.refresh(user)

    local_token = create_access_token({"sub": user.username})
    return RedirectResponse(f"/?token={local_token}", status_code=302)
