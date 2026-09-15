import sys
sys.path.insert(0, 'v1\\auth-gateway-extracted')
from auth_gateway import check, check_reason, sync_external_user, _store
import re

# 模拟 main.py 的完整流程

# 1. 模拟 JWT payload
payload = {
    "sub": "usr_R4jyvizIyZZd4tKG",
    "username": "robertwright",
    "security_level": "secret"
}

user_id = payload["sub"]
security_level = payload.get("security_level", "public")

# 2. 模拟 sync_external_user
sync_external_user(user_id, security_level)

print(f"User ID: {user_id}")
print(f"Security Level: {security_level}")
print(f"User level in store: {_store.get_user_level(user_id)}")
print()

# 3. 模拟 extract_resources
PATH_RE = re.compile(r'([A-Za-z]:\\[a-zA-Z0-9_.\-\\]+)', re.IGNORECASE)

def extract_resources(text):
    resources = []
    for m in PATH_RE.finditer(text):
        p = m.group(0).rstrip('.,;:!?，。；：！？')
        resources.append(("path", p))
    return resources

# 4. 测试消息
messages = [
    "帮我看看 C:\\Users\\admin\\ 里面有什么",
]

for msg in messages:
    print(f'消息: {msg}')
    resources = extract_resources(msg)
    print(f'  提取资源: {resources}')

    for rtype, rvalue in resources:
        kwargs = {"user_id": user_id}
        if rtype == "path":
            kwargs["path"] = rvalue
        elif rtype == "tool":
            kwargs["tool"] = rvalue

        result = check(**kwargs)
        ok, reason = check_reason(**kwargs)
        print(f'  类型: {rtype}, 值: {rvalue}')
        print(f'  check: {result}')
        print(f'  reason: {ok} {reason}')

        if not result:
            print(f'  🛡️ [Argus] 您的等级 ({security_level}) 无权访问: {rvalue}')
    print()
