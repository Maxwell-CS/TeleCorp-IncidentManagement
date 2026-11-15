from conftest import body, send_reports
from pulsored import clock
from pulsored.services import correlator, intake, reports


def test_validation_rejects_bad_input(env):
    for bad in (
        body(1, problem_type="XXX"),
        body(1, zone_id="Z99"),
        body(1, phone="abc"),
        body(1, description="x" * 1001),
        {**body(1), "extra": 1},
    ):
        assert intake.register_report(env.store, bad)[0] == 400
    b = body(1)
    del b["description"]
    assert intake.register_report(env.store, b)[0] == 400
    assert intake.register_report(env.store, "no-objeto")[0] == 400


def test_idempotent_intake_same_key_5_times(env):
    ids = set()
    codes = []
    for _ in range(5):
        code, out = intake.register_report(env.store, body(1))
        codes.append(code)
        ids.add(out["report_id"])
    assert codes == [202, 200, 200, 200, 200]
    assert len(ids) == 1
    assert len(env.store.data["reports"]) == 1
    assert next(iter(ids)).startswith("R-Z07-")


def test_nine_users_no_incident(env):
    assert send_reports(env.store, 9) == []
    assert env.store.data["incidents"] == {}


def test_ten_reports_same_user_no_incident(env):
    for i in range(10):
        b = body(0, idempotency_key=f"idem-same-user-{i:04d}")
        code, out = intake.register_report(env.store, b)
        assert code == 202
        assert correlator.process_report(env.store, env.store.get("reports", out["report_id"], "Z07")) is None


def test_ten_users_two_zones_no_incident(env):
    send_reports(env.store, 5, zone="Z07")
    assert send_reports(env.store, 5, zone="Z04", start=100) == []


def test_ten_users_open_exactly_one_incident(env):
    created = send_reports(env.store, 10)
    assert len(created) == 1
    inc = created[0]
    assert inc["users_affected"] == 10 and inc["status"] == "REGISTRADA"
    assert inc["id"].startswith("INC-Z07-DATOS-")
    assert all(r["incident_id"] == inc["id"] for r in env.store.data["reports"].values())


def test_eleventh_user_links_to_open_incident(env):
    send_reports(env.store, 10)
    assert send_reports(env.store, 1, start=10) == []   # no crea 2.º incidente
    assert len(env.store.data["incidents"]) == 1
    inc = next(iter(env.store.data["incidents"].values()))
    assert inc["users_affected"] == 11


def test_reprocessing_same_report_is_idempotent(env):
    send_reports(env.store, 10)
    inc = next(iter(env.store.data["incidents"].values()))
    for r in env.store.data["reports"].values():
        assert correlator.process_report(env.store, r) is None
    assert len(env.store.data["incidents"]) == 1
    assert env.store.count_incident_users(inc["id"]) == 10


def test_window_24h_sliding(env):
    # 9 usuarios, luego el 10.º a las 24 h 01 min del 1.º: la ventana ya no contiene al 1.º
    send_reports(env.store, 9)
    clock.advance(hours=24, minutes=1)
    assert send_reports(env.store, 1, start=50) == []
    assert env.store.data["incidents"] == {}


def test_ten_users_within_23h59_make_incident(env):
    send_reports(env.store, 5)
    clock.advance(hours=23, minutes=50)
    assert len(send_reports(env.store, 5, start=50)) == 1


def test_different_problem_group_does_not_mix(env):
    send_reports(env.store, 5, ptype="SIN_DATOS")
    assert send_reports(env.store, 5, start=50, ptype="LLAMADAS") == []


def test_public_report_hides_pii_and_shows_incident_status(env):
    send_reports(env.store, 10)
    rid = next(iter(env.store.data["reports"].values()))["id"]
    code, out = reports.get_public_report(env.store, rid)
    assert code == 200 and out["incident"]["status"] == "REGISTRADA"
    blob = str(out)
    for pii in ("DOC0", "+51999", "@test.pe", "user_key"):
        assert pii not in blob
    assert reports.get_public_report(env.store, "R-Z07-NOEXISTE")[0] == 404


def test_report_status_transitions(env):
    _, out = intake.register_report(env.store, body(1))
    rid = out["report_id"]
    assert reports.change_report_status(env.store, rid, "SOLUCIONADA", "x")[0] == 409  # inválida
    hist = env.store.list_history(rid)
    assert any(h["action"] == "TRANSITION_REJECTED" for h in hist)    # rechazada y registrada
    assert reports.change_report_status(env.store, rid, "EN_REVISION", "ok")[0] == 200
