'''Quarantine routes for AccessControl near-permanent ban.'''

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from clawguard.modules.access_control.quarantine_store import QuarantineStore

router = APIRouter(prefix='/v1/admin/quarantine', tags=['quarantine'])


class QuarantineClearRequest(BaseModel):
    user_id: str
    by: str = 'admin'


class QuarantineAddRequest(BaseModel):
    user_id: str
    reason: str = 'manual'
    by: str = 'admin'


@router.get('/list')
def list_quarantine(all: bool = False) -> dict[str, Any]:
    store = QuarantineStore()
    if all:
        items = store.list_all()
    else:
        items = store.list_active()
    return {'items': items, 'total': len(items), 'all': all}


@router.get('/check/{user_id}')
def check_quarantine(user_id: str) -> dict[str, Any]:
    store = QuarantineStore()
    rec = store.get(user_id)
    return {'user_id': user_id, 'quarantined': store.is_quarantined(user_id), 'record': rec}


@router.post('/quarantine')
def add_quarantine(req: QuarantineAddRequest) -> dict[str, Any]:
    if not req.user_id.strip():
        raise HTTPException(status_code=422, detail={'code': 'user_id_required', 'message': 'user_id required'})
    store = QuarantineStore()
    rec = store.quarantine(req.user_id.strip(), req.reason, assessment={'manual': True}, by=req.by)
    return {'status': 'quarantined', 'record': rec}


@router.post('/clear')
def clear_quarantine(req: QuarantineClearRequest) -> dict[str, Any]:
    if not req.user_id.strip():
        raise HTTPException(status_code=422, detail={'code': 'user_id_required', 'message': 'user_id required'})
    store = QuarantineStore()
    ok = store.clear(req.user_id.strip(), by=req.by)
    if not ok:
        raise HTTPException(status_code=404, detail={'code': 'not_quarantined', 'message': 'user not quarantined or already cleared'})
    return {'status': 'cleared', 'user_id': req.user_id.strip()}


@router.post('/clear_all')
def clear_all_quarantine() -> dict[str, Any]:
    store = QuarantineStore()
    cnt = store.clear_all()
    return {'status': 'cleared_all', 'cleared_count': cnt}
