from pulsored import domain


def test_transitions():
    assert domain.can_transition("REGISTRADA", "EN_REVISION")
    assert domain.can_transition("SOLUCIONADA", "EN_REVISION")  # reapertura
    assert not domain.can_transition("REGISTRADA", "SOLUCIONADA")
    assert not domain.can_transition("CERRADA", "EN_REVISION")


def test_priority_health_beats_residential():
    salud = domain.compute_priority(5000, "SALUD", False, 0.7, 1, 0)
    resid = domain.compute_priority(12, "RESIDENCIAL", False, 0.0, 1, 0)
    assert salud["score"] > resid["score"]
    assert salud["level"] in ("ALTA", "CRITICA")
    assert resid["level"] in ("BAJA", "MEDIA")


def test_priority_levels_and_bounds():
    assert domain.priority_level(75) == "CRITICA"
    assert domain.priority_level(74) == "ALTA"
    assert domain.priority_level(25) == "MEDIA"
    assert domain.priority_level(24) == "BAJA"
    top = domain.compute_priority(10 ** 6, "SALUD", True, 1.0, 99, 99)
    assert top["score"] == 100


def _ev(ant, typ, at):
    return {"antenna_id": ant, "event_type": typ, "occurred_at": at}


def test_antenna_evidence_latest_wins():
    evs = [_ev("A1", "ANTENNA_DOWN", "2026-11-15T10:00:00.000000Z"),
           _ev("A1", "ANTENNA_DISABLED", "2026-11-15T10:05:00.000000Z"),
           _ev("A2", "ANTENNA_DOWN", "2026-11-15T10:01:00.000000Z"),
           _ev("A2", "ANTENNA_RECOVERED", "2026-11-15T10:30:00.000000Z")]
    e = domain.antenna_evidence(evs)
    assert e["antenna_ids"] == ["A1"] and e["weight"] == 1.0 and e["confirmed"]
    assert e["first_anomaly_at"] == "2026-11-15T10:00:00.000000Z"


def test_predictive_risk_does_not_confirm():
    e = domain.antenna_evidence([_ev("A1", "PREDICTIVE_RISK", "2026-11-15T10:00:00.000000Z")])
    assert not e["confirmed"] and e["weight"] == 0.2


def test_critical_site_and_report_id_zone():
    assert domain.detect_critical_site(["No hay señal cerca del Hospital Loayza"])
    assert not domain.detect_critical_site(["no tengo internet"])
    assert domain.zone_of_report_id("R-Z07-ABCDEF") == "Z07"
    assert domain.zone_of_report_id("basura") == ""
