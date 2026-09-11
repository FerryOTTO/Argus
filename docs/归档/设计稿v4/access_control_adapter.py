# -*- coding: utf-8 -*-
"""Argus v4 — 访问控制适配器

职责：将统一 SecurityRequest 转换为 v3 check() 参数，
      并将 bool 结果转换为统一 ModuleResult。
"""

import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from auth_gateway import check_v4


class AccessControlAdapter:
    """访问控制模块适配器"""

    name = "access_control"

    def run(self, request: dict) -> dict:
        """执行访问控制检查。

        Args:
            request: 统一 SecurityRequest 字典
                { "context": {...}, "payload": {...} }

        Returns:
            ModuleResult 格式的字典
        """
        started = time.perf_counter()

        try:
            context = request.get("context", {})
            payload = request.get("payload", {})

            user_id = context.get("user_id", "default_user")
            tool_name = payload.get("tool_name", "")
            if tool_name and not tool_name.startswith("tool:"):
                tool_name = f"tool:{tool_name}"
            arguments = payload.get("arguments", {})
            path = arguments.get("path", "")
            database = payload.get("database", "")

            result = check_v4(user_id=user_id, path=path, tool=tool_name, database=database)
            allowed = result["allowed"]
            reason = result["reason"]

            latency = (time.perf_counter() - started) * 1000

            return {
                "module": self.name,
                "success": True,
                "action": "allow" if allowed else "block",
                "risk_score": 0.0 if allowed else 1.0,
                "reason": reason,
                "modified_data": None,
                "details": {
                    "user_id": user_id,
                    "tool": tool_name,
                    "path": path,
                    "database": database,
                },
                "latency_ms": latency,
                "error": None,
            }

        except Exception as exc:
            latency = (time.perf_counter() - started) * 1000
            return {
                "module": self.name,
                "success": False,
                "action": "block",
                "risk_score": 1.0,
                "reason": "module_error",
                "modified_data": None,
                "details": {},
                "latency_ms": latency,
                "error": str(exc),
            }


_adapter = AccessControlAdapter()


def run(request: dict) -> dict:
    """模块级便捷入口"""
    return _adapter.run(request)


# === CLI 演示 ===

if __name__ == "__main__":
    import json

    demo_request = {
        "context": {
            "trace_id": "trace-demo-001",
            "session_id": "session-001",
            "user_id": "user_01",
            "stage": "tool_pre",
            "timestamp": "2026-08-03T10:00:02+08:00",
        },
        "payload": {
            "tool_name": "read_file",
            "tool_call_id": "call-001",
            "arguments": {"path": "C:/demo/public.txt"},
            "database": ""
        }
    }

    result = run(demo_request)
    print(json.dumps(result, ensure_ascii=False, indent=2))
