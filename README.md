# VPS Health Audit

A safe, read-only Linux health auditor that produces a compact Markdown or JSON report without installing an agent or changing the server.

## Checks

- Available memory and swap
- 1/5/15-minute load normalized by CPU count
- Disk usage for one or more selected paths
- Failed systemd units
- Count of listening TCP/UDP sockets without exposing endpoint details
- Host platform and uptime metadata

Thresholds are deliberately simple and visible in the source. The tool does not restart services, change firewall rules, delete files, or claim that a warning has one automatic fix.

## Run

```bash
python3 vps_audit.py
python3 vps_audit.py --format json
python3 vps_audit.py --path / --path /var --output audit.md
```

Exit code `2` means at least one critical check was found. Warnings keep exit code `0`, making the tool suitable for an initial report before a human-approved remediation plan.

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
