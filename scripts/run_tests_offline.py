"""Corre la suite completa sin red, sin secretos y con una base SQLite temporal.

Uso (desde la raíz del repo):
    python scripts/run_tests_offline.py [-v]

- Pisa con valores vacíos las variables con claves reales (Gemini, SMTP, n8n,
  Telegram, Hunter.io) para que ni el entorno ni un `.env` se carguen.
- Apunta DATABASE_PATH a un archivo temporal que se borra al terminar.
- Bloquea cualquier conexión o resolución DNS que no sea a loopback: un test
  que intente salir a internet falla en vez de contactar un servicio real.
"""

import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECRET_VARS = [
    "EROS_API_KEY",
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "HUNTER_IO_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USER_ID",
    "N8N_APPLICATION_WEBHOOK_URL",
    "N8N_WEBHOOK_SECRET",
    "SMTP_HOST",
    "SMTP_USER",
    "SMTP_PASS",
    "CV_LINK_SECRET",
]

LOOPBACK = {"127.0.0.1", "::1", "localhost", ""}


class NetworkBlockedError(OSError):
    pass


def _host_of(address) -> str:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


def block_network() -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and _host_of(address) not in LOOPBACK:
            raise NetworkBlockedError(f"Red bloqueada en tests: connect a {address!r}")
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and _host_of(address) not in LOOPBACK:
            raise NetworkBlockedError(f"Red bloqueada en tests: connect a {address!r}")
        return real_connect_ex(self, address)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host is not None and str(host) not in LOOPBACK:
            raise NetworkBlockedError(f"Red bloqueada en tests: DNS de {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    def guarded_gethostbyname(host):
        if str(host) not in LOOPBACK:
            raise NetworkBlockedError(f"Red bloqueada en tests: DNS de {host!r}")
        return "127.0.0.1"

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.getaddrinfo = guarded_getaddrinfo
    socket.gethostbyname = guarded_gethostbyname


def main() -> int:
    tmp_dir = tempfile.TemporaryDirectory(prefix="eros-tests-")
    for var in SECRET_VARS:
        os.environ[var] = ""
    os.environ["DATABASE_PATH"] = str(Path(tmp_dir.name) / "eros-test.db")
    os.environ["ENV"] = "test"
    os.environ["PERIODIC_SCAN_ENABLED"] = "false"

    sys.path.insert(0, str(ROOT / "src"))
    # Sin .env: los tests corren desde un directorio temporal.
    os.chdir(tmp_dir.name)
    block_network()

    verbosity = 2 if "-v" in sys.argv else 1
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    try:
        tmp_dir.cleanup()
    except Exception:
        pass
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
