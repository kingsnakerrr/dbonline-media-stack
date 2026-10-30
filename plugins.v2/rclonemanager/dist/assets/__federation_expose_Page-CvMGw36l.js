import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {toDisplayString:_toDisplayString,createElementVNode:_createElementVNode,createTextVNode:_createTextVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,normalizeClass:_normalizeClass,withModifiers:_withModifiers,withKeys:_withKeys,renderList:_renderList,Fragment:_Fragment,vModelSelect:_vModelSelect,withDirectives:_withDirectives} = await importShared('vue');


const _hoisted_1 = { class: "panel" };
const _hoisted_2 = ["href"];
const _hoisted_3 = {
  key: 0,
  class: "error"
};
const _hoisted_4 = { key: 1 };
const _hoisted_5 = ["disabled"];
const _hoisted_6 = { key: 0 };
const _hoisted_7 = { class: "summary" };
const _hoisted_8 = { class: "actions" };
const _hoisted_9 = ["disabled"];
const _hoisted_10 = ["disabled"];
const _hoisted_11 = ["disabled"];
const _hoisted_12 = { class: "task-section" };
const _hoisted_13 = { class: "section-heading" };
const _hoisted_14 = {
  key: 0,
  class: "task-grid"
};
const _hoisted_15 = { class: "task-top" };
const _hoisted_16 = ["title"];
const _hoisted_17 = ["title"];
const _hoisted_18 = { key: 1 };
const _hoisted_19 = {
  class: "dialog",
  role: "dialog",
  "aria-modal": "true",
  "aria-label": "实时传输"
};
const _hoisted_20 = { class: "dialog-actions" };
const _hoisted_21 = { class: "transfer-list" };
const _hoisted_22 = { key: 0 };
const _hoisted_23 = { key: 1 };
const _hoisted_24 = { key: 2 };

