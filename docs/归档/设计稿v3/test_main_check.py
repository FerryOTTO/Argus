import sys
sys.path.insert(0, 'v1\\auth-gateway-extracted')
from auth_gateway import check, check_reason, sync_external_user, _store

# 模拟 main.py 的调用
sync_external_user('usr_R4jyvizIyZZd4tKG', 'secret')

# 模拟 WebSocket 消息
messages = [
    "帮我看看 C:\\Users\\admin\\ 里面有什么",
    "看看 C:\\Windows\\System32",
    "读取 C:\\Users\\admin\\Documents\\file.txt",
]

import re
PATH_RE = re.compile(r'([A-Za-z]:\\[a-zA-Z0-9_.\-\\]+)', re.IGNORECASE)

for msg in messages:
    print(f'消息: {msg}')
    resources = []
    for m in PATH_RE.finditer(msg):
        p = m.group(0).rstrip('.,;:!?，。；：！？')
        resources.append(p)

    for path in resources:
        user_id = 'usr_R4jyvizIyZZd4tKG'
        result = check(user_id, path, '', '')
        ok, reason = check_reason(user_id, path, '', '')
        print(f'  路径: {path}')
        print(f'  check: {result}, reason: {ok} {reason}')
    print()
