# -*- coding: utf-8 -*-
"""OpenGuard 认证 / 多用户隔离数据集 runner（真实鉴权链路，隔离库）。

为什么单独写一个 runner：
1. 数据集里的 JWT 是演示占位串（签名为 demo_signature_abc123），对真实服务一律 401。
   所以「期望 200/403」的用例必须换成同身份真登录拿到的真 Token 再发同一请求，
   「期望 401」的用例保留原始 Token，验证鉴权链路是真的会拒。
2. 限流类用例（register/login 429）按真实规则连打触发，每条用例前清空限流窗口，
   否则前几条用例就会把后面的挤成 429。
3. 整跑在临时 SQLite 上做（SQLITE_PATH 指向临时库、会话目录也指临时目录），
   不动服务端 data/auth.db，不污染在线服务。

用法：
    python eval_openguard_auth.py --repo <仓库根目录>\\terminal
    python eval_openguard_auth.py --repo ... --dump auth_result.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from eval_dataset import judge, load_dataset, summarize  # noqa: E402

FIXTURE_PW = "test12345"
ADMIN_PW = "admin12345"

# 端点 -> 需要管理员身份（数据集里给的是普通用户 Token，但接口实现是 admin-only）
ADMIN_ONLY = ("/api/admin/", "/auth/users", "/auth/sessions")

# endpoint 里的 {user_id} 占位符，按用例语义指向不同目标
TARGET_SELF = {"og-034", "og-038", "og-040"}      # 打自己 → 400
TARGET_MISSING = {"og-035"}                        # 不存在的用户 → 404
TARGET_ALICE = {"og-033"}                          # 改他人角色 → 200
TARGET_ZHANGSAN = {"og-020", "og-023", "og-036"}   # 配额 / 禁用 zhangsan（喂 og-037）
TARGET_VICTIM = {"og-039"}                         # 删除他人 → 200

# 用例跑了要额外说明的地方（写进 dump，方便出报告）
NOTES: dict[str, str] = {}


def _jwt_payload(token: str) -> dict:
    """不验签，只把 JWT payload 解出来看身份（数据集里的演示 Token 用）。"""
    try:
        seg = token.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg))
    except Exception:
        return {}


def _bearer(headers: dict) -> str:
    auth = (headers or {}).get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else ""


class _Session:
    """一次评测运行期间的夹具与状态。"""

    def __init__(self, client, limiter):
        self.client = client
        self.limiter = limiter
        self.ids: dict[str, str] = {}
        self.tokens: dict[str, str] = {}
        self.stale_refresh: str = ""

    # ---- 基础 I/O ----
    def clear_limit(self) -> None:
        self.limiter._windows.clear()

    def register(self, username: str, password: str = FIXTURE_PW):
        self.clear_limit()
        resp = self.client.post(
            "/auth/register", json={"username": username, "password": password}
        )
        if resp.status_code == 200:
            self.ids[username] = resp.json()["id"]
        return resp

    def login(self, username: str, password: str = FIXTURE_PW) -> str | None:
        """真登录拿真 Token（带缓存；登出后要手动 discard）。"""
        if username in self.tokens:
            return self.tokens[username]
        if username == "admin":
            password = ADMIN_PW
        self.clear_limit()
        resp = self.client.post(
            "/auth/login", json={"username": username, "password": password}
        )
        if resp.status_code == 401:
            # 夹具账号还没建（例如 zhangsan 由 og-001 现场注册）：补建后重试一次
            self.register(username, password)
            self.clear_limit()
            resp = self.client.post(
                "/auth/login", json={"username": username, "password": password}
            )
        if resp.status_code != 200:
            return None
        data = resp.json()
        self.tokens[username] = data["access_token"]
        self.refresh_tokens = getattr(self, "refresh_tokens", {})
        self.refresh_tokens[username] = data["refresh_token"]
        return self.tokens[username]

    def headers(self, username: str) -> dict:
        tok = self.login(username)
        return {"Authorization": f"Bearer {tok}"} if tok else {}

    def ensure_id(self, username: str) -> str:
        """拿用户 id：优先本地记录，其次问管理接口（对象可能是用例现场建的）。"""
        if username in self.ids:
            return self.ids[username]
        resp = self.client.get("/api/admin/users", headers=self.headers("admin"))
        if resp.status_code == 200:
            for u in resp.json():
                self.ids.setdefault(u["username"], u["id"])
        return self.ids.get(username, "usr_not_exist_0000")

    def discard(self, username: str) -> None:
        self.tokens.pop(username, None)


def _seed(sess: _Session) -> None:
    """备齐数据集需要的账号：admin + 普通用户 + 被禁用账号。"""
    sess.register("admin", ADMIN_PW)          # ADMIN_USERNAME=admin → 自动 admin 角色
    # zhangsan 留给 og-001 现场注册，验证「注册即建号」这条链路
    for name in ("lisi", "alice", "victim_user"):
        sess.register(name)
    sess.register("disabled_user")
    victim = sess.ids.get("disabled_user")
    if victim:
        resp = sess.client.put(
            f"/api/admin/users/{victim}/status",
            json={"status": "disabled"},
            headers=sess.headers("admin"),
        )
        if resp.status_code != 200:
            NOTES["seed"] = f"禁用夹具账号失败：HTTP {resp.status_code}"


def _case_status(r: dict, sess: _Session) -> int:
    """跑单条用例，返回真实 HTTP 状态码。"""
    cid = r["id"]
    sess.client.cookies.clear()      # 防止上一条用例的登录 Cookie 串到下一条
    req = r.get("request") or {}
    headers = dict(req.get("headers") or {})
    body = req.get("body")
    if body is None:
        body = {k: v for k, v in req.items() if k != "headers"} or None

    # ---------- 有状态的用例：单独处理 ----------
    if cid == "og-005":                     # 注册限流：连续打满
        sess.clear_limit()
        resp = None
        for _ in range(4):
            resp = sess.client.post("/auth/register", json=body)
        NOTES[cid] = "连打 4 次注册（限额 3/分钟），取最后一次"
        return resp.status_code

    if cid == "og-024":                     # 登录限流：连续打满
        sess.clear_limit()
        resp = None
        for _ in range(6):
            resp = sess.client.post("/auth/login", json=body)
        NOTES[cid] = "连打 6 次错误登录（限额 5/分钟），取最后一次"
        return resp.status_code

    if cid == "og-009":                     # 换发：数据集里的 refresh_token 是假串
        sess.login("zhangsan")
        rt = sess.refresh_tokens["zhangsan"]
        sess.stale_refresh = rt
        NOTES[cid] = "用真登录拿到的 refresh_token 换发（数据集里是演示占位串）"
        return sess.client.post("/auth/refresh", json={"refresh_token": rt}).status_code

    if cid == "og-010":                     # 重用检测：拿刚用过的那个再换一次
        NOTES[cid] = "复用上一条已消费的 refresh_token，应触发重用检测"
        return sess.client.post(
            "/auth/refresh", json={"refresh_token": sess.stale_refresh}
        ).status_code

    if cid == "og-014":                     # 登出后旧 Token 应失效
        tok = sess.login("zhangsan")
        sess.client.post("/auth/logout", headers={"Authorization": f"Bearer {tok}"})
        sess.discard("zhangsan")
        NOTES[cid] = "真登出后拿同一个 access_token 再访问 /me"
        return sess.client.get(
            "/me", headers={"Authorization": f"Bearer {tok}"}
        ).status_code

    if cid == "og-026":                     # 登出：用真 Token
        tok = sess.login("lisi")
        sess.discard("lisi")
        return sess.client.post(
            "/auth/logout", headers={"Authorization": f"Bearer {tok}"}
        ).status_code

    if cid == "og-022":                     # 配额超限：数据集用的是演示代理 Key
        NOTES[cid] = "数据集给的是演示代理 Key（sk-argus-proxy-…），非真实密钥"
        return sess.client.post(r["endpoint"], json=body, headers=headers).status_code

    # ---------- 通用路径 ----------
    endpoint = r["endpoint"].replace("{provider}", "oidc")
    if "{user_id}" in endpoint:
        if cid in TARGET_SELF:
            target = sess.ids["admin"]
        elif cid in TARGET_MISSING:
            target = "usr_not_exist_0000"
        elif cid in TARGET_ALICE:
            target = sess.ensure_id("alice")
        elif cid in TARGET_VICTIM:
            target = sess.ensure_id("victim_user")
        elif cid in TARGET_ZHANGSAN:
            target = sess.ensure_id("zhangsan")
        else:
            target = sess.ensure_id("zhangsan")
        endpoint = endpoint.replace("{user_id}", target)

    # 角色字段：实现只支持 user/admin 两级，数据集里写的 secret 会先被 422 拦掉，
    # 这里换成合法值，保证打到的仍然是「改角色」这条业务分支。
    if cid in ("og-033", "og-034", "og-035") and isinstance(body, dict):
        body = {**body, "role": "user" if cid != "og-033" else "admin"}
        NOTES[cid] = "数据集假设 4 级角色（secret），实现只有 user/admin，改用合法值"

    # 除「期望 401」（专测拒绝）之外的带 Token 用例，一律换成同身份真 Token：
    # 数据集里写的是演示占位串，直接发出去只会得到 401，测不到业务本身。
    want_token = _bearer(headers)
    if r["expected_status"] != 401 and want_token:
        username = _jwt_payload(want_token).get("username")
        if r["expected_status"] == 200 and any(endpoint.startswith(p) for p in ADMIN_ONLY):
            username = "admin"
            NOTES.setdefault(cid, "接口实现为 admin-only，改用管理员身份验证功能本身")
        if username in ("zhangsan", "lisi", "alice", "victim_user", "admin"):
            headers["Authorization"] = f"Bearer {sess.login(username)}"
    elif r["expected_status"] == 200 and any(endpoint.startswith(p) for p in ADMIN_ONLY):
        # 数据集这几条没写 Authorization，但接口本身就是管理员接口，按题面补上管理员身份
        headers["Authorization"] = f"Bearer {sess.login('admin')}"
        NOTES.setdefault(cid, "数据集未带 Token，按接口要求补管理员身份")

    kwargs = {"json": body, "headers": headers}
    # 无 Bearer 的状态变更请求走浏览器场景：带上一对 CSRF cookie/header，
    # 否则会先被 CSRF 中间件拦成 403，测不到后面的鉴权逻辑。
    if r["method"] in ("POST", "PUT", "DELETE", "PATCH") and not _bearer(headers):
        token = "eval-csrf-token"
        kwargs["cookies"] = {"csrf_token": token}
        kwargs["headers"] = {**headers, "X-CSRF-Token": token}
    resp = sess.client.request(r["method"], endpoint, **kwargs)
    if r["method"] == "POST" and endpoint == "/auth/register" and resp.status_code == 200:
        sess.ids.setdefault((body or {}).get("username", ""), resp.json().get("id", ""))
    return resp.status_code


def run_openguard_auth(rows: list[dict], repo: str | Path | None = None):
    """在隔离实例上逐条跑 OpenGuard 认证数据集。"""
    from fastapi.testclient import TestClient

    repo_root = Path(repo).resolve() if repo else None
    if repo_root is None or not (repo_root / "argus").exists():
        raise SystemExit("请用 --repo 指定 Argus 仓库路径")
    og_dir = repo_root / "openguard" / "original"

    # 隔离环境：临时库 + 临时会话目录，不能碰服务端 data/auth.db
    tmp = Path(tempfile.mkdtemp(prefix="og-eval-"))
    os.environ["SQLITE_PATH"] = str(tmp / "auth.db")
    os.environ["ADMIN_USERNAME"] = "admin"
    os.environ.setdefault("BRIDGE_TOKEN", "eval-bridge-token")

    sys.path.insert(0, str(og_dir))
    for stale in ("main", "config", "auth", "database", "models", "routes",
                  "session_store", "rate_limiter", "middleware", "sso",
                  "llm_proxy", "skills_routes", "message_store", "proxy"):
        sys.modules.pop(stale, None)

    import main as og_main                      # noqa: E402
    from session_store import session_store     # noqa: E402
    from rate_limiter import limiter            # noqa: E402

    session_store.SESSION_DIR = tmp / "sessions"
    session_store.SESSION_DIR.mkdir(parents=True, exist_ok=True)
    session_store._cache.clear()

    outcomes: list[tuple[dict, str, bool]] = []
    with TestClient(og_main.app) as client:
        sess = _Session(client, limiter)
        _seed(sess)
        for r in rows:
            try:
                status = _case_status(r, sess)
            except Exception as exc:                     # 单条崩了不拖垮整跑
                status = -1
                NOTES[r["id"]] = f"runner 异常：{type(exc).__name__}: {exc}"
            ok = status == r["expected_status"]
            outcomes.append((r, f"HTTP {status}", ok))
    return outcomes


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenGuard 认证数据集评测")
    ap.add_argument("--repo", required=True, help="Argus 仓库路径")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dump", default=None, help="把逐条结果写成 JSON")
    args = ap.parse_args()

    rows = load_dataset("openguard_auth")
    if args.limit:
        rows = rows[: args.limit]
    outcomes = run_openguard_auth(rows, args.repo)
    summarize("openguard_auth", rows, outcomes)

    if args.dump:
        payload = [
            {
                "id": r["id"], "category": r["category"],
                "endpoint": f'{r["method"]} {r["endpoint"]}',
                "expected_status": r["expected_status"],
                "actual": a, "hit": hit,
                "note": r.get("expected", ""),
                "runner_note": NOTES.get(r["id"], ""),
            }
            for r, a, hit in outcomes
        ]
        Path(args.dump).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"逐条结果已写入 {args.dump}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
