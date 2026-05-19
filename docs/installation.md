# Installation

## Quick Start (30 seconds)

```bash
# Download nexus_mcp.py
curl -O https://raw.githubusercontent.com/nexus-memory/nexus/main/nexus_mcp.py

# Run it
python nexus_mcp.py
```

That's it. No pip install, no requirements.txt, no Docker.

## Claude Code Integration

### Method 1: CLI Config (recommended)

```bash
claude mcp add nexus-memory -- python path/to/nexus_mcp.py
```

### Method 2: Manual config.json

Add to your `claude.json` or `settings.local.json`:

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

Then restart Claude Code. You'll see 5 new tools: search, stats, save, touch, decay.

## Hermes Agent Integration

Replace Hindsight with Nexus in 1 environment variable:

```bash
export HINDSIGHT_API_URL=http://localhost:9177
```

No code changes. Nexus speaks the Hindsight v1 protocol.

### Persistent config:

```bash
# Add to your .bashrc or .zshrc
echo 'export HINDSIGHT_API_URL=http://localhost:9177' >> ~/.bashrc
```

Or set per-agent in `.hermes/config.yaml`:
```yaml
memory:
  provider: hindsight
  config:
    api_url: http://localhost:9177
```

## REST API (standalone)

```bash
python nexus_rest.py --port 9177 --host 0.0.0.0
```

Then hit `http://localhost:9177/health` to verify.

## HTTP/SSE MCP (for marketplace listing)

```bash
python nexus_mcp_sse.py --port 9876
```

Connect any MCP 2024-11-05 compatible client:
- SSE: `http://localhost:9876/sse`
- POST: `http://localhost:9876/mcp`

## CLI

```bash
# Search memories
python nexus_engine.py retrieve "query"

# View memory statistics
python nexus_engine.py tokens

# Run memory consolidation
python nexus_engine.py consolidate

# Run decay (Ebbinghaus)
python nexus_engine.py decay --dry-run

# Generate pointers
python nexus_engine.py pointers "query"
```

## 24/7 Monitoring

```bash
# Start monitoring daemon
python nexus_monitor.py daemon

# View daily report
python nexus_monitor.py report
```

## Docker (Coming Soon)

```dockerfile
FROM python:3.11-slim
COPY nexus_mcp.py /app/
CMD ["python", "/app/nexus_mcp.py"]
```
