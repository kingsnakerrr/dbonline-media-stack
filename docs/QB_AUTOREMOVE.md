# dbonline 种子监控自动删种

安装时会询问是否启用：

```text
是否启用 dbonline 种子监控：MDC-NG 刮削移动后删除种子和残留文件 [Y]
```

这个组件只处理 qBittorrent 分类为 `dbonline` 的种子。

## 工作逻辑

1. qB 种子下载完成后，等待 `10` 分钟；
2. 读取 qB 文件清单，识别正片文件；
3. 检查正片文件是否已经被 MDC-NG 从 `/home/dbonline_downloads` 移走；
4. 正片移走后继续静默等待 `1` 小时；
5. 条件满足后调用 qB API 删除种子，并删除 qB 任务残留文件。

## 开关命令

```bash
media autoremove status
media autoremove on
media autoremove off
media autoremove logs
```

## 配置项

配置文件位于：

```text
/opt/dbonline-media-stack/.env
```

关键配置：

```env
QB_AUTOREMOVE_ENABLED=true
QB_AUTOREMOVE_DELETE_REMAINING_FILES=true
QB_AUTOREMOVE_QUIET_SECONDS=3600
QB_AUTOREMOVE_MIN_COMPLETED_AGE_SECONDS=600
```

`QB_AUTOREMOVE_DELETE_REMAINING_FILES=true` 表示删除种子时同时让 qB 删除该种子的残留文件。
