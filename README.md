# FCPC LMS MCP server

An MCP server that lets an AI assistant answer questions about a student's own
Moodle account — assignments due, unread messages, pending quizzes and enrolled
courses.

Students connect from **Claude on the web, on a phone, or on a desktop** by
registering **one URL**. No software to install, no tokens to copy by hand.

Built for First City Providential College, but it works against any Moodle site
with web services enabled.

## What it can answer

- Everything with a deadline in the coming days, in one list
- Unread messages from teachers and classmates
- Notifications: reminders, grading notices and alerts
- The overall grade in each course
- Assignments due, and quizzes not yet completed
- Announcements posted by teachers
- What is inside a course: sections, activities and links
- Which courses you are enrolled in

```
"Do I have any new messages?"
"What is due this week?"
"How am I doing in my courses?"
"Did I miss anything?"
"What are we covering in week 3 of History?"
```

## Two ways to run it

| | Remote server | Local server |
|---|---|---|
| Who it is for | A class or a whole institution | One person, on their own machine |
| Client | Claude (web, iOS, Android, desktop) | Any MCP client on that machine |
| Student sets up | One URL | Nothing, but needs the repo installed |
| Sign-in | OAuth, handled by Claude | A token in `.env` |
| Entry point | `remote_server.py` | `server.py` |

Most deployments want the remote server.

---

## Remote server (recommended)

### Requirements

- Python 3.11 or newer
- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
  (`brew install cloudflared`) or any other way to expose an HTTPS address
- A Moodle account on the site, used once during setup to record the site address

### For the administrator

1. Run `setup.command` (macOS) or `setup.bat` (Windows) once and sign in.
   This writes your Moodle site address to `.env`.
2. Run `start-server.command`. It prints the URL to hand out:

```
https://xxxx.trycloudflare.com/mcp
```

Closing that window stops the server, so leave it open while the service is in
use. Free `trycloudflare.com` addresses change every restart; use a
[named tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
for a fixed address.

### For students

1. Open [claude.ai](https://claude.ai) in any browser, including a phone.
2. Go to **Settings → Connectors → Add custom connector**.
3. Give it any name and paste the URL you were given.
4. Claude opens the Moodle sign-in page. Sign in with your usual Moodle
   username and password.

That is the whole setup. Afterwards it works in the Claude mobile apps too.

The same page has a second box that takes a web service token instead. Use it
when the account has no Moodle password — a Google or other SSO account — or to
demonstrate the connector with a token you already hold. It accepts the plain
token, or the whole `moodlemobile://token=...` value from
`admin/tool/mobile/launch.php`.

> Connectors can only be **added** from the Claude website, but a phone browser
> works fine. Once added, they sync to the apps.

### How sign-in works

```
Student's Claude ──HTTPS──▶ MCP server ──▶ Moodle
                 (OAuth)
```

Each user is identified by an OAuth sign-in. When a student signs in, their
Moodle token is **encrypted into the access token itself** and handed back to
Claude.

- The server stores **no** Moodle tokens and **no** passwords
- A password is used once to obtain a token, then discarded
- One user can never see another user's data

`.oauth_key` (the encryption key) and `.oauth_clients.json` are secrets. Both
are excluded from git. Deleting `.oauth_key` signs everyone out.

---

## Local server

For running the MCP server on your own machine, over stdio.

1. Run `setup.command` / `setup.bat`, or:

```
python -m venv venv
source venv/bin/activate          # macOS/Linux
.\venv\Scripts\activate           # Windows PowerShell
pip install -r requirements.txt
python setup_gui.py
```

2. Point your MCP client at `server.py`. For example, in Claude Desktop's
   `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "moodle": {
      "command": "/path/to/venv/bin/python",
      "args": ["/path/to/server.py"]
    }
  }
}
```

To see exactly what the AI receives:

```
python list_tools.py
```

There are also two standalone chat clients, `client.py` (OpenAI) and
`client_localLLM.py` (ollama). Both take the server script as an argument:

```
python client.py server.py
```

---

## Testing

`selftest.py` checks everything that can be checked without a browser: the
Moodle connection, both servers, the OAuth flow through to a real tool call,
and that users cannot see each other's data.

```
python selftest.py             # all checks
python selftest.py --offline   # skip anything needing the network
```

It exits 0 when everything passes and prints the remaining manual steps:
registering the connector in Claude, signing in, asking a question, and
repeating it on a phone.

Run it after installing, after changing the code, and on the machine that will
host the server.

It cannot tell "no assignments are due" apart from "the tool is broken", because
both look the same against an empty account. `TEST_DATA.md` specifies the
courses, activities and accounts to create in Moodle so that every answer has
something to be right about.

---

## Notes on Moodle

Some Moodle sites sit behind Cloudflare and reject ordinary HTTPS clients with
HTTP 403. Requests therefore go through `curl_cffi` with a browser TLS
fingerprint. This is why the server cannot be reimplemented in, say, Apps
Script, and why it should run somewhere with a normal-looking network path.

### Sites that use SSO

If students sign in to Moodle through Google or another identity provider, they
have no Moodle password, so `login/token.php` cannot issue them a token. The
mobile route `admin/tool/mobile/launch.php` does issue one, but Moodle returns
it only as `moodlemobile://token=...` and validates the scheme against
`^[a-zA-Z][a-zA-Z0-9-+.]*$`, so a web application cannot receive it. Only a
native app can. `decode_token.py` decodes that value if you can capture it by
hand.

On such a site the administrator has to issue tokens. `ADMIN_REQUEST.md` is a
document you can hand to them; it sets out the two workable arrangements and
their security trade-offs.

## Files

| File | Purpose |
|---|---|
| `remote_server.py` | Remote MCP server with OAuth, for Claude connectors |
| `oauth_provider.py` | OAuth authorization server; stores no tokens |
| `login_page.py` | The Moodle sign-in page Claude opens |
| `server.py` | Local MCP server over stdio |
| `moodle_client.py` | Moodle API client, one token per instance |
| `moodle_auth.py` | Token retrieval and `.env` handling |
| `setup_gui.py` | Setup wizard |
| `setup.command` / `setup.bat` | Double-click setup (macOS / Windows) |
| `start-server.command` | Publish the remote server (macOS) |
| `selftest.py` | Check the installation end to end |
| `list_tools.py` | Print the tools the AI sees |
| `get_token.py` | Fetch a token from the command line |
| `decode_token.py` | Token extraction for SSO users |
| `ADMIN_REQUEST.md` | What to ask a Moodle administrator for on an SSO site |
| `TEST_DATA.md` | The Moodle courses and accounts needed to test against live data |
| `TEST_PLAN.md` | Two-pass test procedure: as a student, then as a teacher |
| `check_token.py` | Show which account a token belongs to and what it can see |
| `TEST_DATA.md` | The Moodle courses and accounts needed to test against live data |
| `client.py`, `client_localLLM.py` | Standalone chat clients |

## Credits

The MCP server itself (`server.py`, `client.py`, `client_localLLM.py`) was
written by **Jiseong JEONG ([@jeongjisung690](https://github.com/jeongjisung690))**.
Original repository: https://github.com/jeongjisung690/Moodle---MCP-server

This repository adds:

- Support for Moodle sites behind Cloudflare
- Automatic token retrieval from a username and password
- Token extraction for SSO users
- A setup wizard for non-technical users
- A remote MCP server with OAuth, so students connect with a single URL

## License

No license has been set. Please contact the authors before using or
redistributing this code.
