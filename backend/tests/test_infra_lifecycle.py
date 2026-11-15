import json

import pytest
from conftest import send_reports
from pulsored import clock, lifecycle
from pulsored.localrun import run_lifecycle
from pulsored.services import export, incidents, infra, notify


def ev(i=1, typ="ANTENNA_DOWN", zone="Z07", ant="A-0123", **kw):
    e = {"event_id": f"evt-{i:06d}", "event_type": typ, "antenna_id": ant, "zone_id": zone,
         "occurred_at": clock.iso(), "severity": "HIGH"}
    e.update(kw)
    return e


def incident(env, n=10, zone="Z07"):
    return send_reports(env.store, n, zone=zone)[0]


# ------------------------------------------------------------ eventos de AWS
def test_infra_event_idempotent_5_times(env):
    codes = [infra.ingest_event(env.store, ev())[0] for _ in range(5)]
    assert codes == [202, 200, 200, 200, 200]
    assert len(env.store.data["infra_events"]) == 1


def test_infra_event_validation(env):
    assert infra.ingest_event(env.store, ev(event_type="OTRA_COSA"))[0] == 400
    assert infra.ingest_event(env.store, ev(zone="Z99"))[0] == 400
    assert infra.ingest_event(env.store, {"event_id": "x"})[0] == 400


def test_infra_event_raises_priority_and_signals(env):
    inc = incident(env)
    before = env.store.get("incidents", inc["id"], "Z07")["priority_score"]
    e = ev()
    infra.ingest_event(env.store, e)
    signals = infra.link_event(env.store, env.store.get("infra_events", e["event_id"], "Z07"))
    after = env.store.get("incidents", inc["id"], "Z07")
    assert after["priority_score"] > before
    assert after["origin"] == "BOTH" and after["antenna_ids"] == ["A-0123"]
    assert signals == [inc["id"]]
    hist = env.store.list_history(inc["id"])
    assert any(h["action"] == "INFRA_EVENT" for h in hist)
    assert any(h["action"] == "PRIORITY_CHANGED" for h in hist)


def test_predictive_event_does_not_signal(env):
    inc = incident(env)
    e = ev(typ="PREDICTIVE_RISK")
    infra.ingest_event(env.store, e)
    assert infra.link_event(env.store, e) == []


def test_detection_lag_positive_when_antenna_first(env):
    infra.ingest_event(env.store, ev(occurred_at=clock.iso()))
    clock.advance(minutes=4)
    inc = incident(env)
    assert env.store.get("incidents", inc["id"], "Z07")["detection_lag_s"] > 0


# ------------------------------------------------------------ ciclo de vida
def test_lifecycle_happy_path_with_infra_confirmation(env):
    infra.ingest_event(env.store, ev())            # la antena ya reportó la caída
    inc = incident(env)
    result, steps = run_lifecycle(inc)
    assert result["outcome"] == "CERRADA"
    final = env.store.get("incidents", inc["id"], "Z07")
    assert final["status"] == "CERRADA" and final["closed_at"]
    assert final["ai_source"] == "rules" and final["ai"]["summary"]
    assert "check_infra" in steps and "enqueue_notifications" in steps


def test_lifecycle_recovers_when_aws_reports_recovered(env):
    infra.ingest_event(env.store, ev(1))
    inc = incident(env)
    polls = {"n": 0}

    def on_step(name, inp, res):
        if name == "check_recovery":
            polls["n"] += 1
            if polls["n"] == 2:
                infra.ingest_event(env.store, ev(2, typ="ANTENNA_RECOVERED"))
            if polls["n"] <= 2:
                assert res is False   # mientras la antena siga caída o hubo reportes recientes
    start = clock.now()
    result, _ = run_lifecycle(inc, on_step=on_step)
    assert result["outcome"] == "CERRADA"
    assert (clock.now() - start).total_seconds() < 6 * 3600   # no esperó a que caducara la ventana de 48 h


def test_lifecycle_reopens_on_new_reports_during_cooldown(env):
    infra.ingest_event(env.store, ev(1))
    inc = incident(env)
    state = {"reopened": False, "recovered": False}

    def on_step(name, inp, res):
        if name == "check_recovery" and not state["recovered"]:
            state["recovered"] = True
            infra.ingest_event(env.store, ev(2, typ="ANTENNA_RECOVERED"))     # AWS: la antena volvió
        if name == "enqueue_notifications" and inp["stage"] == "RESTABLECIDO" and not state["reopened"]:
            state["reopened"] = True
            clock.advance(minutes=1)
            send_reports(env.store, 1, start=500)         # reporte nuevo durante el cooldown (se enlaza al abierto)

    # 2.º ciclo: sin evidencia de antena -> espera al operador, que confirma
    result, steps = run_lifecycle(inc, events=["CONFIRMAR"], on_step=on_step)
    assert result["outcome"] == "CERRADA"
    assert steps.count("enqueue_notifications") == 6          # 3 etapas x 2 ciclos (hubo reapertura)
    final = env.store.get("incidents", inc["id"], "Z07")
    assert final["users_affected"] == 11
    assert [h["to"] for h in env.store.list_history(inc["id"]) if h["action"] == "STATUS_CHANGED"].count("EN_REVISION") == 2


