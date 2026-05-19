#!/usr/bin/env python3
"""Nexus 24/7 Monitor — health checks, token tracking, daily reports.

Usage:
    python nexus_monitor.py check     — single health check
    python nexus_monitor.py daemon    — run every 10 min (background)
    python nexus_monitor.py report    — print daily summary
"""
import json, os, sys, time, subprocess, urllib.request
from datetime import datetime, date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
MONITOR_LOG = SCRIPT_DIR / "memory" / ".monitor_log.json"

SERVICES = {
    "nexus_rest": {"port": 9177, "type": "http", "url": "http://localhost:9177/health"},
    "hub":       {"port": 3005, "type": "http", "url": "http://localhost:3005/"},
    "postgresql":{"port": 5444, "type": "tcp"},
}

def check_port(port):
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=5)
        return f":{port} " in r.stdout and "LISTENING" in r.stdout
    except:
        return False

def check_http(url):
    try:
        urllib.request.urlopen(url, timeout=3)
        return True
    except:
        return False

def check_service(name, info):
    if info["type"] == "http":
        ok = check_http(info["url"])
    else:
        ok = check_port(info["port"])
    return {"name": name, "status": "ok" if ok else "fail", "port": info["port"], "time": datetime.now().isoformat()}

def load_log():
    if MONITOR_LOG.exists():
        try:
            return json.loads(MONITOR_LOG.read_text())
        except:
            pass
    return {"version": "1.0", "started": datetime.now().isoformat(), "checks": [], "hourly": {}, "daily": {}, "alerts": []}

def save_log(log):
    MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    MONITOR_LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False))

def cmd_check():
    log = load_log()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    hour = str(now.hour)

    results = [check_service(n, i) for n, i in SERVICES.items()]
    all_ok = all(r["status"] == "ok" for r in results)

    log.setdefault("checks", []).append({"timestamp": now.isoformat(), "services": {r["name"]: r for r in results}, "all_ok": all_ok})
    if len(log["checks"]) > 10000:
        log["checks"] = log["checks"][-10000:]

    hourly = log.setdefault("hourly", {}).setdefault(today, {}).setdefault(hour, {"ok": 0, "fail": 0, "total": 0})
    hourly["total"] += 1
    hourly["ok" if all_ok else "fail"] += 1

    log["last_check"] = now.isoformat()
    save_log(log)

    status = "OK" if all_ok else "FAIL"
    failed = [r["name"] for r in results if r["status"] == "fail"]
    msg = f"[{now.isoformat()[:19]}] {status} — all services healthy" if all_ok else f"[{now.isoformat()[:19]}] FAIL — {', '.join(failed)} down"
    print(msg)
    return all_ok

def cmd_report():
    log = load_log()
    checks = log.get("checks", [])
    if not checks:
        print("No monitoring data yet.")
        return

    total = len(checks)
    ok_count = sum(1 for c in checks if c.get("all_ok"))
    fail_count = total - ok_count
    uptime = (ok_count / total * 100) if total else 0

    svc_fails = {}
    for c in checks:
        for name, info in c.get("services", {}).items():
            if info.get("status") == "fail":
                svc_fails[name] = svc_fails.get(name, 0) + 1

    # Token economics
    tok_path = SCRIPT_DIR / "memory" / ".token_economics.json"
    tok_data = {}
    if tok_path.exists():
        try:
            tok_data = json.loads(tok_path.read_text())
        except:
            pass

    print("=" * 50)
    print("  Nexus 24h Monitoring Report")
    print("=" * 50)
    print(f"  Period:  {checks[0]['timestamp'][:19]}  →  {checks[-1]['timestamp'][:19]}")
    print(f"  Checks:  {total}  |  OK: {ok_count}  |  Fail: {fail_count}  |  Uptime: {uptime:.1f}%")
    print()
    if svc_fails:
        print("  Service Failures:")
        for name, count in sorted(svc_fails.items()):
            print(f"    {name}: {count}x")
    else:
        print("  All services: no failures")
    print()
    if tok_data:
        saved = tok_data.get("total_tokens_saved", 0)
        spent = tok_data.get("total_tokens_spent", 0)
        net = saved - spent
        cost = net / 1_000_000 * 3.0
        ratio = (saved / spent) if spent else 0
        print(f"  Token Economics:")
        print(f"    Saved:     {saved:>10,} tokens")
        print(f"    Spent:     {spent:>10,} tokens")
        print(f"    Net:       {net:>10,} tokens")
        print(f"    Cost:      ${cost:.4f} saved (@ $3/M)")
        print(f"    Ratio:     {ratio:.1f}x efficiency")
    print()

def cmd_daemon():
    print(f"[{datetime.now().isoformat()[:19]}] Monitor daemon started (every 10 min)")
    print(f"[{datetime.now().isoformat()[:19]}] Log: {MONITOR_LOG}")
    while True:
        cmd_check()
        time.sleep(1800)  # every 30 min (was 10 min — too aggressive for Windows)

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    {"check": cmd_check, "daemon": cmd_daemon, "report": cmd_report}.get(cmd, lambda: print("Usage: check|daemon|report"))()
