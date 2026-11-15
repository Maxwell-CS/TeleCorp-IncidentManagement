"""Eventos de infraestructura enviados por AWS (RF-AZ-10/11/12). Contrato en AZURE2.md §3.2."""
from jsonschema import Draft202012Validator

from .. import clock, domain
from ..store import ZONES
from . import priority

EVENT_SCHEMA = {
    "type": "object",
    "required": ["event_id", "event_type", "antenna_id", "zone_id", "occurred_at"],
    "properties": {
        "event_id": {"type": "string", "minLength": 8, "maxLength": 80},
        "event_type": {"enum": domain.EVENT_TYPES},
        "antenna_id": {"type": "string", "maxLength": 40},
        "zone_id": {"type": "string", "maxLength": 8},
        "state_prev": {"type": "string"},
        "state_new": {"type": "string"},
        "traffic_gbmin": {"type": "number", "minimum": 0},
        "severity": {"enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
        "occurred_at": {"type": "string", "maxLength": 40},
        "prediction": {"type": "object"},
    },
}
_validator = Draft202012Validator(EVENT_SCHEMA)
TTL_SECONDS = 60 * 60 * 24 * 30


def ingest_event(store, body):
    """Devuelve (status_http, cuerpo): 202 aceptado · 200 duplicado · 400 inválido."""
    if not isinstance(body, dict):
        return 400, {"error": "BAD_REQUEST", "message": "Se esperaba un objeto JSON"}
    errors = sorted(_validator.iter_errors(body), key=lambda e: list(e.path))
    if errors:
        return 400, {"error": "BAD_REQUEST", "message": errors[0].message}
    if body["zone_id"] not in ZONES:
        return 400, {"error": "BAD_REQUEST", "message": "zone_id: zona desconocida"}
    try:
        occurred = clock.normalize(body["occurred_at"])
    except ValueError:
        return 400, {"error": "BAD_REQUEST", "message": "occurred_at: fecha ISO-8601 inválida"}
    doc = {**body, "id": body["event_id"], "occurred_at": occurred, "received_at": clock.iso(), "ttl": TTL_SECONDS}
    if not store.create("infra_events", doc):
        return 200, {"status": "duplicate"}
    return 202, {"status": "accepted"}


def link_event(store, ev):
    """Change feed de infra_events: relaciona el evento con incidentes abiertos de la zona.
    Devuelve la lista de incident_id que deben recibir la señal CONFIRMAR (orquestación a la espera)."""
    signals = []
    for inc in store.open_incidents_in_zone(ev["zone_id"]):
        store.add_history(inc["id"], inc["status"], inc["status"], "SISTEMA", "INFRA_EVENT",
                          f'{ev["event_type"]} {ev["antenna_id"]}')
        priority.recompute(store, inc["id"], ev["zone_id"])
        if ev["event_type"] in domain.ANOMALY_WEIGHT and ev["event_type"] != "PREDICTIVE_RISK" \
                and inc["status"] in ("REGISTRADA", "EN_REVISION"):
            signals.append(inc["id"])
    return signals
