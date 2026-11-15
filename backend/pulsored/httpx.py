"""Utilidades HTTP independientes del framework (probables sin Azure)."""
import hmac
import json

from . import config


def operator_ok(headers) -> bool:
    expected = config.env("OPERATOR_TOKEN")
    got = headers.get("x-operator-token", "") if headers else ""
    return bool(expected) and bool(got) and hmac.compare_digest(got, expected)


def unauthorized():
    return 401, {"error": "UNAUTHORIZED", "message": "Token de operador requerido"}


def dumps(body) -> str:
    return json.dumps(body, default=str, ensure_ascii=False)
