# Installation runbook

For the person putting this on a server. Follow it in order; each step ends
with a check, and a failed check means stop rather than continue.

Roughly 45 minutes if the Moodle side is already done, plus waiting on
whoever holds the Cloudflare account.

| Document | For |
|---|---|
| **This file** | Installing on a server |
| `ADMIN_REQUEST.md` | What to ask the Moodle administrator for |
| `DEPLOYMENT.md` | Running it day to day, and shutting it down |
| `TEST_PLAN.md` | Proving it works, as a student and as a teacher |
| `README.md` | What the service is, and its known limitations |

---

## 0. What you are installing

One Python process that answers MCP requests from Claude, and a Cloudflare
connector that gives it a public address.

```
students' Claude ──HTTPS──▶ Cloudflare ──tunnel──▶ this server ──▶ Moodle
```

- **No inbound port and no public IP.** The connector dials out
- **No database.** One encryption key on disk is the entire server-side state
- **No Moodle server access.** It uses the public web service API, like any
  other client
- **Read-only.** Nothing submits, posts, enrols, grades or messages

It runs as an unprivileged user. Root is needed only to install the services.

---

## 1. Moodle side

This must be done first. It is not something the server can work around.

**1.1** An external service exists holding these thirteen functions, all
read-only:

```
core_webservice_get_site_info            mod_assign_get_assignments
core_enrol_get_users_courses             mod_quiz_get_quizzes_by_courses
core_course_get_contents                 mod_quiz_get_user_attempts
core_course_get_courses_by_field         mod_forum_get_forums_by_courses
core_calendar_get_action_events_by_timesort  mod_forum_get_forum_discussions
core_message_get_conversations
message_popup_get_popup_notifications
gradereport_overview_get_course_grades
```

**1.2** Students can obtain a token for it. On a site where students sign in
through Google they have no Moodle password, so either the administrator
issues tokens under Manage tokens, or `moodle/webservice:createtoken` is
granted so `/user/managetoken.php` shows each student their own.

`ADMIN_REQUEST.md` sets both options out, with the trade-offs.

> **Check.** Get one token and run, from any machine with this repository:
>
> ```
> python check_token.py <token>
> ```
>
> It must print an account name and a course list. "This token was refused"
> means the functions are not in the service - **stop and fix that first.**
> Everything below depends on it.

---

## 2. The host

**2.1 Requirements**

| | |
|---|---|
| OS | Linux (a unit file is provided). macOS works; Windows needs manual service setup |
| Python | 3.11 or newer |
| Network | Outbound HTTPS. **No firewall change** |
| Disk | About 300 MB including the virtual environment |
| Load | Thirty students asking at once completed in under 6 seconds, measured on a laptop |

**2.2 Create a user and install**

```
sudo useradd --system --create-home --home-dir /opt/moodle-mcp moodle-mcp
sudo -u moodle-mcp git clone <repository> /opt/moodle-mcp/app
cd /opt/moodle-mcp/app
sudo -u moodle-mcp python3 -m venv venv
sudo -u moodle-mcp venv/bin/pip install -r requirements-server.txt
```

`requirements-server.txt` is what the server needs. `requirements.txt`
additionally pulls in the OpenAI client, which only the optional standalone
chat client uses; a server does not need it.

> **Check.**
> ```
> sudo -u moodle-mcp venv/bin/python -c "import remote_server; print('ok')"
> ```

**2.3 Configure**

```
sudo -u moodle-mcp cp .env.example .env
sudo -u moodle-mcp chmod 600 .env
sudo -u moodle-mcp nano .env
```

Set:

```
MOODLE_URL=https://lms.example.edu
MOODLE_TOKEN=<a token for any one account>
MOODLE_SERVICE=<shortname of the restricted service, if there is one>
```

`MOODLE_TOKEN` is **not** what students use. Each student's own token is
sealed into their own access token when they sign in. This entry exists only
so the verification tools and the local `server.py` can reach Moodle.
`OPENAI_API_KEY` and `LLM_MODEL` may be left as they are.

> **Check.**
> ```
> sudo -u moodle-mcp venv/bin/python selftest.py
> ```
> 82 checks, 0 failed. **Do not expose anything on a failure.**

---

## 3. A public address

