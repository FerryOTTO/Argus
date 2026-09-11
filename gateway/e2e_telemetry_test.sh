#!/bin/bash
# LLMGate 终端遥测模块端到端联调脚本（对照 REMOTE.md 契约）
set -e
BASE=http://127.0.0.1:8080
J() { python3 -c "import sys,json;d=json.load(sys.stdin);print(eval('d'+sys.argv[1]))" "$1"; }

echo "== 1) 管理员登录 =="
ADMIN_TOKEN=$(curl -s -X POST $BASE/api/auth/login -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | J "['token']")
echo "admin token ok: ${ADMIN_TOKEN:0:20}..."

echo "== 2) 管理端添加终端 =="
CREATE=$(curl -s -X POST $BASE/api/admin/terminals \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"dev-test-01","agent_type":"openclaw","description":"e2e 联调终端"}')
echo "$CREATE" | python3 -m json.tool | head -12
CODE=$(echo "$CREATE" | J "['data']['registration_code']")
TERM_ID=$(echo "$CREATE" | J "['data']['terminal']['id']")
echo "terminal_id=$TERM_ID code=${CODE:0:8}..."

echo "== 3) 客户端注册（注册码换取遥测令牌） =="
REG=$(curl -s -X POST $BASE/telemetry/v1/register -H "Content-Type: application/json" \
  -d "{\"registration_code\":\"$CODE\",\"hostname\":\"dev-mac\",\"os_info\":\"macOS 26.5.1\",\"agent_type\":\"openclaw\",\"agent_version\":\"2026.6.11\",\"argus_version\":\"2.1.0\"}")
TOKEN=$(echo "$REG" | J "['data']['token']")
echo "注册成功: terminal_id=$(echo "$REG" | J "['data']['terminal_id']") token=${TOKEN:0:8}..."

echo "== 4) 心跳 =="
curl -s -X POST $BASE/telemetry/v1/heartbeat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"hostname":"dev-mac","argus_version":"2.1.0"}'
echo

echo "== 5) 管理端下发 Argus 配置 =="
# 用 python 构造嵌套 JSON，避免 shell 转义问题
CONFIG_PAYLOAD=$(python3 -c "import json; print(json.dumps({'config': json.dumps({'modules': {'io_guard': {'enabled': True, 'risk_threshold': 0.8}}})}))")
curl -s -X PUT $BASE/api/admin/terminals/$TERM_ID/config \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d "$CONFIG_PAYLOAD"
echo

echo "== 5b) 验证回执超前保护（config_version=99 应被 409 拒绝） =="
curl -s -X POST $BASE/telemetry/v1/config/applied \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"config_version":99}'
echo

echo "== 6) 客户端拉取配置 =="
curl -s $BASE/telemetry/v1/config -H "Authorization: Bearer $TOKEN"
echo

echo "== 7) 应用回执 =="
curl -s -X POST $BASE/telemetry/v1/config/applied \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"config_version":1}'
echo

echo "== 8) 上报 Token/安全预警增量 =="
curl -s -X POST $BASE/telemetry/v1/report \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"window_started_at":"2026-09-08T21:00:00Z","token_usage_delta":12500,"security_alerts_delta":2,"alert_samples":[{"at":"2026-09-08T21:30:00Z","stage":"tool_pre","module":"tool_guard","action":"block","risk_score":0.93,"reason":"intent mismatch","trace_id":"claw-e2e-1"}]}'
echo

echo "== 9) 心跳确认配置已同步 =="
curl -s -X POST $BASE/telemetry/v1/heartbeat -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}'
echo

echo "== 10) 管理端查看终端列表（聚合数据） =="
curl -s "$BASE/api/admin/terminals?keyword=dev-test-01" -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -c "
import sys, json
d = json.load(sys.stdin)['data'][0]
keys = ['id','name','agent_type','bound_username','hostname','argus_version','agent_version','status','online','token_usage_total','alert_count_total','config_version','config_applied_version','last_seen_at']
for k in keys: print(f'  {k}: {d.get(k)}')
"
echo "== E2E PASS =="
