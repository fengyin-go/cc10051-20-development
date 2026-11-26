"""实体变更审批版本历史场景验证：对照需求逐条核对服务端行为。

运行前提：后端已在 127.0.0.1:8021 监听。
用法：.venv/bin/python tests/scenario_versioning.py
"""
from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8021"
PASSED: list[str] = []
FAILED: list[str] = []


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(f"{name} {detail}")
    print(f"{'✔' if cond else '✘'} {name} {detail}")


def action(module: str, entry_id: int, act: str) -> dict:
    return call("POST", f"/api/{module}/{entry_id}/actions", {"action": act})


def create_change(order_no: str, entity: str, content: str) -> dict:
    return call("POST", "/api/model_change",
                {"values": {"变更单号": order_no, "实体编码": entity, "变更内容": content,
                            "审批状态": "起草中", "生效版本": ""}})


def main() -> None:
    # ---------- 准备：两张都基于 v2 的变更单，候选定义各不相同 ----------
    entity = call("GET", "/api/entity_model/1")
    check("前置：实体当前版本为 v2", entity["版本号"] == "v2", f"实际 {entity['版本号']}")

    a = create_change("MC-SCENE-A", "ENTI-0001", "唯一键规则增加来源系统")["entry"]
    b = create_change("MC-SCENE-B", "ENTI-0001", "合并策略改人工裁决")["entry"]
    check("变更单登记即锁定基线版本", a["基线版本"] == "v2" and b["基线版本"] == "v2")
    check("变更单登记即携带候选定义", bool(a["候选定义"]) and bool(b["候选定义"]))

    call("POST", f"/api/model_change/{a['id']}/candidate",
         {"values": {"唯一键规则": "证件类型+证件号码+来源系统"}})
    call("POST", f"/api/model_change/{b['id']}/candidate",
         {"values": {"合并策略": "人工裁决"}})

    ra = action("model_change", a["id"], "提交审批")
    rb = action("model_change", b["id"], "提交审批")
    check("两单提交审批后均为待审批",
          ra["entry"]["status"] == "待审批" and rb["entry"]["status"] == "待审批")

    # ---------- 第一张先获准生效 ----------
    ra = action("model_change", a["id"], "生效变更")
    check("第一张确认生效", ra["ok"] and ra["entry"]["status"] == "已生效")
    check("第一张生效版本为 v3", ra["entry"]["生效版本"] == "v3")
    entity = call("GET", "/api/entity_model/1")
    check("实体版本推进到 v3", entity["版本号"] == "v3")
    check("实体定义只采用第一单候选（唯一键规则）",
          entity["唯一键规则"] == "证件类型+证件号码+来源系统", entity["唯一键规则"])
    check("实体定义未混入第二单未确认字段（合并策略）",
          entity["合并策略"] == "最新优先", entity["合并策略"])
    check("第二单被标记为已代替", rb["entry"] and
          call("GET", f"/api/model_change/{b['id']}")["status"] == "已代替")

    # ---------- 第二张回执迟到，继续办理其生效操作 ----------
    rb2 = action("model_change", b["id"], "生效变更")
    b_now = call("GET", f"/api/model_change/{b['id']}")
    check("第二单转入待重新核对而非自行生效", b_now["status"] == "待重新核对")
    receipt = call("GET", f"/api/model_change/{b['id']}/receipt")
    check("第二单回执记录基线冲突", receipt["回执"]["结果"] == "等待重新核对",
          receipt["回执"]["说明"])
    check("回执给出当前新版本", receipt["回执"]["当前版本"] == "v3")
    entity = call("GET", "/api/entity_model/1")
    check("冲突期间实体未被第二单污染", entity["版本号"] == "v3"
          and entity["合并策略"] == "最新优先")

    # ---------- 重新核对后第二单得到更新后的版本 ----------
    rb3 = action("model_change", b["id"], "重新核对")
    check("重新核对后回到待审批", rb3["entry"]["status"] == "待审批")
    check("重新核对后基线对齐 v3", rb3["entry"]["基线版本"] == "v3")
    rb4 = action("model_change", b["id"], "生效变更")
    check("第二单核对后生效为 v4", rb4["entry"]["生效版本"] == "v4")
    entity = call("GET", "/api/entity_model/1")
    check("实体推进到 v4 且采用第二单定义",
          entity["版本号"] == "v4" and entity["合并策略"] == "人工裁决")

    # ---------- 两单办完后 v2 快照仍可查询 ----------
    versions = call("GET", "/api/entity_model/1/versions")
    v2 = call("GET", "/api/entity_model/1/versions/v2")
    check("v2 快照仍可查询且带生效依据", v2["版本状态"] == "已生效"
          and "MC-20260901-001" in v2["生效依据"])
    check("版本历史完整（v1..v4）",
          [s["版本号"] for s in versions["items"] if s["版本状态"] == "已生效"]
          == ["v1", "v2", "v3", "v4"])
    check("版本历史标注当前可领用版本", versions["当前版本"] == "v4")

    # ---------- 同一变更重复确认只写一份版本记录 ----------
    again = action("model_change", a["id"], "生效变更")
    snaps_a = [s for s in call("GET", "/api/entity_model/1/versions")["items"]
               if s["来源变更单"] == "MC-SCENE-A" and s["版本状态"] == "已生效"]
    check("重复确认返回原版本记录", "重复确认" in again["message"])
    check("重复确认只写入一份版本记录", len(snaps_a) == 1 and snaps_a[0]["版本号"] == "v3")
    receipt_a = call("GET", f"/api/model_change/{a['id']}/receipt")
    check("按原确认刷新取回实际采用的定义",
          receipt_a["实际采用定义"]["唯一键规则"] == "证件类型+证件号码+来源系统")

    # ---------- 审批页回看旧批准单：历史内容与当前可领用状态分开 ----------
    view = call("GET", f"/api/model_change/{a['id']}/version_view")
    check("回看旧批准单可见关联定义", view["关联快照"]["版本号"] == "v3"
          and view["关联定义"]["唯一键规则"] == "证件类型+证件号码+来源系统")
    check("回看可见该结构曾经的生效依据", "MC-SCENE-A" in view["关联快照"]["生效依据"])
    check("当前可领用状态与历史内容分别呈现",
          view["当前生效版本"]["版本号"] == "v4" and view["关联快照"]["版本号"] == "v3")

    # ---------- 从主数据实体页按版本发起办理 ----------
    claim = call("POST", "/api/entity_model/1/versions/v2/claim")
    check("按版本 v2 领用成功", claim["ok"] and claim["entry"]["基线版本"] == "v2")
    check("领用单携带 v2 快照定义",
          claim["entry"]["候选定义"]["唯一键规则"] == "证件类型+证件号码")
    bad_claim = call("POST", "/api/entity_model/1/versions/v9/claim")
    check("不存在版本不可领用", not bad_claim["ok"])

    # ---------- 驳回/被代替可恢复查证，不能自行生效 ----------
    d = create_change("MC-SCENE-D", "ENTI-0001", "尝试驳回后恢复")["entry"]
    action("model_change", d["id"], "提交审批")
    action("model_change", d["id"], "驳回变更")
    d_now = call("GET", f"/api/model_change/{d['id']}")
    check("驳回后状态为已驳回", d_now["status"] == "已驳回")
    denied = action("model_change", d["id"], "生效变更")
    check("已驳回不能自行切换成已生效", not denied["ok"]
          and call("GET", f"/api/model_change/{d['id']}")["status"] == "已驳回")
    restored = action("model_change", d["id"], "恢复查证")
    check("已驳回可恢复查证", restored["ok"] and restored["entry"]["status"] == "起草中")
    snaps_d = call("GET", f"/api/model_change/{d['id']}/receipt")["关联快照"]
    check("驳回的候选快照保留可查", any(s["版本状态"] == "已驳回" for s in snaps_d))

    # ---------- 实体发布入口：快照与审批单关联 ----------
    pub = action("entity_model", 2, "发布实体")
    check("实体发布入口生效", pub["ok"] and pub["entry"]["版本号"] == "v1")
    versions2 = call("GET", "/api/entity_model/2/versions")
    snap_v1 = next((s for s in versions2["items"] if s["版本号"] == "v1"), None)
    check("发布写入版本快照并关联审批单",
          snap_v1 is not None and snap_v1["来源变更单"].startswith("MC-2-"))
    order_id = snap_v1["变更单ID"]
    view2 = call("GET", f"/api/model_change/{order_id}/version_view")
    check("审批回看能查到该结构曾经的状态和生效依据",
          view2["关联快照"]["版本状态"] == "已生效" and "实体发布入口" in view2["关联快照"]["生效依据"])

    print(f"\n通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败明细：")
        for item in FAILED:
            print(" -", item)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
