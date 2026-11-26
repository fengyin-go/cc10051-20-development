"""实体版本快照领域逻辑：变更审批与实体发布共用的版本历史读写。

数据链路位置：模型治理层版本端，负责维护实体定义的版本快照、
生效依据与变更单回执，供审批页回看旧定义、实体页按版本领用。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.store import store

SNAPSHOT_TABLE = "entity_version"
DEFINITION_FIELDS = ["实体名称", "唯一键规则", "合并策略"]
SNAPSHOT_STATUSES = ["候选", "已生效", "已代替", "已驳回"]
# 只有这些状态下的变更单允许继续编辑候选定义
CANDIDATE_EDITABLE_STATUSES = ("起草中", "待审批", "待重新核对")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def version_number(version: Any) -> int:
    text = str(version or "").strip().lstrip("vV")
    return int(text) if text.isdigit() else 0


def next_version(current: Any) -> str:
    return f"v{version_number(current) + 1}"


def definition_of(entity_row: dict[str, Any]) -> dict[str, str]:
    """从实体行提取结构定义字段（版本号、实体编码属标识，不进定义）。"""
    return {field: str(entity_row.get(field, "")) for field in DEFINITION_FIELDS}


def entity_of(entity_code: str) -> dict[str, Any] | None:
    return next((row for row in store.rows("entity_model")
                 if row.get("实体编码") == entity_code), None)


def snapshots_for(entity_code: str) -> list[dict[str, Any]]:
    return [row for row in store.rows(SNAPSHOT_TABLE)
            if row.get("实体编码") == entity_code]


def snapshot_of(entity_code: str, version: str) -> dict[str, Any] | None:
    """按版本号取快照；同号快照优先返回已生效的那一份。"""
    matches = [row for row in snapshots_for(entity_code)
               if row.get("版本号") == version]
    if not matches:
        return None
    effective = [row for row in matches if row.get("版本状态") == "已生效"]
    return effective[0] if effective else matches[0]


def snapshots_by_order(order_no: str) -> list[dict[str, Any]]:
    return [row for row in store.rows(SNAPSHOT_TABLE)
            if row.get("来源变更单") == order_no]


def current_effective(entity_code: str) -> dict[str, Any] | None:
    """实体当前生效版本的快照（与实体行版本号对齐）。"""
    entity = entity_of(entity_code)
    if entity is None:
        return None
    snap = snapshot_of(entity_code, str(entity.get("版本号", "")))
    if snap is not None and snap.get("版本状态") == "已生效":
        return snap
    return None


def new_snapshot(
    *,
    entity_code: str,
    version: str,
    baseline: str,
    order_no: str,
    order_id: int | None,
    definition: dict[str, Any],
    status: str,
    basis: str,
) -> dict[str, Any]:
    """写入一份版本快照；定义深拷贝，保证快照之间互不串字段。"""
    rows = store.rows(SNAPSHOT_TABLE)
    snapshot = {
        "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
        "实体编码": entity_code,
        "版本号": version,
        "版本状态": status,
        "基线版本": baseline,
        "来源变更单": order_no,
        "变更单ID": order_id,
        "快照定义": deepcopy(definition),
        "生效依据": basis,
        "登记时间": now_iso(),
        "生效时间": now_iso() if status == "已生效" else "",
        "status": status,
        "pending": status == "候选",
        "abnormal": status in ("已代替", "已驳回"),
    }
    rows.append(snapshot)
    return snapshot


def supersede_candidates(
    entity_code: str,
    baseline: str,
    winner_order_no: str,
    winner_version: str,
) -> list[dict[str, Any]]:
    """同一基线上的其他候选快照与待审批变更单标记为已代替。

    被代替的单据保留可查，但不能自行切换成已生效。
    """
    affected: list[dict[str, Any]] = []
    for snap in snapshots_for(entity_code):
        if (snap.get("版本状态") == "候选"
                and snap.get("基线版本") == baseline
                and snap.get("来源变更单") != winner_order_no):
            snap["版本状态"] = "已代替"
            snap["status"] = "已代替"
            snap["pending"] = False
            snap["abnormal"] = True
            affected.append(snap)
    for order in store.rows("model_change"):
        if (order.get("实体编码") == entity_code
                and order.get("status") == "待审批"
                and str(order.get("基线版本", "")) == baseline
                and order.get("变更单号") != winner_order_no):
            order["status"] = "已代替"
            order["审批状态"] = "已代替"
            order["pending"] = False
            order["abnormal"] = True
            order["回执"] = {
                "确认流水": order.get("确认流水", ""),
                "结果": "已被代替",
                "当前版本": winner_version,
                "说明": f"基线 {baseline} 已被变更单 {winner_order_no} 占用，版本 {winner_version} 先生效",
                "时间": now_iso(),
            }
            affected.append(order)
    return affected


# ---- 查询与领用：供路由层调用的只读/登记逻辑 ----

def list_versions(entity_id: int) -> dict[str, Any] | None:
    """实体页版本历史：全部快照带生效依据，并标注当前可领用版本。"""
    entity = store.find("entity_model", entity_id)
    if entity is None:
        return None
    code = str(entity.get("实体编码", ""))
    snaps = sorted(snapshots_for(code),
                   key=lambda r: (version_number(r.get("版本号")), int(r.get("id", 0))))
    return {
        "实体编码": code,
        "实体名称": entity.get("实体名称", ""),
        "当前版本": entity.get("版本号", ""),
        "items": snaps,
    }


def get_version(entity_id: int, version: str) -> dict[str, Any] | None:
    entity = store.find("entity_model", entity_id)
    if entity is None:
        return None
    return snapshot_of(str(entity.get("实体编码", "")), version)


def claim_version(entity_id: int, version: str) -> tuple[dict[str, Any] | None, str]:
    """按版本发起办理：领用一份已生效快照，生成以其为基线的变更单。"""
    entity = store.find("entity_model", entity_id)
    if entity is None:
        return None, "实体定义不存在"
    code = str(entity.get("实体编码", ""))
    snap = snapshot_of(code, version)
    if snap is None:
        return None, f"实体 {code} 的版本 {version} 不存在"
    if snap.get("版本状态") != "已生效":
        return None, f"版本 {version} 状态为{snap.get('版本状态')}，只有已生效版本可领用"
    changes = store.rows("model_change")
    change_id = max((int(r.get("id", 0)) for r in changes), default=0) + 1
    order_no = f"MC-{entity_id}-{change_id}"
    order = {
        "id": change_id,
        "变更单号": order_no,
        "实体编码": code,
        "变更内容": f"基于版本 {version} 发起变更（领用快照 #{snap.get('id')}）",
        "审批状态": "起草中",
        "生效版本": "",
        "基线版本": version,
        "候选定义": deepcopy(snap.get("快照定义") or {}),
        "确认流水": f"CF-{order_no}",
        "回执": None,
        "status": "起草中",
        "pending": True,
        "abnormal": False,
    }
    changes.append(order)
    return order, f"已按版本 {version} 发起变更单 {order_no}，请到实体变更审批页继续办理"


def version_view(change_id: int) -> dict[str, Any] | None:
    """审批页回看：本单关联定义（历史内容）与当前可领用状态分开返回。"""
    order = store.find("model_change", change_id)
    if order is None:
        return None
    code = str(order.get("实体编码", ""))
    linked = sorted(snapshots_by_order(str(order.get("变更单号", ""))),
                    key=lambda r: int(r.get("id", 0)))
    chosen: dict[str, Any] | None = None
    for status in ("已生效", "候选"):
        chosen = next((s for s in linked if s.get("版本状态") == status), None)
        if chosen is not None:
            break
    if chosen is None and linked:
        chosen = linked[-1]
    definition = chosen.get("快照定义") if chosen is not None else order.get("候选定义")
    claimable = [s for s in snapshots_for(code) if s.get("版本状态") == "已生效"]
    claimable.sort(key=lambda r: version_number(r.get("版本号")))
    return {
        "变更单": order,
        "关联快照": chosen,
        "关联定义": definition,
        "回执": order.get("回执"),
        "实体": entity_of(code),
        "当前生效版本": current_effective(code),
        "可领用版本": claimable,
    }


def receipt_view(change_id: int) -> dict[str, Any] | None:
    """按原确认取回执：返回该单实际采用的定义与全部关联快照。"""
    order = store.find("model_change", change_id)
    if order is None:
        return None
    receipt = order.get("回执")
    adopted: dict[str, Any] | None = None
    if receipt and receipt.get("采用版本"):
        snap = snapshot_of(str(order.get("实体编码", "")), str(receipt["采用版本"]))
        adopted = deepcopy(snap.get("快照定义")) if snap is not None else None
    return {
        "变更单号": order.get("变更单号"),
        "确认流水": order.get("确认流水"),
        "回执": receipt,
        "实际采用定义": adopted,
        "关联快照": snapshots_by_order(str(order.get("变更单号", ""))),
    }


def update_candidate(change_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """更新变更单候选定义，并同步到仍处于候选状态的快照。"""
    order = store.find("model_change", change_id)
    if order is None:
        return None, "变更单不存在"
    if order.get("status") not in CANDIDATE_EDITABLE_STATUSES:
        return None, f"变更单状态为{order.get('status')}，候选定义不可再修改"
    candidate = dict(order.get("候选定义") or {})
    for field in DEFINITION_FIELDS:
        if field in values and str(values[field]).strip():
            candidate[field] = str(values[field]).strip()
    order["候选定义"] = candidate
    for snap in snapshots_by_order(str(order.get("变更单号", ""))):
        if snap.get("版本状态") == "候选":
            snap["快照定义"] = deepcopy(candidate)
    return order, "候选定义已更新"
