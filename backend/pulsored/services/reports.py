"""Consulta pública de un reporte y cambios de estado por el operador (RF-AZ-04/05)."""
from .. import clock, domain


def _public(r):
    return {k: r.get(k) for k in ("report_id", "zone_id", "problem_type", "created_at", "updated_at", "incident_id")}


def get_public_report(store, report_id):
    """Nunca devuelve datos personales."""
    zone = domain.zone_of_report_id(report_id)
    r = store.get("reports", report_id, zone) if zone else None
    if not r:
        return 404, {"error": "NOT_FOUND", "message": "Reporte no encontrado"}
    out = _public(r)
    out["status"] = r["status"]
    history = store.list_history(report_id)
    if r.get("incident_id"):
        inc = store.get("incidents", r["incident_id"], zone)
        if inc:
            out["incident"] = {"incident_id": inc["id"], "status": inc["status"]}
            if r["status"] != "CERRADA":
                out["status"] = inc["status"]  # estado efectivo: el del incidente colectivo
            history = sorted(history + store.list_history(inc["id"]), key=lambda h: h["ts"])
    out["history"] = [{k: h.get(k) for k in ("ts", "from", "to", "actor", "action", "note")} for h in history]
    return 200, out


def change_report_status(store, report_id, to, note, actor="OPERADOR"):
    zone = domain.zone_of_report_id(report_id)
    r = store.get("reports", report_id, zone) if zone else None
    if not r:
        return 404, {"error": "NOT_FOUND", "message": "Reporte no encontrado"}
    if to not in domain.STATES:
        return 400, {"error": "BAD_REQUEST", "message": f"Estado inválido: {to}"}
    if not domain.can_transition(r["status"], to):
        store.add_history(report_id, r["status"], to, actor, "TRANSITION_REJECTED", note or "")
        return 409, {"error": "INVALID_TRANSITION", "message": f'{r["status"]} -> {to} no permitido'}
    store.add_history(report_id, r["status"], to, actor, "STATUS_CHANGED", note or "")
    r["status"], r["updated_at"] = to, clock.iso()
    store.upsert("reports", r)
    return 200, {"report_id": report_id, "status": to}
