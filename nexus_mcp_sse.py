#!/usr/bin/env python3
"""Nexus MCP — HTTP/SSE Transport
Wraps nexus_mcp.py for MCP HTTP transport (marketplace-compatible).
Required for listing on MCPize, AgenticMarket, etc.

Usage:
    python nexus_mcp_sse.py --port 9876

Then connect any MCP client via SSE at http://localhost:9876/sse
"""
import json, os, sys, re, uuid, io
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Import the MCP handler logic from nexus_mcp.py
import nexus_mcp

# ─── SSE session manager ───────────────────────────────────────────────

class SSESession:
    """Manages one SSE connection. Sends server→client messages."""
    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self.queue = []
        self.wfile = None
        self.connected = False

    def connect(self, wfile):
        self.wfile = wfile
        self.connected = True

    def send_event(self, event, data):
        if self.wfile:
            try:
                self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            except:
                self.connected = False

    def send_message(self, msg):
        self.send_event("message", msg)

_sessions = {}

# ─── HTTP Handler ──────────────────────────────────────────────────────

class MCPHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write(f"[Nexus-MCP-SSE] {args[0]} {args[1]} {args[2]}\n")

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _send_error(self, status, msg):
        self._send_json({"error": msg}, status)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")

        # Health
        if path == "/health":
            self._send_json({
                "status": "ok",
                "service": "nexus-mcp-sse",
                "version": "2.0.0",
                "transport": "sse",
                "timestamp": datetime.now().isoformat(),
            })
            return

        # SSE endpoint — MCP HTTP transport (2024-11-05)
        if path == "/sse":
            session = SSESession()
            _sessions[session.session_id] = session

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            # Send endpoint event so the client knows where to POST
            session.connect(self.wfile)
            session.send_event("endpoint", f"/mcp?session_id={session.session_id}")

            # Keep-alive: send comments periodically
            import time
            try:
                while session.connected:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    time.sleep(15)
            except:
                pass
            finally:
                _sessions.pop(session.session_id, None)
            return

        self._send_error(404, f"Not found: {path}")

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        params = {}
        qs = urlparse(self.path).query
        if qs:
            for pair in qs.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k] = v

        # MCP message endpoint
        if path == "/mcp":
            session_id = params.get("session_id", "")
            session = _sessions.get(session_id)

            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                self._send_error(400, "Empty body")
                return
            raw = self.rfile.read(length)
            # Try UTF-8 then GBK
            try:
                body = json.loads(raw.decode("utf-8"))
            except UnicodeDecodeError:
                try:
                    body = json.loads(raw.decode("gbk"))
                except:
                    self._send_error(400, "Invalid encoding")
                    return
            except json.JSONDecodeError:
                self._send_error(400, "Invalid JSON")
                return

            # Route MCP methods
            result = None
            error = None
            req_id = body.get("id")
            method = body.get("method")
            params_body = body.get("params", {})

            try:
                if method == "initialize":
                    result = nexus_mcp.handle_initialize(req_id)
                elif method == "notifications/initialized":
                    pass
                elif method == "notifications/cancelled":
                    pass
                elif method == "resources/list":
                    result = nexus_mcp.handle_resources_list(req_id)
                elif method == "resources/read":
                    uri = params_body.get("uri", "")
                    result, error = nexus_mcp.handle_resources_read(req_id, uri)
                elif method == "tools/list":
                    result = nexus_mcp.handle_tools_list(req_id)
                elif method == "tools/call":
                    name = params_body.get("name", "")
                    args = params_body.get("arguments", {})
                    result, error = nexus_mcp.handle_tools_call(req_id, name, args)
                else:
                    error = {"code": -32601, "message": f"Method not found: {method}"}
            except Exception as e:
                error = {"code": -32603, "message": str(e)}

            # Build response
            msg = {"jsonrpc": "2.0", "id": req_id}
            if error:
                msg["error"] = error
            else:
                msg["result"] = result or {}

            # If there's an active SSE session, send response via SSE
            if session and session.connected and session_id in _sessions:
                session.send_message(msg)
                self._send_json({"status": "sent"}, 202)
            else:
                # No SSE session, respond directly
                self._send_json(msg)

        else:
            self._send_error(404, f"Not found: {path}")


def run_server(port=9876, host="0.0.0.0"):
    server = HTTPServer((host, port), MCPHTTPHandler)
    print(f"\n{'='*50}")
    print(f"  Nexus MCP SSE Server")
    print(f"  Listening: http://{host}:{port}")
    print(f"  SSE:       http://{host}:{port}/sse")
    print(f"  POST:      http://{host}:{port}/mcp")
    print(f"  Compat:    MCP HTTP Transport (2024-11-05)")
    print(f"  Tools:     search, stats, save, touch, decay")
    print(f"{'='*50}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Nexus MCP SSE Server")
    parser.add_argument("--port", type=int, default=9876, help="Port")
    parser.add_argument("--host", default="0.0.0.0", help="Host")
    args = parser.parse_args()
    run_server(args.port, args.host)
