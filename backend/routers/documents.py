import csv
import io
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import ALLOWED_EXTENSIONS, MAX_UPLOAD_MB, UPLOAD_DIR
from ..database import get_db
from ..models import Alert, Document, User, utcnow
from ..schemas import (DocumentCreate, DocumentOut, DocumentUpdate, HistoryOut, RenewRequest)
from ..security import (CONF_RANK, ROLE_RANK, can_view, get_current_user,
                        require_role, visible_documents)
from ..services import format_changes, generate_alerts, log_history

router = APIRouter(prefix="/documents", tags=["Documents"])

REQUIRED_FIELDS = {"doc_code", "title", "category", "confidentiality", "renewal_lead_days"}


def get_doc_or_404(db: Session, user: User, doc_id: int) -> Document:
    doc = db.get(Document, doc_id)
    if not doc or not can_view(user, doc):  # same error for "missing" and "forbidden": don't leak existence
        raise HTTPException(404, "Document not found")
    return doc


def ensure_can_assign(user: User, level: str) -> None:
    if CONF_RANK[level] > ROLE_RANK[user.role]:
        raise HTTPException(403, f"Your role cannot create or assign '{level}' documents")


def ensure_unique_code(db: Session, code: str, exclude_id: int | None = None) -> None:
    query = db.query(Document).filter(Document.doc_code == code)
    if exclude_id:
        query = query.filter(Document.id != exclude_id)
    if query.first():
        raise HTTPException(409, f"Document code '{code}' already exists")


@router.get("", response_model=list[DocumentOut])
def list_documents(
    search: str | None = None, category: str | None = None, status: str | None = None,
    confidentiality: str | None = None, include_archived: bool = False,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    query = visible_documents(db, user, include_archived)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            Document.title.ilike(like), Document.doc_code.ilike(like),
            Document.owner.ilike(like), Document.issuing_authority.ilike(like),
        ))
    if category:
        query = query.filter(Document.category == category)
    if confidentiality:
        query = query.filter(Document.confidentiality == confidentiality)
    docs = query.order_by(Document.expiry_date.is_(None), Document.expiry_date).all()
    if status:  # status is computed from dates, so it is filtered in Python
        docs = [d for d in docs if d.status == status]
    return docs


