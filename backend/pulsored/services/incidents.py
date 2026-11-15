"""API de gestión de incidentes para la consola de operación (RF-AZ-14/15)."""
from .. import clock, domain


def _summary(i):
    keys = ("incident_id", "zone_id", "problem_group", "status", "origin", "users_affected", "priority_score",
            "priority_level", "antenna_ids", "opened_at", "closed_at", "detection_lag_s", "ai_source", "updated_at")
    return {k: i.get(k) for k in keys}


def list_incidents(store, zone=None, include_closed=False):
    return 200, {"items": [_summary(i) for i in store.list_incidents(zone, include_closed)]}


def get_incident(store, incident_id):
    zone = incident_id.split("-")[1] if incident_id.startswith("INC-") and incident_id.count("-") >= 3 else None
    inc = store.get("incidents", incident_id, zone) if zone else None
    if not inc:
        return 404, {"error": "NOT_FOUND", "message": "Incidente no encontrado"}
    reports = store.reports_for_incident(incident_id, zone)
    out = _summary(inc)
    out.update({
        "priority_factors": inc.get("priority_factors"), "ai": inc.get("ai"), "first_report_at": inc.get("first_report_at"),
        "first_anomaly_at": inc.get("first_anomaly_at"),
        "history": [{k: h.get(k) for k in ("ts", "from", "to", "actor", "action", "note")} for h in store.list_history(incident_id)],
        "reports": [{"report_id": r["id"], "created_at": r["created_at"], "problem_type": r["problem_type"],
                     "description": r["description"][:200]} for r in reports[:200]],  # sin datos de contacto
    })
    return 200, out


def force_status(store, incident_id, zone, to, actor, note, reason=None):
    """Cambia estado validando la transición; inválida => rechazada y registrada. Idempotente si ya está en `to`."""
    inc = store.get("incidents", incident_id, zone)
    if not inc:
        return 404, {"error": "NOT_FOUND", "message": "Incidente no encontrado"}
    if inc["status"] == to:
        return 200, {"incident_id": incident_id, "status": to, "applied": False}
    if not domain.can_transition(inc["status"], to):
        store.add_history(incident_id, inc["status"], to, actor, "TRANSITION_REJECTED", note or "")
        return 409, {"error": "INVALID_TRANSITION", "message": f'{inc["status"]} -> {to} no permitido'}
    store.add_history(incident_id, inc["status"], to, actor, "STATUS_CHANGED", (note or reason or ""))
    inc["status"], inc["updated_at"] = to, clock.iso()
    if to == "CERRADA":
        inc["closed_at"] = inc["updated_at"]
        if reason:
            inc["close_reason"] = reason
    if to == "SOLUCIONADA":
        inc["resolved_at"] = inc["updated_at"]
    store.upsert("incidents", inc)
    return 200, {"incident_id": incident_id, "status": to, "applied": True}


def apply_action(store, incident_id, body, actor="OPERADOR"):
    """Devuelve (status, cuerpo, señal). señal = valor a enviar a la orquestación Durable ('CONFIRMAR'/'DESCARTAR') o None."""
    action = (body or {}).get("action")
    note = (body or {}).get("note", "")
    status, inc = get_incident(store, incident_id)
    if status != 200:
        return status, inc, None
    zone = inc["zone_id"]
    if action == "CONFIRMAR":
        if inc["status"] not in ("REGISTRADA", "EN_REVISION"):
            return 409, {"error": "INVALID_STATE", "message": "El incidente ya fue confirmado"}, None
        store.add_history(incident_id, inc["status"], inc["status"], actor, "OPERATOR_CONFIRMED", note)
        return 202, {"incident_id": incident_id, "action": action}, "CONFIRMAR"
    if action == "DESCARTAR":
        if inc["status"] not in ("REGISTRADA", "EN_REVISION"):
            return 409, {"error": "INVALID_STATE", "message": "Solo se descarta antes de la atención"}, None
        store.add_history(incident_id, inc["status"], inc["status"], actor, "OPERATOR_DISCARDED", note)
        return 202, {"incident_id": incident_id, "action": action}, "DESCARTAR"
    if action == "CAMBIAR_ESTADO":
        to = (body or {}).get("to")
        if to not in domain.STATES:
            return 400, {"error": "BAD_REQUEST", "message": "Estado destino inválido"}, None
        code, out = force_status(store, incident_id, zone, to, actor, note)
        return code, out, None
    return 400, {"error": "BAD_REQUEST", "message": "action debe ser CONFIRMAR, DESCARTAR o CAMBIAR_ESTADO"}, None
