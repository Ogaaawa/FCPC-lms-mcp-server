# Deploying on a Linux host

For the full picture - Moodle prerequisites, what students do, monitoring and
shutdown - read `../DEPLOYMENT.md`. This directory holds the files that make it
survive a reboot.

| File | Purpose |
|---|---|
| `moodle-mcp.service` | systemd unit for the MCP server |
| `windows.md` | The same thing on Windows: scheduled task, sleep, updates |

## The two halves

The service has two moving parts, and they are installed separately.

```
cloudflared  (its own service)   the public address
    |
    v
remote_server.py  (this unit)    the MCP server, on 127.0.0.1:8000
```

`cloudflared service install <token>` registers the tunnel as a service by
itself, so the unit here only has to run the Python side.

## Use a named tunnel, not a quick one

`start-server.sh` uses a quick tunnel, which issues a **new address every
time**. The address becomes the OAuth issuer, so changing it invalidates every
student's connector. That is fine for a demo and wrong for anything running
for a week.

`fcpc.edu.ph` is already on Cloudflare, so a named tunnel on the school's own
domain costs nothing. `../DEPLOYMENT.md` has the request to send.

## After installing

```
sudo systemctl enable --now moodle-mcp
systemctl status moodle-mcp
journalctl -u moodle-mcp -f
```

Then, from any machine:

```
python healthcheck.py https://ai.fcpc.edu.ph/mcp
```

## Restart it once, on purpose

```
sudo reboot
```

and confirm the health check passes again without anybody touching it. An
untested restart is not a restart.

## Files that must not be lost

`.env`, `.oauth_key` and `.oauth_clients.json` live in the working directory
and are excluded from git. Deleting `.oauth_key` signs every user out.
