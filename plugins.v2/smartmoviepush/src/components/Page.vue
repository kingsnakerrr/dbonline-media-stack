<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
})

const loading = ref(false)
const error = ref('')
const message = ref('')
const accessReady = ref(false)
const accessPassword = ref('')
const accessToken = ref('')
const accessTokenKey = 'smartmoviepush_access_token'
const dialog = ref('')
const dialogOpen = computed({
  get: () => Boolean(dialog.value),
  set: value => { if (!value) dialog.value = '' },
})
const queueSearch = ref('')
const historySearch = ref('')
const suppressedSearch = ref('')
const logSearch = ref('')
const showDetailedLogs = ref(false)
const logsRefreshing = ref(false)
const logsRefreshedAt = ref('')
const pageSizes = [20, 50, 100]
const briefLogCategories = new Set(['提交下载', '提交失败', '推送成功', '推送失败', '整理完成', 'Emby 已入库', '每日统计'])
const visibleLogs = computed(() => showDetailedLogs.value
  ? (state.value.logs || [])
  : (state.value.logs || []).filter(item => briefLogCategories.has(item.category)))

async function toggleDetailedLogs() {
  showDetailedLogs.value = !showDetailedLogs.value
  await refreshLogs()
}
async function refreshLogs() {
  logsRefreshing.value = true
  try {
    if (await loadStatus(true)) logsRefreshedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } finally {
    logsRefreshing.value = false
  }
}
async function openLogs() {
  dialog.value = 'logs'
  await refreshLogs()
}
const state = ref({
  summary: {}, queue: [], history: [], suppressed: [], logs: [],
  telegram: { source: '', admins_override: '', chat_id_override: '', sources: [] },
  disk_guard: { enabled: true, active: false, free_gb: 0, threshold_gb: 300, recover_gb: 350, waiting: [] },
})
const telegramForm = ref({ source: '', admins_override: '', chat_id_override: '' })
const diskForm = ref({ disk_guard_enabled: true, disk_guard_path: '/home', disk_guard_threshold_gb: 300, disk_guard_recover_gb: 350 })
const pushForm = ref({ limit: 20, test_limit: 2, max_active_downloads: 20, max_searches: 80, site_ids: [], min_score: 6 })
const controlForm = ref({ enabled: true, auto_push: false, auto_download: false, push_interval_minutes: 60 })
const intervalItems = [30, 60, 120, 180, 240, 300].map(value => ({ title: `${value} 分钟`, value }))
const downloadModeItems = [
  { title: '自动下载', value: true },
  { title: '手动确认', value: false },
]

const unwrap = response => response?.data?.data ?? response?.data ?? response
const envelope = response => (response?.success !== undefined ? response : (response?.data ?? response))

function applyState(data, syncForms = true) {
  if (!data) return
  state.value = data
  if (!syncForms) return
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
  pushForm.value = {
    limit: data.summary?.limit || 20,
    test_limit: data.summary?.test_limit || 2,
    max_active_downloads: data.summary?.max_active_downloads || 20,
    max_searches: data.summary?.max_searches || 80,
    site_ids: data.summary?.site_ids || [],
    min_score: data.summary?.min_score ?? 6,
  }
  controlForm.value = {
    enabled: data.summary?.enabled !== false,
    auto_push: Boolean(data.summary?.auto_push),
    auto_download: Boolean(data.summary?.auto_download),
    push_interval_minutes: data.summary?.push_interval_minutes || 60,
  }
}

async function loadStatus(silent = false) {
  if (!accessToken.value) return
  if (!silent) loading.value = true
  if (!silent) error.value = ''
  try {
    const response = await props.api.post('plugin/SmartMoviePush/secure_status', { access_token: accessToken.value })
    const body = envelope(response)
    if (body?.locked || body?.success === false) {
      lockLocally()
      return false
    }
    applyState(unwrap(response), !silent)
    return true
  } catch (err) {
    error.value = err?.message || '加载失败'
    return false
  } finally {
    if (!silent) loading.value = false
  }
}