@router.get("/export/csv")
def export_csv(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Document register as CSV (only documents the caller is allowed to see)."""
    columns = ["doc_code", "title", "category", "confidentiality", "issuing_authority", "owner",
               "issue_date", "expiry_date", "days_left", "status", "renewal_lead_days", "notes"]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for doc in visible_documents(db, user).order_by(Document.doc_code).all():
        writer.writerow([getattr(doc, col) if getattr(doc, col) is not None else "" for col in columns])
    return Response(
        buffer.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=document_register.csv"},
    )


@router.post("", response_model=DocumentOut, status_code=201)
def create_document(payload: DocumentCreate, db: Session = Depends(get_db),
                    user: User = Depends(require_role("manager"))):
    ensure_can_assign(user, payload.confidentiality)
    ensure_unique_code(db, payload.doc_code)
    doc = Document(**payload.model_dump(), created_by=user.username)
    db.add(doc)
    db.flush()
    log_history(db, doc, "CREATED", user.username, f"Registered '{doc.title}' ({doc.category})")
    db.commit()
    generate_alerts(db)
    db.refresh(doc)
    return doc


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_doc_or_404(db, user, doc_id)


@router.put("/{doc_id}", response_model=DocumentOut)
def update_document(doc_id: int, payload: DocumentUpdate, db: Session = Depends(get_db),
                    user: User = Depends(require_role("manager"))):
    doc = get_doc_or_404(db, user, doc_id)
    data = {k: v for k, v in payload.model_dump(exclude_unset=True).items()
            if not (v is None and k in REQUIRED_FIELDS)}
    if "confidentiality" in data:
        ensure_can_assign(user, data["confidentiality"])
    if "doc_code" in data:
        ensure_unique_code(db, data["doc_code"], exclude_id=doc.id)

    issue = data.get("issue_date", doc.issue_date)
    expiry = data.get("expiry_date", doc.expiry_date)
    if issue and expiry and expiry < issue:
        raise HTTPException(422, "expiry_date cannot be before issue_date")

    changes = {}
    for field, new in data.items():
        old = getattr(doc, field)
        if old != new:
            changes[field] = (old, new)
            setattr(doc, field, new)
    if changes:
        doc.updated_at = utcnow()
        log_history(db, doc, "UPDATED", user.username, format_changes(changes))
        db.commit()
        generate_alerts(db)
        db.refresh(doc)
    return doc


@router.post("/{doc_id}/renew", response_model=DocumentOut)
def renew_document(doc_id: int, payload: RenewRequest, db: Session = Depends(get_db),
                   user: User = Depends(require_role("manager"))):
    doc = get_doc_or_404(db, user, doc_id)
    from datetime import date
    if payload.new_expiry_date <= date.today():
        raise HTTPException(422, "New expiry date must be in the future")
    old = doc.expiry_date
    doc.expiry_date = payload.new_expiry_date
    doc.updated_at = utcnow()
    db.query(Alert).filter(Alert.document_id == doc.id, Alert.is_acknowledged.is_(False)).update(
        {"is_acknowledged": True, "acknowledged_by": user.username}
    )
    details = f"Expiry {old or 'none'} → {payload.new_expiry_date}"
    if payload.note:
        details += f". Note: {payload.note}"
    log_history(db, doc, "RENEWED", user.username, details)
    db.commit()
    generate_alerts(db)
    db.refresh(doc)
    return doc


@router.delete("/{doc_id}", status_code=204)
def archive_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    """Soft delete: records are never destroyed, which keeps the audit trail intact."""
    doc = get_doc_or_404(db, user, doc_id)
    doc.is_archived = True
    doc.updated_at = utcnow()
    log_history(db, doc, "ARCHIVED", user.username, "Document archived")
    db.commit()
    return Response(status_code=204)


@router.post("/{doc_id}/restore", response_model=DocumentOut)
def restore_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    doc = get_doc_or_404(db, user, doc_id)
    doc.is_archived = False
    doc.updated_at = utcnow()
    log_history(db, doc, "RESTORED", user.username, "Document restored from archive")
    db.commit()
    generate_alerts(db)
    db.refresh(doc)
    return doc


@router.get("/{doc_id}/history", response_model=list[HistoryOut])
def document_history(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_doc_or_404(db, user, doc_id).history


@router.post("/{doc_id}/upload", response_model=DocumentOut)
async def upload_file(doc_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                      user: User = Depends(require_role("manager"))):
    doc = get_doc_or_404(db, user, doc_id)
    original = Path(file.filename or "").name
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File larger than {MAX_UPLOAD_MB} MB")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    stored = f"{uuid4().hex}{ext}"  # random name: never trust user-supplied file names on disk
    (Path(UPLOAD_DIR) / stored).write_bytes(content)
    if doc.file_path:
        (Path(UPLOAD_DIR) / doc.file_path).unlink(missing_ok=True)
    doc.file_name, doc.file_path, doc.updated_at = original, stored, utcnow()
    log_history(db, doc, "FILE_UPLOADED", user.username, f"{original} ({len(content) // 1024} KB)")
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{doc_id}/download")
def download_file(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = get_doc_or_404(db, user, doc_id)
    if not doc.file_path or not (Path(UPLOAD_DIR) / doc.file_path).exists():
        raise HTTPException(404, "No file attached to this document")
    log_history(db, doc, "FILE_DOWNLOADED", user.username, doc.file_name or "")
    db.commit()
    return FileResponse(Path(UPLOAD_DIR) / doc.file_path, filename=doc.file_name)
