#!/usr/bin/env python3
"""
Sandbox MCP HTTP Server — 通过 HTTP 为 OpenCode 提供沙箱工具

使用 Python stdlib 实现，无需额外依赖。
启动后 OpenCode 通过 HTTP 连接：
  opencode mcp add sandbox --url http://localhost:9876/mcp

用法：
  python sandbox_mcp_http.py [--port 9876] [--host 127.0.0.1]
"""

import sys
import os
import json
import signal
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

SANDBOX_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SANDBOX_DIR)

# ============================================================
# 工具定义
# ============================================================
TOOLS = [
    {
        "name": "sandbox_exec",
        "description": (
            "在 Docker 沙箱容器中安全执行命令。隔离的 sandbox-exec 容器，"
            "512MB 内存, 1 CPU, 120 秒超时, 网络隔离, 非 root 执行。"
            "结果经过 5 层有害内容检测，危险命令自动阻止。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell 命令"
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数，默认 120",
                    "default": 120
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "sandbox_read",
        "description": (
            "通过独立 Docker 容器安全读取文件。sandbox-file 容器（64MB, 只读），"
            "与执行容器完全隔离。路径白名单检查和文件内容有害检测。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径"
                },
                "offset": {
                    "type": "integer",
                    "description": "起始行号（1-indexed），默认 1",
                    "default": 1
                },
                "limit": {
                    "type": "integer",
                    "description": "最大行数，默认 500",
                    "default": 500
                }
            },
            "required": ["path"]
        }
    }
]


class MCPHandler(BaseHTTPRequestHandler):
    """MCP HTTP 请求处理器"""

    def log_message(self, format, *args):
        """日志输出到 stderr"""
        print(f"[sandbox-mcp-http] {args[0]}", file=sys.stderr)

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/mcp" or path == "/":
            self._send_json({
                "jsonrpc": "2.0",
                "id": None,
                "result": {
                    "serverInfo": {"name": "hermes-sandbox", "version": "1.0.0"},
                    "capabilities": {"tools": {}},
                    "tools": TOOLS
                }
            })
        elif path == "/health":
            self._send_json({"status": "ok", "sandbox": "connected"})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            request = json.loads(body)
        except Exception as e:
            self._send_json({"jsonrpc": "2.0", "error": {"code": -32700, "message": str(e)}}, 400)
            return

        method = request.get("method", "")
        req_id = request.get("id")

        if path == "/mcp":
            response = self._handle_mcp(method, req_id, request.get("params", {}))
            if response:
                self._send_json(response)
        else:
            self._send_json({"error": "not found"}, 404)

    def _handle_mcp(self, method: str, req_id, params: dict) -> dict:
        if method == "initialize":
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "hermes-sandbox", "version": "1.0.0"}
                }
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {"tools": TOOLS}
            }

        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})

            try:
                if tool_name == "sandbox_exec":
                    from sandbox_exec import SandboxExecutor
                    sb = SandboxExecutor(timeout=tool_args.get("timeout", 120))
                    result = sb.run(tool_args["command"])
                    text = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
                elif tool_name == "sandbox_read":
                    from sandbox_file import SandboxFileReader
                    reader = SandboxFileReader()
                    result = reader.read(
                        tool_args["path"],
                        offset=tool_args.get("offset", 1),
                        limit=tool_args.get("limit", 500)
                    )
                    text = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
                else:
                    return {
                        "jsonrpc": "2.0", "id": req_id,
                        "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
                    }

                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {"content": [{"type": "text", "text": text}]}
                }

            except Exception as e:
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": f"Tool error: {e}"}
                }

        elif method == "notifications/initialized":
            return None

        return {
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"}
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sandbox MCP HTTP Server")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), MCPHandler)

    def shutdown(sig, frame):
        print("\n[sandbox-mcp-http] Shutting down...", file=sys.stderr)
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"[sandbox-mcp-http] Server running at http://{args.host}:{args.port}/mcp", file=sys.stderr)
    print(f"[sandbox-mcp-http] OpenCode: opencode mcp add sandbox --url http://{args.host}:{args.port}/mcp", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("[sandbox-mcp-http] Server stopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
