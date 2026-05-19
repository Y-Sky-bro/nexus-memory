#!/usr/bin/env python3
"""Nexus v2 — Memory Optimization Engine
Token-efficient memory with:
- Two-tier retrieval (keyword + semantic)
- Automatic consolidation (working→episodic→semantic)
- Pointer-based context injection (like Kronos)
- Token budget tracking & optimization
"""

import json, os, re, math, time, hashlib
from datetime import datetime, date
from pathlib import Path
from collections import defaultdict, Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(SCRIPT_DIR, "memory")

# ─── Configuration ────────────────────────────────────────────────────
CONFIG = {
    "tier_decay_days": {
        "working": 7,
        "episodic": 30,
        "semantic": 90,
        "procedural": 180,
        "reflection": 60,
    },
    "promote_after_days": {
        "working_to_episodic": 1,      # Working older than 1 day → episodic
        "episodic_to_semantic": 7,      # Episodic accessed 3+ times in 7 days → semantic
    },
    "token_budget": {
        "max_context_tokens": 4000,      # Max tokens for memory in context
        "pointer_tokens": 300,           # Kronos-style pointer size
        "recall_max_tokens": 1500,       # Max recall output
    },
    "cost_model": {
        "claude_input_per_mtok": 3.00,   # Sonnet 4.6 input pricing
        "claude_output_per_mtok": 15.00,
        "hindsight_retain_llm_save": 200, # Estimated tokens saved vs Hindsight
        "hindsight_recall_llm_save": 300,
    }
}

# ─── Frontmatter helpers ──────────────────────────────────────────────

def _parse_fm(text, field):
    for pattern in [rf'^{re.escape(field)}:\s*(.+)$', rf'^\s+{re.escape(field)}:\s*(.+)$']:
        m = re.search(pattern, text, re.MULTILINE)
        if m:
            val = re.sub(r'\s*#.*$', '', m.group(1).strip()).strip()
            if val:
                return val
    return None

def _update_fm(text, field, value):
    def replacer(m):
        return m.group(1) + value
    new_text = re.sub(
        rf'^({re.escape(field)}:\s*).*$',
        replacer,
        text, count=1, flags=re.MULTILINE
    )
    if new_text == text:
        new_text = re.sub(
            rf'^(\s+{re.escape(field)}:\s*).*$',
            replacer,
            text, count=1, flags=re.MULTILINE
        )
    return new_text

# ─── Memory listing ───────────────────────────────────────────────────

def _all_memories():
    results = []
    for tier in ["core", "episodic", "semantic", "procedural", "reflections", "working"]:
        d = os.path.join(MEMORY_DIR, tier)
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if not fname.endswith(".md"):
                continue
            fp = os.path.join(d, fname)
            with open(fp, encoding="utf-8") as fh:
                content = fh.read()
            name = os.path.splitext(fname)[0]
            title = ""
            for line in content.splitlines():
                if line.startswith("# "):
                    title = line[2:]
                    break
            results.append({
                "path": os.path.relpath(fp, MEMORY_DIR),
                "tier": tier,
                "name": name,
                "title": title or name,
                "content": content,
                "strength": float(_parse_fm(content, "strength") or 1.0),
                "type": _parse_fm(content, "type") or tier,
                "created": _parse_fm(content, "created") or "unknown",
                "tags": _parse_fm(content, "tags") or "",
                "access_count": int(_parse_fm(content, "access_count") or 0),
                "size_bytes": len(content.encode("utf-8")),
            })
    return results

# ─── Tier-1: Fast keyword retrieval (zero token cost) ─────────────────

