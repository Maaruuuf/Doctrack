"""Business logic: audit logging, alert generation, e-mail digest, monthly report."""
import logging
import smtplib
from collections import Counter
from datetime import date, datetime
from email.message import EmailMessage

from sqlalchemy.orm import Session

from . import config
from .models import Alert, Document, DocumentHistory, User
from .security import visible_documents

logger = logging.getLogger("doctrack")

LEVEL_ORDER = {"EXPIRED": 0, "CRITICAL": 1, "WARNING": 2}


# ---------- Audit trail ----------
def log_history(db: Session, doc: Document, action: str, username: str, details: str = "") -> None:
    db.add(DocumentHistory(document_id=doc.id, action=action, changed_by=username, details=details))


def format_changes(changes: dict) -> str:
    def short(value):
        text = str(value)
        return text if len(text) <= 60 else text[:57] + "..."
    return "; ".join(f"{field}: {short(old)} → {short(new)}" for field, (old, new) in changes.items())


# ---------- Alerts ----------
def classify(doc: Document, today: date):
    days = (doc.expiry_date - today).days
    if days < 0:
        return "EXPIRED", f"{doc.doc_code} '{doc.title}' expired {abs(days)} day(s) ago on {doc.expiry_date}."
    if days <= min(config.CRITICAL_DAYS, doc.renewal_lead_days):
        return "CRITICAL", f"{doc.doc_code} '{doc.title}' expires in {days} day(s) on {doc.expiry_date}."
    if days <= doc.renewal_lead_days:
        return "WARNING", f"{doc.doc_code} '{doc.title}' is due for renewal: {days} day(s) left ({doc.expiry_date})."
    return None, None


def generate_alerts(db: Session) -> list[Alert]:
    """Scan all active documents and create alerts that don't exist yet. Idempotent."""
    today = date.today()
    created: list[Alert] = []
    docs = db.query(Document).filter(
        Document.is_archived.is_(False), Document.expiry_date.isnot(None)
    ).all()
    for doc in docs:
        level, message = classify(doc, today)
        if not level:
            continue
        exists = db.query(Alert).filter(
            Alert.document_id == doc.id, Alert.level == level, Alert.expiry_on == doc.expiry_date
        ).first()
        if exists:
            continue
        # escalation: older, lower-severity alerts for the same expiry are superseded
        db.query(Alert).filter(
            Alert.document_id == doc.id, Alert.expiry_on == doc.expiry_date,
            Alert.is_acknowledged.is_(False),
        ).update({"is_acknowledged": True, "acknowledged_by": "system"})
        alert = Alert(document_id=doc.id, level=level, message=message, expiry_on=doc.expiry_date)
        db.add(alert)
        created.append(alert)
    db.commit()
    return created


def send_email_digest(lines: list[str]) -> bool:
    if not (config.SMTP_HOST and config.ALERT_EMAIL_TO and lines):
        return False
    msg = EmailMessage()
    msg["Subject"] = f"[DocTrack] {len(lines)} new document alert(s)"
    msg["From"] = config.ALERT_EMAIL_FROM
    msg["To"] = config.ALERT_EMAIL_TO
    msg.set_content("New expiry / renewal alerts:\n\n" + "\n".join(f"- {line}" for line in lines))
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception:
        logger.exception("Could not send alert e-mail")
        return False


def run_scan(db: Session) -> int:
    new_alerts = generate_alerts(db)
    send_email_digest([f"[{a.level}] {a.message}" for a in new_alerts])
    return len(new_alerts)


def scheduled_scan() -> None:
    from .database import SessionLocal
    with SessionLocal() as db:
        count = run_scan(db)
        logger.info("Scheduled expiry scan finished: %s new alert(s)", count)


# ---------- Reports ----------
def document_row(doc: Document) -> dict:
    return {
        "doc_code": doc.doc_code, "title": doc.title, "category": doc.category,
        "confidentiality": doc.confidentiality, "owner": doc.owner,
        "expiry_date": str(doc.expiry_date) if doc.expiry_date else None,
        "days_left": doc.days_left, "status": doc.status,
    }


def monthly_report(db: Session, user: User, year: int, month: int) -> dict:
    start = datetime(year, month, 1)
    end = datetime(year + (month == 12), (month % 12) + 1, 1)

    docs = visible_documents(db, user).all()
    ids = [d.id for d in docs]

    history = db.query(DocumentHistory).filter(
        DocumentHistory.document_id.in_(ids),
        DocumentHistory.changed_at >= start, DocumentHistory.changed_at < end,
    ).all()
    activity = Counter(h.action for h in history)

    alerts_raised = db.query(Alert).filter(
        Alert.document_id.in_(ids), Alert.created_at >= start, Alert.created_at < end
    ).count()

    expired = sorted((d for d in docs if d.status == "Expired"), key=lambda d: d.days_left)
    expiring = sorted(
        (d for d in docs if d.days_left is not None and 0 <= d.days_left <= 30),
        key=lambda d: d.days_left,
    )

    return {
        "period": f"{year}-{month:02d}",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "generated_by": user.full_name,
        "totals": {
            "documents_on_register": len(docs),
            "new_documents": sum(1 for d in docs if start <= d.created_at < end),
            "updates": activity.get("UPDATED", 0),
            "renewals": activity.get("RENEWED", 0),
            "files_uploaded": activity.get("FILE_UPLOADED", 0),
            "alerts_raised": alerts_raised,
            "expired_now": len(expired),
            "expiring_next_30_days": len(expiring),
        },
        "by_category": dict(Counter(d.category for d in docs)),
        "by_confidentiality": dict(Counter(d.confidentiality for d in docs)),
        "by_status": dict(Counter(d.status for d in docs)),
        "activity": dict(activity),
        "expired_documents": [document_row(d) for d in expired],
        "expiring_soon": [document_row(d) for d in expiring],
    }
