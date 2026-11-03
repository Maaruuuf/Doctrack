"""Seed helpers. Run `python -m backend.seed` to load demo users + documents."""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .config import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME
from .database import Base, SessionLocal, engine
from .models import Document, User
from .security import hash_password
from .services import generate_alerts, log_history


def create_default_admin(db: Session) -> None:
    if db.query(User).count() == 0:
        db.add(User(
            username=DEFAULT_ADMIN_USERNAME, full_name="System Administrator",
            hashed_password=hash_password(DEFAULT_ADMIN_PASSWORD), role="admin",
        ))
        db.commit()


DEMO_USERS = [
    ("manager1", "Admin Manager", "Manager@123", "manager"),
    ("staff1", "Office Staff", "Staff@12345", "staff"),
]

# code, title, category, confidentiality, authority, owner, issued N days ago, expires in N days
DEMO_DOCS = [
    ("LIC-001", "Trade Licence", "Licence", "Public", "City Corporation", "Administration", 340, 25),
    ("LIC-002", "Fire Safety Licence", "Licence", "Public", "Fire Service", "Facilities", 700, -12),
    ("LIC-003", "Environmental Clearance", "Licence", "Confidential", "Dept. of Environment", "Compliance", 200, 160),
    ("CERT-001", "ISO 9001 Certificate", "Certificate", "Public", "ISO Certification Body", "Quality", 900, 5),
    ("CERT-002", "Tax Compliance Certificate", "Certificate", "Confidential", "Tax Authority", "Finance", 120, 245),
    ("CON-001", "Office Lease Agreement", "Contract", "Confidential", "Landlord Ltd.", "Administration", 500, 230),
    ("CON-002", "IT Support Contract", "Contract", "Public", "TechServe Ltd.", "IT", 300, 20),
    ("CON-003", "Executive Employment Contract", "Contract", "Restricted", "HR", "HR", 800, 400),
    ("DOC-001", "Company Registration Certificate", "Official Document", "Public", "Registrar of Companies", "Legal", 2000, None),
    ("DOC-002", "Board Resolution 2025", "Official Document", "Restricted", "Board of Directors", "Company Secretary", 150, None),
    ("POL-001", "Data Protection Policy", "Policy", "Public", "Internal", "Compliance", 365, 90),
    ("POL-002", "Health & Safety Policy", "Policy", "Public", "Internal", "HR", 365, 3),
]


def seed_demo(db: Session) -> None:
    create_default_admin(db)
    for username, name, password, role in DEMO_USERS:
        if not db.query(User).filter(User.username == username).first():
            db.add(User(username=username, full_name=name, hashed_password=hash_password(password), role=role))
    db.commit()

    today = date.today()
    for code, title, cat, conf, authority, owner, issued_ago, expires_in in DEMO_DOCS:
        if db.query(Document).filter(Document.doc_code == code).first():
            continue
        doc = Document(
            doc_code=code, title=title, category=cat, confidentiality=conf,
            issuing_authority=authority, owner=owner,
            issue_date=today - timedelta(days=issued_ago),
            expiry_date=today + timedelta(days=expires_in) if expires_in is not None else None,
            renewal_lead_days=30, created_by="admin",
        )
        db.add(doc)
        db.flush()
        log_history(db, doc, "CREATED", "admin", f"Registered '{title}' ({cat}) — demo data")
    db.commit()
    generate_alerts(db)


if __name__ == "__main__":
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed_demo(session)
    print("Demo data loaded.")
    print(f"  admin    / {DEFAULT_ADMIN_PASSWORD}")
    for username, _, password, role in DEMO_USERS:
        print(f"  {username:<8} / {password}   ({role})")