def keyword_retrieve(query, max_results=5, tier_boost=None):
    """Fast keyword-based retrieval. No LLM, no embeddings, no cost."""
    memories = _all_memories()
    q = query.lower()
    q_words = set(q.split())

    def score(m):
        c = m["content"].lower()
        n = m["name"].lower()
        t = m["title"].lower()
        tags = m["tags"].lower()

        # Exact phrase match (highest)
        exact = c.count(q) * 3 + t.count(q) * 5 + n.count(q) * 4

        # Word-level matches
        word_matches = sum(1 for w in q_words if w in c)
        word_density = word_matches / max(1, len(q_words))

        # Title/tag boost
        title_bonus = 10 if any(w in t for w in q_words) else 0
        tag_bonus = 8 if any(w in tags for w in q_words) else 0

        # Freshness boost (newer = slightly higher)
        freshness = 0
        if m["created"] != "unknown":
            try:
                days_old = (datetime.now() - datetime.strptime(m["created"][:10], "%Y-%m-%d")).days
                freshness = max(0, 1 - days_old / 365) * 2
            except:
                pass

        # Tier boost
        tb = tier_boost.get(m["tier"], 1.0) if tier_boost else 1.0

        result = (exact + word_density * 5 + title_bonus + tag_bonus + freshness) * tb
        return max(0, result)

    scored = [(score(m), m) for m in memories if score(m) > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:max_results]]

# ─── Tier-2: Pointer generation (like Kronos) ─────────────────────────

def generate_pointer(memory):
    """Generate a compact 300-token pointer for a memory."""
    name = memory.get("title", memory["name"])
    tier = memory["tier"]
    strength = memory["strength"]
    created = memory["created"][:10] if memory["created"] != "unknown" else "?"
    tags = memory["tags"]

    # Extract first meaningful paragraph
    body = re.sub(r'^---.*?---\s*', '', memory["content"], flags=re.DOTALL).strip()
    first_line = body.split("\n")[0].strip() if body else ""
    first_line = re.sub(r'^#+\s*', '', first_line)  # remove heading markers

    # Extract key nouns/concepts (simple heuristic)
    body_words = body.lower().split()
    word_freq = Counter(body_words)
    # Filter stop words
    stop_words = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                  "being", "have", "has", "had", "do", "does", "did", "will",
                  "would", "could", "should", "may", "might", "shall", "can",
                  "to", "of", "in", "for", "on", "with", "at", "by", "from",
                  "as", "into", "through", "during", "before", "after", "above",
                  "below", "between", "out", "off", "over", "under", "again",
                  "further", "then", "once", "here", "there", "when", "where",
                  "why", "how", "all", "each", "every", "both", "few", "more",
                  "most", "other", "some", "such", "no", "nor", "not", "only",
                  "own", "same", "so", "than", "too", "very", "just", "because",
                  "and", "but", "or", "if", "while", "that", "this", "these",
                  "those", "it", "its", "you", "your", "he", "she", "they", "we",
                  "我", "的", "了", "是", "在", "有", "和", "就", "不", "人", "都",
                  "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你",
                  "会", "着", "没有", "看", "好", "自己", "这", "他", "她", "它"}
    keywords = [w for w, c in word_freq.most_common(20)
                if w not in stop_words and len(w) > 1][:8]

    pointer = {
        "id": f"{tier}/{memory['name']}",
        "title": name,
        "type": "memory",
        "tier": tier,
        "strength": round(strength, 2),
        "created": created,
        "tags": tags,
        "keywords": keywords,
        "summary": first_line[:200] if first_line else f"[{tier}] {name}",
        "token_estimate": min(len(body), 300),
    }
    return pointer

# ─── Context assembly (token-budgeted) ────────────────────────────────

