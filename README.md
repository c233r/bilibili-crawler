# B站视频采集与 VLM 初筛流水线

一个从 **关键词搜索 → 视频下载 → 大模型视觉初筛 → 结果落库** 的完整数据采集工具链，
用三个逐步演进的版本来解决同一件事：**如何低人工成本地筛出"非赛事的球类运动教学/人物纪实"类视频**。

> 本仓库是「爬虫数据获取」项目，是整条数据生产链路的第一环。
> 下游还有两个配套仓库：**`02-human-detection`**（人体目标检测 · 关键点解析 · 持绳二分类）
> 与 **`03-clip-clustering`**（CLIP 后处理聚类切分）。三者合起来构成一条完整的数据生产链路。

---

## 目录

- [项目简介](#项目简介)
- [三个版本对比](#三个版本对比)
- [系统架构](#系统架构)
- [目录结构](#目录结构)
- [环境与依赖](#环境与依赖)
- [快速开始](#快速开始)
- [核心模块说明](#核心模块说明)
- [配置说明](#配置说明)
- [输出与数据落库](#输出与数据落库)
- [与下游项目的衔接](#与下游项目的衔接)
- [注意事项](#注意事项)
- [License](#license)

---

## 项目简介

这个项目要解决的是一个很具体的标注数据来源问题：**需要大量"持绳 / 非持绳"的跳绳、
以及球类运动教学类视频片段，但人工在视频网站上按关键词一页页翻找、逐个打开确认效率极低。**

于是把流程拆成可自动化的四步：

1. **搜索** — 调用 B 站 Web API，按关键词分页搜索视频或 UP 主；
2. **下载** — 支持 DASH 音视频分流下载 + ffmpeg 自动合并，也支持 yt-dlp 兜底（受限视频）；
3. **初筛** — 抽取视频关键帧，交给视觉大模型（GLM-4V）判断"是否符合目标画像"，不满足的直接丢弃；
4. **落库** — 把每个任务的搜索结果、下载状态、筛选结论、耗时持久化，支持中断后断点续传。

这样只需要给出关键词和一段自然语言筛选提示词（Prompt），就能自动攒出一批已初筛的视频，
再交给下游的检测 / 关键点 / 分类 / 聚类流水线做精加工。

### 功能特性

| 能力 | 说明 |
| --- | --- |
| 关键词搜索 | 搜索视频（`--video`）或 UP 主（`--up`），支持分页、目标数量上限 |
| 多下载后端 | 自研 DASH 下载器（速度快、可控） + yt-dlp / you-get（兼容性好，可下 720P+） |
| 音视频合并 | 调用 ffmpeg 把分离的视频流与音频流合并为 mp4 |
| 弹幕 / 封面 / 封面批量合并 | 附带 `batch_merge.py` 用于批量合并目录 |
| VLM 初筛 | 抽帧 + 视觉大模型结构化判定，输出置信度与判定理由 |
| 精细化分析 | `refined` 模式：多帧采样 + 聚合投票，比单帧判定更稳 |
| 并发下载 | 线程池并行下载（V2/V3） |
| 异步 VLM 调用 | `asyncio` + `AsyncOpenAI` + `Semaphore`，单线程内并发多帧请求（V3） |
| 断点续传 | SQLite 记录 Run / Video / Result / Checkpoint，中断后按关键词恢复（V3） |
| 数据血缘 | 每条分析结果可回溯到源视频、使用的 Prompt 与分析模式（V3） |

---

## 三个版本对比

三个版本**不是三套无关的代码，而是同一套爬虫库上逐步加能力的三次迭代**。
每一版都可以独立运行，建议直接用 `v3-resume`，另外两版保留用于理解演进过程。

| | `v1-single-process` | `v2-multithread` | `v3-resume` |
| --- | --- | --- | --- |
| 并发模型 | 单进程顺序执行 | 动态线程池（下载/分析共享线程） | 动态线程池 + `asyncio` 协程并发调 VLM |
| 入口 | `integrated_cli.py`（菜单式） | `integrated_cli.py` / `integrated_cli_multiproc.py` | `integrated_cli_v3.py` |
| 调度方式 | for 循环逐个处理 | `TaskQueue` 生产者-消费者 + `DynamicThreadPool` | 同上 + Checkpoint 驱动 |
| VLM 调用 | 同步阻塞，逐帧串行 | 同步阻塞（线程内串行） | `AsyncVLMAnalyzer`，`Semaphore` 限流并发 |
| 状态持久化 | 无（仅内存 + json） | 无 | SQLite（`sql/` 模块），WAL 模式 |
| 断点续传 | 不支持 | 不支持 | 支持，按关键词 `start_or_resume()` |
| 数据血缘 | 无 | 无 | `LineageBuilder`，可导出溯源信息 |
| 下游衔接 | 无 | `pipeline/api/` 推送到 EdgeCrafter 服务 | 同上 |
| 适用场景 | 小批量、调试、理解流程 | 中等批量，纯下载吞吐 | 大批量、长时间运行、需要可恢复 |

### 各版本解决的问题

- **V1：先让它能跑通。** 单进程顺序执行，逻辑直观，适合调试 API 与 Prompt。
  瓶颈很明显 —— 下载时 CPU 与网络都在等，VLM 请求时整条流水线完全阻塞。
- **V2：把"下载"和"分析"解耦。** 引入 `TaskQueue` + `DynamicThreadPool`，
  线程不再固定角色，而是**按队列状态在"下载任务"和"分析任务"之间动态切换**，
  避免出现"下载线程饿死、分析线程排队"的资源错配。
  同时加入 `pipeline/api/`，把满足条件的视频推送到人体目标检测服务。
- **V3：让它能长时间无人值守地跑。** 大模型 API 是网络 IO，
  用线程去并发会浪费在线程切换上，于是改为 `asyncio` 协程 + `Semaphore(3)` 限流，
  单个分析线程内部即可并发多个帧请求。
  更关键的是引入 SQLite 持久化：每完成一个视频就落一次状态，
  进程被 kill 或机器重启后，用相同关键词即可 `start_or_resume()` 从断点继续，
  已完成的任务不会重复下载、重复计费。

---

## 系统架构

### V1：单进程直筒式

```
┌───────────────────────────────────────────────────────────────┐
│                       integrated_cli.py                       │
│                      （菜单驱动，顺序执行）                     │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────┐   ┌──────────────────┐   ┌───────────────┐
│  BilibiliAPI     │──▶│  DownloadManager │──▶│ FFMpegMerger  │
│  搜索视频/UP主    │   │  DASH / yt-dlp   │   │  音视频合并    │
└──────────────────┘   └──────────────────┘   └───────────────┘
                                                      │
                                                      ▼
                       ┌──────────────────────────────────────────┐
                       │  大模型接入筛选                            │
                       │  frame_extractor → vlm_analyzer (GLM-4V) │
                       │  → result_handler → statistics           │
                       └──────────────────────────────────────────┘
```

### V2 / V3：生产者-消费者流水线

```
                     ┌──────────────────────────────────────────┐
                     │            VideoPipeline                 │
                     │        （pipeline_main.py）               │
                     └──────────────────────────────────────────┘
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                           ▼
                 ┌─────────────────┐         ┌─────────────────┐
                 │  VideoSearcher  │         │   TaskQueue     │
                 │  分页搜索关键词   │────────▶│  待处理任务队列   │
                 └─────────────────┘         └─────────────────┘
                                                      │
                                                      ▼
                     ┌────────────────────────────────────────────────┐
                     │            DynamicThreadPool                   │
                     │   worker 按队列压力在两种角色间动态切换           │
                     │                                                │
                     │   ┌────────────────┐    ┌────────────────┐     │
                     │   │  下载角色       │    │  分析角色       │     │
                     │   │  VideoDownloader│    │ VideoFilterAPI │     │
                     │   │  + ffmpeg 合并  │    │  (V3: asyncio) │     │
                     │   └────────────────┘    └────────────────┘     │
                     └────────────────────────────────────────────────┘
                              │                        │
                              │                        ▼
                              │              ┌────────────────────┐
                              │              │  满足条件 → 回调    │
                              │              └────────────────────┘
                              │                        │
                              ▼                        ▼
                   ┌────────────────────┐   ┌──────────────────────┐
                   │  PipelineMonitor   │   │  VideoPusher         │
                   │  统计/进度/落日志    │   │  推送到检测服务       │
                   └────────────────────┘   └──────────────────────┘
                              │
                    (仅 V3)   ▼
                   ┌────────────────────────────────────────────┐
                   │  sql/  —— SQLite 持久化                     │
                   │  Run / Video / AnalysisResult / Checkpoint │
                   │  CheckpointManager: start_or_resume()      │
                   └────────────────────────────────────────────┘
```

### V3 的协程并发模型

```
分析线程 (threading.Thread)
  │
  └─ asyncio.run_coroutine_threadsafe(...)  ──▶ 该线程独占的事件循环
                                                   │
                                       ┌───────────┴───────────┐
                                       ▼                       ▼
                                 帧 1 请求               帧 N 请求
                                       └──── Semaphore(3) ─────┘
                                                   │
                                                   ▼
                                        AsyncOpenAI (GLM-4V)
                                        asyncio.gather 聚合 → 投票
```

要点：**每个分析线程持有自己的事件循环与 `Semaphore`**（通过 `threading.local()` 实现），
所以"多线程 × 多协程"两层并发是叠加的，而不是互相争抢同一个 loop。

---

## 目录结构

```
01-bilibili-crawler/
├── README.md
├── .gitignore                     # 已确保不会提交 cookie.txt 与 config.json
├── requirements.txt               # 依赖总览
├── examples/                      # 输出格式示例（已脱敏，不含真实路径与标题）
│   ├── result.example.json        #   逐条筛选结论
│   └── statistics.example.json    #   汇总统计
│
├── v1-single-process/             # ── V1：单进程版 ──
│   ├── integrated_cli.py          #   菜单式整合入口
│   ├── bilibili爬虫/               #   爬虫核心库（三个版本共用同一套）
│   │   ├── config.json            #   本地配置（已被 .gitignore 忽略）
│   │   ├── config.example.json    #   配置模板
│   │   ├── requirements.txt
│   │   └── src/
│   │       ├── main.py            #   Tkinter GUI 入口
│   │       ├── cli.py             #   无图形界面命令行入口（服务器用）
│   │       ├── batch_merge.py      #   批量合并工具
│   │       ├── model/bilibili_api.py       # B站 Web API 封装
│   │       ├── downloaders/                # 下载器
│   │       │   ├── base_downloader.py
│   │       │   ├── video_downloader.py     #   单个视频（DASH/yt-dlp）
│   │       │   ├── tv_downloader.py        #   番剧/剧集
│   │       │   └── download_manager.py     #   分页批量下载调度
│   │       ├── ffmpeg/merger.py            #   音视频合并
│   │       ├── controller/controller.py    #   GUI 事件绑定
│   │       ├── view/                       #   Tkinter 组件
│   │       └── utils/downloader.py         #   底层 HTTP / 分片下载
│   └── 大模型接入筛选/              #   VLM 初筛模块
│       ├── config.json            #   含 api_key（已置空，见"配置说明"）
│       ├── config.example.json
│       ├── filter_api.py          #   VideoFilterAPI 对外封装
│       ├── video_filter.py        #   单独运行筛选的 CLI
│       ├── requirements.txt
│       └── modules/
│           ├── frame_extractor.py  #  抽帧 / 取视频时长
│           ├── vlm_analyzer.py     #  VLMAnalyzer / AsyncVLMAnalyzer
│           ├── refined_analyzer.py #  精细化（多帧聚合）分析
│           ├── result_handler.py   #  结果落盘
│           └── video_statistics.py #  统计汇总
│
├── v2-multithread/                # ── V2：多线程流水线版 ──
│   ├── integrated_cli.py
│   ├── integrated_cli_multiproc.py
│   ├── bilibili爬虫/               #   同上
│   ├── 大模型接入筛选/              #   同上
│   └── pipeline/                  #   核心新增：流水线
│       ├── __init__.py
│       ├── README.md
│       ├── example.py
│       ├── control/
│       │   ├── task_queue.py      #   TaskQueue / DownloadTask / TaskStatus
│       │   └── pipeline_main.py   #   VideoPipeline 总控
│       ├── threads/
│       │   ├── downloader_pool.py #   下载线程池
│       │   ├── analyzer_pool.py   #   分析线程池
│       │   ├── dynamic_pool.py    #   动态线程池（角色可切换）
│       │   └── monitor_thread.py  #   监控/统计线程
│       ├── api/
│       │   ├── edgecrafter_client.py  # 检测服务客户端（同步/异步）
│       │   └── video_pusher.py        # 视频推送器
│       └── log/logger.py          #   分级日志（main/download/analyzer/stats）
│
└── v3-resume/                     # ── V3：持久化 + 断点续传版（推荐） ──
    ├── integrated_cli_v3.py       #   主入口
    ├── example_v3_usage.py        #   完整调用示例（5 个场景）
    ├── test_v3_db.py              #   数据库自测
    ├── update_models.py           #   模型更新工具
    ├── bilibili爬虫/               #   同上
    ├── 大模型接入筛选/              #   同上（refined_analyzer 进一步强化）
    ├── pipeline/                  #   同上（pipeline_main 增强为持久化版）
    ├── utils/video_searcher.py    #   搜索器单例，封装分页搜索 + 断点续传
    └── sql/                       #   核心新增：持久化层
        ├── database.py            #   DatabaseManager（连接、建表、WAL）
        ├── models.py              #   Run / Video / AnalysisResult / Checkpoint
        │                          #   / UploadRecord + 各状态枚举 + LineageBuilder
        ├── repos.py               #   RunRepo / VideoRepo / ResultRepo
        │                          #   / CheckpointRepo / UploadRepo
        └── checkpoint.py          #   CheckpointManager：断点续传核心
```

---

## 环境与依赖

- **Python** ≥ 3.8（V3 的协程与类型标注建议 3.10+）
- **ffmpeg** —— 必须可执行且在 `PATH` 中，否则音视频无法合并
- 可选：**you-get**、**yt-dlp**（受限视频与 720P+ 画质）

```bash
# 爬虫核心
pip install -r v3-resume/bilibili爬虫/requirements.txt

# VLM 初筛（底层为智谱 GLM / OpenAI 兼容 SDK）
pip install -r v3-resume/大模型接入筛选/requirements.txt
```

> V3 的 `sql/` 模块只用标准库 `sqlite3`，无需额外安装。

---

## 快速开始

### 1. 准备 Cookie（必需，否则下载受限）

B 站未登录状态下只能拿到 360P 且部分接口受限。导出方式二选一：

```bash
# 方式 A：让 yt-dlp 从浏览器直接读并导出
yt-dlp --cookies-from-browser edge --cookies "v3-resume/bilibili爬虫/src/cookie.txt"

# 方式 B：浏览器扩展 "Get cookies.txt LOCALLY" 导出后另存为上面的路径
```

格式说明见仓库中的 `bilibili爬虫/src/cookie.txt.example`（该文件仅为模板，**不含真实凭据**）。

### 2. 配置

```bash
cp v3-resume/bilibili爬虫/config.example.json      v3-resume/bilibili爬虫/config.json
cp v3-resume/大模型接入筛选/config.example.json     v3-resume/大模型接入筛选/config.json
```

然后编辑 `大模型接入筛选/config.json`，填入你自己的智谱 API Key（见[配置说明](#配置说明)）。

### 3. 运行

```bash
cd v3-resume

# 菜单式交互（推荐先这样跑一遍，确认 Cookie 与 API Key 都通）
python integrated_cli_v3.py

# 或直接按代码方式调用流水线
python example_v3_usage.py
```

V3 也可以在代码里这样用：

```python
from pipeline.control.pipeline_main import VideoPipeline

with VideoPipeline(total_workers=10) as pipeline:
    # force_new=False 时，会自动按关键词恢复上次未完成的 Run
    pipeline.start_run(
        keyword="网球教学",
        search_type="video",
        target_count=200,
        use_refined=True,
        filter_prompt="画面中是否有真人在做球类运动，且球清晰可见、场景为教学或练习而非正式比赛",
        force_new=False,
    )
    pipeline.wait_until_complete()
    pipeline.print_statistics()
```

`sql` 层单独验证：

```bash
python test_v3_db.py
```

### 4. 单独跑爬虫（不接大模型）

```bash
cd v3-resume/bilibili爬虫
python src/cli.py            # 命令行版（服务器）
python src/main.py           # Tkinter 图形界面版
```

---

## 核心模块说明

### `bilibili爬虫` —— 数据获取层

| 模块 | 职责 |
| --- | --- |
| `model/bilibili_api.py` | 封装 B 站 Web API：搜索视频 / 搜索 UP 主 / 取视频详情 / 取播放地址（含 WBI 签名相关逻辑） |
| `downloaders/download_manager.py` | 分页下载调度：维护页码游标、去重、失败重试 |
| `downloaders/video_downloader.py` | 单视频下载：优先自研 DASH 分片下载，失败回退 yt-dlp |
| `downloaders/base_downloader.py` | 下载器基类：进度回调、断点、分片合并 |
| `ffmpeg/merger.py` | 探测 ffmpeg 并合并 DASH 的 video-only 与 audio-only 流 |
| `utils/downloader.py` | 底层 HTTP：会话复用、Range 分片、重试与限速 |

### `大模型接入筛选` —— 初筛层

| 模块 | 职责 |
| --- | --- |
| `filter_api.py` | `VideoFilterAPI`：对上层暴露"给一个视频路径 + Prompt，返回是否满足 + 置信度" |
| `modules/frame_extractor.py` | 按时间点抽帧，返回 `PIL.Image` 列表与视频时长 |
| `modules/vlm_analyzer.py` | 三类分析器：`VLMAnalyzer`（同步单帧）、`SimpleVLMAnalyzer`、`AsyncVLMAnalyzer`（协程并发） |
| `modules/refined_analyzer.py` | 精细化分析：多帧采样 + 结构化输出 + 聚合投票，显著降低单帧误判 |
| `modules/result_handler.py` | 结果写盘（`result.json`） |
| `modules/video_statistics.py` | 汇总统计（`statistics.json`）：通过率、耗时、失败原因分布 |

**Prompt 即配置。** 想换筛选目标不需要改代码，只要改 `config.json` 里的 `prompt`。
V3 的 `config.example.json` 里放了一段针对"非赛事球类运动教学/人物纪实"的完整 Prompt，
包含正向准入条件、负向排除条件（赞助商 Logo、看台人群密度、计分板）、
动态行为特征与镜头语言偏好 —— 可以作为写自己 Prompt 的参考模板。

### `pipeline` —— 调度层（V2/V3）

| 模块 | 职责 |
| --- | --- |
| `control/task_queue.py` | 线程安全任务队列，`TaskStatus` 全生命周期（pending → downloading → downloaded → analyzing → completed / failed），支持重试 |
| `control/pipeline_main.py` | `VideoPipeline` 总控：装配队列、线程池、监控、推送、持久化 |
| `threads/dynamic_pool.py` | **动态线程池**：worker 不固定角色，根据队列中下载/分析任务的比例切换身份 |
| `threads/monitor_thread.py` | 周期性统计吞吐、队列深度、剩余量，写 stats 日志 |
| `api/video_pusher.py` | 把满足筛选的视频推送到下游检测服务，支持同步与异步（`aiohttp`）两条路径 |
| `log/logger.py` | 按用途分文件：main / download / analyzer / dynamic / stats |

### `sql` —— 持久化层（V3）

| 模块 | 职责 |
| --- | --- |
| `database.py` | 连接管理、建表、开启 WAL（允许读写并发） |
| `models.py` | `Run`（一次运行）、`Video`（单个视频）、`AnalysisResult`（分析结论）、`Checkpoint`、`UploadRecord`；`LineageBuilder` 组装血缘 |
| `repos.py` | 各表的 CRUD 仓库 |
| `checkpoint.py` | `CheckpointManager.start_or_resume(keyword)`：同关键词存在未完成 Run 就续跑，否则新建 |

---

## 配置说明

### `bilibili爬虫/config.json`

```json
{
  "download_path": "./downloads",
  "cookies_path": "./bilibili爬虫/src/cookie.txt",
  "page_size": 20,
  "use_ytdlp": true,
  "download_audio": true
}
```

| 字段 | 说明 |
| --- | --- |
| `download_path` | 下载根目录，内部再分 `videos/`、`tv/` |
| `cookies_path` | Netscape 格式 Cookie 文件路径 |
| `page_size` | 每次搜索请求返回条数 |
| `use_ytdlp` | `true` 走 yt-dlp（兼容性好），`false` 走自研 DASH 下载器（更快） |
| `download_audio` | 是否下载音频（需要合并成完整 mp4 时必须为 `true`） |

### `大模型接入筛选/config.json`

```json
{
  "api_key": "",
  "model": "glm-4v-flash",
  "interval_seconds": 60,
  "prompt": "……你的筛选 Prompt……",
  "use_structured_output": true,
  "output_file": "result.json",
  "statistics_file": "statistics.json",
  "threshold": 0.6
}
```

| 字段 | 说明 |
| --- | --- |
| `api_key` | **必填，但请勿提交。** 模板中已置空 |
| `model` | 视觉模型名，默认 `glm-4v-flash` |
| `interval_seconds` | 两次请求之间的节流间隔，防触发限流 |
| `prompt` | 筛选判据，自然语言描述，可自由替换 |
| `use_structured_output` | 是否要求模型返回结构化 JSON |
| `threshold` | 判定为"满足"的置信度阈值 |

**填 API Key 的三种方式**，任选其一：

```bash
# 1) 写入本地 config.json（该文件已被 .gitignore 忽略）
# 2) 命令行覆盖
python video_filter.py --api-key "<YOUR_KEY>"
# 3) 代码里构造
create_filter_api_from_config("大模型接入筛选/config.json")
```

> `config.example.json` 是**模板**，会提交到仓库；`config.json` 是**你自己的**，不会提交。
> 提交前请务必用 `git status` 确认 `config.json` 与 `cookie.txt` 都没有出现在待提交列表里。

---

## 输出与数据落库

### 文件产物

```
downloads/
├── videos/            # 普通投稿视频
└── tv/                # 番剧 / 剧集
```

筛选结果写入 `大模型接入筛选/` 下的 `result.json`（逐条结论）与 `statistics.json`（汇总统计），
文件名由配置里的 `output_file` / `statistics_file` 决定。

这两个文件是**运行时产物**，内容会包含你的本机绝对路径与实际爬取的视频标题，
因此已被 `.gitignore` 忽略。格式示例见
[`examples/result.example.json`](examples/result.example.json) 与
[`examples/statistics.example.json`](examples/statistics.example.json)（已脱敏）。

### V3 数据库表

```
runs             一次运行：关键词、搜索类型、目标数量、Prompt、状态、起止时间
videos           单个视频：bvid、标题、时长、下载状态、文件路径
analysis_results 分析结论：是否满足、置信度、分析模式、Prompt 摘要、生成时间
checkpoints      断点：每个视频的阶段快照，用于恢复
uploads          上传记录：推送到下游检测服务的状态
```

恢复逻辑：`CheckpointManager.start_or_resume(keyword, force_new=False)`
→ 命中未完成的 Run 就复用（`was_resumed=True`），并从
`get_unfinished_videos(run_id)` 取出未完成视频重新入队；否则新建 Run。

---

## 与下游项目的衔接

V2/V3 的 `pipeline/api/` 已经内置了把筛过的视频推送到下一环的能力：

```
本仓库（爬虫 + VLM 初筛）
        │  HTTP multipart 上传视频
        ▼
02-human-detection  （EdgeCrafter 目标检测 → mmpose 关键点 → ConvNeXt 持绳二分类）
        │  产出带标签的 crop / 关键点 / 分类结果
        ▼
03-clip-clustering  （CLIP 嵌入 → 层次聚类 → 正负样本切分）
```

调用示例：

```python
from pipeline.api.video_pusher import VideoPusher

pusher = VideoPusher(api_url="http://<检测服务地址>:8000", conf_threshold=0.5)
pusher.push_video("/path/to/video.mp4", wait=True)
```

`EdgeCrafterClient` 提供的接口：健康检查、服务状态、队列状态、上传视频、轮询任务完成。
`AsyncVideoPusher` 则用 `aiohttp` + `Semaphore(3)` 做并发上传。

---

## 注意事项

### ⚠️ 凭据安全

- `cookie.txt` 里的 `SESSDATA` / `bili_jct` **等同于账号密码**，拿到即可操作你的 B 站账号。
  本仓库已通过 `.gitignore` 忽略 `cookie.txt` 与 `config.json`，并提供 `.example` 模板。
- 仓库中**不包含任何真实凭据**。如果你 fork 或沿用本项目，请同样保持这一约定。
- 一旦 Cookie 或 API Key 曾经被提交过，**仅从文件里删掉是不够的** ——
  Git 历史里仍然保留完整内容，必须去对应平台**吊销并重新生成**。

### 合规与使用边界

- 本项目仅用于**个人学习与研究**，以及获取**用于模型训练的自有数据集**。
- 请遵守 B 站《用户协议》与 `robots.txt`；不要高频请求，注意 `interval_seconds` 节流。
- 下载的视频版权归原作者所有，**不要二次分发**；用于训练时请自行评估合规性。
- 大模型筛选会产生 API 费用，注意设置 `target_count` 上限与节流间隔。

### 其它

- 代码中的中文目录名（`bilibili爬虫`、`大模型接入筛选`）是 Python 的 **namespace package**，
  不需要 `__init__.py` 也能被 `import`；但如果你的环境或工具链对非 ASCII 路径支持不佳，
  建议重命名并同步修改 `sys.path.insert(...)` 处。
- 这些模块通过 `sys.path.insert` 相互引用，**请从版本根目录（如 `v3-resume/`）启动**，
  否则会出现 `ModuleNotFoundError`。

---

## License

MIT License。第三方依赖（yt-dlp、you-get、ffmpeg、智谱 SDK 等）遵循其各自许可证。

> 本项目仅供学习研究使用。使用者需自行承担因使用本项目产生的全部责任，
> 包括但不限于对目标网站的访问频率、数据版权与 API 费用。
