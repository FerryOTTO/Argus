"""Personal local module config API - mirrors LLMGate TerminalConfigEditor groups, wired to real files."""
from __future__ import annotations
import json
import os
from copy import deepcopy
from typing import Any, Dict, Optional
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1/local", tags=["local-config"])

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
def _p(*parts): return os.path.join(ROOT, *parts)
PATHS = {
  "modules": _p("configs", "modules.yaml"),
  "policy": _p("clawguard", "modules", "io_guard", "original", "configs", "default_policy.json"),
  "whitelist": _p("clawguard", "modules", "retrieval_guard", "original", "a_url", "whitelist.yaml"),
  "b_injection": _p("clawguard", "modules", "retrieval_guard", "original", "b_injection", "config.yaml"),
  "c_prompt": _p("clawguard", "modules", "retrieval_guard", "original", "c_prompt", "config.yaml"),
  "users": _p("clawguard", "modules", "access_control", "original", "rules", "users.txt"),
  "resources": _p("clawguard", "modules", "access_control", "original", "rules", "resources.txt"),
  "sandbox": _p("sandbox_mcp", "original", "sandbox_config.yaml"),
  "access_local": _p("configs", "access_local.json"),
  "integration_local": _p("configs", "integration_local.json"),
  "remote": _p("configs", "remote.json"),
  "edition": _p("configs", "workspace_edition.json"),
}

try:
  import yaml
except Exception:
  yaml = None

def _read_yaml(path, default):
  try:
    if not os.path.exists(path): return deepcopy(default)
    with open(path, "r", encoding="utf-8") as f:
      data = yaml.safe_load(f) if yaml else json.load(f)
      return data if isinstance(data, dict) else deepcopy(default)
  except Exception: return deepcopy(default)

def _read_json(path, default):
  try:
    if not os.path.exists(path): return deepcopy(default)
    with open(path, "r", encoding="utf-8") as f: return json.load(f)
  except Exception: return deepcopy(default)

def _read_text(path):
  try:
    with open(path, "r", encoding="utf-8") as f: return f.read()
  except Exception: return ""

def _backup(path):
  try:
    if os.path.exists(path):
      with open(path, "r", encoding="utf-8") as f: content = f.read()
      with open(path + ".bak", "w", encoding="utf-8") as f: f.write(content)
  except Exception: pass

def _write_yaml(path, data):
  _backup(path); os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(path, "w", encoding="utf-8") as f:
    if yaml: yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    else: json.dump(data, f, ensure_ascii=False, indent=2)

def _write_json(path, data):
  _backup(path); os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

def _write_text(path, text):
  _backup(path); os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(path, "w", encoding="utf-8") as f: f.write(text or "")

def _get(d, keys, default=None):
  cur = d
  for k in keys:
    if not isinstance(cur, dict) or k not in cur: return default
    cur = cur[k]
  return cur

def _set(d, keys, value):
  cur = d
  for k in keys[:-1]:
    if k not in cur or not isinstance(cur[k], dict): cur[k] = {}
    cur = cur[k]
  cur[keys[-1]] = value
