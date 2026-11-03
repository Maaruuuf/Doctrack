from datetime import date, timedelta

from fastapi.testclient import TestClient


def make_doc(client: TestClient, headers, code, **overrides):
    body = {
        "doc_code": code, "title": f"Document {code}", "category": "Licence",
        "confidentiality": "Public",
        "issue_date": str(date.today() - timedelta(days=100)),
        "expiry_date": str(date.today() + timedelta(days=100)),
        "renewal_lead_days": 30,
    }
    body.update(overrides)
    return client.post("/documents", json=body, headers=headers)


def test_login_rejects_wrong_password(client):
    r = client.post("/auth/login", data={"username": "admin", "password": "nope"})
    assert r.status_code == 401


def test_requests_without_token_are_rejected(client):
    assert client.get("/documents").status_code == 401


def test_staff_cannot_create_documents(client, auth):
    assert make_doc(client, auth["staff"], "ST-1").status_code == 403


def test_duplicate_code_is_rejected(client, auth):
    assert make_doc(client, auth["manager"], "DUP-1").status_code == 201
    assert make_doc(client, auth["manager"], "DUP-1").status_code == 409


def test_expiry_date_before_issue_date_is_rejected(client, auth):
    r = make_doc(client, auth["manager"], "BAD-1",
                 issue_date=str(date.today()), expiry_date=str(date.today() - timedelta(days=1)))
    assert r.status_code == 422


def test_status_calculation(client, auth):
    h = auth["manager"]
    soon = make_doc(client, h, "STAT-SOON", expiry_date=str(date.today() + timedelta(days=10))).json()
    expired = make_doc(client, h, "STAT-EXP", expiry_date=str(date.today() - timedelta(days=2))).json()
    never = make_doc(client, h, "STAT-NONE", expiry_date=None).json()
    active = make_doc(client, h, "STAT-OK").json()
    assert soon["status"] == "Expiring Soon" and soon["days_left"] == 10
    assert expired["status"] == "Expired"
    assert never["status"] == "No Expiry"
    assert active["status"] == "Active"


def test_alerts_are_generated_and_deduplicated(client, auth):
    h = auth["manager"]
    alerts = client.get("/alerts", headers=h).json()
    levels = {a["doc_code"]: a["level"] for a in alerts}
    assert levels["STAT-SOON"] == "WARNING"
    assert levels["STAT-EXP"] == "EXPIRED"
    before = len(alerts)
    assert client.post("/alerts/run", headers=h).json()["new_alerts"] == 0  # idempotent
    assert len(client.get("/alerts", headers=h).json()) == before


def test_renewal_resolves_alerts_and_is_audited(client, auth):
    h = auth["manager"]
    doc = make_doc(client, h, "REN-1", expiry_date=str(date.today() + timedelta(days=3))).json()
    assert any(a["doc_code"] == "REN-1" for a in client.get("/alerts", headers=h).json())

    new_expiry = str(date.today() + timedelta(days=400))
    r = client.post(f"/documents/{doc['id']}/renew", json={"new_expiry_date": new_expiry, "note": "Renewed"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "Active"
    assert not any(a["doc_code"] == "REN-1" for a in client.get("/alerts", headers=h).json())

    history = client.get(f"/documents/{doc['id']}/history", headers=h).json()
    assert [e["action"] for e in history][:2] == ["RENEWED", "CREATED"]


def test_update_writes_audit_trail(client, auth):
    h = auth["manager"]
    doc = make_doc(client, h, "UPD-1").json()
    r = client.put(f"/documents/{doc['id']}", json={"title": "New title"}, headers=h)
    assert r.status_code == 200 and r.json()["title"] == "New title"
    latest = client.get(f"/documents/{doc['id']}/history", headers=h).json()[0]
    assert latest["action"] == "UPDATED" and "title" in latest["details"]


def test_role_based_access_to_confidential_documents(client, auth):
    admin, manager, staff = auth["admin"], auth["manager"], auth["staff"]
    conf = make_doc(client, manager, "RBAC-CONF", confidentiality="Confidential").json()
    restricted = make_doc(client, admin, "RBAC-RES", confidentiality="Restricted").json()

    # managers cannot create Restricted documents
    assert make_doc(client, manager, "RBAC-NOPE", confidentiality="Restricted").status_code == 403

    def codes(headers):
        return {d["doc_code"] for d in client.get("/documents", headers=headers).json()}

    assert {"RBAC-CONF", "RBAC-RES"} <= codes(admin)
    assert "RBAC-CONF" in codes(manager) and "RBAC-RES" not in codes(manager)
    assert "RBAC-CONF" not in codes(staff) and "RBAC-RES" not in codes(staff)

    # direct access is blocked and does not reveal the document exists
    assert client.get(f"/documents/{conf['id']}", headers=staff).status_code == 404
    assert client.get(f"/documents/{restricted['id']}", headers=manager).status_code == 404
    assert client.get(f"/documents/{restricted['id']}/history", headers=manager).status_code == 404


def test_csv_export_respects_permissions(client, auth):
    r = client.get("/documents/export/csv", headers=auth["staff"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "RBAC-CONF" not in r.text and "DUP-1" in r.text


def test_file_upload_and_download(client, auth):
    h = auth["manager"]
    doc = make_doc(client, h, "FILE-1").json()
    url = f"/documents/{doc['id']}"
    assert client.post(f"{url}/upload", files={"file": ("x.txt", b"hello")}, headers=auth["staff"]).status_code == 403
    assert client.post(f"{url}/upload", files={"file": ("evil.exe", b"MZ")}, headers=h).status_code == 400
    r = client.post(f"{url}/upload", files={"file": ("licence.txt", b"hello world")}, headers=h)
    assert r.status_code == 200 and r.json()["file_name"] == "licence.txt"
    d = client.get(f"{url}/download", headers=h)
    assert d.status_code == 200 and d.content == b"hello world"


def test_archive_is_soft_delete_admin_only(client, auth):
    doc = make_doc(client, auth["manager"], "ARC-1").json()
    url = f"/documents/{doc['id']}"
    assert client.delete(url, headers=auth["manager"]).status_code == 403
    assert client.delete(url, headers=auth["admin"]).status_code == 204
    assert client.get(url, headers=auth["manager"]).status_code == 404
    listed = client.get("/documents?include_archived=true", headers=auth["admin"]).json()
    assert any(d["doc_code"] == "ARC-1" and d["is_archived"] for d in listed)
    assert client.post(f"{url}/restore", headers=auth["admin"]).status_code == 200
    assert client.get(url, headers=auth["manager"]).status_code == 200


def test_monthly_report(client, auth):
    r = client.get("/reports/monthly", headers=auth["manager"])
    assert r.status_code == 200
    report = r.json()
    assert report["totals"]["new_documents"] >= 1
    assert report["totals"]["renewals"] >= 1
    assert any(d["doc_code"] == "STAT-EXP" for d in report["expired_documents"])
    assert client.get("/reports/monthly?month=13", headers=auth["manager"]).status_code == 422


def test_dashboard_summary(client, auth):
    s = client.get("/reports/summary", headers=auth["manager"]).json()
    assert s["total"] > 0 and s["open_alerts"] > 0 and "Licence" in s["by_category"]


def test_user_management_is_admin_only(client, auth):
    assert client.get("/auth/users", headers=auth["manager"]).status_code == 403
    assert client.get("/auth/users", headers=auth["admin"]).status_code == 200
