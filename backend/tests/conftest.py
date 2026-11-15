import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
for k in ("COSMOS", "SB", "ACS_CONNECTION_STRING", "ACS_SENDER", "GCP_URL", "AI_URL"):
    os.environ.pop(k, None)
os.environ["OPERATOR_TOKEN"] = "tok-test"

from pulsored import clock, messaging, queueing, store as store_mod  # noqa: E402
from pulsored.services import correlator, intake  # noqa: E402


@pytest.fixture(autouse=True)
def env():
    clock.set_fixed(datetime(2026, 11, 15, 14, 0, tzinfo=timezone.utc))
    s, q, snd = store_mod.MemoryStore(), queueing.MemoryQueue(), messaging.SimulatedSender()
    store_mod.set_store(s)
    queueing.set_queue(q)
    messaging.set_sender(snd)
    yield type("Env", (), {"store": s, "queue": q, "sender": snd})
    clock.set_fixed(None)


def body(i, zone="Z07", ptype="SIN_DATOS", **kw):
    b = {
        "idempotency_key": f"idem-{zone}-{i:04d}-xx", "user_document": f"DOC{i:05d}", "phone": f"+5199900{i:04d}",
        "email": f"u{i}@test.pe", "zone_id": zone, "occurred_at": clock.iso(), "problem_type": ptype,
        "description": f"Sin internet desde hace una hora ({i})",
    }
    b.update(kw)
    return b


def send_reports(st, n, zone="Z07", start=0, ptype="SIN_DATOS", **kw):
    """Registra n reportes de n usuarios distintos y pasa cada uno por el correlador (como el change feed)."""
    created = []
    for i in range(start, start + n):
        code, out = intake.register_report(st, body(i, zone, ptype, **kw))
        assert code == 202, out
        r = st.get("reports", out["report_id"], zone)
        inc = correlator.process_report(st, r)
        if inc:
            created.append(inc)
        clock.advance(seconds=1)
    return created
