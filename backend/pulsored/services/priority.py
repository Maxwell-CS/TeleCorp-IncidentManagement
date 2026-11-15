"""Evidencia de antenas + recálculo de prioridad explicable (RF-AZ-11/12/13/15)."""
from .. import clock, config, domain


def evidence(store, zone_id):
    since = clock.ago(hours=config.evidence_window_hours())
    return domain.antenna_evidence(store.infra_events(zone_id, since))


def recompute(store, incident_id, zone_id):
    """Relee reportes y eventos, actualiza origen/antenas/lag/prioridad y deja rastro si cambió."""
    inc = store.get("incidents", incident_id, zone_id)
    if not inc or inc["status"] == "CERRADA":
        return inc
    ev = evidence(store, zone_id)
    zone = store.get_zone(zone_id) or {}
    now = clock.now()
    hours_open = (now - clock.parse(inc["opened_at"])).total_seconds() / 3600
    recurrence = store.count_incidents_since(zone_id, clock.ago(days=30), exclude_id=incident_id)
    crit = bool((inc.get("ai") or {}).get("critical_site"))
    p = domain.compute_priority(inc["users_affected"], zone.get("type", "RESIDENCIAL"), crit,
                                ev["weight"], hours_open, recurrence)

    inc["antenna_ids"] = ev["antenna_ids"]
    inc["first_anomaly_at"] = ev["first_anomaly_at"]
    inc["origin"] = "BOTH" if ev["antenna_ids"] else "USERS"
    if ev["first_anomaly_at"] and inc.get("first_report_at"):
        # positivo = la antena avisó ANTES que los usuarios (ganancia de detección)
        inc["detection_lag_s"] = int((clock.parse(inc["first_report_at"]) - clock.parse(ev["first_anomaly_at"])).total_seconds())
    old = (inc.get("priority_score"), inc.get("priority_level"))
    inc["priority_score"], inc["priority_level"], inc["priority_factors"] = p["score"], p["level"], p["factors"]
    inc["updated_at"] = clock.iso()
    store.upsert("incidents", inc)
    if old != (p["score"], p["level"]):
        store.add_history(incident_id, inc["status"], inc["status"], "SISTEMA", "PRIORITY_CHANGED",
                          f'{old[0]}({old[1]}) -> {p["score"]}({p["level"]})')
    return inc
