"""终端 -> LLMGate 常驻同步器：心跳保活 + 用量上报 + 审计事件增量上传。

契约见 LLMGate/REMOTE.md 4.2/4.5/4.7，上报周期默认 60 秒（环境变量 ARGUS_SYNC_INTERVAL）。
只用标准库；任何失败只记日志不抛异常，下轮重试。
游标 runtime/remote/cursors.json 与状态页共用，只增键、不改旧键。
"""
from __future__ import annotations
import asyncio
import datetime as _dt
import json
import logging
import os
import re
import socket
import urllib.request
import urllib.error

log = logging.getLogger("argus.remote_sync")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REMOTE_PATH = os.path.join(ROOT, "configs", "remote.json")
CURSORS_PATH = os.path.join(ROOT, "runtime", "remote", "cursors.json")
AUDIT_PATH = os.path.join(ROOT, "runtime", "audit", "audit-events.jsonl")
USAGE_PATH = os.path.join(ROOT, "runtime", "usage", "usage.jsonl")
USERS_PATH = os.path.join(ROOT, "argus", "modules", "access_control", "original", "rules", "users.txt")
RESOURCES_PATH = os.path.join(ROOT, "argus", "modules", "access_control", "original", "rules", "resources.txt")
MODULES_PATH = os.path.join(ROOT, "configs", "modules.yaml")
POLICY_PATH = os.path.join(ROOT, "argus", "modules", "io_guard", "original", "configs", "default_policy.json")
ACCESS_LOCAL_PATH = os.path.join(ROOT, "configs", "access_local.json")
INTEGRATION_LOCAL_PATH = os.path.join(ROOT, "configs", "integration_local.json")
WHITELIST_PATH = os.path.join(ROOT, "argus", "modules", "retrieval_guard", "original", "a_url", "whitelist.yaml")
B_INJECTION_PATH = os.path.join(ROOT, "argus", "modules", "retrieval_guard", "original", "b_injection", "config.yaml")
C_PROMPT_PATH = os.path.join(ROOT, "argus", "modules", "retrieval_guard", "original", "c_prompt", "config.yaml")
LIVE_REPORT_MAX = 120 * 1024

VALID_ACTIONS = ("allow", "block", "rewrite", "human_review")
ALERT_ACTIONS = ("block", "human_review")
MAX_BATCH = 500
MAX_FIX_ATTEMPTS = 5
TIMEOUT = 20


def _interval():
    try:
        return max(15, int(os.environ.get("ARGUS_SYNC_INTERVAL", "60") or 60))
    except ValueError:
        return 60


