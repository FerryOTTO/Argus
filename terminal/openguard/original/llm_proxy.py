# llm_proxy.py — LLM 密钥集中代理（借鉴 AgentClaw Provider Catalog + 5 级路由）
# 新增：5 级优先级路由、_sanitize_messages 清洗、_FIXED_TEMPERATURE_MODELS 白名单、
#       SSE 正确头、max_completion_tokens 兼容、诊断日志、/llm/v1/messages Claude 原生协议
import json, time, uuid, secrets
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from config import config
from database import (find_user_by_agent_id, find_user_by_id, insert_usage_record,
    sum_user_tokens_since, get_week_start_ms)

router = APIRouter()

# ===== 1. 特殊模型参数白名单 =====
_FIXED_TEMPERATURE_MODELS = {"kimi-k2.5","kimi-k2","moonshot-v1-128k"}

# ===== 2. 消息清洗器（AgentClaw 风格：按 role 白名单过滤字段） =====
def _sanitize_messages(messages):
    _ALLOWED = {"system":{"role","content","name"},"user":{"role","content","name"},
                "assistant":{"role","content","tool_calls","refusal"},"tool":{"role","content","tool_call_id"}}
    cleaned = []
    for msg in messages:
        role = msg.get("role", "user")
        allowed = _ALLOWED.get(role, {"role","content"})
        out = {k: msg[k] for k in allowed if k in msg}
        if role != "assistant" and out.get("content") is None: out["content"] = ""
        if role == "assistant" and out.get("content") is None and "tool_calls" not in out: out["content"] = ""
        if "tool_calls" in out and out["tool_calls"]:
            s = []
            for tc in out["tool_calls"]:
                if isinstance(tc, dict) and "function" in tc:
                    f = tc["function"] or {}
                    s.append({"id": tc.get("id",""), "type": tc.get("type","function"),
                        "function": {"name": f.get("name","") if isinstance(f, dict) else "",
                                     "arguments": f.get("arguments","{}") if isinstance(f, dict) else "{}"}})
            out["tool_calls"] = s
            if not out["tool_calls"]: del out["tool_calls"]
        cleaned.append(out)
    return cleaned

# ===== 3. 提供商映射（4 家：DeepSeek / MiniMax / GLM / Kimi） =====
_PROVIDER_MAP = {
    "deepseek": ("deepseek_base_url", "deepseek_api_key"),
    "moonshot": ("moonshot_base_url", "moonshot_api_key"),
    "kimi":     ("moonshot_base_url", "moonshot_api_key"),
    "glm":      ("zhipu_base_url", "zhipu_api_key"),
    "zhipu":    ("zhipu_base_url", "zhipu_api_key"),
    "minimax":  ("minimax_base_url", "minimax_api_key"),
}

# ===== 4. 优先级解析：统一端点 → 自部署 vLLM → 4 家厂商 =====
def resolve_provider(model):
    ml = model.lower()
    # P1 统一端点（公司自建 OpenAI 协议代理，可选）
    if config.llm_api_base and config.llm_api_key:
        return config.llm_api_base, config.llm_api_key, "llm-unified", None
    # P2 自部署 vLLM（可选）
    if config.hosted_vllm_api_base:
        return config.hosted_vllm_api_base, config.hosted_vllm_api_key or "dummy", "hosted_vllm", None
    # 4 家厂商
    for kw, (ba, ka) in _PROVIDER_MAP.items():
        if kw in ml:
            base = getattr(config, ba, ""); key = getattr(config, ka, "")
            if base and key: return base, key, kw, None
    raise ValueError(f"未配置模型 {model} 对应的提供商（支持：deepseek/minimax/glm/kimi）")

def _build_chat_url(base_url):
    u = base_url.rstrip("/")
    return u if u.endswith("/chat/completions") else u + "/chat/completions"

# ===== 配额（周度） =====
_TIER_LIMITS = {"free":config.quota_free, "basic":config.quota_basic, "pro":config.quota_pro}

