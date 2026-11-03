from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(100))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="staff")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50), index=True)
    confidentiality: Mapped[str] = mapped_column(String(20), default="Public")
    issuing_authority: Mapped[str | None] = mapped_column(String(200), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    renewal_lead_days: Mapped[int] = mapped_column(Integer, default=30)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    history = relationship(
        "DocumentHistory", back_populates="document",
        cascade="all, delete-orphan", order_by="DocumentHistory.id.desc()",
    )
    alerts = relationship("Alert", back_populates="document", cascade="all, delete-orphan")

    @property
    def days_left(self) -> int | None:
        if not self.expiry_date:
            return None
        return (self.expiry_date - date.today()).days

    @property
    def status(self) -> str:
        days = self.days_left
        if days is None:
            return "No Expiry"
        if days < 0:
            return "Expired"
        if days <= self.renewal_lead_days:
            return "Expiring Soon"
        return "Active"


class DocumentHistory(Base):
    """Append-only audit trail: who did what to which document, and when."""
    __tablename__ = "document_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    changed_by: Mapped[str] = mapped_column(String(50))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    document = relationship("Document", back_populates="history")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    level: Mapped[str] = mapped_column(String(20))  # WARNING | CRITICAL | EXPIRED
    message: Mapped[str] = mapped_column(String(500))
    expiry_on: Mapped[date] = mapped_column(Date)  # expiry date this alert refers to (dedupe key)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(50), nullable=True)

    document = relationship("Document", back_populates="alerts")

    @property
    def doc_code(self) -> str:
        return self.document.doc_code

    @property
    def doc_title(self) -> str:
        return self.document.title
