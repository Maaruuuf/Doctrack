import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI

from .config import ALERT_HOUR, DISABLE_SCHEDULER, UPLOAD_DIR
from .database import Base, SessionLocal, engine
from .routers import alerts, auth, documents, reports
from .seed import create_default_admin
from .services import generate_alerts, scheduled_scan

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with SessionLocal() as db:
        create_default_admin(db)
        generate_alerts(db)
    scheduler = None
    if not DISABLE_SCHEDULER:
        scheduler = BackgroundScheduler()
        scheduler.add_job(scheduled_scan, "cron", hour=ALERT_HOUR, minute=0, id="daily_expiry_scan")
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="DocTrack — Document & Records Management API",
    description="Centralized document tracking, filing and compliance management.",
    version="1.0.0",
    lifespan=lifespan,
)

for router in (auth.router, documents.router, alerts.router, reports.router):
    app.include_router(router)


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok"}
