"""DocTrack — Streamlit front-end for the Document & Records Management API."""
import os
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")
CATEGORIES = ["Licence", "Certificate", "Contract", "Official Document", "Policy", "Other"]
CONFIDENTIALITY = ["Public", "Confidential", "Restricted"]
STATUSES = ["Active", "Expiring Soon", "Expired", "No Expiry"]
ROLE_RANK = {"staff": 1, "manager": 2, "admin": 3}
CONF_RANK = {"Public": 1, "Confidential": 2, "Restricted": 3}
STATUS_ICON = {"Active": "🟢", "Expiring Soon": "🟠", "Expired": "🔴", "No Expiry": "⚪"}
LEVEL_ICON = {"EXPIRED": "🔴", "CRITICAL": "🟠", "WARNING": "🟡"}

st.set_page_config(page_title="DocTrack", page_icon="🗂️", layout="wide")


# ---------------------------------------------------------------- API helpers
def call(method: str, path: str, **kwargs) -> requests.Response:
    headers = {}
    if st.session_state.get("token"):
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    try:
        resp = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=20, **kwargs)
    except requests.RequestException:
        st.error(f"Cannot reach the API at {API_URL}. Is the backend running?")
        st.stop()
    if resp.status_code == 401 and st.session_state.get("token"):
        st.session_state.clear()
        st.rerun()
    return resp


def show_error(resp: requests.Response) -> None:
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        detail = resp.text
    if isinstance(detail, list):
        detail = "; ".join(f"{'.'.join(map(str, e.get('loc', [])[1:]))}: {e.get('msg')}" for e in detail)
    st.error(detail)


def get_json(path: str, **params):
    resp = call("GET", path, params={k: v for k, v in params.items() if v not in (None, "", False)})
    if resp.ok:
        return resp.json()
    show_error(resp)
    return None


def role() -> str:
    return st.session_state.user["role"]


def is_manager() -> bool:
    return ROLE_RANK[role()] >= ROLE_RANK["manager"]


def with_icons(df: pd.DataFrame) -> pd.DataFrame:
    if "status" in df:
        df["status"] = df["status"].map(lambda s: f"{STATUS_ICON.get(s, '')} {s}")
    return df


# ---------------------------------------------------------------- Login
def login_view() -> None:
    _, middle, _ = st.columns([1, 1.2, 1])
    with middle:
        st.title("🗂️ DocTrack")
        st.caption("Centralized Document Tracking, Filing & Compliance Management")
        with st.form("login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in", width="stretch"):
                resp = call("POST", "/auth/login", data={"username": username, "password": password})
                if resp.ok:
                    data = resp.json()
                    st.session_state.token = data["access_token"]
                    st.session_state.user = {k: data[k] for k in ("username", "full_name", "role")}
                    st.rerun()
                show_error(resp)


# ---------------------------------------------------------------- Shared form
def document_form(key: str, doc: dict | None = None, submit_label: str = "Save"):
    d = doc or {}
    allowed = [c for c in CONFIDENTIALITY if CONF_RANK[c] <= ROLE_RANK[role()]]
    with st.form(key):
        c1, c2 = st.columns(2)
        code = c1.text_input("Document code *", d.get("doc_code", ""))
        title = c2.text_input("Title *", d.get("title", ""))
        category = c1.selectbox("Category", CATEGORIES,
                                index=CATEGORIES.index(d["category"]) if d.get("category") in CATEGORIES else 0)
        conf = c2.selectbox("Confidentiality", allowed,
                            index=allowed.index(d["confidentiality"]) if d.get("confidentiality") in allowed else 0)
        authority = c1.text_input("Issuing authority", d.get("issuing_authority") or "")
        owner = c2.text_input("Owner / department", d.get("owner") or "")
        issue = c1.date_input("Issue date", date.fromisoformat(d["issue_date"]) if d.get("issue_date") else date.today())
        has_expiry = c2.checkbox("This document expires", value=bool(d.get("expiry_date")) or not d)
        expiry = c2.date_input("Expiry date", date.fromisoformat(d["expiry_date"]) if d.get("expiry_date")
                               else date.today() + timedelta(days=365))
        lead = c1.number_input("Renewal reminder (days before expiry)", 0, 365, int(d.get("renewal_lead_days", 30)))
        notes = st.text_area("Notes", d.get("notes") or "")
        submitted = st.form_submit_button(submit_label)
    if not submitted:
        return None
    return {
        "doc_code": code.strip(), "title": title.strip(), "category": category, "confidentiality": conf,
        "issuing_authority": authority.strip() or None, "owner": owner.strip() or None,
        "issue_date": str(issue), "expiry_date": str(expiry) if has_expiry else None,
        "renewal_lead_days": int(lead), "notes": notes.strip() or None,
    }