def test_lifecycle_waits_for_operator_and_discard(env):
    inc = incident(env)                             # sin evidencia de antena
    result, _ = run_lifecycle(inc, events=["DESCARTAR"])
    assert result["outcome"] == "FALSO_POSITIVO"
    final = env.store.get("incidents", inc["id"], "Z07")
    assert final["status"] == "CERRADA" and final["close_reason"] == "FALSO_POSITIVO"


def test_lifecycle_operator_confirm_then_recovery(env):
    inc = incident(env)
    result, _ = run_lifecycle(inc, events=["CONFIRMAR"])
    assert result["outcome"] == "CERRADA"
    h = [x["action"] for x in env.store.list_history(inc["id"])]
    assert h.count("STATUS_CHANGED") >= 4          # EN_REVISION, EN_ATENCION, SOLUCIONADA, CERRADA


def test_lifecycle_operator_timeout_escalates(env, monkeypatch):
    inc = incident(env)
    seen = []
    # sin eventos disponibles -> gana el timer: alerta y luego espera la decisión (que falla en el guion)
    with pytest.raises(RuntimeError):
        run_lifecycle(inc, events=[], on_step=lambda n, i, r: seen.append(n))
    assert "alert_operator" in seen


def test_notifications_three_stages_one_per_user(env):
    infra.ingest_event(env.store, ev())
    inc = incident(env)
    run_lifecycle(inc)
    msgs = env.queue.messages["notifications"]
    stages = {m["stage"] for m in msgs}
    assert stages == {"EVALUANDO", "IDENTIFICADA", "RESTABLECIDO"}
    assert len(msgs) == 30                          # 10 usuarios x 3 etapas
    assert all("@" not in json.dumps(m) and "phone" not in m and "email" not in m for m in msgs)


def test_notifier_is_idempotent(env):
    inc = incident(env)
    notify.enqueue_notifications(env.store, env.queue, inc["id"], "Z07", "EVALUANDO")
    msgs = env.queue.drain("notifications")
    for m in msgs:
        assert notify.deliver(env.store, env.sender, m) == "sent"
    for m in msgs:                                   # reintento tras fallo: no repite
        assert notify.deliver(env.store, env.sender, m) == "duplicate"
    emails = [s for s in env.sender.sent if s[0] == "EMAIL_SIMULATED"]
    assert len(emails) == 10


def test_export_has_no_pii_and_is_aggregate(env):
    inc = incident(env)
    export.enqueue_export(env.store, env.queue, inc["id"], "Z07")
    payload = env.queue.drain("analytics-export")[0]
    blob = json.dumps(payload)
    for pii in ("DOC0", "+51999", "@test.pe", "user_key", "description"):
        assert pii not in blob
    assert payload["users_affected"] == 10 and payload["incident_id"] == inc["id"]
    assert export.send_to_gcp(payload) == "mock"


def test_gcp_down_falls_back_to_rules(env, monkeypatch):
    monkeypatch.setenv("AI_URL", "http://127.0.0.1:9/nada")
    monkeypatch.setenv("GCP_KEY", "k")
    inc = incident(env)
    out = lifecycle.ai_enrich({"incident_id": inc["id"], "zone_id": "Z07"})
    assert out["ai_source"] == "rules"


def test_operator_actions_and_invalid_transition(env):
    inc = incident(env)
    iid = inc["id"]
    assert incidents.apply_action(env.store, iid, {"action": "CAMBIAR_ESTADO", "to": "SOLUCIONADA"})[0] == 409
    assert any(h["action"] == "TRANSITION_REJECTED" for h in env.store.list_history(iid))
    code, _, sig = incidents.apply_action(env.store, iid, {"action": "CONFIRMAR"})
    assert (code, sig) == (202, "CONFIRMAR")
    assert incidents.apply_action(env.store, iid, {"action": "???"})[0] == 400
    assert incidents.get_incident(env.store, "INC-Z07-DATOS-1")[0] == 404
    code, detail = incidents.get_incident(env.store, iid)
    assert code == 200 and "user_document" not in json.dumps(detail) and "phone" not in json.dumps(detail)


def test_incident_list_sorted_by_priority(env):
    send_reports(env.store, 10, zone="Z07")                    # residencial
    send_reports(env.store, 10, zone="Z11", start=100)         # salud
    items = incidents.list_incidents(env.store)[1]["items"]
    assert [i["zone_id"] for i in items] == ["Z11", "Z07"]
