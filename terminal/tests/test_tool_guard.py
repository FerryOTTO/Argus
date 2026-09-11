"""Clawguard — Tool Guard 意图匹配裁判测试套件

覆盖:
- 会话存储:prompt 绑定、工具链记录、参数摘要、链长上限、TTL 清理
- LLM 配置:默认值/环境变量/运行期修改/脱敏
- IntentMatchDetector:正常打分、JSON 容错、JSON 失败重发、score clamp、空锚点异常
- ToolGuardAdapter:无会话、未配置、低/中/高分映射、LLM 异常兜底
- 审计:由 API 层统一进程内写入(见 test_audit_* 集成测试),Adapter 不再直接对接
"""

import asyncio
import json
import os
import sys
import tempfile
import time

# Windows 控制台 GBK 编码无法输出中文/emoji,统一切到 UTF-8
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        sys.stdout = __import__('io').TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

from clawguard.adapters.tool_guard_adapter import ToolGuardAdapter
from clawguard.common.models import RequestContext, SecurityRequest
from clawguard.modules.tool_guard.intent_match import IntentMatchDetector
from clawguard.modules.tool_guard.llm_config import ToolGuardLLMConfig
from clawguard.modules.tool_guard.session_store import (
    ToolSessionStore,
    summarize_arguments,
)


def _request(session_id="s1", tool_name="read_file", arguments=None) -> SecurityRequest:
    return SecurityRequest(
        context=RequestContext(
            trace_id="t1",
            session_id=session_id,
            user_id="u1",
            stage="tool_pre",
        ),
        payload={"tool_name": tool_name, "arguments": arguments or {}},
    )


def _config(**overrides) -> ToolGuardLLMConfig:
    values = {
        "base_url": "http://test-llm/v1",
        "api_key": "test-key",
        "model": "test-model",
        "block_threshold": 0.4,
        "review_threshold": 0.7,
        "timeout_seconds": 5.0,
    }
    values.update(overrides)
    return ToolGuardLLMConfig(values)


