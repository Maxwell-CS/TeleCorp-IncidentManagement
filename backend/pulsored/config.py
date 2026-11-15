"""Configuración leída del entorno en cada llamada (así las pruebas pueden cambiarla)."""
import os


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def users_threshold() -> int:
    return int(env("USERS_THRESHOLD", "10"))


def window_hours() -> int:
    return int(env("WINDOW_HOURS", "24"))


def evidence_window_hours() -> int:
    return int(env("EVIDENCE_WINDOW_HOURS", "48"))


def timers() -> dict:
    return {
        "operator_wait_min": int(env("OPERATOR_WAIT_MIN", "120")),
        "recovery_poll_min": int(env("RECOVERY_POLL_MIN", "5")),
        "cooldown_min": int(env("COOLDOWN_MIN", "30")),
        "quiet_min": int(env("RECOVERY_QUIET_MIN", "15")),
    }


COSMOS_DB = "pulsored"


def cosmos_db() -> str:
    return env("COSMOS_DB", COSMOS_DB)
