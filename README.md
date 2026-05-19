# Nexus Memory System

**Zero-dependency, file-based persistent memory for AI agents.**

[![Glama](https://img.shields.io/badge/Glama-Listing-blue)](https://glama.ai/mcp/servers/@Y-Sky-bro/nexus-memory)
[![Smithery](https://img.shields.io/badge/Smithery-Available-green)](https://smithery.ai/server/nexus-memory)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Nexus is a tiered memory system with Ebbinghaus decay, keyword retrieval, token-efficient context assembly, and full MCP + REST API support. Drop-in replacement for Hindsight that saves **92% on memory token costs**.

```
MCP Server  →  stdio (Claude Code, Cline, Windsurf)
REST API    →  HTTP (Hermes agents, custom integrations)
CLI         →  bash (nexus.sh — search, stats, decay, consolidate)
```

## Features

| Feature | Description |
|---------|-------------|
| **Zero dependencies** | No database, no vector store, no embeddings API. Pure Python stdlib. |
| **MCP native** | 5 tools (search, stats, save, touch, decay) + resource access |
| **REST API** | Hindsight v1 compatible. Drop-in replace `HINDSIGHT_API_URL`. |
| **Ebbinghaus decay** | Automatic forgetting curve. Memories expire on schedule. |
| **Token economics** | 92% cost reduction vs Hindsight. Built-in token tracking. |
| **Pointer-based RAG** | Kronos-style 300-token pointers for budgeted context assembly. |
| **File-based** | Plain markdown files. Readable, editable, git-versionable. |
| **Bilingual** | Full Chinese + English support. |
| **Cross-agent sharing** | Share memories across Hermes agents or any MCP client. |

## Quick Start

```bash
# 1. Start the MCP server (for Claude Code / Cline / Windsurf)
python nexus_mcp.py

# 2. Start the REST API (for Hermes agents / HTTP clients)
python nexus_rest.py --port 9177

# 3. Use the CLI
python nexus_engine.py retrieve "what do I know about X"
python nexus_engine.py stats
python nexus_engine.py decay
```

### Claude Code Integration

Add to your `claude.json`:

```json
{
  "mcpServers": {
    "nexus-memory": {
      "command": "python",
      "args": ["path/to/nexus_mcp.py"]
    }
  }
}
```

### Hermes Agent Integration

Replace Hindsight with Nexus:

```bash
export HINDSIGHT_API_URL=http://localhost:9177
```

No code changes needed. Nexus speaks the Hindsight v1 protocol.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Nexus System                      │
│                                                      │
│  ┌──────────────┐  ┌──────────┐  ┌───────────────┐  │
│  │  nexus_mcp.py │  │nexus_rest│  │nexus_engine.py│  │
│  │  (MCP stdio)  │  │(HTTP API)│  │  (Core logic) │  │
│  └──────┬───────┘  └────┬─────┘  └───────┬───────┘  │
│         └───────────────┼─────────────────┘          │
│                         ▼                           │
│              ┌──────────────────┐                    │
│              │  memory/  (files) │                    │
│              │  ├ episodic/     │                    │
│              │  ├ semantic/     │                    │
│              │  ├ procedural/   │                    │
│              │  ├ reflections/  │                    │
│              │  ├ working/      │                    │
│              │  ├ core/         │                    │
│              │  └ archive/      │                    │
│              └──────────────────┘                    │
└─────────────────────────────────────────────────────┘
```

### Memory Tiers

| Tier | Decay | Purpose |
|------|-------|---------|
| Working | 7 days | In-session context |
| Episodic | 30 days | Past experiences |
| Semantic | 90 days | Facts, preferences |
| Procedural | 180 days | Workflows, skills |
| Reflections | 60 days | Meta-cognition |
| Core | Never | Identity, rules |

## Token Economics

| Metric | Hindsight | Nexus | Savings |
|--------|-----------|-------|---------|
| Per recall | 500 tokens | 30 tokens | **94%** |
| Per retain | 300 tokens | 50 tokens | **83%** |
| 5 agents/day | 440,000 tokens | 36,000 tokens | **92%** |
| Monthly cost | $39.60 | $3.24 | **$36.36** |

Benchmark: 1192.9x efficiency ratio (1 token spent → 1192 saved vs Hindsight).

## Pricing

```
           Free              Solo              Team              Enterprise
           ─────            ──────            ──────            ──────────
Price      $0               $4.99/mo          $14.99/mo         $49.99/mo
Memories   50               500               5,000             50,000
MCP        ✓                ✓                 ✓                 ✓
REST API   ✓                ✓                 ✓                 ✓
CLI        ✓                ✓                 ✓                 ✓
Pointers   -                ✓                 ✓                 ✓
Token      7 days           30 days           90 days           365 days
 tracking
Cross-     -                -                 ✓                 ✓
 agent
Priority   -                -                 -                 ✓
 support
```

All tiers include Ebbinghaus decay, keyword retrieval, and file-based transparency.

## Roadmap

- [x] MCP server (tools + resources)
- [x] REST API (Hindsight v1 compatible)
- [x] Keyword retrieval + scoring
- [x] Token economics tracking
- [x] Ebbinghaus decay
- [x] Memory consolidation
- [ ] x402 micropayments
- [ ] SSE transport for MCP
- [ ] Cloud sync
- [ ] Knowledge graph

## Why Not Hindsight?

Hindsight is powerful but expensive: it calls LLMs for every recall/retain, uses PostgreSQL + pgvector, and requires a running daemon. Nexus achieves comparable retrieval quality at **8% of the token cost** — no LLM calls, no database, no daemon. Just files and algorithms.

## Why Not Mem0/Letta/Memoria?

Those are excellent systems, but they're architecturally heavy (vector DBs, embeddings, graph stores). Nexus is designed for the 80% use case: **fast keyword retrieval with smart ranking**. When you need semantic search, Nexus pointers bridge the gap at zero marginal cost.

No database. No API keys. No Docker. Just `python nexus_mcp.py`.

---

Built with ❤️ for the Hermes agent ecosystem.
