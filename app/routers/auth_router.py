from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from auth import (
    create_access_token,
    generate_totp_qr,
    generate_totp_secret,
    get_current_user,
    hash_password,
    verify_password,
    verify_totp,
)
from database import User, get_db

router = APIRouter()


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
