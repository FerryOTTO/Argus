import sys
sys.path.insert(0, 'E:\\tiaozhanbei\\MAC\\v1\\auth-gateway-extracted')
from auth_gateway import check, check_reason, sync_external_user, _store

# 诊断信息
print("=== Argus 诊断 ===")
print()

# 1. 检查所有用户
print("1. 用户规则:")
for uid, data in _store.users.items():
    print(f"   {uid}: level={data['level']}, specials={data.get('specials', [])}")
print()

# 2. 检查资源规则
print("2. 资源规则 (前10条):")
for pattern, level, mode in _store.resources[:10]:
    print(f"   {pattern} | {level} | {mode}")
print()

# 3. 测试 robertwright 的权限
user_id = 'usr_R4jyvizIyZZd4tKG'
sync_external_user(user_id, 'secret')

print(f"3. 用户 {user_id} 的等级: {_store.get_user_level(user_id)}")
print()

# 4. 测试各种路径
test_paths = [
    'C:\\Users\\admin\\',
    'C:\\Users\\admin\\test.txt',
    'C:\\Windows\\System32',
    'C:\\Users\\',
]

print("4. 路径测试:")
for path in test_paths:
    level = _store._backend._normalize_level if hasattr(_store._backend, '_normalize_level') else None
    result = check(user_id, path, '', '')
    ok, reason = check_reason(user_id, path, '', '')
    print(f"   {path}: {result} ({reason})")
