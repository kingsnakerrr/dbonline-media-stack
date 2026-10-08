import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementVNode:_createElementVNode,createVNode:_createVNode} = await importShared('vue');


const _hoisted_1 = { class: "text-h6 font-weight-bold" };
const _hoisted_2 = { class: "text-h6 font-weight-bold" };
const _hoisted_3 = { class: "text-h6 font-weight-bold" };
const _hoisted_4 = { class: "text-h6 font-weight-bold" };
const _hoisted_5 = { class: "d-flex align-center justify-space-between" };
const _hoisted_6 = { class: "text-h4 mt-3" };
const _hoisted_7 = { class: "d-flex align-center justify-space-between" };
const _hoisted_8 = { class: "text-h4 mt-3" };
const _hoisted_9 = { class: "d-flex align-center justify-space-between" };
const _hoisted_10 = { class: "text-h4 mt-3" };
const _hoisted_11 = { class: "d-flex ga-2 mb-3" };
const _hoisted_12 = { class: "d-flex ga-2 mb-3" };

const {computed,onMounted,ref} = await importShared('vue');



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
const dialog = ref('');
const queueSearch = ref('');
const historySearch = ref('');
const suppressedSearch = ref('');
const pageSizes = [20, 50, 100];
const state = ref({
  summary: {}, queue: [], history: [], suppressed: [],
  telegram: { source: '', admins_override: '', chat_id_override: '', sources: [] },
});
const telegramForm = ref({ source: '', admins_override: '', chat_id_override: '' });

const unwrap = response => response?.data?.data ?? response?.data ?? response;
const envelope = response => (response?.success !== undefined ? response : (response?.data ?? response));

function applyState(data) {
  if (!data) return
  state.value = data;
  telegramForm.value = {
    source: data.telegram?.source || '',
    admins_override: data.telegram?.admins_override || '',
    chat_id_override: data.telegram?.chat_id_override || '',
  };
}

async function loadStatus() {
  loading.value = true;
  error.value = '';
  try {
    applyState(unwrap(await props.api.get('plugin/SmartMoviePush/ui_status')));
  } catch (err) {
    error.value = err?.message || '加载失败';
  } finally {
    loading.value = false;
  }
}

async function runAction(action, extra = {}) {
  loading.value = true;
  error.value = '';
  message.value = '';
  try {
    const response = await props.api.post('plugin/SmartMoviePush/ui_action', { action, ...extra });
    const body = envelope(response);
    message.value = body?.message || '操作完成';
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
    const response = await props.api.post('plugin/SmartMoviePush/ui_config', telegramForm.value);
    const body = envelope(response);
    message.value = body?.message || 'Telegram 设置已保存';
    applyState(body?.data);
  } catch (err) {
    error.value = err?.message || '保存失败';
  } finally {
    loading.value = false;
  }
}

const summary = computed(() => state.value.summary || {});
const queueHeaders = [
  { title: '影片', key: 'title' },
  { title: '加入时间', key: 'created_at', width: 180 },
  { title: '重试', key: 'attempts', width: 80 },
  { title: '操作', key: 'actions', sortable: false, width: 120 },
];
const historyHeaders = [
  { title: '影片', key: 'title' },
  { title: '提交时间', key: 'submitted_at', width: 190 },
];
const suppressedHeaders = [
  { title: '影片', key: 'title' },
  { title: '加入时间', key: 'added_at', width: 190 },
  { title: '操作', key: 'actions', sortable: false, width: 120 },
];

onMounted(loadStatus);

