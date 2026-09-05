# Running the assistant for a one-week pilot

Operating notes for hosting this on an FCPC machine and letting students use
it for a week. It assumes the Moodle side is already done; if it is not, see
`ADMIN_REQUEST.md` first.

For what the service is and how it works, see `README.md`. For testing it, see
`TEST_PLAN.md`.

---

## Before the week starts

### On Moodle

| Requirement | How to confirm |
|---|---|
| An external service holding the thirteen functions | `python check_token.py <token>` prints an account and its courses. If it says "This token was refused", the functions are missing |
| Students can obtain a token | A student opens `/user/managetoken.php` and sees a row with a **Copy to clipboard** button |
| Web services enabled | Implied by the two above |

The thirteen functions are listed in `README.md`. All are read-only.

### On the host machine

- Python 3.11 or newer
- Outbound HTTPS. **No inbound port, no public IP, no firewall change** - the
  tunnel dials out
- `cloudflared`, or another way to publish an HTTPS address
- Enough uptime to cover the week. This is the part that actually fails: see
  **Keeping it running** below

### Install

```
git clone <this repository>
cd moodle-mcp-server
python -m venv venv
venv/bin/pip install -r requirements.txt
```

### Configure

Create `.env`:

```
MOODLE_URL=https://lms.fcpc.edu.ph
MOODLE_TOKEN=<a token for any account; used only by selftest and server.py>
MOODLE_SERVICE=<shortname of the restricted service, if one exists>
```

`MOODLE_TOKEN` is **not** what students use. Each student's own token is sealed
into their own access token when they sign in. This entry only lets
`selftest.py` and the local `server.py` reach Moodle.

### Verify before exposing anything

```
venv/bin/python selftest.py
```

82 checks. Do not go live on a failure.

---

## Starting it

```
./start-server.command          # macOS
```

It prints the address to hand out:

```
https://xxxx.trycloudflare.com/mcp
```

```
./start-server.sh               # Linux, or macOS
```

Both use a quick tunnel. On Windows, run the two parts yourself:

```
cloudflared tunnel --url http://127.0.0.1:8000 --no-autoupdate
venv\Scripts\python remote_server.py --port 8000 --public-url https://<the address>
```

The public address must be passed in, because it becomes the OAuth issuer.

For a host that should survive a reboot, do not use these at all. Install a
named tunnel and the systemd unit in `deploy/` - see the guide for your platform in `install/`.

### A fixed address

A free quick tunnel gets a **new address every restart**, and every student
then has to register the connector again. For a week-long pilot that is a real
risk, not a cosmetic one.

`fcpc.edu.ph` is already on Cloudflare (nameservers `coraline.ns.cloudflare.com`
and `hal.ns.cloudflare.com`), so a named tunnel on the school's own domain
costs nothing. Ask whoever holds the Cloudflare account to:

1. Zero Trust → Networks → Tunnels → Create a tunnel (connector: Cloudflared)
2. Send you the connector token
3. Under Public Hostname add: `ai` . `fcpc.edu.ph` → HTTP → `localhost:8000`

Then, on the host:

```
cloudflared service install <connector token>
```

That registers it as a system service, so it starts on boot and restarts if it
dies. The address becomes `https://ai.fcpc.edu.ph/mcp` and stays put.

### Keeping it running

A terminal window someone must leave open **will** be closed, and a laptop
**will** be shut. Neither is a deployment. In order of preference:

1. A machine that is on anyway - a school server - with the tunnel installed as
   a service, as above
2. A dedicated machine that nobody else uses
3. A desktop PC, with the service configured to start at boot rather than at
   login

On Linux, `deploy/moodle-mcp.service` (Linux) and `deploy/com.fcpc.moodle-mcp.plist` (macOS) do this. `cloudflared service install`
registers the tunnel as its own service, so the two halves come back
independently.

Whatever you choose, restart it once deliberately and confirm it comes back by
itself. An untested restart is not a restart.

---

## What students do

