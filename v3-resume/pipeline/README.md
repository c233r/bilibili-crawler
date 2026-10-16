# B站视频下载与分析流水线

## 架构概述

这是一个基于生产者-消费者模式的多线程并行下载与分析系统，实现了高效的流水线处理。

```
┌────────────────────────────────────────────────────────────────┐
│                      V2 流水线版                                 │
├────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Task Queue ──> Download Workers ──> Video Queue ──> Analyze  │
│  (待下载)       (2线程并行下载)      (待分析缓冲)   Workers    │
│                                                  (3线程)       │
│                                                                  │
└────────────────────────────────────────────────────────────────┘
```

## 核心组件

### 1. 任务队列管理 (`task_queue.py`)
- 实现生产者-消费者模式的消息队列
- 支持任务状态跟踪（待处理、下载中、已下载、分析中、已完成、失败）
- 提供任务重试机制
- 实时统计和进度回调

### 2. 下载线程池 (`downloader_pool.py`)
- 多线程并行下载（默认2个线程）
- 自动从配置文件加载设置
- 支持下载路径、Cookie路径配置
- 实时下载进度监控

### 3. 分析线程池 (`analyzer_pool.py`)
- 多线程并行视频分析（默认3个线程）
- 集成大模型筛选功能
- 支持普通分析和精细化分析模式
- 实时分析结果统计

### 4. 流水线主控 (`pipeline_main.py`)
- 整合下载和分析线程池
- 提供统一的任务管理接口
- 支持搜索视频和UP主
- 完整的统计和报告功能

## 快速开始

### 基础使用

```python
from pipeline import VideoPipeline

# 创建流水线实例（2个下载线程，3个分析线程）
with VideoPipeline(num_download_workers=2, num_analyze_workers=3) as pipeline:
    
    # 方式1: 手动添加视频任务
    videos = [
        {'bvid': 'BV1GJ411x7h7', 'title': '示例视频1'},
        {'bvid': 'BV1ap4y1k7ZF', 'title': '示例视频2'},
    ]
    pipeline.add_download_tasks(videos)
    
    # 等待所有任务完成
    pipeline.wait_until_complete()
    
    # 打印统计信息
    pipeline.print_statistics()
```

### 搜索并下载

```python
from pipeline import VideoPipeline

with VideoPipeline() as pipeline:
    # 搜索关键词并下载前5个视频
    pipeline.search_and_add_videos("Python教程", max_count=5)
    
    # 等待完成
    pipeline.wait_until_complete()
```

### 搜索UP主并下载

```python
from pipeline import VideoPipeline

with VideoPipeline() as pipeline:
    # 搜索UP主并下载其视频
    pipeline.search_up_and_add_videos("某UP主名称", max_count=10)
    
    # 等待完成
    pipeline.wait_until_complete()
```

### 带筛选功能的下载

```python
from pipeline import VideoPipeline

with VideoPipeline() as pipeline:
    # 设置筛选提示词
    pipeline.set_filter_prompt(
        "视频内容是否包含技术讲解",
        use_refined=False  # 使用普通分析
    )
    
    # 搜索并下载
    pipeline.search_and_add_videos("编程教程", max_count=5)
    
    # 等待完成
    pipeline.wait_until_complete()
    
    # 获取最终报告
    report = pipeline.get_final_report()
    print(f"满足条件: {report['satisfied_count']}")
    print(f"满足率: {report['satisfaction_rate']:.1f}%")
```

### 精细化分析模式

```python
from pipeline import VideoPipeline

with VideoPipeline() as pipeline:
    # 设置筛选提示词（使用精细化分析）
    pipeline.set_filter_prompt(
        "视频是否包含详细的代码讲解",
        use_refined=True  # 使用精细化分析
    )
    
    # 搜索并下载
    pipeline.search_and_add_videos("编程教程", max_count=5)
    
    # 等待完成
    pipeline.wait_until_complete()
```

## 配置说明

流水线会自动从 `bilibili爬虫/config.json` 加载配置：

```json
{
  "download_path": "D:/Downloads/bilibili",
  "cookies_path": "bilibili爬虫/src/cookie.txt",
  "use_ytdlp": true
}
```

## 运行示例

提供了完整的使用示例：

```bash
# 运行示例程序
python pipeline/example.py
```

示例程序包含：
1. 基础下载功能（不使用筛选）
2. 搜索并下载视频
3. 搜索UP主并下载其视频
4. 带筛选功能的下载
5. 自定义配置

## 核心特性

### 1. 多线程并行处理
- 下载线程池：2个线程并行下载
- 分析线程池：3个线程并行分析
- 线程安全的数据结构

### 2. 流水线架构
- 生产者-消费者模式
- 任务队列缓冲
- 下载和分析解耦

### 3. 智能任务管理
- 自动任务重试
- 失败任务处理
- 实时进度跟踪

### 4. 完整的统计功能
- 下载统计
- 分析统计
- 性能指标
- 最终报告

### 5. 灵活的配置
- 可配置线程数量
- 支持多种下载模式
- 集成大模型筛选

## 性能优势

相比单线程版本：
- **下载速度提升**: 2个线程并行下载，速度提升约2倍
- **分析效率提升**: 3个线程并行分析，充分利用CPU资源
- **系统吞吐量**: 流水线架构，下载和分析同时进行
- **资源利用率**: 更好地利用网络和CPU资源

## 注意事项

1. **线程数量**: 根据网络带宽和CPU性能调整线程数量
2. **队列大小**: 默认队列大小为100，可根据需求调整
3. **API限制**: 注意B站API的调用频率限制
4. **磁盘空间**: 确保有足够的磁盘空间存储视频
5. **网络稳定性**: 不稳定的网络可能导致下载失败

## 扩展性

系统设计具有良好的扩展性：

1. **自定义线程数量**: 可根据需求调整下载和分析线程数量
2. **自定义筛选逻辑**: 可扩展筛选API实现自定义筛选逻辑
3. **自定义任务类型**: 可扩展任务队列支持其他类型的任务
4. **自定义统计**: 可扩展统计功能收集更多指标

## 故障排查

### 下载失败
- 检查网络连接
- 检查Cookie是否有效
- 检查磁盘空间
- 查看错误日志

### 分析失败
- 检查大模型API配置
- 检查API Key是否有效
- 检查视频文件是否存在
- 查看错误日志

### 性能问题
- 调整线程数量
- 检查网络带宽
- 检查CPU使用率
- 检查磁盘I/O性能

## 技术栈

- **Python 3.7+**
- **多线程**: threading, queue
- **B站API**: bilibili爬虫
- **视频下载**: yt-dlp/you-get
- **大模型筛选**: 智谱AI

## 许可证

MIT License

## 作者

B站爬虫项目团队