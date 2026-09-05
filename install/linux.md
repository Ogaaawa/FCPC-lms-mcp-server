# Installing on Linux

Read `../INSTALL.md` first: the Moodle side has to be done before any of this
matters, and it explains what you are installing.

A systemd unit is provided, so this is the least fiddly of the three
platforms.

---

## 1. Install

```
sudo useradd --system --create-home --home-dir /opt/moodle-mcp moodle-mcp
sudo -u moodle-mcp git clone https://github.com/Ogaaawa/FCPC-lms-mcp-server.git /opt/moodle-mcp/app
cd /opt/moodle-mcp/app
sudo -u moodle-mcp python3 -m venv venv
sudo -u moodle-mcp venv/bin/pip install -r requirements-server.txt
```

`requirements-server.txt` is what the server needs. `requirements.txt`
additionally pulls in the OpenAI client, which only the optional standalone
chat client uses.

> **Check.**
> ```
> sudo -u moodle-mcp venv/bin/python -c "import remote_server; print('ok')"
> ```

## 2. Configure

```
sudo -u moodle-mcp cp .env.example .env
sudo -u moodle-mcp chmod 600 .env
sudo -u moodle-mcp nano .env
```

```
MOODLE_URL=https://lms.example.edu
MOODLE_TOKEN=<a token for any one account>
MOODLE_SERVICE=<shortname of the restricted service, if there is one>
```

`MOODLE_TOKEN` is **not** what students use; see `../INSTALL.md`.

> **Check.**
> ```
> sudo -u moodle-mcp venv/bin/python selftest.py
> ```
> 82 checks, 0 failed. Do not expose anything on a failure.

## 3. A fixed public address

The address becomes the OAuth issuer, so it must survive a restart unchanged.
`../INSTALL.md` step 3 has the request to send to whoever holds the Cloudflare
account. Once you have the connector token:

```
sudo cloudflared service install <connector token>
systemctl status cloudflared
```

It dials out. **Nothing needs to be opened inbound.**

## 4. The server as a service

```
sudo cp deploy/moodle-mcp.service /etc/systemd/system/
sudo nano /etc/systemd/system/moodle-mcp.service
```

Set `PUBLIC_URL` to the tunnel hostname, **with no trailing slash and no
`/mcp`**:

```
Environment=PUBLIC_URL=https://ai.example.edu
```

```
sudo systemctl daemon-reload
sudo systemctl enable --now moodle-mcp
systemctl status moodle-mcp
```

The unit sets `Restart=always`, which is what makes it come back after a
crash. It deliberately does not manage the tunnel: `cloudflared` registers its
own service, so the two halves recover independently.

> **Check.** From any machine, without a token:
> ```
> python healthcheck.py https://ai.example.edu/mcp
> ```

## 5. Prove it restarts by itself

```
sudo reboot
```

> **Check.** After it comes back, without logging in or starting anything, run
> the health check again. Still HEALTHY.
>
> If not:
> ```
> systemctl status moodle-mcp cloudflared
> journalctl -u moodle-mcp -b
> ```

**An untested restart is not a restart.**

---

## Day to day

| Task | Command |
|---|---|
| Is it up | `python healthcheck.py <url> --quiet` |
| Restart the server | `sudo systemctl restart moodle-mcp` |
| Restart the tunnel | `sudo systemctl restart cloudflared` |
| Follow the log | `journalctl -u moodle-mcp -f` |

## Uninstall

```
sudo systemctl disable --now moodle-mcp
sudo rm /etc/systemd/system/moodle-mcp.service
sudo systemctl daemon-reload
sudo cloudflared service uninstall
sudo rm -rf /opt/moodle-mcp
```

Then revoke the Moodle tokens - see `../INSTALL.md`.

## Files that must not be lost

`.env`, `.oauth_key` and `.oauth_clients.json` live in `/opt/moodle-mcp/app`
and are excluded from git. Deleting `.oauth_key` signs every user out at once.
