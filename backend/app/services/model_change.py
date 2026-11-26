"""实体变更审批领域服务：管理实体模型变更单的起草、提交审批、生效与驳回。

数据链路位置：模型治理层流程端，负责消费实体定义的版本变更，
把生效版本回写给实体模型并通知下游。

版本流转约定：
- 每张变更单登记时锁定自己的基线版本与候选定义，确认生效时只采用本单候选定义；
- 生效前做基线核对，基线被其他变更单占用时转入「待重新核对」，不强行生效；
- 同一变更单重复确认只写入一份版本记录，按原确认可刷新取回实际采用的定义；
- 已驳回、已代替的单据可恢复查证，但不能自行切换成已生效。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.services import versioning
from app.services.base import BaseModuleService
from app.store import store


class ModelChangeService(BaseModuleService):
    MODULE = "model_change"
    ENTITY = "变更单"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["变更单号", "实体编码", "变更内容", "审批状态", "生效版本"]
    REQUIRED_FIELDS = ["变更单号", "实体编码", "变更内容"]
    STATUS_ORDER = ["起草中", "待审批", "待重新核对", "已驳回", "已代替", "已生效"]
    ACTION_RULES = {
        "提交审批": "待审批",
        "生效变更": "已生效",
        "驳回变更": "已驳回",
        "重新核对": "待审批",
        "恢复查证": "起草中",
    }
    NEGATIVE_ACTIONS = ["驳回变更"]

    # ---- 登记：锁定本单基线版本与候选定义 ----

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        entry, missing = super().create_entry(values)
        if entry is None:
            return None, missing
        entity = versioning.entity_of(str(entry.get("实体编码", "")))
        entry["审批状态"] = "起草中"
        entry["生效版本"] = ""
        entry["基线版本"] = str(entity.get("版本号", "")) if entity else ""
        entry["候选定义"] = versioning.definition_of(entity) if entity else {}
        entry["确认流水"] = f"CF-{entry.get('变更单号')}"
        entry["回执"] = None
        return entry, []

    # ---- 动作分派：状态流转只允许在这里改 ----

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        handlers = {
            "提交审批": self._submit,
            "生效变更": self._confirm,
            "驳回变更": self._reject,
            "重新核对": self._recheck,
            "恢复查证": self._restore,
        }
        handler = handlers.get(action)
        if handler is None:
            return None, f"动作「{action}」不属于{self.MODULE}可执行范围"
        return handler(entry)

    def _submit(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """提交审批：按当前实体版本重新锁定基线，并登记候选版本快照。"""
        if entry.get("status") != "起草中":
            return None, f"只有起草中的变更单能提交审批（当前：{entry.get('status')}）"
        entity = versioning.entity_of(str(entry.get("实体编码", "")))
        if entity is None:
            return None, f"实体 {entry.get('实体编码')} 不存在"
        if not str(entry.get("变更内容", "")).strip():
            return None, "变更内容为空，不能提交"
        baseline = str(entity.get("版本号", ""))
        entry["基线版本"] = baseline
        if not entry.get("候选定义"):
            entry["候选定义"] = versioning.definition_of(entity)
        candidate_version = versioning.next_version(baseline)
        versioning.new_snapshot(
            entity_code=str(entity.get("实体编码", "")),
            version=candidate_version,
            baseline=baseline,
            order_no=str(entry.get("变更单号", "")),
            order_id=int(entry.get("id", 0)),
            definition=entry["候选定义"],
            status="候选",
            basis="",
        )
        entry["status"] = "待审批"
        entry["审批状态"] = "待审批"
        entry["pending"] = True
        return entry, f"变更单已提交审批，候选版本 {candidate_version} 等待确认生效"

    def _confirm(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """生效变更：基线核对 + 幂等写入版本记录，回写实体定义。"""
        status = entry.get("status")
        if status == "已生效":
            receipt = entry.get("回执") or {}
            adopted = receipt.get("采用版本", entry.get("生效版本", ""))
            return entry, f"重复确认：变更单已生效，版本记录 {adopted} 未重复写入"
        if status == "已驳回":
            return None, "已驳回的变更单不能自行生效，请先恢复查证"
        if status == "起草中":
            return None, "变更单尚未提交审批，不能生效"
        entity = versioning.entity_of(str(entry.get("实体编码", "")))
        if entity is None:
            return None, f"实体 {entry.get('实体编码')} 不存在"
        current = str(entity.get("版本号", ""))
        baseline = str(entry.get("基线版本", ""))
        if status == "已代替":
            self._mark_pending_recheck(
                entry, current,
                f"本单基线 {baseline} 已被其他变更单代替，当前版本 {current}，需重新核对后再确认")
            return entry, f"基线冲突：本单已被代替，转入待重新核对（当前版本 {current}）"
        if baseline != current:
            self._mark_pending_recheck(
                entry, current,
                f"基线 {baseline} 与当前版本 {current} 不一致，等待重新核对")
            return entry, f"基线冲突：当前版本 {current} 与基线 {baseline} 不一致，已转入待重新核对"
        # 幂等：本单已写过已生效快照则复用，不重复写入版本记录
        existing = next((s for s in versioning.snapshots_by_order(str(entry.get("变更单号", "")))
                         if s.get("版本状态") == "已生效"), None)
        if existing is not None:
            version = str(existing.get("版本号", ""))
            definition = deepcopy(existing.get("快照定义") or {})
        else:
            version = versioning.next_version(current)
            definition = deepcopy(entry.get("候选定义") or versioning.definition_of(entity))
            versioning.new_snapshot(
                entity_code=str(entity.get("实体编码", "")),
                version=version,
                baseline=baseline,
                order_no=str(entry.get("变更单号", "")),
                order_id=int(entry.get("id", 0)),
                definition=definition,
                status="已生效",
                basis=f"审批单 {entry.get('变更单号')} 于 {versioning.now_iso()} 确认生效",
            )
            versioning.supersede_candidates(
                str(entity.get("实体编码", "")), baseline,
                str(entry.get("变更单号", "")), version)
        # 回写实体：只采用本单候选定义，不混入其他未确认单的字段
        for field in versioning.DEFINITION_FIELDS:
            if field in definition:
                entity[field] = definition[field]
        entity["版本号"] = version
        entity["status"] = "已发布"
        entry["status"] = "已生效"
        entry["审批状态"] = "已生效"
        entry["生效版本"] = version
        entry["pending"] = False
        entry["abnormal"] = False
        entry["回执"] = {
            "确认流水": entry.get("确认流水", ""),
            "结果": "已生效",
            "采用版本": version,
            "采用定义": definition,
            "说明": f"审批通过，版本 {version} 已生效",
            "时间": versioning.now_iso(),
        }
        return entry, f"变更单已生效，实体版本更新为 {version}"

    def _reject(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """驳回变更：候选快照作废为已驳回，保留可查。"""
        if entry.get("status") not in ("待审批", "待重新核对"):
            return None, f"只有待审批或待重新核对的变更单能驳回（当前：{entry.get('status')}）"
        entry["status"] = "已驳回"
        entry["审批状态"] = "已驳回"
        entry["pending"] = False
        entry["abnormal"] = True
        for snap in versioning.snapshots_by_order(str(entry.get("变更单号", ""))):
            if snap.get("版本状态") == "候选":
                snap["版本状态"] = "已驳回"
                snap["status"] = "已驳回"
                snap["pending"] = False
                snap["abnormal"] = True
        entry["回执"] = {
            "确认流水": entry.get("确认流水", ""),
            "结果": "已驳回",
            "说明": "审批驳回，候选版本已作废，快照保留可查",
            "时间": versioning.now_iso(),
        }
        return entry, "变更单已驳回，候选快照保留可查"

    def _recheck(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """重新核对：基线对齐当前版本，旧候选快照作废，登记新候选快照。"""
        if entry.get("status") != "待重新核对":
            return None, f"只有待重新核对的变更单能重新核对（当前：{entry.get('status')}）"
        entity = versioning.entity_of(str(entry.get("实体编码", "")))
        if entity is None:
            return None, f"实体 {entry.get('实体编码')} 不存在"
        current = str(entity.get("版本号", ""))
        for snap in versioning.snapshots_by_order(str(entry.get("变更单号", ""))):
            if snap.get("版本状态") == "候选":
                snap["版本状态"] = "已代替"
                snap["status"] = "已代替"
                snap["pending"] = False
                snap["abnormal"] = True
        entry["基线版本"] = current
        candidate_version = versioning.next_version(current)
        versioning.new_snapshot(
            entity_code=str(entity.get("实体编码", "")),
            version=candidate_version,
            baseline=current,
            order_no=str(entry.get("变更单号", "")),
            order_id=int(entry.get("id", 0)),
            definition=entry.get("候选定义") or versioning.definition_of(entity),
            status="候选",
            basis="",
        )
        entry["status"] = "待审批"
        entry["审批状态"] = "待审批"
        entry["pending"] = True
        entry["abnormal"] = False
        entry["回执"] = {
            "确认流水": entry.get("确认流水", ""),
            "结果": "已重新核对",
            "当前版本": current,
            "说明": f"基线已更新为 {current}，候选版本 {candidate_version} 重新待审",
            "时间": versioning.now_iso(),
        }
        return entry, f"已按当前版本 {current} 重新核对，候选版本 {candidate_version} 等待确认"

    def _restore(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """恢复查证：已驳回/已代替单据恢复为起草中，历史快照保留可查。"""
        if entry.get("status") not in ("已驳回", "已代替"):
            return None, f"只有已驳回或已代替的变更单能恢复查证（当前：{entry.get('status')}）"
        entry["status"] = "起草中"
        entry["审批状态"] = "起草中"
        entry["pending"] = True
        entry["abnormal"] = False
        entry["回执"] = {
            "确认流水": entry.get("确认流水", ""),
            "结果": "恢复查证",
            "说明": "已恢复为起草中，历史快照保留可查，需重新提交审批后才能生效",
            "时间": versioning.now_iso(),
        }
        return entry, "变更单已恢复查证，需重新提交审批"

    def _mark_pending_recheck(self, entry: dict[str, Any], current: str, note: str) -> None:
        entry["status"] = "待重新核对"
        entry["审批状态"] = "待重新核对"
        entry["pending"] = True
        entry["回执"] = {
            "确认流水": entry.get("确认流水", ""),
            "结果": "等待重新核对",
            "当前版本": current,
            "说明": note,
            "时间": versioning.now_iso(),
        }

    # ---- 业务扩展：跨模块联动 ----

    def submit_for_approval(self, entry_id: int) -> dict[str, Any]:
        """提交审批（脚本侧入口）：走与动作一致的提交逻辑。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "变更单不存在"}
        updated, message = self._submit(entry)
        return {"ok": updated is not None, "message": message,
                "entity": entry.get("实体编码", "")}

    def apply_effective_version(self, entry_id: int) -> dict[str, Any]:
        """生效变更（脚本侧入口）：走与动作一致的确认逻辑。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "变更单不存在"}
        updated, message = self._confirm(entry)
        return {"ok": updated is not None, "message": message,
                "version": entry.get("生效版本", "")}

    def reject_with_reason(self, entry_id: int, reason: str) -> str:
        """驳回变更并记录驳回原因。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return "变更单不存在"
        _, message = self._reject(entry)
        entry["驳回原因"] = reason
        return f"{message}: {reason}" if reason else message

    def consume_entity_versions(self, entry_id: int) -> list[str]:
        """读取实体的历史版本序列（含候选与作废快照）。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return []
        code = str(entry.get("实体编码", ""))
        return [str(snap.get("版本号", "")) for snap in versioning.snapshots_for(code)]

    def notify_version_change(self, entry_id: int) -> list[str]:
        """版本生效后通知全部订阅方刷新口径。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已生效":
            return []
        entity_code = entry.get("实体编码", "")
        notified: list[str] = []
        for sub in store.rows("subscriber_mgr"):
            if entity_code in str(sub.get("订阅实体", "")):
                sub["pending"] = True
                notified.append(sub.get("订阅方标识", ""))
        return notified

    def register_change_lineage(self, entry_id: int) -> str | None:
        """登记变更单到实体模型血缘边。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        edges = store.rows("lineage_graph")
        edge_id = max((int(r.get("id", 0)) for r in edges), default=0) + 1
        edges.append({
            "id": edge_id,
            "血缘边标识": f"edge-change-{edge_id}",
            "上游节点": entry.get("变更单号", ""),
            "下游节点": entry.get("实体编码", ""),
            "变换规则": "变更生效",
            "登记时间": datetime.now(timezone.utc).isoformat(),
            "status": "已登记",
            "pending": False,
            "abnormal": False,
        })
        return f"edge-change-{edge_id}"
