"""Funciones HTTP: portal de usuario, consola de operación y recepción de eventos de AWS."""
import logging

import azure.durable_functions as df
import azure.functions as func

from pulsored import httpx
from pulsored.queueing import get_queue
from pulsored.services import incidents, infra, intake, reports
from pulsored.store import get_store

bp = df.Blueprint()
log = logging.getLogger("pulsored.http")


def _resp(result):
    status, body = result[0], result[1]
    return func.HttpResponse(httpx.dumps(body), status_code=status, mimetype="application/json",
                             headers={"Cache-Control": "no-store"})


def _body(req):
    try:
        return req.get_json()
    except ValueError:
        return None


@bp.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _resp((200, {"ok": True, "service": "pulsored-azure"}))


@bp.route(route="zones", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def zones(req: func.HttpRequest) -> func.HttpResponse:
    return _resp((200, {"items": get_store().list_zones()}))


# ---------- portal de usuario ----------
@bp.route(route="reports", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def intake_report(req: func.HttpRequest) -> func.HttpResponse:
    if len(req.get_body() or b"") > 8192:
        return _resp((413, {"error": "TOO_LARGE", "message": "Solicitud demasiado grande"}))
    return _resp(intake.register_report(get_store(), _body(req)))


@bp.route(route="reports/{report_id}", methods=["GET", "PATCH"], auth_level=func.AuthLevel.ANONYMOUS)
def reports_api(req: func.HttpRequest) -> func.HttpResponse:
    rid = req.route_params["report_id"]
    if req.method == "GET":
        return _resp(reports.get_public_report(get_store(), rid))
    if not httpx.operator_ok(req.headers):
        return _resp(httpx.unauthorized())
    b = _body(req) or {}
    return _resp(reports.change_report_status(get_store(), rid, b.get("to"), b.get("note", "")))


# ---------- consola de operación ----------
@bp.route(route="incidents", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def incidents_list(req: func.HttpRequest) -> func.HttpResponse:
    if not httpx.operator_ok(req.headers):
        return _resp(httpx.unauthorized())
    return _resp(incidents.list_incidents(get_store(), req.params.get("zone_id"),
                                          req.params.get("include_closed") == "1"))


@bp.route(route="incidents/{incident_id}", methods=["GET", "PATCH"], auth_level=func.AuthLevel.ANONYMOUS)
@bp.durable_client_input(client_name="client")
async def incidents_detail(req: func.HttpRequest, client) -> func.HttpResponse:
    if not httpx.operator_ok(req.headers):
        return _resp(httpx.unauthorized())
    iid, store = req.route_params["incident_id"], get_store()
    if req.method == "GET":
        return _resp(incidents.get_incident(store, iid))
    status, body, signal = incidents.apply_action(store, iid, _body(req) or {})
    if signal:
        try:
            await client.raise_event(iid, "operator_decision", signal)
        except Exception as e:  # noqa: BLE001 - la orquestación ya terminó o no existe
            log.warning("no se pudo señalar %s (%s); aplico el cambio directo", iid, e)
            if signal == "DESCARTAR":
                zone = iid.split("-")[1]
                incidents.force_status(store, iid, zone, "CERRADA", "OPERADOR", "Descartado", reason="FALSO_POSITIVO")
    return _resp((status, body))


@bp.route(route="infra/events", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def infra_events_list(req: func.HttpRequest) -> func.HttpResponse:
    if not httpx.operator_ok(req.headers):
        return _resp(httpx.unauthorized())
    return _resp((200, {"items": get_store().list_infra_events(req.params.get("zone_id"))}))


@bp.route(route="ops/redrive", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def redrive_dlq(req: func.HttpRequest) -> func.HttpResponse:
    if not httpx.operator_ok(req.headers):
        return _resp(httpx.unauthorized())
    queue = (_body(req) or {}).get("queue")
    if queue not in ("notifications", "analytics-export"):
        return _resp((400, {"error": "BAD_REQUEST", "message": "queue inválida"}))
    return _resp((200, {"moved": get_queue().redrive(queue)}))


# ---------- eventos de AWS (function key) ----------
@bp.route(route="infra/events", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def ingest_infra_event(req: func.HttpRequest) -> func.HttpResponse:
    return _resp(infra.ingest_event(get_store(), _body(req)))
