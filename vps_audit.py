#!/usr/bin/env python3
"""Generate a read-only Linux VPS health report in Markdown or JSON."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


UTC = dt.timezone.utc
# Distinct weights only: with a tie, max() returns whichever check happened to run
# first, so the same machine state could report "warning" once and "unavailable" the
# next time. A check that could not run ranks below a real warning.
STATUS_ORDER = {"ok": 0, "unavailable": 1, "warning": 2, "critical": 3}


def now_iso() -> str:
    return dt.datetime.now(UTC).replace(microsecond=0).isoformat()


def human_bytes(value: int) -> str:
    amount = float(value)
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or suffix == "TiB":
            return f"{amount:.1f} {suffix}"
        amount /= 1024
    return f"{amount:.1f} TiB"


def parse_meminfo(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        fields = raw.strip().split()
        if not fields or not fields[0].isdigit():
            continue
        multiplier = 1024 if len(fields) > 1 and fields[1].lower() == "kb" else 1
        values[key] = int(fields[0]) * multiplier
    return values


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    summary: str
    details: dict[str, Any]


def disk_check(path: Path, total: int, used: int, free: int) -> Check:
    # Match df: its Use% is used/(used+available) and excludes the root-reserved
    # blocks, so used/total would read a few points lower than the number the
    # operator sees in their terminal.
    usable = used + free
    percent = (used / usable * 100) if usable else 100.0
    status = "critical" if percent >= 92 else "warning" if percent >= 80 else "ok"
    return Check(
        name=f"disk:{path}",
        status=status,
        summary=f"{percent:.1f}% used, {human_bytes(free)} free",
        details={"path": str(path), "total_bytes": total, "used_bytes": used, "free_bytes": free},
    )


def memory_check(values: dict[str, int]) -> Check:
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    ratio = (available / total * 100) if total else 0.0
    status = "critical" if ratio < 7 else "warning" if ratio < 15 else "ok"
    return Check(
        name="memory",
        status=status,
        summary=f"{ratio:.1f}% available ({human_bytes(available)} of {human_bytes(total)})",
        details={
            "total_bytes": total,
            "available_bytes": available,
            "swap_total_bytes": values.get("SwapTotal", 0),
            "swap_free_bytes": values.get("SwapFree", 0),
        },
    )


def load_check(load: tuple[float, float, float], cpus: int) -> Check:
    cpus = max(1, cpus)
    normalized = load[0] / cpus
    status = "critical" if normalized >= 2.0 else "warning" if normalized >= 1.0 else "ok"
    return Check(
        name="load",
        status=status,
        summary=f"load {load[0]:.2f}/{load[1]:.2f}/{load[2]:.2f} across {cpus} CPU(s)",
        details={"load_1m": load[0], "load_5m": load[1], "load_15m": load[2], "cpus": cpus},
    )


def run_lines(command: list[str], timeout: int = 5) -> tuple[list[str], str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return [], type(error).__name__
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    error = "" if result.returncode == 0 else f"exit {result.returncode}"
    return lines, error


def failed_units_check(show_units: bool = False) -> Check:
    """Report failed units, by count only unless the operator opts in.

    Unit names describe what the host actually runs, which is the same class of
    infrastructure detail the listening-socket check deliberately withholds. Reports
    get pasted into tickets and chats, so the safe default is a count.
    """
    lines, error = run_lines(
        ["systemctl", "list-units", "--failed", "--no-legend", "--no-pager", "--plain"]
    )
    if error:
        return Check("failed-units", "unavailable", error, {"count": 0})
    units = [line.split()[0] for line in lines if line.split()]
    status = "warning" if units else "ok"
    summary = f"{len(units)} failed systemd unit(s)"
    details: dict[str, Any] = {"count": len(units)}
    if show_units:
        details["units"] = units[:20]
    else:
        details["redacted"] = "unit names hidden; pass --show-units to include them"
    return Check("failed-units", status, summary, details)


def listening_sockets_check() -> Check:
    lines, error = run_lines(["ss", "-H", "-lntu"])
    if error:
        return Check("listening-sockets", "unavailable", error, {"count": 0})
    # Only report a count. Raw endpoints may contain infrastructure details.
    return Check(
        "listening-sockets",
        "ok",
        f"{len(lines)} listening TCP/UDP socket(s)",
        {"count": len(lines)},
    )


def collect(paths: list[Path], show_units: bool = False) -> dict[str, Any]:
    checks: list[Check] = []
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
        checks.append(memory_check(parse_meminfo(meminfo)))
    except OSError as error:
        checks.append(Check("memory", "unavailable", type(error).__name__, {}))

    try:
        checks.append(load_check(os.getloadavg(), os.cpu_count() or 1))
    except OSError as error:
        checks.append(Check("load", "unavailable", type(error).__name__, {}))

    for path in paths:
        try:
            usage = shutil.disk_usage(path)
            checks.append(disk_check(path, usage.total, usage.used, usage.free))
        except OSError as error:
            checks.append(Check(f"disk:{path}", "unavailable", type(error).__name__, {}))

    checks.extend([failed_units_check(show_units), listening_sockets_check()])
    overall = max(checks, key=lambda check: STATUS_ORDER[check.status]).status if checks else "unavailable"
    try:
        uptime_seconds = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        uptime_seconds = None
    return {
        "schema_version": 1,
        "generated_at": now_iso(),
        "overall_status": overall,
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "uptime_seconds": uptime_seconds,
        },
        "checks": [asdict(check) for check in checks],
    }


def render_markdown(report: dict[str, Any]) -> str:
    icons = {"ok": "✅", "warning": "⚠️", "critical": "🚨", "unavailable": "❔"}
    lines = [
        "# VPS Health Audit",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Host: `{report['host']['hostname']}`",
        f"- Overall: **{report['overall_status'].upper()}**",
        "",
        "| Check | Status | Summary |",
        "|---|---|---|",
    ]
    for check in report["checks"]:
        summary = str(check["summary"]).replace("|", "\\|")
        lines.append(
            f"| `{check['name']}` | {icons.get(check['status'], '•')} {check['status']} | {summary} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "This report is read-only. A warning is evidence to investigate, not permission to restart, delete, or reconfigure services.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", action="append", type=Path, dest="paths", default=[])
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument(
        "--show-units",
        action="store_true",
        help="include failed unit names (they reveal what this host runs)",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = collect(args.paths or [Path("/")], show_units=args.show_units)
    rendered = (
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.format == "json"
        else render_markdown(report)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 2 if report["overall_status"] == "critical" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