The address becomes the OAuth issuer, so it must be **the same after every
restart**. A free quick tunnel issues a new one each time, which invalidates
every student's connector: acceptable for a demo, wrong for anything running
for a week.

**3.1** Ask whoever holds the Cloudflare account for the domain to:

1. Zero Trust → Networks → Tunnels → Create a tunnel, connector "Cloudflared"
2. Send you the connector token
3. Under **Public Hostname**, add one entry:
   `ai` . `example.edu` → HTTP → `localhost:8000`

If the domain is already on Cloudflare, this costs nothing and takes about ten
minutes. Check with `dig +short NS example.edu`; Cloudflare nameservers end in
`ns.cloudflare.com`.

**3.2** Install the connector on the host:

```
sudo cloudflared service install <connector token>
systemctl status cloudflared
```

It dials out to Cloudflare. **Nothing needs to be opened inbound.**

> **Check.** `systemctl status cloudflared` is active. Nothing answers on the
> public address yet - the server is not running.

---

## 4. The server as a service

```
sudo cp deploy/moodle-mcp.service /etc/systemd/system/
sudo nano /etc/systemd/system/moodle-mcp.service
```

Set `PUBLIC_URL` to the hostname from step 3, **with no trailing slash and no
`/mcp`**:

```
Environment=PUBLIC_URL=https://ai.example.edu
```

Then:

```
sudo systemctl daemon-reload
sudo systemctl enable --now moodle-mcp
systemctl status moodle-mcp
```

> **Check.** From any machine, including one that has never seen this
> repository:
> ```
> python healthcheck.py https://ai.example.edu/mcp
> ```
> Ten checks, "HEALTHY". It needs no token, so a colleague can run it too.

---

## 5. Prove it restarts by itself

This is the step people skip, and it is the one that decides whether the
service survives the week.

```
sudo reboot
```

> **Check.** After it comes back, without logging in or starting anything:
> ```
> python healthcheck.py https://ai.example.edu/mcp
> ```
> Still HEALTHY. If not, `systemctl status moodle-mcp cloudflared` and
> `journalctl -u moodle-mcp -b` will say why.

**An untested restart is not a restart.**

---

## 6. End to end, as a student

1. On claude.ai: Settings → Connectors → Add custom connector
2. Any name; URL `https://ai.example.edu/mcp`
3. Claude opens a sign-in page. Paste a Moodle token into the lower box, or -
   if the account has a Moodle password - use the upper boxes
4. In a new chat: "What courses am I in?"

> **Check.** The answer names real courses. Then work through
> `TEST_PLAN.md`, which covers a student, a teacher, and proving that one user
> cannot see another's data.

---

## What to hand on

| Item | To whom |
|---|---|
| The connector URL | Students |
| How to copy their token (`/user/managetoken.php`) | Students |
| `DEPLOYMENT.md` | Whoever watches it during the pilot |
| Where `.env`, `.oauth_key` and `.oauth_clients.json` live | Whoever succeeds you |

`.oauth_key` is the encryption key for every issued access token. **Deleting it
signs everyone out.** It is excluded from git; back it up somewhere that is
not the repository.

---

## Uninstall

```
sudo systemctl disable --now moodle-mcp
sudo rm /etc/systemd/system/moodle-mcp.service
sudo systemctl daemon-reload
sudo cloudflared service uninstall
sudo rm -rf /opt/moodle-mcp
```

Then ask the Cloudflare account holder to delete the tunnel and its DNS
record, and revoke the Moodle tokens under Manage tokens. **A token left alive
is a credential left alive.**

---

## Troubleshooting

| Symptom | Where to look |
|---|---|
| `healthcheck.py` says UNREACHABLE | `systemctl status cloudflared`. Is the DNS record still there? |
| UNREACHABLE, tunnel healthy | `systemctl status moodle-mcp`, `journalctl -u moodle-mcp -b` |
| Claude cannot add the connector | URL must end in `/mcp` and be HTTPS |
| Sign-in page opens, token rejected | Wrong row copied, or the token was **Reset** afterwards |
| Every answer is "could not retrieve" | `check_token.py <token>`. Usually a revoked token or a function removed from the service |
| Every answer is "you have no ..." | Not a fault. That account has no data |
| Fewer than ten tools | An older process is still running: `systemctl restart moodle-mcp` |

"Could not retrieve" is a failure. "You have none" is an answer. The wording
distinguishes them deliberately.
