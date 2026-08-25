# FCPC LMS MCP server

An MCP server that lets an AI assistant answer questions about a student's own
Moodle account — assignments due, unread messages, pending quizzes and enrolled
courses.

Students connect from **Claude on the web, on a phone, or on a desktop** by
registering **one URL**. No software to install, no tokens to copy by hand.

Built for First City Providential College, but it works against any Moodle site
with web services enabled.

## What it can answer

- When your assignments are due
- Unread messages from teachers and classmates
- Quizzes you have not completed
- Which courses you are enrolled in

```
"Do I have any new messages?"
"What is due this week?"
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

## Notes on Moodle

Some Moodle sites sit behind Cloudflare and reject ordinary HTTPS clients with
HTTP 403. Requests therefore go through `curl_cffi` with a browser TLS
fingerprint. This is why the server cannot be reimplemented in, say, Apps
Script, and why it should run somewhere with a normal-looking network path.

Users who sign in to Moodle through SSO (Google and similar) cannot use
`login/token.php`. `decode_token.py` covers that case.

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
| `list_tools.py` | Print the tools the AI sees |
| `get_token.py` | Fetch a token from the command line |
| `decode_token.py` | Token extraction for SSO users |
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
