#!/usr/bin/env python3
"""Nexus Memory System — MCP Server
Provides memory read/write/search as MCP tools + resources for Claude.
Protocol: JSON-RPC 2.0 over stdio (MCP 2024-11-05)"""

import json, sys, os, glob, re, math
from datetime import datetime, date

MEMORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory")
TIERS = ["episodic", "semantic", "procedural", "reflections", "working", "core", "archive"]

# ─── helpers ──────────────────────────────────────────────────────────

def parse_frontmatter(text, field):
    """Extract a YAML frontmatter field value from markdown text."""
    m = re.search(rf'^{re.escape(field)}:\s*(.+)$', text, re.MULTILINE)
    if m:
        val = m.group(1).strip()
        val = re.sub(r'\s*#.*$', '', val).strip()
        return val
    m = re.search(rf'^\s+{re.escape(field)}:\s*(.+)$', text, re.MULTILINE)
    if m:
        val = m.group(1).strip()
        val = re.sub(r'\s*#.*$', '', val).strip()
        return val
    return None

def list_memory_files():
    """Return list of {tier, name, path, title, strength, type} for all memories."""
    results = []
    for tier in TIERS:
        tier_dir = os.path.join(MEMORY_DIR, tier)
        if not os.path.isdir(tier_dir):
            continue
        for f in sorted(glob.glob(os.path.join(tier_dir, "*.md"))):
            name = os.path.splitext(os.path.basename(f))[0]
            with open(f, encoding="utf-8") as fh:
                content = fh.read()
            title = ""
            for line in content.splitlines():
                if line.startswith("# "):
                    title = line[2:]
                    break
            strength = parse_frontmatter(content, "strength") or "1.0"
            type_ = parse_frontmatter(content, "type") or tier
            results.append({
                "uri": f"nexus://{tier}/{name}",
                "name": name,
                "title": title,
                "tier": tier,
                "strength": float(strength),
                "type": type_,
                "path": os.path.relpath(f, MEMORY_DIR),
            })
    return results

def calc_stats():
    files = list_memory_files()
    total = len(files)
    by_tier = {}
    for f in files:
        by_tier.setdefault(f["tier"], []).append(f)
    lines = [f"Total: {total} memories"]
    for tier in TIERS:
        entries = by_tier.get(tier, [])
        if not entries:
            continue
        avg_s = sum(e["strength"] for e in entries) / len(entries)
        decaying = sum(1 for e in entries if 0.2 <= e["strength"] < 0.4)
        archived = sum(1 for e in entries if e["strength"] < 0.2)
        active = len(entries) - decaying - archived
        lines.append(f"  {tier}: {len(entries)} files | avg strength {avg_s:.2f} | {active} active, {decaying} decaying, {archived} archived")
    return "\n".join(lines)

# ─── MCP handlers ─────────────────────────────────────────────────────

def handle_initialize(req_id):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"resources": {}, "tools": {}},
        "serverInfo": {"name": "nexus-mcp", "version": "1.0"},
    }

def handle_resources_list(req_id):
    files = list_memory_files()
    resources = []
    for f in files:
        resources.append({
            "uri": f["uri"],
            "name": f["title"] or f["name"],
            "description": f"[{f['tier']}] strength: {f['strength']:.2f}",
            "mimeType": "text/markdown",
        })
    # Add stats as a virtual resource
    resources.append({
        "uri": "nexus://stats",
        "name": "Memory Statistics",
        "description": "Nexus memory health overview",
        "mimeType": "text/plain",
    })
    return {"resources": resources}

def handle_resources_read(req_id, uri):
    if uri == "nexus://stats":
        return {"contents": [{"uri": uri, "mimeType": "text/plain", "text": calc_stats()}]}
    # Parse nexus://tier/name
    m = re.match(r"^nexus://(\w+)/(.+)$", uri)
    if not m:
        return None, {"code": -32602, "message": f"Invalid URI: {uri}"}
    tier, name = m.group(1), m.group(2)
    # Try direct path
    for ext in ["", ".md"]:
        path = os.path.join(MEMORY_DIR, tier, name + ext)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]}
    return None, {"code": -32602, "message": f"Memory not found: {uri}"}