# ---------------------------------------------------------------- Pages
def dashboard() -> None:
    st.header("Dashboard")
    summary = get_json("/reports/summary")
    if not summary:
        return
    by_status = summary["by_status"]
    cols = st.columns(5)
    cols[0].metric("Documents", summary["total"])
    cols[1].metric("🟢 Active", by_status.get("Active", 0))
    cols[2].metric("🟠 Expiring soon", by_status.get("Expiring Soon", 0))
    cols[3].metric("🔴 Expired", by_status.get("Expired", 0))
    cols[4].metric("🔔 Open alerts", summary["open_alerts"])

    left, right = st.columns([1, 2])
    with left:
        st.subheader("By category")
        if summary["by_category"]:
            st.bar_chart(pd.Series(summary["by_category"], name="documents"))
    with right:
        st.subheader("Upcoming expiries (next 90 days)")
        if summary["upcoming_expiries"]:
            df = pd.DataFrame(summary["upcoming_expiries"])[
                ["doc_code", "title", "category", "expiry_date", "days_left", "status"]]
            st.dataframe(with_icons(df), hide_index=True, width="stretch")
        else:
            st.info("Nothing expires in the next 90 days.")


def register() -> None:
    st.header("Document Register")
    f1, f2, f3, f4 = st.columns([2, 1, 1, 1])
    search = f1.text_input("Search", placeholder="code, title, owner, authority…")
    category = f2.selectbox("Category", [""] + CATEGORIES, format_func=lambda x: x or "All")
    status = f3.selectbox("Status", [""] + STATUSES, format_func=lambda x: x or "All")
    include_archived = f4.checkbox("Include archived") if role() == "admin" else False

    docs = get_json("/documents", search=search, category=category, status=status,
                    include_archived=include_archived)
    if docs is None:
        return
    if not docs:
        st.info("No documents match these filters.")
        return

    df = pd.DataFrame(docs)
    shown = with_icons(df[["doc_code", "title", "category", "confidentiality", "owner",
                           "expiry_date", "days_left", "status", "is_archived"]].copy())
    st.dataframe(shown, hide_index=True, width="stretch")
    csv = call("GET", "/documents/export/csv")
    if csv.ok:
        st.download_button("⬇️ Export register (CSV)", csv.content, "document_register.csv", "text/csv")

    st.divider()
    labels = {d["id"]: f"{d['doc_code']} — {d['title']}" for d in docs}
    doc_id = st.selectbox("Open a document", list(labels), format_func=labels.get)
    document_detail(next(d for d in docs if d["id"] == doc_id))


