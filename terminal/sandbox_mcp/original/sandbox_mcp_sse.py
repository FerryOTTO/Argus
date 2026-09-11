#!/usr/bin/env python3
"""
Sandbox MCP SSE Server — 通过 SSE (Server-Sent Events) 为 OpenCode 提供沙箱工具

MCP SSE 传输协议：
- GET  /sse     → SSE 事件流（text/event-stream）
- POST /message → JSON-RPC 请求（响应通过 SSE 返回）

OpenCode 配置：
  opencode mcp add sandbox --url http://127.0.0.1:9876/sse

用法：
  python sandbox_mcp_sse.py [--port 9876] [--host 127.0.0.1]
"""

import sys
import os
import json
import time
import queue
import threading
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP 服务器，支持并发 SSE 连接"""
    daemon_threads = True

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
                "command": {"type": "string", "description": "Shell 命令"},
                "timeout": {"type": "integer", "description": "超时秒数", "default": 120}
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
                "path": {"type": "string", "description": "文件路径"},
                "offset": {"type": "integer", "description": "起始行号", "default": 1},
                "limit": {"type": "integer", "description": "最大行数", "default": 500}
            },
            "required": ["path"]
        }
    }
]

# 全局 SSE 客户端管理
sse_clients: dict = {}       # session_id → queue.Queue
sse_clients_lock = threading.Lock()


def _handle_tool_call(tool_name: str, tool_args: dict) -> dict:
    """执行沙箱工具调用"""
    if tool_name == "sandbox_exec":
        from sandbox_exec import SandboxExecutor
        sb = SandboxExecutor(timeout=tool_args.get("timeout", 120))
        result = sb.run(tool_args["command"])
        return result.to_dict()

    elif tool_name == "sandbox_read":
        from sandbox_file import SandboxFileReader
        reader = SandboxFileReader()
        result = reader.read(
            tool_args["path"],
            offset=tool_args.get("offset", 1),
            limit=tool_args.get("limit", 500)
        )
        return result.to_dict()

    else:
        return {"error": f"Unknown tool: {tool_name}"}


def _handle_jsonrpc(request: dict, session_id: str) -> dict:
    """处理 JSON-RPC 请求"""
    method = request.get("method", "")
    req_id = request.get("id")

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
        tool_name = request.get("params", {}).get("name", "")
        tool_args = request.get("params", {}).get("arguments", {})
        try:
            result = _handle_tool_call(tool_name, tool_args)
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}
                    ]
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": str(e)}
            }

    elif method == "notifications/initialized":
        return None

    return {
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"}
    }


class SSEMCPHandler(BaseHTTPRequestHandler):
    """SSE + MCP HTTP 处理器"""

    def log_message(self, format, *args):
        print(f"[sandbox-sse] {args[0]}", file=sys.stderr)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/sse":
            # 建立 SSE 连接
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            session_id = uuid.uuid4().hex
            msg_queue: queue.Queue = queue.Queue()

            with sse_clients_lock:
                sse_clients[session_id] = msg_queue

            print(f"[sandbox-sse] Client connected: {session_id}", file=sys.stderr)

            try:
                # 发送 endpoint 事件
                endpoint = f"http://127.0.0.1:{self.server.server_port}/message?session={session_id}"
                endpoint_event = f"event: endpoint\ndata: {endpoint}\n\n"
                self.wfile.write(endpoint_event.encode())
                self.wfile.flush()

                # 等待消息
                while True:
                    try:
                        msg = msg_queue.get(timeout=30)
                        event_data = f"event: message\ndata: {json.dumps(msg)}\n\n"
                        self.wfile.write(event_data.encode())
                        self.wfile.flush()
                    except queue.Empty:
                        # 发送心跳
                        self.wfile.write(": heartbeat\n\n".encode())
                        self.wfile.flush()

            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with sse_clients_lock:
                    sse_clients.pop(session_id, None)
                print(f"[sandbox-sse] Client disconnected: {session_id}", file=sys.stderr)

        elif path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        query = urlparse(self.path).query
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        session_id = params.get("session", "")

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            request = json.loads(body)
        except Exception as e:
            self.send_response(400)
            self.end_headers()
            return

        if path == "/message":
            response = _handle_jsonrpc(request, session_id)

            if response is not None:
                # 通过 SSE 推送响应
                with sse_clients_lock:
                    q = sse_clients.get(session_id)
                if q:
                    q.put(response)

            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"accepted": True}).encode())

        else:
            self.send_response(404)
            self.end_headers()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sandbox MCP SSE Server")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), SSEMCPHandler)
    print(f"[sandbox-sse] SSE server: http://{args.host}:{args.port}/sse", file=sys.stderr)
    print(f"[sandbox-sse] OpenCode: opencode mcp add sandbox --url http://{args.host}:{args.port}/sse", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("[sandbox-sse] Server stopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
