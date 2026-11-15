"""Simula a AWS enviando eventos de antena a Azure:
  python scripts/aws_simulator.py --url https://<func>.azurewebsites.net --key <function-key> --zone Z07 --type ANTENNA_DOWN
Sirve para probar el contrato de AZURE2.md §3.2 (y para que el equipo de AWS vea la respuesta esperada)."""
import argparse
import json
import uuid
from datetime import datetime, timezone

import requests

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://localhost:7071")
ap.add_argument("--key", default="")
ap.add_argument("--zone", default="Z07")
ap.add_argument("--antenna", default="A-0123")
ap.add_argument("--type", default="ANTENNA_DOWN",
                choices=["ANTENNA_DISABLED", "ANTENNA_DOWN", "ANTENNA_SATURATED", "ANTENNA_RECOVERED", "PREDICTIVE_RISK"])
ap.add_argument("--repeat", type=int, default=1, help="reenvía el MISMO evento n veces (prueba de idempotencia)")
a = ap.parse_args()

ev = {"event_id": str(uuid.uuid4()), "event_type": a.type, "antenna_id": a.antenna, "zone_id": a.zone,
      "occurred_at": datetime.now(timezone.utc).isoformat(), "severity": "HIGH"}
for i in range(a.repeat):
    r = requests.post(f"{a.url}/api/infra/events", json=ev, headers={"x-functions-key": a.key}, timeout=15)
    print(i + 1, r.status_code, r.text)
print(json.dumps(ev))
