"""
Alpaca CLI detection & health-check (Milestone 3).

The core application must never depend on the CLI being present — it is
an optional automation/inspection surface. This module only shells out
for detection and read-only diagnostics.
"""
from __future__ import annotations

import shutil
import subprocess

INSTALL_HINT = (
    "Alpaca CLI not found. Install it with your platform's package manager "
    "or see https://docs.alpaca.markets for the current install method. "
    "OptionSentinel runs fine without it — the CLI is an optional automation layer."
)


def _run(cmd: list[str], timeout: float = 5.0) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        output = (result.stdout or "").strip() or (result.stderr or "").strip()
        return result.returncode == 0, output
    except FileNotFoundError:
        return False, "binary not found"
    except subprocess.TimeoutExpired:
        return False, "command timed out"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def cli_health_check() -> dict[str, str]:
    binary = shutil.which("alpaca")
    if binary is None:
        return {
            "ALPACA_CLI_PRESENT": "NO",
            "ALPACA_CLI_VERSION": "N/A",
            "ALPACA_CLI_DOCTOR": "N/A",
            "ALPACA_CLI_HINT": INSTALL_HINT,
        }

    status: dict[str, str] = {"ALPACA_CLI_PRESENT": f"YES ({binary})"}

    ok, out = _run(["alpaca", "version"])
    status["ALPACA_CLI_VERSION"] = out if ok else f"FAIL: {out}"

    ok, out = _run(["alpaca", "doctor"])
    status["ALPACA_CLI_DOCTOR"] = out if ok else f"UNAVAILABLE: {out}"

    return status
