/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
  entry?: EntryRow | null
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

/** 实体版本快照：服务端返回的带生效依据的历史版本记录。 */
export type VersionSnapshot = {
  id: number
  实体编码: string
  版本号: string
  版本状态: string
  基线版本: string
  来源变更单: string
  变更单ID: number | null
  快照定义: Record<string, string>
  生效依据: string
  登记时间: string
  生效时间: string
  status: string
}

export type EntityVersionList = {
  实体编码: string
  实体名称: string
  当前版本: string
  items: VersionSnapshot[]
}

export type ChangeReceipt = {
  确认流水: string
  结果: string
  采用版本?: string
  采用定义?: Record<string, string>
  当前版本?: string
  说明: string
  时间: string
}

/** 审批页版本视图：本单历史内容与当前可领用状态分开呈现。 */
export type ChangeVersionView = {
  变更单: EntryRow
  关联快照: VersionSnapshot | null
  关联定义: Record<string, string> | null
  回执: ChangeReceipt | null
  实体: EntryRow | null
  当前生效版本: VersionSnapshot | null
  可领用版本: VersionSnapshot[]
}

export type ChangeReceiptView = {
  变更单号: string
  确认流水: string
  回执: ChangeReceipt | null
  实际采用定义: Record<string, string> | null
  关联快照: VersionSnapshot[]
}
