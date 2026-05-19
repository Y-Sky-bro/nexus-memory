#!/usr/bin/env python3
"""Nexus v2 — REST API Server
Uses nexus_engine.py for smart retrieval, pointer generation, token tracking.
Hindsight-compatible endpoints for Hermes agent integration.
Zero heavy dependencies (uses Python stdlib http.server + engine).
"""

import argparse
import json
import os
import re
import sys
import traceback
from datetime import datetime, date
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(SCRIPT_DIR, "memory")

# ─── Engine import ─────────────────────────────────────────────────────
sys.path.insert(0, SCRIPT_DIR)
from nexus_engine import keyword_retrieve, generate_pointer, TokenTracker, calculate_decay, consolidate, assemble_context, CONFIG

_tt = TokenTracker()
TIERS = ["episodic", "semantic", "procedural", "reflections", "working", "core", "archive"]

# ─── Legacy token log bridge ───────────────────────────────────────────
_legacy_log_path = os.path.join(MEMORY_DIR, ".token_usage.json")

def _load_legacy_log():
    if os.path.exists(_legacy_log_path):
        try:
            with open(_legacy_log_path) as f:
                return json.load(f)
        except:
            pass
    return {"total_saved": 0, "total_spent": 0, "operations": [], "daily": {}}

def _log_operation(op, saved=0, spent=0):
    _tt.log_operation(op, tokens_saved=saved, tokens_spent=spent, detail="")

# ─── Core memory operations ──────────────────────────────────────────

def parse_frontmatter(text, field):
    for pat in [rf'^{re.escape(field)}:\s*(.+)$', rf'^\s+{re.escape(field)}:\s*(.+)$']:
        m = re.search(pat, text, re.MULTILINE)
        if m:
            val = re.sub(r'\s*#.*$', '', m.group(1).strip()).strip()
            if val:
                return val
    return None

def list_memories(tier=None, search_term=None):
    results = []
    tiers_to_check = [tier] if tier else TIERS
    for t in tiers_to_check:
        d = os.path.join(MEMORY_DIR, t)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".md"):
                continue
            fp = os.path.join(d, f)
            with open(fp, encoding="utf-8") as fh:
                content = fh.read()
            name = os.path.splitext(f)[0]
            title = ""
            for line in content.splitlines():
                if line.startswith("# "):
                    title = line[2:]
                    break
            strength = parse_frontmatter(content, "strength") or "1.0"
            type_ = parse_frontmatter(content, "type") or t
            if search_term and search_term.lower() not in content.lower() and \
               search_term.lower() not in name.lower() and \
               search_term.lower() not in title.lower():
                continue
            results.append({
                "id": f"{t}/{name}",
                "name": name,
                "title": title or name,
                "tier": t,
                "type": type_,
                "strength": float(strength),
                "content": content,
                "path": os.path.relpath(fp, MEMORY_DIR),
                "size_bytes": len(content.encode("utf-8")),
            })
    return results

def search_memories(query, bank_id=None, max_results=10):
    """Engine-powered search with tier boosting."""
    tier_boost = {"semantic": 2.0, "core": 2.0, "procedural": 1.5}
    results = keyword_retrieve(query, max_results=max_results, tier_boost=tier_boost)
    # Map engine results to REST format
    mapped = []
    seen = set()
    for m in results:
        mid = f"{m['tier']}/{m['name']}"
        if mid not in seen:
            seen.add(mid)
            # Get strength from file
            fp = os.path.join(MEMORY_DIR, m["path"])
            strength = 1.0
            try:
                with open(fp, encoding="utf-8") as fh:
                    s = parse_frontmatter(fh.read(), "strength")
                    if s:
                        strength = float(s)
            except:
                pass
            mapped.append({
                "id": mid,
                "name": m["name"],
                "title": m["title"],
                "tier": m["tier"],
                "type": m.get("type", m["tier"]),
                "strength": strength,
                "content": m["content"],
                "path": m["path"],
                "score": strength,
            })
    return mapped[:max_results]