def _read_json(path, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else default
    except Exception:
        return default


def _merge_cursors(patch):
    try:
        cur = _read_json(CURSORS_PATH, {})
        if not isinstance(cur, dict):
            cur = {}
        cur.update(patch)
        os.makedirs(os.path.dirname(CURSORS_PATH), exist_ok=True)
        with open(CURSORS_PATH, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning("write cursors failed: %s", e)


def _now_iso():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_binding():
    """返回 (base_url, token)，未绑定返回 (None, None)。"""
    try:
        remote = _read_json(REMOTE_PATH, {})
        inner = remote.get("remote") if isinstance(remote.get("remote"), dict) else {}
        base = (remote.get("base_url") or inner.get("base_url") or "").strip().rstrip("/")
        tok = (remote.get("token") or inner.get("token") or "").strip()
        if not tok:
            return None, None
        return base or "http://127.0.0.1:8080", tok
    except Exception:
        return None, None


def _post(base, token, path, payload):
    """同步 POST，返回 (ok, status, data)。网络错返回 (False, 0, {}); 4xx/5xx 返回 (False, code, body)。"""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path, data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
            return True, resp.status, data
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8") or "{}"
            data = json.loads(raw)
        except Exception:
            data = {}
        return False, e.code, data
    except Exception as e:
        log.warning("POST %s failed: %s", path, e)
        return False, 0, {}


def _get(base, token, path):
    req = urllib.request.Request(
        base + path,
        headers={"Authorization": "Bearer " + token},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
            return True, resp.status, data
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8") or "{}"
            data = json.loads(raw)
        except Exception:
            data = {}
        return False, e.code, data
    except Exception as e:
        log.warning("GET %s failed: %s", path, e)
        return False, 0, {}


def _read_text_cap(path, limit=LIVE_REPORT_MAX):
    try:
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            t = f.read()
        if len(t.encode("utf-8")) > limit:
            t = t.encode("utf-8")[:limit].decode("utf-8", errors="ignore")
        return t
    except Exception:
        return ""


def _backup_write_text(path, text):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                old = f.read()
            try:
                with open(path + ".bak", "w", encoding="utf-8") as f:
                    f.write(old)
            except Exception:
                pass
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if text and not text.endswith("\n"):
            text += "\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(text or "")
        return True
    except Exception as e:
        log.warning("write %s failed: %s", path, e)
        return False


_USER_LEVEL_ALIASES = {
    "1": "public", "2": "internal", "3": "secret", "4": "top_secret",
    "a": "public", "b": "internal", "c": "secret", "d": "top_secret",
    "public": "public", "internal": "internal", "secret": "secret",
    "top_secret": "top_secret", "topsecret": "top_secret",
}
_USER_LEVELS = ("public", "internal", "secret", "top_secret")

_UNSET = object()


def _normalize_user_level(raw):
    if raw is None:
        return ""
    s = str(raw).strip().lower()
    v = _USER_LEVEL_ALIASES.get(s, "")
    return v if v in _USER_LEVELS else ""


def _apply_access_user(username, level="", specials=_UNSET):
    """users.txt 已下线：只写 access_local.json 的 bound_user（单用户绑定），不碰本地规则文件。"""
    name = (username or "").strip() if isinstance(username, str) else ""
    if not name:
        return False
    lv = _normalize_user_level(level)
    if specials is _UNSET or specials is None:
        sp = None
    elif isinstance(specials, (list, tuple)):
        sp = [str(s).strip() for s in specials if str(s).strip()]
    else:
        s0 = str(specials).strip()
        sp = [x for x in (v.strip() for v in s0.split(",")) if x] if s0 else []
    if not lv and sp is None:
        return False
    cur = _read_json_file(ACCESS_LOCAL_PATH, {})
    b = cur.get("bound_user") if isinstance(cur.get("bound_user"), dict) else {}
    keep_sp = list(b.get("specials") or []) if sp is None else sp
    keep_lv = lv or _normalize_user_level(b.get("level") or "") or ""
    if not keep_lv:
        return False
    if b.get("username") == name and b.get("level") == keep_lv and list(b.get("specials") or []) == keep_sp:
        return False
    cur["bound_user"] = {"username": name, "level": keep_lv, "specials": keep_sp}
    cur["default_user_level"] = keep_lv
    if not _write_json_file(ACCESS_LOCAL_PATH, cur):
        return False
    try:
        from argus.modules.access_control.original import auth_gateway as _ag
        _ag.set_bound_user(name, keep_lv, keep_sp)
        _ag.DEFAULT_USER_LEVEL = _ag._resolve_default_user_level()
    except Exception as e:
        log.warning("bound user hot-reload failed: %s", e)
    return True


try:
    import yaml as _yaml
except Exception:
    _yaml = None

_KNOWN_TOP_MODULES = ("io_guard_input", "io_guard_context", "io_guard_output", "access_control", "tool_guard", "retrieval_guard", "audit")
_KNOWN_FLAT_MODULES = ("sandbox", "human_review")
_KNOWN_CONFIG_TOP_KEYS = ("schema_version", "modules", "io_guard_policy", "retrieval", "access", "access_user", "access_rules", "integration")

# generic nested merge: src wins, lists and scalars replaced, unknown local keys kept
def _deep_merge(dst, src):
    if not isinstance(dst, dict) or not isinstance(src, dict):
        return dst
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst

def _read_yaml_file(path, default):
    try:
        if not os.path.exists(path):
            return dict(default) if isinstance(default, dict) else default
        with open(path, "r", encoding="utf-8") as f:
            data = _yaml.safe_load(f) if _yaml is not None else json.load(f)
        return data if isinstance(data, dict) else (dict(default) if isinstance(default, dict) else default)
    except Exception as e:
        log.warning("read yaml %s failed: %s", path, e)
        return dict(default) if isinstance(default, dict) else default

def _write_yaml_file(path, data):
    try:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    old = f.read()
                with open(path + ".bak", "w", encoding="utf-8") as f:
                    f.write(old)
            except Exception:
                pass
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            if _yaml is not None:
                _yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
            else:
                json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log.warning("write yaml %s failed: %s", path, e)
        return False

def _read_json_file(path, default):
    try:
        if not os.path.exists(path):
            return dict(default) if isinstance(default, dict) else default
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else (dict(default) if isinstance(default, dict) else default)
    except Exception as e:
        log.warning("read json %s failed: %s", path, e)
        return dict(default) if isinstance(default, dict) else default

def _write_json_file(path, data):
    try:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    old = f.read()
                with open(path + ".bak", "w", encoding="utf-8") as f:
                    f.write(old)
            except Exception:
                pass
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log.warning("write json %s failed: %s", path, e)
        return False

# modules.* -> configs/modules.yaml (nested merge, unknown local keys kept).
# empty tool_guard api_key never wipes the local secret.
def _apply_modules(patch):
    wrote = []
    if not isinstance(patch, dict):
        return wrote
    doc = _read_yaml_file(MODULES_PATH, {})
    if "modules" not in doc or not isinstance(doc.get("modules"), dict):
        doc["modules"] = {}
    for mod_name, mod_val in patch.items():
        if not isinstance(mod_val, dict):
            continue
        if mod_name in _KNOWN_FLAT_MODULES:
            if not isinstance(doc.get(mod_name), dict):
                doc[mod_name] = {}
            _deep_merge(doc[mod_name], dict(mod_val))
            wrote.append("modules." + mod_name)
        elif mod_name in _KNOWN_TOP_MODULES or mod_name in doc["modules"]:
            if not isinstance(doc["modules"].get(mod_name), dict):
                doc["modules"][mod_name] = {}
            val = dict(mod_val)
            if mod_name == "tool_guard" and not val.get("api_key"):
                val.pop("api_key", None)
            _deep_merge(doc["modules"][mod_name], val)
            wrote.append("modules." + mod_name)
        else:
            log.warning("config: unknown modules key '%s' ignored", mod_name)
    if wrote:
        _write_yaml_file(MODULES_PATH, doc)
    try:
        from argus.modules.tool_guard.llm_config import ToolGuardLLMConfig
        tg = patch.get("tool_guard") or {}
        if isinstance(tg, dict):
            upd = {k: v for k, v in tg.items() if k in ("base_url", "model", "timeout_seconds", "block_threshold", "review_threshold") and v not in (None, "")}
            if tg.get("api_key"):
                upd["api_key"] = tg["api_key"]
            if upd:
                ToolGuardLLMConfig.instance().update(upd)
    except Exception as e:
        log.warning("tool_guard llm hot-reload failed: %s", e)
    return wrote

# io_guard_policy.* -> default_policy.json (nested merge)
def _apply_io_guard_policy(patch):
    if not isinstance(patch, dict):
        return []
    cur = _read_json_file(POLICY_PATH, {})
    _deep_merge(cur, patch)
    if _write_json_file(POLICY_PATH, cur):
        return ["io_guard_policy"]
    return []

# retrieval.* -> three yaml files (same split as personal edition)
def _apply_retrieval(patch):
    wrote = []
    if not isinstance(patch, dict):
        return wrote
    if isinstance(patch.get("whitelist"), dict):
        wl = _read_yaml_file(WHITELIST_PATH, {"trusted": [], "blocked": []})
        if "trusted" in patch["whitelist"]:
            wl["trusted"] = patch["whitelist"]["trusted"] or []
        if "blocked" in patch["whitelist"]:
            wl["blocked"] = patch["whitelist"]["blocked"] or []
        if _write_yaml_file(WHITELIST_PATH, wl):
            wrote.append("retrieval.whitelist")
    if isinstance(patch.get("injection"), dict):
        inj = _read_yaml_file(B_INJECTION_PATH, {})
        _deep_merge(inj, patch["injection"])
        if _write_yaml_file(B_INJECTION_PATH, inj):
            wrote.append("retrieval.injection")
    if isinstance(patch.get("prompt_wrap"), dict):
        pr = _read_yaml_file(C_PROMPT_PATH, {})
        _deep_merge(pr, patch["prompt_wrap"])
        if _write_yaml_file(C_PROMPT_PATH, pr):
            wrote.append("retrieval.prompt_wrap")
    if isinstance(patch.get("injection"), dict):
        log.warning("retrieval.injection changed: restart 8000 to reload PIGuard thresholds")
    return wrote

# access.* -> configs/access_local.json (flat merge) + refresh default level
def _apply_access(patch):
    if not isinstance(patch, dict):
        return []
    cur = _read_json_file(ACCESS_LOCAL_PATH, {})
    _deep_merge(cur, patch)
    if _write_json_file(ACCESS_LOCAL_PATH, cur):
        try:
            from argus.modules.access_control.original import auth_gateway as _ag
            _ag.DEFAULT_USER_LEVEL = _ag._resolve_default_user_level()
        except Exception as e:
            log.warning("access default-level refresh failed: %s", e)
        return ["access"]
    return []

# integration.* -> configs/integration_local.json (terminal-local archive, same as personal edition).
# cross-machine OpenClaw plugin side needs a separate channel, no hot reload here.
def _apply_integration(patch):
    if not isinstance(patch, dict):
        return []
    cur = _read_json_file(INTEGRATION_LOCAL_PATH, {})
    _deep_merge(cur, patch)
    if _write_json_file(INTEGRATION_LOCAL_PATH, cur):
        return ["integration"]
    return []


def do_config(base, token, cursors):
    try:
        ok, code, data = _get(base, token, "/telemetry/v1/config")
        if not ok:
            if code:
                log.warning("config fetch HTTP %s", code)
            return False
        inner = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else {}
        try:
            ver = int(inner.get("config_version") or 0)
        except Exception:
            ver = 0
        try:
            applied = int(cursors.get("config_applied_version") or 0)
        except Exception:
            applied = 0
        pending = bool(inner.get("config_pending"))
        if ver <= 0 or (not pending and ver <= applied):
            return True
        if ver <= applied:
            return True
        cfg_text = inner.get("config") or ""
        if not isinstance(cfg_text, str) or not cfg_text.strip():
            _merge_cursors({"config_applied_version": ver, "last_config_applied_at": _now_iso()})
            _post(base, token, "/telemetry/v1/config/applied", {"config_version": ver})
            return True
        try:
            obj = json.loads(cfg_text)
        except Exception as e:
            log.warning("config parse failed: %s", e)
            return False
        if not isinstance(obj, dict):
            return False
        wrote = []
        warnings = []
        if isinstance(obj.get("modules"), dict):
            wrote += _apply_modules(obj["modules"])
        if isinstance(obj.get("io_guard_policy"), dict):
            wrote += _apply_io_guard_policy(obj["io_guard_policy"])
        if isinstance(obj.get("retrieval"), dict):
            wrote += _apply_retrieval(obj["retrieval"])
        if isinstance(obj.get("access"), dict):
            wrote += _apply_access(obj["access"])
        ar = obj.get("access_rules")
        if isinstance(ar, dict):
            u = ar.get("users")
            if isinstance(u, str) and u.strip():
                warnings.append("access_rules.users 已下线：用户规则只保留在服务端，终端不再写入 users.txt")
            r = ar.get("resources")
            if isinstance(r, str) and r.strip():
                if _backup_write_text(RESOURCES_PATH, r):
                    wrote.append("access_rules.resources")
        au = obj.get("access_user")
        if isinstance(au, dict):
            aname = au.get("username", "")
            if isinstance(aname, str) and aname.strip():
                if _apply_access_user(aname, au.get("level", ""), au.get("specials", _UNSET)):
                    wrote.append("access_user.level")
        if isinstance(obj.get("integration"), dict):
            wrote += _apply_integration(obj["integration"])
        for k in obj.keys():
            if k not in _KNOWN_CONFIG_TOP_KEYS:
                warnings.append("unknown top-level key ignored: " + str(k))
        if warnings:
            for w in warnings:
                log.warning("config: %s", w)
        _merge_cursors({"config_applied_version": ver, "last_config_applied_at": _now_iso(), "last_config_wrote": wrote, "last_config_warnings": warnings})
        _post(base, token, "/telemetry/v1/config/applied", {"config_version": ver})
        try:
            import threading as _th
            def _reload():
                try:
                    from argus.core import registry as _regmod
                    reg = getattr(_regmod, "registry", None)
                    if reg is not None and _yaml is not None:
                        try:
                            with open(str(getattr(reg, "config_path")), "r", encoding="utf-8") as f:
                                reg.config = _yaml.safe_load(f) or {}
                        except Exception as e:
                            log.warning("registry modules reload failed: %s", e)
                        try:
                            _mdoc = _read_yaml_file(MODULES_PATH, {})
                            _rg = ((_mdoc.get("modules") or {}).get("retrieval_guard")) or {}
                            _gs = _rg.get("guards") or {}
                            _rt0 = reg.get("retrieval_guard")
                            if _rt0 is not None and isinstance(_gs, dict):
                                if "A" in _gs:
                                    _rt0._guard_a = bool(_gs["A"])
                                if "B" in _gs:
                                    _rt0._guard_b = bool(_gs["B"])
                                if "C" in _gs:
                                    _rt0._guard_c = bool(_gs["C"])
                        except Exception as e:
                            log.warning("retrieval guards hot-sync failed: %s", e)
                except Exception as e:
                    log.warning("registry reload failed: %s", e)
                try:
                    from argus.modules.tool_guard.llm_config import ToolGuardLLMConfig
                    _mdoc2 = _read_yaml_file(MODULES_PATH, {})
                    _mtg2 = ((_mdoc2.get("modules") or {}).get("tool_guard")) or {}
                    _p2 = {k: v for k, v in _mtg2.items() if k in ("base_url", "model", "timeout_seconds", "block_threshold", "review_threshold") and v not in (None, "")}
                    if _p2:
                        ToolGuardLLMConfig.instance().update(_p2)
                except Exception as e:
                    log.warning("tool_guard config re-sync failed: %s", e)
                if bool(isinstance(obj.get("io_guard_policy"), dict)) or bool(isinstance(obj.get("retrieval"), dict)):
                    try:
                        from argus.core import registry as _regmod2
                        reg2 = getattr(_regmod2, "registry", None)
                        if reg2 is not None:
                            try:
                                _io = reg2.get("io_guard_input")
                                if _io is not None and hasattr(_io, "_delegate"):
                                    _io._delegate = None
                                    _io._service = None
                            except Exception:
                                pass
                            try:
                                _rt = reg2.get("retrieval_guard")
                                if _rt is not None:
                                    try:
                                        from argus.modules.retrieval_guard.original.a_url import URLWhitelist as _UWL
                                        _rt._url_guard = _UWL()
                                    except Exception:
                                        pass
                                    try:
                                        from argus.modules.retrieval_guard.original.c_prompt import PromptWrapper as _PW
                                        _rt._wrapper = _PW()
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                    except Exception as e:
                        log.warning("adapter hot-reload failed: %s", e)
                try:
                    from argus.api import main as _main
                    store = getattr(_main, "ACCESS_STORE", None) or getattr(_main, "access_store", None)
                    if store is not None and hasattr(store, "reload"):
                        store.reload()
                except Exception as e:
                    log.warning("access reload failed: %s", e)
            _th.Thread(target=_reload, daemon=True).start()
        except Exception:
            pass
        log.info("config applied v%s wrote=%s warnings=%s", ver, wrote, warnings)
        return True
    except Exception as e:
        log.warning("config sync failed: %s", e)
        return False

def _valid_ts(raw):
    """时间戳能被服务端接受才返回原串，否则 None。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()
    try:
        t = s
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        _dt.datetime.fromisoformat(t)
        return s
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            _dt.datetime.strptime(s, fmt)
            return s
        except Exception:
            continue
    return None


def _as_obj(v):
    return v if isinstance(v, dict) else {}


def _norm_event(e):
    """本地审计行 -> 上报体；非法返回 None。"""
    if not isinstance(e, dict):
        return None
    eid = str(e.get("event_id") or "").strip()
    if not eid or len(eid) > 128:
        return None
    action = str(e.get("action") or "").strip()
    if action not in VALID_ACTIONS:
        # OpenClaw conversation events (received/sent) are not security verdicts, but enterprise requires full sync:
        # map to allow and keep the original action in metadata; unknown actions are still dropped.
        if action in ("received", "sent"):
            try:
                _m = e.get("metadata")
                if isinstance(_m, dict):
                    _m["_original_action"] = action
                    _m["_mapped_for_sync"] = True
            except Exception:
                pass
            action = "allow"
        else:
            return None
    ts = _valid_ts(e.get("timestamp"))
    if ts is None:
        return None
    try:
        risk = float(e.get("risk_score", 0) or 0)
    except (TypeError, ValueError):
        return None
    if risk < 0 or risk > 1:
        return None
    reason = str(e.get("reason") or "").strip()
    if len(reason.encode("utf-8")) > 4096:
        return None
    content = _as_obj(e.get("content"))
    metadata = _as_obj(e.get("metadata"))
    try:
        if len(json.dumps(content).encode("utf-8")) > 64 * 1024:
            content = {}
        if len(json.dumps(metadata).encode("utf-8")) > 64 * 1024:
            metadata = {}
    except Exception:
        content, metadata = {}, {}
    return {
        "event_id": eid,
        "trace_id": str(e.get("trace_id") or "").strip()[:128],
        "session_id": str(e.get("session_id") or "").strip()[:128],
        "user_id": str(e.get("user_id") or "").strip()[:64],
        "timestamp": ts,
        "stage": str(e.get("stage") or "").strip()[:32],
        "source_module": str(e.get("source_module") or "").strip()[:64],
        "action": action,
        "risk_score": risk,
        "reason": reason,
        "content": content,
        "metadata": metadata,
    }


def _read_new_lines(path, consumed):
    """返回 (全部新行原文列表, 当前总行数)。文件只追加，用行数做游标。"""
    try:
        if not os.path.exists(path):
            return [], consumed
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [ln for ln in f if ln.strip()]
        total = len(lines)
        if consumed < 0:
            consumed = 0
        if consumed > total:
            consumed = 0  # 文件被轮转过，从头开始（服务端幂等去重兜底）
        return lines[consumed:], total
    except Exception as e:
        log.warning("read %s failed: %s", path, e)
        return [], consumed


def do_heartbeat(base, token):
    try:
        hostname = socket.gethostname() or ""
    except Exception:
        hostname = ""
    try:
        import platform as _pf
        os_info = _pf.platform() or ""
    except Exception:
        os_info = ""
    ok, code, data = _post(base, token, "/telemetry/v1/heartbeat", {
        "hostname": hostname, "os_info": os_info,
        "agent_version": "", "argus_version": "2.1",
    })
    if ok:
        _merge_cursors({"last_heartbeat_at": _now_iso()})
        return True
    if code:
        log.warning("heartbeat HTTP %s: %s", code, json.dumps(data)[:300])
    return False


_LIVE_SECTION_CAP = 64 * 1024

def _live_capped_dict(d):
    try:
        if not isinstance(d, dict) or not d:
            return {}
        raw = json.dumps(d, ensure_ascii=False)
        if len(raw.encode("utf-8")) > _LIVE_SECTION_CAP:
            log.warning("live_config section too large, skipped")
            return {}
        return d
    except Exception:
        return {}

def _build_live_config():
    out = {}
    try:
        mod = _read_yaml_file(MODULES_PATH, {})
        if isinstance(mod, dict) and mod:
            m = {}
            inner = mod.get("modules")
            if isinstance(inner, dict):
                inner2 = dict(inner)
                tg = inner2.get("tool_guard")
                if isinstance(tg, dict) and "api_key" in tg:
                    tg2 = dict(tg)
                    tg2.pop("api_key", None)
                    inner2["tool_guard"] = tg2
                m.update(inner2)
            for k in ("sandbox", "human_review"):
                if isinstance(mod.get(k), dict):
                    m[k] = mod[k]
            m = _live_capped_dict(m)
            if m:
                out["modules"] = m
        pol = _read_json_file(POLICY_PATH, {})
        pol = _live_capped_dict(pol)
        if pol:
            out["io_guard_policy"] = pol
        acc = _read_json_file(ACCESS_LOCAL_PATH, {})
        acc = _live_capped_dict(acc)
        if acc:
            out["access"] = acc
        ret = {}
        try:
            wl = _read_yaml_file(WHITELIST_PATH, {})
            if isinstance(wl, dict) and (wl.get("trusted") or wl.get("blocked")):
                ret["whitelist"] = {"trusted": wl.get("trusted") or [], "blocked": wl.get("blocked") or []}
        except Exception:
            pass
        try:
            inj = _read_yaml_file(B_INJECTION_PATH, {})
            if isinstance(inj, dict) and inj:
                ret["injection"] = inj
        except Exception:
            pass
        try:
            pr = _read_yaml_file(C_PROMPT_PATH, {})
            if isinstance(pr, dict) and pr:
                ret["prompt_wrap"] = pr
        except Exception:
            pass
        ret = _live_capped_dict(ret)
        if ret:
            out["retrieval"] = ret
        integ = _read_json_file(INTEGRATION_LOCAL_PATH, {})
        integ = _live_capped_dict(integ)
        if integ:
            out["integration"] = integ
    except Exception as e:
        log.warning("build live_config failed: %s", e)
        return {}
    return out

def do_report(base, token, cursors):
    usage_new, usage_total = _read_new_lines(USAGE_PATH, int(cursors.get("usage_lines_consumed", 0) or 0))
    audit_new, _ = _read_new_lines(AUDIT_PATH, int(cursors.get("audit_lines_consumed", 0) or 0))
    tok_delta = 0
    for ln in usage_new:
        try:
            u = json.loads(ln)
            tok_delta += int(float(u.get("total", 0) or 0))
        except Exception:
            continue
    alerts = 0
    samples = []
    for ln in audit_new:
        try:
            e = json.loads(ln)
        except Exception:
            continue
        if str(e.get("action") or "") in ALERT_ACTIONS:
            alerts += 1
            if len(samples) < 20:
                ts = e.get("timestamp")
                samples.append({
                    "at": ts if isinstance(ts, str) else _now_iso(),
                    "stage": str(e.get("stage") or ""),
                    "module": str(e.get("source_module") or ""),
                    "action": str(e.get("action") or ""),
                    "risk_score": float(e.get("risk_score", 0) or 0),
                    "reason": str(e.get("reason") or "")[:200],
                    "trace_id": str(e.get("trace_id") or ""),
                })
    if tok_delta < 0:
        tok_delta = 0
    live = {}
    try:
        live = {"users": "", "resources": _read_text_cap(RESOURCES_PATH)}
    except Exception:
        live = {}
    live_cfg = _build_live_config()
    ok, code, data = _post(base, token, "/telemetry/v1/report", {
        "window_started_at": cursors.get("last_report_at") or _now_iso(),
        "token_usage_delta": tok_delta,
        "security_alerts_delta": alerts,
        "alert_samples": samples,
        "access_rules": live,
        "live_config": live_cfg,
    })
    if ok:
        inner = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else {}
        patch = {"last_report_at": _now_iso(), "usage_lines_consumed": usage_total}
        if inner.get("token_usage_total") is not None:
            patch["token_usage_total"] = inner.get("token_usage_total")
        _merge_cursors(patch)
        return True
    if code:
        log.warning("report HTTP %s: %s", code, json.dumps(data)[:300])
    return False


def _upload_batch(base, token, batch):
    """发一批；400 时按 events[i] 定位剔除坏条目后重试（有界）。返回 (accepted, fixed)。"""
    attempt = 0
    fixed = 0
    while attempt <= MAX_FIX_ATTEMPTS:
        ok, code, data = _post(base, token, "/telemetry/v1/audit/events", {"events": batch})
        if ok:
            inner = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else {}
            return int(inner.get("accepted", 0) or 0), fixed
        if code == 400:
            msg = ""
            try:
                msg = ((data.get("error") or {}).get("message")) or ""
            except Exception:
                msg = ""
            m = re.search(r"events\[(\d+)\]", msg or "")
            if m:
                idx = int(m.group(1))
                if 0 <= idx < len(batch):
                    bad = batch.pop(idx)
                    fixed += 1
                    attempt += 1
                    log.warning("audit batch: drop invalid events[%d] (%s), retry %d/%d",
                                idx, (msg or "")[:160], attempt, MAX_FIX_ATTEMPTS)
                    if not batch:
                        return 0, fixed
                    continue
            log.warning("audit batch 400 unfixable: %s", (msg or "")[:300])
            return -1, fixed
        if code:
            log.warning("audit batch HTTP %s: %s", code, json.dumps(data)[:300])
            return -1, fixed
        return -1, fixed  # 网络错：下轮重试
    log.warning("audit batch: still failing after %d fixes, defer to next round", MAX_FIX_ATTEMPTS)
    return -1, fixed


def do_audit(base, token, cursors):
    consumed = int(cursors.get("audit_lines_consumed", 0) or 0)
    new_lines, total = _read_new_lines(AUDIT_PATH, consumed)
    if not new_lines:
        return True
    sendable = []
    skipped = 0
    for ln in new_lines:
        try:
            row = _norm_event(json.loads(ln))
        except Exception:
            row = None
        if row is None:
            skipped += 1
        else:
            sendable.append(row)
    accepted_total = 0
    pos = 0
    failed = False
    while pos < len(sendable):
        batch = sendable[pos:pos + MAX_BATCH]
        acc, _ = _upload_batch(base, token, batch)
        if acc < 0:
            failed = True
            break
        accepted_total += acc
        pos += len(batch)
    if failed:
        log.warning("audit upload deferred: %d lines stay for next round", len(new_lines))
        return False
    prev_skip = int(cursors.get("audit_skipped_total", 0) or 0)
    _merge_cursors({
        "audit_lines_consumed": total,
        "last_audit_upload_at": _now_iso(),
        "last_audit_accepted": accepted_total,
        "last_audit_skipped": skipped,
        "audit_skipped_total": prev_skip + skipped,
    })
    log.info("audit upload ok: accepted=%d skipped_invalid=%d cursor=%d", accepted_total, skipped, total)
    return True


def run_once():
    base, token = _load_binding()
    if not token:
        return False
    cursors = _read_json(CURSORS_PATH, {})
    if not isinstance(cursors, dict):
        cursors = {}
    hb = do_heartbeat(base, token)
    rep = do_report(base, token, cursors)
    aud = do_audit(base, token, _read_json(CURSORS_PATH, {}))
    try:
        do_config(base, token, _read_json(CURSORS_PATH, {}))
    except Exception as e:
        log.warning("config round failed: %s", e)
    return bool(hb and rep and aud)


async def _loop():
    interval = _interval()
    log.info("remote sync loop started (interval=%ss)", interval)
    while True:
        try:
            await asyncio.to_thread(run_once)
        except Exception as e:
            log.warning("sync round failed: %s", e)
        await asyncio.sleep(_interval())


_task = None


def start_remote_sync(app=None):
    global _task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("no running loop; remote sync not started")
        return None
    if _task is None or _task.done():
        _task = loop.create_task(_loop())
    return _task


async def stop_remote_sync():
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        _task = None