def assemble_context(query, max_tokens=4000, include_pointers=True):
    """Assemble memory context within token budget.

    Returns a context string optimized for token efficiency:
    - High-relevance memories get full content
    - Low-relevance memories get pointers only (like Kronos)
    """
    memories = keyword_retrieve(query)
    if not memories:
        return ""

    # Score and sort
    scored = []
    for m in memories:
        body = re.sub(r'^---.*?---\s*', '', m["content"], flags=re.DOTALL).strip()
        pointer = generate_pointer(m) if include_pointers else None
        relevance = (
            body.lower().count(query.lower()) * 3 +
            (10 if query.lower() in m["title"].lower() else 0) +
            m["strength"] * 5
        )
        scored.append((relevance, m, body, pointer))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Rough token estimation (4 chars ≈ 1 token for mixed content)
    def est_tokens(text):
        return len(text) // 4

    parts = []
    budget = max_tokens
    full_memories_used = 0
    pointer_memories_used = 0

    for relevance, m, body, pointer in scored:
        full_tokens = est_tokens(body)
        pointer_tokens = est_tokens(json.dumps(pointer, ensure_ascii=False)) if pointer else 0

        # Top memories get full content, rest get pointers
        if full_memories_used < 2 and budget >= full_tokens:
            parts.append(f"--- {m['title']} [{m['tier']}, str:{m['strength']:.2f}] ---\n{body[:2000]}")
            budget -= full_tokens
            full_memories_used += 1
        elif pointer and budget >= pointer_tokens:
            parts.append(f"[{m['tier']}] {m['title']}: {pointer['summary'][:150]}")
            budget -= pointer_tokens
            pointer_memories_used += 1
            if budget < 50:
                break

    header = f"# Nexus Memory Context (query: {query})\n# {full_memories_used} full + {pointer_memories_used} pointers within budget\n\n"
    return header + "\n\n".join(parts)

# ─── Consolidation engine ────────────────────────────────────────────

def consolidate(dry_run=False):
    """Auto-promote memories between tiers.

    - Working older than 1 day → promote to episodic
    - Episodic accessed 3+ times in 7 days → promote to semantic
    - Strength < 0.2 → archive
    """
    report = {"promoted": [], "archived": [], "errors": []}
    memories = _all_memories()
    now = datetime.now()

    for m in memories:
        fp = os.path.join(MEMORY_DIR, m["path"])
        try:
            with open(fp, encoding="utf-8") as fh:
                content = fh.read()

            # Archive check
            if m["strength"] < 0.2 and m["tier"] != "archive":
                archive_dir = os.path.join(MEMORY_DIR, "archive")
                os.makedirs(archive_dir, exist_ok=True)
                dest = os.path.join(archive_dir, os.path.basename(fp))
                if not dry_run:
                    os.rename(fp, dest)
                report["archived"].append(f"{m['path']} (strength: {m['strength']:.2f})")
                continue

            # Working → Episodic promotion
            if m["tier"] == "working" and m["created"] != "unknown":
                try:
                    created = datetime.strptime(m["created"][:10], "%Y-%m-%d")
                    age_days = (now - created).days
                    if age_days >= CONFIG["promote_after_days"]["working_to_episodic"]:
                        content = _update_fm(content, "type", "episodic")
                        dest = os.path.join(MEMORY_DIR, "episodic", os.path.basename(fp))
                        if not dry_run:
                            with open(fp, "w", encoding="utf-8") as fh:
                                fh.write(content)
                            os.rename(fp, dest)
                        report["promoted"].append(f"{m['path']} → episodic (age: {age_days}d)")
                except ValueError:
                    pass

            # Episodic → Semantic promotion
            if m["tier"] == "episodic" and m["access_count"] >= 3 and m["created"] != "unknown":
                try:
                    created = datetime.strptime(m["created"][:10], "%Y-%m-%d")
                    age_days = (now - created).days
                    if age_days >= CONFIG["promote_after_days"]["episodic_to_semantic"]:
                        content = _update_fm(content, "type", "semantic")
                        dest = os.path.join(MEMORY_DIR, "semantic", os.path.basename(fp))
                        if not dry_run:
                            with open(fp, "w", encoding="utf-8") as fh:
                                fh.write(content)
                            os.rename(fp, dest)
                        report["promoted"].append(f"{m['path']} → semantic (access: {m['access_count']}, age: {age_days}d)")
                except ValueError:
                    pass

        except Exception as e:
            report["errors"].append(f"{m['path']}: {e}")

    return report

# ─── Decay calculation ────────────────────────────────────────────────