async function runAction(action, extra = {}) {
  loading.value = true
  error.value = ''
  message.value = ''
  try {
    const response = await props.api.post('plugin/SmartMoviePush/ui_action', { action, ...extra, access_token: accessToken.value })
    const body = envelope(response)
    if (body?.locked) { lockLocally(); return }
    if (body?.success === false) error.value = body?.message || '操作失败'
    else message.value = body?.message || '操作完成'
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
    const response = await props.api.post('plugin/SmartMoviePush/ui_config', { ...telegramForm.value, access_token: accessToken.value })
    const body = envelope(response)
    if (body?.locked) { lockLocally(); return }
    if (body?.success === false) { error.value = body?.message || '保存失败'; return }
    if (body?.warning) error.value = body?.message || body.warning
    else message.value = body?.message || 'Telegram 设置已保存'
    applyState(body?.data)
  } catch (err) {
    error.value = err?.message || '保存失败'
  } finally {
    loading.value = false
  }
}

async function saveControlSettings(extra = {}) {
  Object.assign(controlForm.value, extra)
  loading.value = true
  error.value = ''
  message.value = ''
  try {
    const response = await props.api.post('plugin/SmartMoviePush/ui_config', { ...extra, access_token: accessToken.value })
    const body = envelope(response)
    if (body?.locked) { lockLocally(); return }
    if (body?.success === false) { error.value = body?.message || '保存失败'; return }
    message.value = body?.message || '控制设置已保存'
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
    const response = await props.api.post('plugin/SmartMoviePush/ui_config', { ...diskForm.value, access_token: accessToken.value })
    const body = envelope(response)
    if (body?.locked) { lockLocally(); return }
    if (body?.success === false) { error.value = body?.message || '保存失败'; return }
    message.value = body?.message || '硬盘保护设置已保存'
    applyState(body?.data)
  } catch (err) {
    error.value = err?.message || '保存失败'
  } finally {
    loading.value = false
  }
}

