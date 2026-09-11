# seed.py — 批量生成测试用户（Faker 真实姓名）
#
# 用法:
#   python seed.py              # 默认生成 20 个用户
#   python seed.py -n 50        # 生成 50 个用户
#   python seed.py -n 10 --cn   # 仅中文名
#   python seed.py -n 10 --en   # 仅英文名
#   python seed.py --admin adminuser  # 同时创建一个 admin
"""
示例输出:
  $ python seed.py -n 8
  密码: test12345（所有用户统一）
  ──────────────────────────────────
  1.  admin_user        role=admin
  2.  张伟  (zhangwei)   role=user  agent=agent_xxx...
  3.  John Smith (johnsmith) role=user  agent=agent_xxx...
  ...
"""
import asyncio
import argparse
import sys
import os

# Windows 终端强制 UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from faker import Faker


async def seed_users(count: int = 20, locale: str = "both",
                     admin_username: str = "", password: str = "test12345"):
    """
    批量生成用户。

    Args:
        count: 生成数量
        locale: 'cn' | 'en' | 'both' 姓名偏好
        admin_username: 额外创建一个 admin 用户
        password: 所有用户的统一密码
    """
    from database import init_db, close_db, count_users

    await init_db()

    existing = await count_users()
    print(f"当前数据库已有 {existing} 个用户\n")

    # ---- 生成姓名列表 ----
    seen_usernames = set()
    names = []

    fake_cn = Faker("zh_CN") if locale in ("cn", "both") else None
    fake_en = Faker("en_US") if locale in ("en", "both") else None

    cn_target = count if locale == "cn" else (count // 2 if locale == "both" else 0)
    en_target = count if locale == "en" else (count - cn_target if locale == "both" else 0)

    # Chinese names: retry until we have enough valid ones
    cn_collected = 0
    for _ in range(cn_target * 5):  # max attempts
        if cn_collected >= cn_target:
            break
        raw = fake_cn.name().replace("先生", "").replace("女士", "").strip()
        if len(raw) < 3 or raw in seen_usernames:
            continue
        seen_usernames.add(raw)
        names.append((raw, raw))
        cn_collected += 1

    # English names
    en_collected = 0
    for _ in range(en_target * 3):
        if en_collected >= en_target:
            break
        first = fake_en.first_name()
        last = fake_en.last_name()
        username = f"{first.lower()}{last.lower()}"
        if username in seen_usernames:
            continue
        seen_usernames.add(username)
        names.append((f"{first} {last}", username))
        en_collected += 1

    # ---- 批量注册 ----
    from auth import register_user
    from config import config

    created = []
    errors = []

    for i, (full_name, username) in enumerate(names, 1):
        try:
            user = await register_user(username, password)
            created.append((i, full_name, username, user["role"], user["agent"]["agent_id"]))
        except ValueError as e:
            errors.append((username, str(e)))

    # ---- 创建 admin（如果指定）----
    admin_created = False
    if admin_username:
        try:
            # 临时设 config.admin_username 以自动提升
            config.admin_username = admin_username
            user = await register_user(admin_username, password)
            config.admin_username = ""  # 恢复
            admin_created = True
            created.insert(0, (0, admin_username, admin_username, "admin", user["agent"]["agent_id"]))
        except ValueError as e:
            errors.append((admin_username, str(e)))

    # ---- 输出结果 ----
    print(f"Password: {password} (all users)")
    print(f"{'-' * 62}")
    for idx, full_name, username, role, agent_id in created:
        tag = "[ADMIN]" if role == "admin" else "       "
        print(f"{tag} {idx:3d}. {full_name:<20s} @{username:<24s} role={role:<5s} agent={agent_id[:24]}...")
    print(f"{'-' * 62}")
    print(f"Success: {len(created)}  Failed: {len(errors)}")

    if errors:
        print(f"\n[WARN] 失败详情:")
        for username, err in errors:
            print(f"    {username}: {err}")

    await close_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenGuard 测试用户种子脚本")
    parser.add_argument("-n", "--count", type=int, default=20, help="生成数量（默认 20）")
    parser.add_argument("--cn", action="store_true", help="仅中文名")
    parser.add_argument("--en", action="store_true", help="仅英文名")
    parser.add_argument("--admin", type=str, default="", help="同时创建 admin 用户")
    parser.add_argument("--password", type=str, default="test12345", help="统一密码（默认 test12345）")
    args = parser.parse_args()

    locale = "cn" if args.cn else ("en" if args.en else "both")

    asyncio.run(seed_users(
        count=args.count,
        locale=locale,
        admin_username=args.admin,
        password=args.password,
    ))
