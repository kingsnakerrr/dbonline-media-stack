<script setup>
import { onMounted, onUnmounted, ref } from 'vue'

const props = defineProps({ api: { type: Object, default: () => ({}) } })
const state = ref({ tasks: [], stats: {}, transferring: [] })
const busy = ref(false)
const error = ref('')
const transferDialog = ref(false)
const transferLimit = ref(20)
let timer
const unwrap = response => response?.data?.data ?? response?.data ?? response
async function refresh() {
  try {
    const result = unwrap(await props.api.post('plugin/RcloneManager/state', {
      transfer_limit: transferDialog.value ? transferLimit.value : 0,
    }))
    if (!result?.success) throw new Error(result?.message || '读取状态失败')
    state.value = result
    error.value = result.warning || ''
  } catch (e) { error.value = e?.message || String(e) }
}
async function control(action) {
  if (busy.value) return
  if (action === 'stop' && !confirm('停止 Rclone Manager？运行中的传输会中断。')) return
  if (action === 'uninstall' && !confirm('卸载 Rclone Manager 服务容器？镜像和任务数据会保留，正在传输的任务会中断。')) return
  busy.value = true
  try {
    const result = unwrap(await props.api.post('plugin/RcloneManager/control', { action }))
    if (!result?.success) throw new Error(result?.message || '操作失败')
    await refresh()
  } catch (e) { error.value = e?.message || String(e) }
  finally { busy.value = false }
}
function bytes(value) {
  const n = Number(value) || 0
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n, i = -1
  do { v /= 1024; i++ } while (v >= 1024 && i < units.length - 1)
  return `${v.toFixed(1)} ${units[i]}`
}
onMounted(() => { refresh(); timer = setInterval(refresh, 3000) })
onUnmounted(() => clearInterval(timer))
function openTransfers() { transferDialog.value = true; refresh() }
function closeTransfers() { transferDialog.value = false; refresh() }
function changeTransferLimit() { refresh() }
function managerUrl() { return state.value.url || `http://${window.location.hostname}:7071` }
function taskStatus(task) {
  if (!state.value.running || task.display_status === 'stopped') return '任务已关闭'
  return task.display_status === 'running' ? '上传中' : '待机'
}
</script>

<template>
  <main class="panel">
    <header><div><h2>Rclone Manager 控制台 <small>v{{ state.version || '0.3.3' }}</small></h2><p>独立服务仍按原方式运行；此处只监控和开关。</p></div><a v-if="state.installed" :href="managerUrl()" target="_blank" rel="noopener noreferrer">打开原管理界面 ↗</a></header>
    <p v-if="error" class="error">{{ error }}</p>
    <section v-if="state.installed === false"><h3>尚未安装独立服务</h3><p>安装会使用这台机器已有的 Rclone Manager 镜像；不会改动任务数据。</p><button :disabled="busy || !state.image_available" @click="control('install')">安装并启动</button><p v-if="!state.image_available">本机没有可用镜像，需先按原方式部署镜像。</p></section>
    <template v-else>
    <section class="summary"><div><span>服务状态</span><strong :class="state.running ? 'ok' : 'off'">{{ state.running ? '运行中' : '已停止' }}</strong><small>更新于 {{ state.updated_at || '读取中' }}</small></div><div><span>运行任务</span><strong>{{ state.tasks.filter(t => t.display_status === 'running').length }}</strong><small>共 {{ state.tasks.length }} 个任务</small></div><div><span>传输速度</span><strong>{{ bytes(state.stats.speed) }}/s</strong><small>已传输 {{ bytes(state.stats.bytes) }}</small></div></section>
    <div class="actions"><button v-if="!state.running" :disabled="busy" @click="control('start')">启动服务</button><button v-else class="danger" :disabled="busy" @click="control('stop')">停止服务</button><button class="secondary" @click="refresh">刷新</button><button class="danger" :disabled="busy" @click="control('uninstall')">卸载软件</button></div>
    <section class="transfer-card" @click="openTransfers" role="button" tabindex="0" @keydown.enter="openTransfers"><div><h3>实时传输</h3><p>{{ state.running ? `当前 ${state.transfer_count || 0} 个文件正在传输` : '服务未运行' }}</p></div><button class="secondary" @click.stop="openTransfers">查看弹窗 ↗</button></section>
    <section class="task-section"><div class="section-heading"><h3>任务状态</h3><small>共 {{ state.tasks.length }} 个任务</small></div><div v-if="state.tasks.length" class="task-grid"><div v-for="task in state.tasks" :key="task.id" class="task-item"><div class="task-top"><strong :title="task.name">{{ task.name }}</strong><span class="status-pill" :class="!state.running || task.display_status === 'stopped' ? 'status-stopped' : `status-${task.display_status}`">{{ taskStatus(task) }}</span></div><small v-if="state.running && task.error_hint" class="task-error" :title="task.error_hint">⚠ {{ task.error_hint }}</small></div></div><p v-else>暂无任务。</p></section>
    </template>
    <div v-if="transferDialog" class="overlay" @click.self="closeTransfers"><div class="dialog" role="dialog" aria-modal="true" aria-label="实时传输"><header><div><h3>实时传输</h3><small>当前 {{ state.transfer_count || 0 }} 条 · 每 3 秒刷新</small></div><div class="dialog-actions"><label>显示 <select v-model.number="transferLimit" @change="changeTransferLimit"><option :value="20">20 条</option><option :value="50">50 条</option><option :value="100">100 条</option><option :value="1000">1000 条</option></select></label><button class="secondary" @click="closeTransfers">关闭</button></div></header><div class="transfer-list"><p v-if="!state.running">服务未运行。</p><p v-else-if="!state.transferring.length">当前没有正在传输的文件。</p><div v-for="(file, index) in state.transferring" :key="`${file.name}-${index}`" class="row"><strong>{{ file.name || '未命名文件' }}</strong><span>{{ bytes(file.bytes) }} / {{ bytes(file.size) }} · {{ bytes(file.speed) }}/s <template v-if="file.percentage != null">· {{ file.percentage }}%</template></span></div><p v-if="state.transfer_count > state.transferring.length">仅显示前 {{ state.transferring.length }} 条，可调整显示数量。</p></div></div></div>
  </main>
