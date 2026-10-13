# 智能下载影视资源_惹咪之北

MoviePilot V2 私人电影推荐与下载插件。插件从 TMDB 候选中排除媒体库已有影片，再到所选 PT 站点搜索资源，按 MoviePilot 过滤规则选择结果，可推送到 Telegram 或自动提交下载。

## 主要功能

- 定时 30、60、120、180、240 或 300 分钟运行
- 自动下载与手动确认两种模式
- 限制同时下载任务数，超出后进入顺序等候队列
- 硬盘剩余空间保护，空间不足时保留候选但停止新增种子
- 等候下载、插件下载记录、不再推送列表均支持搜索和分页
- Telegram 推荐、下载按钮、不再推送按钮及每日统计
- 每天 00:00 汇总上一自然日插件下载数量，并标记已经入库的电影
- 私人固定密码保护；密码只保存为加盐哈希

## 手动安装

适用于 Docker 版 MoviePilot V2。以下示例假设容器名为 `moviepilot-v2`，配置目录为 `/opt/docker-compose/moviepilot/config`。

1. 解压安装包，确认得到 `smartmoviepush` 文件夹。
2. 将整个文件夹复制到 MoviePilot 的本地插件目录：

   ```bash
   mkdir -p /opt/docker-compose/moviepilot/config/local-plugins/plugins.v2
   cp -a smartmoviepush /opt/docker-compose/moviepilot/config/local-plugins/plugins.v2/
   ```

3. 如果当前 MoviePilot 版本不会自动加载本地目录，再复制进容器：

   ```bash
   docker exec moviepilot-v2 mkdir -p /app/app/plugins/smartmoviepush
   docker cp smartmoviepush/. moviepilot-v2:/app/app/plugins/smartmoviepush/
   ```

4. 重启 MoviePilot：

   ```bash
   docker restart moviepilot-v2
   ```

5. 打开 MoviePilot 的“插件”，进入“智能下载影视资源_惹咪之北”。

## 私人密码

本插件只接受作者设置的私人固定密码。首次打开时请联系 `@SDFSDFSF12321` 获取密码。首次输入正确后，当前浏览器会保存访问会话；点击插件里的“锁定”可清除当前浏览器会话。

公开仓库不会保存密码明文，只保存不可直接读取的 PBKDF2 加盐校验值。个人安装包里的专用教程记录密码明文，请勿转发。

## 基本使用

1. 打开“插件状态”。关闭后不会定时推荐、提交排队任务或执行空间保护。
2. 选择定时推送间隔和“自动下载/手动下载”。
3. 设置每轮数量、立即运行数量、同时下载上限、TMDB 最低评分和资源搜索站点。
4. Telegram 三个输入框留空时跟随 MoviePilot 的 Telegram 通知配置；只需填写要覆盖的项目。
5. 设置硬盘保护检测路径、停止新增阈值和恢复阈值。
6. 保存设置后可点击“立即运行”测试真实搜索与下载流程。

“立即运行”不受定时推送暂停影响，但仍遵守同时下载上限和硬盘保护。自动下载模式中，空位不足的影片会保留在“等候下载”，以后按顺序提交。

## 升级

停止 MoviePilot 后覆盖 `smartmoviepush` 文件夹，再重启容器即可。不要删除 MoviePilot 的配置数据库；插件密码、队列、历史记录和设置都存放在 MoviePilot 数据中。

## 常见问题

- 看不到插件：确认目录层级是 `plugins.v2/smartmoviepush/__init__.py`，然后重启 MoviePilot。
- 密码不知道：按首次打开页面提示联系 `@SDFSDFSF12321` 获取。
- 点击立即运行但未下载：检查同时下载上限、硬盘保护状态、站点是否可用以及 MoviePilot 过滤规则。
- 影片已下载但未标记入库：只有 MoviePilot 完成整理并触发入库记录后，午夜统计才显示“✓ 已入库”。
