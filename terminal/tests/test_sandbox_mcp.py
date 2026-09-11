"""沙箱 MCP HTTP 服务(sandbox_mcp_http)的协议层功能测试。

通过子进程启动真实 HTTP 服务(随机端口),验证 /health、MCP initialize、
tools/list、tools/call(未知工具/未知方法错误)、CORS 头等协议行为。
真实命令执行(sandbox_exec)依赖 Docker,不在本测试范围,见 VM 手册。
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SERVER = ROOT / "sandbox_mcp" / "original" / "sandbox_mcp_http.py"


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    proc = subprocess.Popen(
        [PY, str(SERVER), "--port", str(port), "--host", "127.0.0.1"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=1):
                break
        except Exception:
            time.sleep(0.3)
    else:
        proc.terminate()
        pytest.fail("sandbox MCP server did not start")
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _get(base, path):
    with urllib.request.urlopen(f"{base}{path}", timeout=5) as r:
        return json.loads(r.read().decode())


def _mcp(base, method, idn, params=None):
    body = json.dumps({"jsonrpc": "2.0", "id": idn, "method": method,
                       "params": params or {}}).encode()
    req = urllib.request.Request(f"{base}/mcp", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


def test_health(server):
    data = _get(server, "/health")
    assert data["status"] == "ok"
    assert data["sandbox"] == "connected"


def test_initialize(server):
    r = _mcp(server, "initialize", 1)
    result = r["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "hermes-sandbox"
    assert "tools" in result["capabilities"]


def test_tools_list(server):
    r = _mcp(server, "tools/list", 2)
    tools = {t["name"]: t for t in r["result"]["tools"]}
    assert "sandbox_exec" in tools
    assert "sandbox_read" in tools
    # 工具 schema 应含 inputSchema 和 required 字段
    exec_schema = tools["sandbox_exec"]["inputSchema"]
    assert exec_schema["type"] == "object"
    assert "command" in exec_schema["required"]


def test_unknown_tool_returns_error(server):
    r = _mcp(server, "tools/call", 3, {"name": "nonexistent", "arguments": {}})
    assert r["error"]["code"] == -32601
    assert "Unknown tool" in r["error"]["message"]


def test_unknown_method_returns_error(server):
    r = _mcp(server, "not_a_method", 4)
    assert r["error"]["code"] == -32601


def test_404_unknown_path(server):
    try:
        _get(server, "/nonexistent")
        pytest.fail("expected 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_cors_headers(server):
    req = urllib.request.Request(f"{server}/mcp", method="OPTIONS")
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.headers.get("Access-Control-Allow-Origin") == "*"
        assert "POST" in r.headers.get("Access-Control-Allow-Methods", "")
