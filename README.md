# dbonline-media-stack

一键安装 DBOnline + qBittorrent + MDC-NG + Rclone Manager + AVDB + FlareSolverr + rclone 的自动化媒体栈。

默认适合“不反代、VPS 端口全部开放”的机器，所有服务都会绑定公网端口。

## 一键安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/kingsnakerrr/dbonline-media-stack/main/install.sh)
```

安装脚本会交互询问每个软件的账号密码；留空会随机生成，并在安装完成后输出到：

```text
/opt/dbonline-media-stack/install-info.txt
```

## 默认端口

| 服务 | 地址 |
| --- | --- |
| DBOnline | `http://你的域名:9090` |
| qBittorrent | `http://你的域名:8080` |
| MDC-NG | `http://你的域名:9208` |
| Rclone Manager | `http://你的域名:7071` |
| AVDB | `http://你的域名:8000` |
| FlareSolverr | `http://你的域名:8191` |

## 固定目录

| 用途 | 路径 |
| --- | --- |
| DBOnline/qB 下载目录 | `/home/dbonline_downloads` |
| MDC-NG 监控目录 | `/home/dbonline_downloads` |
| MDC-NG 刮削输出目录 | `/home/mdcng_guaxiao` |
| Rclone Manager 监控目录 | `/home/mdcng_guaxiao` |
| rclone 配置文件 | `/root/.config/rclone/rclone.conf` |

所有容器统一映射：

```yaml
/home:/home
```

## qBittorrent

qB 使用 `userdocs/qbittorrent-nox-static` 的 `5.1.4` 静态二进制，自建 Docker 镜像运行。

安装脚本会自动设置：

- WebUI 账号密码
- 下载目录 `/home/dbonline_downloads`
- BT 端口 `6881`
- WebUI session 超时 `604800` 秒
- Docker 内网白名单
- 关闭 Host Header 校验
- DHT/PEX/LSD 开启
- 队列关闭
- 连接数优化

DBOnline 连接 qB 时请使用容器内地址：

```text
qbittorrent:8080
```

不要在容器内配置 `127.0.0.1:8080`，那会指向 DBOnline 自己。

## FlareSolverr

容器内地址：

```text
http://flaresolverr:8191/v1
```

MDC-NG 或 AVDB 需要配置 FlareSolverr 时，用这个地址。

## Rclone Manager 优化版

本仓库内置的是优化后的 Rclone Manager：

- 修复旧日志重复扫描导致的假上传记录
- `move` 模式只记录本地文件真正消失后的成功记录
- 多账号轮询上传时识别 403/429/Google upload limit 并切号
- 默认目录稳定模式：只上传已经完整稳定的影片文件夹

目录稳定模式逻辑：

1. 扫描 `/home/mdcng_guaxiao` 下的一级影片目录；
2. 目录里必须至少有一个视频文件；
3. 目录内所有文件最后修改时间都超过任务的 `min_age`，默认建议 `5m`；
4. 满足条件后，整目录交给 rclone 上传；
5. 未稳定目录会等待下一轮，避免只上传 mp4、漏掉 nfo/poster/fanart/thumb。

安装完成后，请把 rclone 配置放到：

```text
/root/.config/rclone/rclone.conf
```

然后在 Rclone Manager 前端选择 remotes、监控目录和目标目录。

## 常用命令

```bash
media status
media logs
media restart
media update
media info
```

也可以直接使用：

```bash
cd /opt/dbonline-media-stack
docker compose ps
docker compose logs -f
docker compose restart
```

## 卸载

```bash
cd /opt/dbonline-media-stack
docker compose down
```

如需连数据一起删除，确认后手动删除：

```bash
rm -rf /opt/dbonline-media-stack
```

下载目录 `/home/dbonline_downloads` 和刮削目录 `/home/mdcng_guaxiao` 不会自动删除。
