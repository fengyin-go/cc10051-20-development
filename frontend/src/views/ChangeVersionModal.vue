<template>
  <div class="modal-backdrop" data-testid="change-version-modal" @click.self="emit('close')">
    <div class="modal version-modal">
      <h3>变更单版本视图 — {{ order.变更单号 }}</h3>
      <p v-if="message" class="error-text" data-testid="version-view-message">{{ message }}</p>
      <template v-if="view">
        <section class="version-block">
          <h4>单据状态</h4>
          <dl class="def-grid">
            <dt>实体编码</dt>
            <dd>{{ view.变更单.实体编码 }}</dd>
            <dt>审批状态</dt>
            <dd>
              <span class="badge" :class="`badge-${view.变更单.status}`">{{ view.变更单.status }}</span>
            </dd>
            <dt>基线版本</dt>
            <dd>{{ view.变更单.基线版本 || '—' }}</dd>
            <dt>生效版本</dt>
            <dd>{{ view.变更单.生效版本 || '—' }}</dd>
            <dt>变更内容</dt>
            <dd>{{ view.变更单.变更内容 }}</dd>
            <dt>确认流水</dt>
            <dd>{{ view.变更单.确认流水 || '—' }}</dd>
          </dl>
        </section>

        <section class="version-block" data-testid="linked-definition">
          <h4>本单关联定义（历史内容）</h4>
          <p v-if="view.关联快照" class="muted">
            快照 #{{ view.关联快照.id }} · 版本 {{ view.关联快照.版本号 }} ·
            状态 {{ view.关联快照.版本状态 }}
          </p>
          <p v-if="view.关联快照?.生效依据" class="muted" data-testid="linked-basis">
            生效依据：{{ view.关联快照.生效依据 }}
          </p>
          <dl class="def-grid">
            <template v-for="(value, key) in view.关联定义 ?? {}" :key="key">
              <dt>{{ key }}</dt>
              <dd>{{ value }}</dd>
            </template>
          </dl>
        </section>

        <section v-if="view.回执" class="version-block" data-testid="receipt-block">
          <h4>确认回执</h4>
          <dl class="def-grid">
            <dt>结果</dt>
            <dd>{{ view.回执.结果 }}</dd>
            <dt>采用版本</dt>
            <dd>{{ view.回执.采用版本 || '—' }}</dd>
            <dt>说明</dt>
            <dd>{{ view.回执.说明 }}</dd>
            <dt>时间</dt>
            <dd>{{ view.回执.时间 }}</dd>
          </dl>
        </section>

        <section class="version-block" data-testid="claimable-block">
          <h4>当前可领用状态</h4>
          <p>
            当前生效版本：
            <strong data-testid="current-effective">{{ view.当前生效版本?.版本号 ?? '—' }}</strong>
          </p>
          <ul class="claimable-list">
            <li v-for="item in view.可领用版本" :key="item.id">
              {{ item.版本号 }}（{{ item.生效依据 || '初始发布' }}）
            </li>
          </ul>
        </section>

        <section v-if="editable" class="version-block">
          <h4>候选定义（本单拟采用）</h4>
          <label v-for="field in definitionFields" :key="field" class="create-field">
            <span>{{ field }}</span>
            <input v-model="candidateForm[field]" :data-testid="`candidate-${field}`" />
          </label>
          <button class="btn" type="button" data-testid="save-candidate" @click="saveCandidate">
            保存候选定义
          </button>
        </section>
      </template>

      <div class="page-actions">
        <button
          v-if="canConfirm"
          class="btn primary"
          type="button"
          data-testid="modal-confirm"
          @click="doAction('生效变更')"
        >
          确认生效
        </button>
        <button
          v-if="view?.变更单.status === '待重新核对'"
          class="btn"
          type="button"
          data-testid="modal-recheck"
          @click="doAction('重新核对')"
        >
          重新核对
        </button>
        <button
          v-if="restorable"
          class="btn"
          type="button"
          data-testid="modal-restore"
          @click="doAction('恢复查证')"
        >
          恢复查证
        </button>
        <button class="btn ghost" type="button" data-testid="goto-entity" @click="goEntity">
          前往实体页版本历史
        </button>
        <button class="btn" type="button" @click="emit('close')">关闭</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  loadChangeVersionView,
  runAction,
  saveChangeCandidate,
} from '@/api/backend-service'
import type { ChangeVersionView, EntryRow } from '@/data/types'

const props = defineProps<{ order: EntryRow }>()
const emit = defineEmits<{
  close: []
  changed: []
}>()

const router = useRouter()
const view = ref<ChangeVersionView | null>(null)
const message = ref('')
const definitionFields = ['实体名称', '唯一键规则', '合并策略']
const candidateForm = ref<Record<string, string>>({})

const editable = computed(() =>
  ['起草中', '待审批', '待重新核对'].includes(String(view.value?.变更单.status)),
)
const canConfirm = computed(() =>
  ['待审批', '待重新核对', '已代替'].includes(String(view.value?.变更单.status)),
)
const restorable = computed(() =>
  ['已驳回', '已代替'].includes(String(view.value?.变更单.status)),
)

async function refresh() {
  view.value = await loadChangeVersionView(Number(props.order.id))
  const candidate = (view.value.变更单['候选定义'] ?? {}) as unknown as Record<string, string>
  candidateForm.value = { ...candidate }
}

async function doAction(action: string) {
  message.value = ''
  try {
    const result = await runAction('model_change', Number(props.order.id), action)
    message.value = result.message
    await refresh()
    emit('changed')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function saveCandidate() {
  message.value = ''
  try {
    const result = await saveChangeCandidate(Number(props.order.id), candidateForm.value)
    if (!result.ok) throw new Error(result.message)
    message.value = result.message
    await refresh()
    emit('changed')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '候选定义保存失败'
  }
}

function goEntity() {
  emit('close')
  void router.push({
    path: '/entity_model',
    query: { versions: String(view.value?.变更单.实体编码 ?? props.order.实体编码) },
  })
}

onMounted(async () => {
  try {
    await refresh()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '版本视图读取失败'
  }
})
</script>
