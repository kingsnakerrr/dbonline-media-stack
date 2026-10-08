<script setup>
import { computed, onMounted, ref } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
})

const loading = ref(false)
const error = ref('')
const message = ref('')
const dialog = ref('')
const queueSearch = ref('')
const historySearch = ref('')
const suppressedSearch = ref('')
const pageSizes = [20, 50, 100]
const state = ref({
  summary: {}, queue: [], history: [], suppressed: [],
  telegram: { source: '', admins_override: '', chat_id_override: '', sources: [] },
  disk_guard: { enabled: true, active: false, free_gb: 0, threshold_gb: 300, recover_gb: 350, waiting: [] },
})
const telegramForm = ref({ source: '', admins_override: '', chat_id_override: '' })
const diskForm = ref({ disk_guard_enabled: true, disk_guard_path: '/home', disk_guard_threshold_gb: 300, disk_guard_recover_gb: 350 })

const unwrap = response => response?.data?.data ?? response?.data ?? response
const envelope = response => (response?.success !== undefined ? response : (response?.data ?? response))

function applyState(data) {
  if (!data) return
  state.value = data
  telegramForm.value = {
    source: data.telegram?.source || '',
    admins_override: data.telegram?.admins_override || '',
    chat_id_override: data.telegram?.chat_id_override || '',
  }
  diskForm.value = {
    disk_guard_enabled: data.disk_guard?.enabled !== false,
    disk_guard_path: data.disk_guard?.path || '/home',
    disk_guard_threshold_gb: data.disk_guard?.threshold_gb || 300,
    disk_guard_recover_gb: data.disk_guard?.recover_gb || 350,
  }
}