def _detector_for_score(score: float):
    """构造固定返回 score 的假 LLM,返回 (detector, client)。"""
    content = json.dumps({"score": score, "reason": "judge says", "deviation": "dev"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    detector = IntentMatchDetector(
        base_url="http://test-llm/v1", model="test-model", client=client
    )
    return detector, client


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Part A: 会话存储
# ---------------------------------------------------------------------------

class TestSessionStore:
    @staticmethod
    def test_prompt_and_chain():
        store = ToolSessionStore(ttl_seconds=3600)
        store.set_prompt("s1", "整理本地项目资料并输出报告")
        store.record_call("s1", "read_file", {"path": "C:/demo/a.txt"})
        store.record_call("s1", "web_search", {"query": "clawguard", "limit": 5})
        session = store.get("s1")
        assert session is not None
        assert session.original_prompt == "整理本地项目资料并输出报告"
        assert len(session.tool_calls) == 2
        assert session.tool_calls[0]["tool_name"] == "read_file"
        assert session.tool_calls[0]["arguments"]["path"] == "C:/demo/a.txt"
        assert session.tool_calls[1]["tool_name"] == "web_search"
        print("  ✓ A1 prompt 绑定与工具链记录")

    @staticmethod
    def test_argument_summarize():
        summary = summarize_arguments(
            {
                "path": "x" * 500,
                "count": 3,
                "enabled": True,
                "extra": {"nested": 1},
                "none": None,
            }
        )
        assert summary["path"].endswith("...")
        assert len(summary["path"]) < 500
        assert summary["count"] == "3"
        assert summary["enabled"] == "True"
        assert summary["extra"] == "dict"
        assert summary["none"] == "None"
        assert summarize_arguments("not-a-dict") == {}
        print("  ✓ A2 参数摘要与截断")

    @staticmethod
    def test_chain_length_limit():
        store = ToolSessionStore(ttl_seconds=3600, max_chain_len=3)
        for i in range(5):
            store.record_call("s1", f"tool_{i}", {"i": i})
        session = store.get("s1")
        assert len(session.tool_calls) == 3
        assert session.tool_calls[0]["tool_name"] == "tool_2"
        assert session.tool_calls[-1]["tool_name"] == "tool_4"
        assert session.chain_truncated is True
        print("  ✓ A3 工具链长度上限与截断标记")

    @staticmethod
    def test_ttl_cleanup():
        store = ToolSessionStore(ttl_seconds=0.1)
        store.set_prompt("s1", "prompt")
        assert store.get("s1") is not None
        time.sleep(0.2)
        assert store.get("s1") is None  # 惰性删除
        store.set_prompt("s2", "p2")
        time.sleep(0.15)
        assert store.cleanup_expired() >= 1  # s2 到期后被批量清理
        print("  ✓ A4 TTL 过期清理")


# ---------------------------------------------------------------------------
# Part B: LLM 配置
# ---------------------------------------------------------------------------

class TestLLMConfig:
    @staticmethod
    def test_defaults_and_env():
        old = {k: os.environ.get(k) for k in (
            "TOOL_GUARD_LLM_BASE_URL", "TOOL_GUARD_LLM_MODEL", "TOOL_GUARD_BLOCK_THRESHOLD",
            "TOOL_GUARD_LLM_API_KEY")}
        try:
            os.environ["TOOL_GUARD_LLM_BASE_URL"] = "http://env-llm/v1"
            os.environ["TOOL_GUARD_LLM_MODEL"] = "env-model"
            os.environ["TOOL_GUARD_BLOCK_THRESHOLD"] = "0.25"
            os.environ["TOOL_GUARD_LLM_API_KEY"] = "env-key"
            config = ToolGuardLLMConfig({"base_url": "http://yaml-llm/v1", "model": "yaml-model"})
            assert config.get("base_url") == "http://env-llm/v1"
            assert config.get("model") == "env-model"
            assert config.get("block_threshold") == 0.25
            assert config.get("review_threshold") == 0.7  # 默认值
            assert config.get("api_key") == "env-key"
            assert config.configured() is True
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        print("  ✓ B1 环境变量优先于 yaml/默认值")

    @staticmethod
    def test_snapshot_masks_key():
        config = _config()
        snap = config.snapshot()
        assert snap["api_key"] == "***"
        assert snap["model"] == "test-model"
        print("  ✓ B2 配置快照脱敏")

    @staticmethod
    def test_update_runtime():
        config = _config()
        snap = config.update({"model": "new-model", "block_threshold": 0.3, "unknown_key": 1})
        assert snap["model"] == "new-model"
        assert snap["block_threshold"] == 0.3
        assert "unknown_key" not in snap
        assert config.get("model") == "new-model"
        print("  ✓ B3 运行期更新配置")

    @staticmethod
    def test_configured_requires_base_url_and_model():
        assert ToolGuardLLMConfig({"base_url": "", "model": "m"}).configured() is False
        assert ToolGuardLLMConfig({"base_url": "http://x", "model": ""}).configured() is False
        assert ToolGuardLLMConfig({"base_url": "http://x", "model": "m", "api_key": "k"}).configured() is True
        # 无 key 仅允许本地服务(如 Ollama)
        assert ToolGuardLLMConfig({"base_url": "http://127.0.0.1:11434", "model": "m"}).configured() is True
        assert ToolGuardLLMConfig({"base_url": "https://api.deepseek.com/v1", "model": "m"}).configured() is False
        print("  ✓ B4 configured 判定")


# ---------------------------------------------------------------------------
# Part C: IntentMatchDetector
# ---------------------------------------------------------------------------

class TestDetector:
    @staticmethod
    def test_normal_score():
        detector, client = _detector_for_score(0.85)
        try:
            result = _run(detector.detect("写一篇报告", [{"tool_name": "read_file", "arguments": {"path": "a.txt"}}], "write_file", {"path": "b.md"}))
            assert result.score == 0.85
            assert result.reason == "judge says"
        finally:
            _run(client.aclose())
        print("  ✓ C1 正常打分解析")

    @staticmethod
    def test_json_with_extra_text():
        content = '好的,分析如下:```json\n{"score": 0.2, "reason": "偏离", "deviation": "无关调用"}\n```'

        def handler(request):
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        detector = IntentMatchDetector(base_url="http://t", model="m", client=client)
        try:
            result = _run(detector.detect("查询天气", [], "send_email", {"to": "x"}))
            assert result.score == 0.2
            assert result.deviation == "无关调用"
        finally:
            _run(client.aclose())
        print("  ✓ C2 JSON 容错解析(带前后缀文字)")

    @staticmethod
    def test_score_clamp():
        for raw in (2.5, -0.5, 1.0, 0.0):
            detector, client = _detector_for_score(raw)
            try:
                result = _run(detector.detect("p", [], "t", {}))
                assert 0.0 <= result.score <= 1.0
            finally:
                _run(client.aclose())
        print("  ✓ C3 score 边界收敛")

    @staticmethod
    def test_empty_prompt_raises():
        detector, client = _detector_for_score(0.9)
        try:
            try:
                _run(detector.detect("   ", [], "t", {}))
                raise AssertionError("应抛出 ValueError")
            except ValueError:
                pass
        finally:
            _run(client.aclose())
        print("  ✓ C4 空意图锚点抛错")

    @staticmethod
    def test_http_error_propagates():
        def handler(request):
            return httpx.Response(500, text="upstream down")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        detector = IntentMatchDetector(base_url="http://t", model="m", client=client)
        try:
            try:
                _run(detector.detect("p", [], "t", {}))
                raise AssertionError("应抛出异常")
            except httpx.HTTPStatusError:
                pass
        finally:
            _run(client.aclose())
        print("  ✓ C5 LLM 上游异常上抛")

    @staticmethod
    def test_json_retry_succeeds():
        """首次输出非格式化文本,按重发策略以强制指令重发后成功恢复。"""
        calls = []
        replies = [
            "好的,分析如下,但请稍等 {score: 0.75, reason: 失败",  # 不可解析
            json.dumps({"score": 0.75, "reason": "retry ok", "deviation": ""}),
        ]

        def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(
                200, json={"choices": [{"message": {"content": replies.pop(0)}}]}
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        detector = IntentMatchDetector(base_url="http://t", model="m", client=client)
        try:
            result = _run(detector.detect("查询天气", [], "web_search", {"query": "北京"}))
            assert result.score == 0.75
            assert result.reason == "retry ok"
            assert len(calls) == 2  # 首次失败 + 重发一次
            retry_text = calls[1]["messages"][-1]["content"]
            assert "重新输出" in retry_text  # 重发请求携带强制格式指令
            assert "不可解析" in retry_text
        finally:
            _run(client.aclose())
        print("  ✓ C6 JSON 解析失败重发一次后成功")

    @staticmethod
    def test_json_retry_exhausted_raises():
        """重发后仍不可解析,异常上抛由上层按 on_error 兜底。"""
        replies = ["不是 JSON", "也不是 JSON"]

        def handler(request):
            return httpx.Response(
                200, json={"choices": [{"message": {"content": replies.pop(0)}}]}
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        detector = IntentMatchDetector(base_url="http://t", model="m", client=client)
        try:
            try:
                _run(detector.detect("p", [], "t", {}))
                raise AssertionError("应抛出 ValueError")
            except ValueError:
                pass
        finally:
            _run(client.aclose())
        print("  ✓ C7 重发后仍失败则上抛")


# ---------------------------------------------------------------------------
# Part D: ToolGuardAdapter
# ---------------------------------------------------------------------------

class TestAdapter:
    @staticmethod
    def test_no_session_context_allow():
        adapter = ToolGuardAdapter(config=_config(), store=ToolSessionStore(), on_error="block")
        result = _run(adapter.run(_request()))
        assert result.action == "allow"
        assert result.reason == "no_session_context"
        assert result.success is False
        print("  ✓ D1 无会话上下文放行并提示")

    @staticmethod
    def test_llm_unconfigured_blocks():
        adapter = ToolGuardAdapter(
            config=ToolGuardLLMConfig({"base_url": "", "model": ""}),
            store=_store_with_context(),
            on_error="block",
        )
        result = _run(adapter.run(_request()))
        assert result.action == "block"
        assert result.reason == "llm_unconfigured"
        print("  ✓ D2 LLM 未配置按 on_error 拦截")

    @staticmethod
    def test_llm_unconfigured_allows_when_on_error_allow():
        adapter = ToolGuardAdapter(
            config=ToolGuardLLMConfig({"base_url": "", "model": ""}),
            store=_store_with_context(),
            on_error="allow",
        )
        result = _run(adapter.run(_request()))
        assert result.action == "allow"
        print("  ✓ D3 on_error=allow 时未配置放行")

    @staticmethod
    def test_high_score_allows():
        detector, client = _detector_for_score(0.9)
        try:
            adapter = ToolGuardAdapter(
                config=_config(), store=_store_with_context(), detector=detector, on_error="block"
            )
            result = _run(adapter.run(_request()))
            assert result.action == "allow"
            assert result.risk_score == 0.0
            assert result.details["score"] == 0.9
            assert result.details["chain_length"] == 1
        finally:
            _run(client.aclose())
        print("  ✓ D4 高分放行")

    @staticmethod
    def test_mid_score_human_review():
        detector, client = _detector_for_score(0.5)
        try:
            adapter = ToolGuardAdapter(
                config=_config(), store=_store_with_context(), detector=detector, on_error="block"
            )
            result = _run(adapter.run(_request()))
            assert result.action == "human_review"
            assert result.risk_score == 0.6
        finally:
            _run(client.aclose())
        print("  ✓ D5 中分转人工确认")

    @staticmethod
    def test_low_score_blocks():
        detector, client = _detector_for_score(0.15)
        try:
            adapter = ToolGuardAdapter(
                config=_config(), store=_store_with_context(), detector=detector, on_error="block"
            )
            result = _run(adapter.run(_request()))
            assert result.action == "block"
            assert result.risk_score == 1.0
            assert result.reason.startswith("intent_score=0.15")
        finally:
            _run(client.aclose())
        print("  ✓ D6 低分拦截")

    @staticmethod
    def test_detector_exception_falls_back():
        def handler(request):
            return httpx.Response(500, text="boom")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        detector = IntentMatchDetector(base_url="http://t", model="m", client=client)
        try:
            adapter = ToolGuardAdapter(
                config=_config(), store=_store_with_context(), detector=detector, on_error="block"
            )
            result = _run(adapter.run(_request()))
            assert result.action == "block"
            assert result.reason == "module_error"
            assert result.success is False
            assert result.error and "500" in result.error
        finally:
            _run(client.aclose())
        print("  ✓ D7 LLM 异常按 on_error 兜底")


# ---------------------------------------------------------------------------
# Part E: 已移除 — 审计由 API 层统一进程内写入(见 test_audit_* 集成测试)
# ---------------------------------------------------------------------------


def _store_with_context() -> ToolSessionStore:
    store = ToolSessionStore(ttl_seconds=3600)
    store.set_prompt("s1", "把本地项目资料整理成一份报告")
    store.record_call("s1", "read_file", {"path": "C:/demo/a.txt"})
    return store


# 测试运行器 ----------------------------------------------------------------

def run_all_tests():
    print("=" * 70)
    print("Clawguard Tool Guard — 意图匹配裁判测试套件")
    print("=" * 70)

    test_groups = [
        ("Part A: 会话存储", [
            TestSessionStore.test_prompt_and_chain,
            TestSessionStore.test_argument_summarize,
            TestSessionStore.test_chain_length_limit,
            TestSessionStore.test_ttl_cleanup,
        ]),
        ("Part B: LLM 配置", [
            TestLLMConfig.test_defaults_and_env,
            TestLLMConfig.test_snapshot_masks_key,
            TestLLMConfig.test_update_runtime,
            TestLLMConfig.test_configured_requires_base_url_and_model,
        ]),
        ("Part C: IntentMatchDetector", [
            TestDetector.test_normal_score,
            TestDetector.test_json_with_extra_text,
            TestDetector.test_score_clamp,
            TestDetector.test_empty_prompt_raises,
            TestDetector.test_http_error_propagates,
            TestDetector.test_json_retry_succeeds,
            TestDetector.test_json_retry_exhausted_raises,
        ]),
        ("Part D: ToolGuardAdapter", [
            TestAdapter.test_no_session_context_allow,
            TestAdapter.test_llm_unconfigured_blocks,
            TestAdapter.test_llm_unconfigured_allows_when_on_error_allow,
            TestAdapter.test_high_score_allows,
            TestAdapter.test_mid_score_human_review,
            TestAdapter.test_low_score_blocks,
            TestAdapter.test_detector_exception_falls_back,
        ]),
    ]

    total_passed = 0
    total_failed = 0
    group_results = []

    for group_name, tests in test_groups:
        print(f"\n{'─' * 70}")
        print(f"  {group_name}")
        print(f"{'─' * 70}")
        passed = 0
        failed = 0
        for test in tests:
            try:
                test()
                passed += 1
                total_passed += 1
            except Exception as e:
                failed += 1
                total_failed += 1
                print(f"  ✗ {test.__name__} FAILED: {e}")
                import traceback
                traceback.print_exc()
        group_results.append((group_name, passed, failed))

    print()
    print("=" * 70)
    print("测试汇总")
    print("=" * 70)
    for group_name, passed, failed in group_results:
        status = "✓ 全部通过" if failed == 0 else f"✗ {failed} 个失败"
        print(f"  {group_name}: {passed}/{passed + failed} — {status}")
    print(f"{'─' * 70}")
    print(f"  总计: {total_passed} 通过, {total_failed} 失败")
    print("=" * 70)

    if total_failed == 0:
        print("\n  🎉 所有测试通过！")
    else:
        print(f"\n  ⚠️ 有 {total_failed} 个测试失败,请检查。")

    return total_failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
