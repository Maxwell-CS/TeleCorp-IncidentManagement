"""Reglas de negocio puras (sin I/O): grupos de problema, estados, prioridad, evidencia de antenas."""
import math

# problem_type -> problem_group (RF-AZ-06: "similares" = misma zona + mismo grupo)
PROBLEM_GROUPS = {
    "SIN_DATOS": "DATOS",
    "LENTITUD": "DATOS",
    "SIN_SENAL": "VOZ",
    "LLAMADAS": "VOZ",
    "SIN_SERVICIO": "TOTAL",
    "OTRO": "OTRO",
}

STATES = ["REGISTRADA", "EN_REVISION", "EN_ATENCION", "SOLUCIONADA", "CERRADA"]

TRANSITIONS = {
    "REGISTRADA": {"EN_REVISION", "CERRADA"},
    "EN_REVISION": {"EN_ATENCION", "CERRADA"},
    "EN_ATENCION": {"SOLUCIONADA"},
    "SOLUCIONADA": {"CERRADA", "EN_REVISION"},  # EN_REVISION = reapertura
    "CERRADA": set(),
}


def can_transition(frm: str, to: str) -> bool:
    return to in TRANSITIONS.get(frm, set())


# Peso de cada evento de antena como evidencia (factor A de la prioridad)
ANOMALY_WEIGHT = {
    "ANTENNA_DISABLED": 1.0,
    "ANTENNA_DOWN": 0.7,
    "ANTENNA_SATURATED": 0.5,
    "PREDICTIVE_RISK": 0.2,
}
EVENT_TYPES = list(ANOMALY_WEIGHT) + ["ANTENNA_RECOVERED"]

ZONE_WEIGHT = {
    "SALUD": 1.0, "CRITICA": 1.0, "EDUCATIVA": 0.8,
    "INDUSTRIAL": 0.7, "COMERCIAL": 0.5, "RESIDENCIAL": 0.4,
}


def priority_level(score: int) -> str:
    if score >= 75:
        return "CRITICA"
    if score >= 50:
        return "ALTA"
    if score >= 25:
        return "MEDIA"
    return "BAJA"


def compute_priority(users, zone_type, critical_site, antenna_weight, hours_open, recurrence):
    """score = 40·U + 25·Z + 20·A + 10·D + 5·R  (PLAN.md §4.5). Devuelve score, nivel y factores explicables."""
    u = min(1.0, math.log10(max(users, 1)) / 4)
    z = min(1.0, ZONE_WEIGHT.get(zone_type, 0.4) + (0.2 if critical_site else 0.0))
    a = float(antenna_weight)
    d = min(1.0, max(hours_open, 0) / 6)
    r = min(1.0, recurrence / 5)
    score = int(round(40 * u + 25 * z + 20 * a + 10 * d + 5 * r))
    return {
        "score": score,
        "level": priority_level(score),
        "factors": {"U": round(u, 3), "Z": round(z, 3), "A": round(a, 3), "D": round(d, 3), "R": round(r, 3)},
    }


def antenna_evidence(events):
    """Estado actual de antenas a partir de sus eventos (el último evento de cada antena manda)."""
    by = {}
    for e in sorted(events, key=lambda e: e["occurred_at"]):
        by.setdefault(e["antenna_id"], []).append(e)
    active = {}
    for ant, evs in by.items():
        start, cur = None, None
        for e in evs:
            if e["event_type"] in ANOMALY_WEIGHT:
                if cur is None:
                    start = e["occurred_at"]
                cur = e
            else:  # ANTENNA_RECOVERED
                start, cur = None, None
        if cur is not None:
            active[ant] = (cur, start)
    weight = max((ANOMALY_WEIGHT[c["event_type"]] for c, _ in active.values()), default=0.0)
    confirmed = any(c["event_type"] != "PREDICTIVE_RISK" for c, _ in active.values())
    first = min((s for _, s in active.values()), default=None)
    return {
        "weight": weight,
        "confirmed": confirmed,
        "antenna_ids": sorted(active),
        "first_anomaly_at": first,
    }


CRITICAL_KEYWORDS = (
    "hospital", "clínica", "clinica", "posta médica", "colegio", "escuela", "universidad",
    "comisaría", "comisaria", "bomberos", "planta", "aeropuerto", "puerto", "ambulancia", "emergencia",
)


def detect_critical_site(texts) -> bool:
    blob = " ".join(t.lower() for t in texts if t)
    return any(k in blob for k in CRITICAL_KEYWORDS)


def zone_of_report_id(report_id: str) -> str:
    """R-<zona>-<id>: la zona viaja dentro del id (lecturas puntuales baratas)."""
    parts = report_id.split("-")
    return parts[1] if len(parts) >= 3 and parts[0] == "R" else ""
