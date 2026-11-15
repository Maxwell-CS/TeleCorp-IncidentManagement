"""Demo end-to-end 100 % local (memoria, sin Azure):  python scripts/simulate_local.py
Escenario: 10 usuarios reportan en Z07 -> incidente -> evento de AWS lo confirma -> 3 notificaciones -> export."""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k in ("COSMOS", "SB", "ACS_CONNECTION_STRING", "GCP_URL", "AI_URL"):
    os.environ.pop(k, None)

from pulsored import clock, messaging, queueing, store as store_mod  # noqa: E402
from pulsored.localrun import run_lifecycle  # noqa: E402
from pulsored.services import correlator, export, infra, intake, notify  # noqa: E402

clock.set_fixed(datetime(2026, 11, 15, 14, 0, tzinfo=timezone.utc))
st, q, snd = store_mod.MemoryStore(), queueing.MemoryQueue(), messaging.SimulatedSender()
store_mod.set_store(st), queueing.set_queue(q), messaging.set_sender(snd)


def step(t):
    print(f"\n== {t}")


step("AWS informa: antena A-0123 CAIDA en Z07")
print(infra.ingest_event(st, {"event_id": "evt-demo-0001", "event_type": "ANTENNA_DOWN", "antenna_id": "A-0123",
                              "zone_id": "Z07", "occurred_at": clock.iso(), "severity": "HIGH"}))
clock.advance(minutes=4)

step("10 usuarios distintos reportan 'sin datos' en Z07")
incident = None
for i in range(10):
    _, out = intake.register_report(st, {
        "idempotency_key": f"demo-{i:04d}-key", "user_document": f"DOC{i:05d}", "phone": f"+5199900{i:04d}",
        "email": f"usuario{i}@correo.pe", "zone_id": "Z07", "occurred_at": clock.iso(), "problem_type": "SIN_DATOS",
        "description": "No tengo internet desde hace una hora" + (" y la clínica cercana tampoco" if i == 3 else "")})
    incident = correlator.process_report(st, st.get("reports", out["report_id"], "Z07")) or incident
    clock.advance(seconds=5)
print("incidente:", incident["id"], "| usuarios:", incident["users_affected"])

step("Orquestación (Durable) ejecutada localmente")
polls = {"n": 0}


def on_step(name, inp, res):
    if name == "check_recovery":
        polls["n"] += 1
        if polls["n"] == 3:  # a los ~15 min AWS informa que la antena volvió
            print("  ... AWS informa ANTENNA_RECOVERED")
            infra.ingest_event(st, {"event_id": "evt-demo-0002", "event_type": "ANTENNA_RECOVERED",
                                    "antenna_id": "A-0123", "zone_id": "Z07", "occurred_at": clock.iso()})
        if polls["n"] > 1:
            return
    print(f"  {name:<22} -> {json.dumps(res, default=str)[:90]}")


result, steps = run_lifecycle(incident, on_step=on_step)
print("resultado:", result)

inc = st.get("incidents", incident["id"], "Z07")
step("Estado final")
print(f'estado={inc["status"]} prioridad={inc["priority_score"]} ({inc["priority_level"]}) origen={inc["origin"]} '
      f'ia={inc["ai_source"]} antenas={inc["antenna_ids"]} detection_lag_s={inc["detection_lag_s"]}')
print("factores:", inc["priority_factors"])
print("resumen IA:", inc["ai"]["summary"])

step("Notificador (cola -> email/SMS simulados)")
for m in q.drain("notifications"):
    notify.deliver(st, snd, m)
print("envíos simulados:", len(snd.sent), "| ejemplo:", snd.sent[0][:3])

step("Exportador a GCP (agregados, sin PII)")
payloads = q.drain("analytics-export")
print(len(payloads), "exportaciones | última:", json.dumps(payloads[-1], indent=1)[:600])
print("entrega:", export.send_to_gcp(payloads[-1]))

step("Historial del incidente")
for h in st.list_history(incident["id"]):
    print(f'  {h["ts"][11:19]} {h["actor"]:<8} {h["action"]:<20} {h["from"]}->{h["to"]} {h["note"]}')
