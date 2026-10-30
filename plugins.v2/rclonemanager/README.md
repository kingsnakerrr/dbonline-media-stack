# Rclone Manager 控制台

MoviePilot V2 插件，只负责独立 `rclone-manager` 容器的安装/卸载、运行状态、启动/停止、实时传输概况与原站跳转。不会创建、修改或删除 Rclone 任务，也不会改动独立服务的数据和账户。

在 MoviePilot V2 的插件市场添加第三方仓库 `https://github.com/kingsnakerrr/dbonline-media-stack`，安装“Rclone Manager 控制台”。这是独立服务的控制面板，不是 Rclone Manager 本体；只安装插件不会自动下载或构建服务镜像。

第一次打开插件不会安装软件：检测到原容器时直接显示控制台；容器不存在时才显示“安装并启动”。安装按钮仅适用于已在本机准备好 `zzmrclone-manager:local` 镜像、宿主机目录 `/opt/docker-compose/zzmrclone-manager` 和 7071 端口的同构部署；其他部署请先按独立服务文档手动安装。卸载只删除服务容器，保留镜像、`/opt/docker-compose/zzmrclone-manager/data` 与任务数据；不提供自动下载和构建镜像。

插件 API 继续使用 MoviePilot 登录鉴权，不另设插件密码。原管理界面仍保持自身登录方式；跳转不会绕过它。

运行条件：MoviePilot 容器需挂载 `/var/run/docker.sock`，并与宿主机共享网络，以访问 `127.0.0.1:7071`。Docker socket 授权范围很大，仅应在可信的自有服务器使用。控制操作严格限定为名为 `rclone-manager` 的容器。原管理页面默认打开当前 MoviePilot 主机的 7071 端口，也可在插件设置中填入反向代理地址。页面每 3 秒刷新传输概况；实时文件列表只在弹窗打开时读取，默认 20 条，可切换 50/100/1000 条，弹窗内滚动不会拉长主页。任务状态在紧凑卡片中显示“上传中 / 待机 / 任务已关闭”；上次运行出错时显示简短原因。仅系统 OOM 计数确认的强制终止标为“内存不足”，旧的 `signal: killed` 不会被误报为已确认 OOM；原始错误仍可到管理器日志查看。停止容器会中断正在进行的传输，页面会在操作前确认。
