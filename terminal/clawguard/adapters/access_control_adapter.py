'''AccessControl Adapter with near-permanent quarantine.'''

from __future__ import annotations

import os
from time import perf_counter
from typing import Any

from clawguard.adapters.base import BaseAdapter
from clawguard.common.models import ModuleResult, SecurityRequest
from clawguard.modules.access_control.original.auth_gateway import check_v4
from clawguard.modules.access_control.risk_link import AuditRiskMonitor, DynamicLinePolicy, QuarantinePolicy
from clawguard.modules.access_control.quarantine_store import QuarantineStore

class AccessControlAdapter(BaseAdapter):
    name = 'access_control'
    def __init__(self, *, risk_monitor: AuditRiskMonitor | None = None, risk_policy: DynamicLinePolicy | None = None, risk_link_enabled: bool | None = None, quarantine_store: QuarantineStore | None = None, quarantine_policy: QuarantinePolicy | None = None) -> None:
        self._risk_link_enabled = risk_link_enabled if risk_link_enabled is not None else os.getenv('CLAWGUARD_AC_RISK_LINK', '1') != '0'
        self._risk_monitor = risk_monitor or AuditRiskMonitor()
        self._risk_policy = risk_policy or DynamicLinePolicy()
        self._quarantine_store = quarantine_store or QuarantineStore()
        self._quarantine_policy = quarantine_policy or QuarantinePolicy()
    def run_sync(self, request: SecurityRequest | dict[str, Any]) -> ModuleResult | dict[str, Any]:
        started = perf_counter()
        is_dict_input = isinstance(request, dict)
        try:
            if is_dict_input:
                context = request.get('context', {})
                payload = request.get('payload', {})
                user_id = str(context.get('user_id', 'default_user'))
                session_id = str(context.get('session_id', ''))
            else:
                context = request.context
                payload = request.payload or {}
                user_id = str(context.user_id)
                session_id = str(context.session_id)
            tool_name = str(payload.get('tool_name', ''))
            if tool_name and not tool_name.startswith('tool:'):
                tool_name = f'tool:{tool_name}'
            arguments = payload.get('arguments', {})
            path = '' if not isinstance(arguments, dict) else str(arguments.get('path', ''))
            if path:
                path = os.path.normpath(path)
            database = str(payload.get('database', ''))
            res_dict = self._decide(user_id=user_id, session_id=session_id, path=path, tool=tool_name, database=database)
            latency = (perf_counter() - started) * 1000
            res_dict['latency_ms'] = round(latency, 3)
            if is_dict_input:
                return res_dict
            return ModuleResult(**res_dict)
        except Exception as exc:
            latency = (perf_counter() - started) * 1000
            err_dict = {'module': self.name, 'success': False, 'action': 'block', 'risk_score': 1.0, 'reason': 'module_error', 'modified_data': None, 'details': {}, 'latency_ms': round(latency, 3), 'error': str(exc)}
            if is_dict_input:
                return err_dict
            return ModuleResult(**err_dict)
    def _decide(self, *, user_id: str, session_id: str, path: str, tool: str, database: str) -> dict[str, Any]:
        result = check_v4(user_id=user_id, path=path, tool=tool, database=database)
        allowed = bool(result.get('allowed', False))
        reason = str(result.get('reason', ''))
        if not self._risk_link_enabled:
            return {'module': self.name, 'success': True, 'action': 'allow' if allowed else 'block', 'risk_score': 0.0 if allowed else 1.0, 'reason': reason, 'modified_data': None, 'details': {'user_id': user_id, 'tool': tool, 'path': path, 'database': database, 'risk': {'score': 0.0, 'block_count': 0, 'event_count': 0, 'probe_likely': False}, 'escalated': False, 'penalty': 0}, 'error': None}
        # 0.5) 已隔离检查 - 按原始判定返回 block/human_review
        try:
            if self._quarantine_store.is_quarantined(user_id):
                rec = self._quarantine_store.get(user_id) or {}
                action = 'block' if not allowed else 'human_review'
                return {'module': self.name, 'success': True, 'action': action, 'risk_score': 1.0, 'reason': f'quarantined: user {user_id} 已隔离需管理员解除 (since {rec.get('quarantined_at','')}, reason={rec.get('reason','')})', 'modified_data': None, 'details': {'user_id': user_id, 'tool': tool, 'path': path, 'database': database, 'risk': {'score': 1.0, 'block_count': 999, 'event_count': 999, 'probe_likely': True, 'quarantined': True}, 'escalated': True, 'penalty': 2, 'quarantine': rec}, 'error': None}
        except Exception:
            pass
        try:
            assessment = self._risk_monitor.assess(user_id, session_id)
        except Exception:
            assessment = {'risk_score': 0.0, 'block_count': 0, 'probe_likely': False, 'event_count': 0}
        penalty = self._risk_policy.penalty_for(assessment)
        escalated_allowed = allowed
        if penalty > 0:
            escalated = check_v4(user_id=user_id, path=path, tool=tool, database=database, penalty=penalty)
            escalated_allowed = bool(escalated.get('allowed', False))
        decision = self._risk_policy.decide(allowed=allowed, escalated_allowed=escalated_allowed, reason=reason, assessment=assessment)
        try:
            should, q_reason = self._quarantine_policy.should_quarantine(assessment)
            if should:
                self._quarantine_store.quarantine(user_id, q_reason, assessment, by='system')
            else:
                lw = self._quarantine_policy.long_window_assessment(user_id, session_id, store=self._risk_monitor._store if hasattr(self._risk_monitor, '_store') else None)
                if lw.get('trigger'):
                    self._quarantine_store.quarantine(user_id, lw['reason'], assessment, by='system')
        except Exception:
            pass
        return {'module': self.name, 'success': True, 'action': decision['action'], 'risk_score': decision['risk_score'], 'reason': decision['reason'], 'modified_data': None, 'details': {'user_id': user_id, 'tool': tool, 'path': path, 'database': database, 'risk': {'score': assessment.get('risk_score', 0.0), 'block_count': assessment.get('block_count', 0), 'event_count': assessment.get('event_count', 0), 'probe_likely': assessment.get('probe_likely', False)}, 'escalated': decision['escalated'], 'penalty': decision['penalty'], 'quarantined': self._quarantine_store.is_quarantined(user_id) if hasattr(self, '_quarantine_store') else False}, 'error': None}
    async def run(self, request: SecurityRequest | dict[str, Any]) -> ModuleResult:
        res = self.run_sync(request)
        if isinstance(res, dict):
            return ModuleResult(**res)
        return res
