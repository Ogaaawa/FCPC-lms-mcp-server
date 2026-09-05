# Running it on Windows

`INSTALL.md` describes a Linux host. This covers the same ground on Windows.
Read `INSTALL.md` first for the Moodle prerequisites and the checks; only the
host part differs.

**Windows Server or Windows 10/11 both work.** What matters is that the
machine stays on and starts the service without anybody logging in.

---

## 1. Install

**1.1 Python 3.11 or newer**

From <https://www.python.org/downloads/>. During installation tick
**"Add Python to PATH"**. Check:

```
python --version
```

**1.2 Get the code**

```
git clone https://github.com/Ogaaawa/FCPC-lms-mcp-server.git C:\moodle-mcp
cd C:\moodle-mcp
```

No git? Download the ZIP from the same page and extract it to `C:\moodle-mcp`.

**1.3 Virtual environment and dependencies**

```
python -m venv venv
venv\Scripts\pip install -r requirements-server.txt
```

> **Check.**
> ```
> venv\Scripts\python -c "import remote_server; print('ok')"
> ```

**1.4 Settings**

```
copy .env.example .env
notepad .env
```

Set `MOODLE_URL`, `MOODLE_TOKEN` and, if the site has a restricted service,
`MOODLE_SERVICE`. `MOODLE_TOKEN` is not what students use; see `INSTALL.md`.

> **Check.**
> ```
> venv\Scripts\python selftest.py
> ```
> 82 checks, 0 failed. Do not expose anything on a failure.

**1.5 cloudflared**

Download `cloudflared-windows-amd64.exe` from
<https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/>,
rename it to `cloudflared.exe`, put it somewhere on the PATH (for example
`C:\Windows\System32`, or its own folder added to PATH).

> **Check.** `cloudflared --version`

---

## 2. Trying it, before making it permanent

```
start-server.bat
```

Double-clicking works too. It prints the URL to hand out and keeps running
until the window is closed.

**This is for a demo, not for a pilot.** The address changes every time, so
every student would have to register the connector again. It also stops the
moment somebody closes the window or the machine sleeps.

> `start-server.bat` runs `taskkill /f /im cloudflared.exe` when it exits.
> Do not use it on a machine that also serves a named tunnel - it would stop
> that too.

---

## 3. Making it permanent

Two services: the tunnel, and the server. Install them separately.

### 3.1 A fixed address

The public address becomes the OAuth issuer, so it must be the same after
every restart. Ask whoever holds the Cloudflare account for the domain to
create a named tunnel and send you the connector token - `INSTALL.md` step 3
has the exact request.

Then, in an **Administrator** command prompt:

```
cloudflared service install <connector token>
sc query cloudflared
```

That registers a real Windows service, so the tunnel starts at boot on its
own.

### 3.2 The server as a scheduled task

Windows has no equivalent of a systemd unit built in, but Task Scheduler can
start a program at boot, without a logged-in user, and restart it if it stops.

In an **Administrator** command prompt, one line (adjust the path and the
address):

```
schtasks /create /tn "MoodleMCP" /ru "SYSTEM" /sc onstart /rl highest /f ^
  /tr "cmd /c cd /d C:\moodle-mcp && venv\Scripts\python.exe remote_server.py --host 127.0.0.1 --port 8000 --public-url https://ai.fcpc.edu.ph"
```

- `/ru "SYSTEM"` - runs without anybody logged in. **This is the point.**
- `/sc onstart` - at boot, not at login
- `--public-url` - must match the tunnel hostname exactly, no trailing slash
  and no `/mcp`

Then add automatic restart, which `schtasks` cannot set from the command line:

1. Open **Task Scheduler** → find **MoodleMCP** → Properties
2. **Settings** tab
3. Tick **"If the task fails, restart every:"** → 1 minute, up to 3 times
4. Untick **"Stop the task if it runs longer than:"** - it is meant to run
   forever
5. **Conditions** tab → untick **"Start the task only if the computer is on
   AC power"** if this is a laptop

Start it now without rebooting:

```
schtasks /run /tn "MoodleMCP"
```

> **Check.** From any machine:
> ```
> python healthcheck.py https://ai.fcpc.edu.ph/mcp
> ```

### 3.3 Stop Windows from sleeping

A machine that sleeps takes every student offline. In an Administrator
prompt:

```
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 15
```

The screen may still turn off; the machine will not sleep.

### 3.4 Windows Update

Updates reboot the machine, usually at night. That is survivable **because**
both halves start at boot - which is exactly what step 4 tests. Set active
hours so it does not happen mid-class:

**Settings → Windows Update → Advanced options → Active hours.**

---

## 4. Prove it comes back by itself

The step people skip, and the one that decides whether the pilot survives.

```
shutdown /r /t 0
```

After it comes back, **without logging in or starting anything**:

```
python healthcheck.py https://ai.fcpc.edu.ph/mcp
```

Still HEALTHY. If not:

```
sc query cloudflared
schtasks /query /tn "MoodleMCP" /v /fo list
```

**An untested restart is not a restart.**

---

## Day to day

| Task | Command |
|---|---|
| Is it up | `python healthcheck.py <url> --quiet` |
| Restart the server | `schtasks /end /tn "MoodleMCP"` then `/run` |
| Restart the tunnel | `sc stop cloudflared` then `sc start cloudflared` |
| Server log | Task Scheduler → MoodleMCP → History |

To capture the server's own output, change the task's action to redirect it:

```
cmd /c cd /d C:\moodle-mcp && venv\Scripts\python.exe remote_server.py ... >> C:\moodle-mcp\server.log 2>&1
```

---

## Uninstall

```
schtasks /delete /tn "MoodleMCP" /f
cloudflared service uninstall
rmdir /s /q C:\moodle-mcp
```

Then have the Cloudflare account holder delete the tunnel and its DNS record,
and revoke the Moodle tokens under Manage tokens. **A token left alive is a
credential left alive.**

---

## Files that must not be lost

`.env`, `.oauth_key` and `.oauth_clients.json` live in `C:\moodle-mcp` and are
excluded from git. Deleting `.oauth_key` signs every user out at once. Back it
up somewhere that is not the repository.