def calculate_decay(dry_run=False):
    """Ebbinghaus decay for all memories."""
    report = {"decayed": [], "archived": []}
    memories = _all_memories()

    for m in memories:
        if m["tier"] == "core":  # Core never decays
            continue

        dc = CONFIG["tier_decay_days"].get(m["tier"], 30)
        last_access = _parse_fm(m["content"], "last_accessed") or m["created"] or str(date.today())

        try:
            dt = datetime.strptime(last_access[:10], "%Y-%m-%d")
            days_since = max(1, (datetime.now() - dt).days)
        except ValueError:
            days_since = 1

        new_strength = m["strength"] * math.exp(-days_since / dc)
        new_strength = max(0.05, min(1.0, new_strength))

        if abs(new_strength - m["strength"]) > 0.01:
            fp = os.path.join(MEMORY_DIR, m["path"])
            if new_strength < 0.2 and m["tier"] not in ("archive", "core"):
                # Archive
                archive_dir = os.path.join(MEMORY_DIR, "archive")
                os.makedirs(archive_dir, exist_ok=True)
                dest = os.path.join(archive_dir, os.path.basename(fp))
                if not dry_run:
                    with open(fp, encoding="utf-8") as fh:
                        content = fh.read()
                    content = _update_fm(content, "strength", f"{new_strength:.4f}")
                    with open(os.path.join(archive_dir, os.path.basename(fp)), "w", encoding="utf-8") as fh:
                        fh.write(content)
                    os.remove(fp)
                report["archived"].append(f"{m['name']}: {m['strength']:.2f} → {new_strength:.4f} ({days_since}d)")
            else:
                if not dry_run:
                    with open(fp, encoding="utf-8") as fh:
                        content = fh.read()
                    content = _update_fm(content, "strength", f"{new_strength:.4f}")
                    with open(fp, "w", encoding="utf-8") as fh:
                        fh.write(content)
                report["decayed"].append(f"{m['name']}: {m['strength']:.2f} → {new_strength:.4f} ({days_since}d, dc={dc})")

    return report

# ─── Token efficiency tracking ────────────────────────────────────────

class TokenTracker:
    """Track token savings vs Hindsight baseline."""
    def __init__(self):
        self.log_path = os.path.join(MEMORY_DIR, ".token_economics.json")
        self._load()

    def _load(self):
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path) as f:
                    self.data = json.load(f)
                    return
            except:
                pass
        self.data = {
            "version": "2.0",
            "started": datetime.now().isoformat(),
            "total_tokens_saved": 0,
            "total_tokens_spent": 0,
            "total_cost_saved": 0.0,
            "total_cost_spent": 0.0,
            "operations": [],
            "daily": {},
        }

    def _save(self):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        with open(self.log_path, "w") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def log_operation(self, op_type, tokens_saved=0, tokens_spent=0, detail=""):
        cost_per_mtok_input = CONFIG["cost_model"]["claude_input_per_mtok"]
        cost_saved = (tokens_saved / 1_000_000) * cost_per_mtok_input
        cost_spent = (tokens_spent / 1_000_000) * cost_per_mtok_input

        self.data["total_tokens_saved"] += tokens_saved
        self.data["total_tokens_spent"] += tokens_spent
        self.data["total_cost_saved"] += cost_saved
        self.data["total_cost_spent"] += cost_spent

        today = date.today().isoformat()
        if today not in self.data["daily"]:
            self.data["daily"][today] = {"saved": 0, "spent": 0, "ops": 0}
        self.data["daily"][today]["saved"] += tokens_saved
        self.data["daily"][today]["spent"] += tokens_spent
        self.data["daily"][today]["ops"] += 1

        self.data["operations"].append({
            "type": op_type,
            "time": datetime.now().isoformat(),
            "tokens_saved": tokens_saved,
            "tokens_spent": tokens_spent,
            "cost_saved": round(cost_saved, 6),
            "cost_spent": round(cost_spent, 6),
            "detail": detail[:200],
        })
        if len(self.data["operations"]) > 1000:
            self.data["operations"] = self.data["operations"][-1000:]
        self._save()

    def get_summary(self):
        net_tokens = self.data["total_tokens_saved"] - self.data["total_tokens_spent"]
        net_cost = self.data["total_cost_saved"] - self.data["total_cost_spent"]
        efficiency = 0
        if self.data["total_tokens_spent"] > 0:
            efficiency = (self.data["total_tokens_saved"] / self.data["total_tokens_spent"]) * 100
        return {
            "total_tokens_saved": self.data["total_tokens_saved"],
            "total_tokens_spent": self.data["total_tokens_spent"],
            "net_tokens_saved": net_tokens,
            "net_cost_saved_usd": round(net_cost, 4),
            "efficiency_ratio": f"{efficiency:.1f}x",
            "today": self.data["daily"].get(date.today().isoformat(), {}),
        }


