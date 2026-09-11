"""Step 6b: 个人版供应商 = 本机 openclaw.json 的 models.providers，直读直改。

真相源：~/.openclaw/openclaw.json（与 daemon openClawStateDir 口径一致：
OPENCLAW_STATE_DIR > OPENCLAW_HOME > bundle 内 openclaw-data > ~/.openclaw）。
浏览器不能直读本地文件，由 :8000 代理读写。改完即落盘（.bak 备份），
网关下次重载生效；切换当前模型改 agents.defaults.model.primary。
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1/local/openclaw-providers", tags=["local-providers"])


def _state_dir() -> Path:
    for cand in (os.getenv("OPENCLAW_STATE_DIR"), os.getenv("OPENCLAW_HOME")):
        if cand and os.path.isdir(cand):
            return Path(cand)
    # 个人版真相源优先走用户级 ~/.openclaw（网关实际读它）；
    # 只有它不存在时才回落 bundle 内 openclaw-data。
    home_oc = Path(os.path.expanduser("~")) / ".openclaw"
    if (home_oc / "openclaw.json").exists():
        return home_oc
    root = Path(__file__).resolve().parent.parent.parent
    bundled = root.parent / "openclaw-data"
    if bundled.is_dir():
        return bundled
    return home_oc


def _config_path() -> Path:
    return _state_dir() / "openclaw.json"


def _read_config() -> Dict[str, Any]:
    p = _config_path()
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_config(data: Dict[str, Any]) -> None:
    p = _config_path()
    try:
        if p.exists():
            p.with_suffix(".json.bak").write_text(
                p.read_text(encoding="utf-8-sig"), encoding="utf-8"
            )
    except Exception:
        pass
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _providers_dict(cfg: Dict[str, Any]) -> Dict[str, Any]:
    models = cfg.get("models")
    if not isinstance(models, dict):
        cfg["models"] = {}
        models = cfg["models"]
    provs = models.get("providers")
    if not isinstance(provs, dict):
        models["providers"] = {}
        provs = models["providers"]
    return provs


def _current_ref(cfg: Dict[str, Any]) -> str:
    try:
        return str(
            cfg.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", "")
        )
    except Exception:
        return ""


def _to_card(pid: str, p: Dict[str, Any], current_ref: str) -> Dict[str, Any]:
    models = p.get("models") if isinstance(p.get("models"), list) else []
    first_model = ""
    try:
        if models and isinstance(models[0], dict):
            first_model = str(models[0].get("id") or models[0].get("name") or "")
    except Exception:
        pass
    ref = f"{pid}/{first_model}" if first_model else pid
    return {
        "id": pid,
        "name": str(p.get("name") or pid),
        "mark": str(pid[:1]).upper() or "◉",
        "endpoint": str(p.get("baseUrl") or ""),
        "category": "本地模型" if "127.0.0.1" in str(p.get("baseUrl") or "") or "localhost" in str(p.get("baseUrl") or "") else "自定义",
        "active": True,
        "current": current_ref == ref or current_ref.startswith(pid + "/"),
        "model": first_model,
        "models": [str(m.get("id") or m.get("name")) for m in models if isinstance(m, dict)],
        "model_count": len(models),
        "api": str(p.get("api") or ""),
        "has_key": bool(p.get("apiKey")),
        "notes": "",
    }


@router.get("")
def list_openclaw_providers():
    cfg = _read_config()
    provs = _providers_dict(cfg)
    current_ref = _current_ref(cfg)
    cards = [_to_card(pid, p, current_ref) for pid, p in provs.items() if isinstance(p, dict)]
    return {"data": {"providers": cards, "current": current_ref, "path": str(_config_path())}}


class ProviderPutBody(BaseModel):
    id: str = ""
    baseUrl: Optional[str] = None
    apiKey: Optional[str] = None
    model: Optional[str] = None
    name: Optional[str] = None
    api: Optional[str] = None


@router.put("")
def put_openclaw_provider(body: ProviderPutBody):
    """新增或修改一个 provider，直写 openclaw.json。apiKey 空=不覆盖。"""
    pid = (body.id or "").strip()
    if not pid:
        return {"ok": False, "detail": "id required"}
    cfg = _read_config()
    provs = _providers_dict(cfg)
    p = deepcopy(provs.get(pid)) if isinstance(provs.get(pid), dict) else {}
    if body.baseUrl is not None and str(body.baseUrl).strip():
        p["baseUrl"] = str(body.baseUrl).strip()
    if body.apiKey:
        p["apiKey"] = body.apiKey
    if body.api is not None and str(body.api).strip():
        p["api"] = str(body.api).strip()
    if body.name is not None and str(body.name).strip():
        p["name"] = str(body.name).strip()
    if "api" not in p:
        p["api"] = "openai-completions"
    if body.model is not None and str(body.model).strip():
        mid = str(body.model).strip()
        models = p.get("models") if isinstance(p.get("models"), list) else []
        ids = [str(m.get("id") or m.get("name")) for m in models if isinstance(m, dict)]
        if mid not in ids:
            models.append({"id": mid, "name": mid.split("/")[-1], "input": ["text"]})
            p["models"] = models
    provs[pid] = p
    _write_config(cfg)
    return {"ok": True, "data": {"providers": [_to_card(k, v, _current_ref(cfg)) for k, v in provs.items() if isinstance(v, dict)]}}


class SwitchBody(BaseModel):
    id: str = ""
    model: Optional[str] = None


@router.post("/switch")
def switch_openclaw_provider(body: SwitchBody):
    """切换当前模型：改 agents.defaults.model.primary。网关重载后生效。"""
    pid = (body.id or "").strip()
    if not pid:
        return {"ok": False, "detail": "id required"}
    cfg = _read_config()
    provs = _providers_dict(cfg)
    p = provs.get(pid)
    if not isinstance(p, dict):
        return {"ok": False, "detail": "provider not found"}
    models = p.get("models") if isinstance(p.get("models"), list) else []
    mid = (body.model or "").strip()
    if not mid and models and isinstance(models[0], dict):
        mid = str(models[0].get("id") or models[0].get("name") or "")
    if not mid:
        return {"ok": False, "detail": "model required"}
    agents = cfg.get("agents")
    if not isinstance(agents, dict):
        cfg["agents"] = {}
        agents = cfg["agents"]
    defaults = agents.get("defaults")
    if not isinstance(defaults, dict):
        agents["defaults"] = {}
        defaults = agents["defaults"]
    model_cfg = defaults.get("model")
    if not isinstance(model_cfg, dict):
        defaults["model"] = {}
        model_cfg = defaults["model"]
    model_cfg["primary"] = f"{pid}/{mid}"
    _write_config(cfg)
    return {"ok": True, "data": {"primary": model_cfg["primary"]}}


@router.delete("/{pid}")
def delete_openclaw_provider(pid: str):
    cfg = _read_config()
    provs = _providers_dict(cfg)
    if pid not in provs:
        return {"ok": False, "detail": "not found"}
    # 不删当前正在用的
    if _current_ref(cfg).startswith(pid + "/") or _current_ref(cfg) == pid:
        return {"ok": False, "detail": "provider in use"}
    del provs[pid]
    _write_config(cfg)
    return {"ok": True}


def _read_text() -> str:
    p = _config_path()
    try:
        return p.read_text(encoding="utf-8-sig")
    except Exception:
        return ""


@router.get("/raw")
def get_openclaw_raw():
    """返回 openclaw.json 全文（个人版首页直接编辑）。"""
    return {"data": {"text": _read_text(), "path": str(_config_path())}}


class RawPutBody(BaseModel):
    text: str = ""


@router.put("/raw")
def put_openclaw_raw(body: RawPutBody):
    """整文件写回：必须合法 JSON 且含 models 段，否则拒绝。自动 .bak 备份。"""
    raw = body.text or ""
    try:
        data = json.loads(raw)
    except Exception as e:
        return {"ok": False, "detail": f"invalid JSON: {e}"}
    if not isinstance(data, dict) or not isinstance(data.get("models"), dict):
        return {"ok": False, "detail": "missing models section"}
    _write_config(data)
    return {"ok": True, "data": {"path": str(_config_path())}}