def retain_memory(bank_id, content, tags=None, context=None):
    name_slug = re.sub(r'[^a-z0-9-]', '', bank_id.lower().replace(' ', '-'))
    if not name_slug:
        name_slug = f"memory-{int(time.time())}"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{name_slug}-{timestamp}" if len(name_slug) < 40 else name_slug
    filepath = os.path.join(MEMORY_DIR, "episodic", f"{safe_name}.md")
    tag_str = ", ".join(tags) if tags else bank_id
    today = date.today().isoformat()
    frontmatter = f"""---
type: episodic
strength: 1.0
created: {today}
updated: {today}
tags: [{tag_str}]
source: hindsight-bridge
access_count: 1
last_accessed: {today}
---

{content}
"""
    os.makedirs(os.path.join(MEMORY_DIR, "episodic"), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(frontmatter)
    _log_operation("retain", saved=50)
    return {"id": safe_name, "path": os.path.relpath(filepath, MEMORY_DIR)}

def reflect(bank_id, query, context=None):
    """Synthesize across memories using engine."""
    memories = search_memories(query, bank_id, max_results=5)
    if not memories:
        return {"text": f"I don't have any memories about '{query}' yet.", "based_on": []}
    parts = []
    for m in memories[:5]:
        body = re.sub(r'^---.*?---\s*', '', m["content"], flags=re.DOTALL).strip()
        parts.append({"memory_id": m["id"], "content": body[:1000], "strength": m["strength"]})
    ctx = f"Context: {context}\n\n" if context else ""
    memories_text = "\n\n".join([f"---\n{p['content']}\n(strength: {p['strength']:.2f})" for p in parts])
    text = f"""{ctx}Based on my memories related to "{query}":

{memories_text}"""
    _log_operation("reflect", saved=200)
    return {"text": text, "based_on": parts}

# ─── REST Handler ───────────────────────────────────────────────────────

class NexusHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write(f"[Nexus] {args[0]} {args[1]} {args[2]}\n")

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def _send_error(self, status, message):
        self._send_json({"error": message}, status)

    _V1_RECALL = re.compile(r'^/v1/default/banks/([^/]+)/memories/recall$')
    _V1_RETAIN = re.compile(r'^/v1/default/banks/([^/]+)/memories$')
    _V1_REFLECT = re.compile(r'^/v1/default/banks/([^/]+)/reflect$')
    _V1_LIST = re.compile(r'^/v1/default/banks/([^/]+)/memories/list$')

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            raw = self.rfile.read(length)
            for enc in ("utf-8", "gbk", "gb2312", "cp936"):
                try:
                    return json.loads(raw.decode(enc))
                except (UnicodeDecodeError, UnicodeError):
                    continue
            return json.loads(raw.decode("utf-8", errors="replace"))
        return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        try:
            # Health check
            if path in ("/health", "/v1/default/health"):
                self._send_json({
                    "status": "ok",
                    "service": "nexus-v2",
                    "version": "2.0.0",
                    "timestamp": datetime.now().isoformat(),
                    "engine": "nexus_engine.py",
                    "retrieval": "keyword+scoring+tier_boost",
                })
                _log_operation("health")

            elif path == "/version":
                self._send_json({
                    "version": "2.0.0",
                    "service": "nexus-memory",
                    "api_compat": ["hindsight"],
                })

            # Stats (with engine economics)
            elif path == "/nexus/stats":
                stats = _calc_stats()
                s = _tt.get_summary()
                legacy = _load_legacy_log()
                stats["token_economics"] = {
                    "engine_saved": s["total_tokens_saved"],
                    "engine_spent": s["total_tokens_spent"],
                    "legacy_saved": legacy["total_saved"],
                    "net_efficiency": (s["total_tokens_saved"] + legacy["total_saved"]) - s["total_tokens_spent"],
                    "net_cost_saved_usd": s["net_cost_saved_usd"],
                    "efficiency_ratio": s["efficiency_ratio"],
                    "today": s["today"],
                }
                self._send_json(stats)

            # List memories
            elif path == "/nexus/memories":
                tier = params.get("tier", [None])[0]
                q = params.get("q", [None])[0]
                memories = list_memories(tier=tier, search_term=q)
                self._send_json({
                    "count": len(memories),
                    "memories": [{"id": m["id"], "title": m["title"], "tier": m["tier"],
                                  "strength": m["strength"], "type": m["type"]} for m in memories],
                })

            # Recall (Hindsight-compatible, engine-powered)
            elif "/memories/recall" in path or path.endswith("/recall"):
                q = params.get("query", [None])[0]
                bank_id = params.get("bank_id", ["default"])[0]
                if not q:
                    self._send_error(400, "query parameter required")
                    return
                results = search_memories(q, bank_id)
                self._send_json({
                    "results": [{"text": m["content"][:2000], "score": m.get("score", m["strength"]),
                                 "id": m["id"], "type": m["type"], "tier": m["tier"]} for m in results],
                    "count": len(results),
                })
                _log_operation("recall", saved=100)

            # Reflect
            elif "/reflect" in path:
                q = params.get("query", [None])[0]
                bank_id = params.get("bank_id", ["default"])[0]
                if not q:
                    self._send_error(400, "query parameter required")
                    return
                result = reflect(bank_id, q)
                self._send_json({"text": result["text"], "based_on": result["based_on"]})

            # Read specific memory
            elif path.startswith("/nexus/memory/"):
                mem_id = path[len("/nexus/memory/"):]
                memories = list_memories()
                for m in memories:
                    if m["id"] == mem_id:
                        self._send_json(m)
                        return
                self._send_error(404, f"Memory not found: {mem_id}")

            # Token economics
            elif path == "/nexus/tokens":
                s = _tt.get_summary()
                legacy = _load_legacy_log()
                self._send_json({"engine": s, "legacy": legacy})

            # ─── Engine endpoints ────────────────────────────────────
            elif path == "/nexus/engine/retrieve":
                q = params.get("query", [None])[0]
                if not q:
                    self._send_error(400, "query required")
                    return
                ctx = assemble_context(q, max_tokens=CONFIG.get("token_budget", {}).get("max_context_tokens", 4000))
                self._send_json({"context": ctx, "length": len(ctx)})

            elif path == "/nexus/engine/pointers":
                q = params.get("query", [None])[0]
                if not q:
                    self._send_error(400, "query required")
                    return
                memories = keyword_retrieve(q, max_results=5)
                pointers = [generate_pointer(m) for m in memories]
                self._send_json({"pointers": pointers, "count": len(pointers)})

            elif path == "/nexus/engine/decay":
                dry = params.get("dry_run", ["true"])[0].lower() == "true"
                result = calculate_decay(dry_run=dry)
                self._send_json(result)

            elif path == "/nexus/engine/consolidate":
                dry = params.get("dry_run", ["true"])[0].lower() == "true"
                result = consolidate(dry_run=dry)
                self._send_json(result)

            else:
                self._send_error(404, f"Not found: {path}")

        except Exception as e:
            self._send_error(500, str(e))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        try:
            body = self._read_body()

            # ── Hindsight v1-compatible routes ────────────────────────
            m = self._V1_RECALL.match(path)
            if m:
                bank_id = m.group(1)
                q = body.get("query", "")
                if not q:
                    self._send_error(400, "query required")
                    return
                hits = search_memories(q, bank_id)
                self._send_json({
                    "results": [{"text": hit["content"][:2000], "score": hit.get("score", hit["strength"]),
                                 "id": hit["id"], "type": hit.get("type", ""), "tags": []} for hit in hits],
                    "count": len(hits),
                    "trace": None,
                })
                _log_operation("recall", saved=100)
                return

            m = self._V1_RETAIN.match(path)
            if m:
                bank_id = m.group(1)
                items = body.get("items", [{"content": body.get("content", "")}])
                results = []
                for item in items:
                    r = retain_memory(bank_id, item.get("content", ""), tags=item.get("tags", body.get("document_tags")))
                    results.append(r["id"])
                self._send_json({"status": "stored", "ids": results}, 201)
                return

            m = self._V1_REFLECT.match(path)
            if m:
                bank_id = m.group(1)
                q = body.get("query", "")
                ctx = body.get("context", "")
                if not q:
                    self._send_error(400, "query required")
                    return
                result = reflect(bank_id, q, context=ctx)
                self._send_json({"text": result["text"], "based_on": result["based_on"]})
                return

            m = self._V1_LIST.match(path)
            if m:
                bank_id = m.group(1)
                mems = list_memories(search_term=body.get("query", ""))
                self._send_json({
                    "results": [{"id": mem["id"], "text": mem["content"][:2000],
                                 "type": mem["type"], "tags": []} for mem in mems],
                    "count": len(mems),
                })
                return

            # POST /recall (backward-compat, also used by some Hindsight clients)
            if path.endswith("/recall"):
                q = body.get("query", "")
                bank_id = body.get("bank_id", "default") or params.get("bank_id", ["default"])[0]
                if not q:
                    self._send_error(400, "query required")
                    return
                hits = search_memories(q, bank_id)
                self._send_json({
                    "results": [{"text": hit["content"][:2000], "score": hit.get("score", hit["strength"]),
                                 "id": hit["id"]} for hit in hits],
                    "count": len(hits),
                })
                _log_operation("recall", saved=100)
                return

            # Retain
            if "/memories/retain" in path or path.endswith("/retain"):
                content = body.get("content", "")
                if not content:
                    self._send_error(400, "content required")
                    return
                bank_id = params.get("bank_id", ["default"])[0] or body.get("bank_id", "hermes")
                tags = body.get("tags", [bank_id])
                result = retain_memory(bank_id, content, tags=tags)
                self._send_json({"status": "stored", "id": result["id"]}, 201)

            # Reflect via POST
            elif "/reflect" in path:
                q = body.get("query", "")
                bank_id = body.get("bank_id", "default") or params.get("bank_id", ["default"])[0]
                ctx = body.get("context", "")
                if not q:
                    self._send_error(400, "query required")
                    return
                result = reflect(bank_id, q, context=ctx)
                self._send_json({"text": result["text"], "based_on": result["based_on"]})

            # Search (engine-powered)
            elif path.endswith("/search"):
                q = body.get("query", "")
                bank_id = body.get("bank_id", "default")
                if not q:
                    self._send_error(400, "query required")
                    return
                results = search_memories(q, bank_id)
                self._send_json({
                    "results": [{"text": m["content"][:2000], "score": m.get("score", m["strength"]),
                                 "id": m["id"]} for m in results],
                    "count": len(results),
                })

            # Batch retain
            elif path.endswith("/retain/batch"):
                items = body.get("items", [])
                results = []
                for item in items:
                    r = retain_memory(body.get("bank_id", "hermes"), item.get("content", ""), tags=item.get("tags"))
                    results.append(r)
                self._send_json({"status": "stored", "count": len(results), "ids": results}, 201)

            # Clear memories
            elif path.endswith("/memories/clear"):
                tier = body.get("tier") or params.get("tier", [None])[0]
                if tier:
                    d = os.path.join(MEMORY_DIR, tier)
                    if os.path.isdir(d):
                        for f in os.listdir(d):
                            if f.endswith(".md"):
                                os.remove(os.path.join(d, f))
                self._send_json({"status": "cleared", "tier": tier or "all"})

            # Tokens
            elif path == "/nexus/tokens":
                s = _tt.get_summary()
                legacy = _load_legacy_log()
                self._send_json({"engine": s, "legacy": legacy})

            # Engine operations via POST
            elif path == "/nexus/engine/decay":
                dry = body.get("dry_run", True)
                result = calculate_decay(dry_run=dry)
                self._send_json(result)

            elif path == "/nexus/engine/consolidate":
                dry = body.get("dry_run", True)
                result = consolidate(dry_run=dry)
                self._send_json(result)

            elif path == "/nexus/engine/retrieve":
                q = body.get("query", "")
                if not q:
                    self._send_error(400, "query required")
                    return
                max_tokens = body.get("max_tokens", 4000)
                ctx = assemble_context(q, max_tokens=max_tokens)
                self._send_json({"context": ctx, "length": len(ctx)})

            elif path == "/nexus/engine/pointers":
                q = body.get("query", "")
                if not q:
                    self._send_error(400, "query required")
                    return
                memories = keyword_retrieve(q, max_results=5)
                pointers = [generate_pointer(m) for m in memories]
                self._send_json({"pointers": pointers, "count": len(pointers)})

            else:
                self._send_error(404, f"Not found: {path}")

        except json.JSONDecodeError:
            self._send_error(400, "Invalid JSON body")
        except Exception as e:
            self._send_error(500, f"{e}\n{traceback.format_exc()}")

def _calc_stats():
    mems = list_memories()
    by_tier = {}
    for m in mems:
        by_tier.setdefault(m["tier"], []).append(m)
    tier_stats = {}
    for t in TIERS:
        entries = by_tier.get(t, [])
        if not entries:
            continue
        avg_s = sum(e["strength"] for e in entries) / len(entries)
        decaying = sum(1 for e in entries if 0.2 <= e["strength"] < 0.4)
        archived = sum(1 for e in entries if e["strength"] < 0.2)
        active = len(entries) - decaying - archived
        tier_stats[t] = {"count": len(entries), "avg_strength": round(avg_s, 2),
                         "active": active, "decaying": decaying, "archived": archived}
    return {"total_memories": len(mems), "tiers": tier_stats}


def run_server(port=9177, host="0.0.0.0"):
    server = HTTPServer((host, port), NexusHTTPHandler)
    print(f"\n{'='*50}")
    print(f"  Nexus v2 + Engine")
    print(f"  Listening: http://{host}:{port}")
    print(f"  Memory:   {MEMORY_DIR}")
    print(f"  Engine:   keyword_retrieve + pointers + TokenTracker")
    print(f"  Compat:   Hindsight API + Nexus engine endpoints")
    print(f"{'='*50}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nexus v2 REST Server")
    parser.add_argument("--port", type=int, default=9177, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    args = parser.parse_args()
    run_server(args.port, args.host)
