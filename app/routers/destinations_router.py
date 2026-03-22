import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth import get_current_user
from database import Destination, get_db
from encryption import decrypt, encrypt
from storage import (
    configure_b2,
    configure_local,
    configure_sftp,
    configure_smb,
    remove_remote,
    test_remote,
)

router = APIRouter()

SENSITIVE_FIELDS = {"password", "application_key", "key", "pass"}


def redact_config(config: dict) -> dict:
    return {
        k: ("***" if k in SENSITIVE_FIELDS else v)
        for k, v in config.items()
    }


class CreateDestinationRequest(BaseModel):
    name: str
    type: str  # b2 / smb / sftp / local
    config: dict[str, Any]


def _configure_rclone(dest_type: str, remote_name: str, config: dict) -> None:
    if dest_type == "b2":
        configure_b2(
            remote_name=remote_name,
            account=config.get("account_id", ""),
            key=config.get("application_key", ""),
        )
    elif dest_type == "smb":
        configure_smb(
            remote_name=remote_name,
            host=config.get("host", ""),
            share=config.get("share", ""),
            user=config.get("user", ""),
            password=config.get("password", ""),
            domain=config.get("domain", ""),
        )
    elif dest_type == "sftp":
        configure_sftp(
            remote_name=remote_name,
            host=config.get("host", ""),
            port=int(config.get("port", 22)),
            user=config.get("user", ""),
            password=config.get("password"),
            key_file=config.get("key_file"),
        )
    elif dest_type == "local":
        configure_local(
            remote_name=remote_name,
            path=config.get("path", ""),
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown destination type: {dest_type!r}",
        )


@router.get("")
def list_destinations(current_user=Depends(get_current_user), db=Depends(get_db)):
    destinations = db.query(Destination).all()
    result = []
    for d in destinations:
        try:
            config = json.loads(decrypt(d.config_encrypted))
        except Exception:
            config = {}
        result.append(
            {
                "id": d.id,
                "name": d.name,
                "type": d.type,
                "config": redact_config(config),
                "created_at": d.created_at.isoformat(),
            }
        )
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
def create_destination(
    req: CreateDestinationRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    dest = Destination(
        name=req.name,
        type=req.type,
        config_encrypted=encrypt(json.dumps(req.config)),
    )
    db.add(dest)
    db.commit()
    db.refresh(dest)

    remote_name = f"dest_{dest.id}"
    try:
        _configure_rclone(req.type, remote_name, req.config)
    except Exception as exc:
        db.delete(dest)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to configure rclone remote: {exc}",
        )

    return {
        "id": dest.id,
        "name": dest.name,
        "type": dest.type,
        "created_at": dest.created_at.isoformat(),
    }


@router.put("/{dest_id}")
def update_destination(
    dest_id: int,
    req: CreateDestinationRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    dest = db.query(Destination).filter(Destination.id == dest_id).first()
    if not dest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Destination not found")

    # Merge: if a sensitive field is blank or still "***", keep the existing stored value
    try:
        existing_config = json.loads(decrypt(dest.config_encrypted))
    except Exception:
        existing_config = {}

    merged = dict(req.config)
    for field in SENSITIVE_FIELDS:
        if field in merged and merged[field] in ("", "***"):
            merged[field] = existing_config.get(field, "")

    dest.name = req.name
    dest.type = req.type
    dest.config_encrypted = encrypt(json.dumps(merged))
    db.commit()

    remote_name = f"dest_{dest_id}"
    try:
        _configure_rclone(req.type, remote_name, merged)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reconfigure rclone remote: {exc}",
        )

    return {"id": dest.id, "name": dest.name, "type": dest.type, "created_at": dest.created_at.isoformat()}


@router.post("/{dest_id}/test")
def test_destination_connection(
    dest_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    dest = db.query(Destination).filter(Destination.id == dest_id).first()
    if not dest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Destination not found")

    ok, message = test_remote(f"dest_{dest_id}")
    return {"ok": ok, "message": message}


@router.delete("/{dest_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_destination(
    dest_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    dest = db.query(Destination).filter(Destination.id == dest_id).first()
    if not dest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Destination not found")

    remove_remote(f"dest_{dest_id}")
    db.delete(dest)
    db.commit()