def build_snapshot():
  modules = _read_yaml(PATHS["modules"], {})
  policy = _read_json(PATHS["policy"], {})
  wl = _read_yaml(PATHS["whitelist"], {"trusted": [], "blocked": []})
  inj = _read_yaml(PATHS["b_injection"], {})
  prompt = _read_yaml(PATHS["c_prompt"], {})
  access_local = _read_json(PATHS["access_local"], {})
  if "default_user_level" not in access_local: access_local["default_user_level"] = "secret"
  integration = _read_json(PATHS["integration_local"], {})
  mods = modules.get("modules", {}) if isinstance(modules, dict) else {}
  return {
    "modules": {
      "io_guard_input": {"enabled": _get(mods, ["io_guard_input", "enabled"], True), "on_error": _get(mods, ["io_guard_input", "on_error"], "allow"), "media_extraction": _get(mods, ["io_guard_input", "media_extraction"], True)},
      "io_guard_context": {"enabled": _get(mods, ["io_guard_context", "enabled"], True), "on_error": _get(mods, ["io_guard_context", "on_error"], "allow")},
      "tool_guard": {"enabled": _get(mods, ["tool_guard", "enabled"], True), "on_error": _get(mods, ["tool_guard", "on_error"], "block"), "base_url": _get(mods, ["tool_guard", "base_url"], "https://api.deepseek.com/v1"), "api_key": "", "model": _get(mods, ["tool_guard", "model"], "deepseek-chat"), "timeout_seconds": _get(mods, ["tool_guard", "timeout_seconds"], 30), "block_threshold": _get(mods, ["tool_guard", "block_threshold"], 0.4), "review_threshold": _get(mods, ["tool_guard", "review_threshold"], 0.7), "fetch_guard": {"enabled": _get(mods, ["tool_guard", "fetch_guard", "enabled"], True), "shell_tools": _get(mods, ["tool_guard", "fetch_guard", "shell_tools"], ["execute_bash", "exec", "bash", "shell", "sh", "terminal", "cmd", "powershell"]), "url_tools": _get(mods, ["tool_guard", "fetch_guard", "url_tools"], ["browser"])}},
      "retrieval_guard": {"enabled": _get(mods, ["retrieval_guard", "enabled"], True), "on_error": _get(mods, ["retrieval_guard", "on_error"], "allow"), "model_path": _get(mods, ["retrieval_guard", "model_path"], ""), "guards": _get(mods, ["retrieval_guard", "guards"], {"A": True, "B": True, "C": True})},
      "access_control": {"enabled": _get(mods, ["access_control", "enabled"], True), "on_error": _get(mods, ["access_control", "on_error"], "block")},
      "audit": {"enabled": _get(mods, ["audit", "enabled"], True), "on_error": _get(mods, ["audit", "on_error"], "ignore")},
      "sandbox": {"enabled": _get(modules, ["sandbox", "enabled"], True), "mode": _get(modules, ["sandbox", "mode"], "mcp"), "url": _get(modules, ["sandbox", "url"], "http://127.0.0.1:9876")},
      "human_review": {"unsupported_action": _get(modules, ["human_review", "unsupported_action"], "block")},
    },
    "io_guard_policy": policy,
    "retrieval": {"whitelist": {"trusted": (wl.get("trusted") or []), "blocked": (wl.get("blocked") or [])}, "injection": {"threshold": inj.get("threshold", 0.95), "window_size": inj.get("window_size", 400), "step": inj.get("step", 200)}, "prompt_wrap": {"random_length": prompt.get("random_length", 10), "self_reminder": prompt.get("self_reminder", ""), "post_prompting": prompt.get("post_prompting", "")}},
    "access": access_local if access_local else {"mode": "rbac", "default_user_level": "secret", "block_unknown_users": False, "risk_link_enabled": True, "risk_window_seconds": 300, "risk_threshold": 0.6, "risk_probe_block_count": 3, "risk_escalation_threshold": 0.5, "quarantine_enabled": True, "quarantine_block_count": 8, "quarantine_risk_threshold": 0.85, "quarantine_long_window_seconds": 3600, "quarantine_long_window_count": 15},
    "access_rules": {"resources": _read_text(PATHS["resources"])},
    "integration": integration if integration else {"clawguard_url": "http://127.0.0.1:8000", "api_token_env": "CLAWGUARD_API_TOKEN", "timeout_ms": 30000, "fail_mode": "closed", "enable_media_check": True, "media_root": "", "protected_tools": ["web_fetch", "web_search"]},
    "meta": {"paths": {k: os.path.relpath(v, ROOT) for k, v in PATHS.items()}},
  }

class ConfigUpdate(BaseModel):
  modules: Optional[Dict[str, Any]] = None
  io_guard_policy: Optional[Dict[str, Any]] = None
  retrieval: Optional[Dict[str, Any]] = None
  access: Optional[Dict[str, Any]] = None
  access_rules: Optional[Dict[str, Any]] = None
  integration: Optional[Dict[str, Any]] = None

def _deep_merge(dst, src):
  for k, v in (src or {}).items():
    if isinstance(v, dict) and isinstance(dst.get(k), dict): _deep_merge(dst[k], v)
    else: dst[k] = v
  return dst

@router.get("/config")
def get_local_config(): return {"data": build_snapshot()}

