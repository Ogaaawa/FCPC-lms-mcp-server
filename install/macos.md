# Installing on macOS

Read `../INSTALL.md` first: the Moodle side has to be done before any of this
matters, and it explains what you are installing.

**A Mac is a fine machine to demonstrate from, and a poor one to run a pilot
on.** It sleeps when the lid closes, it goes home in a bag, and when it does
either, every student loses access at once. If the choice exists, use a Linux
host. If it does not, section 3 makes a Mac survive a reboot; nothing can make
it survive being carried out of the building.

---

## 1. Install

```
git clone https://github.com/Ogaaawa/FCPC-lms-mcp-server.git ~/moodle-mcp
cd ~/moodle-mcp
python3 -m venv venv
venv/bin/pip install -r requirements-server.txt
```

Or double-click **`setup.command`**, which creates the environment and opens a
window for the settings.

> **Check.**
> ```
> venv/bin/python -c "import remote_server; print('ok')"
> ```

## 2. Configure

```
cp .env.example .env
chmod 600 .env
nano .env
```

```
MOODLE_URL=https://lms.example.edu
MOODLE_TOKEN=<a token for any one account>
MOODLE_SERVICE=<shortname of the restricted service, if there is one>
```

`MOODLE_TOKEN` is **not** what students use; see `../INSTALL.md`.

> **Check.**
> ```
> venv/bin/python selftest.py
> ```
> 82 checks, 0 failed. Do not expose anything on a failure.

## 3. Trying it, before making it permanent

```
brew install cloudflared
./start-server.command
```

Double-clicking works too. It prints the URL to hand out and keeps running
until the window is closed.

**This is for a demo, not for a pilot.** The address changes every time, so
every student would have to register the connector again.

---

## 4. Making it permanent

Two jobs: the tunnel, and the server. Install them separately.

### 4.1 A fixed address

The address becomes the OAuth issuer, so it must survive a restart unchanged.
`../INSTALL.md` step 3 has the request to send to whoever holds the Cloudflare
account. Once you have the connector token:

```
sudo cloudflared service install <connector token>
sudo launchctl list | grep cloudflared
```

It dials out. **Nothing needs to be opened inbound.**

### 4.2 The server as a LaunchDaemon

A **LaunchDaemon** starts at boot with nobody logged in. A LaunchAgent only
starts at login, which is not good enough here.

```
sudo cp deploy/com.fcpc.moodle-mcp.plist /Library/LaunchDaemons/
sudo nano /Library/LaunchDaemons/com.fcpc.moodle-mcp.plist
```

Edit three things:

- the two paths, if the checkout is not at `/opt/moodle-mcp/app`
- `--public-url`, to the tunnel hostname - **no trailing slash, no `/mcp`**
- `UserName`, to the account that owns the checkout

Then:

```
sudo chown root:wheel /Library/LaunchDaemons/com.fcpc.moodle-mcp.plist
sudo chmod 644 /Library/LaunchDaemons/com.fcpc.moodle-mcp.plist
sudo launchctl load -w /Library/LaunchDaemons/com.fcpc.moodle-mcp.plist
sudo launchctl list | grep moodle-mcp
```

`KeepAlive` restarts it if it stops, which is what makes it a service rather
than a program someone left running.

> **Check.** From any machine, without a token:
> ```
> python healthcheck.py https://ai.example.edu/mcp
> ```

### 4.3 Stop it sleeping

A Mac that sleeps takes every student offline.

```
sudo pmset -c sleep 0 disablesleep 1
sudo pmset -c displaysleep 15
pmset -g
```

`-c` means "on mains power". **On a laptop with the lid closed, this still
requires the power adapter to be connected**; on battery it will sleep
regardless.

### 4.4 After a macOS update

Updates reboot the machine. That is survivable **because** both halves start
at boot - which is exactly what section 5 tests.

---

## 5. Prove it comes back by itself

The step people skip, and the one that decides whether the pilot survives.

```
sudo reboot
```

After it comes back, **without logging in or starting anything**:

```
python healthcheck.py https://ai.example.edu/mcp
```

Still HEALTHY. If not:

```
sudo launchctl list | grep -E "moodle-mcp|cloudflared"
tail -50 /var/log/moodle-mcp.log
```

**An untested restart is not a restart.**

---

## Day to day

| Task | Command |
|---|---|
| Is it up | `python healthcheck.py <url> --quiet` |
| Restart the server | `sudo launchctl kickstart -k system/com.fcpc.moodle-mcp` |
| Follow the log | `tail -f /var/log/moodle-mcp.log` |

## Uninstall

```
sudo launchctl unload -w /Library/LaunchDaemons/com.fcpc.moodle-mcp.plist
sudo rm /Library/LaunchDaemons/com.fcpc.moodle-mcp.plist
sudo cloudflared service uninstall
sudo pmset -c disablesleep 0
rm -rf ~/moodle-mcp
```

Then revoke the Moodle tokens - see `../INSTALL.md`.

## Files that must not be lost

`.env`, `.oauth_key` and `.oauth_clients.json` live in the checkout and are
excluded from git. Deleting `.oauth_key` signs every user out at once.
