"""Bring the clinic's own customer spreadsheet in.

Two steps on purpose. The first reads the file and *proposes* what each column
is; the second applies a mapping a human confirmed, and dry-runs it before it
writes. A spreadsheet import is the only operation in this product that can put
several thousand wrong rows into a clinic's CRM in one second, and there is no
undo for it.
"""
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from backend.app.api.deps import verify_owner, verify_receptionist_or_above
from backend.app.core.database import get_db
from backend.app.models.models import User
from backend.app.services import importer
from backend.app.services.audit import log_action

router = APIRouter()

#: Large enough for a clinic's whole history, small enough that a mistaken
#: upload cannot exhaust memory on the smallest Render instance.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


async def _read(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File quá lớn (tối đa {MAX_UPLOAD_BYTES // (1024 * 1024)}MB).",
        )
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File rỗng.")
    return content


@router.post("/patients/preview")
async def preview_patient_file(
    file: UploadFile = File(...),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Read the file and propose a column mapping. Writes nothing.

    Returns five real rows alongside the proposal, because a mapping is much
    easier to check against the clinic's own data than against field names.
    """
    content = await _read(file)
    try:
        return importer.preview(content, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/patients/run")
async def import_patients(
    file: UploadFile = File(...),
    mapping: str = Form(..., description='JSON: {"full_name": 0, "phone": 1, ...}'),
    dry_run: bool = Form(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner),
) -> Any:
    """Apply a confirmed mapping.

    Owner-only, and dry_run defaults to true: the caller has to ask for the
    write explicitly. The dry run reports exactly what the real one would do,
    down to the per-row problems, so nobody has to find out afterwards.
    """
    if not current_user.clinic_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Tài khoản chưa gắn với phòng khám nào.")
    content = await _read(file)
    try:
        parsed = json.loads(mapping)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="mapping không phải JSON hợp lệ.") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="mapping phải là object {tên_trường: số_cột}.")

    clean: dict = {}
    for field, column in parsed.items():
        if field not in importer.FIELDS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Trường không hợp lệ: {field}")
        if column is None or column == "":
            continue
        try:
            clean[field] = int(column)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Số cột không hợp lệ cho {field}: {column}") from exc

    try:
        result = importer.run_import(db, current_user.clinic_id, content,
                                     file.filename or "", clean, dry_run=dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not dry_run:
        log_action(db, current_user.id, "patients_imported",
                   details=f"{file.filename}: {result['patients_created']} mới, "
                           f"{result['patients_updated']} cập nhật, "
                           f"{result['visits_created']} lượt khám")
        db.commit()
    return result


@router.get("/patients/fields")
def importable_fields(current_user: User = Depends(verify_receptionist_or_above)) -> Any:
    """What the importer understands, for building the mapping screen."""
    return [
        {"key": key, "label": spec["label"], "required": bool(spec.get("required"))}
        for key, spec in importer.FIELDS.items()
    ]
