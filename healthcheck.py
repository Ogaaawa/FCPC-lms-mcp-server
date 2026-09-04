"""Check a running server from outside, over the public address.

Everything here is unauthenticated, so it can be run from anywhere - another
machine, a phone, a monitoring job - without holding a Moodle token. It
answers "is the service up and correctly exposed?", not "is anybody's data
correct".

Usage:
    python healthcheck.py https://ai.example.edu/mcp
    python healthcheck.py https://ai.example.edu/mcp --quiet

Exit code 0 if healthy, 1 if not, so it can drive an alert.
"""
import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request

TIMEOUT = 20
FAILURES = []
QUIET = False


def _context():
    """Trust the usual certificate authorities.

    A Python installed from python.org on macOS does not read the system
    keychain, so verification fails on a perfectly good certificate. certifi
    ships with most environments and fixes that; fall back to the default
    when it is absent.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


CONTEXT = _context()


def get(url, method="GET", body=None, headers=None):
    request = urllib.request.Request(url, method=method, data=body)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT,
                                    context=CONTEXT) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def check(label, ok, detail=""):
    if not QUIET:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}"
              + (f"\n         {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)
    return ok


def main():
    parser = argparse.ArgumentParser(description="Check a deployed server from outside")
    parser.add_argument("url", help="the connector URL, ending in /mcp")
    parser.add_argument("--quiet", action="store_true",
                        help="print only a single line of output")
    args = parser.parse_args()

    global QUIET
    QUIET = args.quiet

    mcp = args.url.rstrip("/")
    if not mcp.endswith("/mcp"):
        print("The URL should end in /mcp - that is what students register.")
        return 1
    base = mcp[: -len("/mcp")]

    if not args.quiet:
        print(f"Checking {mcp}\n")

    started = time.time()

    # -- the address is reachable at all, over HTTPS
    try:
        status, headers, raw = get(f"{base}/.well-known/oauth-protected-resource")
    except Exception as e:
        if args.quiet:
            print(f"UNREACHABLE {mcp} {type(e).__name__}")
        else:
            print(f"  [FAIL] Cannot reach the server\n         {type(e).__name__}: {e}")
            print("\nUNHEALTHY - the address is not answering. The server or "
                  "the tunnel is down.")
        return 1

    ok = check("Answers on the public address", status == 200, f"HTTP {status}")
    if ok:
        try:
            meta = json.loads(raw)
            check("Points at itself as the protected resource",
                  meta.get("resource", "").rstrip("/") == mcp,
                  meta.get("resource", ""))
        except Exception as e:
            check("Protected resource metadata is valid JSON", False, str(e))

    # -- the authorization server is advertised over HTTPS
    status, _, raw = get(f"{base}/.well-known/oauth-authorization-server")
    if check("Publishes its authorization server metadata", status == 200,
             f"HTTP {status}"):
        try:
            meta = json.loads(raw)
            endpoints = [meta.get(k, "") for k in
                         ("authorization_endpoint", "token_endpoint",
                          "registration_endpoint")]
            check("Every endpoint is HTTPS",
                  all(e.startswith("https://") for e in endpoints),
                  " ".join(endpoints))
            check("Offers dynamic client registration",
                  bool(meta.get("registration_endpoint")))
            check("Requires PKCE",
                  "S256" in (meta.get("code_challenge_methods_supported") or []))
            check("Supports refresh tokens",
                  "refresh_token" in (meta.get("grant_types_supported") or []))
        except Exception as e:
            check("Authorization server metadata is valid JSON", False, str(e))

    # -- data is not served to strangers
    status, headers, _ = get(
        mcp, method="POST",
        body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list",
                         "params": {}}).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"})
    check("Refuses an unauthenticated request", status == 401, f"HTTP {status}")
    challenge = headers.get("WWW-Authenticate", "") or headers.get("www-authenticate", "")
    check("Tells the client where to sign in",
          "resource_metadata=" in challenge, challenge[:90])

    # -- the sign-in page is being served, and rejects a made-up link
    status, _, raw = get(f"{base}/login?k=not-a-real-key")
    check("Sign-in page is alive and rejects a forged link", status == 400,
          f"HTTP {status}")

    elapsed = time.time() - started

    if args.quiet:
        state = "HEALTHY" if not FAILURES else f"UNHEALTHY ({len(FAILURES)} failed)"
        print(f"{state} {mcp} {elapsed:.1f}s")
        return 0 if not FAILURES else 1

    print()
    if FAILURES:
        print(f"UNHEALTHY - {len(FAILURES)} check(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1

    print(f"HEALTHY - answered in {elapsed:.1f}s")
    print("\nThis says the service is up and correctly exposed. It does not "
          "test\nanybody's data; that needs a token and selftest.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
