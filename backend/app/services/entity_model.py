"""主数据实体领域服务：管理实体定义的唯一键规则、合并策略、版本发布与废弃。

数据链路位置：主数据模型层，负责定义合并策略并向合并任务、清洗规则
派发生成规则，是金记录链路的规则来源。

发布约定：发布实体时把实际采用的版本快照与审批单关联后写入版本历史，
供应下游查询可用结构；历史快照保留生效依据，供变更审批回看。
"""
from __future__ import annotations

from typing import Any

from app.services import versioning
from app.services.base import BaseModuleService
from app.store import store


class EntityModelService(BaseModuleService):
    MODULE = "entity_model"
    ENTITY = "实体定义"
    OPERATION_TERM = "合并"
    LIST_FIELDS = ["实体编码", "实体名称", "唯一键规则", "合并策略", "版本号"]
    REQUIRED_FIELDS = ["实体编码", "实体名称", "唯一键规则"]
    STATUS_ORDER = ["草稿", "已发布", "已废弃"]
    ACTION_RULES = {"发布实体": "已发布", "废弃实体": "已废弃"}
    NEGATIVE_ACTIONS = []

    # ---- 动作分派：发布/废弃走领域逻辑，保证版本历史一致 ----

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if action == "发布实体":
            result = self.publish_with_version(entry_id)
            if not result.get("ok"):
                return None, str(result.get("message", "发布失败"))
            return entry, f"实体定义已发布，生效版本 {result['version']}，审批单 {result['change_no']}"
        if action == "废弃实体":
            message = self.archive_deprecated(entry_id)
            return entry, message
        return None, f"动作「{action}」不属于{self.MODULE}可执行范围"

    # ---- 业务扩展：实体发布与合并策略联动 ----

    def publish_with_version(self, entry_id: int) -> dict[str, Any]:
        """发布实体定义并递增版本号，同步生成已生效变更单与版本快照。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "实体定义不存在"}
        if entry.get("status") == "已废弃":
            return {"ok": False, "message": "已废弃实体不能发布"}
        old_ver = str(entry.get("版本号", "v0"))
        new_ver = versioning.next_version(old_ver)
        definition = versioning.definition_of(entry)
        entity_code = str(entry.get("实体编码", ""))
        changes = store.rows("model_change")
        change_id = max((int(r.get("id", 0)) for r in changes), default=0) + 1
        order_no = f"MC-{entry_id}-{change_id}"
        basis = f"审批单 {order_no} 于 {versioning.now_iso()} 确认生效（实体发布入口）"
        # 实际采用的版本快照与审批单关联后写入版本历史，供应可用结构
        versioning.new_snapshot(
            entity_code=entity_code,
            version=new_ver,
            baseline=old_ver,
            order_no=order_no,
            order_id=change_id,
            definition=definition,
            status="已生效",
            basis=basis,
        )
        versioning.supersede_candidates(entity_code, old_ver, order_no, new_ver)
        entry["版本号"] = new_ver
        entry["status"] = "已发布"
        changes.append({
            "id": change_id,
            "变更单号": order_no,
            "实体编码": entity_code,
            "变更内容": f"发布版本 {new_ver}",
            "审批状态": "已生效",
            "生效版本": new_ver,
            "基线版本": old_ver,
            "候选定义": dict(definition),
            "确认流水": f"CF-{order_no}",
            "回执": {
                "确认流水": f"CF-{order_no}",
                "结果": "已生效",
                "采用版本": new_ver,
                "采用定义": dict(definition),
                "说明": f"实体发布入口确认，版本 {new_ver} 已生效",
                "时间": versioning.now_iso(),
            },
            "status": "已生效",
            "pending": False,
            "abnormal": False,
        })
        return {"ok": True, "version": new_ver, "change_id": change_id, "change_no": order_no}

    def spawn_merge_tasks(self, entry_id: int, candidate_groups: list[str]) -> list[int]:
        """按实体合并策略为候选组生成合并任务。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已发布":
            return []
        tasks = store.rows("golden_merge")
        created: list[int] = []
        for group in candidate_groups:
            task_id = max((int(r.get("id", 0)) for r in tasks), default=0) + 1
            tasks.append({
                "id": task_id,
                "合并任务": f"merge-{entry.get('实体编码')}-{task_id}",
                "实体编码": entry.get("实体编码", ""),
                "候选组": group,
                "生还规则": entry.get("合并策略", "最新优先"),
                "合并结果": "",
                "status": "待合并",
                "pending": True,
                "abnormal": False,
            })
            created.append(task_id)
        return created

    def bind_cleanse_rules(self, entry_id: int, stages: list[str]) -> int:
        """为实体绑定标准化清洗规则，写入 std_cleanse。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return 0
        rules = store.rows("std_cleanse")
        count = 0
        for stage in stages:
            rule_id = max((int(r.get("id", 0)) for r in rules), default=0) + 1
            rules.append({
                "id": rule_id,
                "规则名称": f"cleanse-{entry.get('实体编码')}-{stage}",
                "实体编码": entry.get("实体编码", ""),
                "清洗阶段": stage,
                "规则表达式": "trim+upper",
                "异常处理": "转人工",
                "status": "草稿",
                "pending": True,
                "abnormal": False,
            })
            count += 1
        return count

    def consume_merge_results(self, entry_id: int) -> list[dict[str, Any]]:
        """读取合并任务产物，统计已完成合并数。"""
        code = (store.find(self.MODULE, entry_id) or {}).get("实体编码", "")
        return [r for r in store.rows("golden_merge")
                if r.get("实体编码") == code and r.get("status") == "已合并"]

    def request_change_approval(self, entry_id: int, content: str) -> str:
        """为实体发起模型变更审批单。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return "实体定义不存在"
        changes = store.rows("model_change")
        change_id = max((int(r.get("id", 0)) for r in changes), default=0) + 1
        order_no = f"MC-{entry_id}-{change_id}"
        changes.append({
            "id": change_id,
            "变更单号": order_no,
            "实体编码": entry.get("实体编码", ""),
            "变更内容": content,
            "审批状态": "待审批",
            "生效版本": "",
            "基线版本": entry.get("版本号", ""),
            "候选定义": versioning.definition_of(entry),
            "确认流水": f"CF-{order_no}",
            "回执": None,
            "status": "待审批",
            "pending": True,
            "abnormal": False,
        })
        return order_no

    def archive_deprecated(self, entry_id: int) -> str:
        """废弃实体并停止其清洗规则。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return "实体定义不存在"
        entry["status"] = "已废弃"
        for rule in store.rows("std_cleanse"):
            if rule.get("实体编码") == entry.get("实体编码") and rule.get("status") == "已启用":
                rule["status"] = "已停用"
                rule["abnormal"] = True
        return f"实体 {entry.get('实体编码')} 已废弃，关联清洗规则已停用"
