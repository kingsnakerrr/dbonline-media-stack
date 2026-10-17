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
const dialogSource = ref('all')
const dialogOpen = computed({
  get: () => Boolean(dialog.value),
  set: value => { if (!value) dialog.value = '' },
})
const queueSearch = ref('')
const historySearch = ref('')
const historyPeriod = ref('all')
const historyDate = ref('')
const historyStatus = ref('all')
const historyPage = ref(1)
const historyPageSize = ref(100)
const historySource = ref('all')
const historyBusy = ref(false)
const historyView = ref({ dates: [], items: [], total: 0, page: 1 })
const monthlyForm = ref({ task_id: '', year: new Date().getFullYear(), month: 0, min_score: 7, min_votes: 50, batch_size: 5 })
const monthlyView = ref({ task: {}, items: [], counts: {}, total: 0, page: 1 })
const monthlyTaskId = ref('')
const monthlyArchiveKey = ref('')
const monthlyArchiveYear = ref(0)
const monthlyArchiveMonth = ref(0)
const archiveYear = ref(new Date().getFullYear())
const archiveYearOptions = Array.from({ length: new Date().getFullYear() - 1899 }, (_, index) => new Date().getFullYear() - index)
const monthlySearch = ref('')
const monthlyStatus = ref('all')
const monthlyPage = ref(1)
const monthlyPageSize = ref(20)
const monthlyMinScore = ref(7)
const annualReleaseMonth = ref(0)
const annualCategory = ref('all')
const monthlyEditMode = ref(false)
const monthlySelected = ref([])
const monthlyBusy = ref(false)
const monthlyStatusOptions = [
  { title: '全部', value: 'all', color: 'primary' },
  { title: '只看未下载', value: 'not_downloaded', color: 'info' },
  { title: '候选', value: 'candidate', color: 'info' },
  { title: '等候下载', value: 'queued', color: 'warning' },
  { title: '未下载完成', value: 'unfinished', color: 'secondary' },
  { title: '待入库', value: 'awaiting_library', color: 'info' },
  { title: '已整理', value: 'organized', color: 'warning' },
  { title: '已整理未入库', value: 'organized_not_ingested', color: 'error' },
  { title: 'Emby 已入库', value: 'emby_all', color: 'success' },
  { title: '已推送', value: 'pushed', color: 'primary' },
  { title: '不再推送', value: 'suppressed', color: 'error' },
]
const monthlyStatusMeta = Object.fromEntries(monthlyStatusOptions.map(item => [item.value, item]))
function monthlyStatusLabel(item) {
  if (item.status === 'queued') return item.queue_source === 'annual' ? '已在年度下载队列' : '已在随机下载队列'
  if (item.status === 'emby_ingested') return 'Emby 已入库'
  if (item.status === 'library') return 'Emby 已入库（其他来源）'
  return monthlyStatusMeta[item.status]?.title || item.status
}
function monthlyStatusColor(item) {
  return ['emby_ingested', 'library'].includes(item.status) ? 'success' : monthlyStatusMeta[item.status]?.color || 'secondary'
}
const annualEntry = computed(() => {
  const year = Number(archiveYear.value)
  const archives = (state.value.monthly_archives || []).filter(item => Number(item.year) === year && Number(item.month) === 0)
  const tasks = (state.value.monthly_tasks || []).filter(item => Number(item.year) === year && Number(item.month) === 0)
  const latest = archives.reduce((current, item) => !current || String(item.scanned_at || '') > String(current.scanned_at || '') ? item : current, null)
  const scanTask = tasks.find(item => item.scan_state === 'running') || tasks.find(item => item.scan_state === 'pending')
  const failedTask = scanTask ? null : tasks.find(item => item.scan_state === 'error')
  return { year, month: 0, latest, tasks, scanTask, failedTask, minimum: latest?.min_score ?? 7,
    scans: archives.reduce((total, item) => total + Number(item.scan_count || 1), 0),
    movies: Number(latest?.month_candidate_count || latest?.candidate_count || 0) }
})
const yearScanBadges = computed(() => {
  const badges = new Map()
  for (const archive of state.value.monthly_archives || []) {
    if (Number(archive.month) !== 0) continue
    const year = Number(archive.year)
    const badge = badges.get(year) || { scans: 0, status: '' }
    badge.scans += Number(archive.scan_count || 1)
    badges.set(year, badge)
  }
  for (const task of state.value.monthly_tasks || []) {
    if (Number(task.month) !== 0) continue
    const year = Number(task.year)
    const badge = badges.get(year) || { scans: 0, status: '' }
    if (task.scan_state === 'running' || (task.scan_state === 'pending' && badge.status !== 'running') || (task.scan_state === 'error' && !badge.status)) badge.status = task.scan_state
    badges.set(year, badge)
  }
  return badges
})
function yearScanBadge(year) {
  const badge = yearScanBadges.value.get(Number(year)) || { scans: 0, status: '' }
  if (badge.status === 'running') return { text: `正在扫第 ${badge.scans + 1} 次`, color: 'info' }
  if (badge.status === 'pending') return { text: `等待第 ${badge.scans + 1} 次`, color: 'warning' }
  if (badge.status === 'error') return { text: badge.scans ? `扫描失败 · 已扫 ${badge.scans} 次` : '扫描失败', color: 'error' }
  return badge.scans ? { text: `已扫 ${badge.scans} 次`, color: 'success' } : { text: '未扫描', color: 'secondary' }
}
const archiveMonths = computed(() => Array.from({ length: 12 }, (_, index) => {
  const month = index + 1
  const archives = (state.value.monthly_archives || []).filter(item => Number(item.year) === Number(archiveYear.value) && Number(item.month) === month)
  const tasks = (state.value.monthly_tasks || []).filter(item => Number(item.year) === Number(archiveYear.value) && Number(item.month) === month)
  const latest = archives.reduce((current, item) => !current || String(item.scanned_at || '') > String(current.scanned_at || '') ? item : current, null)
  return { year: Number(archiveYear.value), month, latest, tasks,
    minimum: archives.length ? Math.min(...archives.map(item => Number(item.min_score))) : 7,
    scans: archives.reduce((total, item) => total + Number(item.scan_count || 1), 0),
    movies: Number(latest?.month_candidate_count || latest?.candidate_count || 0) }
}))
const selectedMonthTasks = computed(() => (state.value.monthly_tasks || []).filter(item =>
  Number(item.year) === Number(monthlyArchiveYear.value || monthlyView.value.task?.year)
  && Number(item.month) === Number(monthlyArchiveMonth.value || monthlyView.value.task?.month)))