def _unauthorized(detail="missing or invalid proxy token"):
    return JSONResponse(status_code=401, content={"error":{"message":detail,"type":"unauthorized"}})

async def _check_auth(request):
    auth = request.headers.get("Authorization","")
    if not auth.startswith("Bearer ") or not config.llm_proxy_token: return None
    # 恒定时间比较，避免代理 token 计时侧信道
    if not secrets.compare_digest(auth[7:].strip(), config.llm_proxy_token): return None
    agent_id = request.headers.get("X-Agent-Id","").strip()
    if agent_id:
        user = await find_user_by_agent_id(agent_id)
        if user: return user["id"], agent_id
    # 无法归属到用户/agent：默认仍放行（OpenClaw provider 客户端不带 X-Agent-Id），
    # 但不再静默——打印告警；开启 LLM_PROXY_REQUIRE_AGENT 时拒绝（fail-closed）。
    if config.llm_proxy_require_agent:
        print("[LLM Proxy] rejected unattributed request (LLM_PROXY_REQUIRE_AGENT=true)", flush=True)
        return None
    print("[LLM Proxy] warn: unattributed request (no X-Agent-Id), quota not enforced", flush=True)
    return "", ""

def _quota_exceeded(used, limit):
    return JSONResponse(status_code=429, content={"error":{
        "message":f"Weekly token quota exceeded ({used:,}/{limit:,}). Resets on Monday 00:00 UTC.",
        "type":"quota_exceeded","used_tokens":used,"limit_tokens":limit}})

async def _check_quota(user_id):
    user = await find_user_by_id(user_id)
    if not user: return None
    limit = int(user["daily_token_quota"]) if user.get("daily_token_quota") is not None else _TIER_LIMITS.get(user.get("quota_tier") or "free", _TIER_LIMITS["free"])
    used = await sum_user_tokens_since(user_id, get_week_start_ms())
    if used >= limit:
        print(f"[LLM Proxy] weekly quota exceeded: user={user_id} used={used} limit={limit}", flush=True)
        return _quota_exceeded(used, limit)
    return None

def _compute_cost(model, prompt_tokens, completion_tokens):
    """按模型定价（元/1K tokens）计算本次调用成本。未定价模型返回 0。"""
    pricing = config.model_pricing.get(model)
    if not pricing:
        return 0.0
    return round((prompt_tokens / 1000.0) * pricing.get("input", 0.0)
                 + (completion_tokens / 1000.0) * pricing.get("output", 0.0), 6)


async def _record_usage(agent_id, user_id, model, usage, provider=""):
    try:
        prompt = int((usage or {}).get("prompt_tokens", 0) or 0)
        completion = int((usage or {}).get("completion_tokens", 0) or 0)
        await insert_usage_record({
            "id": "ur_" + uuid.uuid4().hex[:12], "user_id": user_id or None,
            "agent_id": agent_id or None, "model": model, "provider": provider,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": int((usage or {}).get("total_tokens", 0) or 0),
            "cost": _compute_cost(model, prompt, completion),
            "created_at": int(time.time() * 1000)})
    except Exception as e:
        print(f"[LLM Proxy] usage record failed: {type(e).__name__}: {e}")

