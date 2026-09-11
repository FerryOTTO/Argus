# argus_client.py — Argus 统一安全服务 HTTP 客户端（对接方案 10.5）
"""
调用 Argus 四个统一接口：
  /v1/input/check   — 输入安全检查
  /v1/tool/pre_check — 工具调用前检查
  /v1/content/check  — 外部内容检查
  /v1/output/check   — 输出安全检查

关键设计：
  - 超时后按配置返回 allow（不阻断）
  - 异常时返回 success=false，不抛异常
  - 所有请求自动带上 trace_id
"""
import time
import httpx
from typing import Optional
from config import config
from models import RequestContext, SecurityRequest, SecurityResponse


class ArgusClient:
    """Argus API 的统一封装"""

    def __init__(self, base_url: str = "", timeout: int = 0):
        self.base_url = base_url or config.argus_url
        self.timeout = timeout or config.argus_timeout

    _NO_PROXY_MOUNTS = {
        "http://": httpx.AsyncHTTPTransport(),
        "https://": httpx.AsyncHTTPTransport(),
    }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
            transport=httpx.AsyncHTTPTransport(),
            mounts=self._NO_PROXY_MOUNTS,
            trust_env=False,
        )

    async def _post(self, path: str, request: SecurityRequest) -> SecurityResponse:
        """发送安全请求，超时/异常时返回 allow 而非抛出异常"""
        started = time.perf_counter()
        try:
            async with self._client() as c:
                resp = await c.post(path, json=request.model_dump())
                resp.raise_for_status()
                data = resp.json()
                return SecurityResponse(**data)
        except Exception as exc:
            return SecurityResponse(
                trace_id=request.context.trace_id,
                stage=request.context.stage or "unknown",
                action="allow",  # 失败时放行，避免阻断正常流程
                risk_score=0.0,
                reason=f"argus_unavailable: {type(exc).__name__}",
                module_results=[],
            )

    async def check_input(self, text: str, context: RequestContext,
                          channel: str = "web", history: list = None) -> SecurityResponse:
        """输入安全检查（对接方案 8.2）"""
        context.stage = "input"
        req = SecurityRequest(
            context=context,
            payload={"text": text, "channel": channel, "history": history or []},
        )
        return await self._post("/v1/input/check", req)

    async def check_output(self, text: str, context: RequestContext,
                           channel: str = "web") -> SecurityResponse:
        """输出安全检查（对接方案 8.5）"""
        context.stage = "output"
        req = SecurityRequest(
            context=context,
            payload={"text": text, "channel": channel},
        )
        return await self._post("/v1/output/check", req)

    async def check_tool_pre(self, tool_name: str, arguments: dict,
                             context: RequestContext, tool_call_id: str = "",
                             tool_type: str = "", description: str = "",
                             database: str = "") -> SecurityResponse:
        """工具调用前检查（对接方案 8.3）"""
        context.stage = "tool_pre"
        req = SecurityRequest(
            context=context,
            payload={
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "arguments": arguments,
                "tool_type": tool_type,
                "description": description,
                "database": database,
            },
        )
        return await self._post("/v1/tool/pre_check", req)

    async def check_content(self, url: str, content: str,
                            context: RequestContext, tool_name: str = "web_fetch",
                            tool_call_id: str = "", source: str = "web_fetch",
                            metadata: str = "") -> SecurityResponse:
        """外部内容检查（对接方案 8.4）"""
        context.stage = "content"
        req = SecurityRequest(
            context=context,
            payload={
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "url": url,
                "content": content,
                "source": source,
                "metadata": metadata,
            },
        )
        return await self._post("/v1/content/check", req)

    async def health_check(self) -> dict:
        """检查 Argus 健康状态"""
        try:
            async with self._client() as c:
                resp = await c.get("/health")
                return resp.json() if resp.status_code == 200 else {"status": "error"}
        except Exception:
            return {"status": "error"}


# 全局单例
argus = ArgusClient()