1. Open `https://lms.fcpc.edu.ph/user/managetoken.php`, find the row for the
   service, press **Copy to clipboard**
2. On claude.ai: Settings → Connectors → Add custom connector. Any name; paste
   the URL you handed out
3. Claude opens a sign-in page. Paste the token into the lower box and press
   **Continue with token**

Connectors can only be **added** from the Claude website, but a phone browser
does that fine, and once added they appear in the mobile apps.

If the student's account has a Moodle password - not a Google account - the
upper box works instead and they never touch a token.

---

## Checking it from outside

```
venv/bin/python healthcheck.py https://ai.fcpc.edu.ph/mcp
venv/bin/python healthcheck.py https://ai.fcpc.edu.ph/mcp --quiet
```

Nothing here needs a token, so it can be run from any machine, including one
that has never seen this repository. Exit code is 0 when healthy and 1 when
not, so it can drive an alert:

```
*/10 * * * * cd /path/to/repo && venv/bin/python healthcheck.py \
  https://ai.fcpc.edu.ph/mcp --quiet >> /tmp/mcp-health.log 2>&1
```

It confirms the address answers, that the OAuth metadata is published and all
HTTPS, that an unauthenticated request is refused with a 401 pointing at the
sign-in, and that the sign-in page rejects a forged link.

**It does not check that anybody's data is right.** That needs a token and
`selftest.py`.

---

## During the week

Worth a look once a day:

| Check | Command or place |
|---|---|
| Is it up | `healthcheck.py <url> --quiet` |
| Is Moodle still answering | `check_token.py <a token>` |
| Has the address changed | Compare against what students registered |
| Errors | The server's own output |

Capacity is not the constraint. Thirty students asking at once was measured at
30/30 successful, worst case 5.4 seconds, with no rate limiting from Moodle.
The bottleneck is the host staying up and the address staying the same.

### If a student reports a problem

| Symptom | Likely cause |
|---|---|
| "Add custom connector" fails | Wrong URL, or the server is down. Run `healthcheck.py` |
| Sign-in page never opens | Tunnel is down, or the address changed |
| Token rejected | Wrong row copied, or the token was **Reset** afterwards, which invalidates the old one |
| Answers are all "could not retrieve" | Moodle side: token revoked, or a function removed from the service |
| Answers are all "you have no ..." | Not a fault. That account genuinely has no data |
| Fewer than ten tools | An older server process is still running |

The difference between the last two rows matters. "Could not retrieve" is a
failure; "you have none" is an answer.

---

## Security, in short

- The server stores **no** Moodle tokens and **no** passwords
- A student's Moodle token is encrypted into their own access token and
  decrypted per request, in memory
- `.oauth_key` and `.oauth_clients.json` are secrets, excluded from git.
  Deleting `.oauth_key` signs everyone out at once
- Every tool is read-only. Nothing submits, posts, enrols, grades or messages
- A student's token carries that student's own permissions and nothing more.
  One user cannot reach another user's data
- To revoke one student: they press **Reset** on their token in Moodle, or an
  administrator deletes it under Manage tokens

There is **no audit log**. Nothing records who asked what. For a one-week
pilot among consenting participants that is usually acceptable; state it
plainly to whoever approves the pilot rather than leaving it to be discovered.

---

## Ending the pilot

1. Stop the server, and remove the tunnel service if one was installed
   (`cloudflared service uninstall`)
2. Ask the Cloudflare account holder to delete the tunnel and its DNS record
3. Have students remove the connector from Claude
4. Revoke the tokens: Manage tokens → delete, or each student presses Reset
5. If the service is no longer wanted, disable it under External services

Step 4 is the one that matters. A token left alive is a credential left alive.

---

## Known limitations

`README.md` lists them. The three that bear on a pilot:

- **No audit log**
- **Times are shown in JST**, so timestamps read one hour ahead of Philippine
  time. Deadlines are mostly unaffected, since Moodle formats those itself
- **One Moodle site per server**