@router.put("/config")
def update_local_config(body: ConfigUpdate):
  applied = []
  modules = _read_yaml(PATHS["modules"], {})
  if "modules" not in modules or not isinstance(modules.get("modules"), dict): modules["modules"] = {}
  if body.modules:
    for mod_name, mod_val in body.modules.items():
      if mod_name in ("sandbox", "human_review"):
        if mod_name not in modules or not isinstance(modules.get(mod_name), dict): modules[mod_name] = {}
        if isinstance(mod_val, dict):
          if mod_name == "tool_guard" and not mod_val.get("api_key"): mod_val = {k: v for k, v in mod_val.items() if k != "api_key"}
          _deep_merge(modules[mod_name], mod_val); applied.append("modules." + mod_name)
      elif mod_name in modules["modules"] or mod_name in ("io_guard_input", "io_guard_context", "tool_guard", "retrieval_guard", "access_control", "audit"):
        if mod_name not in modules["modules"]: modules["modules"][mod_name] = {}
        if isinstance(mod_val, dict):
          if mod_name == "tool_guard" and not mod_val.get("api_key"): mod_val = {k: v for k, v in mod_val.items() if k != "api_key"}
          _deep_merge(modules["modules"][mod_name], mod_val); applied.append("modules." + mod_name)
    _write_yaml(PATHS["modules"], modules)
    try:
      from clawguard.modules.tool_guard.llm_config import ToolGuardLLMConfig
      tg = (body.modules or {}).get("tool_guard") or {}
      patch = {k: v for k, v in tg.items() if k in ("base_url", "model", "timeout_seconds", "block_threshold", "review_threshold") and v not in (None, "")}
      if tg.get("api_key"): patch["api_key"] = tg["api_key"]
      if patch: ToolGuardLLMConfig.instance().update(patch)
    except Exception: pass
  if body.io_guard_policy is not None:
    policy = _read_json(PATHS["policy"], {})
    _deep_merge(policy, body.io_guard_policy); _write_json(PATHS["policy"], policy); applied.append("io_guard_policy")
  if body.retrieval is not None:
    ret = body.retrieval
    if "whitelist" in ret and isinstance(ret["whitelist"], dict):
      wl = _read_yaml(PATHS["whitelist"], {"trusted": [], "blocked": []})
      if "trusted" in ret["whitelist"]: wl["trusted"] = ret["whitelist"]["trusted"] or []
      if "blocked" in ret["whitelist"]: wl["blocked"] = ret["whitelist"]["blocked"] or []
      _write_yaml(PATHS["whitelist"], wl); applied.append("retrieval.whitelist")
    if "injection" in ret and isinstance(ret["injection"], dict):
      inj = _read_yaml(PATHS["b_injection"], {}); _deep_merge(inj, ret["injection"]); _write_yaml(PATHS["b_injection"], inj); applied.append("retrieval.injection")
    if "prompt_wrap" in ret and isinstance(ret["prompt_wrap"], dict):
      pr = _read_yaml(PATHS["c_prompt"], {}); _deep_merge(pr, ret["prompt_wrap"]); _write_yaml(PATHS["c_prompt"], pr); applied.append("retrieval.prompt_wrap")
  if body.access is not None:
    cur = _read_json(PATHS["access_local"], {})
    _deep_merge(cur, body.access); _write_json(PATHS["access_local"], cur); applied.append("access")
    try:
      from clawguard.modules.access_control.original import auth_gateway as _ag
      _ag.DEFAULT_USER_LEVEL = _ag._resolve_default_user_level()
    except Exception:
      pass
  if body.access_rules is not None:
    pass  # users.txt 已下线：用户规则只保留在服务端，忽略下发的 users 键
    if "resources" in body.access_rules and isinstance(body.access_rules["resources"], str): _write_text(PATHS["resources"], body.access_rules["resources"]); applied.append("access_rules.resources")
  if body.integration is not None:
    cur = _read_json(PATHS["integration_local"], {})
    _deep_merge(cur, body.integration); _write_json(PATHS["integration_local"], cur); applied.append("integration")
  return {"data": {"applied": applied, "snapshot": build_snapshot()}}

class EditionBody(BaseModel):
  edition: Optional[str] = "personal"

@router.get("/edition")
def get_edition():
  d = _read_json(PATHS["edition"], {})
  ed = d.get("edition", "personal")
  if ed not in ("personal", "pro"): ed = "personal"
  return {"data": {"edition": ed}}

@router.put("/edition")
def put_edition(body: EditionBody):
  ed = (body.edition or "personal").strip().lower()
  if ed not in ("personal", "pro"): ed = "personal"
  _write_json(PATHS["edition"], {"edition": ed})
  return {"data": {"edition": ed}}

@router.get("/enterprise/status")
def enterprise_status():
  remote = _read_json(PATHS["remote"], {})
  inner = remote.get("remote") if isinstance(remote.get("remote"), dict) else {}
  bound = bool(remote.get("token") or inner.get("token"))
  tok = remote.get("token") or inner.get("token", "") or ""
  try:
    import glob as _glob
    _afs = _glob.glob(os.path.join(ROOT, "clawguard", "audit", "*.jsonl")) + _glob.glob(os.path.join(ROOT, "runtime", "audit", "*.jsonl")) + _glob.glob(os.path.join(ROOT, "logs", "audit*.jsonl"))
    _cnt = 0
    for _fp in _afs[:6]:
      try:
        with open(_fp, "r", encoding="utf-8", errors="ignore") as _f:
          for _ln in _f:
            if _ln.strip(): _cnt += 1
      except Exception: pass
  except Exception: _cnt = 0
  try:
    _cp = os.path.join(ROOT, "runtime", "remote", "cursors.json")
    _cursors = {}
    if os.path.exists(_cp):
      with open(_cp, "r", encoding="utf-8") as _f: _cursors = json.load(_f) or {}
  except Exception: _cursors = {}
  return {"data": {"bound": bound, "enterprise_name": remote.get("enterprise_name") or inner.get("enterprise_name", "") or "", "terminal_name": remote.get("terminal_name") or inner.get("terminal_name", "") or remote.get("hostname", ""), "level": remote.get("level", "member"), "token_masked": ((tok[:4] + "****" + tok[-4:]) if len(tok) >= 8 else ""), "base_url": remote.get("base_url") or inner.get("base_url", ""), "audit_events_local": _cnt, "cursors": _cursors}}