return (_ctx, _cache) => {
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VDialogCloseBtn = _resolveComponent("VDialogCloseBtn");
  const _component_VDataTable = _resolveComponent("VDataTable");
  const _component_VCardText = _resolveComponent("VCardText");
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
      _createVNode(_component_VRow, {
        dense: "",
        class: "mb-3"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VCol, {
            cols: "12",
            md: "3"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_VCard, {
                variant: "tonal",
                color: "success",
                class: "pa-4 h-100"
              }, {
                default: _withCtx(() => [
                  _cache[19] || (_cache[19] = _createElementVNode("div", { class: "text-caption" }, "插件状态", -1)),
                  _createElementVNode("div", _hoisted_1, _toDisplayString(summary.value.enabled ? '已启用' : '已关闭'), 1)
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VCol, {
            cols: "12",
            md: "3"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_VCard, {
                variant: "tonal",
                color: "primary",
                class: "pa-4 h-100"
              }, {
                default: _withCtx(() => [
                  _cache[20] || (_cache[20] = _createElementVNode("div", { class: "text-caption" }, "定时推送", -1)),
                  _createElementVNode("div", _hoisted_2, _toDisplayString(summary.value.auto_push ? summary.value.cron : '已暂停'), 1)
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VCol, {
            cols: "12",
            md: "3"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_VCard, {
                variant: "tonal",
                color: "warning",
                class: "pa-4 h-100"
              }, {
                default: _withCtx(() => [
                  _cache[21] || (_cache[21] = _createElementVNode("div", { class: "text-caption" }, "下载模式", -1)),
                  _createElementVNode("div", _hoisted_3, _toDisplayString(summary.value.auto_download ? '自动下载' : '手动确认'), 1)
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VCol, {
            cols: "12",
            md: "3"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_VCard, {
                variant: "tonal",
                color: "info",
                class: "pa-4 h-100"
              }, {
                default: _withCtx(() => [
                  _cache[22] || (_cache[22] = _createElementVNode("div", { class: "text-caption" }, "正在下载", -1)),
                  _createElementVNode("div", _hoisted_4, _toDisplayString(summary.value.active_downloads || 0) + "/" + _toDisplayString(summary.value.max_active_downloads || 20), 1)
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createVNode(_component_VCard, {
        variant: "outlined",
        class: "pa-4 mb-4"
      }, {
        default: _withCtx(() => [
          _cache[25] || (_cache[25] = _createElementVNode("div", { class: "text-h6 mb-3" }, "快捷控制", -1)),
          _createVNode(_component_VBtn, {
            class: "mr-2 mb-2",
            variant: "tonal",
            loading: loading.value,
            onClick: _cache[0] || (_cache[0] = $event => (runAction('toggle_auto_push')))
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(summary.value.auto_push ? '暂停定时推送' : '开启定时推送'), 1)
            ]),
            _: 1
          }, 8, ["loading"]),
          _createVNode(_component_VBtn, {
            class: "mr-2 mb-2",
            variant: "tonal",
            color: "primary",
            loading: loading.value,
            onClick: _cache[1] || (_cache[1] = $event => (runAction('toggle_download_mode')))
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(summary.value.auto_download ? '改为手动下载' : '改为自动下载'), 1)
            ]),
            _: 1
          }, 8, ["loading"]),
          _createVNode(_component_VBtn, {
            class: "mr-2 mb-2",
            variant: "tonal",
            color: "success",
            loading: loading.value,
            onClick: _cache[2] || (_cache[2] = $event => (runAction('run_once')))
          }, {
            default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
              _createTextVNode("立即试推送", -1)
            ]))]),
            _: 1
          }, 8, ["loading"]),
          _createVNode(_component_VBtn, {
            class: "mr-2 mb-2",
            variant: "tonal",
            color: "error",
            loading: loading.value,
            onClick: _cache[3] || (_cache[3] = $event => (runAction('clear_cache')))
          }, {
            default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
              _createTextVNode("清空扫描缓存", -1)
            ]))]),
            _: 1
          }, 8, ["loading"]),
          _createVNode(_component_VBtn, {
            class: "mb-2",
            variant: "text",
            icon: "mdi-refresh",
            loading: loading.value,
            onClick: loadStatus
          }, null, 8, ["loading"])
        ]),
        _: 1
      }),
      _createVNode(_component_VRow, {
        dense: "",
        class: "mb-4"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VCol, {
            cols: "12",
            md: "4"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_VCard, {
                variant: "outlined",
                class: "pa-4 h-100 list-card",
                onClick: _cache[4] || (_cache[4] = $event => (dialog.value = 'queue'))
              }, {
                default: _withCtx(() => [
                  _createElementVNode("div", _hoisted_5, [
                    _cache[26] || (_cache[26] = _createElementVNode("div", { class: "text-h6" }, "等候下载", -1)),
                    _createVNode(_component_VIcon, { icon: "mdi-chevron-right" })
                  ]),
                  _createElementVNode("div", _hoisted_6, _toDisplayString(state.value.queue.length), 1),
                  _cache[27] || (_cache[27] = _createElementVNode("div", { class: "text-caption mt-2" }, "点击查看、搜索或取消任务", -1))
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VCol, {
            cols: "12",
            md: "4"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_VCard, {
                variant: "outlined",
                class: "pa-4 h-100 list-card",
                onClick: _cache[5] || (_cache[5] = $event => (dialog.value = 'history'))
              }, {
                default: _withCtx(() => [
                  _createElementVNode("div", _hoisted_7, [
                    _cache[28] || (_cache[28] = _createElementVNode("div", { class: "text-h6" }, "插件下载记录", -1)),
                    _createVNode(_component_VIcon, { icon: "mdi-chevron-right" })
                  ]),
                  _createElementVNode("div", _hoisted_8, _toDisplayString(state.value.history.length), 1),
                  _cache[29] || (_cache[29] = _createElementVNode("div", { class: "text-caption mt-2" }, "点击查看和搜索，只读记录", -1))
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VCol, {
            cols: "12",
            md: "4"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_VCard, {
                variant: "outlined",
                class: "pa-4 h-100 list-card",
                onClick: _cache[6] || (_cache[6] = $event => (dialog.value = 'suppressed'))
              }, {
                default: _withCtx(() => [
                  _createElementVNode("div", _hoisted_9, [
                    _cache[30] || (_cache[30] = _createElementVNode("div", { class: "text-h6" }, "不再推送列表", -1)),
                    _createVNode(_component_VIcon, { icon: "mdi-chevron-right" })
                  ]),
                  _createElementVNode("div", _hoisted_10, _toDisplayString(state.value.suppressed.length), 1),
                  _cache[31] || (_cache[31] = _createElementVNode("div", { class: "text-caption mt-2" }, "点击查看、搜索或取消排除", -1))
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createVNode(_component_VCard, {
        variant: "outlined",
        class: "pa-4"
      }, {
        default: _withCtx(() => [
          _cache[33] || (_cache[33] = _createElementVNode("div", { class: "text-h6 mb-1" }, "Telegram 设置", -1)),
          _cache[34] || (_cache[34] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-3" }, "留空即自动使用 MoviePilot 通知设置；也可选择其他已配置的 Telegram 实例并覆盖管理员或群组。", -1)),
          _createVNode(_component_VRow, { dense: "" }, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, {
                cols: "12",
                md: "4"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VSelect, {
                    modelValue: telegramForm.value.source,
                    "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((telegramForm.value.source) = $event)),
                    items: state.value.telegram.sources || [],
                    "item-title": "title",
                    "item-value": "value",
                    label: "Telegram 机器人"
                  }, null, 8, ["modelValue", "items"])
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
                    "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((telegramForm.value.admins_override) = $event)),
                    label: "管理员 ID/用户名（可选）",
                    placeholder: state.value.telegram.effective_admins || '跟随 MP'
                  }, null, 8, ["modelValue", "placeholder"])
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
                    "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((telegramForm.value.chat_id_override) = $event)),
                    label: "通知群组/频道 Chat ID（可选）",
                    placeholder: state.value.telegram.effective_chat_id || '跟随 MP'
                  }, null, 8, ["modelValue", "placeholder"])
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
            default: _withCtx(() => [...(_cache[32] || (_cache[32] = [
              _createTextVNode("保存 Telegram 设置", -1)
            ]))]),
            _: 1
          }, 8, ["loading"])
        ]),
        _: 1
      }),
      _createVNode(_component_VDialog, {
        modelValue: dialog.value,
        "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((dialog).value = $event)),
        "max-width": "75rem",
        scrollable: ""
      }, {
        default: _withCtx(() => [
          (dialog.value === 'queue')
            ? (_openBlock(), _createBlock(_component_VCard, {
                key: 0,
                title: "等候下载"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VDialogCloseBtn, {
                    onClick: _cache[10] || (_cache[10] = $event => (dialog.value = ''))
                  }),
                  _createVNode(_component_VCardText, null, {
                    default: _withCtx(() => [
                      _createElementVNode("div", _hoisted_11, [
                        _createVNode(_component_VTextField, {
                          modelValue: queueSearch.value,
                          "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((queueSearch).value = $event)),
                          label: "搜索影片",
                          "prepend-inner-icon": "mdi-magnify",
                          clearable: "",
                          "hide-details": ""
                        }, null, 8, ["modelValue"]),
                        _createVNode(_component_VBtn, {
                          color: "error",
                          variant: "tonal",
                          onClick: _cache[12] || (_cache[12] = $event => (runAction('clear_queue')))
                        }, {
                          default: _withCtx(() => [...(_cache[35] || (_cache[35] = [
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
                            default: _withCtx(() => [...(_cache[36] || (_cache[36] = [
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
                  key: 1,
                  title: "插件下载记录"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VDialogCloseBtn, {
                      onClick: _cache[13] || (_cache[13] = $event => (dialog.value = ''))
                    }),
                    _createVNode(_component_VCardText, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_VTextField, {
                          modelValue: historySearch.value,
                          "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((historySearch).value = $event)),
                          label: "搜索影片",
                          "prepend-inner-icon": "mdi-magnify",
                          clearable: "",
                          class: "mb-3",
                          "hide-details": ""
                        }, null, 8, ["modelValue"]),
                        _createVNode(_component_VDataTable, {
                          headers: historyHeaders,
                          items: state.value.history,
                          search: historySearch.value,
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
              : (dialog.value === 'suppressed')
                ? (_openBlock(), _createBlock(_component_VCard, {
                    key: 2,
                    title: "不再推送列表"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VDialogCloseBtn, {
                        onClick: _cache[15] || (_cache[15] = $event => (dialog.value = ''))
                      }),
                      _createVNode(_component_VCardText, null, {
                        default: _withCtx(() => [
                          _createElementVNode("div", _hoisted_12, [
                            _createVNode(_component_VTextField, {
                              modelValue: suppressedSearch.value,
                              "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((suppressedSearch).value = $event)),
                              label: "搜索影片",
                              "prepend-inner-icon": "mdi-magnify",
                              clearable: "",
                              "hide-details": ""
                            }, null, 8, ["modelValue"]),
                            _createVNode(_component_VBtn, {
                              color: "error",
                              variant: "tonal",
                              onClick: _cache[17] || (_cache[17] = $event => (runAction('clear_suppressed')))
                            }, {
                              default: _withCtx(() => [...(_cache[37] || (_cache[37] = [
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
                                default: _withCtx(() => [...(_cache[38] || (_cache[38] = [
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
                : _createCommentVNode("", true)
        ]),
        _: 1
      }, 8, ["modelValue"])
    ]),
    _: 1
  }))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-ffffd50b"]]);

export { Page as default };
