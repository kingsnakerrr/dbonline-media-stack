# 架构说明

```text
DBOnline  --推送磁力-->  qBittorrent  --下载到--> /home/dbonline_downloads
                                             |
                                             v
MDC-NG  --监控下载目录并刮削移动--> /home/mdcng_guaxiao
                                             |
                                             v
Rclone Manager --等待影片目录稳定后--> Google Drive / Team Drive
```

辅助组件：

- `FlareSolverr`: 给 MDC-NG / AVDB 绕过 Cloudflare 站点保护。
- `AVDB`: 元数据和资源辅助服务。
- `rclone`: 由宿主机安装，配置文件放在 `/root/.config/rclone/rclone.conf`。

## 为什么 Rclone Manager 要目录稳定模式

MDC-NG 刮削不是一次性原子操作。常见顺序是：

```text
移动 mp4
生成 nfo
下载 poster.jpg
下载 fanart.jpg
下载 thumb.jpg
```

如果上传器只按“单文件超过 10 秒”判断，就可能先上传 mp4，然后图片还没生成，造成漏文件。

优化后的逻辑按“影片文件夹”判断：目录里所有文件都超过 `min_age` 没变化，才整目录上传。
