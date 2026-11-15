"""Carga el catálogo de zonas en Cosmos (para que otras nubes/consultas lo vean). Uso:
  $env:COSMOS = "<connection string>"; python scripts/seed_zones.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsored.store import CosmosStore, ZONES  # noqa: E402

s = CosmosStore()
for z in ZONES.values():
    s.upsert("zones", {**z, "zone_id": z["id"]})
print(f"{len(ZONES)} zonas cargadas")
