import sys
sys.path.insert(0, 'E:\\tiaozhanbei\\MAC\\v1\\auth-gateway-extracted')
from auth_gateway import check, check_reason, sync_external_user, _store

# 模拟新用户（internal等级）
user_id = 'new_internal_user'
sync_external_user(user_id, 'internal')

print(f"User ID: {user_id}")
print(f"User level: {_store.get_user_level(user_id)}")
print()

# 测试路径
test_paths = [
    'C:\\Users\\admin\\Downloads\\',
    'C:\\Users\\guest\\',
    'C:\\Users\\admin\\',
]

for path in test_paths:
    result = check(user_id, path, '', '')
    ok, reason = check_reason(user_id, path, '', '')
    print(f"路径: {path}")
    print(f"  check: {result}")
    print(f"  reason: {ok} {reason}")
    print()
