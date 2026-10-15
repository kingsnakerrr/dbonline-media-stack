import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createVNode:_createVNode,createElementVNode:_createElementVNode,withKeys:_withKeys,unref:_unref,createElementBlock:_createElementBlock,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = { class: "d-flex align-center ga-3 mb-4" };
const _hoisted_2 = { class: "status-grid mb-3" };
const _hoisted_3 = { class: "status-item" };
const _hoisted_4 = { class: "d-flex align-center justify-space-between ga-3" };
const _hoisted_5 = { class: "text-h6 font-weight-bold" };
const _hoisted_6 = { class: "status-item" };
const _hoisted_7 = { class: "d-flex align-center justify-space-between mb-2" };
const _hoisted_8 = { class: "text-h6 font-weight-bold" };
const _hoisted_9 = { class: "status-item" };
const _hoisted_10 = { class: "status-item" };
const _hoisted_11 = { class: "d-flex align-center justify-space-between" };
const _hoisted_12 = { class: "text-h6 font-weight-bold" };
const _hoisted_13 = { class: "status-item" };
const _hoisted_14 = { class: "d-flex align-center justify-space-between" };
const _hoisted_15 = { class: "text-h6 font-weight-bold" };
const _hoisted_16 = { class: "status-item" };
const _hoisted_17 = { class: "d-flex align-center justify-space-between" };
const _hoisted_18 = { class: "text-h6 font-weight-bold" };
const _hoisted_19 = { class: "status-item" };
const _hoisted_20 = { class: "d-flex align-center justify-space-between" };
const _hoisted_21 = { class: "text-h6 font-weight-bold" };
const _hoisted_22 = { class: "status-secondary-grid mb-3" };
const _hoisted_23 = { class: "d-flex align-center justify-space-between ga-2 mb-2" };
const _hoisted_24 = { class: "min-w-0" };
const _hoisted_25 = { class: "text-caption text-truncate" };
const _hoisted_26 = { class: "text-right text-no-wrap" };
const _hoisted_27 = { class: "text-h6 font-weight-bold" };
const _hoisted_28 = { class: "text-caption" };
const _hoisted_29 = { class: "disk-controls-grid" };
const _hoisted_30 = { class: "mt-2 d-flex align-center flex-wrap ga-2" };
const _hoisted_31 = { class: "text-caption disk-rule-text" };
const _hoisted_32 = { class: "d-flex flex-wrap ga-2" };
const _hoisted_33 = { key: 0 };
const _hoisted_34 = { class: "d-flex align-center ga-2" };
const _hoisted_35 = { class: "text-caption text-no-wrap" };
const _hoisted_36 = { class: "d-flex ga-2 mb-3" };
const _hoisted_37 = { class: "d-flex flex-wrap align-center ga-2 mb-3" };
const _hoisted_38 = { class: "text-caption text-medium-emphasis mb-2" };
const _hoisted_39 = { class: "d-flex align-center justify-end ga-3 mt-3" };
const _hoisted_40 = { class: "text-caption" };
const _hoisted_41 = { class: "d-flex ga-2 mb-3" };
const _hoisted_42 = { class: "d-flex ga-2 mb-3" };
const _hoisted_43 = { class: "text-caption text-medium-emphasis mb-2" };

const {computed,onMounted,onUnmounted,ref,watch} = await importShared('vue');


const accessTokenKey = 'smartmoviepush_access_token';

