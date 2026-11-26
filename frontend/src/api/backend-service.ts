import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  ActionResult,
  ChangeReceiptView,
  ChangeVersionView,
  EntityVersionList,
  EntryRow,
  OverviewResult,
  PageResult,
} from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

/** 实体页版本历史：服务端返回带生效依据的版本快照与当前可领用版本。 */
export async function listEntityVersions(entityId: number): Promise<EntityVersionList> {
  const response = await request(`/api/entity_model/${entityId}/versions`)
  if (!response.ok) throw new Error('版本历史读取失败')
  return await response.json()
}

/** 按版本发起办理：领用已生效快照，生成以其为基线的变更单。 */
export async function claimEntityVersion(
  entityId: number,
  version: string,
): Promise<ActionResult> {
  const response = await request(`/api/entity_model/${entityId}/versions/${version}/claim`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
  return await response.json()
}

/** 审批页回看：本单关联定义（历史内容）与当前可领用状态分开返回。 */
export async function loadChangeVersionView(changeId: number): Promise<ChangeVersionView> {
  const response = await request(`/api/model_change/${changeId}/version_view`)
  if (!response.ok) throw new Error('变更单版本视图读取失败')
  return await response.json()
}

/** 按原确认取回执：返回该单实际采用的定义。 */
export async function loadChangeReceipt(changeId: number): Promise<ChangeReceiptView> {
  const response = await request(`/api/model_change/${changeId}/receipt`)
  if (!response.ok) throw new Error('变更单回执读取失败')
  return await response.json()
}

/** 更新变更单候选定义。 */
export async function saveChangeCandidate(
  changeId: number,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/model_change/${changeId}/candidate`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}
