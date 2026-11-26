<template>
  <div class="modal-backdrop" data-testid="entity-versions-modal" @click.self="emit('close')">
    <div class="modal version-modal">
      <h3>实体版本历史 — {{ data?.实体编码 ?? entity.实体编码 }}</h3>
      <p v-if="data" class="current-version" data-testid="current-claimable">
        当前可领用版本：<strong>{{ data.当前版本 }}</strong>
        <span class="muted">（{{ data.实体名称 }}，仅已生效版本可领用）</span>
      </p>

      <table class="data-table">
        <thead>
          <tr>
            <th>版本号</th>
            <th>版本状态</th>
            <th>基线版本</th>
            <th>来源变更单</th>
            <th>生效依据</th>
            <th>生效时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in data?.items ?? []" :key="item.id" :data-testid="`version-${item.版本号}-${item.版本状态}`">
            <td>{{ item.版本号 }}</td>
            <td>
              <span class="badge" :class="`badge-${item.版本状态}`">{{ item.版本状态 }}</span>
            </td>
            <td>{{ item.基线版本 }}</td>
            <td>{{ item.来源变更单 }}</td>
            <td>{{ item.生效依据 || '—' }}</td>
            <td>{{ item.生效时间 || '—' }}</td>
            <td class="row-actions">
              <button class="link" type="button" :data-testid="`view-def-${item.id}`" @click="toggleDef(item.id)">
                {{ expandedId === item.id ? '收起定义' : '查看定义' }}
              </button>
              <button
                v-if="item.版本状态 === '已生效'"
                class="link"
                type="button"
                :data-testid="`claim-${item.版本号}`"
                @click="claim(item.版本号)"
              >
                按版本发起办理
              </button>
            </td>
          </tr>
          <tr v-if="expanded">
            <td colspan="7" class="def-cell">
              <dl class="def-grid" data-testid="version-definition">
                <template v-for="(value, key) in expanded.快照定义" :key="key">
                  <dt>{{ key }}</dt>
                  <dd>{{ value }}</dd>
                </template>
              </dl>
            </td>
          </tr>
          <tr v-if="data && !data.items.length">
            <td colspan="7" class="empty-state">暂无版本快照</td>
          </tr>
        </tbody>
      </table>

      <p v-if="message" class="error-text" data-testid="versions-message">{{ message }}</p>
      <div class="page-actions">
        <button class="btn" type="button" @click="emit('close')">关闭</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { claimEntityVersion, listEntityVersions } from '@/api/backend-service'
import type { EntityVersionList, EntryRow, VersionSnapshot } from '@/data/types'

const props = defineProps<{ entity: EntryRow }>()
const emit = defineEmits<{
  close: []
  claimed: [order: EntryRow]
}>()

const data = ref<EntityVersionList | null>(null)
const expandedId = ref<number | null>(null)
const message = ref('')

const expanded = computed<VersionSnapshot | null>(
  () => data.value?.items.find((item) => item.id === expandedId.value) ?? null,
)

function toggleDef(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}

async function claim(version: string) {
  message.value = ''
  try {
    const result = await claimEntityVersion(Number(props.entity.id), version)
    if (!result.ok || !result.entry) throw new Error(result.message)
    emit('claimed', result.entry as EntryRow)
  } catch (error) {
    message.value = error instanceof Error ? error.message : '领用失败'
  }
}

onMounted(async () => {
  try {
    data.value = await listEntityVersions(Number(props.entity.id))
  } catch (error) {
    message.value = error instanceof Error ? error.message : '版本历史读取失败'
  }
})
</script>