async function loadStatus() {
  loading.value = true
  error.value = ''
  try {
    applyState(unwrap(await props.api.get('plugin/SmartMoviePush/ui_status')))
  } catch (err) {
    error.value = err?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function runAction(action, extra = {}) {
  loading.value = true
  error.value = ''
  message.value = ''
  try {
    const response = await props.api.post('plugin/SmartMoviePush/ui_action', { action, ...extra })
    const body = envelope(response)
    message.value = body?.message || '操作完成'
    applyState(body?.data)
  } catch (err) {
    error.value = err?.message || '操作失败'
  } finally {
    loading.value = false
  }
}

async function saveTelegram() {
  loading.value = true
  error.value = ''
  message.value = ''
  try {
    const response = await props.api.post('plugin/SmartMoviePush/ui_config', telegramForm.value)
    const body = envelope(response)
    message.value = body?.message || 'Telegram 设置已保存'
    applyState(body?.data)
  } catch (err) {
    error.value = err?.message || '保存失败'
  } finally {
    loading.value = false
  }
}

async function saveDiskGuard() {
  loading.value = true
  error.value = ''
  message.value = ''
  try {
    const response = await props.api.post('plugin/SmartMoviePush/ui_config', diskForm.value)
    const body = envelope(response)
    message.value = body?.message || '硬盘保护设置已保存'
    applyState(body?.data)
  } catch (err) {
    error.value = err?.message || '保存失败'
  } finally {
    loading.value = false
  }
}

const summary = computed(() => state.value.summary || {})
const diskGuard = computed(() => state.value.disk_guard || {})
const queueHeaders = [
  { title: '影片', key: 'title' },
  { title: '加入时间', key: 'created_at', width: 180 },
  { title: '重试', key: 'attempts', width: 80 },
  { title: '操作', key: 'actions', sortable: false, width: 120 },
]
const historyHeaders = [
  { title: '影片', key: 'title' },
  { title: '提交时间', key: 'submitted_at', width: 190 },
]
const suppressedHeaders = [
  { title: '影片', key: 'title' },
  { title: '加入时间', key: 'added_at', width: 190 },
  { title: '操作', key: 'actions', sortable: false, width: 120 },
]
const diskHeaders = [
  { title: '种子', key: 'title' },
  { title: '分类', key: 'category', width: 130 },
  { title: '暂停时间', key: 'added_at', width: 190 },
]

onMounted(loadStatus)
</script>

<template>
  <VContainer fluid class="pa-2">
    <VAlert v-if="error" type="error" variant="tonal" class="mb-3" closable>{{ error }}</VAlert>
    <VAlert v-if="message" type="success" variant="tonal" class="mb-3" closable>{{ message }}</VAlert>

    <VRow dense class="mb-3">
      <VCol cols="12" md="3"><VCard variant="tonal" color="success" class="pa-4 h-100"><div class="text-caption">插件状态</div><div class="text-h6 font-weight-bold">{{ summary.enabled ? '已启用' : '已关闭' }}</div></VCard></VCol>
      <VCol cols="12" md="3"><VCard variant="tonal" color="primary" class="pa-4 h-100"><div class="text-caption">定时推送</div><div class="text-h6 font-weight-bold">{{ summary.auto_push ? summary.cron : '已暂停' }}</div></VCard></VCol>
      <VCol cols="12" md="3"><VCard variant="tonal" color="warning" class="pa-4 h-100"><div class="text-caption">下载模式</div><div class="text-h6 font-weight-bold">{{ summary.auto_download ? '自动下载' : '手动确认' }}</div></VCard></VCol>
      <VCol cols="12" md="3"><VCard variant="tonal" color="info" class="pa-4 h-100"><div class="text-caption">正在下载</div><div class="text-h6 font-weight-bold">{{ summary.active_downloads || 0 }}/{{ summary.max_active_downloads || 20 }}</div></VCard></VCol>
    </VRow>

    <VCard variant="outlined" class="pa-4 mb-4">
      <div class="text-h6 mb-3">快捷控制</div>
      <VBtn class="mr-2 mb-2" variant="tonal" :loading="loading" @click="runAction('toggle_auto_push')">{{ summary.auto_push ? '暂停定时推送' : '开启定时推送' }}</VBtn>
      <VBtn class="mr-2 mb-2" variant="tonal" color="primary" :loading="loading" @click="runAction('toggle_download_mode')">{{ summary.auto_download ? '改为手动下载' : '改为自动下载' }}</VBtn>
      <VBtn class="mr-2 mb-2" variant="tonal" color="success" :loading="loading" @click="runAction('run_once')">立即试推送</VBtn>
      <VBtn class="mr-2 mb-2" variant="tonal" color="error" :loading="loading" @click="runAction('clear_cache')">清空扫描缓存</VBtn>
      <VBtn class="mb-2" variant="text" icon="mdi-refresh" :loading="loading" @click="loadStatus" />
    </VCard>

    <VCard variant="tonal" :color="diskGuard.active ? 'error' : 'success'" class="pa-4 mb-4">
      <div class="d-flex flex-wrap align-center justify-space-between ga-3 mb-3">
        <div>
          <div class="text-h6">硬盘空间保护</div>
          <div class="text-body-2 mt-1">
            {{ diskGuard.active ? '保护中：旧下载继续，新 JAV/MP 种子暂停等候' : '正常：允许添加新种子' }}
          </div>
        </div>
        <div class="text-right">
          <div class="text-h5 font-weight-bold">剩余 {{ diskGuard.free_gb ?? 0 }}G</div>
          <div class="text-caption">暂停等候 {{ diskGuard.waiting_count || 0 }} 个</div>
        </div>
      </div>
      <VRow dense>
        <VCol cols="12" md="3"><VSwitch v-model="diskForm.disk_guard_enabled" label="启用硬盘保护" color="success" hide-details /></VCol>
        <VCol cols="12" md="3"><VTextField v-model="diskForm.disk_guard_path" label="检测路径" density="compact" hide-details /></VCol>
        <VCol cols="6" md="3"><VTextField v-model.number="diskForm.disk_guard_threshold_gb" label="停止新增（G）" type="number" density="compact" hide-details /></VCol>
        <VCol cols="6" md="3"><VTextField v-model.number="diskForm.disk_guard_recover_gb" label="允许恢复（G）" type="number" density="compact" hide-details /></VCol>
      </VRow>
      <div class="mt-3 d-flex flex-wrap ga-2">
        <VBtn color="primary" variant="tonal" :loading="loading" @click="saveDiskGuard">保存设置</VBtn>
        <VBtn variant="tonal" :loading="loading" @click="runAction('disk_guard_check')">立即检查</VBtn>
        <VBtn v-if="diskGuard.active && !diskGuard.acked" color="warning" variant="tonal" :loading="loading" @click="runAction('disk_guard_ack', { incident_id: diskGuard.incident_id })">收到，停止提醒</VBtn>
        <VBtn v-if="diskGuard.active" color="success" variant="tonal" :loading="loading" @click="runAction('disk_guard_resume')">空间清理后恢复添加/下载</VBtn>
        <VBtn v-if="diskGuard.waiting_count" variant="text" @click="dialog = 'disk'">查看暂停种子</VBtn>
      </div>
      <div class="text-caption mt-3">
        {{ diskGuard.active && diskGuard.recovered ? `空间已达到 ${diskGuard.recover_gb}G 恢复线，请点击上面的恢复按钮。` : `低于 ${diskGuard.threshold_gb}G 启动保护；清理到 ${diskGuard.recover_gb}G 后由你手动恢复。` }}
      </div>
      <VAlert v-if="diskGuard.last_error" type="warning" variant="tonal" class="mt-3">{{ diskGuard.last_error }}</VAlert>
    </VCard>

    <VRow dense class="mb-4">
      <VCol cols="12" md="4">
        <VCard variant="outlined" class="pa-4 h-100 list-card" @click="dialog = 'queue'">
          <div class="d-flex align-center justify-space-between"><div class="text-h6">等候下载</div><VIcon icon="mdi-chevron-right" /></div>
          <div class="text-h4 mt-3">{{ state.queue.length }}</div><div class="text-caption mt-2">点击查看、搜索或取消任务</div>
        </VCard>
      </VCol>
      <VCol cols="12" md="4">
        <VCard variant="outlined" class="pa-4 h-100 list-card" @click="dialog = 'history'">
          <div class="d-flex align-center justify-space-between"><div class="text-h6">插件下载记录</div><VIcon icon="mdi-chevron-right" /></div>
          <div class="text-h4 mt-3">{{ state.history.length }}</div><div class="text-caption mt-2">点击查看和搜索，只读记录</div>
        </VCard>
      </VCol>
      <VCol cols="12" md="4">
        <VCard variant="outlined" class="pa-4 h-100 list-card" @click="dialog = 'suppressed'">
          <div class="d-flex align-center justify-space-between"><div class="text-h6">不再推送列表</div><VIcon icon="mdi-chevron-right" /></div>
          <div class="text-h4 mt-3">{{ state.suppressed.length }}</div><div class="text-caption mt-2">点击查看、搜索或取消排除</div>
        </VCard>
      </VCol>
    </VRow>

    <VCard variant="outlined" class="pa-4">
      <div class="text-h6 mb-1">Telegram 设置</div>
      <div class="text-caption text-medium-emphasis mb-3">留空即自动使用 MoviePilot 通知设置；也可选择其他已配置的 Telegram 实例并覆盖管理员或群组。</div>
      <VRow dense>
        <VCol cols="12" md="4"><VSelect v-model="telegramForm.source" :items="state.telegram.sources || []" item-title="title" item-value="value" label="Telegram 机器人" /></VCol>
        <VCol cols="12" md="4"><VTextField v-model="telegramForm.admins_override" label="管理员 ID/用户名（可选）" :placeholder="state.telegram.effective_admins || '跟随 MP'" /></VCol>
        <VCol cols="12" md="4"><VTextField v-model="telegramForm.chat_id_override" label="通知群组/频道 Chat ID（可选）" :placeholder="state.telegram.effective_chat_id || '跟随 MP'" /></VCol>
      </VRow>
      <VBtn color="primary" variant="tonal" :loading="loading" @click="saveTelegram">保存 Telegram 设置</VBtn>
    </VCard>

    <VDialog v-model="dialog" max-width="75rem" scrollable>
      <VCard v-if="dialog === 'queue'" title="等候下载">
        <VDialogCloseBtn @click="dialog = ''" />
        <VCardText>
          <div class="d-flex ga-2 mb-3"><VTextField v-model="queueSearch" label="搜索影片" prepend-inner-icon="mdi-magnify" clearable hide-details /><VBtn color="error" variant="tonal" @click="runAction('clear_queue')">批量清空</VBtn></div>
          <VDataTable :headers="queueHeaders" :items="state.queue" :search="queueSearch" :items-per-page="20" :items-per-page-options="pageSizes" item-value="key" density="compact" hover>
            <template #item.actions="{ item }"><VBtn size="small" color="error" variant="tonal" @click="runAction('remove_queue', { key: item.key })">取消下载</VBtn></template>
          </VDataTable>
        </VCardText>
      </VCard>
      <VCard v-else-if="dialog === 'history'" title="插件下载记录">
        <VDialogCloseBtn @click="dialog = ''" />
        <VCardText>
          <VTextField v-model="historySearch" label="搜索影片" prepend-inner-icon="mdi-magnify" clearable class="mb-3" hide-details />
          <VDataTable :headers="historyHeaders" :items="state.history" :search="historySearch" :items-per-page="20" :items-per-page-options="pageSizes" density="compact" hover />
        </VCardText>
      </VCard>
      <VCard v-else-if="dialog === 'suppressed'" title="不再推送列表">
        <VDialogCloseBtn @click="dialog = ''" />
        <VCardText>
          <div class="d-flex ga-2 mb-3"><VTextField v-model="suppressedSearch" label="搜索影片" prepend-inner-icon="mdi-magnify" clearable hide-details /><VBtn color="error" variant="tonal" @click="runAction('clear_suppressed')">批量取消</VBtn></div>
          <VDataTable :headers="suppressedHeaders" :items="state.suppressed" :search="suppressedSearch" :items-per-page="20" :items-per-page-options="pageSizes" item-value="tmdb_id" density="compact" hover>
            <template #item.actions="{ item }"><VBtn size="small" color="warning" variant="tonal" @click="runAction('remove_suppressed', { tmdb_id: item.tmdb_id })">取消排除</VBtn></template>
          </VDataTable>
        </VCardText>
      </VCard>
      <VCard v-else-if="dialog === 'disk'" title="硬盘保护暂停的 qB 种子">
        <VDialogCloseBtn @click="dialog = ''" />
        <VCardText>
          <VAlert type="info" variant="tonal" class="mb-3">这里的种子没有删除；空间清理到恢复线后，在硬盘保护卡片点击“恢复添加/下载”。</VAlert>
          <VDataTable :headers="diskHeaders" :items="diskGuard.waiting || []" :items-per-page="20" :items-per-page-options="pageSizes" density="compact" hover />
        </VCardText>
      </VCard>
    </VDialog>
  </VContainer>
</template>

<style scoped>
.list-card { cursor: pointer; transition: border-color .2s, transform .2s; }
.list-card:hover { border-color: rgb(var(--v-theme-primary)); transform: translateY(-2px); }
</style>
