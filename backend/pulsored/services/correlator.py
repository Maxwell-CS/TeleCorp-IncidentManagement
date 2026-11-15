"""Correlador de reportes -> incidente colectivo (RF-AZ-06…09).

Regla: >= N usuarios DISTINTOS (documento+teléfono) con reportes en la misma zona y grupo de problema,
dentro de una ventana deslizante de 24 h. Con un incidente abierto, los nuevos reportes se enlazan.
Todo es idempotente: IDs determinísticos y create_item (409 = ya existía)."""
import logging
from datetime import timedelta

from .. import clock, config
from . import priority

log = logging.getLogger("pulsored.correlator")


def _link(store, inc, reports):
    """Enlaza reportes al incidente y actualiza el conteo exacto de usuarios distintos."""
    for r in reports:
        if r.get("incident_id") == inc["id"]:
            continue
        r["incident_id"], r["updated_at"] = inc["id"], clock.iso()
        store.upsert("reports", r)
        store.add_incident_user(inc["id"], r["user_key"])
        store.add_history(r["id"], r["status"], r["status"], "SISTEMA", "LINKED_TO_INCIDENT", inc["id"])
    inc = store.get("incidents", inc["id"], inc["zone_id"]) or inc
    inc["users_affected"] = store.count_incident_users(inc["id"])
    inc["updated_at"] = clock.iso()
    store.upsert("incidents", inc)
    return inc


def process_report(store, r):
    """Procesa un reporte del change feed. Devuelve el incidente NUEVO creado (o None)."""
    if r.get("incident_id") or r.get("status") == "CERRADA" or not r.get("zone_id"):
        return None  # ya enlazado (también evita bucles por nuestros propios updates)
    zone, group = r["zone_id"], r["problem_group"]

    open_inc = store.find_open_incident(zone, group)
    if open_inc:
        inc = _link(store, open_inc, [r])
        priority.recompute(store, inc["id"], zone)
        return None

    since = clock.iso(clock.parse(r["created_at"]) - timedelta(hours=config.window_hours()))
    pending = store.reports_unlinked_since(zone, group, since)
    users = {p["user_key"] for p in pending}
    if r["user_key"] not in users:  # el propio reporte siempre cuenta
        pending.append(r)
        users.add(r["user_key"])
    if len(users) < config.users_threshold():
        return None

    first = min(p["created_at"] for p in pending)
    inc_id = f'INC-{zone}-{group}-{int(clock.parse(r["created_at"]).timestamp())}'
    now = clock.iso()
    inc = {
        "id": inc_id, "incident_id": inc_id, "zone_id": zone, "problem_group": group, "status": "REGISTRADA",
        "origin": "USERS", "users_affected": 0, "priority_score": 0, "priority_level": "BAJA",
        "priority_factors": {}, "antenna_ids": [], "first_report_at": first, "first_anomaly_at": None,
        "detection_lag_s": None, "ai": None, "ai_source": None, "opened_at": now, "closed_at": None, "updated_at": now,
    }
    if not store.create("incidents", inc):
        return None  # ya existía (reproceso del change feed): no reiniciar la orquestación
    store.add_history(inc_id, None, "REGISTRADA", "SISTEMA", "INCIDENT_OPENED",
                      f"{len(users)} usuarios distintos en {zone}/{group}")
    inc = _link(store, inc, pending)
    priority.recompute(store, inc_id, zone)
    log.info("incidente %s abierto con %d usuarios", inc_id, inc["users_affected"])
    return store.get("incidents", inc_id, zone)
