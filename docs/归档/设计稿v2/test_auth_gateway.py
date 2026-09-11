"""
Clawguard 访问控制网关 — 测试与演示脚本
============================================================
对核心函数 check() 做覆盖性验证：
  - 4 种用户等级放行路径
  - 等级拦截
  - 特例放行（越级）
  - 特例显式拒绝（!）
  - 未知用户处理
  - 工具 / 数据库 / 路径 三类资源
运行：
  python test_auth_gateway.py
"""

import sys
import io

# Windows 控制台 GBK 编码无法输出 emoji，统一切到 UTF-8
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from auth_gateway import check, check_reason, reload_rules


def _case(name, expect, uid, path="", tool="", database=""):
    ok = check(uid, path, tool, database)
    _, reason = check_reason(uid, path, tool, database)
    mark = "✅" if ok == expect else "❌"
    print(f"  {mark} {name}")
    print(f"     输入 user={uid!r} path={path!r} tool={tool!r} db={database!r}")
    print(f"     期望 {'ALLOW' if expect else 'BLOCK'} | 实际 {'ALLOW' if ok else 'BLOCK'} | {reason}")
    return ok == expect


def run_demo():
    print("=" * 72)
    print("       🛡️  Clawguard 访问控制网关 — 核心函数验证")
    print("=" * 72)
    print(" 函数签名： check(user_id, path, tool, database) -> bool (True=allow)")
    print(" 规则文件： rules/users.txt | rules/resources.txt\n")

    results = []

    print("【1】user_01 (internal=2) 访问 internal 资源 → 应 ALLOW")
    results.append(_case("普通员工查internal报告", True,
                         "user_01", path="/data/reports/2024/q3.txt"))

    print("\n【2】intern_01 (public=1) 调用 execute_bash (需4) → 应 BLOCK")
    results.append(_case("实习生执行bash", False,
                         "intern_01", tool="tool:execute_bash"))

    print("\n【3】intern_01 调用 query_weather (需1，且在特例中) → 应 ALLOW")
    results.append(_case("实习生查天气", True,
                         "intern_01", tool="tool:query_weather"))

    print("\n【4】auditor_01 (internal=2) 写文件 (需3，且特例!禁止) → 应 BLOCK")
    results.append(_case("审计员写文件被特例拒绝", False,
                         "auditor_01", tool="tool:write_file"))

    print("\n【5】auditor_01 读文件 (需2，特例允许) → 应 ALLOW")
    results.append(_case("审计员读文件特例放行", True,
                         "auditor_01", tool="tool:read_file"))

    print("\n【6】user_01 访问 /data/secret/* (需4) → 应 BLOCK（等级不足）")
    results.append(_case("普通员工读机密目录", False,
                         "user_01", path="/data/secret/x.pdf"))

    print("\n【7】admin_01 (top=4, 特例 *) 访问任何资源 → 应 ALLOW")
    results.append(_case("管理员读机密目录", True,
                         "admin_01", path="/data/secret/x.pdf"))
    results.append(_case("管理员执行bash", True,
                         "admin_01", tool="tool:execute_bash"))
    results.append(_case("管理员访问华为库", True,
                         "admin_01", database="db:huawei_db"))

    print("\n【8】guest_01 (public=1) 读 /public/news/* (需1，且特例) → 应 ALLOW")
    results.append(_case("访客读公开新闻", True,
                         "guest_01", path="/public/news/today.html"))

    print("\n【9】guest_01 读 /data/reports/* (需2) → 应 BLOCK")
    results.append(_case("访客读内部报告", False,
                         "guest_01", path="/data/reports/2024/q3.txt"))

    print("\n【10】数据库访问：user_01 访问华为库 (需4) → 应 BLOCK")
    results.append(_case("普通员工访问华为库", False,
                         "user_01", database="db:huawei_db"))

    print("\n【11】数据库访问：user_01 访问 public_db (需1) → 应 ALLOW")
    results.append(_case("普通员工访问公开库", True,
                         "user_01", database="db:public_db"))

    print("\n【12】路径遍历：user_01 访问 /etc/passwd (匹配 /etc/* 需4) → 应 BLOCK")
    results.append(_case("普通员工读etc", False,
                         "user_01", path="/etc/passwd"))

    print("\n【13】空请求（没有任何资源）→ 应 BLOCK")
    results.append(_case("空请求拒绝", False, "user_01"))

    print("\n【14】未知用户（不在 users.txt）→ 视策略放行/拦截")
    results.append(_case("未知用户读公开资源", True,
                         "ghost_01", path="/public/x"))

    # ===== 汇总 =====
    print("\n" + "=" * 72)
    print(f"  结果: {sum(results)}/{len(results)} 用例通过")
    print("=" * 72)
    return all(results)


if __name__ == "__main__":
    reload_rules()
    ok = run_demo()
    sys.exit(0 if ok else 1)