</template>

<style scoped>
.panel{padding:24px;background:#11141d;color:#e8eaf4;min-height:600px;font-family:Arial,'Microsoft YaHei',sans-serif}header{display:flex;justify-content:space-between;gap:20px;align-items:center;border-bottom:1px solid #323849;padding-bottom:16px}h2{margin:0}h2 small{font-size:12px;color:#a877ef}p,small,span{color:#aeb6c8}a,button{background:#874de0;color:white;text-decoration:none;border:0;border-radius:8px;padding:10px 15px;cursor:pointer}button:disabled{opacity:.5}.summary{display:grid;grid-template-columns:repeat(3,minmax(160px,1fr));gap:14px;margin:20px 0}.summary>div,section:not(.summary){background:#1c2230;border:1px solid #343d50;border-radius:10px;padding:18px}.summary>div{display:flex;flex-direction:column;gap:8px}.summary strong{font-size:23px}.ok{color:#5fe0aa}.off,.error{color:#ff999e}.actions{display:flex;gap:10px;margin-bottom:18px}.danger{background:#a43e4c}.secondary{background:#343a4b}.row{display:flex;justify-content:space-between;gap:20px;border-top:1px solid #343d50;padding:10px 0;overflow-wrap:anywhere}section+section{margin-top:18px}@media(max-width:700px){.summary{grid-template-columns:1fr}.row,header{flex-direction:column}}
.transfer-card{display:flex;justify-content:space-between;align-items:center;gap:20px;cursor:pointer}.transfer-card h3{margin:0}.transfer-card p{margin-bottom:0}.overlay{position:fixed;inset:0;z-index:10000;background:#000a;display:flex;align-items:center;justify-content:center;padding:24px}.dialog{width:min(100%,1100px);max-height:85vh;display:flex;flex-direction:column;background:#1c2230;border:1px solid #4b5469;border-radius:12px;padding:20px}.dialog h3{margin:0 0 8px}.dialog-actions{display:flex;align-items:center;gap:12px}.dialog-actions label{color:#aeb6c8}select{background:#11141d;color:#e8eaf4;border:1px solid #4b5469;border-radius:7px;padding:8px}.transfer-list{overflow-y:auto;min-height:100px;padding-right:6px}.transfer-list .row{align-items:flex-start}.transfer-list .row strong{max-width:65%}@media(max-width:700px){.dialog header{align-items:stretch}.dialog-actions{justify-content:space-between}.transfer-list .row strong{max-width:none}}
.section-heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.section-heading h3{margin:0}.task-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.task-item{min-width:0;background:#171c29;border:1px solid #303a4c;border-radius:9px;padding:14px 16px}.task-top{display:flex;justify-content:space-between;align-items:center;gap:14px}.task-top strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.status-pill{flex:none;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:700}.status-running{color:#68e3b4;background:#173d34}.status-idle{color:#b5c4d9;background:#303a4b}.status-stopped{color:#a7aebb;background:#2a2e38}.task-error{display:block;margin-top:9px;color:#e9b878;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}@media(max-width:700px){.task-grid{grid-template-columns:1fr}}
</style>