# ===== /llm/v1/chat/completions（OpenAI 兼容）=====
@router.post("/llm/v1/chat/completions")
async def chat_completions(request: Request):
    ident = await _check_auth(request)
    if ident is None: return _unauthorized()
    user_id, agent_id = ident
    try:
        body = json.loads(await request.body())
    except Exception:
        return JSONResponse(status_code=400, content={"error":{"message":"invalid JSON body"}})
    model = str(body.get("model",""))
    is_stream = bool(body.get("stream"))
    print(f"[LLM Proxy] req: agent={agent_id or '-'} user={user_id or '-'} model={model} stream={is_stream}", flush=True)
    if user_id:
        q = await _check_quota(user_id)
        if q is not None: return q
    # max_completion_tokens 兼容
    if body.get("max_completion_tokens"): body["max_tokens"] = int(body["max_completion_tokens"])
    # 消息清洗
    if isinstance(body.get("messages"), list):
        body["messages"] = _sanitize_messages(body["messages"])
    # 5 级路由
    try:
        base_url, api_key, provider, extra_h = resolve_provider(model)
    except Exception as e:
        return JSONResponse(status_code=503, content={"error":{"message":str(e)}})
    upstream_url = _build_chat_url(base_url)
    # 直接厂商/自部署 vLLM 需要裸模型名（去掉 "provider/" 前缀）；统一端点(LiteLLM/OneAPI)保留完整 id
    if provider != "llm-unified" and "/" in model:
        body["model"] = model.split("/", 1)[1]
    # 特殊模型参数
    base = model.split("/")[-1].lower()
    if base in _FIXED_TEMPERATURE_MODELS:
        body.pop("temperature", None); body.pop("top_p", None)
    if is_stream and "stream_options" not in body:
        body["stream_options"] = {"include_usage":True}
    headers = {"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}
    if extra_h: headers.update(extra_h)
    # 诊断日志
    dbg = {k:v for k,v in body.items() if k!="messages"}
    sm = [(m.get("role"),"tool_calls" in m, bool(m.get("tool_call_id"))) for m in body.get("messages",[])[:5]]
    print(f"[LLM Proxy] route: provider={provider} base={base_url} extra={bool(extra_h)}", flush=True)
    print(f"[LLM Proxy] args(no msg): {dbg}", flush=True)
    print(f"[LLM Proxy] msg roles[:5]: {sm}", flush=True)
    try:
        if not is_stream:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(upstream_url, json=body, headers=headers)
                try: data = resp.json()
                except Exception as e:
                    print(f"[LLM Proxy] upstream non-json {resp.status_code}: {resp.text[:500]}", flush=True)
                    return JSONResponse(status_code=502, content={"error":{"message":f"invalid upstream: {resp.text[:500]}"}})
                if resp.status_code != 200:
                    print(f"[LLM Proxy] upstream err {resp.status_code}: {json.dumps(data, ensure_ascii=False)[:800]}", flush=True)
                    return JSONResponse(status_code=resp.status_code, content=data)
                await _record_usage(agent_id, user_id, model, data.get("usage"), provider)
                return JSONResponse(content=data)
        # 流式
        async def sse_stream():
            usage_seen = None
            try:
                async with httpx.AsyncClient(timeout=300.0) as client:
                    async with client.stream("POST", upstream_url, json=body, headers=headers) as resp:
                        if resp.status_code != 200:
                            err = await resp.atext()
                            yield f"data: {json.dumps({'error':{'message':f'upstream {resp.status_code}: {err[:300]}'}})}\n\n"
                            yield "data: [DONE]\n\n"; return
                        async for line in resp.aiter_lines():
                            yield line + "\n"
                            if line.startswith("data:"):
                                p = line[5:].strip()
                                if p == "[DONE]": continue
                                try:
                                    c = json.loads(p)
                                    if isinstance(c, dict) and c.get("usage"): usage_seen = c["usage"]
                                except Exception: pass
            except Exception as e:
                print(f"[LLM Proxy] stream err: {type(e).__name__}: {e}", flush=True)
                yield f"data: {json.dumps({'error':{'message':f'{type(e).__name__}: {e}'}})}\n\n"
            finally:
                yield "data: [DONE]\n\n"
            if usage_seen is not None:
                await _record_usage(agent_id, user_id, model, usage_seen, provider)
        return StreamingResponse(sse_stream(), media_type="text/event-stream",
            headers={"Cache-Control":"no-cache","Connection":"keep-alive","X-Accel-Buffering":"no"})
    except httpx.ConnectError as e:
        print(f"[LLM Proxy] connect err: {e}", flush=True)
        return JSONResponse(status_code=502, content={"error":{"message":"upstream unreachable"}})
    except Exception as e:
        print(f"[LLM Proxy] unexpected: {type(e).__name__}: {e}", flush=True)
        return JSONResponse(status_code=500, content={"error":{"message":f"{type(e).__name__}: {e}"}})

# ===== /llm/v1/messages（Claude 原生协议）=====
@router.post("/llm/v1/messages")
async def claude_messages(request: Request):
    ident = await _check_auth(request)
    if ident is None: return _unauthorized()
    user_id, agent_id = ident
    try:
        body = json.loads(await request.body())
    except Exception:
        return JSONResponse(status_code=400, content={"error":{"message":"invalid JSON body"}})
    model = str(body.get("model",""))
    is_stream = bool(body.get("stream"))
    print(f"[LLM Proxy] /messages Claude native: model={model} stream={is_stream}", flush=True)
    if user_id:
        q = await _check_quota(user_id)
        if q is not None: return q
    # Claude 协议 → OpenAI 格式转换 + 走主路由（4 家厂商）
    msgs = []
    for m in body.get("messages", []):
        role = m.get("role","user"); content = m.get("content")
        if isinstance(content, list):
            content = "\n".join([(c.get("text","") if isinstance(c, dict) else "") for c in content])
        msgs.append({"role":role,"content":content or ""})
    sb = dict(body); sb["messages"] = msgs; sb["max_tokens"] = body.get("max_tokens", 4096)
    try:
        base_url, api_key, provider, extra_h = resolve_provider(model)
    except Exception as e:
        return JSONResponse(status_code=503, content={"error":{"message":str(e)}})
    upstream_url = _build_chat_url(base_url)
    # 直接厂商需要裸模型名（去掉 "provider/" 前缀）
    if provider != "llm-unified" and "/" in model:
        sb["model"] = model.split("/", 1)[1]
    hs = {"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}
    if extra_h: hs.update(extra_h)
    if is_stream and "stream_options" not in sb: sb["stream_options"] = {"include_usage":True}
    try:
        if not is_stream:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(upstream_url, json=sb, headers=hs)
                data = resp.json()
                ch = (data.get("choices") or [{}])[0]; m0 = ch.get("message", {}); usage = data.get("usage", {})
                out = {"id":data.get("id","msg_"+uuid.uuid4().hex[:12]),"type":"message","role":"assistant",
                    "model":model,"content":[],"stop_reason":ch.get("finish_reason"),
                    "usage":{"input_tokens":usage.get("prompt_tokens",0),"output_tokens":usage.get("completion_tokens",0)}}
                if m0.get("content"): out["content"].append({"type":"text","text":m0["content"]})
                for tc in m0.get("tool_calls") or []:
                    f = tc.get("function") or {}
                    try: args = json.loads(f.get("arguments","{}"))
                    except Exception: args = {}
                    out["content"].append({"type":"tool_use","id":tc.get("id",""),"name":f.get("name",""),"input":args})
                if resp.status_code != 200: return JSONResponse(status_code=resp.status_code, content=data)
                await _record_usage(agent_id, user_id, model, usage, provider)
                return JSONResponse(content=out)
        async def _s():
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream("POST", upstream_url, json=sb, headers=hs) as resp:
                    async for line in resp.aiter_lines(): yield line + "\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_s(), media_type="text/event-stream",
            headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
    except httpx.ConnectError:
        return JSONResponse(status_code=502, content={"error":{"message":"upstream unreachable"}})

# ===== /llm/v1/models & health =====
@router.get("/llm/v1/models")
async def list_models(request: Request):
    ident = await _check_auth(request)
    if ident is None: return _unauthorized()
    data = [{"id":m["id"],"object":"model","owned_by":"openguard-proxy","name":m["name"],"description":m.get("description","")} for m in config.available_models]
    return {"object":"list","data":data}

@router.get("/llm/v1/health")
async def llm_health():
    any_key = bool(config.llm_api_base or config.hosted_vllm_api_base
        or config.deepseek_api_key or config.minimax_api_key
        or config.zhipu_api_key or config.moonshot_api_key)
    return {"status":"ok","configured":bool(any_key and config.llm_proxy_token)}
