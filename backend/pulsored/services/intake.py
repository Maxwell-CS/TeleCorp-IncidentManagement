"""POST /reports: validación, idempotencia y registro (RF-AZ-01/02/03)."""
import base64
import hashlib

from jsonschema import Draft202012Validator

from .. import clock, domain
from ..store import ZONES

REPORT_SCHEMA = {
    "type": "object",
    "required": ["idempotency_key", "user_document", "phone", "zone_id", "occurred_at", "problem_type", "description"],
    "additionalProperties": False,
    "properties": {
        "idempotency_key": {"type": "string", "minLength": 8, "maxLength": 64},
        "user_document": {"type": "string", "pattern": r"^[A-Za-z0-9]{6,15}$"},
        "phone": {"type": "string", "pattern": r"^\+?[0-9]{7,15}$"},
        "email": {"type": "string", "format": "email", "maxLength": 120, "pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$"},
        "zone_id": {"type": "string", "maxLength": 8},
        "location": {
            "type": "object",
            "required": ["lat", "lng"],
            "properties": {"lat": {"type": "number", "minimum": -90, "maximum": 90},
                           "lng": {"type": "number", "minimum": -180, "maximum": 180}},
        },
        "occurred_at": {"type": "string", "maxLength": 40},
        "problem_type": {"enum": list(domain.PROBLEM_GROUPS)},
        "description": {"type": "string", "maxLength": 1000},
    },
}
_validator = Draft202012Validator(REPORT_SCHEMA)


def user_key(document: str, phone: str) -> str:
    return hashlib.sha256(f"{document.strip().upper()}|{phone.strip()}".encode()).hexdigest()[:24]


def report_id_for(zone_id: str, idempotency_key: str) -> str:
    """Determinístico: el mismo idempotency_key siempre produce el mismo id."""
    digest = hashlib.sha256(idempotency_key.encode()).digest()
    return f"R-{zone_id}-" + base64.b32encode(digest)[:16].decode()


def validate(body):
    errors = sorted(_validator.iter_errors(body), key=lambda e: list(e.path))
    if errors:
        e = errors[0]
        loc = ".".join(str(p) for p in e.path) or "body"
        return f"{loc}: {e.message}"
    if body["zone_id"] not in ZONES:
        return "zone_id: zona desconocida"
    try:
        clock.parse(body["occurred_at"])
    except ValueError:
        return "occurred_at: fecha ISO-8601 inválida"
    return None


def register_report(store, body):
    """Devuelve (status_http, cuerpo)."""
    if not isinstance(body, dict):
        return 400, {"error": "BAD_REQUEST", "message": "Se esperaba un objeto JSON"}
    err = validate(body)
    if err:
        return 400, {"error": "BAD_REQUEST", "message": err}
    now = clock.iso()
    rid = report_id_for(body["zone_id"], body["idempotency_key"])
    doc = {
        "id": rid, "report_id": rid, "zone_id": body["zone_id"],
        "user_key": user_key(body["user_document"], body["phone"]),
        "user_document": body["user_document"], "phone": body["phone"], "email": body.get("email"),
        "location": body.get("location"),
        "occurred_at": clock.normalize(body["occurred_at"]), "created_at": now, "updated_at": now,
        "problem_type": body["problem_type"], "problem_group": domain.PROBLEM_GROUPS[body["problem_type"]],
        "description": body["description"], "status": "REGISTRADA", "incident_id": None,
        "idempotency_key": body["idempotency_key"],
    }
    if not store.create("reports", doc):
        return 200, {"report_id": rid, "status": "REGISTRADA", "duplicate": True}
    store.add_history(rid, None, "REGISTRADA", "USUARIO", "REPORT_CREATED", "Reporte recibido")
    return 202, {"report_id": rid, "status": "REGISTRADA"}
