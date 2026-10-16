"""
Pipeline主入口文件
整合动态线程池，实现完整的流水线功能
支持根据队列状态动态分配线程资源
V3持久化版：支持数据库持久化和断点续传
"""

import os
import sys
import threading
import time
import json
from typing import Optional

# 添加爬虫模块路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bilibili爬虫', 'src'))

# 添加V3持久化模块路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from model.bilibili_api import BilibiliAPI
from .task_queue import TaskQueue
from ..threads.dynamic_pool import DynamicThreadPool
from ..threads.monitor_thread import PipelineMonitor
from ..log.logger import get_main_logger, get_stats_logger
from ..api.video_pusher import VideoPusher, AsyncVideoPusher

# V3 持久化模块
from sql import get_database, CheckpointManager, RunStatus, VideoStatus, UploadStatus


class VideoPipeline:
    """视频下载与分析流水线（V3持久化版）"""
    
    def __init__(self, total_workers: int = 5):
        """
        初始化流水线
        
        Args:
            total_workers: 总线程数量（动态分配给下载和分析）
        """
        # 初始化日志器
        self.logger = get_main_logger()
        # 创建共享任务队列
        self.task_queue = TaskQueue()
        
        # 创建动态线程池（替代原来的下载池和分析池）
        self.dynamic_pool = DynamicThreadPool(
            total_workers=total_workers,
            task_queue=self.task_queue
        )
        
        # 设置回调函数（用于收集满足条件的视频）
        self.dynamic_pool.set_callback(self.add_satisfied_video_with_unique_source)
        
        # 初始化B站API
        self.api = BilibiliAPI()
        
        # 配置文件路径
        # pipeline_main.py 在 pipeline/control/ 下，需要 3 层 dirname 到达项目根目录
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.config_file = os.path.join(
            project_root, 
            'bilibili爬虫', 
            'config.json'
        )
        
        # 加载配置
        self._load_config()
        
        # V3 持久化 - 初始化数据库和断点续传管理器
        self.db = get_database()
        self.checkpoint_manager = CheckpointManager(self.db)
        self.current_run = None
        
        # 统计信息
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        
        # BV号哈希表（防止重复下载）
        self._processed_bvids = set()
        self._bvid_lock = threading.Lock()
        
        # 视频推送器（延迟初始化）
        self.video_pusher: Optional[VideoPusher] = None
        
        # 满足条件的视频列表（用于推送，按片段）
        self.satisfied_videos: list[str] = []
        
        # 已满足的原始视频集合（按原始视频去重，用于计数）
        self._satisfied_source_videos: set[str] = set()
        
        # 断点续传时从数据库恢复的满足计数
        self._base_satisfied_count = 0
        
        # 推送队列（线程安全）
        self._push_queue = None
        
        # 推送监控线程
        self.push_monitor_thread = None
        self.push_monitor_running = False
        
        # 目标数量设置
        self.target_count = 0
        self.target_satisfied = 0
        
        # 监控线程
        self.monitor_thread = None
        self.stats_interval = 2.0
        
        # 停止事件（用于通知主线程退出）
        self._stop_event = threading.Event()
        self._was_stopped = False  # 标记是否为手动停止（而非正常完成）
        self._phase = 'running'  # 'running' | 'draining' | 'stopped'
    
    def _load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                    # 设置下载路径
                    download_path = config.get('download_path', '')
                    if download_path:
                        self.dynamic_pool.set_download_path(download_path)
                    
                    # 设置Cookie路径
                    cookies_path = config.get('cookies_path', '')
                    if cookies_path and os.path.exists(cookies_path):
                        # 需要获取下载器实例来设置cookie
                        pass
                    
                    # 设置是否使用yt-dlp
                    use_ytdlp = config.get('use_ytdlp', True)
                    # 需要获取下载器实例来设置
                    pass
                    
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
    
    def set_filter_prompt(self, prompt: str, use_refined: bool = False):
        """
        设置筛选提示词
        
        Args:
            prompt: 筛选提示词
            use_refined: 是否使用精细化分析
        """
        # 添加大模型筛选模块路径
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '大模型接入筛选'))
        
        from filter_api import create_filter_api_from_config
        
        # 构建配置文件路径
        filter_config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
            '大模型接入筛选', 
            'config.json'
        )
        
        # 从配置文件创建筛选API
        filter_api = create_filter_api_from_config(filter_config_path)
        
        if filter_api:
            self.dynamic_pool.set_filter_api(filter_api, prompt, use_refined)
            self.logger.info(f"筛选提示词已设置（精细化分析: {use_refined}）")
        else:
            self.logger.error("筛选API初始化失败，请检查配置文件中的api_key")
    
    def add_download_tasks(self, videos: list[dict]) -> tuple[int, list[dict]]:
        """
        批量添加下载任务（根据队列剩余容量动态调整）
        
        Args:
            videos: 视频列表，每个元素包含bvid和title
        
        Returns:
            (成功添加的任务数量, 未能添加的视频列表)
        """
        # 过滤重复的 BV 号
        unique_videos = []
        with self._bvid_lock:
            for video in videos:
                bvid = video.get('bvid', '')
                if bvid and bvid not in self._processed_bvids:
                    self._processed_bvids.add(bvid)
                    unique_videos.append(video)
                elif bvid:
                    self.logger.debug(f"[去重] 跳过重复视频: {video.get('title', '未知')} (BV: {bvid})")
        
        added_count = 0
        total_page_count = 0
        added_video_names = []
        
        for video in unique_videos:
            bvid = video.get('bvid', '')
            title = video.get('title', '未知')
            
            if not bvid:
                continue
            
            # 先查询该视频的分集数量
            page_count = self.api.get_video_pages(bvid)
            
            # 分批次添加分集：能塞多少塞多少，避免死循环
            page_added = 0
            next_page = 1
            while next_page <= page_count:
                remaining = self.task_queue.get_download_remaining()
                if remaining <= 0:
                    time.sleep(0.5)
                    continue
                
                # 当前批次：取剩余空位与剩余分集的较小值
                batch_end = min(next_page + remaining - 1, page_count)
                for p in range(next_page, batch_end + 1):
                    success = self.dynamic_pool.add_download_task(bvid, title, page=p)
                    if success:
                        page_added += 1
                        total_page_count += 1
                
                next_page = batch_end + 1
                
                if next_page <= page_count:
                    # 还有分集没加完，等队列消耗后再加
                    time.sleep(0.5)
            
            if page_added > 0:
                added_count += 1
                if page_count > 1:
                    added_video_names.append(f"{title} (BV: {bvid}, {page_count}P)")
                else:
                    added_video_names.append(f"{title} (BV: {bvid})")
        
        if added_video_names:
            self.logger.debug(f"[下载队列] 已添加视频: {', '.join(added_video_names)}")
        
        self.logger.info(f"已添加 {added_count} 个视频（共 {total_page_count} 个分集任务）")
        
        # V3 持久化 - 保存已发现的视频到数据库
        if self.current_run:
            for video in unique_videos:
                bvid = video.get('bvid', '')
                title = video.get('title', '未知')
                self.checkpoint_manager.on_video_discovered(
                    self.current_run.run_id, bvid, title
                )
        
        # 等待模式下不再有跳过视频，始终返回空列表
        return added_count, []
    
    # ─── V3 持久化接口 ─────────────────────────────────────
    
    def start_run(
        self,
        keyword: str,
        search_type: str = 'video',
        target_count: int = 0,
        use_refined: bool = False,
        filter_prompt: str = "",
        force_new: bool = False,
    ):
        """
        V3 启动或恢复运行（断点续传）
        
        Args:
            keyword: 搜索关键词
            search_type: 'video' | 'up'
            target_count: 目标下载数量
            use_refined: 是否精细化分析
            filter_prompt: 筛选Prompt
            force_new: 是否强制创建新运行（忽略断点）
        
        Returns:
            当前运行记录
        """
        self.current_run = self.checkpoint_manager.start_or_resume(
            keyword=keyword,
            search_type=search_type,
            target_count=target_count,
            use_refined=use_refined,
            filter_prompt=filter_prompt,
            total_workers=self.dynamic_pool.total_workers,
            force_new=force_new,
        )
        self.target_satisfied = target_count
        
        # 加载所有已处理的 BV 号到哈希表（防止重复下载）
        from sql.repos import VideoRepo
        all_videos = VideoRepo.list_all(self.db, self.current_run.run_id)
        with self._bvid_lock:
            self._processed_bvids = {v.bvid for v in all_videos}
        self.logger.info(f"[去重] 已加载 {len(self._processed_bvids)} 个已处理的 BV 号")
        
        # 恢复统计信息（断点续传时恢复内存计数器）
        if not force_new and self.current_run.status == RunStatus.RUNNING:
            stats = self.checkpoint_manager.get_statistics(self.current_run.run_id)
            db_completed = int(stats.get('completed', 0) or 0)
            db_failed = int(stats.get('failed', 0) or 0)
            db_satisfied = int(stats.get('satisfied_count', 0) or 0)

            # 恢复任务队列计数（内存计数器从DB值开始累加）
            self.task_queue.completed_count = db_completed
            self.task_queue.failed_count = db_failed
            self._base_satisfied_count = db_satisfied

            self.logger.info(f"[恢复统计] 已完成={db_completed}, 失败={db_failed}, 满足={db_satisfied}")
        
        # 如果是恢复运行，加载未完成的视频
        if self.current_run.status == RunStatus.RUNNING:
            unfinished_videos = self.checkpoint_manager.get_unfinished_videos(
                self.current_run.run_id
            )
            if unfinished_videos:
                self.logger.info(f"[断点续传] 恢复 {len(unfinished_videos)} 个未完成视频")
                for video in unfinished_videos:
                    if video.status in (VideoStatus.PENDING, VideoStatus.DOWNLOADING):
                        self.dynamic_pool.add_download_task(video.bvid, video.title)
                    elif video.status == VideoStatus.DOWNLOADED and video.download_path:
                        from pipeline.control.task_queue import DownloadTask
                        task = DownloadTask(
                            bvid=video.bvid,
                            title=video.title,
                            video_path=video.download_path,
                            retry_count=video.retry_count,
                            max_retries=video.max_retries
                        )
                        self.task_queue.add_video_task(task)
        
        # 恢复待上传的视频到推送队列（断点续传）
        if self.current_run and self._push_queue is not None:
            pending_uploads = self.checkpoint_manager.get_pending_uploads(
                self.current_run.run_id
            )
            if pending_uploads:
                self.logger.info(f"[断点续传] 恢复 {len(pending_uploads)} 个待上传视频")
                for rec in pending_uploads:
                    if os.path.exists(rec.video_path):
                        # 文件还在，重新加入推送队列
                        self._push_queue.put(rec.video_path)
                        self.logger.info(f"[断点续传] 恢复推送任务: {os.path.basename(rec.video_path)}")
                    else:
                        # 文件已删除 → 说明已下载+分析过，只恢复满足计数，不用重新下载
                        if rec.video_path not in self.satisfied_videos:
                            self.satisfied_videos.append(rec.video_path)
                            source_key = self._get_source_video_key(rec.video_path)
                            self._satisfied_source_videos.add(source_key)
                        self.logger.info(f"[断点续传] 文件已清理，恢复满足计数: {os.path.basename(rec.video_path)}")
                        # 清理数据库记录（已计入满足，不再需要上传）
                        self.checkpoint_manager.on_upload_success(rec.id)
        
        return self.current_run
    
    def save_progress(self, progress: dict):
        """
        V3 保存进度快照
        
        Args:
            progress: 进度数据，如 {"page": 5, "satisfied_count": 3}
        """
        if self.current_run:
            self.checkpoint_manager.save_progress(self.current_run.run_id, progress)
    
    def on_video_downloading(self, bvid: str):
        """V3 视频开始下载"""
        if self.current_run:
            self.checkpoint_manager.on_video_downloading(self.current_run.run_id, bvid)
    
    def on_video_downloaded(self, bvid: str, download_path: str):
        """V3 视频下载完成"""
        if self.current_run:
            self.checkpoint_manager.on_video_downloaded(
                self.current_run.run_id, bvid, download_path
            )
    
    def on_video_analyzing(self, bvid: str):
        """V3 视频开始分析"""
        if self.current_run:
            self.checkpoint_manager.on_video_analyzing(self.current_run.run_id, bvid)
    
    def on_video_completed(self, bvid: str):
        """V3 视频处理完成"""
        if self.current_run:
            self.checkpoint_manager.on_video_completed(self.current_run.run_id, bvid)
    
    def on_video_failed(self, bvid: str, error_message: str = ""):
        """V3 视频处理失败"""
        if self.current_run:
            self.checkpoint_manager.on_video_failed(
                self.current_run.run_id, bvid, error_message
            )
    
    def save_analysis_result(
        self,
        bvid: str,
        satisfied: bool,
        analysis_mode: str,
        prompt_used: str,
        confidence: float = 0.0,
        result_detail: dict = None,
        segment_paths: list = None,
        source_frame_count: int = 0,
        satisfied_frame_count: int = 0,
        duration_ms: float = 0.0,
        api_duration_ms: float = 0.0,
    ):
        """
        V3 保存分析结果（自动构建数据血缘）
        
        Args:
            bvid: 视频BV号
            satisfied: 是否满足条件
            analysis_mode: 'basic' | 'refined'
            prompt_used: 使用的Prompt
            confidence: 置信度
            result_detail: 结果详情
            segment_paths: 片段路径列表
            source_frame_count: 总抽帧数
            satisfied_frame_count: 满足帧数
            duration_ms: 总耗时（毫秒）
            api_duration_ms: API耗时（毫秒）
        
        Returns:
            结果记录ID
        """
        if not self.current_run:
            return 0
        
        video = self.checkpoint_manager.db.get_connection().execute(
            "SELECT id FROM videos WHERE run_id = ? AND bvid = ?",
            (self.current_run.run_id, bvid)
        ).fetchone()
        
        if video:
            return self.checkpoint_manager.save_analysis_result(
                video_id=video[0],
                run_id=self.current_run.run_id,
                bvid=bvid,
                satisfied=satisfied,
                analysis_mode=analysis_mode,
                prompt_used=prompt_used,
                confidence=confidence,
                result_detail=result_detail,
                segment_paths=segment_paths,
                source_frame_count=source_frame_count,
                satisfied_frame_count=satisfied_frame_count,
                duration_ms=duration_ms,
                api_duration_ms=api_duration_ms,
            )
        return 0
    
    def finish_run(self):
        """V3 标记运行完成"""
        if self.current_run:
            self.checkpoint_manager.finish(self.current_run.run_id)
            self.current_run = None
    
    def stop_run(self):
        """V3 暂停运行（保留断点）"""
        if self.current_run:
            self.checkpoint_manager.stop(self.current_run.run_id)
    
    def get_run_statistics(self) -> dict:
        """V3 获取当前运行的数据库统计"""
        if self.current_run:
            return self.checkpoint_manager.get_statistics(self.current_run.run_id)
        return {}
    
    def export_lineage(self) -> list:
        """V3 导出数据血缘"""
        if self.current_run:
            return self.checkpoint_manager.export_lineage(self.current_run.run_id)
        return []
    
    def start(self):
        """启动流水线"""
        self.logger.info(f"启动流水线...")
        self.logger.info(f"总线程数: {self.dynamic_pool.total_workers}")
        
        # V3 持久化 - 设置回调（在启动线程池之前设置）
        self.task_queue.set_status_change_callback(self._on_status_change)
        self.dynamic_pool.set_status_change_callback(self._on_status_change)
        self.dynamic_pool.set_analysis_result_callback(self.save_analysis_result)
        
        # 启动动态线程池
        self.dynamic_pool.start()
        
        # 创建并启动监控线程（整合统计、负载均衡和停止控制）
        self.monitor_thread = PipelineMonitor(
            name="PipelineMonitor",
            interval=self.stats_interval,
            get_statistics_callback=self._output_statistics,
            check_stop_callback=self._check_stop_condition,
            stop_callback=self._graceful_shutdown,
            load_balance_callback=self.dynamic_pool.balance_workers,
        )
        self.monitor_thread.start()
        self.logger.info("监控线程已启动")
        
        # 记录开始时间
        self.start_time = time.time()
        
        self.logger.info(f"流水线已启动")
    
    def _on_status_change(self, status: str, task, **kwargs):
        """
        V3 持久化 - 状态变更回调处理
        
        Args:
            status: 变更后的状态（downloading/downloaded/analyzing/completed/failed）
            task: DownloadTask 对象
            kwargs: 额外参数（video_path, error_message）
        """
        try:
            bvid = getattr(task, 'bvid', '')
            if not bvid:
                return
            
            if status == 'downloading':
                self.on_video_downloading(bvid)
            elif status == 'downloaded':
                video_path = kwargs.get('video_path', '')
                self.on_video_downloaded(bvid, video_path)
            elif status == 'analyzing':
                self.on_video_analyzing(bvid)
            elif status == 'completed':
                self.on_video_completed(bvid)
            elif status == 'failed':
                error_message = kwargs.get('error_message', '')
                self.on_video_failed(bvid, error_message)
        except Exception as e:
            self.logger.error(f"[V3持久化] 状态变更回调异常: {str(e)}")
    
    def stop(self):
        """停止流水线（快速停止）"""
        self.logger.info(f"停止流水线...")
        
        # 设置停止事件，通知所有线程退出
        self._graceful_shutdown()
        
        # 交由统一清理流程处理（推送队列 drain + 重试 + 线程停止）
        self._cleanup_after_shutdown()
        
        self.logger.info(f"流水线已停止")
    
    def _output_statistics(self):
        """输出统计信息（供监控线程调用）"""
        try:
            queue_stats = self.task_queue.get_statistics()
            pool_stats = self.dynamic_pool.get_statistics()
            
            stats_logger = get_stats_logger()
            stats_logger.info(f"[流水线统计] 已完成={queue_stats['completed_count']}, "
                              f"失败={queue_stats['failed_count']}, "
                              f"待下载={queue_stats['pending_download']}, "
                              f"待分析={queue_stats['pending_analysis']}, "
                              f"满足={len(self.satisfied_videos) + self._base_satisfied_count}")
            stats_logger.info(f"[线程池统计] 总线程={pool_stats['total_workers']}, "
                              f"下载线程={pool_stats['download_workers']}, "
                              f"分析线程={pool_stats['analyze_workers']}")
        except Exception as e:
            stats_logger = get_stats_logger()
            stats_logger.error(f"统计监控线程异常: {str(e)}")
    
    def _check_stop_condition(self) -> bool:
        """检查是否需要停止流水线（供监控线程调用）"""
        completed = self.task_queue.get_completed_count()
        satisfied = len(self._satisfied_source_videos) + self._base_satisfied_count
        
        # 输出当前目标值和实际值，便于调试
        stats_logger = get_stats_logger()
        stats_logger.info(f"[停止条件检查] target_count={self.target_count}, "
                          f"target_satisfied={self.target_satisfied}, "
                          f"completed={completed}, "
                          f"satisfied={satisfied}")
        
        # ── Phase 1: 达到目标 → 进入排空阶段 ──
        if self._phase == 'running':
            if self.target_satisfied > 0 and satisfied >= self.target_satisfied:
                self.logger.info(f"已达到目标满足数量 ({satisfied}/{self.target_satisfied} 个)，进入排空阶段")
                self._enter_draining_phase()
                return False  # 不触发完全关闭，等待排空完成
            
            if self.target_count > 0 and completed >= self.target_count:
                self.logger.info(f"已达到目标完成数量 ({completed}/{self.target_count} 个)，进入排空阶段")
                self._enter_draining_phase()
                return False
        
        # ── Phase 2: 排空阶段 → 检查是否全部完成 ──
        if self._phase == 'draining':
            if self._is_drain_complete():
                self.logger.info("所有分析和推送任务已完成，准备完全关闭")
                return True
        
        return False
    
    def _enter_draining_phase(self):
        """进入排空阶段：停止下载，等待剩余分析和推送完成"""
        self._phase = 'draining'
        
        # 设置任务队列为排空模式（禁止添加新下载任务）
        self.task_queue.set_draining(True)
        
        # 清空下载队列（不再下载新视频）
        cleared = self.task_queue.clear_download_queue()
        self.logger.info(f"[排空] 已清空下载队列 ({cleared} 个任务)")
        
        # 通知线程池：下载结束，全部线程切去分析
        self.dynamic_pool.all_to_analyze = True
        self.logger.info("[排空] 已设置线程池全部投入分析模式")
        
        self.logger.info("[排空] 等待剩余分析和推送完成...")
    
    def _is_drain_complete(self) -> bool:
        """检查排空阶段是否完成"""
        video_qsize = self.task_queue.video_queue.qsize()
        push_qsize = self._push_queue.qsize() if self._push_queue else 0
        
        stats_logger = get_stats_logger()
        stats_logger.info(f"[排空检查] 待分析={video_qsize}, 待推送={push_qsize}")
        
        if video_qsize == 0 and push_qsize == 0:
            return True
        return False
    
    def _graceful_shutdown(self):
        """
        优雅关闭流程：
        1. 设置停止事件，通知主线程退出
        2. 主线程负责清理工作
        """
        self.logger.info("开始优雅关闭流程...")
        
        # 排空阶段自然完成时不标记为手动停止（返回 "completed"）
        # 手动调用 stop() 时标记为手动停止（返回 "stopped"）
        if self._phase != 'draining':
            self._was_stopped = True
        
        # 立即设置停止事件，通知主线程退出
        self._stop_event.set()
        
        self.logger.info("已通知主线程开始清理")
    
    def enable_video_push(self, api_url: str = 'http://localhost:8000', conf_threshold: float = 0.5, use_async: bool = True):
        """
        启用视频推送功能
        
        Args:
            api_url: EdgeCrafter API服务地址
            conf_threshold: 置信度阈值
            use_async: 是否使用异步推送
        """
        import queue
        
        if use_async:
            self.video_pusher = AsyncVideoPusher(api_url, conf_threshold)
            self.logger.info(f"视频推送功能已启用（异步模式），API地址: {api_url}")
        else:
            self.video_pusher = VideoPusher(api_url, conf_threshold)
            self.logger.info(f"视频推送功能已启用（同步模式），API地址: {api_url}")
        self.video_pusher.set_logger(self.logger)
        
        # 初始化推送队列（线程安全）
        self._push_queue = queue.Queue()
        
        # 启动推送监控线程
        self.push_monitor_running = True
        self.push_monitor_thread = threading.Thread(target=self._push_monitor_loop, name="PushMonitor")
        self.push_monitor_thread.daemon = True
        self.push_monitor_thread.start()
        self.logger.info("推送监控线程已启动")
    
    def add_satisfied_video(self, video_paths: list[str]):
        """
        添加满足条件的视频到推送队列
        
        Args:
            video_paths: 视频文件路径列表（精细化分析时可能有多个片段）
        """
        if not self.video_pusher:
            self.logger.warning("视频推送功能未启用，跳过推送")
            return
        
        for video_path in video_paths:
            if video_path not in self.satisfied_videos:
                self.satisfied_videos.append(video_path)
                self.logger.info(f"已添加满足条件的视频: {os.path.basename(video_path)}")
                
                # 将视频路径放入推送队列
                if self._push_queue is not None:
                    self._push_queue.put(video_path)
                    self.logger.debug(f"已加入推送队列: {os.path.basename(video_path)}")
    
    def _get_source_video_key(self, video_path: str) -> str:
        """
        从片段文件名提取原始视频标识（去重用）
        
        文件名格式: {原始视频名}_{片段号}_{开始时间}-{结束时间}.mp4
        例如: 人类无差别单打精华——凯文·杜兰特_1_30-150.mp4
        
        Returns:
            str: 原始视频标识（不含片段号和时间范围）
        """
        basename = os.path.splitext(os.path.basename(video_path))[0]
        parts = basename.split('_')
        if len(parts) >= 3:
            return '_'.join(parts[:-2])
        return basename
    
    def add_satisfied_video_with_unique_source(self, video_paths: list[str]):
        """
        添加满足条件的视频到推送队列（按原始视频去重计数）
        同时记录到数据库，支持断点续传
        
        Args:
            video_paths: 视频文件路径列表（精细化分析时可能有多个片段）
        """
        # 先计数：无论是否启用推送，都要记录满足数量
        for video_path in video_paths:
            if video_path not in self.satisfied_videos:
                self.satisfied_videos.append(video_path)
                
                # 提取原始视频标识，用于去重计数
                source_key = self._get_source_video_key(video_path)
                self._satisfied_source_videos.add(source_key)
                
                # 记录到数据库（断点续传用）
                if self.current_run:
                    basename = os.path.basename(video_path)
                    title = os.path.splitext(basename)[0]
                    # 从文件名尝试提取bvid（文件名格式类似: {bvid}_xxx.mp4）
                    # 如果无法提取，使用源key作为bvid
                    parts = basename.split('_')
                    bvid = parts[0] if len(parts) >= 1 else source_key
                    
                    self.checkpoint_manager.on_upload_pending(
                        run_id=self.current_run.run_id,
                        bvid=bvid,
                        title=title,
                        video_path=video_path,
                    )
                    self.logger.debug(f"[上传记录] 已记录待上传: {basename}")
        
        # 再推送：如果没有启用推送功能则跳过
        if not self.video_pusher:
            self.logger.debug("视频推送功能未启用，跳过推送")
            return
        
        for video_path in video_paths:
            if self._push_queue is not None:
                self._push_queue.put(video_path)
                self.logger.debug(f"已加入推送队列: {os.path.basename(video_path)}")
    
    def _push_monitor_loop(self):
        """
        推送监控线程循环
        
        负责从推送队列中获取视频路径并推送，与分析线程完全隔离
        """
        self.logger.info("[推送监控] 线程已启动，开始监听推送队列...")
        
        total_processed = 0
        success_count = 0
        fail_count = 0
        
        while self.push_monitor_running:
            try:
                # 等待队列中有视频（最多等待1秒）
                video_path = self._push_queue.get(timeout=1)
                
                self.logger.info(f"[推送监控] 获取到推送任务: {os.path.basename(video_path)}, 队列剩余: {self._push_queue.qsize()}")
                
                self._process_push_task(video_path)
                
                # 标记任务完成
                self._push_queue.task_done()
                total_processed += 1
                
            except Exception:
                # 队列空或其他异常，继续循环
                continue
        
        self.logger.info(f"[推送监控] 进入排空阶段，已处理 {total_processed} 个任务(成功:{success_count},失败:{fail_count})")
        
        # 排空队列：多次尝试，防止分析线程刚刚添加但尚未入队的新任务
        max_drain_attempts = 5
        drain_count = 0
        for attempt in range(max_drain_attempts):
            drained_any = False
            while not self._push_queue.empty():
                try:
                    video_path = self._push_queue.get_nowait()
                    self.logger.info(f"[推送监控] 排空处理: {os.path.basename(video_path)}")
                    self._process_push_task(video_path)
                    self._push_queue.task_done()
                    drained_any = True
                    drain_count += 1
                except Exception:
                    break
            
            if not drained_any:
                break  # 连续两次都没新任务，认为已排空完成
            
            self.logger.info(f"[推送监控] 排空第{attempt+1}轮完成，已排空 {drain_count} 个任务")
            
            # 仍有任务被处理，等一会儿再看是否有新的
            time.sleep(0.5)
        
        self.logger.info(f"[推送监控] 线程已停止，共处理 {total_processed + drain_count} 个任务")
    
    def _process_push_task(self, video_path: str):
        """
        处理单个推送任务
        
        Args:
            video_path: 视频文件路径
        """
        if not self.video_pusher:
            return
        
        if not os.path.exists(video_path):
            self.logger.warning(f"[视频推送] 文件不存在: {os.path.basename(video_path)}")
            return
        
        basename = os.path.basename(video_path)
        self.logger.info(f"[视频推送] 开始推送: {basename}")
        
        # 查找数据库中的上传记录ID
        upload_record_id = None
        if self.current_run:
            try:
                from sql.repos import UploadRepo
                records = UploadRepo.get_pending(self.db, self.current_run.run_id)
                for rec in records:
                    if rec.video_path == video_path:
                        upload_record_id = rec.id
                        break
            except Exception:
                pass
        
        try:
            if isinstance(self.video_pusher, AsyncVideoPusher):
                # 异步推送器：在独立线程中执行，避免阻塞监控循环
                result = self.video_pusher.push_videos_sync([video_path], wait=False)
                if result and result[0].get('status') == 'success':
                    task_id = result[0].get('task_id', 'N/A')
                    self.logger.info(f"[视频推送] 成功: {basename}, 任务ID: {task_id}")
                    # 更新数据库记录
                    if upload_record_id and self.current_run:
                        self.checkpoint_manager.on_upload_success(upload_record_id)
                    self._delete_video_file(video_path)
                else:
                    error_msg = result[0].get('message') or result[0].get('error', '') if result else ''
                    self.logger.error(f"[视频推送] 失败: {basename}, 错误: {error_msg}")
                    # 更新数据库记录为失败
                    if upload_record_id and self.current_run:
                        self.checkpoint_manager.on_upload_failed(upload_record_id, error_msg)
            else:
                # 同步推送器：直接推送
                result = self.video_pusher.push_video(video_path, wait=False)
                if result.get('status') == 'success':
                    task_id = result.get('task_id', 'N/A')
                    self.logger.info(f"[视频推送] 成功: {basename}, 任务ID: {task_id}")
                    # 更新数据库记录
                    if upload_record_id and self.current_run:
                        self.checkpoint_manager.on_upload_success(upload_record_id)
                    self._delete_video_file(video_path)
                else:
                    error_msg = result.get('message') or result.get('error', '')
                    self.logger.warning(f"[视频推送] 失败: {basename}, 错误: {error_msg}")
                    # 更新数据库记录为失败
                    if upload_record_id and self.current_run:
                        self.checkpoint_manager.on_upload_failed(upload_record_id, error_msg)
        except Exception as e:
            self.logger.error(f"[视频推送] 异常: {os.path.basename(video_path)}, {str(e)}")
            # 更新数据库记录为失败
            if upload_record_id and self.current_run:
                self.checkpoint_manager.on_upload_failed(upload_record_id, str(e))
    
    def _delete_video_file(self, video_path: str):
        """
        删除本地视频文件
        
        Args:
            video_path: 视频文件路径
        """
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
                self.logger.info(f"[视频清理] 已删除本地视频片段: {os.path.basename(video_path)}")
            except Exception as e:
                self.logger.warning(f"[视频清理] 删除本地视频片段失败: {video_path}, {str(e)}")
    
    def push_satisfied_videos(self, wait: bool = False):
        """
        推送所有满足条件的视频到服务器（仅推送尚未推送的视频）
        
        注意：由于视频在分析完成后会立即推送，此方法主要用于推送之前推送失败的视频
        
        Args:
            wait: 是否等待处理完成
        
        Returns:
            推送结果列表
        """
        if not self.video_pusher:
            self.logger.warning("视频推送功能未启用，请先调用 enable_video_push()")
            return []
        
        # 过滤出仍然存在的视频（未被删除的）
        existing_videos = [v for v in self.satisfied_videos if os.path.exists(v)]
        
        if not existing_videos:
            self.logger.info("没有需要推送的视频（所有视频已推送并删除）")
            return []
        
        self.logger.info(f"开始推送 {len(existing_videos)} 个剩余视频...")
        
        if isinstance(self.video_pusher, AsyncVideoPusher):
            results = self.video_pusher.push_videos_sync(existing_videos, wait=wait)
        else:
            results = self.video_pusher.push_videos(existing_videos, wait=wait)
        
        success_count = sum(1 for r in results if r.get('status') == 'success')
        self.logger.info(f"视频推送完成，成功: {success_count}/{len(results)}")
        
        # 上传成功后删除本地视频片段
        deleted_count = 0
        for video_path in existing_videos:
            if os.path.exists(video_path):
                try:
                    os.remove(video_path)
                    self.logger.info(f"[视频清理] 已删除本地视频片段: {os.path.basename(video_path)}")
                    deleted_count += 1
                except Exception as e:
                    self.logger.warning(f"[视频清理] 删除本地视频片段失败: {video_path}, {str(e)}")
        
        if deleted_count > 0:
            self.logger.info(f"[视频清理] 共删除 {deleted_count} 个本地视频片段")
        
        return results
    
    def wait_until_complete(self, check_interval: float = 2.0, target_count: int = 0, target_satisfied: int = 0):
        """
        等待直到所有任务完成
        
        停止逻辑由监控线程负责，此方法仅设置目标值并打印统计信息
        
        Args:
            check_interval: 检查间隔（秒）
            target_count: 目标完成数量（0表示等待所有任务）
            target_satisfied: 目标满足条件数量（0表示不限制）
        
        Returns:
            str: 停止原因，"completed"（正常完成）或 "stopped"（手动停止）
        """
        self.target_count = target_count
        self.target_satisfied = target_satisfied
        
        self.logger.info(f"等待任务完成... (目标完成: {target_count}, 目标满足: {target_satisfied})")
        self.logger.info(f"监控线程状态: {'运行中' if self.monitor_thread and self.monitor_thread.running else '未启动'}")
        
        # 如果停止事件已被设置（来自监控线程），直接进入清理
        if self._stop_event.is_set():
            self.logger.info("检测到停止事件已设置，直接开始清理")
            self._cleanup_after_shutdown()
            
            if self.start_time and not self.end_time:
                self.end_time = time.time()
            return "completed" if not self._was_stopped else "stopped"
        
        while not self._stop_event.is_set():
            # 打印统计信息
            self.print_statistics()
            
            # 等待（停止条件由监控线程检查）
            time.sleep(check_interval)
        
        # 收到停止事件，执行清理工作
        self._cleanup_after_shutdown()
        
        if self.start_time and not self.end_time:
            self.end_time = time.time()
        
        return "completed" if not self._was_stopped else "stopped"
    
    def _cleanup_after_shutdown(self):
        """优雅关闭后的清理工作"""
        self.logger.info("开始清理工作...")
        
        # 1. 清空剩余队列（不再接受新任务）
        self.task_queue.clear()
        self.logger.info("已清空剩余任务队列")
        
        # 2. 阻塞所有线程（暂停执行任务，不再处理新任务）
        self.logger.info("阻塞所有工作线程...")
        self.dynamic_pool.block_all()
        
        # 3. 记录结束时间
        self.end_time = time.time()
        
        # 4. 停止推送监控线程
        # 注意：推送完全由 PushMonitor 负责，Main-0 不做推送
        # 排空阶段已确保推送队列清空后才进入此处
        self.push_monitor_running = False
        if self.push_monitor_thread:
            self.push_monitor_thread.join(timeout=120)
            self.logger.info("推送监控线程已停止")
        
        # 5. 停止监控线程
        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.join(timeout=5)
            self.logger.info("监控线程已停止")
        
        # 6. 停止线程池
        self.dynamic_pool.stop()
        
        self.logger.info("所有任务已完成，准备退出")
    
    def print_statistics(self) -> dict:
        """打印流水线统计信息并返回统计数据"""
        print(f"\n{'='*60}")
        print(f"[流水线统计]")
        print(f"{'='*60}")
        
        queue_stats = self.task_queue.get_statistics()
        pool_stats = self.dynamic_pool.get_statistics()
        
        self.task_queue.print_statistics()
        
        print(f"\n[动态线程池统计]")
        print(f"总线程数: {pool_stats['total_workers']}")
        print(f"下载线程数: {pool_stats['download_workers']}")
        print(f"分析线程数: {pool_stats['analyze_workers']}")
        
        print(f"\n[线程详细统计]")
        for worker in pool_stats['worker_stats']:
            print(f"  线程-{worker['worker_id']}: 角色={worker['role']}, "
                  f"下载={worker['downloaded_count']}, 分析={worker['analyzed_count']}, "
                  f"满足={worker['satisfied_count']}, 失败={worker['failed_count']}")
        
        if self.start_time:
            elapsed = time.time() - self.start_time
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            print(f"\n运行时间: {hours:02d}:{minutes:02d}:{seconds:02d}")
        
        print(f"{'='*60}")
        
        self.logger.info(f"[流水线统计] 已完成={queue_stats['completed_count']}, "
                         f"失败={queue_stats['failed_count']}, "
                         f"待下载={queue_stats['pending_download']}, "
                         f"待分析={queue_stats['pending_analysis']}, "
                         f"满足={len(self._satisfied_source_videos) + self._base_satisfied_count}")
        self.logger.info(f"[线程池统计] 总线程={pool_stats['total_workers']}, "
                         f"下载线程={pool_stats['download_workers']}, "
                         f"分析线程={pool_stats['analyze_workers']}")
        
        return {
            'queue_stats': queue_stats,
            'pool_stats': pool_stats,
            'satisfied_count': len(self._satisfied_source_videos) + self._base_satisfied_count,
            'elapsed_time': time.time() - self.start_time if self.start_time else 0
        }

    def get_statistics(self) -> dict:
        """获取统计信息（不打印）"""
        queue_stats = self.task_queue.get_statistics()
        pool_stats = self.dynamic_pool.get_statistics()
        return {
            'queue_stats': queue_stats,
            'pool_stats': pool_stats,
            'satisfied_count': len(self._satisfied_source_videos) + self._base_satisfied_count,
            'completed': queue_stats.get('completed_count', 0),
            'failed': queue_stats.get('failed_count', 0),
            'pending_download': queue_stats.get('pending_download', 0),
            'pending_analysis': queue_stats.get('pending_analysis', 0),
            'elapsed_time': time.time() - self.start_time if self.start_time else 0,
        }