const monthlyCanDownload = item => ['candidate', 'pushed', 'queued'].includes(item.status)
function selectMonthlyPage() {
  const values = new Set(monthlySelected.value)
  for (const item of monthlyView.value.items || []) {
    if (!monthlyCanDownload(item)) continue
    const id = String(item.tmdb_id)
    values.add(id)
  }
  monthlySelected.value = [...values]
}
function toggleMonthlyMovie(item, checked) {
  const id = String(item.tmdb_id)
  monthlySelected.value = checked
    ? [...new Set([...monthlySelected.value, id])]
    : monthlySelected.value.filter(value => value !== id)
}
const posterUrl = path => typeof path === 'string' && /^\/[a-zA-Z0-9_./-]+$/.test(path) ? `https://image.tmdb.org/t/p/w342${path}` : ''
const movieTitle = item => item.display_title || item.title || `TMDB ${item.tmdb_id}`
const historyPeriodOptions = [
  { title: '全部记录', value: 'all' },
  { title: '今天', value: 'today' },
  { title: '昨天', value: 'yesterday' },
  { title: '本周', value: 'week' },
  { title: '本月', value: 'month' },
  { title: '上个月', value: 'last_month' },
  { title: '今年', value: 'year' },
  { title: '指定日期', value: 'date' },
]
const historyStatusOptions = [
  { title: '全部', value: 'all', color: 'primary' },
  { title: 'Emby 已入库', value: 'emby_ingested', color: 'success' },
  { title: '待入库', value: 'awaiting_library', color: 'info' },
  { title: '未下载完成', value: 'unfinished', color: 'secondary' },
  { title: '已整理', value: 'organized', color: 'warning' },
  { title: '整理失败', value: 'organize_failed', color: 'error' },
  { title: '已整理未入库', value: 'organized_not_ingested', color: 'error' },
]
const historyStatusMeta = Object.fromEntries(historyStatusOptions.map(item => [item.value, item]))
const historyDateOptions = computed(() => [
  { title: '全部日期', value: '' },
  ...(historyView.value.dates || []).map(date => ({ title: date, value: date })),
])
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
async function loadHistory() {
  if (!accessToken.value) return
  historyBusy.value = true
  try {
    const response = await props.api.post('plugin/SmartMoviePush/secure_history', {
      access_token: accessToken.value,
      period: historyPeriod.value,
      date: historyDate.value,
      status: historyStatus.value,
      search: historySearch.value,
      page: historyPage.value,
      page_size: historyPageSize.value,
      source: historySource.value,
    })
    const body = envelope(response)
    if (body?.locked) { lockLocally(); return }
    if (body?.success === false) { error.value = body?.message || '加载下载记录失败'; return }
    historyView.value = unwrap(response)
    historyPage.value = historyView.value.page || 1
  } catch (err) {
    error.value = err?.message || '加载下载记录失败'
  } finally {
    historyBusy.value = false
  }
}
async function openHistory(source = 'all') {
  historySource.value = source
  historyPeriod.value = 'all'
  historyStatus.value = 'all'
  historyPage.value = 1
  dialog.value = 'history'
  await loadHistory()
}
function openActive(source = 'all') {
  dialogSource.value = source
  dialog.value = 'active'
  loadStatus(true)
}
function openQueue(source = 'all') {
  dialogSource.value = source
  queueSearch.value = ''
  dialog.value = 'queue'
  loadStatus(true)
}
async function loadMonthly(refreshLibrary = false) {
  if (!accessToken.value || (!monthlyTaskId.value && !monthlyArchiveKey.value && !monthlyArchiveYear.value)) return
  monthlyBusy.value = true
  try {
    const response = await props.api.post('plugin/SmartMoviePush/secure_monthly', {
      access_token: accessToken.value, task_id: monthlyTaskId.value,
      archive_key: monthlyArchiveKey.value,
      archive_year: monthlyArchiveYear.value, archive_month: monthlyArchiveMonth.value,
      page: monthlyPage.value, search: monthlySearch.value, status: monthlyStatus.value,
      page_size: monthlyPageSize.value, min_score: monthlyMinScore.value,
      release_month: annualReleaseMonth.value, category: annualCategory.value,
      refresh_library: refreshLibrary,
    })
    const body = envelope(response)
    if (body?.locked) { lockLocally(); return }
    if (body?.success === false) { error.value = body?.message || '加载月份名单失败'; return }
    monthlyView.value = unwrap(response)
    monthlyPage.value = monthlyView.value.page || 1
  } catch (err) {
    error.value = err?.message || '加载月份名单失败'
  } finally {
    monthlyBusy.value = false
  }
}
async function openMonthly(task) {
  monthlyTaskId.value = task.id
  monthlyArchiveKey.value = (state.value.monthly_archives || []).some(item => item.scan_key === task.scan_key) ? task.scan_key : ''
  monthlyArchiveYear.value = 0
  monthlyArchiveMonth.value = 0
  monthlyPage.value = 1
  monthlyMinScore.value = Math.max(7, Number(task.min_score || 0))
  monthlySelected.value = []
  monthlySearch.value = ''
  monthlyStatus.value = 'all'
  dialog.value = 'monthly'
  await loadMonthly()
}
async function openMonthlyArchive(archive) {
  monthlyTaskId.value = archive.latest ? '' : archive.tasks?.[0]?.id || ''
  monthlyArchiveKey.value = ''
  monthlyArchiveYear.value = archive.latest ? Number(archive.year) : 0
  monthlyArchiveMonth.value = archive.latest ? Number(archive.month) : 0
  monthlyEditMode.value = !archive.latest && !archive.tasks?.length
  monthlyForm.value = { task_id: archive.tasks?.[0]?.id || '', year: Number(archive.year),
    month: Number(archive.month), min_score: Number(archive.tasks?.[0]?.min_score ?? 7),
    min_votes: Number(archive.tasks?.[0]?.min_votes ?? 50),
    batch_size: Number(archive.tasks?.[0]?.batch_size ?? 5) }
  monthlyView.value = { task: { year: archive.year, month: archive.month }, items: [], counts: {}, total: 0, page: 1 }
  monthlyPage.value = 1
  monthlyMinScore.value = Number(archive.minimum ?? 7)
  annualReleaseMonth.value = 0
  annualCategory.value = 'all'
  monthlySelected.value = []
  monthlySearch.value = ''
  monthlyStatus.value = 'all'
  dialog.value = 'monthly'
  if (archive.latest || archive.tasks?.length) await loadMonthly()
}
async function downloadMonthlySelected() {
  if (!monthlySelected.value.length) return
  const selections = monthlySelected.value.map(tmdb_id => ({ tmdb_id }))
  await runAction('monthly_batch_download', {
    year: monthlyArchiveYear.value, month: monthlyArchiveMonth.value, selections,
  })
  if (!error.value) monthlySelected.value = []
  await Promise.all([loadMonthly(), loadStatus(true)])
}
function editMonthly(task) {
  monthlyForm.value = { task_id: task.id, year: task.year, month: task.month, min_score: task.min_score,
    min_votes: task.min_votes ?? 50, batch_size: task.batch_size || 5 }
  monthlyEditMode.value = true
}
function resetMonthlyForm() {
  monthlyForm.value = { task_id: '', year: new Date().getFullYear(), month: 0, min_score: 7, min_votes: 50, batch_size: 5 }
}
async function saveMonthly() {
  const form = { ...monthlyForm.value }
  await runAction('monthly_save', form)
  if (!error.value) {
    monthlyEditMode.value = false
    const task = (state.value.monthly_tasks || []).find(item => Number(item.year) === Number(form.year) && Number(item.month) === Number(form.month))
    if (task) monthlyTaskId.value = task.id
    await loadMonthly()
  }
}
let monthlySearchTimer
watch(monthlySearch, () => {
  window.clearTimeout(monthlySearchTimer)
  if (dialog.value === 'monthly') {
    monthlyPage.value = 1
    monthlySearchTimer = window.setTimeout(loadMonthly, 300)
  }
})
watch(monthlyStatus, () => {
  if (dialog.value === 'monthly') { monthlyPage.value = 1; loadMonthly() }
})
watch([annualReleaseMonth, annualCategory], () => {
  if (dialog.value === 'monthly' && Number(monthlyArchiveMonth.value) === 0 && monthlyArchiveYear.value) {
    monthlyPage.value = 1
    loadMonthly()
  }
})
let historySearchTimer
watch(historySearch, () => {
  window.clearTimeout(historySearchTimer)
  if (dialog.value === 'history') {
    historyPage.value = 1
    historySearchTimer = window.setTimeout(loadHistory, 300)
  }
})
watch([historyPeriod, historyDate, historyStatus, historyPageSize], () => {
  if (historyPeriod.value === 'date' && !historyDate.value) {
    historyDate.value = historyView.value.dates?.[0] || ''
    if (!historyDate.value) return
  }
  if (dialog.value === 'history') { historyPage.value = 1; loadHistory() }
})
async function changeHistoryPage(delta) {
  historyPage.value += delta
  await loadHistory()
}
const state = ref({
  summary: {}, queue: [], history: [], suppressed: [], logs: [],
  monthly_tasks: [], monthly_archives: [],
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
const annualActiveItems = computed(() => (summary.value.active_download_items || []).filter(item => item.source === 'annual'))
const annualQueueItems = computed(() => (state.value.queue || []).filter(item => item.source === 'annual'))
const visibleActiveItems = computed(() => dialogSource.value === 'annual' ? annualActiveItems.value : (summary.value.active_download_items || []))
const visibleQueueItems = computed(() => dialogSource.value === 'annual' ? annualQueueItems.value : (state.value.queue || []))
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
let monthlyRefreshTimer
let monthlyRefreshTick = 0
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
  window.clearInterval(monthlyRefreshTimer)
  accessToken.value = ''
  accessReady.value = false
  dialog.value = ''
}

function startRefresh() {
  window.clearInterval(refreshTimer)
  refreshTimer = window.setInterval(() => loadStatus(true), 5000)
  window.clearInterval(monthlyRefreshTimer)
  monthlyRefreshTimer = window.setInterval(async () => {
    if (dialog.value !== 'monthly' || monthlyBusy.value) return
    monthlyRefreshTick += 1
    if (!monthlyView.value.batch_progress?.running && monthlyRefreshTick % 3 !== 0) return
    if (!monthlyArchiveYear.value && monthlyTaskId.value) {
      const task = (state.value.monthly_tasks || []).find(item => item.id === monthlyTaskId.value)
      if (task?.scan_state === 'complete') {
        monthlyArchiveYear.value = Number(task.year)
        monthlyArchiveMonth.value = Number(task.month)
      }
    }
    await loadMonthly()
  }, 3000)
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
  window.clearInterval(monthlyRefreshTimer)
  window.clearTimeout(historySearchTimer)
  window.clearTimeout(monthlySearchTimer)
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
        <VCard variant="tonal" color="info" class="pa-4 h-100 list-card status-card" @click="openActive()">
          <div class="d-flex align-center justify-space-between"><div><div class="text-caption">正在下载（点击看实时详情）</div><div class="text-h6 font-weight-bold">{{ summary.active_downloads || 0 }}/{{ summary.max_active_downloads || 20 }}</div></div><VIcon icon="mdi-chevron-right" /></div>
        </VCard>
      </div>
      <div class="status-item">
        <VCard variant="tonal" color="secondary" class="pa-4 h-100 list-card status-card" @click="openQueue()">
          <div class="d-flex align-center justify-space-between"><div><div class="text-caption">等候下载</div><div class="text-h6 font-weight-bold">{{ state.queue.length }}</div><div class="text-caption mt-1">搜索、取消任务或批量清空</div></div><VIcon icon="mdi-chevron-right" /></div>
        </VCard>
      </div>
      <div class="status-item">
        <VCard variant="tonal" color="primary" class="pa-4 h-100 list-card status-card" @click="openHistory">
          <div class="d-flex align-center justify-space-between"><div><div class="text-caption">下载记录</div><div class="text-h6 font-weight-bold">{{ summary.history_count || 0 }}</div><div class="text-caption mt-1">全部记录 · 按时间段筛选</div></div><VIcon icon="mdi-chevron-right" /></div>
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
      <div class="d-flex align-center justify-space-between mb-1">
        <div class="text-h6">按年份筛选电影</div>
        <VChip size="small" color="primary">{{ (state.monthly_tasks || []).length }}/5</VChip>
      </div>
      <div class="text-caption text-medium-emphasis mb-3">选定年份后扫描全年；创建任务只保存电影名单，不会开始下载。扫描完成后可勾选电影手动下载，或点击“启动自动下载”按每轮数量定时下载；最多保留 5 个自动任务。</div>
      <VRow dense class="mb-3">
        <VCol cols="12" sm="4"><VCard variant="tonal" color="info" class="pa-3 h-100 list-card" @click="openActive('annual')"><div class="d-flex justify-space-between align-center"><div><div class="text-caption">年度正在下载</div><div class="text-h6 font-weight-bold">{{ annualActiveItems.length }}</div></div><VIcon icon="mdi-chevron-right" /></div></VCard></VCol>
        <VCol cols="12" sm="4"><VCard variant="tonal" color="secondary" class="pa-3 h-100 list-card" @click="openQueue('annual')"><div class="d-flex justify-space-between align-center"><div><div class="text-caption">年度等候下载</div><div class="text-h6 font-weight-bold">{{ annualQueueItems.length }}</div></div><VIcon icon="mdi-chevron-right" /></div></VCard></VCol>
        <VCol cols="12" sm="4"><VCard variant="tonal" color="primary" class="pa-3 h-100 list-card" @click="openHistory('annual')"><div class="d-flex justify-space-between align-center"><div><div class="text-caption">年度下载记录</div><div class="text-h6 font-weight-bold">{{ summary.annual_history_count || 0 }}</div></div><VIcon icon="mdi-chevron-right" /></div></VCard></VCol>
      </VRow>
      <div class="d-flex flex-wrap align-center ga-3 mt-4 mb-3">
        <VCombobox v-model="archiveYear" :items="archiveYearOptions" label="选择或输入年份" type="number" density="compact" hide-details class="monthly-year-select">
          <template #item="{ props: listProps, item }">
            <VListItem v-bind="listProps">
              <template #append><span class="year-option-badge" :class="`text-${yearScanBadge(item.raw).color}`">{{ yearScanBadge(item.raw).text }}</span></template>
            </VListItem>
          </template>
        </VCombobox>
        <VBtn color="primary" variant="tonal" size="large" :disabled="Number(archiveYear) < 1900 || Number(archiveYear) > new Date().getFullYear()" @click="openMonthlyArchive(annualEntry)">{{ annualEntry.latest || annualEntry.tasks.length ? '查看年度名单' : '扫描这一年' }}</VBtn>
      </div>
      <div v-if="annualEntry.scanTask" class="text-caption text-info">{{ annualEntry.scanTask.scan_progress || '全年扫描中' }}</div>
      <div v-if="annualEntry.failedTask" class="text-caption text-error">{{ annualEntry.failedTask.scan_error || '扫描中断，请查看日志后重试' }}</div>
      <div v-if="annualEntry.latest" class="text-caption">{{ archiveYear }} 年已保存 {{ annualEntry.movies }} 部电影；重新打开会读取已有名单。</div>
      <details v-if="archiveMonths.some(item => item.latest || item.tasks.length)" class="mt-4">
        <summary class="text-caption">查看以前保存的按月任务与名单</summary>
        <div class="monthly-month-grid mt-3">
          <button v-for="item in archiveMonths.filter(value => value.latest || value.tasks.length)" :key="item.month" type="button" class="monthly-month-tile monthly-month-scanned" @click="openMonthlyArchive(item)">
            <span class="monthly-month-name">{{ item.month }} 月</span>
            <span class="monthly-month-summary">{{ item.latest ? `${item.movies} 部` : item.tasks[0].scan_progress || '扫描中' }}</span>
          </button>
        </div>
      </details>
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
      <VCard v-if="dialog === 'active'" :title="dialogSource === 'annual' ? '年度正在下载 · 实时状态' : '全部正在下载 · 实时状态'">
        <VDialogCloseBtn @click="dialog = ''" />
        <VCardText>
          <VAlert v-if="!visibleActiveItems.length" type="info" variant="tonal" class="mb-3">当前没有此类正在下载的任务，或下载器暂未返回详情。</VAlert>
          <VDataTable v-else :headers="activeHeaders" :items="visibleActiveItems" :items-per-page="20" :items-per-page-options="pageSizes" density="compact" hover>
            <template #item.progress="{ item }"><div class="d-flex align-center ga-2"><VProgressLinear :model-value="item.progress" color="info" height="8" rounded /><span class="text-caption text-no-wrap">{{ item.progress }}%</span></div></template>
          </VDataTable>
          <div class="text-caption text-medium-emphasis mt-3">每 5 秒自动刷新。</div>
        </VCardText>
      </VCard>
      <VCard v-else-if="dialog === 'queue'" :title="dialogSource === 'annual' ? '年度等候下载' : '全部等候下载'">
        <VDialogCloseBtn @click="dialog = ''" />
        <VCardText>
          <div class="d-flex ga-2 mb-3"><VTextField v-model="queueSearch" label="搜索影片" prepend-inner-icon="mdi-magnify" clearable hide-details /><VBtn color="error" variant="tonal" @click="runAction('clear_queue', { source: dialogSource })">{{ dialogSource === 'annual' ? '清空年度等候' : '批量清空' }}</VBtn></div>
          <VDataTable :headers="queueHeaders" :items="visibleQueueItems" :search="queueSearch" :items-per-page="20" :items-per-page-options="pageSizes" item-value="key" density="compact" hover>
            <template #item.actions="{ item }"><VBtn size="small" color="error" variant="tonal" @click="runAction('remove_queue', { key: item.key })">取消下载</VBtn></template>
          </VDataTable>
        </VCardText>
      </VCard>
      <VCard v-else-if="dialog === 'history'" :title="historySource === 'annual' ? '年度下载记录' : '全部下载记录'">
        <VDialogCloseBtn @click="dialog = ''" />
        <VCardText>
          <VTabs v-model="historyStatus" show-arrows class="mb-3">
            <VTab v-for="option in historyStatusOptions" :key="option.value" :value="option.value">
              {{ option.title }} {{ historyView.status_counts?.[option.value] ?? 0 }}
            </VTab>
          </VTabs>
          <div class="d-flex flex-wrap align-center ga-2 mb-3">
            <VSelect v-model="historyPeriod" :items="historyPeriodOptions" label="时间范围" density="compact" hide-details style="min-width: 170px; max-width: 200px" />
            <VSelect v-if="historyPeriod === 'date'" v-model="historyDate" :items="historyDateOptions.slice(1)" label="提交日期" density="compact" hide-details style="min-width: 180px; max-width: 220px" />
            <VTextField v-model="historySearch" label="搜索影片或 TMDB ID" prepend-inner-icon="mdi-magnify" clearable density="compact" hide-details style="min-width: 220px" />
            <VSelect v-model="historyPageSize" :items="pageSizes" label="每页条数" density="compact" hide-details style="max-width: 140px" />
            <VBtn variant="tonal" :loading="historyBusy" @click="loadHistory">刷新</VBtn>
          </div>
          <div class="text-caption text-medium-emphasis mb-2">当前列表 {{ historyView.total || 0 }} 条；{{ historySource === 'annual' ? '只显示明确标记为年度方式提交的任务；旧版未记录来源的任务不猜测归属。' : '仅统计本插件提交的任务，含历史归档。' }}默认每页 100 条。待入库＝下载完成、等待 MP 整理；已整理＝MP 已整理、等待上传及 Emby 扫描；已整理未入库＝整理超过 24 小时仍未在 Emby 找到，需排查上传、扫描或匹配情况。</div>
          <VDataTable :headers="historyHeaders" :items="historyView.items || []" :items-per-page="historyPageSize" hide-default-footer density="compact" hover>
            <template #item.result="{ item }">
              <VChip size="small" :color="historyStatusMeta[item.view_status]?.color || 'secondary'" :title="item.organize_error || ''">{{ historyStatusMeta[item.view_status]?.title || '未知状态' }}</VChip>
            </template>
          </VDataTable>
          <div class="d-flex align-center justify-end ga-3 mt-3">
            <span class="text-caption">第 {{ historyView.page || 1 }} / {{ Math.max(1, Math.ceil((historyView.total || 0) / historyPageSize)) }} 页</span>
            <VBtn size="small" variant="tonal" :disabled="historyBusy || historyPage <= 1" @click="changeHistoryPage(-1)">上一页</VBtn>
            <VBtn size="small" variant="tonal" :disabled="historyBusy || historyPage * historyPageSize >= (historyView.total || 0)" @click="changeHistoryPage(1)">下一页</VBtn>
          </div>
        </VCardText>
      </VCard>
      <VCard v-else-if="dialog === 'monthly'" :title="`${monthlyView.task?.year || monthlyForm.year} 年${Number(monthlyView.task?.month ?? monthlyForm.month) === 0 ? '全年' : `${monthlyView.task?.month ?? monthlyForm.month} 月`}电影名单`">
        <VDialogCloseBtn @click="dialog = ''" />
        <VCardText>
          <div v-if="monthlyEditMode" class="monthly-task-row pa-4 mb-3">
            <div class="text-subtitle-1 mb-3">{{ monthlyForm.task_id ? '修改任务并重扫' : '新建年度扫描' }}</div>
            <div class="d-flex flex-wrap align-center ga-3">
              <VTextField v-model.number="monthlyForm.min_score" label="TMDB 最低评分" type="number" min="0" max="10" step="0.1" density="comfortable" hide-details style="max-width: 190px" />
              <VTextField v-if="Number(monthlyForm.month) === 0" v-model.number="monthlyForm.min_votes" label="高口碑最低评价人数" type="number" min="0" max="10000" density="comfortable" hide-details style="max-width: 200px" />
              <VTextField v-model.number="monthlyForm.batch_size" label="自动任务每轮下载（部）" type="number" min="1" max="50" density="comfortable" hide-details style="max-width: 210px" />
              <VBtn color="primary" variant="tonal" size="default" :loading="loading" :disabled="!monthlyForm.task_id && (state.monthly_tasks || []).length >= 5" @click="saveMonthly">{{ monthlyForm.task_id ? '保存并重扫' : '创建并扫描（不下载）' }}</VBtn>
              <VBtn v-if="monthlyForm.task_id" variant="text" size="default" @click="monthlyEditMode = false">取消</VBtn>
            </div>
            <div v-if="!monthlyForm.task_id && (state.monthly_tasks || []).length >= 5" class="text-caption text-warning mt-2">已有 5 个任务，请先删除不需要的任务；已保存的月份名单不受删除影响。</div>
          </div>
          <div v-for="task in selectedMonthTasks" :key="task.id" class="monthly-task-row pa-3 mb-3">
            <div class="d-flex flex-wrap align-center justify-space-between ga-2">
              <div class="text-caption">任务 ≥{{ task.min_score }} 分 · 每轮 {{ task.batch_size || 5 }} 部 · {{ task.scan_progress || '等待扫描' }}<span v-if="task.scan_error" class="text-error"> · {{ task.scan_error }}</span></div>
              <div class="d-flex flex-wrap ga-2">
                <VBtn size="default" variant="tonal" @click="editMonthly(task)">编辑任务</VBtn>
                <VBtn size="default" variant="tonal" :disabled="task.scan_state === 'running'" @click="runAction('monthly_rescan', { task_id: task.id })">重扫</VBtn>
                <VBtn v-if="!task.active" size="default" color="success" variant="tonal" :disabled="task.scan_state !== 'complete' || !controlForm.enabled" @click="runAction('monthly_start', { task_id: task.id })">开启自动任务（每轮 {{ task.batch_size || 5 }} 部）</VBtn>
                <VBtn v-else size="default" color="warning" variant="tonal" @click="runAction('monthly_pause', { task_id: task.id })">暂停自动下载</VBtn>
                <VBtn size="default" color="error" variant="tonal" @click="runAction('monthly_delete', { task_id: task.id })">删除任务</VBtn>
              </div>
            </div>
            <div class="text-caption text-medium-emphasis mt-2">自动任务与下方勾选无关：开启后立即尝试一轮，之后每 10 分钟从未入库且未在下载的候选中继续挑选；每轮最多 {{ task.batch_size || 5 }} 部。只下载勾选的电影，请用下方“下载选中”。</div>
          </div>
          <VBtn v-if="monthlyArchiveYear && !selectedMonthTasks.length && !monthlyEditMode" size="default" variant="tonal" class="mb-3" @click="monthlyEditMode = true">创建年度自动任务</VBtn>
          <VAlert v-if="!monthlyArchiveYear && !monthlyTaskId" type="info" variant="tonal" class="mb-3">此年度尚未扫描。设置最低评分和评价人数后点击“创建并扫描（不下载）”；扫描可能较长，完成后可手动选择下载或启动自动任务。</VAlert>
          <template v-if="monthlyArchiveYear || monthlyTaskId">
          <div class="d-flex flex-wrap align-center ga-2 mb-3">
            <VTextField v-model.number="monthlyMinScore" label="最低评分" type="number" min="0" max="10" step="0.1" density="compact" hide-details style="max-width: 125px" />
            <VSelect v-if="Number(monthlyArchiveMonth) === 0" v-model="annualCategory" :items="[{ title: '全部电影', value: 'all' }, { title: '主流电影', value: 'mainstream' }, { title: '高口碑电影', value: 'high_quality' }]" label="类型" density="compact" hide-details style="min-width: 155px; max-width: 180px" />
            <VSelect v-if="Number(monthlyArchiveMonth) === 0" v-model="annualReleaseMonth" :items="[{ title: '全年', value: 0 }, ...Array.from({ length: 12 }, (_, index) => ({ title: `${index + 1} 月`, value: index + 1 }))]" label="上映月份" density="compact" hide-details style="min-width: 135px; max-width: 155px" />
            <VSelect v-model="monthlyStatus" :items="monthlyStatusOptions.map(item => ({ title: `${item.title} ${monthlyView.counts?.[item.value] ?? (item.value === 'all' ? monthlyView.task?.candidate_count || 0 : 0)}`, value: item.value }))" label="状态" density="compact" hide-details style="min-width: 190px; max-width: 250px" />
            <VTextField v-model="monthlySearch" label="搜索电影或 TMDB ID" prepend-inner-icon="mdi-magnify" clearable density="compact" hide-details style="min-width: 220px" />
            <VSelect v-model="monthlyPageSize" :items="[{ title: '20', value: 20 }, { title: '50', value: 50 }, { title: '100', value: 100 }, { title: '1000（全部）', value: 1000 }]" label="每页条数" density="compact" hide-details style="max-width: 155px" @update:model-value="monthlyPage = 1; loadMonthly()" />
          </div>
          <div v-if="monthlyArchiveYear" class="d-flex flex-wrap align-center justify-start ga-2 mb-3">
            <VBtn variant="tonal" :loading="monthlyBusy" @click="loadMonthly(true)">立即核对 Emby</VBtn>
          </div>
          <div class="text-caption text-medium-emphasis mb-3">电影名单只读取 TMDB，不提前查询 PT 站。选中后点击“下载选中”，系统会先核对 Emby 和 MoviePilot 下载状态，再按随机下载的规则逐部搜索资源；找到才提交或进入等候队列。{{ monthlyView.emby_fresh ? '' : 'Emby 暂不可用，当前显示最近记录。' }}</div>
          <div v-if="monthlyView.batch_progress?.total" class="text-caption mb-3">批量下载：已处理 {{ monthlyView.batch_progress.done || 0 }}/{{ monthlyView.batch_progress.total }} · 已提交 {{ monthlyView.batch_progress.submitted || 0 }} · 等候 {{ monthlyView.batch_progress.queued || 0 }} · 跳过 {{ monthlyView.batch_progress.skipped || 0 }} · 失败 {{ monthlyView.batch_progress.errors || 0 }}<span v-if="monthlyView.batch_progress.message" class="text-error"> · {{ monthlyView.batch_progress.message }}</span></div>
          <div class="d-flex flex-wrap align-center ga-2 mb-3">
            <VBtn size="small" variant="tonal" :disabled="!(monthlyView.items || []).some(monthlyCanDownload)" @click="selectMonthlyPage">全选当前页</VBtn>
            <VBtn size="small" variant="text" :disabled="!monthlySelected.length" @click="monthlySelected = []">清空选择</VBtn>
            <VBtn size="small" color="success" :disabled="!monthlySelected.length || !monthlyArchiveYear || !controlForm.enabled" @click="downloadMonthlySelected">下载选中 {{ monthlySelected.length }} 部</VBtn>
          </div>
          <div v-if="!monthlyView.items?.length" class="text-center text-medium-emphasis pa-8">暂无符合当前筛选条件的电影</div>
          <div v-else class="monthly-movie-list">
            <div v-for="item in monthlyView.items" :key="item.tmdb_id" class="monthly-movie-row">
              <div class="monthly-row-check"><VCheckboxBtn :model-value="monthlySelected.includes(String(item.tmdb_id))" :disabled="!monthlyCanDownload(item)" density="compact" @update:model-value="toggleMonthlyMovie(item, $event)" /></div>
              <VImg v-if="posterUrl(item.poster_path)" :src="posterUrl(item.poster_path)" width="52" height="72" cover class="monthly-row-poster" />
              <div v-else class="monthly-row-poster monthly-row-poster-empty"><VIcon icon="mdi-movie-open" size="23" /></div>
              <div class="monthly-row-main">
                <a class="monthly-row-title" :href="`https://www.themoviedb.org/movie/${item.tmdb_id}?language=zh-CN`" target="_blank" rel="noopener noreferrer">{{ movieTitle(item) }} ({{ item.year }})</a>
                <div v-if="item.original_title && item.original_title !== movieTitle(item)" class="monthly-row-subtitle">{{ item.original_title }}</div>
                <div class="monthly-row-subtitle">{{ item.release_date || '日期未知' }}</div>
              </div>
              <div class="monthly-row-score">⭐ {{ Number(item.score || 0).toFixed(1) }}<span class="monthly-row-votes">{{ item.vote_count || 0 }} 人评价</span></div>
              <VChip size="small" :color="monthlyStatusColor(item)" class="monthly-row-status">{{ monthlyStatusLabel(item) }}</VChip>
            </div>
          </div>
          <div class="d-flex align-center justify-end ga-3 mt-3">
            <span class="text-caption">第 {{ monthlyView.page || 1 }} / {{ Math.max(1, Math.ceil((monthlyView.total || 0) / monthlyPageSize)) }} 页，共 {{ monthlyView.total || 0 }} 部</span>
            <VBtn size="small" variant="tonal" :disabled="monthlyBusy || monthlyPage <= 1" @click="monthlyPage--; loadMonthly()">上一页</VBtn>
            <VBtn size="small" variant="tonal" :disabled="monthlyBusy || monthlyPage * monthlyPageSize >= (monthlyView.total || 0)" @click="monthlyPage++; loadMonthly()">下一页</VBtn>
          </div>
          </template>
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
.monthly-task-row { border: 1px solid rgba(var(--v-theme-on-surface), .14); border-radius: 10px; }
.monthly-year-select { width: 190px; max-width: 100%; flex: none; }
.year-option-badge { min-width: 125px; text-align: right; font-size: 12px; white-space: nowrap; }
.monthly-month-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; }
.monthly-month-tile { min-height: 70px; display: flex; flex-direction: column; justify-content: center; align-items: flex-start; gap: 5px; padding: 9px 12px; border: 1px solid rgba(var(--v-theme-on-surface), .16); border-radius: 10px; color: inherit; text-align: left; }
.monthly-month-tile:disabled { opacity: .5; }
.monthly-month-tile:not(:disabled) { cursor: pointer; }
.monthly-month-tile:not(:disabled):hover { border-color: rgba(var(--v-theme-primary), .65); }
.monthly-month-scanned { background: rgba(var(--v-theme-primary), .10); border-color: rgba(var(--v-theme-primary), .4); cursor: pointer; }
.monthly-month-scanned:hover { background: rgba(var(--v-theme-primary), .20); }
.monthly-month-name { font-size: 16px; font-weight: 700; }
.monthly-month-summary { font-size: 12px; opacity: .78; }
.monthly-movie-list { border: 1px solid rgba(var(--v-theme-on-surface), .12); border-radius: 10px; overflow: hidden; }
.monthly-movie-row { display: grid; grid-template-columns: 28px 52px minmax(0, 1fr) 86px 200px; align-items: center; column-gap: 12px; min-height: 88px; padding: 8px 14px; border-bottom: 1px solid rgba(var(--v-theme-on-surface), .10); }
.monthly-row-check { width: 28px; min-width: 28px; justify-self: start; }
.monthly-row-check :deep(.v-selection-control) { min-width: 28px; width: 28px; }
.monthly-movie-row:last-child { border-bottom: 0; }
.monthly-movie-row:nth-child(even) { background: rgba(var(--v-theme-on-surface), .025); }
.monthly-row-poster { width: 52px; height: 72px; border-radius: 5px; overflow: hidden; justify-self: start; }
.monthly-row-poster-empty { height: 72px; display: flex; align-items: center; justify-content: center; background: rgba(var(--v-theme-on-surface), .08); }
.monthly-row-main { min-width: 0; flex: 1; }
.monthly-row-title { display: block; color: inherit; font-weight: 650; text-decoration: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.monthly-row-title:hover { color: rgb(var(--v-theme-primary)); }
.monthly-row-subtitle { margin-top: 3px; font-size: 12px; opacity: .65; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.monthly-resource-options { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }
.monthly-resource-option { max-width: 100%; padding: 4px 7px; border: 1px solid rgba(var(--v-theme-on-surface), .18); border-radius: 6px; color: inherit; font-size: 11px; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.monthly-resource-active { color: rgb(var(--v-theme-primary)); border-color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), .12); }
.monthly-row-score { width: 86px; justify-self: start; text-align: left; font-weight: 600; }
.monthly-row-votes { display: block; font-size: 11px; font-weight: 400; opacity: .65; }
.monthly-row-status { width: max-content; max-width: 200px; justify-self: start; white-space: nowrap; }
@media (max-width: 850px) { .monthly-month-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 600px) { .monthly-month-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .monthly-movie-row { grid-template-columns: 28px 44px minmax(0, 1fr); gap: 8px; padding: 8px; } .monthly-row-poster { width: 44px; height: 62px; } .monthly-row-score { grid-column: 3; width: auto; } .monthly-row-status { grid-column: 3; } .monthly-row-votes { display: none; } }
</style>
