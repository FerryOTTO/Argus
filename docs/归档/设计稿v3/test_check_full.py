import sys
sys.path.insert(0, 'E:\\tiaozhanbei\\MAC\\v1\\auth-gateway-extracted')
from auth_gateway import check, check_reason, sync_external_user, _store

# 模拟 main.py 的调用
sync_external_user('usr_R4jyvizIyZZd4tKG', 'secret')

# 测试 check
user_id = 'usr_R4jyvizIyZZd4tKG'
path = 'C:\\Users\\admin\\'

print('User ID:', user_id)
print('User level:', _store.get_user_level(user_id))
print('Path:', path)

result = check(user_id, path, '', '')
print('check result:', result)

ok, reason = check_reason(user_id, path, '', '')
print('check_reason:', ok, reason)