const {onMounted,onUnmounted,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'Page',
  props: { api: { type: Object, default: () => ({}) } },
  setup(__props) {

const props = __props;
const state = ref({ tasks: [], stats: {}, transferring: [] });
const busy = ref(false);
const error = ref('');
const transferDialog = ref(false);
const transferLimit = ref(20);
let timer;
const unwrap = response => response?.data?.data ?? response?.data ?? response;
async function refresh() {
  try {
    const result = unwrap(await props.api.post('plugin/RcloneManager/state', {
      transfer_limit: transferDialog.value ? transferLimit.value : 0,
    }));
    if (!result?.success) throw new Error(result?.message || '读取状态失败')
    state.value = result;
    error.value = result.warning || '';
  } catch (e) { error.value = e?.message || String(e); }
}
async function control(action) {
  if (busy.value) return
  if (action === 'stop' && !confirm('停止 Rclone Manager？运行中的传输会中断。')) return
  if (action === 'uninstall' && !confirm('卸载 Rclone Manager 服务容器？镜像和任务数据会保留，正在传输的任务会中断。')) return
  busy.value = true;
  try {
    const result = unwrap(await props.api.post('plugin/RcloneManager/control', { action }));
    if (!result?.success) throw new Error(result?.message || '操作失败')
    await refresh();
  } catch (e) { error.value = e?.message || String(e); }
  finally { busy.value = false; }
}
function bytes(value) {
  const n = Number(value) || 0;
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB'];
  let v = n, i = -1;
  do { v /= 1024; i++; } while (v >= 1024 && i < units.length - 1)
  return `${v.toFixed(1)} ${units[i]}`
}
onMounted(() => { refresh(); timer = setInterval(refresh, 3000); });
onUnmounted(() => clearInterval(timer));
function openTransfers() { transferDialog.value = true; refresh(); }
function closeTransfers() { transferDialog.value = false; refresh(); }
function changeTransferLimit() { refresh(); }
function managerUrl() { return state.value.url || `http://${window.location.hostname}:7071` }
function taskStatus(task) {
  if (!state.value.running || task.display_status === 'stopped') return '任务已关闭'
  return task.display_status === 'running' ? '上传中' : '待机'
}

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("main", _hoisted_1, [
    _createElementVNode("header", null, [
      _createElementVNode("div", null, [
        _createElementVNode("h2", null, [
          _cache[5] || (_cache[5] = _createTextVNode("Rclone Manager 控制台 ", -1)),
          _createElementVNode("small", null, "v" + _toDisplayString(state.value.version || '0.3.3'), 1)
        ]),
        _cache[6] || (_cache[6] = _createElementVNode("p", null, "独立服务仍按原方式运行；此处只监控和开关。", -1))
      ]),
      (state.value.installed)
        ? (_openBlock(), _createElementBlock("a", {
            key: 0,
            href: managerUrl(),
            target: "_blank",
            rel: "noopener noreferrer"
          }, "打开原管理界面 ↗", 8, _hoisted_2))
        : _createCommentVNode("", true)
    ]),
    (error.value)
      ? (_openBlock(), _createElementBlock("p", _hoisted_3, _toDisplayString(error.value), 1))
      : _createCommentVNode("", true),
    (state.value.installed === false)
      ? (_openBlock(), _createElementBlock("section", _hoisted_4, [
          _cache[7] || (_cache[7] = _createElementVNode("h3", null, "尚未安装独立服务", -1)),
          _cache[8] || (_cache[8] = _createElementVNode("p", null, "安装会使用这台机器已有的 Rclone Manager 镜像；不会改动任务数据。", -1)),
          _createElementVNode("button", {
            disabled: busy.value || !state.value.image_available,
            onClick: _cache[0] || (_cache[0] = $event => (control('install')))
          }, "安装并启动", 8, _hoisted_5),
          (!state.value.image_available)
            ? (_openBlock(), _createElementBlock("p", _hoisted_6, "本机没有可用镜像，需先按原方式部署镜像。"))
            : _createCommentVNode("", true)
        ]))
      : (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
          _createElementVNode("section", _hoisted_7, [
            _createElementVNode("div", null, [
              _cache[9] || (_cache[9] = _createElementVNode("span", null, "服务状态", -1)),
              _createElementVNode("strong", {
                class: _normalizeClass(state.value.running ? 'ok' : 'off')
              }, _toDisplayString(state.value.running ? '运行中' : '已停止'), 3),
              _createElementVNode("small", null, "更新于 " + _toDisplayString(state.value.updated_at || '读取中'), 1)
            ]),
            _createElementVNode("div", null, [
              _cache[10] || (_cache[10] = _createElementVNode("span", null, "运行任务", -1)),
              _createElementVNode("strong", null, _toDisplayString(state.value.tasks.filter(t => t.display_status === 'running').length), 1),
              _createElementVNode("small", null, "共 " + _toDisplayString(state.value.tasks.length) + " 个任务", 1)
            ]),
            _createElementVNode("div", null, [
              _cache[11] || (_cache[11] = _createElementVNode("span", null, "传输速度", -1)),
              _createElementVNode("strong", null, _toDisplayString(bytes(state.value.stats.speed)) + "/s", 1),
              _createElementVNode("small", null, "已传输 " + _toDisplayString(bytes(state.value.stats.bytes)), 1)
            ])
          ]),
          _createElementVNode("div", _hoisted_8, [
            (!state.value.running)
              ? (_openBlock(), _createElementBlock("button", {
                  key: 0,
                  disabled: busy.value,
                  onClick: _cache[1] || (_cache[1] = $event => (control('start')))
                }, "启动服务", 8, _hoisted_9))
              : (_openBlock(), _createElementBlock("button", {
                  key: 1,
                  class: "danger",
                  disabled: busy.value,
                  onClick: _cache[2] || (_cache[2] = $event => (control('stop')))
                }, "停止服务", 8, _hoisted_10)),
            _createElementVNode("button", {
              class: "secondary",
              onClick: refresh
            }, "刷新"),
            _createElementVNode("button", {
              class: "danger",
              disabled: busy.value,
              onClick: _cache[3] || (_cache[3] = $event => (control('uninstall')))
            }, "卸载软件", 8, _hoisted_11)
          ]),
          _createElementVNode("section", {
            class: "transfer-card",
            onClick: openTransfers,
            role: "button",
            tabindex: "0",
            onKeydown: _withKeys(openTransfers, ["enter"])
          }, [
            _createElementVNode("div", null, [
              _cache[12] || (_cache[12] = _createElementVNode("h3", null, "实时传输", -1)),
              _createElementVNode("p", null, _toDisplayString(state.value.running ? `当前 ${state.value.transfer_count || 0} 个文件正在传输` : '服务未运行'), 1)
            ]),
            _createElementVNode("button", {
              class: "secondary",
              onClick: _withModifiers(openTransfers, ["stop"])
            }, "查看弹窗 ↗")
          ], 32),
          _createElementVNode("section", _hoisted_12, [
            _createElementVNode("div", _hoisted_13, [
              _cache[13] || (_cache[13] = _createElementVNode("h3", null, "任务状态", -1)),
              _createElementVNode("small", null, "共 " + _toDisplayString(state.value.tasks.length) + " 个任务", 1)
            ]),
            (state.value.tasks.length)
              ? (_openBlock(), _createElementBlock("div", _hoisted_14, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(state.value.tasks, (task) => {
                    return (_openBlock(), _createElementBlock("div", {
                      key: task.id,
                      class: "task-item"
                    }, [
                      _createElementVNode("div", _hoisted_15, [
                        _createElementVNode("strong", {
                          title: task.name
                        }, _toDisplayString(task.name), 9, _hoisted_16),
                        _createElementVNode("span", {
                          class: _normalizeClass(["status-pill", !state.value.running || task.display_status === 'stopped' ? 'status-stopped' : `status-${task.display_status}`])
                        }, _toDisplayString(taskStatus(task)), 3)
                      ]),
                      (state.value.running && task.error_hint)
                        ? (_openBlock(), _createElementBlock("small", {
                            key: 0,
                            class: "task-error",
                            title: task.error_hint
                          }, "⚠ " + _toDisplayString(task.error_hint), 9, _hoisted_17))
                        : _createCommentVNode("", true)
                    ]))
                  }), 128))
                ]))
              : (_openBlock(), _createElementBlock("p", _hoisted_18, "暂无任务。"))
          ])
        ], 64)),
    (transferDialog.value)
      ? (_openBlock(), _createElementBlock("div", {
          key: 3,
          class: "overlay",
          onClick: _withModifiers(closeTransfers, ["self"])
        }, [
          _createElementVNode("div", _hoisted_19, [
            _createElementVNode("header", null, [
              _createElementVNode("div", null, [
                _cache[14] || (_cache[14] = _createElementVNode("h3", null, "实时传输", -1)),
                _createElementVNode("small", null, "当前 " + _toDisplayString(state.value.transfer_count || 0) + " 条 · 每 3 秒刷新", 1)
              ]),
              _createElementVNode("div", _hoisted_20, [
                _createElementVNode("label", null, [
                  _cache[16] || (_cache[16] = _createTextVNode("显示 ", -1)),
                  _withDirectives(_createElementVNode("select", {
                    "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((transferLimit).value = $event)),
                    onChange: changeTransferLimit
                  }, [...(_cache[15] || (_cache[15] = [
                    _createElementVNode("option", { value: 20 }, "20 条", -1),
                    _createElementVNode("option", { value: 50 }, "50 条", -1),
                    _createElementVNode("option", { value: 100 }, "100 条", -1),
                    _createElementVNode("option", { value: 1000 }, "1000 条", -1)
                  ]))], 544), [
                    [
                      _vModelSelect,
                      transferLimit.value,
                      void 0,
                      { number: true }
                    ]
                  ])
                ]),
                _createElementVNode("button", {
                  class: "secondary",
                  onClick: closeTransfers
                }, "关闭")
              ])
            ]),
            _createElementVNode("div", _hoisted_21, [
              (!state.value.running)
                ? (_openBlock(), _createElementBlock("p", _hoisted_22, "服务未运行。"))
                : (!state.value.transferring.length)
                  ? (_openBlock(), _createElementBlock("p", _hoisted_23, "当前没有正在传输的文件。"))
                  : _createCommentVNode("", true),
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(state.value.transferring, (file, index) => {
                return (_openBlock(), _createElementBlock("div", {
                  key: `${file.name}-${index}`,
                  class: "row"
                }, [
                  _createElementVNode("strong", null, _toDisplayString(file.name || '未命名文件'), 1),
                  _createElementVNode("span", null, [
                    _createTextVNode(_toDisplayString(bytes(file.bytes)) + " / " + _toDisplayString(bytes(file.size)) + " · " + _toDisplayString(bytes(file.speed)) + "/s ", 1),
                    (file.percentage != null)
                      ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                          _createTextVNode("· " + _toDisplayString(file.percentage) + "%", 1)
                        ], 64))
                      : _createCommentVNode("", true)
                  ])
                ]))
              }), 128)),
              (state.value.transfer_count > state.value.transferring.length)
                ? (_openBlock(), _createElementBlock("p", _hoisted_24, "仅显示前 " + _toDisplayString(state.value.transferring.length) + " 条，可调整显示数量。", 1))
                : _createCommentVNode("", true)
            ])
          ])
        ]))
      : _createCommentVNode("", true)
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-cdcfc3ae"]]);

export { Page as default };
