from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Alert, Document, User
from ..schemas import AlertOut
from ..security import allowed_levels, get_current_user, require_role
from ..services import LEVEL_ORDER, run_scan

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(unacknowledged_only: bool = True, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    query = db.query(Alert).join(Document).filter(
        Document.is_archived.is_(False), Document.confidentiality.in_(allowed_levels(user))
    )
    if unacknowledged_only:
        query = query.filter(Alert.is_acknowledged.is_(False))
    alerts = query.order_by(Alert.created_at.desc()).all()
    return sorted(alerts, key=lambda a: LEVEL_ORDER.get(a.level, 9))


@router.post("/run")
def run_expiry_scan(db: Session = Depends(get_db), _: User = Depends(require_role("manager"))):
    """Trigger the expiry scan on demand (it also runs automatically every day)."""
    return {"new_alerts": run_scan(db)}


@router.post("/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge(alert_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("manager"))):
    alert = db.get(Alert, alert_id)
    if not alert or alert.document.confidentiality not in allowed_levels(user):
        raise HTTPException(404, "Alert not found")
    alert.is_acknowledged, alert.acknowledged_by = True, user.username
    db.commit()
    db.refresh(alert)
    return alert
