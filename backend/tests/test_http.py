"""Importa los blueprints (valida que los decoradores de Azure Functions/Durable son correctos) y prueba la capa HTTP."""
import json

import azure.functions as func
from conftest import body


def _req(method, url, payload=None, headers=None, params=None, route=None):
    return func.HttpRequest(method, url, headers=headers or {}, params=params or {}, route_params=route or {},
                            body=json.dumps(payload).encode() if payload is not None else b"")


def test_function_app_registers_everything():
    import function_app
    names = {f.get_function_name() for f in function_app.app.get_functions()}
    expected = {"health", "zones", "intake_report", "reports_api", "incidents_list", "incidents_detail",
                "infra_events_list", "redrive_dlq", "ingest_infra_event", "correlator_fn", "infra_linker",
                "incident_lifecycle", "notifier", "exporter"}
    assert expected <= names, expected - names
    assert {"load_context", "check_infra", "ai_enrich", "compute_priority", "set_status", "enqueue_notifications",
            "enqueue_export", "alert_operator", "check_recovery", "check_new_reports"} <= names


def test_http_intake_and_public_get(env):
    from blueprints import http_api as h
    f = h.intake_report.build().get_user_function() if hasattr(h.intake_report, "build") else h.intake_report
    r = f(_req("POST", "/api/reports", body(1)))
    assert r.status_code == 202
    rid = json.loads(r.get_body())["report_id"]
    g = h.reports_api.build().get_user_function() if hasattr(h.reports_api, "build") else h.reports_api
    r2 = g(_req("GET", f"/api/reports/{rid}", route={"report_id": rid}))
    assert r2.status_code == 200 and json.loads(r2.get_body())["status"] == "REGISTRADA"


def test_http_operator_endpoints_require_token(env):
    from blueprints import http_api as h
    lst = h.incidents_list.build().get_user_function() if hasattr(h.incidents_list, "build") else h.incidents_list
    assert lst(_req("GET", "/api/incidents")).status_code == 401
    assert lst(_req("GET", "/api/incidents", headers={"x-operator-token": "mal"})).status_code == 401
    assert lst(_req("GET", "/api/incidents", headers={"x-operator-token": "tok-test"})).status_code == 200


def test_http_bad_json_and_oversize(env):
    from blueprints import http_api as h
    f = h.intake_report.build().get_user_function() if hasattr(h.intake_report, "build") else h.intake_report
    bad = func.HttpRequest("POST", "/api/reports", headers={}, params={}, route_params={}, body=b"{no json")
    assert f(bad).status_code == 400
    big = func.HttpRequest("POST", "/api/reports", headers={}, params={}, route_params={}, body=b"x" * 9000)
    assert f(big).status_code == 413


def test_http_infra_ingest(env):
    from blueprints import http_api as h
    f = h.ingest_infra_event.build().get_user_function() if hasattr(h.ingest_infra_event, "build") else h.ingest_infra_event
    e = {"event_id": "evt-http-0001", "event_type": "ANTENNA_DOWN", "antenna_id": "A-1", "zone_id": "Z07",
         "occurred_at": "2026-11-15T14:00:00Z"}
    assert f(_req("POST", "/api/infra/events", e)).status_code == 202
    assert f(_req("POST", "/api/infra/events", e)).status_code == 200
