# Marketplace Listings

Pre-written descriptions for each MCP marketplace. All use the same core copy with platform-specific tweaks.

## Short Description (50 chars)
Zero-dependency persistent memory for AI agents

## Medium Description (140 chars)
File-based memory with Ebbinghaus decay, MCP + REST API, keyword retrieval, token economics. Drop-in Hindsight replacement saves 92%.

## Long Description

Nexus Memory System provides persistent, tiered memory for AI agents with zero external dependencies — no database, no vector store, no embeddings API.

**For AI Agents:**
- MCP native: 5 tools (search, stats, save, touch, decay) + resource access
- REST API: Hindsight v1 compatible — set HINDSIGHT_API_URL and go
- Ebbinghaus decay: automatic forgetting curve, tiered retention (7/30/90/180 days)
- Token economics: built-in tracking, 92% cost reduction vs Hindsight

**For Developers:**
- Single file: `python nexus_mcp.py` — that's it
- Three interfaces: MCP stdio, HTTP/SSE, REST API, CLI
- File-based: all memories are plain markdown, git-versionable
- Bilingual: full Chinese + English support

**Technical:**
- Zero dependencies (stdlib only)
- Keyword retrieval with smart scoring (exact phrase ×3, tier boosting, freshness bonus)
- Pointer-based context assembly (Kronos-style, 300-token pointers)
- Automatic consolidation (working → episodic → semantic → archive)
- Token economics dashboard with daily/monthly reporting

**Use Cases:**
- Claude Code persistent memory via MCP
- Hermes agent memory backend (Hindsight replacement)
- Cline / Windsurf / Cursor memory plugin
- Cross-session context for any AI agent

## Platform-Specific

### MCPize
**Category:** Memory & Storage
**Pricing:** Free / $4.99 / $14.99 / $49.99 per month
**Tags:** memory, hindsight, ai-agents, persistent-storage, zero-dependency

### AgenticMarket
**Category:** Memory
**Pricing:** $0.001–$0.005 per call
**Setup time:** 10 minutes (self-hosted)

### Smithery.ai
**Type:** command
**Command:** `python nexus_mcp.py` (stdio) or `python nexus_mcp_sse.py --port 9876` (SSE)