# ─── Hub bridge: cross-agent memory sharing ───────────────────────────

def share_across_agents(content, source_agent, target_agents=None, tags=None):
    """Share a memory across Hermes agents.

    This creates a shared memory visible to all agents.
    Cross-agent sharing is a key advantage over Hindsight's isolated banks.
    """
    shared_dir = os.path.join(MEMORY_DIR, "semantic")
    os.makedirs(shared_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    agent_tag = f"shared, agent:{source_agent}"
    if target_agents:
        agent_tag += ", to:" + ",".join(target_agents)
    if tags:
        agent_tag += ", " + ", ".join(tags)

    name_slug = re.sub(r'[^a-z0-9-]', '', source_agent.lower())
    fname = f"shared-{name_slug}-{ts}.md"
    fp = os.path.join(shared_dir, fname)
    today = date.today().isoformat()

    frontmatter = f"""---
type: semantic
strength: 1.0
created: {today}
updated: {today}
tags: [{agent_tag}]
source: hub-bridge
access_count: 1
last_accessed: {today}
---

# Shared Memory from {source_agent}

{content}
"""
    with open(fp, "w", encoding="utf-8") as f:
        f.write(frontmatter)
    return fname


# ─── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "retrieve":
        q = " ".join(sys.argv[2:])
        ctx = assemble_context(q)
        print(ctx if ctx else "No relevant memories found.")

    elif cmd == "consolidate":
        dry = "--dry-run" in sys.argv
        r = consolidate(dry)
        print(f"Promoted: {len(r['promoted'])}")
        for p in r["promoted"]:
            print(f"  OK {p}")
        print(f"Archived: {len(r['archived'])}")
        for a in r["archived"]:
            print(f"  -> {a}")
        if r["errors"]:
            print(f"Errors: {len(r['errors'])}")
            for e in r["errors"]:
                print(f"  ERR {e}")

    elif cmd == "decay":
        dry = "--dry-run" in sys.argv
        r = calculate_decay(dry)
        print(f"Decayed: {len(r['decayed'])}")
        for d in r["decayed"][:10]:
            print(f"  {d}")
        if len(r["decayed"]) > 10:
            print(f"  ... and {len(r['decayed'])-10} more")
        print(f"Archived: {len(r['archived'])}")

    elif cmd == "tokens":
        tt = TokenTracker()
        s = tt.get_summary()
        print(json.dumps(s, indent=2))

    elif cmd == "share":
        agent = sys.argv[2] if len(sys.argv) > 2 else "unknown"
        content = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
        if content:
            f = share_across_agents(content, agent)
            print(f"Shared: {f}")
        else:
            print("Usage: nexus_engine.py share <agent_name> <content>")

    elif cmd == "pointers":
        q = " ".join(sys.argv[2:])
        memories = keyword_retrieve(q)
        for m in memories:
            p = generate_pointer(m)
            print(json.dumps(p, ensure_ascii=False, indent=2))
            print("---")

    else:
        print("""Nexus v2 Engine
Commands:
  retrieve <query>    Assemble token-efficient context
  consolidate         Auto-promote memories between tiers
  decay               Calculate Ebbinghaus decay
  tokens              Show token economics summary
  share <agent> <msg> Share memory across agents
  pointers <query>    Generate Kronos-style pointers""")
