#!/usr/bin/env python3
"""Public HTTPS checks; uses Python's standard library and curl only."""
import argparse
import concurrent.futures
import datetime as dt
import json
import pathlib
import socket
import ssl
import subprocess
import time

HOSTS = ("creahub.art", "www.creahub.art")
URLS = (
    "https://creahub.art/login",
    "https://creahub.art/api/health",
    "https://www.creahub.art/",
)


def expiry_severity(seconds_remaining):
    if seconds_remaining <= 86400:
        return 2
    return 1 if seconds_remaining <= 7 * 86400 else 0


def tls_check(host):
    # Match the operating system trust store on macOS and Ubuntu runners.
    ca_file = next((p for p in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt")
                    if pathlib.Path(p).is_file()), None)
    context = ssl.create_default_context(cafile=ca_file)
    with socket.create_connection((host, 443), timeout=15) as raw:
        with context.wrap_socket(raw, server_hostname=host) as connection:
            cert = connection.getpeercert()
    expires = ssl.cert_time_to_seconds(cert["notAfter"])
    remaining = expires - time.time()
    result = {
        "target": host, "kind": "tls", "verified": True,
        "expires_utc": dt.datetime.fromtimestamp(expires, dt.timezone.utc).isoformat(),
        "days_remaining": round(remaining / 86400, 2),
    }
    severity = expiry_severity(remaining)
    if severity:
        result.update(issue="certificate_expiring", severity=severity)
    return result


def evaluate_http(url, status, final_url, verify, body):
    result = {"kind": "http", "target": url, "http_status": int(status),
              "final_url": final_url, "ssl_verify_result": int(verify)}
    if status != "200" or verify != "0":
        result.update(issue="http_or_tls_failure", severity=2)
    elif url.endswith("/api/health"):
        health = json.loads(body)
        if not isinstance(health, dict) or health.get("status") != "ok":
            result.update(issue="health_not_ok", severity=2)
        else:
            result["health_status"] = "ok"
    elif final_url != "https://creahub.art/login":
        result.update(issue="unexpected_redirect", severity=2)
    return result


def http_check(url):
    process = subprocess.run([
        "curl", "--silent", "--show-error", "--fail", "--location",
        "--proto", "=https", "--proto-redir", "=https", "--max-redirs", "5",
        "--connect-timeout", "15", "--max-time", "40",
        "--write-out", "\n__CHECK_METADATA__%{http_code} %{url_effective} %{ssl_verify_result}", url,
    ], capture_output=True, text=True, timeout=45)
    if process.returncode:
        raise RuntimeError(process.stderr.strip()[:300])
    body, meta = process.stdout.rsplit("\n__CHECK_METADATA__", 1)
    status, final_url, verify = meta.split()
    return evaluate_http(url, status, final_url, verify, body)


def check_with_retry(kind, target, delay=20):
    function = tls_check if kind == "tls" else http_check
    for attempt in (1, 2):
        try:
            result = function(target)
        except Exception as error:
            result = {"kind": kind, "target": target, "issue": "probe_failed", "severity": 2,
                      "error": f"{type(error).__name__}: {error}"[:400]}
        result["attempts"] = attempt
        if "issue" not in result:
            return result
        if attempt == 1:
            time.sleep(delay)
    return result


def transition(previous, checks, checked_date):
    """Re-alert only on new, recurring-after-recovery or more severe issues."""
    active = {f'{r["kind"]}|{r["target"]}|{r["issue"]}': r["severity"]
              for r in checks if "issue" in r}
    previous_active = previous.get("active", {})
    alert_keys = sorted(k for k, severity in active.items()
                        if severity > previous_active.get(k, 0))
    state = {"schema_version": 1, "last_check_date_utc": checked_date, "active": active}
    return state, alert_keys


def run_checks():
    tasks = [("tls", host) for host in HOSTS] + [("http", url) for url in URLS]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(check_with_retry, *task) for task in tasks]
        checks = [future.result() for future in futures]
    now = dt.datetime.now(dt.timezone.utc)
    return {"checked_at_utc": now.isoformat(),
            "status": "attention" if any("issue" in r for r in checks) else "ok",
            "checks": checks}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    result = run_checks()
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
