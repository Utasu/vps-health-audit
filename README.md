# VPS Health Audit

A safe, read-only Linux health auditor that produces a compact Markdown or JSON report without installing an agent or changing the server.

## Checks

- Available memory and swap
- 1/5/15-minute load normalized by CPU count
- Disk usage for one or more selected paths
- Failed systemd units, reported as a count by default
- Count of listening TCP/UDP sockets without exposing endpoint details
- Host platform and uptime metadata

Thresholds are deliberately simple and visible in the source. The tool does not restart services, change firewall rules, delete files, or claim that a warning has one automatic fix.

## Quickstart

```bash
git clone https://github.com/Utasu/vps-health-audit && cd vps-health-audit
python3 vps_audit.py                                    # Markdown to stdout
python3 vps_audit.py --format json                      # machine-readable
python3 vps_audit.py --path / --path /var --output audit.md
```

Exit code `2` means at least one critical check was found. Warnings keep exit code `0`, making the tool suitable for an initial report before a human-approved remediation plan.

## Example report

Real output, with the hostname replaced:

```markdown
# VPS Health Audit

- Generated: `2026-09-04T09:02:47+00:00`
- Host: `web-01`
- Overall: **OK**

| Check | Status | Summary |
|---|---|---|
| `memory` | ✅ ok | 51.8% available (3.0 GiB of 5.8 GiB) |
| `load` | ✅ ok | load 0.70/0.61/0.85 across 4 CPU(s) |
| `disk:/` | ✅ ok | 72.3% used, 30.5 GiB free |
| `failed-units` | ✅ ok | 0 failed systemd unit(s) |
| `listening-sockets` | ✅ ok | 27 listening TCP/UDP socket(s) |
```

## What the report withholds

Reports get pasted into tickets and chat, so the defaults avoid describing the host's
attack surface: listening sockets are counted rather than listed, and failed unit
names are hidden behind `--show-units`. The hostname and kernel version are included
because a health report needs to identify its subject — redact them before sharing a
report outside the operating team.

## Test

```bash
python3 -m unittest discover -s tests -v
```

## Example client delivery

1. Run the auditor with read-only access.
2. Review the generated report with the client.
3. Agree on exact remediation and rollback steps.
4. Make only approved changes.
5. Re-run the same report as before/after evidence.
