"""Enterprise sync status (local file-backed)."""
from __future__ import annotations
import glob as _glob
import json
import os
from typing import Any, Dict, Optional
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1/remote", tags=["remote-sync"])

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REMOTE_PATH = os.path.join(ROOT, "configs", "remote.json")
CURSORS_PATH = os.path.join(ROOT, "runtime", "remote", "cursors.json")

def _read_json(path, default):
    try:
        if not os.path.exists(path): return default
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else default
    except Exception: return default

def _write_json(path, data):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f: old = f.read()
            with open(path + ".bak", "w", encoding="utf-8") as f: f.write(old)
    except Exception: pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _audit_count():
    try:
        files = (_glob.glob(os.path.join(ROOT, "argus", "audit", "*.jsonl"))
                 + _glob.glob(os.path.join(ROOT, "runtime", "audit", "*.jsonl"))
                 + _glob.glob(os.path.join(ROOT, "logs", "audit*.jsonl")))
        cnt = 0
        for fp in files[:6]:
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    for ln in f:
                        if ln.strip(): cnt += 1
            except Exception: pass
        return cnt
    except Exception: return 0

def _status_payload():
    remote = _read_json(REMOTE_PATH, {})
    inner = remote.get("remote") if isinstance(remote.get("remote"), dict) else {}
    tok = remote.get("token") or inner.get("token", "") or ""
    bound = bool(tok)
    cursors = _read_json(CURSORS_PATH, {})
    totals = {}
    if isinstance(cursors, dict):
        if cursors.get("token_usage_total") is not None: totals["token_usage_total"] = cursors.get("token_usage_total")
        if cursors.get("config_applied_version") is not None: totals["config_applied_version"] = cursors.get("config_applied_version")
    return {"bound": bound,
        "enterprise_name": remote.get("enterprise_name") or inner.get("enterprise_name", "") or "",
        "terminal_name": remote.get("terminal_name") or inner.get("terminal_name", "") or remote.get("hostname", "") or "",
        "level": remote.get("level", "member") or "member",
        "base_url": remote.get("base_url") or inner.get("base_url", "") or "",
        "token_masked": ((tok[:4] + "****" + tok[-4:]) if len(tok) >= 8 else ""),
        "audit_events_local": _audit_count(),
        "cursors": cursors if isinstance(cursors, dict) else {},
        "totals": totals,
        "syncer": "local-file",
        "note": "" if bound else "unbound: bind with a registration code first"}

@router.get("/status")
def remote_status():
    return {"data": _status_payload()}
class BindBody(BaseModel):
    base_url: Optional[str] = ""
    token: Optional[str] = ""
    enterprise_name: Optional[str] = ""
    terminal_name: Optional[str] = ""
    level: Optional[str] = "member"

@router.post("/bind")
def remote_bind(body: BindBody):
    return _bind_impl(body)
def _bind_impl(body):
    cur = _read_json(REMOTE_PATH, {})
    if not isinstance(cur, dict): cur = {}
    cur.update({"base_url": body.base_url or "", "token": body.token or "",
        "enterprise_name": body.enterprise_name or "", "terminal_name": body.terminal_name or "",
        "level": body.level or "member"})
    with open(REMOTE_PATH, "w", encoding="utf-8") as f:
        import json as _j; _j.dump(cur, f, ensure_ascii=False, indent=2)
    return {"data": _status_payload()}

@router.delete("/unbind")
def remote_unbind():
    return _unbind_impl()
def _unbind_impl():
    cur = _read_json(REMOTE_PATH, {})
    if not isinstance(cur, dict): cur = {}
    cur["token"] = ""
    if isinstance(cur.get("remote"), dict): cur["remote"]["token"] = ""
    with open(REMOTE_PATH, "w", encoding="utf-8") as f:
        import json as _j; _j.dump(cur, f, ensure_ascii=False, indent=2)
    return {"data": _status_payload()}
class RegisterBody(BaseModel):
    base_url: Optional[str] = ""
    registration_code: Optional[str] = ""
    hostname: Optional[str] = ""
    os_info: Optional[str] = ""
    agent_type: Optional[str] = ""
    agent_version: Optional[str] = ""
    argus_version: Optional[str] = "2.1"

@router.post("/register")
def remote_register(body: RegisterBody):
    import urllib.request, urllib.error
    base = (body.base_url or "").strip().rstrip("/") or "http://127.0.0.1:8080"
    code = (body.registration_code or "").strip()
    if not code:
        return {"error": "registration_code required"}
    payload = {"registration_code": code, "hostname": body.hostname or "", "os_info": body.os_info or "", "agent_type": body.agent_type or "", "agent_version": body.agent_version or "", "argus_version": body.argus_version or "2.1"}
    try:
        req = urllib.request.Request(base + "/telemetry/v1/register", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception as e:
        return {"error": str(e)}
    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    token = str(inner.get("token") or "")
    if not token:
        return {"error": "register failed", "raw": data}
    cur = _read_json(REMOTE_PATH, {})
    if not isinstance(cur, dict): cur = {}
    cur.update({"base_url": base, "token": token, "terminal_id": inner.get("terminal_id"), "terminal_name": inner.get("terminal_name") or body.hostname or "", "level": cur.get("level", "member"), "llm": inner.get("llm") or {}})
    _write_json(REMOTE_PATH, cur)
    _write_json(CURSORS_PATH, _read_json(CURSORS_PATH, {}) or {})
    return {"data": _status_payload()}


@router.post("/sync-now")
def remote_sync_now():
    """Watchdog entry: run one heartbeat+usage+audit round now; never raises."""
    try:
        from argus.api.remote_sync import run_once
        ok = run_once()
    except Exception as exc:
        return {"data": {"ok": False, "error": str(exc)[:200], "cursors": _read_json(CURSORS_PATH, {})}}
    return {"data": {"ok": bool(ok), "cursors": _read_json(CURSORS_PATH, {})}}
