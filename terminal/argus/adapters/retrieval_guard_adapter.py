"""检索安全模块 Adapter：对接 Argus 统一接口。

职责（翻译官）：收统一 SecurityRequest → 拆给原模块三件套 → 结果翻译回统一 ModuleResult。
调用链：A URL 白名单 → cleaner 清洗 → B PIGuard 检测 → C 提示词包装。
"""
import logging
import threading

from starlette.concurrency import run_in_threadpool

from argus.adapters.base import BaseAdapter
from argus.common.models import ModuleResult, SecurityRequest
from argus.modules.retrieval_guard.original.a_url import URLWhitelist
from argus.modules.retrieval_guard.original.c_prompt import PromptWrapper
from argus.modules.retrieval_guard.original.cleaner import clean
# 注意：b_injection 依赖 torch，不在顶部导入——
# 保证没装 torch / 没下模型时 FastAPI 仍能启动（懒加载 + 统一接口异常兜底）

logger = logging.getLogger(__name__)


class RetrievalGuardAdapter(BaseAdapter):
    name = "retrieval_guard"

    def __init__(self, model_path: str = None, guards: dict | None = None):
        # 只保存配置，不加载模型（PIGuard 首次调用 B 时才加载，见 run()）
        guards = guards or {}
        self._guard_a = guards.get("A", True)   # URL 白名单
        self._guard_b = guards.get("B", True)   # PIGuard 注入检测
        self._guard_c = guards.get("C", True)   # 提示词包装
        self._model_path = model_path
        self._url_guard = URLWhitelist()
        self._injection_guard = None            # 懒加载：第一次 run() 且 B 开启时创建
        self._b_skip_reason = ''                # B 层降级原因（缺 torch/权重）
        self._load_lock = threading.Lock()      # 双检锁：防并发首次加载重复实例化
        self._wrapper = PromptWrapper()
        if self._guard_b:
            # 后台预热：启动不阻塞，模型在后台加载，避免首次调用撞上 HTTP 超时
            threading.Thread(target=self._warmup, daemon=True).start()

    def _warmup(self) -> None:
        try:
            with self._load_lock:
                if self._injection_guard is None:
                    from argus.modules.retrieval_guard.original.b_injection import InjectionGuard
                    self._injection_guard = InjectionGuard(model_path=self._model_path)
        except Exception as exc:
            # 未见 torch / 未见 PIGuard 权重：降级为只跑 A+C，避免每次调用重试。
            self._guard_b = False
            self._b_skip_reason = str(exc)[:200]

    async def run(self, request: SecurityRequest) -> ModuleResult:
        payload = request.payload
        # 契约：团队统一 content/tool_name（io_guard 对接）；兼容早期 text/tool
        text = payload.get("content") or payload.get("text", "")
        url = payload.get("url", "")

        # ── 适配器 A：URL 白名单（原 POST /url/check，guards.A=false 关闭）──
        if self._guard_a and url and not self._url_guard.is_trusted(url):
            logger.warning("[retrieval_guard] A block url=%s", url)
            return ModuleResult(
                module=self.name, action="block", risk_score=1.0,
                reason=f"url_not_in_whitelist: {url}",
                details={"guard": "A", "url": url},
            )

        # B/C 全关：不送检也不包装，直接放行
        if not self._guard_b and not self._guard_c:
            return ModuleResult(module=self.name, action="allow", reason="guards_off")

        tool_value = payload.get("tool_name") or payload.get("tool", "")
        tool = tool_value if isinstance(tool_value, str) else ""

        # ── 清洗：嵌套 JSON / 错误短路 / OpenClaw 信任边界正文提取 ──
        check_text = clean(text, tool_name=tool)
        if check_text is None:
            return ModuleResult(module=self.name, action="allow", reason="skip_empty_or_error")

        # ── 适配器 B：PIGuard 注入检测（原 POST /guard，guards.B=false 关闭）──
        # 懒加载：第一次走到这里才导入 torch 并构造模型；加载失败抛给 _run_adapter 的
        # on_error 兜底（allow → 返回 module_error，服务不崩，其他模块不受影响）
        # GPU 推理 ~0.5s，放线程池防止阻塞 FastAPI 事件循环；模型内部已有锁保证并发安全
        if self._guard_b:
            if self._injection_guard is None:
                with self._load_lock:
                    if self._injection_guard is None:
                        try:
                            from argus.modules.retrieval_guard.original.b_injection import InjectionGuard
                            self._injection_guard = InjectionGuard(model_path=self._model_path)
                        except Exception as exc:
                            # B 层不可用（缺 torch 或 PIGuard 权重）时降级为 A+C 继续，
                            # 而不是抛异常被 on_error 兜成 module_error（那会连带跳过 C 层包装）。
                            logger.warning(
                                "[retrieval_guard] B guard unavailable, fallback to A+C: %s", exc
                            )
                            self._guard_b = False
                            self._b_skip_reason = str(exc)[:200]
            if self._guard_b:
                result = await run_in_threadpool(self._injection_guard.check, check_text)
                if not result["safe"]:
                    logger.warning("[retrieval_guard] B block score=%s", result["score"])
                    return ModuleResult(
                        module=self.name, action="block",
                        risk_score=result["score"],
                        reason=f"prompt_injection score={result['score']}",
                        details={"guard": "B", "hit_window": result.get("hit_window")},
                    )

        # ── 适配器 C：提示词包装（原 POST /wrap，guards.C=false 则原样放行）──
        if not self._guard_c:
            return ModuleResult(module=self.name, action="allow", reason="passed")

        metadata = f"Source: {'Web Search' if tool == 'web_search' else 'Web Content'}"
        wrapped = self._wrapper.wrap(check_text, metadata=metadata, warning="")
        return ModuleResult(
            module=self.name, action="rewrite", reason="wrapped",
            # 双字段：团队契约读 content，早期补丁读 text，两边都不破
            modified_data={"content": wrapped, "text": wrapped},
            details={"guard": "C"},
        )
