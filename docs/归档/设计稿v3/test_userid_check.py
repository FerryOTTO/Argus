import sys
sys.path.insert(0, 'v1\\auth-gateway-extracted')
from auth_gateway import check, check_reason, sync_external_user, _store

# 模拟 main.py 的调用 - 使用 user_id (JWT sub)
user_id = 'usr_R4jyvizIyZZd4tKG'
sync_external_user(user_id, 'secret')

# 测试 check
path = 'C:\\Users\\admin\\'
result = check(user_id, path, '', '')
ok, reason = check_reason(user_id, path, '', '')
print(f'User ID: {user_id}')
print(f'User level: {_store.get_user_level(user_id)}')
print(f'Path: {path}')
print(f'check: {result}')
print(f'reason: {ok} {reason}')
