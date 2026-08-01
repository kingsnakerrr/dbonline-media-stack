# MDCng 移动完成后自动删除 qB 种子及残留文件

这是不修改 MDCng 的旁路守护容器。它读取 qB 的种子文件清单，只处理指定分类/标签中已经 100% 下载完成的任务；确认正片被 MDCng 移走后，调用 qB Web API 删除种子及原下载目录中的全部残留文件。

> 仅适用于 MDCng“移动”整理模式。复制或硬链模式保留源文件，不会触发。

## 判断顺序

1. 种子必须 100% 下载完成，且不处于下载、校验或 qB 内部移动状态。
2. 单个正片：正片消失并静默 60 分钟后删除，不计算容量比例。
3. 多段正片：识别 `CD1/CD2`、`Disc1/Disc2`、`Part1/Part2`、上中下；全部消失后开始静默。
4. 剧集：识别 `S01E01`、`1x01`、`EP01`、`Episode 01`、第1集/第一集、第1话、日期节目及至少 3 个稳定递增的纯数字文件；所有已识别正片消失后开始静默。
5. 无法可靠分组的多视频种子：已移动容量达到 qB 种子总容量 90%，且静默 60 分钟后删除。
6. `SP/OVA/Special/预告/广告/Sample` 等不参与正片完成判断，最后随种子残留一起删除。

每当 qB 清单中的文件存在状态发生变化，静默计时重新开始。下载盘安全哨兵缺失时绝不删除。

## 支持格式

默认支持：

```text
.mp4 .mkv .avi .mov .wmv .m4v .flv .webm .mpg .mpeg .mpe
.ts .mts .m2ts .m2t .vob .rmvb .rm .asf .divx .f4v .ogv
.3gp .3g2 .mxf .iso .img
```

`BDMV/` 和 `VIDEO_TS/` 会按一个逻辑光盘载体处理，不会把其中每个片段误认成一集。扩展名列表可通过 `.env` 修改，无需改 Python。

## 一键安装（Linux / NAS）

```bash
chmod +x install.sh
./install.sh
```

按提示输入 qB 地址、账号、密码、DBOnline 使用的 qB 分类、宿主机下载目录和 qB 容器内下载路径。最后只有输入大写 `YES` 才立即启用真实删除；其他输入会以演练模式启动。

## 手动安装

先让 DBOnline 添加到 qB 的任务统一使用一个分类或标签，例如 `dbonline`。不要把白名单设置成所有任务。

在实际下载根目录创建安全哨兵：

```bash
touch /你的实际下载目录/.qb-autoremove-mounted
```

然后配置并启动：

```bash
cp .env.example .env
nano .env
docker compose up -d --build
docker compose logs -f qb-mdcng-autoremove
```

至少修改：

- `QB_URL`、`QB_USERNAME`、`QB_PASSWORD`
- `DOWNLOADS_HOST_PATH`：宿主机/NAS 上的真实下载目录
- `QB_CATEGORY` 或 `QB_TAG`：DBOnline 任务白名单
- `QB_PATH_PREFIX`：qB 容器看到的下载路径前缀

例如 qB 把 `/volume1/downloads` 挂载成 `/downloads`：

```dotenv
DOWNLOADS_HOST_PATH=/volume1/downloads
QB_PATH_PREFIX=/downloads
LOCAL_PATH_PREFIX=/downloads
```

第一次建议保持：

```dotenv
DRY_RUN=true
```

日志确认识别和命中正确后改成：

```dotenv
DRY_RUN=false
```

再执行：

```bash
docker compose up -d --force-recreate
```

## 主要参数

- `POLL_SECONDS=60`：检查间隔。
- `QUIET_SECONDS=3600`：达到删除条件后的静默确认时间。
- `MIN_COMPLETED_AGE_SECONDS=600`：下载完成后最少等待时间。
- `FALLBACK_MOVED_PERCENT=90`：无法识别多视频正片组时的容量阈值。
- `DELETE_REMAINING_FILES=true`：让 qB 删除种子以及下载目录中的全部残留文件。
- `DRY_RUN=true`：仅输出将执行的操作，不真实删除。

## 停用

```bash
docker compose down
```

Docker 命名卷 `qb_autoremove_data` 只保存文件观察和计时状态，不含 qB 密码。删除该卷只会让所有任务重新计时。