def document_detail(doc: dict) -> None:
    st.subheader(f"{STATUS_ICON.get(doc['status'], '')} {doc['doc_code']} — {doc['title']}")
    m = st.columns(4)
    m[0].metric("Status", doc["status"])
    m[1].metric("Expiry date", doc["expiry_date"] or "—")
    m[2].metric("Days left", doc["days_left"] if doc["days_left"] is not None else "—")
    m[3].metric("Confidentiality", doc["confidentiality"])
    if doc["is_archived"]:
        st.warning("This document is archived.")

    tabs = st.tabs(["Details & history", "Renew", "Edit", "Attachment", "Admin"])
    doc_id = doc["id"]

    with tabs[0]:
        st.write(f"**Category:** {doc['category']}  |  **Issuing authority:** {doc['issuing_authority'] or '—'}  |  "
                 f"**Owner:** {doc['owner'] or '—'}")
        st.write(f"**Issued:** {doc['issue_date'] or '—'}  |  **Reminder:** {doc['renewal_lead_days']} days before expiry  |  "
                 f"**Created by:** {doc['created_by']}")
        if doc["notes"]:
            st.write(f"**Notes:** {doc['notes']}")
        st.markdown("**Update history**")
        history = get_json(f"/documents/{doc_id}/history")
        if history:
            hdf = pd.DataFrame(history)[["changed_at", "action", "changed_by", "details"]]
            st.dataframe(hdf, hide_index=True, width="stretch")

    with tabs[1]:
        if not is_manager():
            st.info("Only managers and admins can renew documents.")
        else:
            base = date.fromisoformat(doc["expiry_date"]) if doc["expiry_date"] else date.today()
            with st.form(f"renew_{doc_id}"):
                new_expiry = st.date_input("New expiry date", max(base, date.today()) + timedelta(days=365))
                note = st.text_input("Note (e.g. renewal reference number)")
                if st.form_submit_button("Record renewal"):
                    resp = call("POST", f"/documents/{doc_id}/renew",
                                json={"new_expiry_date": str(new_expiry), "note": note or None})
                    if resp.ok:
                        st.success("Renewal recorded. Related alerts were resolved.")
                        st.rerun()
                    show_error(resp)

    with tabs[2]:
        if not is_manager():
            st.info("Only managers and admins can edit documents.")
        else:
            payload = document_form(f"edit_{doc_id}", doc, "Save changes")
            if payload:
                resp = call("PUT", f"/documents/{doc_id}", json=payload)
                if resp.ok:
                    st.success("Document updated.")
                    st.rerun()
                show_error(resp)

    with tabs[3]:
        if doc["file_name"]:
            st.write(f"📎 **{doc['file_name']}**")
            if st.button("Prepare download", key=f"prep_{doc_id}"):
                resp = call("GET", f"/documents/{doc_id}/download")
                if resp.ok:
                    st.download_button("⬇️ Download file", resp.content, doc["file_name"],
                                       key=f"dl_{doc_id}", on_click="ignore")
                else:
                    show_error(resp)
        else:
            st.info("No file attached yet.")
        if is_manager():
            upload = st.file_uploader("Attach or replace file", type=["pdf", "png", "jpg", "jpeg", "docx", "xlsx", "txt"],
                                      key=f"up_{doc_id}")
            if upload and st.button("Upload", key=f"upbtn_{doc_id}"):
                resp = call("POST", f"/documents/{doc_id}/upload",
                            files={"file": (upload.name, upload.getvalue(), upload.type)})
                if resp.ok:
                    st.success("File uploaded.")
                    st.rerun()
                show_error(resp)

    with tabs[4]:
        if role() != "admin":
            st.info("Only admins can archive or restore documents.")
        elif doc["is_archived"]:
            if st.button("Restore document", key=f"restore_{doc_id}"):
                resp = call("POST", f"/documents/{doc_id}/restore")
                if resp.ok:
                    st.rerun()
                show_error(resp)
        else:
            st.caption("Archiving hides the document from the register but keeps its full history.")
            if st.button("Archive document", type="primary", key=f"archive_{doc_id}"):
                resp = call("DELETE", f"/documents/{doc_id}")
                if resp.ok:
                    st.rerun()
                show_error(resp)


def add_document() -> None:
    st.header("Add Document")
    payload = document_form("add_doc", None, "Register document")
    if payload:
        resp = call("POST", "/documents", json=payload)
        if resp.ok:
            st.success(f"Document {payload['doc_code']} registered. Open it in the register to attach a file.")
        else:
            show_error(resp)


def alerts_page() -> None:
    st.header("Expiry & Renewal Alerts")
    if is_manager() and st.button("🔄 Run expiry scan now"):
        resp = call("POST", "/alerts/run")
        if resp.ok:
            st.success(f"Scan complete — {resp.json()['new_alerts']} new alert(s).")
    alerts = get_json("/alerts")
    if not alerts:
        st.success("No open alerts. Everything is up to date. ✅")
        return
    df = pd.DataFrame(alerts)
    df["level"] = df["level"].map(lambda lv: f"{LEVEL_ICON.get(lv, '')} {lv}")
    st.dataframe(df[["id", "level", "doc_code", "doc_title", "expiry_on", "message"]],
                 hide_index=True, width="stretch")
    if is_manager():
        ids = {a["id"]: f"#{a['id']} — {a['doc_code']} ({a['level']})" for a in alerts}
        alert_id = st.selectbox("Acknowledge an alert", list(ids), format_func=ids.get)
        if st.button("Acknowledge"):
            resp = call("POST", f"/alerts/{alert_id}/acknowledge")
            if resp.ok:
                st.rerun()
            show_error(resp)


def report_markdown(r: dict) -> str:
    t = r["totals"]
    lines = [
        f"# Monthly Administrative Status Report — {r['period']}",
        f"_Generated {r['generated_at']} by {r['generated_by']}_", "",
        "## Key figures",
        f"- Documents on register: **{t['documents_on_register']}**",
        f"- New documents this month: **{t['new_documents']}**",
        f"- Renewals recorded: **{t['renewals']}**",
        f"- Record updates: **{t['updates']}**",
        f"- Files uploaded: **{t['files_uploaded']}**",
        f"- Alerts raised: **{t['alerts_raised']}**",
        f"- Currently expired: **{t['expired_now']}**",
        f"- Expiring in next 30 days: **{t['expiring_next_30_days']}**", "",
    ]
    for title, rows in (("Expired documents", r["expired_documents"]), ("Expiring in next 30 days", r["expiring_soon"])):
        lines += [f"## {title}"]
        if rows:
            lines += ["| Code | Title | Owner | Expiry | Days left |", "|---|---|---|---|---|"]
            lines += [f"| {x['doc_code']} | {x['title']} | {x['owner'] or '—'} | {x['expiry_date']} | {x['days_left']} |" for x in rows]
        else:
            lines.append("None.")
        lines.append("")
    lines += ["## Register breakdown", "**By category:** " + ", ".join(f"{k} ({v})" for k, v in r["by_category"].items()),
              "", "**By confidentiality:** " + ", ".join(f"{k} ({v})" for k, v in r["by_confidentiality"].items())]
    return "\n".join(lines)


