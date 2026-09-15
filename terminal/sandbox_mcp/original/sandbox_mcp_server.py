#!/usr/bin/env python3
"""
Sandbox MCP Server — 为 OpenCode 提供沙箱化的工具调用

通过 MCP 协议将 sandbox_exec 和 sandbox_file 暴露为 OpenCode 可用工具，
实现所有命令执行和文件读取都在 Docker 沙箱容器中隔离运行。

OpenCode 配置方法:
  opencode mcp add sandbox --command "python3 ./sandbox_mcp/sandbox_mcp_server.py"
"""

import sys
import os
import json
import asyncio

# 添加 sandbox 模块路径
SANDBOX_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SANDBOX_DIR)

# ============================================================
# MCP Server (stdio transport)
# ============================================================

async def handle_request(request: dict) -> dict:
    """处理 MCP JSON-RPC 请求"""
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "hermes-sandbox",
                    "version": "1.0.0"
                }
            }
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "sandbox_exec",
                        "description": (
                            "在 Docker 沙箱容器中安全执行命令。命令在隔离的 sandbox-exec 容器中运行，"
                            "具有资源限制(512MB内存, 1 CPU, 120秒超时)、网络隔离和非 root 用户执行。"
                            "执行结果会经过有害内容检测，危险命令将被自动阻止。"
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "要在沙箱中执行的 shell 命令"
                                },
                                "timeout": {
                                    "type": "integer",
                                    "description": "超时时间（秒），默认 120",
                                    "default": 120
                                }
                            },
                            "required": ["command"]
                        }
                    },
                    {
                        "name": "sandbox_read",
                        "description": (
                            "通过 Docker 沙箱容器安全读取文件内容。文件读取在独立的 sandbox-file 容器中进行，"
                            "与命令执行容器完全隔离。支持路径安全检查和文件内容有害检测。"
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "要读取的文件路径（Windows 或 WSL 格式）"
                                },
                                "offset": {
                                    "type": "integer",
                                    "description": "起始行号（1-indexed），默认 1",
                                    "default": 1
                                },
                                "limit": {
                                    "type": "integer",
                                    "description": "最大读取行数，默认 500",
                                    "default": 500
                                }
                            },
                            "required": ["path"]
                        }
                    }
                ]
            }
        }

    elif method == "tools/call":
        params = request.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        if tool_name == "sandbox_exec":
            from sandbox_exec import SandboxExecutor
            sb = SandboxExecutor(timeout=tool_args.get("timeout", 120))
            result = sb.run(tool_args["command"])
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
                        }
                    ]
                }
            }

        elif tool_name == "sandbox_read":
            from sandbox_file import SandboxFileReader
            reader = SandboxFileReader()
            result = reader.read(
                tool_args["path"],
                offset=tool_args.get("offset", 1),
                limit=tool_args.get("limit", 500)
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
                        }
                    ]
                }
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
            }

    elif method == "notifications/initialized":
        # No response needed for notifications
        return None

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"}
        }


async def main():
    """MCP stdio 主循环"""
    # 输出到 stderr，避免污染 stdio
    print("[sandbox-mcp] Server starting...", file=sys.stderr)

    # 读取 stdin 行
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        try:
            line = await reader.readline()
            if not line:
                break

            line = line.decode("utf-8").strip()
            if not line:
                continue

            request = json.loads(line)
            response = await handle_request(request)

            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()

        except json.JSONDecodeError as e:
            print(f"[sandbox-mcp] JSON parse error: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[sandbox-mcp] Error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
