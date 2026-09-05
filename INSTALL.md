# Installation

For the person putting this on a server.

The Moodle side comes first and is the same everywhere; the host part differs
by platform. Do section 1, then follow the guide for your operating system.

| Document | For |
|---|---|
| **This file** | Moodle prerequisites, then which platform guide to follow |
| `install/windows.md` | Installing on Windows |
| `install/macos.md` | Installing on macOS |
| `install/linux.md` | Installing on Linux |
| `ADMIN_REQUEST.md` | What to ask the Moodle administrator for |
| `DEPLOYMENT.md` | Running it day to day |
| `TEST_PLAN.md` | Proving it works |
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

It runs as an unprivileged user. Administrator rights are needed only to
install the services.

Roughly an hour of hands-on work, plus waiting on whoever holds the Moodle
and Cloudflare accounts. The waiting is the larger half.

---

## 1. Moodle side

**This must be done first.** It is not something the server can work around,
and it is where this kind of project usually stalls.

**1.1** An external service exists holding these thirteen functions, all
read-only:

```
core_webservice_get_site_info                 mod_assign_get_assignments
core_enrol_get_users_courses                  mod_quiz_get_quizzes_by_courses
core_course_get_contents                      mod_quiz_get_user_attempts
core_course_get_courses_by_field              mod_forum_get_forums_by_courses
core_calendar_get_action_events_by_timesort   mod_forum_get_forum_discussions
core_message_get_conversations
message_popup_get_popup_notifications
gradereport_overview_get_course_grades
```

**1.2** Students can obtain a token for it. On a site where students sign in
through Google they have no Moodle password, so either an administrator issues
tokens under **Manage tokens**, or `moodle/webservice:createtoken` is granted
so that `/user/managetoken.php` shows each student their own with a
**Copy to clipboard** button.

`ADMIN_REQUEST.md` sets both options out with their trade-offs, in a form you
can hand over unchanged.

> **Check.** Get one token and run, on any machine with this repository:
>
> ```
> python check_token.py <token>
> ```
>
> It must print an account name and a course list.
>
> "This token was refused" means the functions are not in the service.
> **Stop here.** Nothing below will work until this passes.

---

## 2. Pick your platform

| Host | Guide | Suitability |
|---|---|---|
| **Linux** | `install/linux.md` | **Best.** A systemd unit is provided |
| **Windows** | `install/windows.md` | Fine. Scheduled task, a few extra settings |
| **macOS** | `install/macos.md` | A good demo machine, a poor pilot host |

Each guide ends with the same two steps, and both matter:

- a health check from **outside**, run without a token
- a **deliberate reboot**, to prove the service comes back on its own

An untested restart is not a restart. It is the single most common reason a
pilot dies quietly halfway through the week.

---

## 3. Asking for a fixed public address

Every platform needs this, so it is here rather than in each guide.

The address becomes the OAuth issuer, so it must be **the same after every
restart**. A free quick tunnel issues a new one each time, which invalidates
every student's connector: acceptable for a demo, wrong for anything running
for a week.

Check whether the domain is already on Cloudflare:

```
dig +short NS example.edu
```

Cloudflare nameservers end in `ns.cloudflare.com`. If they do, this costs
nothing. Ask whoever holds that account to:

1. Zero Trust → Networks → Tunnels → Create a tunnel, connector "Cloudflared"
2. Send you the connector token
3. Under **Public Hostname**, add one entry:
   `ai` . `example.edu` → HTTP → `localhost:8000`

Wording you can send:

```
Could you create a Cloudflare Tunnel for us? About ten minutes, no cost,
and it stays entirely under your control - you can see it, disable it or
delete it from the same screen at any time.

  1. Zero Trust -> Networks -> Tunnels -> Create a tunnel
     Connector type: Cloudflared. Name: e.g. fcpc-ai-assistant
  2. Send us the connector token it shows
  3. Under Public Hostname, add one entry:
       Subdomain: ai    Domain: example.edu
       Path: (empty)    Service: HTTP -> localhost:8000

We install the connector on our side with that token. Nothing needs to be
opened on the firewall: the connector dials out to Cloudflare, so there is
no inbound port and no public IP involved.
```

---

## 4. End to end, as a student

Once the platform guide is finished:

1. On claude.ai: Settings → Connectors → Add custom connector
2. Any name; URL `https://ai.example.edu/mcp`
3. Claude opens a sign-in page. Paste a Moodle token into the lower box - or,
   if the account has a Moodle password, use the upper boxes
4. In a new chat: "What courses am I in?"

> **Check.** The answer names real courses. Then work through `TEST_PLAN.md`,
> which covers a student, a teacher, and proving that one user cannot see
> another's data.

---

## What to hand on

| Item | To whom |
|---|---|
| The connector URL | Students |
| How to copy their token (`/user/managetoken.php`) | Students |
| `DEPLOYMENT.md` | Whoever watches it during the pilot |
| Where `.env`, `.oauth_key` and `.oauth_clients.json` live | Whoever succeeds you |

`.oauth_key` is the encryption key for every access token that has been
issued. **Deleting it signs everyone out.** It is excluded from git; back it
up somewhere that is not the repository.

---

## Uninstall

The platform guides have the commands. Whichever you follow, finish with this:

- Ask the Cloudflare account holder to delete the tunnel and its DNS record
- Revoke the Moodle tokens under **Manage tokens**, or have each student press
  **Reset**
- If the service is no longer wanted, disable it under **External services**

**A token left alive is a credential left alive.**

---

## Troubleshooting

| Symptom | Where to look |
|---|---|
| `healthcheck.py` says UNREACHABLE | Is the tunnel service running? Is the DNS record still there? |
| UNREACHABLE, tunnel healthy | The server process. See the platform guide |
| Claude cannot add the connector | The URL must end in `/mcp` and be HTTPS |
| Sign-in page opens, token rejected | Wrong row copied, or the token was **Reset** afterwards |
| Every answer is "could not retrieve" | `check_token.py <token>`. Usually a revoked token, or a function removed from the service |
| Every answer is "you have no ..." | Not a fault. That account has no data |
| Fewer than ten tools | An older process is still running. Restart the service |

"Could not retrieve" is a failure. "You have none" is an answer. The wording
distinguishes them deliberately.