def reports_page() -> None:
    st.header("Monthly Administrative Status Report")
    today = date.today()
    c1, c2, _ = st.columns([1, 1, 3])
    year = c1.number_input("Year", 2000, 2100, today.year)
    month = c2.number_input("Month", 1, 12, today.month)
    report = get_json("/reports/monthly", year=int(year), month=int(month))
    if not report:
        return
    t = report["totals"]
    row1, row2 = st.columns(4), st.columns(4)
    for col, (label, key) in zip(row1 + row2, [
        ("On register", "documents_on_register"), ("New this month", "new_documents"),
        ("Renewals", "renewals"), ("Updates", "updates"), ("Alerts raised", "alerts_raised"),
        ("Files uploaded", "files_uploaded"), ("Expired now", "expired_now"),
        ("Expiring ≤30 days", "expiring_next_30_days")]):
        col.metric(label, t[key])

    left, right = st.columns(2)
    with left:
        st.subheader("Expired documents")
        if report["expired_documents"]:
            st.dataframe(pd.DataFrame(report["expired_documents"])[["doc_code", "title", "owner", "expiry_date", "days_left"]],
                         hide_index=True, width="stretch")
        else:
            st.success("None")
    with right:
        st.subheader("Expiring in next 30 days")
        if report["expiring_soon"]:
            st.dataframe(pd.DataFrame(report["expiring_soon"])[["doc_code", "title", "owner", "expiry_date", "days_left"]],
                         hide_index=True, width="stretch")
        else:
            st.success("None")

    md = report_markdown(report)
    d1, d2, _ = st.columns([1, 1, 3])
    d1.download_button("⬇️ Report (Markdown)", md, f"status_report_{report['period']}.md", "text/markdown")
    d2.download_button("⬇️ Report (JSON)", pd.Series(report).to_json(indent=2), f"status_report_{report['period']}.json")
    with st.expander("Preview Markdown report"):
        st.markdown(md)


def users_page() -> None:
    st.header("User Management")
    users = get_json("/auth/users")
    if users:
        st.dataframe(pd.DataFrame(users), hide_index=True, width="stretch")
    with st.form("new_user"):
        st.subheader("Create user")
        c1, c2 = st.columns(2)
        username = c1.text_input("Username")
        full_name = c2.text_input("Full name")
        password = c1.text_input("Password (min 8 chars)", type="password")
        new_role = c2.selectbox("Role", ["staff", "manager", "admin"])
        if st.form_submit_button("Create user"):
            resp = call("POST", "/auth/users", json={"username": username, "full_name": full_name,
                                                      "password": password, "role": new_role})
            if resp.ok:
                st.success("User created.")
                st.rerun()
            show_error(resp)
    if users:
        st.subheader("Activate / deactivate")
        labels = {u["id"]: f"{u['username']} ({u['role']}, {'active' if u['is_active'] else 'inactive'})" for u in users}
        uid = st.selectbox("User", list(labels), format_func=labels.get)
        target = next(u for u in users if u["id"] == uid)
        if st.button("Deactivate" if target["is_active"] else "Activate"):
            resp = call("PATCH", f"/auth/users/{uid}/active", params={"active": not target["is_active"]})
            if resp.ok:
                st.rerun()
            show_error(resp)


# ---------------------------------------------------------------- Main
def main() -> None:
    if "token" not in st.session_state:
        login_view()
        st.stop()

    pages = {"📊 Dashboard": dashboard, "📁 Document Register": register}
    if is_manager():
        pages["➕ Add Document"] = add_document
    pages["🔔 Alerts"] = alerts_page
    pages["📝 Monthly Report"] = reports_page
    if role() == "admin":
        pages["👥 User Management"] = users_page

    with st.sidebar:
        st.title("🗂️ DocTrack")
        user = st.session_state.user
        st.caption(f"{user['full_name']} · **{user['role']}**")
        choice = st.radio("Navigate", list(pages), label_visibility="collapsed")
        if st.button("Sign out"):
            st.session_state.clear()
            st.rerun()
    pages[choice]()


main()
