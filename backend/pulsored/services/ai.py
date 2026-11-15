"""Enriquecimiento con IA (Gemini vía endpoint de GCP) con degradación elegante a reglas (RF IA)."""
import logging

import requests

from .. import config, domain

log = logging.getLogger("pulsored.ai")

STAGE_TEXT = {
    "EVALUANDO": "Estamos evaluando una posible falla de servicio en tu zona ({zone}). Tu reporte {report_id} está en revisión.",
    "IDENTIFICADA": "Confirmamos una incidencia en tu zona ({zone}) y nuestro equipo ya trabaja en resolverla. Reporte {report_id}.",
    "RESTABLECIDO": "El servicio en tu zona ({zone}) fue restablecido. Si persiste el problema, responde con un nuevo reporte. Reporte {report_id}.",
}


def rules_enrich(incident, reports, zone):
    texts = [r.get("description", "") for r in reports[:200]]
    critical = domain.detect_critical_site(texts) or bool(zone and zone.get("critical_sites") and
                                                          domain.detect_critical_site(texts))
    group = incident["problem_group"]
    urgency = "ALTA" if critical or group == "TOTAL" else "MEDIA"
    summary = (f'{incident["users_affected"]} usuarios reportan problemas de {group} en '
               f'{(zone or {}).get("name", incident["zone_id"])}'
               + (" con posible afectación a un sitio crítico." if critical else "."))
    return {"summary": summary, "critical_site": critical, "urgency": urgency,
            "notification_text": dict(STAGE_TEXT), "ai_source": "rules"}


def enrich(incident, reports, zone):
    """Intenta Gemini (AI_URL de GCP); ante cualquier fallo cae a reglas. Nunca envía datos personales."""
    url = config.env("AI_URL")
    if url:
        try:
            payload = {
                "incident_id": incident["id"], "zone_id": incident["zone_id"], "zone_type": (zone or {}).get("type"),
                "problem_group": incident["problem_group"], "users_affected": incident["users_affected"],
                "descriptions": [r.get("description", "")[:300] for r in reports[:50]],
            }
            r = requests.post(url, json=payload, timeout=10, headers={"x-api-key": config.env("GCP_KEY")})
            r.raise_for_status()
            out = r.json()
            out.setdefault("notification_text", dict(STAGE_TEXT))
            out["ai_source"] = "gemini"
            return out
        except Exception as e:  # noqa: BLE001 - degradación elegante
            log.warning("IA no disponible (%s); uso reglas", e)
    return rules_enrich(incident, reports, zone)
