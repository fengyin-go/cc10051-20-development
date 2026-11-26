"""实体版本历史接口：版本快照查询、按版本领用、审批回看与确认回执。

路由层只做分派，版本状态流转与快照写入都在 app/services 里完成。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import ActionResult, EntryPayload
from app.services import versioning

router = APIRouter(prefix="/api", tags=["实体版本"])


@router.get("/entity_model/{entry_id}/versions", response_model=dict)
def list_entity_versions(entry_id: int) -> dict:
    """实体页版本历史：全部快照带生效依据，并标注当前可领用版本。"""
    payload = versioning.list_versions(entry_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"实体定义 {entry_id} 不存在或已归档")
    return payload


@router.get("/entity_model/{entry_id}/versions/{version}", response_model=dict)
def get_entity_version(entry_id: int, version: str) -> dict:
    """按版本号取快照：回看该结构曾经的状态和生效依据。"""
    snapshot = versioning.get_version(entry_id, version)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"版本 {version} 不存在")
    return snapshot


@router.post("/entity_model/{entry_id}/versions/{version}/claim", response_model=ActionResult)
def claim_entity_version(entry_id: int, version: str) -> ActionResult:
    """按版本发起办理：领用已生效快照，生成以其为基线的变更单。"""
    order, message = versioning.claim_version(entry_id, version)
    return ActionResult(ok=order is not None, message=message, entry=order)


@router.get("/model_change/{entry_id}/version_view", response_model=dict)
def change_version_view(entry_id: int) -> dict:
    """审批页回看：本单关联定义（历史内容）与当前可领用状态分开返回。"""
    payload = versioning.version_view(entry_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"变更单 {entry_id} 不存在或已归档")
    return payload


@router.get("/model_change/{entry_id}/receipt", response_model=dict)
def change_receipt(entry_id: int) -> dict:
    """按原确认取回执：返回该单实际采用的定义与全部关联快照。"""
    payload = versioning.receipt_view(entry_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"变更单 {entry_id} 不存在或已归档")
    return payload


@router.post("/model_change/{entry_id}/candidate", response_model=ActionResult)
def update_change_candidate(entry_id: int, payload: EntryPayload) -> ActionResult:
    """更新变更单候选定义，同步到仍处于候选状态的快照。"""
    order, message = versioning.update_candidate(entry_id, payload.values)
    return ActionResult(ok=order is not None, message=message, entry=order)