TOOL_DEFS = [
    {
        "name": "search",
        "description": "Search across all memory files by keyword. Returns matching file names, titles, strengths, and context snippets.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Keyword or phrase to search for"}},
            "required": ["query"],
        },
    },
    {
        "name": "stats",
        "description": "Show memory health statistics: file counts per tier, average strength, active/decaying/archived counts.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "save",
        "description": "Save a new memory to a specified tier. Creates a markdown file with frontmatter. Use for recording new information, preferences, or experiences.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tier": {
                    "type": "string",
                    "enum": ["episodic", "semantic", "procedural", "reflection", "working"],
                    "description": "Memory tier: episodic (experiences), semantic (facts/preferences), procedural (workflows), reflection (meta), working (in-session)",
                },
                "name": {"type": "string", "description": "Filename slug (no extension, use dashes: my-memory-name)"},
                "content": {"type": "string", "description": "Full markdown content of the memory (including title heading)"},
                "tags": {"type": "string", "description": "Comma-separated tags (optional)"},
            },
            "required": ["tier", "name", "content"],
        },
    },
    {
        "name": "touch",
        "description": "Boost a memory's strength (simulate access, counteracts Ebbinghaus decay). Use this when a memory is referenced or found relevant.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Memory filename (with or without .md extension)"},
                "boost": {"type": "number", "description": "Strength boost amount (default 0.15, max 1.0)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "decay",
        "description": "Run a dry-run decay check. Calculates Ebbinghaus decay for all memories and reports which would be archived. Does NOT modify any files.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

def handle_tools_list(req_id):
    return {"tools": TOOL_DEFS}

SEARCH_CACHE = {}
def handle_tools_call(req_id, name, args):
    if name == "search":
        query = args.get("query", "").lower()
        if not query:
            return {"content": [{"type": "text", "text": "No query provided."}]}, None
        files = list_memory_files()
        results = []
        for f in files:
            with open(os.path.join(MEMORY_DIR, f["path"]), encoding="utf-8") as fh:
                text = fh.read().lower()
            if query in text:
                lines = text.splitlines()
                snippets = []
                for i, line in enumerate(lines):
                    if query in line.lower():
                        start = max(0, i - 1)
                        end = min(len(lines), i + 2)
                        snippet = "\n".join(lines[start:end]).strip()
                        if len(snippet) > 200:
                            snippet = snippet[:200] + "..."
                        snippets.append(snippet)
                results.append({
                    "title": f["title"] or f["name"],
                    "path": f["path"],
                    "tier": f["tier"],
                    "strength": f["strength"],
                    "snippets": snippets[:3],
                })
        if not results:
            return {"content": [{"type": "text", "text": f"No memories matched '{query}'."}]}, None
        lines = [f"Found {len(results)} memory(s) for '{query}':", ""]
        for r in results:
            lines.append(f"  [{r['tier']}] {r['title']}  (strength: {r['strength']:.2f})")
            lines.append(f"         path: {r['path']}")
            for s in r["snippets"]:
                lines.append(f"         > {s}")
            lines.append("")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}, None

    elif name == "stats":
        return {"content": [{"type": "text", "text": calc_stats()}]}, None

    elif name == "save":
        tier = args["tier"]
        name_slug = args["name"]
        content = args["content"]
        tags = args.get("tags", "")

        tier_dir_map = {
            "episodic": "episodic",
            "semantic": "semantic",
            "procedural": "procedural",
            "reflection": "reflections",
            "working": "working",
        }
        dir_name = tier_dir_map.get(tier)
        if not dir_name:
            return None, {"code": -32602, "message": f"Invalid tier: {tier}"}

        target_dir = os.path.join(MEMORY_DIR, dir_name)
        os.makedirs(target_dir, exist_ok=True)
        filepath = os.path.join(target_dir, name_slug + ".md")

        if os.path.exists(filepath):
            return None, {"code": -32602, "message": f"Memory already exists: {name_slug}.md"}

        today = date.today().isoformat()
        tag_line = f"  tags: [{tags}]" if tags else "  tags: []"
        frontmatter = f"""---
type: {tier}
strength: 1.0
created: {today}
updated: {today}
{tag_line}
links: ""
source: mcp
access_count: 1
last_accessed: {today}
---

{content}
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(frontmatter)
        return {"content": [{"type": "text", "text": f"Saved: {os.path.relpath(filepath, MEMORY_DIR)}"}]}, None

    elif name == "touch":
        target = args["name"]
        boost = min(float(args.get("boost", 0.15)), 1.0)
        target_lower = target.lower().replace(".md", "")

        files = list_memory_files()
        match = None
        for f in files:
            if f["name"].lower() == target_lower:
                match = f
                break
        if not match:
            return None, {"code": -32602, "message": f"Memory not found: {target}"}

        filepath = os.path.join(MEMORY_DIR, match["path"])
        with open(filepath, encoding="utf-8") as fh:
            text = fh.read()

        old_s = match["strength"]
        new_s = min(old_s + boost, 1.0)
        text = re.sub(r'^(strength:\s*)[\d.]+', rf'\g<1>{new_s:.2f}', text, flags=re.MULTILINE)
        text = re.sub(r'^(\s+strength:\s*)[\d.]+', rf'\g<1>{new_s:.2f}', text, flags=re.MULTILINE)

        today = date.today().isoformat()
        if re.search(r'last_accessed:', text):
            text = re.sub(r'^(last_accessed:\s*).*', rf'\g<1>{today}', text, flags=re.MULTILINE)
            text = re.sub(r'^(\s+last_accessed:\s*).*', rf'\g<1>{today}', text, flags=re.MULTILINE)
        if re.search(r'access_count:', text):
            ac = parse_frontmatter(text, "access_count")
            new_ac = int(ac) + 1 if ac else 1
            text = re.sub(r'^(access_count:\s*)\d+', rf'\g<1>{new_ac}', text, flags=re.MULTILINE)
            text = re.sub(r'^(\s+access_count:\s*)\d+', rf'\g<1>{new_ac}', text, flags=re.MULTILINE)

        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(text)
        return {"content": [{"type": "text", "text": f"Touched {target}: strength {old_s:.2f} → {new_s:.2f}"}]}, None

    elif name == "decay":
        files = list_memory_files()
        today_epoch = datetime.now().timestamp()
        decay_map = {
            "semantic": 90, "episodic": 30, "procedural": 180,
            "reflection": 60, "working": 7, "core": 999999,
        }
        results_lines = ["Decay check (dry-run):", ""]
        for f in files:
            with open(os.path.join(MEMORY_DIR, f["path"]), encoding="utf-8") as fh:
                text = fh.read()
            created = parse_frontmatter(text, "created") or "2026-05-18"
            try:
                dt = datetime.strptime(created[:10], "%Y-%m-%d")
                days = max(1, (datetime.now() - dt).days)
            except ValueError:
                days = 1
            dc = decay_map.get(f["type"], 30)
            new_s = f["strength"] * math.exp(-days / dc)
            new_s = max(0.05, min(1.0, new_s))
            if abs(new_s - f["strength"]) > 0.01:
                status = ""
                if new_s < 0.2:
                    status = " [WOULD ARCHIVE]"
                elif new_s < 0.4:
                    status = " [DECAYING]"
                results_lines.append(f"  {f['name']}: {f['strength']:.2f} → {new_s:.2f} ({days}d){status}")
        if len(results_lines) == 2:
            results_lines.append("  All memories at expected strength.")
        return {"content": [{"type": "text", "text": "\n".join(results_lines)}]}, None

    return None, {"code": -32601, "message": f"Unknown tool: {name}"}

# ─── main loop ────────────────────────────────────────────────────────

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        params = msg.get("params", {})
        req_id = msg.get("id")

        try:
            if method == "initialize":
                result = handle_initialize(req_id)
                respond(req_id, result)
            elif method == "notifications/initialized":
                pass
            elif method == "notifications/cancelled":
                pass
            elif method == "resources/list":
                result = handle_resources_list(req_id)
                respond(req_id, result)
            elif method == "resources/read":
                uri = params.get("uri", "")
                result, err = handle_resources_read(req_id, uri)
                if err:
                    respond(req_id, error=err)
                else:
                    respond(req_id, result)
            elif method == "tools/list":
                result = handle_tools_list(req_id)
                respond(req_id, result)
            elif method == "tools/call":
                name = params.get("name", "")
                args = params.get("arguments", {})
                result, err = handle_tools_call(req_id, name, args)
                if err:
                    respond(req_id, error=err)
                else:
                    respond(req_id, result)
            else:
                if req_id:
                    respond(req_id, error={"code": -32601, "message": f"Method not found: {method}"})
        except Exception as e:
            if req_id:
                respond(req_id, error={"code": -32603, "message": str(e)})

def respond(req_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": req_id}
    if error:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()

if __name__ == "__main__":
    main()
