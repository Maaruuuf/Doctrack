from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Alert, Document, User
from ..security import allowed_levels, get_current_user, visible_documents
from ..services import document_row, monthly_report

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    docs = visible_documents(db, user).all()
    upcoming = sorted(
        (d for d in docs if d.days_left is not None and 0 <= d.days_left <= 90),
        key=lambda d: d.days_left,
    )[:10]
    open_alerts = db.query(Alert).join(Document).filter(
        Alert.is_acknowledged.is_(False), Document.is_archived.is_(False),
        Document.confidentiality.in_(allowed_levels(user)),
    ).count()
    return {
        "total": len(docs),
        "by_status": dict(Counter(d.status for d in docs)),
        "by_category": dict(Counter(d.category for d in docs)),
        "upcoming_expiries": [document_row(d) for d in upcoming],
        "open_alerts": open_alerts,
    }


@router.get("/monthly")
def monthly(year: int | None = Query(None, ge=2000, le=2100), month: int | None = Query(None, ge=1, le=12),
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    today = date.today()
    return monthly_report(db, user, year or today.year, month or today.month)
