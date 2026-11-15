"""Exportación de AGREGADOS a GCP (RF-AZ-18). Jamás incluye datos personales."""
import logging

import requests

from .. import clock, config

log = logging.getLogger("pulsored.export")
QUEUE = "analytics-export"


def build_payload(inc):
    closed = inc.get("closed_at")
    duration = None
    if closed:
        duration = int((clock.parse(closed) - clock.parse(inc["opened_at"])).total_seconds())
    return {
        "incident_id": inc["id"], "zone_id": inc["zone_id"], "problem_type": inc["problem_group"],
        "users_affected": inc["users_affected"], "priority_score": inc.get("priority_score"),
        "priority_level": inc.get("priority_level"), "status": inc["status"], "origin": inc.get("origin"),
        "opened_at": inc["opened_at"], "first_anomaly_at": inc.get("first_anomaly_at"), "closed_at": closed,
        "duration_s": duration, "detection_lag_s": inc.get("detection_lag_s"),
        "antenna_ids": inc.get("antenna_ids", []), "ai_source": inc.get("ai_source"), "updated_at": inc["updated_at"],
    }


def enqueue_export(store, queue, incident_id, zone_id):
    inc = store.get("incidents", incident_id, zone_id)
    queue.send(QUEUE, [build_payload(inc)])


def send_to_gcp(payload):
    """POST idempotente al analytics-sink. Sin GCP_URL (aún no hay sink) -> modo mock: se registra y se da por entregado."""
    url = config.env("GCP_URL")
    if not url:
        log.info("[GCP mock] %s %s", payload["incident_id"], payload["status"])
        return "mock"
    r = requests.post(url, json=payload, timeout=10, headers={
        "x-api-key": config.env("GCP_KEY"),
        "Idempotency-Key": f'{payload["incident_id"]}|{payload["status"]}|{payload["updated_at"]}',
    })
    r.raise_for_status()  # excepción -> Service Bus reintenta y luego dead-letter
    return "sent"