const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
},
  setup(__props) {

const props = __props;

const loading = ref(false);
const error = ref('');
const message = ref('');
const accessReady = ref(false);
const accessPassword = ref('');
const accessToken = ref('');
const dialog = ref('');
const dialogOpen = computed({
  get: () => Boolean(dialog.value),
  set: value => { if (!value) dialog.value = ''; },
});
const queueSearch = ref('');
const historySearch = ref('');
const historyDate = ref('');
const historyPage = ref(1);
const historyPageSize = ref(100);
const historyBusy = ref(false);
const historyView = ref({ dates: [], items: [], total: 0, page: 1 });
const historyDateOptions = computed(() => [
  { title: '全部日期', value: '' },
  ...(historyView.value.dates || []).map(date => ({ title: date, value: date })),
]);
const suppressedSearch = ref('');
const logSearch = ref('');
const showDetailedLogs = ref(false);
const logsRefreshing = ref(false);
const logsRefreshedAt = ref('');
const pageSizes = [20, 50, 100];
const briefLogCategories = new Set(['提交下载', '提交失败', '推送成功', '推送失败', '整理完成', 'Emby 已入库', '每日统计']);
const visibleLogs = computed(() => showDetailedLogs.value
  ? (state.value.logs || [])
  : (state.value.logs || []).filter(item => briefLogCategories.has(item.category)));

async function toggleDetailedLogs() {
  showDetailedLogs.value = !showDetailedLogs.value;
  await refreshLogs();
}
async function refreshLogs() {
  logsRefreshing.value = true;
  try {
    if (await loadStatus(true)) logsRefreshedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  } finally {
    logsRefreshing.value = false;
  }
}
async function openLogs() {
  dialog.value = 'logs';
  await refreshLogs();
}
async function loadHistory() {
  if (!accessToken.value) return
  historyBusy.value = true;
  try {
    const response = await props.api.post('plugin/SmartMoviePush/secure_history', {
      access_token: accessToken.value,
      date: historyDate.value,
      search: historySearch.value,
      page: historyPage.value,
      page_size: historyPageSize.value,
    });
    const body = envelope(response);
    if (body?.locked) { lockLocally(); return }
    if (body?.success === false) { error.value = body?.message || '加载下载记录失败'; return }
    historyView.value = unwrap(response);
    historyPage.value = historyView.value.page || 1;
  } catch (err) {
    error.value = err?.message || '加载下载记录失败';
  } finally {
    historyBusy.value = false;
  }
}
async function openHistory() {
  historyPage.value = 1;
  dialog.value = 'history';
  await loadHistory();
}
let historySearchTimer;
watch(historySearch, () => {
  window.clearTimeout(historySearchTimer);
  if (dialog.value === 'history') {
    historyPage.value = 1;
    historySearchTimer = window.setTimeout(loadHistory, 300);
  }
});
watch([historyDate, historyPageSize], () => {
  if (dialog.value === 'history') { historyPage.value = 1; loadHistory(); }
});
async function changeHistoryPage(delta) {
  historyPage.value += delta;
  await loadHistory();
}
const state = ref({
  summary: {}, queue: [], history: [], suppressed: [], logs: [],
  telegram: { source: '', admins_override: '', chat_id_override: '', sources: [] },
  disk_guard: { enabled: true, active: false, free_gb: 0, threshold_gb: 300, recover_gb: 350, waiting: [] },
});
const telegramForm = ref({ source: '', admins_override: '', chat_id_override: '' });
const diskForm = ref({ disk_guard_enabled: true, disk_guard_path: '/home', disk_guard_threshold_gb: 300, disk_guard_recover_gb: 350 });
const pushForm = ref({ limit: 20, test_limit: 2, max_active_downloads: 20, max_searches: 80, site_ids: [], min_score: 6 });
const controlForm = ref({ enabled: true, auto_push: false, auto_download: false, push_interval_minutes: 60 });
const intervalItems = [30, 60, 120, 180, 240, 300].map(value => ({ title: `${value} 分钟`, value }));
const downloadModeItems = [
  { title: '自动下载', value: true },
  { title: '手动确认', value: false },
];

const unwrap = response => response?.data?.data ?? response?.data ?? response;
const envelope = response => (response?.success !== undefined ? response : (response?.data ?? response));

function applyState(data, syncForms = true) {
  if (!data) return
  state.value = data;
  if (!syncForms) return
  telegramForm.value = {
    source: data.telegram?.source || '',
    admins_override: data.telegram?.admins_override || '',
    chat_id_override: data.telegram?.chat_id_override || '',
  };
  diskForm.value = {
    disk_guard_enabled: data.disk_guard?.enabled !== false,
    disk_guard_path: data.disk_guard?.path || '/home',
    disk_guard_threshold_gb: data.disk_guard?.threshold_gb || 300,
    disk_guard_recover_gb: data.disk_guard?.recover_gb || 350,
  };
  pushForm.value = {
    limit: data.summary?.limit || 20,
    test_limit: data.summary?.test_limit || 2,
    max_active_downloads: data.summary?.max_active_downloads || 20,
    max_searches: data.summary?.max_searches || 80,
    site_ids: data.summary?.site_ids || [],
    min_score: data.summary?.min_score ?? 6,
  };
  controlForm.value = {
    enabled: data.summary?.enabled !== false,
    auto_push: Boolean(data.summary?.auto_push),
    auto_download: Boolean(data.summary?.auto_download),
    push_interval_minutes: data.summary?.push_interval_minutes || 60,
  };
}

async function loadStatus(silent = false) {
  if (!accessToken.value) return
  if (!silent) loading.value = true;
  if (!silent) error.value = '';
  try {
    const response = await props.api.post('plugin/SmartMoviePush/secure_status', { access_token: accessToken.value });
    const body = envelope(response);
    if (body?.locked || body?.success === false) {
      lockLocally();
      return false
    }
    applyState(unwrap(response), !silent);
    return true
  } catch (err) {
    error.value = err?.message || '加载失败';
    return false
  } finally {
    if (!silent) loading.value = false;
  }
}

async function runAction(action, extra = {}) {
  loading.value = true;
  error.value = '';
  message.value = '';
  try {
    const response = await props.api.post('plugin/SmartMoviePush/ui_action', { action, ...extra, access_token: accessToken.value });
    const body = envelope(response);
    if (body?.locked) { lockLocally(); return }
    if (body?.success === false) error.value = body?.message || '操作失败';
    else message.value = body?.message || '操作完成';
    applyState(body?.data);
  } catch (err) {
    error.value = err?.message || '操作失败';
  } finally {
    loading.value = false;
  }
}

async function saveTelegram() {
  loading.value = true;
  error.value = '';
  message.value = '';
  try {
    const response = await props.api.post('plugin/SmartMoviePush/ui_config', { ...telegramForm.value, access_token: accessToken.value });
    const body = envelope(response);
    if (body?.locked) { lockLocally(); return }
    if (body?.success === false) { error.value = body?.message || '保存失败'; return }
    if (body?.warning) error.value = body?.message || body.warning;
    else message.value = body?.message || 'Telegram 设置已保存';
    applyState(body?.data);
  } catch (err) {
    error.value = err?.message || '保存失败';
  } finally {
    loading.value = false;
  }
}

async function saveControlSettings(extra = {}) {
  Object.assign(controlForm.value, extra);
  loading.value = true;
  error.value = '';
  message.value = '';
  try {
    const response = await props.api.post('plugin/SmartMoviePush/ui_config', { ...extra, access_token: accessToken.value });
    const body = envelope(response);
    if (body?.locked) { lockLocally(); return }
    if (body?.success === false) { error.value = body?.message || '保存失败'; return }
    message.value = body?.message || '控制设置已保存';
    applyState(body?.data);
  } catch (err) {
    error.value = err?.message || '保存失败';
  } finally {
    loading.value = false;
  }
}

async function saveDiskGuard() {
  loading.value = true;
  error.value = '';
  message.value = '';
  try {
    const response = await props.api.post('plugin/SmartMoviePush/ui_config', { ...diskForm.value, access_token: accessToken.value });
    const body = envelope(response);
    if (body?.locked) { lockLocally(); return }
    if (body?.success === false) { error.value = body?.message || '保存失败'; return }
    message.value = body?.message || '硬盘保护设置已保存';
    applyState(body?.data);
  } catch (err) {
    error.value = err?.message || '保存失败';
  } finally {
    loading.value = false;
  }
}

async function savePushSettings() {
  loading.value = true;
  error.value = '';
  message.value = '';
  try {
    const response = await props.api.post('plugin/SmartMoviePush/ui_config', { ...pushForm.value, access_token: accessToken.value });
    const body = envelope(response);
    if (body?.locked) { lockLocally(); return }
    if (body?.success === false) { error.value = body?.message || '保存失败'; return }
    message.value = body?.message || '推送与下载设置已保存';
    applyState(body?.data);
  } catch (err) {
    error.value = err?.message || '保存失败';
  } finally {
    loading.value = false;
  }
}

const summary = computed(() => state.value.summary || {});
const diskGuard = computed(() => state.value.disk_guard || {});
const queueHeaders = [
  { title: '影片', key: 'title' },
  { title: '加入时间', key: 'created_at', width: 180 },
  { title: '重试', key: 'attempts', width: 80 },
  { title: '操作', key: 'actions', sortable: false, width: 120 },
];
const historyHeaders = [
  { title: '影片', key: 'title' },
  { title: '提交时间', key: 'submitted_at', width: 190 },
  { title: '下载完成', key: 'download_completed_at', width: 190 },
  { title: '整理 / 入库', key: 'result', width: 190 },
];
const suppressedHeaders = [
  { title: '影片', key: 'title' },
  { title: '加入时间', key: 'added_at', width: 190 },
  { title: '操作', key: 'actions', sortable: false, width: 120 },
];
const diskHeaders = [
  { title: '种子', key: 'title' },
  { title: '分类', key: 'category', width: 130 },
  { title: '暂停时间', key: 'added_at', width: 190 },
];
const activeHeaders = [
  { title: '影片', key: 'title' },
  { title: '进度', key: 'progress', width: 240 },
  { title: '实时速度', key: 'speed', width: 150 },
  { title: '状态', key: 'state', width: 120 },
  { title: '剩余时间', key: 'eta', width: 120 },
];
const logHeaders = [
  { title: '时间', key: 'created_at', width: 210 },
  { title: '类型', key: 'category', width: 130 },
  { title: '内容', key: 'message' },
];

let refreshTimer;
let messageTimer;
let errorTimer;
watch(message, value => {
  window.clearTimeout(messageTimer);
  if (value) messageTimer = window.setTimeout(() => { message.value = ''; }, 3000);
});
watch(error, value => {
  window.clearTimeout(errorTimer);
  if (value) errorTimer = window.setTimeout(() => { error.value = ''; }, 3000);
});
function lockLocally() {
  window.localStorage.removeItem(accessTokenKey);
  window.clearInterval(refreshTimer);
  accessToken.value = '';
  accessReady.value = false;
  dialog.value = '';
}

function startRefresh() {
  window.clearInterval(refreshTimer);
  refreshTimer = window.setInterval(() => loadStatus(true), 5000);
}

async function checkAccess() {
  const token = window.localStorage.getItem(accessTokenKey) || '';
  if (!token) return
  loading.value = true;
  try {
    const response = await props.api.post('plugin/SmartMoviePush/auth_check', { access_token: token });
    const body = envelope(response);
    if (!body?.success || !body?.unlocked) {
      lockLocally();
      return
    }
    accessToken.value = token;
    accessReady.value = true;
    await loadStatus();
    startRefresh();
  } catch (err) {
    error.value = err?.message || '验证插件访问权限失败';
  } finally {
    loading.value = false;
  }
}

async function unlockAccess() {
  if (!accessPassword.value) {
    error.value = '请输入插件访问密码';
    return
  }
  loading.value = true;
  error.value = '';
  try {
    const response = await props.api.post('plugin/SmartMoviePush/auth_unlock', { password: accessPassword.value });
    const body = envelope(response);
    if (!body?.success || !body?.access_token) {
      error.value = body?.message || '密码错误';
      return
    }
    accessToken.value = body.access_token;
    window.localStorage.setItem(accessTokenKey, body.access_token);
    accessPassword.value = '';
    accessReady.value = true;
    message.value = '插件已解锁';
    await loadStatus();
    startRefresh();
  } catch (err) {
    error.value = err?.message || '解锁失败';
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  await checkAccess();
});
onUnmounted(() => {
  window.clearInterval(refreshTimer);
  window.clearTimeout(historySearchTimer);
  window.clearTimeout(messageTimer);
  window.clearTimeout(errorTimer);
});

return (_ctx, _cache) => {
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VAvatar = _resolveComponent("VAvatar");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VDialogCloseBtn = _resolveComponent("VDialogCloseBtn");
  const _component_VProgressLinear = _resolveComponent("VProgressLinear");
  const _component_VDataTable = _resolveComponent("VDataTable");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VChip = _resolveComponent("VChip");
  const _component_VDialog = _resolveComponent("VDialog");
  const _component_VContainer = _resolveComponent("VContainer");

  return (_openBlock(), _createBlock(_component_VContainer, {
    fluid: "",
    class: "pa-2"
  }, {
    default: _withCtx(() => [
      (error.value)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 0,
            type: "error",
            variant: "tonal",
            class: "mb-3",
            closable: ""
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(error.value), 1)
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      (message.value)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 1,
            type: "success",
            variant: "tonal",
            class: "mb-3",
            closable: ""
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(message.value), 1)
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      (!accessReady.value)
        ? (_openBlock(), _createBlock(_component_VCard, {
            key: 2,
            variant: "tonal",
            color: "primary",
            class: "access-lock-card pa-6 mx-auto mt-8"
          }, {
            default: _withCtx(() => [
              _createElementVNode("div", _hoisted_1, [
                _createVNode(_component_VAvatar, {
                  color: "primary",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VIcon, { icon: "mdi-lock" })
                  ]),
                  _: 1
                }),
                _cache[51] || (_cache[51] = _createElementVNode("div", null, [
                  _createElementVNode("div", { class: "text-h6 font-weight-bold" }, "智能下载影视资源_惹咪之北"),
                  _createElementVNode("div", { class: "text-body-2 text-medium-emphasis" }, "私人插件，首次使用请联系 @SDFSDFSF12321 获取密码。验证成功后当前浏览器会记住。")
                ], -1))
              ]),
              _createVNode(_component_VTextField, {
                modelValue: accessPassword.value,
                "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((accessPassword).value = $event)),
                label: "插件访问密码",
                type: "password",
                autocomplete: "current-password",
                "prepend-inner-icon": "mdi-key",
                autofocus: "",
                disabled: loading.value,
                onKeyup: _withKeys(unlockAccess, ["enter"])
              }, null, 8, ["modelValue", "disabled"]),
              _createVNode(_component_VBtn, {
                color: "primary",
                block: "",
                size: "large",
                loading: loading.value,
                onClick: unlockAccess
              }, {
                default: _withCtx(() => [...(_cache[52] || (_cache[52] = [
                  _createTextVNode("解锁插件", -1)
                ]))]),
                _: 1
              }, 8, ["loading"])
            ]),
            _: 1
          }))
        : (_openBlock(), _createElementBlock(_Fragment, { key: 3 }, [
            _createElementVNode("div", _hoisted_2, [
              _createElementVNode("div", _hoisted_3, [
                _createVNode(_component_VCard, {
                  variant: "tonal",
                  color: controlForm.value.enabled ? 'success' : 'secondary',
                  class: "pa-4 h-100 status-card"
                }, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_4, [
                      _createElementVNode("div", null, [
                        _cache[53] || (_cache[53] = _createElementVNode("div", { class: "text-caption" }, "插件状态", -1)),
                        _createElementVNode("div", _hoisted_5, _toDisplayString(controlForm.value.enabled ? '已启用' : '已关闭'), 1)
                      ]),
                      _createVNode(_component_VSwitch, {
                        modelValue: controlForm.value.enabled,
                        "onUpdate:modelValue": [
                          _cache[1] || (_cache[1] = $event => ((controlForm.value.enabled) = $event)),
                          _cache[2] || (_cache[2] = value => saveControlSettings({ enabled: value }))
                        ],
                        color: "success",
                        "hide-details": "",
                        loading: loading.value
                      }, null, 8, ["modelValue", "loading"])
                    ])
                  ]),
                  _: 1
                }, 8, ["color"])
              ]),
              _createElementVNode("div", _hoisted_6, [
                _createVNode(_component_VCard, {
                  variant: "tonal",
                  color: "primary",
                  class: "pa-4 h-100 status-card"
                }, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_7, [
                      _createElementVNode("div", null, [
                        _cache[54] || (_cache[54] = _createElementVNode("div", { class: "text-caption" }, "定时推送", -1)),
                        _createElementVNode("div", _hoisted_8, _toDisplayString(diskGuard.value.active ? '硬盘保护暂停' : (controlForm.value.auto_push ? '已开启' : '已暂停')), 1)
                      ]),
                      _createVNode(_component_VSwitch, {
                        modelValue: controlForm.value.auto_push,
                        "onUpdate:modelValue": [
                          _cache[3] || (_cache[3] = $event => ((controlForm.value.auto_push) = $event)),
                          _cache[4] || (_cache[4] = value => saveControlSettings({ auto_push: value }))
                        ],
                        color: "primary",
                        "hide-details": "",
                        disabled: !controlForm.value.enabled
                      }, null, 8, ["modelValue", "disabled"])
                    ]),
                    _createVNode(_component_VSelect, {
                      modelValue: controlForm.value.push_interval_minutes,
                      "onUpdate:modelValue": [
                        _cache[5] || (_cache[5] = $event => ((controlForm.value.push_interval_minutes) = $event)),
                        _cache[6] || (_cache[6] = value => saveControlSettings({ push_interval_minutes: value }))
                      ],
                      items: _unref(intervalItems),
                      density: "compact",
                      label: "推送间隔",
                      "hide-details": "",
                      disabled: !controlForm.value.enabled
                    }, null, 8, ["modelValue", "items", "disabled"])
                  ]),
                  _: 1
                })
              ]),
              _createElementVNode("div", _hoisted_9, [
                _createVNode(_component_VCard, {
                  variant: "tonal",
                  color: "warning",
                  class: "pa-4 h-100 status-card"
                }, {
                  default: _withCtx(() => [
                    _cache[55] || (_cache[55] = _createElementVNode("div", { class: "text-caption mb-2" }, "下载模式", -1)),
                    _createVNode(_component_VSelect, {
                      modelValue: controlForm.value.auto_download,
                      "onUpdate:modelValue": [
                        _cache[7] || (_cache[7] = $event => ((controlForm.value.auto_download) = $event)),
                        _cache[8] || (_cache[8] = value => saveControlSettings({ auto_download: value }))
                      ],
                      items: downloadModeItems,
                      density: "compact",
                      "hide-details": "",
                      disabled: !controlForm.value.enabled
                    }, null, 8, ["modelValue", "disabled"])
                  ]),
                  _: 1
                })
              ]),
              _createElementVNode("div", _hoisted_10, [
                _createVNode(_component_VCard, {
                  variant: "tonal",
                  color: "info",
                  class: "pa-4 h-100 list-card status-card",
                  onClick: _cache[9] || (_cache[9] = $event => (dialog.value = 'active'))
                }, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_11, [
                      _createElementVNode("div", null, [
                        _cache[56] || (_cache[56] = _createElementVNode("div", { class: "text-caption" }, "正在下载（点击看实时详情）", -1)),
                        _createElementVNode("div", _hoisted_12, _toDisplayString(summary.value.active_downloads || 0) + "/" + _toDisplayString(summary.value.max_active_downloads || 20), 1)
                      ]),
                      _createVNode(_component_VIcon, { icon: "mdi-chevron-right" })
                    ])
                  ]),
                  _: 1
                })
              ]),
              _createElementVNode("div", _hoisted_13, [
                _createVNode(_component_VCard, {
                  variant: "tonal",
                  color: "secondary",
                  class: "pa-4 h-100 list-card status-card",
                  onClick: _cache[10] || (_cache[10] = $event => (dialog.value = 'queue'))
                }, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_14, [
                      _createElementVNode("div", null, [
                        _cache[57] || (_cache[57] = _createElementVNode("div", { class: "text-caption" }, "等候下载", -1)),
                        _createElementVNode("div", _hoisted_15, _toDisplayString(state.value.queue.length), 1),
                        _cache[58] || (_cache[58] = _createElementVNode("div", { class: "text-caption mt-1" }, "搜索、取消任务或批量清空", -1))
                      ]),
                      _createVNode(_component_VIcon, { icon: "mdi-chevron-right" })
                    ])
                  ]),
                  _: 1
                })
              ]),
              _createElementVNode("div", _hoisted_16, [
                _createVNode(_component_VCard, {
                  variant: "tonal",
                  color: "primary",
                  class: "pa-4 h-100 list-card status-card",
                  onClick: openHistory
                }, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_17, [
                      _createElementVNode("div", null, [
                        _cache[59] || (_cache[59] = _createElementVNode("div", { class: "text-caption" }, "下载记录", -1)),
                        _createElementVNode("div", _hoisted_18, _toDisplayString(state.value.history.length), 1),
                        _cache[60] || (_cache[60] = _createElementVNode("div", { class: "text-caption mt-1" }, "按日期查看完整记录", -1))
                      ]),
                      _createVNode(_component_VIcon, { icon: "mdi-chevron-right" })
                    ])
                  ]),
                  _: 1
                })
              ]),
              _createElementVNode("div", _hoisted_19, [
                _createVNode(_component_VCard, {
                  variant: "tonal",
                  color: "error",
                  class: "pa-4 h-100 list-card status-card",
                  onClick: _cache[11] || (_cache[11] = $event => (dialog.value = 'suppressed'))
                }, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_20, [
                      _createElementVNode("div", null, [
                        _cache[61] || (_cache[61] = _createElementVNode("div", { class: "text-caption" }, "不再推送列表", -1)),
                        _createElementVNode("div", _hoisted_21, _toDisplayString(state.value.suppressed.length), 1),
                        _cache[62] || (_cache[62] = _createElementVNode("div", { class: "text-caption mt-1" }, "搜索、取消排除或批量清空", -1))
                      ]),
                      _createVNode(_component_VIcon, { icon: "mdi-chevron-right" })
                    ])
                  ]),
                  _: 1
                })
              ])
            ]),
            _createElementVNode("div", _hoisted_22, [
              _createVNode(_component_VCard, {
                variant: "tonal",
                color: diskGuard.value.active ? 'error' : 'success',
                class: "pa-3 disk-guard-card compact-top-card"
              }, {
                default: _withCtx(() => [
                  _createElementVNode("div", _hoisted_23, [
                    _createElementVNode("div", _hoisted_24, [
                      _cache[63] || (_cache[63] = _createElementVNode("div", { class: "text-subtitle-1 font-weight-bold" }, "硬盘空间保护", -1)),
                      _createElementVNode("div", _hoisted_25, _toDisplayString(diskGuard.value.active ? '保护中：定时推送与新下载暂停，旧下载继续' : '正常：允许推送与新增下载'), 1)
                    ]),
                    _createElementVNode("div", _hoisted_26, [
                      _createElementVNode("div", _hoisted_27, "剩余 " + _toDisplayString(diskGuard.value.free_gb ?? 0) + "G", 1),
                      _createElementVNode("div", _hoisted_28, "暂停 " + _toDisplayString(diskGuard.value.waiting_count || 0) + " 个", 1)
                    ])
                  ]),
                  _createElementVNode("div", _hoisted_29, [
                    _createVNode(_component_VSwitch, {
                      modelValue: diskForm.value.disk_guard_enabled,
                      "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((diskForm.value.disk_guard_enabled) = $event)),
                      label: "启用保护",
                      color: "success",
                      density: "compact",
                      "hide-details": ""
                    }, null, 8, ["modelValue"]),
                    _createVNode(_component_VTextField, {
                      modelValue: diskForm.value.disk_guard_path,
                      "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((diskForm.value.disk_guard_path) = $event)),
                      label: "检测路径",
                      density: "compact",
                      "hide-details": ""
                    }, null, 8, ["modelValue"]),
                    _createVNode(_component_VTextField, {
                      modelValue: diskForm.value.disk_guard_threshold_gb,
                      "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((diskForm.value.disk_guard_threshold_gb) = $event)),
                      modelModifiers: { number: true },
                      label: "停止新增（G）",
                      type: "number",
                      density: "compact",
                      "hide-details": ""
                    }, null, 8, ["modelValue"]),
                    _createVNode(_component_VTextField, {
                      modelValue: diskForm.value.disk_guard_recover_gb,
                      "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((diskForm.value.disk_guard_recover_gb) = $event)),
                      modelModifiers: { number: true },
                      label: "允许恢复（G）",
                      type: "number",
                      density: "compact",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _createElementVNode("div", _hoisted_30, [
                    _createVNode(_component_VBtn, {
                      size: "small",
                      color: "primary",
                      variant: "tonal",
                      loading: loading.value,
                      onClick: saveDiskGuard
                    }, {
                      default: _withCtx(() => [...(_cache[64] || (_cache[64] = [
                        _createTextVNode("保存", -1)
                      ]))]),
                      _: 1
                    }, 8, ["loading"]),
                    _createVNode(_component_VBtn, {
                      size: "small",
                      variant: "tonal",
                      loading: loading.value,
                      onClick: _cache[16] || (_cache[16] = $event => (runAction('disk_guard_check')))
                    }, {
                      default: _withCtx(() => [...(_cache[65] || (_cache[65] = [
                        _createTextVNode("立即检查", -1)
                      ]))]),
                      _: 1
                    }, 8, ["loading"]),
                    (diskGuard.value.active && !diskGuard.value.acked)
                      ? (_openBlock(), _createBlock(_component_VBtn, {
                          key: 0,
                          size: "small",
                          color: "warning",
                          variant: "tonal",
                          loading: loading.value,
                          onClick: _cache[17] || (_cache[17] = $event => (runAction('disk_guard_ack', { incident_id: diskGuard.value.incident_id })))
                        }, {
                          default: _withCtx(() => [...(_cache[66] || (_cache[66] = [
                            _createTextVNode("收到，停止提醒", -1)
                          ]))]),
                          _: 1
                        }, 8, ["loading"]))
                      : _createCommentVNode("", true),
                    (diskGuard.value.active)
                      ? (_openBlock(), _createBlock(_component_VBtn, {
                          key: 1,
                          size: "small",
                          color: "success",
                          variant: "tonal",
                          loading: loading.value,
                          onClick: _cache[18] || (_cache[18] = $event => (runAction('disk_guard_resume')))
                        }, {
                          default: _withCtx(() => [...(_cache[67] || (_cache[67] = [
                            _createTextVNode("清理后恢复", -1)
                          ]))]),
                          _: 1
                        }, 8, ["loading"]))
                      : _createCommentVNode("", true),
                    (diskGuard.value.waiting_count)
                      ? (_openBlock(), _createBlock(_component_VBtn, {
                          key: 2,
                          size: "small",
                          variant: "text",
                          onClick: _cache[19] || (_cache[19] = $event => (dialog.value = 'disk'))
                        }, {
                          default: _withCtx(() => [...(_cache[68] || (_cache[68] = [
                            _createTextVNode("查看暂停种子", -1)
                          ]))]),
                          _: 1
                        }))
                      : _createCommentVNode("", true),
                    _createElementVNode("span", _hoisted_31, _toDisplayString(diskGuard.value.active && diskGuard.value.recovered ? `已达到 ${diskGuard.value.recover_gb}G 恢复线，请手动恢复。` : `低于 ${diskGuard.value.threshold_gb}G 停止新增，清理到 ${diskGuard.value.recover_gb}G 后恢复。`), 1)
                  ]),
                  (diskGuard.value.last_error)
                    ? (_openBlock(), _createBlock(_component_VAlert, {
                        key: 0,
                        type: "warning",
                        variant: "tonal",
                        density: "compact",
                        class: "mt-2"
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(diskGuard.value.last_error), 1)
                        ]),
                        _: 1
                      }))
                    : _createCommentVNode("", true)
                ]),
                _: 1
              }, 8, ["color"])
            ]),
            _createVNode(_component_VCard, {
              variant: "outlined",
              class: "pa-4 mb-4"
            }, {
              default: _withCtx(() => [
                _cache[74] || (_cache[74] = _createElementVNode("div", { class: "text-h6 mb-1" }, "推送与下载数量", -1)),
                _cache[75] || (_cache[75] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-3" }, "定时任务按上方所选间隔使用“每轮数量”；“立即运行”使用“立即运行数量”，不受定时推送开关影响。硬盘保护启动后两者均暂停扫描、推荐推送和新增下载，旧下载继续；手动恢复保护后才重新运行。", -1)),
                _createVNode(_component_VRow, {
                  dense: "",
                  class: "settings-row push-settings-row"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VCol, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: pushForm.value.limit,
                          "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((pushForm.value.limit) = $event)),
                          modelModifiers: { number: true },
                          label: "每轮下载/推送（部）",
                          type: "number",
                          min: 1,
                          max: 50,
                          density: "compact"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: pushForm.value.test_limit,
                          "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((pushForm.value.test_limit) = $event)),
                          modelModifiers: { number: true },
                          label: "立即运行数量（部）",
                          type: "number",
                          min: 1,
                          max: 50,
                          density: "compact"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: pushForm.value.max_active_downloads,
                          "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((pushForm.value.max_active_downloads) = $event)),
                          modelModifiers: { number: true },
                          label: "同时下载上限（部）",
                          type: "number",
                          min: 1,
                          max: 100,
                          density: "compact"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: pushForm.value.max_searches,
                          "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => ((pushForm.value.max_searches) = $event)),
                          modelModifiers: { number: true },
                          label: "每轮最多搜索候选电影",
                          type: "number",
                          min: 20,
                          max: 200,
                          density: "compact",
                          hint: "每部候选会同时搜索下面选中的全部站点",
                          "persistent-hint": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: pushForm.value.min_score,
                          "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((pushForm.value.min_score) = $event)),
                          modelModifiers: { number: true },
                          label: "TMDB 最低评分",
                          type: "number",
                          min: 0,
                          max: 10,
                          step: 0.1,
                          density: "compact",
                          hint: "默认 6 分；提高后候选更少但平均质量更高",
                          "persistent-hint": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VSelect, {
                          modelValue: pushForm.value.site_ids,
                          "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => ((pushForm.value.site_ids) = $event)),
                          items: summary.value.site_options || [],
                          "item-title": "title",
                          "item-value": "value",
                          label: "资源搜索站点（可多选）",
                          multiple: "",
                          chips: "",
                          "closable-chips": "",
                          density: "compact",
                          hint: "读取 MoviePilot 已配置站点",
                          "persistent-hint": ""
                        }, null, 8, ["modelValue", "items"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createElementVNode("div", _hoisted_32, [
                  _createVNode(_component_VBtn, {
                    color: "primary",
                    variant: "tonal",
                    loading: loading.value,
                    onClick: savePushSettings
                  }, {
                    default: _withCtx(() => [...(_cache[69] || (_cache[69] = [
                      _createTextVNode("保存推送与下载设置", -1)
                    ]))]),
                    _: 1
                  }, 8, ["loading"]),
                  _createVNode(_component_VBtn, {
                    color: "success",
                    variant: "tonal",
                    loading: loading.value,
                    disabled: !controlForm.value.enabled,
                    onClick: _cache[26] || (_cache[26] = $event => (runAction('run_once')))
                  }, {
                    default: _withCtx(() => [...(_cache[70] || (_cache[70] = [
                      _createTextVNode("立即运行", -1)
                    ]))]),
                    _: 1
                  }, 8, ["loading", "disabled"]),
                  _createVNode(_component_VBtn, {
                    color: "error",
                    variant: "tonal",
                    loading: loading.value,
                    onClick: _cache[27] || (_cache[27] = $event => (runAction('clear_cache')))
                  }, {
                    default: _withCtx(() => [...(_cache[71] || (_cache[71] = [
                      _createTextVNode("清空扫描缓存", -1)
                    ]))]),
                    _: 1
                  }, 8, ["loading"]),
                  _createVNode(_component_VBtn, {
                    color: "info",
                    variant: "tonal",
                    onClick: openLogs
                  }, {
                    default: _withCtx(() => [...(_cache[72] || (_cache[72] = [
                      _createTextVNode("查看日志", -1)
                    ]))]),
                    _: 1
                  }),
                  _createVNode(_component_VBtn, {
                    color: "primary",
                    variant: "tonal",
                    onClick: openHistory
                  }, {
                    default: _withCtx(() => [...(_cache[73] || (_cache[73] = [
                      _createTextVNode("下载记录", -1)
                    ]))]),
                    _: 1
                  }),
                  _createVNode(_component_VBtn, {
                    variant: "text",
                    icon: "mdi-refresh",
                    loading: loading.value,
                    onClick: _cache[28] || (_cache[28] = $event => (loadStatus()))
                  }, null, 8, ["loading"])
                ]),
                (state.value.run_status?.run_id)
                  ? (_openBlock(), _createBlock(_component_VAlert, {
                      key: 0,
                      class: "mt-3",
                      type: "info",
                      variant: "tonal",
                      density: "compact"
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(state.value.run_status.source) + " · " + _toDisplayString(state.value.run_status.stage) + "：" + _toDisplayString(state.value.run_status.detail) + " ", 1),
                        (state.value.run_status.target)
                          ? (_openBlock(), _createElementBlock("span", _hoisted_33, "（目标 " + _toDisplayString(state.value.run_status.target) + "，已查询 " + _toDisplayString(state.value.run_status.searched || 0) + "，选中 " + _toDisplayString(state.value.run_status.selected || 0) + "，已推送 " + _toDisplayString(state.value.run_status.sent || 0) + "）", 1))
                          : _createCommentVNode("", true)
                      ]),
                      _: 1
                    }))
                  : _createCommentVNode("", true)
              ]),
              _: 1
            }),
            _createVNode(_component_VCard, {
              variant: "outlined",
              class: "pa-4 mb-4"
            }, {
              default: _withCtx(() => [
                _cache[78] || (_cache[78] = _createElementVNode("div", { class: "text-h6 mb-1" }, "Telegram 设置", -1)),
                _cache[79] || (_cache[79] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-3" }, "三个输入框留空即跟随 MoviePilot 的 Telegram 通知设置；需要覆盖哪一项就直接输入哪一项。", -1)),
                _createVNode(_component_VRow, {
                  dense: "",
                  class: "settings-row telegram-settings-row"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: telegramForm.value.source,
                          "onUpdate:modelValue": _cache[29] || (_cache[29] = $event => ((telegramForm.value.source) = $event)),
                          label: "TG 机器人 Token 或 MP 实例名（可选）",
                          type: "password",
                          autocomplete: "off",
                          density: "compact",
                          clearable: "",
                          hint: telegramForm.value.source ? '' : '默认使用 MoviePilot TG 通知设置',
                          "persistent-hint": !telegramForm.value.source
                        }, null, 8, ["modelValue", "hint", "persistent-hint"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: telegramForm.value.admins_override,
                          "onUpdate:modelValue": _cache[30] || (_cache[30] = $event => ((telegramForm.value.admins_override) = $event)),
                          label: "管理员 ID/用户名（可选）",
                          density: "compact",
                          clearable: "",
                          placeholder: "多个用逗号分隔",
                          hint: telegramForm.value.admins_override ? '' : '默认使用 MoviePilot TG 通知设置',
                          "persistent-hint": !telegramForm.value.admins_override
                        }, null, 8, ["modelValue", "hint", "persistent-hint"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_VCol, {
                      cols: "12",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: telegramForm.value.chat_id_override,
                          "onUpdate:modelValue": _cache[31] || (_cache[31] = $event => ((telegramForm.value.chat_id_override) = $event)),
                          label: "通知群组/频道 Chat ID（可选）",
                          density: "compact",
                          clearable: "",
                          hint: telegramForm.value.chat_id_override ? '' : '默认使用 MoviePilot TG 通知设置',
                          "persistent-hint": !telegramForm.value.chat_id_override
                        }, null, 8, ["modelValue", "hint", "persistent-hint"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_VBtn, {
                  color: "primary",
                  variant: "tonal",
                  loading: loading.value,
                  onClick: saveTelegram
                }, {
                  default: _withCtx(() => [...(_cache[76] || (_cache[76] = [
                    _createTextVNode("保存 Telegram 设置", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading"]),
                _createVNode(_component_VBtn, {
                  color: "info",
                  variant: "tonal",
                  class: "ml-2",
                  loading: loading.value,
                  onClick: _cache[32] || (_cache[32] = $event => (runAction('telegram_test')))
                }, {
                  default: _withCtx(() => [...(_cache[77] || (_cache[77] = [
                    _createTextVNode("发送测试消息", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading"])
              ]),
              _: 1
            }),
            _createVNode(_component_VDialog, {
              modelValue: dialogOpen.value,
              "onUpdate:modelValue": _cache[50] || (_cache[50] = $event => ((dialogOpen).value = $event)),
              "max-width": "75rem",
              scrollable: ""
            }, {
              default: _withCtx(() => [
                (dialog.value === 'active')
                  ? (_openBlock(), _createBlock(_component_VCard, {
                      key: 0,
                      title: "正在下载 · 实时状态"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VDialogCloseBtn, {
                          onClick: _cache[33] || (_cache[33] = $event => (dialog.value = ''))
                        }),
                        _createVNode(_component_VCardText, null, {
                          default: _withCtx(() => [
                            (!(summary.value.active_download_items || []).length)
                              ? (_openBlock(), _createBlock(_component_VAlert, {
                                  key: 0,
                                  type: "info",
                                  variant: "tonal",
                                  class: "mb-3"
                                }, {
                                  default: _withCtx(() => [...(_cache[80] || (_cache[80] = [
                                    _createTextVNode("当前没有 MoviePilot 正在下载的任务，或下载器暂未返回详情。", -1)
                                  ]))]),
                                  _: 1
                                }))
                              : (_openBlock(), _createBlock(_component_VDataTable, {
                                  key: 1,
                                  headers: activeHeaders,
                                  items: summary.value.active_download_items || [],
                                  "items-per-page": 20,
                                  "items-per-page-options": pageSizes,
                                  density: "compact",
                                  hover: ""
                                }, {
                                  "item.progress": _withCtx(({ item }) => [
                                    _createElementVNode("div", _hoisted_34, [
                                      _createVNode(_component_VProgressLinear, {
                                        "model-value": item.progress,
                                        color: "info",
                                        height: "8",
                                        rounded: ""
                                      }, null, 8, ["model-value"]),
                                      _createElementVNode("span", _hoisted_35, _toDisplayString(item.progress) + "%", 1)
                                    ])
                                  ]),
                                  _: 1
                                }, 8, ["items"])),
                            _cache[81] || (_cache[81] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mt-3" }, "每 5 秒自动刷新。", -1))
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }))
                  : (dialog.value === 'queue')
                    ? (_openBlock(), _createBlock(_component_VCard, {
                        key: 1,
                        title: "等候下载"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VDialogCloseBtn, {
                            onClick: _cache[34] || (_cache[34] = $event => (dialog.value = ''))
                          }),
                          _createVNode(_component_VCardText, null, {
                            default: _withCtx(() => [
                              _createElementVNode("div", _hoisted_36, [
                                _createVNode(_component_VTextField, {
                                  modelValue: queueSearch.value,
                                  "onUpdate:modelValue": _cache[35] || (_cache[35] = $event => ((queueSearch).value = $event)),
                                  label: "搜索影片",
                                  "prepend-inner-icon": "mdi-magnify",
                                  clearable: "",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"]),
                                _createVNode(_component_VBtn, {
                                  color: "error",
                                  variant: "tonal",
                                  onClick: _cache[36] || (_cache[36] = $event => (runAction('clear_queue')))
                                }, {
                                  default: _withCtx(() => [...(_cache[82] || (_cache[82] = [
                                    _createTextVNode("批量清空", -1)
                                  ]))]),
                                  _: 1
                                })
                              ]),
                              _createVNode(_component_VDataTable, {
                                headers: queueHeaders,
                                items: state.value.queue,
                                search: queueSearch.value,
                                "items-per-page": 20,
                                "items-per-page-options": pageSizes,
                                "item-value": "key",
                                density: "compact",
                                hover: ""
                              }, {
                                "item.actions": _withCtx(({ item }) => [
                                  _createVNode(_component_VBtn, {
                                    size: "small",
                                    color: "error",
                                    variant: "tonal",
                                    onClick: $event => (runAction('remove_queue', { key: item.key }))
                                  }, {
                                    default: _withCtx(() => [...(_cache[83] || (_cache[83] = [
                                      _createTextVNode("取消下载", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["onClick"])
                                ]),
                                _: 1
                              }, 8, ["items", "search"])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }))
                    : (dialog.value === 'history')
                      ? (_openBlock(), _createBlock(_component_VCard, {
                          key: 2,
                          title: "下载记录"
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_VDialogCloseBtn, {
                              onClick: _cache[37] || (_cache[37] = $event => (dialog.value = ''))
                            }),
                            _createVNode(_component_VCardText, null, {
                              default: _withCtx(() => [
                                _createElementVNode("div", _hoisted_37, [
                                  _createVNode(_component_VSelect, {
                                    modelValue: historyDate.value,
                                    "onUpdate:modelValue": _cache[38] || (_cache[38] = $event => ((historyDate).value = $event)),
                                    items: historyDateOptions.value,
                                    label: "提交日期",
                                    density: "compact",
                                    "hide-details": "",
                                    style: {"min-width":"180px","max-width":"220px"}
                                  }, null, 8, ["modelValue", "items"]),
                                  _createVNode(_component_VTextField, {
                                    modelValue: historySearch.value,
                                    "onUpdate:modelValue": _cache[39] || (_cache[39] = $event => ((historySearch).value = $event)),
                                    label: "搜索影片或 TMDB ID",
                                    "prepend-inner-icon": "mdi-magnify",
                                    clearable: "",
                                    density: "compact",
                                    "hide-details": "",
                                    style: {"min-width":"220px"}
                                  }, null, 8, ["modelValue"]),
                                  _createVNode(_component_VSelect, {
                                    modelValue: historyPageSize.value,
                                    "onUpdate:modelValue": _cache[40] || (_cache[40] = $event => ((historyPageSize).value = $event)),
                                    items: pageSizes,
                                    label: "每页条数",
                                    density: "compact",
                                    "hide-details": "",
                                    style: {"max-width":"140px"}
                                  }, null, 8, ["modelValue"]),
                                  _createVNode(_component_VBtn, {
                                    variant: "tonal",
                                    loading: historyBusy.value,
                                    onClick: loadHistory
                                  }, {
                                    default: _withCtx(() => [...(_cache[84] || (_cache[84] = [
                                      _createTextVNode("刷新", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["loading"])
                                ]),
                                _createElementVNode("div", _hoisted_38, "本插件提交记录共 " + _toDisplayString(historyView.value.total || 0) + " 条；只显示当前筛选日期，含历史归档。默认每页 100 条。", 1),
                                _createVNode(_component_VDataTable, {
                                  headers: historyHeaders,
                                  items: historyView.value.items || [],
                                  "items-per-page": historyPageSize.value,
                                  "hide-default-footer": "",
                                  density: "compact",
                                  hover: ""
                                }, {
                                  "item.result": _withCtx(({ item }) => [
                                    _createVNode(_component_VChip, {
                                      size: "small",
                                      color: item.emby_ingested_at ? 'success' : item.organized_at || item.organize_failed_at ? 'error' : item.download_completed_at ? 'warning' : 'info',
                                      title: item.organize_error || ''
                                    }, {
                                      default: _withCtx(() => [
                                        _createTextVNode(_toDisplayString(item.emby_ingested_at ? 'Emby 已入库' : item.organized_at ? '待入库' : item.organize_failed_at ? '整理失败' : item.download_completed_at ? '待整理' : '未完成'), 1)
                                      ]),
                                      _: 2
                                    }, 1032, ["color", "title"])
                                  ]),
                                  _: 1
                                }, 8, ["items", "items-per-page"]),
                                _createElementVNode("div", _hoisted_39, [
                                  _createElementVNode("span", _hoisted_40, "第 " + _toDisplayString(historyView.value.page || 1) + " / " + _toDisplayString(Math.max(1, Math.ceil((historyView.value.total || 0) / historyPageSize.value))) + " 页", 1),
                                  _createVNode(_component_VBtn, {
                                    size: "small",
                                    variant: "tonal",
                                    disabled: historyBusy.value || historyPage.value <= 1,
                                    onClick: _cache[41] || (_cache[41] = $event => (changeHistoryPage(-1)))
                                  }, {
                                    default: _withCtx(() => [...(_cache[85] || (_cache[85] = [
                                      _createTextVNode("上一页", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["disabled"]),
                                  _createVNode(_component_VBtn, {
                                    size: "small",
                                    variant: "tonal",
                                    disabled: historyBusy.value || historyPage.value * historyPageSize.value >= (historyView.value.total || 0),
                                    onClick: _cache[42] || (_cache[42] = $event => (changeHistoryPage(1)))
                                  }, {
                                    default: _withCtx(() => [...(_cache[86] || (_cache[86] = [
                                      _createTextVNode("下一页", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["disabled"])
                                ])
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        }))
                      : (dialog.value === 'suppressed')
                        ? (_openBlock(), _createBlock(_component_VCard, {
                            key: 3,
                            title: "不再推送列表"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_VDialogCloseBtn, {
                                onClick: _cache[43] || (_cache[43] = $event => (dialog.value = ''))
                              }),
                              _createVNode(_component_VCardText, null, {
                                default: _withCtx(() => [
                                  _createElementVNode("div", _hoisted_41, [
                                    _createVNode(_component_VTextField, {
                                      modelValue: suppressedSearch.value,
                                      "onUpdate:modelValue": _cache[44] || (_cache[44] = $event => ((suppressedSearch).value = $event)),
                                      label: "搜索影片",
                                      "prepend-inner-icon": "mdi-magnify",
                                      clearable: "",
                                      "hide-details": ""
                                    }, null, 8, ["modelValue"]),
                                    _createVNode(_component_VBtn, {
                                      color: "error",
                                      variant: "tonal",
                                      onClick: _cache[45] || (_cache[45] = $event => (runAction('clear_suppressed')))
                                    }, {
                                      default: _withCtx(() => [...(_cache[87] || (_cache[87] = [
                                        _createTextVNode("批量取消", -1)
                                      ]))]),
                                      _: 1
                                    })
                                  ]),
                                  _createVNode(_component_VDataTable, {
                                    headers: suppressedHeaders,
                                    items: state.value.suppressed,
                                    search: suppressedSearch.value,
                                    "items-per-page": 20,
                                    "items-per-page-options": pageSizes,
                                    "item-value": "tmdb_id",
                                    density: "compact",
                                    hover: ""
                                  }, {
                                    "item.actions": _withCtx(({ item }) => [
                                      _createVNode(_component_VBtn, {
                                        size: "small",
                                        color: "warning",
                                        variant: "tonal",
                                        onClick: $event => (runAction('remove_suppressed', { tmdb_id: item.tmdb_id }))
                                      }, {
                                        default: _withCtx(() => [...(_cache[88] || (_cache[88] = [
                                          _createTextVNode("取消排除", -1)
                                        ]))]),
                                        _: 1
                                      }, 8, ["onClick"])
                                    ]),
                                    _: 1
                                  }, 8, ["items", "search"])
                                ]),
                                _: 1
                              })
                            ]),
                            _: 1
                          }))
                        : (dialog.value === 'disk')
                          ? (_openBlock(), _createBlock(_component_VCard, {
                              key: 4,
                              title: "硬盘保护暂停的 qB 种子"
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_VDialogCloseBtn, {
                                  onClick: _cache[46] || (_cache[46] = $event => (dialog.value = ''))
                                }),
                                _createVNode(_component_VCardText, null, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_VAlert, {
                                      type: "info",
                                      variant: "tonal",
                                      class: "mb-3"
                                    }, {
                                      default: _withCtx(() => [...(_cache[89] || (_cache[89] = [
                                        _createTextVNode("这里的种子没有删除；空间清理到恢复线后，在硬盘保护卡片点击“恢复添加/下载”。", -1)
                                      ]))]),
                                      _: 1
                                    }),
                                    _createVNode(_component_VDataTable, {
                                      headers: diskHeaders,
                                      items: diskGuard.value.waiting || [],
                                      "items-per-page": 20,
                                      "items-per-page-options": pageSizes,
                                      density: "compact",
                                      hover: ""
                                    }, null, 8, ["items"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            }))
                          : (dialog.value === 'logs')
                            ? (_openBlock(), _createBlock(_component_VCard, {
                                key: 5,
                                title: "插件运行日志"
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_VDialogCloseBtn, {
                                    onClick: _cache[47] || (_cache[47] = $event => (dialog.value = ''))
                                  }),
                                  _createVNode(_component_VCardText, null, {
                                    default: _withCtx(() => [
                                      _createElementVNode("div", _hoisted_42, [
                                        _createVNode(_component_VTextField, {
                                          modelValue: logSearch.value,
                                          "onUpdate:modelValue": _cache[48] || (_cache[48] = $event => ((logSearch).value = $event)),
                                          label: "搜索日志",
                                          "prepend-inner-icon": "mdi-magnify",
                                          clearable: "",
                                          "hide-details": ""
                                        }, null, 8, ["modelValue"]),
                                        _createVNode(_component_VBtn, {
                                          color: showDetailedLogs.value ? 'primary' : 'secondary',
                                          variant: "tonal",
                                          loading: logsRefreshing.value,
                                          class: "flex-shrink-0",
                                          onClick: toggleDetailedLogs
                                        }, {
                                          default: _withCtx(() => [
                                            _createTextVNode(_toDisplayString(showDetailedLogs.value ? '详情日志：开' : '详情日志：关'), 1)
                                          ]),
                                          _: 1
                                        }, 8, ["color", "loading"]),
                                        _createVNode(_component_VBtn, {
                                          variant: "tonal",
                                          class: "flex-shrink-0",
                                          loading: logsRefreshing.value,
                                          onClick: refreshLogs
                                        }, {
                                          default: _withCtx(() => [...(_cache[90] || (_cache[90] = [
                                            _createTextVNode("刷新", -1)
                                          ]))]),
                                          _: 1
                                        }, 8, ["loading"]),
                                        _createVNode(_component_VBtn, {
                                          color: "error",
                                          variant: "tonal",
                                          onClick: _cache[49] || (_cache[49] = $event => (runAction('clear_logs')))
                                        }, {
                                          default: _withCtx(() => [...(_cache[91] || (_cache[91] = [
                                            _createTextVNode("清空日志", -1)
                                          ]))]),
                                          _: 1
                                        })
                                      ]),
                                      _createElementVNode("div", _hoisted_43, "当前显示 " + _toDisplayString(visibleLogs.value.length) + "/" + _toDisplayString((state.value.logs || []).length) + " 条。" + _toDisplayString(showDetailedLogs.value ? '含操作、筛选、站点查询、跳过原因、发送结果和定时任务' : '仅显示推送、下载和入库记录；打开详情日志可排查每一步') + "。" + _toDisplayString(logsRefreshedAt.value ? `最近刷新：${logsRefreshedAt.value}。` : '') + "升级前未记录的步骤无法补写。", 1),
                                      _createVNode(_component_VDataTable, {
                                        headers: logHeaders,
                                        items: visibleLogs.value,
                                        search: logSearch.value,
                                        "items-per-page": 20,
                                        "items-per-page-options": pageSizes,
                                        density: "compact",
                                        hover: ""
                                      }, null, 8, ["items", "search"])
                                    ]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              }))
                            : _createCommentVNode("", true)
              ]),
              _: 1
            }, 8, ["modelValue"])
          ], 64))
    ]),
    _: 1
  }))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-a0e84149"]]);

export { Page as default };
