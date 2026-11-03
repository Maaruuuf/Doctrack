# 🗂️ DocTrack — Administrative Document & Records Management System

**Centralized Document Tracking, Filing & Compliance Management System**

A full-stack Python application that gives an organisation one trustworthy place to keep its
licences, certificates, contracts and official documents — with expiry tracking, automated
renewal alerts, a full audit trail, role-based access to confidential files, and monthly
administrative status reports.

**Stack:** Python 3.10+ · FastAPI · SQLAlchemy 2 · SQLite (swap-able) · JWT auth · APScheduler · Streamlit · pytest

---

## Features (mapped to the project brief)

| Requirement | How DocTrack delivers it |
|---|---|
| Digital records of licences, certificates, contracts & official documents | Document register with category, issuing authority, owner, issue/expiry dates, notes and an attached scan (PDF/image/Office file) |
| Track expiry dates & renewal deadlines | Live status per document: 🟢 Active · 🟠 Expiring Soon · 🔴 Expired · ⚪ No Expiry; configurable reminder lead time per document; one-click **Renew** that records the new expiry |
| Document registers & update histories | Searchable/filterable register + CSV export. Every create / update / renew / upload / download / archive is written to an append-only **audit trail** (who, when, what changed: `old → new`) |
| Automated expiry & renewal alerts | Daily scheduled scan (APScheduler) raises `WARNING` → `CRITICAL` → `EXPIRED` alerts. Alerts are de-duplicated, auto-escalate, auto-resolve on renewal, and can be e-mailed via SMTP |
| Confidential documents with role-based access | 3 roles × 3 confidentiality levels (matrix below). Unauthorised users get a `404`, so a restricted document's existence is never leaked |
| Monthly administrative status reports | Report page + API: new documents, renewals, updates, uploads, alerts raised, expired & upcoming expiries, breakdown by category/confidentiality. Download as Markdown or JSON |

### Roles & confidentiality

| Capability | staff | manager | admin |
|---|:--:|:--:|:--:|
| View **Public** documents | ✅ | ✅ | ✅ |
| View **Confidential** documents | ❌ | ✅ | ✅ |
| View **Restricted** documents | ❌ | ❌ | ✅ |
| Create / edit / renew / attach files | ❌ | ✅ (Public & Confidential) | ✅ |
| Run scan, acknowledge alerts | ❌ | ✅ | ✅ |
| Archive / restore documents, manage users | ❌ | ❌ | ✅ |

Reports, alerts, dashboard counts and CSV exports are all filtered by the same rules.

---

## Architecture

```
┌────────────────────┐   REST + JWT    ┌─────────────────────────────┐
│  Streamlit UI      │ ──────────────▶ │  FastAPI                    │
│  frontend/app.py   │                 │  routers: auth · documents  │
└────────────────────┘                 │           alerts · reports  │
                                       │  services: audit · alerts · │
                                       │            e-mail · reports │
                                       │  APScheduler (daily scan)   │
                                       └──────────────┬──────────────┘
                                                      │ SQLAlchemy
                                       ┌──────────────▼──────────────┐
                                       │ SQLite (users, documents,   │
                                       │ document_history, alerts)   │
                                       │ + ./data/uploads            │
                                       └─────────────────────────────┘
```

```
doctrack/
├── backend/
│   ├── main.py          # app, lifespan, scheduler
│   ├── config.py        # env-driven settings
│   ├── database.py      # engine / session
│   ├── models.py        # User, Document, DocumentHistory, Alert
│   ├── schemas.py       # Pydantic validation
│   ├── security.py      # PBKDF2 hashing, JWT, role + confidentiality checks
│   ├── services.py      # audit log, alert engine, e-mail digest, monthly report
│   ├── seed.py          # default admin + demo data
│   └── routers/         # auth.py · documents.py · alerts.py · reports.py
├── frontend/app.py      # Streamlit UI
├── tests/               # 16 pytest API tests
├── screenshots/         # add your screenshots here
├── requirements.txt · requirements-dev.txt · .env.example
```

---

## Quick start

Requires **Python 3.10+**.

```bash
# 1. get the code and create a virtual environment
cd doctrack
python -m venv venv

# activate it
venv\Scripts\activate             # Windows (PowerShell / cmd)

# 2. install dependencies
pip install -r requirements.txt

# 3. (optional) load demo users + 12 sample documents
python -m backend.seed

# 4. start the API  →  http://localhost:8000/docs  (interactive Swagger UI)
uvicorn backend.main:app --reload

# 5. in a SECOND terminal (venv activated), start the UI  →  http://localhost:8501
streamlit run frontend/app.py
```

**Demo accounts** (created by step 3):

| Username | Password | Role |
|---|---|---|
| `admin` | `Admin@12345` | admin |
| `manager1` | `Manager@123` | manager |
| `staff1` | `Staff@12345` | staff |

Without step 3, only the `admin` account is created on first start.
**Change the default password and `SECRET_KEY` for any real use** (see `.env.example`).

### Try this 2-minute tour
1. Sign in as `admin` → **Dashboard** shows the demo data: some documents already expired or expiring.
2. **Alerts** → see `EXPIRED` / `CRITICAL` / `WARNING` alerts raised automatically.
3. **Document Register** → open `LIC-001` → **Renew** → the alert disappears and the history records the renewal.
4. Sign out, sign in as `staff1` → the Confidential and Restricted documents are no longer visible anywhere.
5. As `manager1` → **Monthly Report** → download the Markdown report.

### Run the tests

```bash
pip install -r requirements-dev.txt
pytest -q          # 16 passed
```

---

## API overview

Interactive docs at `/docs`. All endpoints except `/auth/login` and `/health` need a Bearer token.

| Method & path | Purpose | Min role |
|---|---|---|
| `POST /auth/login` | Get JWT | — |
| `GET/POST /auth/users`, `PATCH /auth/users/{id}/active` | User management | admin |
| `GET /documents` (`search`, `category`, `status`, `confidentiality`, `include_archived`) | Register | staff |
| `GET /documents/export/csv` | Register as CSV | staff |
| `POST /documents` · `PUT /documents/{id}` | Create / edit | manager |
| `POST /documents/{id}/renew` | Record renewal | manager |
| `POST /documents/{id}/upload` · `GET /documents/{id}/download` | Attachment | manager / staff |
| `GET /documents/{id}/history` | Audit trail | staff |
| `DELETE /documents/{id}` · `POST /documents/{id}/restore` | Archive / restore | admin |
| `GET /alerts` · `POST /alerts/run` · `POST /alerts/{id}/acknowledge` | Alerts | staff / manager |
| `GET /reports/summary` · `GET /reports/monthly?year=&month=` | Dashboard & monthly report | staff |

## Design decisions

- **Audit trail is append-only and deletion is a soft archive**, so history survives — what a compliance reviewer expects.
- **Alerts are idempotent.** Keyed on *(document, level, expiry date)*, so re-running the scan never spams duplicates; renewing a document resolves its alerts, and a new expiry date can alert again.
- **Authorization is enforced in the API, not the UI.** The UI hides what you cannot use, but the server is the gatekeeper.
- **Uploads** are extension-whitelisted, size-limited, and stored under random names (user-supplied names are never used on disk).
- **Passwords** use salted PBKDF2-SHA256 (200k iterations, stdlib only); tokens are signed JWTs with expiry.