async function savePushSettings() {
  loading.value = true
  error.value = ''
  message.value = ''
  try {
    const response = await props.api.post('plugin/SmartMoviePush/ui_config', { ...pushForm.value, access_token: accessToken.value })
    const body = envelope(response)
    if (body?.locked) { lockLocally(); return }
    if (body?.success === false) { error.value = body?.message || '保存失败'; return }
    message.value = body?.message || '推送与下载设置已保存'
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
  { title: '下载完成', key: 'download_completed_at', width: 190 },
  { title: '整理 / 入库', key: 'result', width: 190 },
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
const activeHeaders = [
  { title: '影片', key: 'title' },
  { title: '进度', key: 'progress', width: 240 },
  { title: '实时速度', key: 'speed', width: 150 },
  { title: '状态', key: 'state', width: 120 },
  { title: '剩余时间', key: 'eta', width: 120 },
]
const logHeaders = [
  { title: '时间', key: 'created_at', width: 210 },
  { title: '类型', key: 'category', width: 130 },
  { title: '内容', key: 'message' },
]

let refreshTimer
let messageTimer
let errorTimer
watch(message, value => {
  window.clearTimeout(messageTimer)
  if (value) messageTimer = window.setTimeout(() => { message.value = '' }, 3000)
})
watch(error, value => {
  window.clearTimeout(errorTimer)
  if (value) errorTimer = window.setTimeout(() => { error.value = '' }, 3000)
})
function lockLocally() {
  window.localStorage.removeItem(accessTokenKey)
  window.clearInterval(refreshTimer)
  accessToken.value = ''
  accessReady.value = false
  dialog.value = ''
}

function startRefresh() {
  window.clearInterval(refreshTimer)
  refreshTimer = window.setInterval(() => loadStatus(true), 5000)
}

async function checkAccess() {
  const token = window.localStorage.getItem(accessTokenKey) || ''
  if (!token) return
  loading.value = true
  try {
    const response = await props.api.post('plugin/SmartMoviePush/auth_check', { access_token: token })
    const body = envelope(response)
    if (!body?.success || !body?.unlocked) {
      lockLocally()
      return
    }
    accessToken.value = token
    accessReady.value = true
    await loadStatus()
    startRefresh()
  } catch (err) {
    error.value = err?.message || '验证插件访问权限失败'
  } finally {
    loading.value = false
  }
}

async function unlockAccess() {
  if (!accessPassword.value) {
    error.value = '请输入插件访问密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const response = await props.api.post('plugin/SmartMoviePush/auth_unlock', { password: accessPassword.value })
    const body = envelope(response)
    if (!body?.success || !body?.access_token) {
      error.value = body?.message || '密码错误'
      return
    }
    accessToken.value = body.access_token
    window.localStorage.setItem(accessTokenKey, body.access_token)
    accessPassword.value = ''
    accessReady.value = true
    message.value = '插件已解锁'
    await loadStatus()
    startRefresh()
  } catch (err) {
    error.value = err?.message || '解锁失败'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await checkAccess()
})
onUnmounted(() => {
  window.clearInterval(refreshTimer)
  window.clearTimeout(messageTimer)
  window.clearTimeout(errorTimer)
})
</script>

<template>
  <VContainer fluid class="pa-2">
    <VAlert v-if="error" type="error" variant="tonal" class="mb-3" closable>{{ error }}</VAlert>
    <VAlert v-if="message" type="success" variant="tonal" class="mb-3" closable>{{ message }}</VAlert>

    <VCard v-if="!accessReady" variant="tonal" color="primary" class="access-lock-card pa-6 mx-auto mt-8">
      <div class="d-flex align-center ga-3 mb-4">
        <VAvatar color="primary" variant="tonal"><VIcon icon="mdi-lock" /></VAvatar>
        <div>
          <div class="text-h6 font-weight-bold">智能下载影视资源_惹咪之北</div>
          <div class="text-body-2 text-medium-emphasis">私人插件，首次使用请联系 @SDFSDFSF12321 获取密码。验证成功后当前浏览器会记住。</div>
        </div>
      </div>
      <VTextField v-model="accessPassword" label="插件访问密码" type="password" autocomplete="current-password" prepend-inner-icon="mdi-key" autofocus :disabled="loading" @keyup.enter="unlockAccess" />
      <VBtn color="primary" block size="large" :loading="loading" @click="unlockAccess">解锁插件</VBtn>
    </VCard>

    <template v-else>
    <div class="status-grid mb-3">
      <div class="status-item">
        <VCard variant="tonal" :color="controlForm.enabled ? 'success' : 'secondary'" class="pa-4 h-100 status-card">
          <div class="d-flex align-center justify-space-between ga-3">
            <div><div class="text-caption">插件状态</div><div class="text-h6 font-weight-bold">{{ controlForm.enabled ? '已启用' : '已关闭' }}</div></div>
            <VSwitch v-model="controlForm.enabled" color="success" hide-details :loading="loading" @update:model-value="value => saveControlSettings({ enabled: value })" />
          </div>
        </VCard>
      </div>
      <div class="status-item">
        <VCard variant="tonal" color="primary" class="pa-4 h-100 status-card">
          <div class="d-flex align-center justify-space-between mb-2"><div><div class="text-caption">定时推送</div><div class="text-h6 font-weight-bold">{{ diskGuard.active ? '硬盘保护暂停' : (controlForm.auto_push ? '已开启' : '已暂停') }}</div></div><VSwitch v-model="controlForm.auto_push" color="primary" hide-details :disabled="!controlForm.enabled" @update:model-value="value => saveControlSettings({ auto_push: value })" /></div>
          <VSelect v-model="controlForm.push_interval_minutes" :items="intervalItems" density="compact" label="推送间隔" hide-details :disabled="!controlForm.enabled" @update:model-value="value => saveControlSettings({ push_interval_minutes: value })" />
        </VCard>
      </div>
      <div class="status-item">
        <VCard variant="tonal" color="warning" class="pa-4 h-100 status-card">
          <div class="text-caption mb-2">下载模式</div>
          <VSelect v-model="controlForm.auto_download" :items="downloadModeItems" density="compact" hide-details :disabled="!controlForm.enabled" @update:model-value="value => saveControlSettings({ auto_download: value })" />
        </VCard>
      </div>
      <div class="status-item">
        <VCard variant="tonal" color="info" class="pa-4 h-100 list-card status-card" @click="dialog = 'active'">
          <div class="d-flex align-center justify-space-between"><div><div class="text-caption">正在下载（点击看实时详情）</div><div class="text-h6 font-weight-bold">{{ summary.active_downloads || 0 }}/{{ summary.max_active_downloads || 20 }}</div></div><VIcon icon="mdi-chevron-right" /></div>
        </VCard>
      </div>
      <div class="status-item">
        <VCard variant="tonal" color="secondary" class="pa-4 h-100 list-card status-card" @click="dialog = 'queue'">
          <div class="d-flex align-center justify-space-between"><div><div class="text-caption">等候下载</div><div class="text-h6 font-weight-bold">{{ state.queue.length }}</div><div class="text-caption mt-1">搜索、取消任务或批量清空</div></div><VIcon icon="mdi-chevron-right" /></div>
        </VCard>
      </div>
      <div class="status-item">
        <VCard variant="tonal" color="primary" class="pa-4 h-100 list-card status-card" @click="dialog = 'history'">
          <div class="d-flex align-center justify-space-between"><div><div class="text-caption">插件下载记录</div><div class="text-h6 font-weight-bold">{{ state.history.length }}</div><div class="text-caption mt-1">搜索和分页查看记录</div></div><VIcon icon="mdi-chevron-right" /></div>
        </VCard>
      </div>
      <div class="status-item">
        <VCard variant="tonal" color="error" class="pa-4 h-100 list-card status-card" @click="dialog = 'suppressed'">
          <div class="d-flex align-center justify-space-between"><div><div class="text-caption">不再推送列表</div><div class="text-h6 font-weight-bold">{{ state.suppressed.length }}</div><div class="text-caption mt-1">搜索、取消排除或批量清空</div></div><VIcon icon="mdi-chevron-right" /></div>
        </VCard>
      </div>
    </div>

    <div class="status-secondary-grid mb-3">
      <VCard variant="tonal" :color="diskGuard.active ? 'error' : 'success'" class="pa-3 disk-guard-card compact-top-card">
        <div class="d-flex align-center justify-space-between ga-2 mb-2">
          <div class="min-w-0">
            <div class="text-subtitle-1 font-weight-bold">硬盘空间保护</div>
          <div class="text-caption text-truncate">{{ diskGuard.active ? '保护中：定时推送与新下载暂停，旧下载继续' : '正常：允许推送与新增下载' }}</div>
          </div>
          <div class="text-right text-no-wrap">
            <div class="text-h6 font-weight-bold">剩余 {{ diskGuard.free_gb ?? 0 }}G</div>
            <div class="text-caption">暂停 {{ diskGuard.waiting_count || 0 }} 个</div>
          </div>
        </div>
        <div class="disk-controls-grid">
          <VSwitch v-model="diskForm.disk_guard_enabled" label="启用保护" color="success" density="compact" hide-details />
          <VTextField v-model="diskForm.disk_guard_path" label="检测路径" density="compact" hide-details />
          <VTextField v-model.number="diskForm.disk_guard_threshold_gb" label="停止新增（G）" type="number" density="compact" hide-details />
          <VTextField v-model.number="diskForm.disk_guard_recover_gb" label="允许恢复（G）" type="number" density="compact" hide-details />
        </div>
        <div class="mt-2 d-flex align-center flex-wrap ga-2">
          <VBtn size="small" color="primary" variant="tonal" :loading="loading" @click="saveDiskGuard">保存</VBtn>
          <VBtn size="small" variant="tonal" :loading="loading" @click="runAction('disk_guard_check')">立即检查</VBtn>
          <VBtn v-if="diskGuard.active && !diskGuard.acked" size="small" color="warning" variant="tonal" :loading="loading" @click="runAction('disk_guard_ack', { incident_id: diskGuard.incident_id })">收到，停止提醒</VBtn>
          <VBtn v-if="diskGuard.active" size="small" color="success" variant="tonal" :loading="loading" @click="runAction('disk_guard_resume')">清理后恢复</VBtn>
          <VBtn v-if="diskGuard.waiting_count" size="small" variant="text" @click="dialog = 'disk'">查看暂停种子</VBtn>
          <span class="text-caption disk-rule-text">{{ diskGuard.active && diskGuard.recovered ? `已达到 ${diskGuard.recover_gb}G 恢复线，请手动恢复。` : `低于 ${diskGuard.threshold_gb}G 停止新增，清理到 ${diskGuard.recover_gb}G 后恢复。` }}</span>
        </div>
        <VAlert v-if="diskGuard.last_error" type="warning" variant="tonal" density="compact" class="mt-2">{{ diskGuard.last_error }}</VAlert>
      </VCard>
    </div>

    <VCard variant="outlined" class="pa-4 mb-4">
      <div class="text-h6 mb-1">推送与下载数量</div>
      <div class="text-caption text-medium-emphasis mb-3">定时任务按上方所选间隔使用“每轮数量”；“立即运行”使用“立即运行数量”，不受定时推送开关影响。硬盘保护启动后两者均暂停扫描、推荐推送和新增下载，旧下载继续；手动恢复保护后才重新运行。</div>
      <VRow dense class="settings-row push-settings-row">
        <VCol cols="6" md="3"><VTextField v-model.number="pushForm.limit" label="每轮下载/推送（部）" type="number" :min="1" :max="50" density="compact" /></VCol>
        <VCol cols="6" md="3"><VTextField v-model.number="pushForm.test_limit" label="立即运行数量（部）" type="number" :min="1" :max="50" density="compact" /></VCol>
        <VCol cols="6" md="3"><VTextField v-model.number="pushForm.max_active_downloads" label="同时下载上限（部）" type="number" :min="1" :max="100" density="compact" /></VCol>
        <VCol cols="6" md="3"><VTextField v-model.number="pushForm.max_searches" label="每轮最多搜索候选电影" type="number" :min="20" :max="200" density="compact" hint="每部候选会同时搜索下面选中的全部站点" persistent-hint /></VCol>
        <VCol cols="12" md="3"><VTextField v-model.number="pushForm.min_score" label="TMDB 最低评分" type="number" :min="0" :max="10" :step="0.1" density="compact" hint="默认 6 分；提高后候选更少但平均质量更高" persistent-hint /></VCol>
        <VCol cols="12" md="3"><VSelect v-model="pushForm.site_ids" :items="summary.site_options || []" item-title="title" item-value="value" label="资源搜索站点（可多选）" multiple chips closable-chips density="compact" hint="读取 MoviePilot 已配置站点" persistent-hint /></VCol>
      </VRow>
      <div class="d-flex flex-wrap ga-2">
        <VBtn color="primary" variant="tonal" :loading="loading" @click="savePushSettings">保存推送与下载设置</VBtn>
        <VBtn color="success" variant="tonal" :loading="loading" :disabled="!controlForm.enabled" @click="runAction('run_once')">立即运行</VBtn>
        <VBtn color="error" variant="tonal" :loading="loading" @click="runAction('clear_cache')">清空扫描缓存</VBtn>
        <VBtn color="info" variant="tonal" @click="openLogs">查看日志</VBtn>
        <VBtn variant="text" icon="mdi-refresh" :loading="loading" @click="loadStatus()" />
      </div>
      <VAlert v-if="state.run_status?.run_id" class="mt-3" type="info" variant="tonal" density="compact">
        {{ state.run_status.source }} · {{ state.run_status.stage }}：{{ state.run_status.detail }}
        <span v-if="state.run_status.target">（目标 {{ state.run_status.target }}，已查询 {{ state.run_status.searched || 0 }}，选中 {{ state.run_status.selected || 0 }}，已推送 {{ state.run_status.sent || 0 }}）</span>
      </VAlert>
    </VCard>

    <VCard variant="outlined" class="pa-4 mb-4">
      <div class="text-h6 mb-1">Telegram 设置</div>
      <div class="text-caption text-medium-emphasis mb-3">三个输入框留空即跟随 MoviePilot 的 Telegram 通知设置；需要覆盖哪一项就直接输入哪一项。</div>
      <VRow dense class="settings-row telegram-settings-row">
        <VCol cols="12" md="4">
          <VTextField v-model="telegramForm.source" label="TG 机器人 Token 或 MP 实例名（可选）" type="password" autocomplete="off" density="compact" clearable :hint="telegramForm.source ? '' : '默认使用 MoviePilot TG 通知设置'" :persistent-hint="!telegramForm.source" />
        </VCol>
        <VCol cols="12" md="4">
          <VTextField v-model="telegramForm.admins_override" label="管理员 ID/用户名（可选）" density="compact" clearable placeholder="多个用逗号分隔" :hint="telegramForm.admins_override ? '' : '默认使用 MoviePilot TG 通知设置'" :persistent-hint="!telegramForm.admins_override" />
        </VCol>
        <VCol cols="12" md="4">
          <VTextField v-model="telegramForm.chat_id_override" label="通知群组/频道 Chat ID（可选）" density="compact" clearable :hint="telegramForm.chat_id_override ? '' : '默认使用 MoviePilot TG 通知设置'" :persistent-hint="!telegramForm.chat_id_override" />
        </VCol>
      </VRow>
      <VBtn color="primary" variant="tonal" :loading="loading" @click="saveTelegram">保存 Telegram 设置</VBtn>
      <VBtn color="info" variant="tonal" class="ml-2" :loading="loading" @click="runAction('telegram_test')">发送测试消息</VBtn>
    </VCard>

    <VDialog v-model="dialogOpen" max-width="75rem" scrollable>
      <VCard v-if="dialog === 'active'" title="正在下载 · 实时状态">
        <VDialogCloseBtn @click="dialog = ''" />
        <VCardText>
          <VAlert v-if="!(summary.active_download_items || []).length" type="info" variant="tonal" class="mb-3">当前没有 MoviePilot 正在下载的任务，或下载器暂未返回详情。</VAlert>
          <VDataTable v-else :headers="activeHeaders" :items="summary.active_download_items || []" :items-per-page="20" :items-per-page-options="pageSizes" density="compact" hover>
            <template #item.progress="{ item }"><div class="d-flex align-center ga-2"><VProgressLinear :model-value="item.progress" color="info" height="8" rounded /><span class="text-caption text-no-wrap">{{ item.progress }}%</span></div></template>
          </VDataTable>
          <div class="text-caption text-medium-emphasis mt-3">每 5 秒自动刷新。</div>
        </VCardText>
      </VCard>
      <VCard v-else-if="dialog === 'queue'" title="等候下载">
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
          <VDataTable :headers="historyHeaders" :items="state.history" :search="historySearch" :items-per-page="20" :items-per-page-options="pageSizes" density="compact" hover>
            <template #item.result="{ item }">
              <span :title="item.organize_error || ''">{{ item.emby_ingested_at ? '✓ Emby 已入库' : item.organized_at ? 'MP 已整理，待 Emby' : item.organize_failed_at ? 'MP 整理失败' : item.download_completed_at ? '已下载，待整理' : '下载中 / 待下载' }}</span>
            </template>
          </VDataTable>
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
      <VCard v-else-if="dialog === 'logs'" title="插件运行日志">
        <VDialogCloseBtn @click="dialog = ''" />
        <VCardText>
          <div class="d-flex ga-2 mb-3">
            <VTextField v-model="logSearch" label="搜索日志" prepend-inner-icon="mdi-magnify" clearable hide-details />
            <VBtn :color="showDetailedLogs ? 'primary' : 'secondary'" variant="tonal" :loading="logsRefreshing" class="flex-shrink-0" @click="toggleDetailedLogs">{{ showDetailedLogs ? '详情日志：开' : '详情日志：关' }}</VBtn>
            <VBtn variant="tonal" class="flex-shrink-0" :loading="logsRefreshing" @click="refreshLogs">刷新</VBtn>
            <VBtn color="error" variant="tonal" @click="runAction('clear_logs')">清空日志</VBtn>
          </div>
          <div class="text-caption text-medium-emphasis mb-2">当前显示 {{ visibleLogs.length }}/{{ (state.logs || []).length }} 条。{{ showDetailedLogs ? '含操作、筛选、站点查询、跳过原因、发送结果和定时任务' : '仅显示推送、下载和入库记录；打开详情日志可排查每一步' }}。{{ logsRefreshedAt ? `最近刷新：${logsRefreshedAt}。` : '' }}升级前未记录的步骤无法补写。</div>
          <VDataTable :headers="logHeaders" :items="visibleLogs" :search="logSearch" :items-per-page="20" :items-per-page-options="pageSizes" density="compact" hover />
        </VCardText>
      </VCard>
    </VDialog>
    </template>
  </VContainer>
</template>

<style scoped>
.status-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
  align-items: stretch;
  margin-bottom: 4px !important;
}
.status-item { min-width: 0; }
.status-card {
  min-height: 118px;
  height: 100%;
  overflow: hidden;
  padding: 12px !important;
}
.status-card :deep(.v-field) { min-width: 0; }
.status-card .text-caption { line-height: 1.25; }
.status-secondary-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
}
.compact-top-card { grid-column: span 3; }
.disk-controls-grid {
  display: grid;
  grid-template-columns: 1.15fr 1.35fr 1fr 1fr;
  gap: 8px;
  align-items: center;
}
.disk-rule-text { margin-left: auto; opacity: .85; }
.settings-row {
  row-gap: 10px;
  margin-bottom: 10px !important;
}
.settings-row :deep(.v-input__details) {
  min-height: 28px;
  padding-top: 7px;
}
.telegram-settings-row { margin-bottom: 4px !important; }
.access-lock-card { max-width: 520px; }
@media (max-width: 960px) {
  .status-grid {
    grid-template-columns: repeat(7, minmax(185px, 1fr));
    overflow-x: auto;
    padding-bottom: 6px;
  }
  .status-secondary-grid { grid-template-columns: 1fr; }
  .compact-top-card { grid-column: 1; }
  .disk-controls-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .disk-rule-text { width: 100%; margin-left: 0; }
}
.list-card { cursor: pointer; transition: border-color .2s, transform .2s; }
.list-card:hover { border-color: rgb(var(--v-theme-primary)); transform: translateY(-2px); }
</style>
