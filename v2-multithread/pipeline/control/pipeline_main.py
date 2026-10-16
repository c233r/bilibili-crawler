"""
Pipeline主入口文件
整合动态线程池，实现完整的流水线功能
支持根据队列状态动态分配线程资源
"""
import os
import sys
import threading
import time
import json
from typing import Optional

# 添加爬虫模块路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bilibili爬虫', 'src'))

from model.bilibili_api import BilibiliAPI
from .task_queue import TaskQueue
from ..threads.dynamic_pool import DynamicThreadPool
from ..threads.monitor_thread import PipelineMonitor
from ..log.logger import get_main_logger, get_stats_logger
from ..api.video_pusher import VideoPusher, AsyncVideoPusher


class VideoPipeline:
    """视频下载与分析流水线"""
    
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
        self.dynamic_pool.set_callback(self.add_satisfied_video)
        
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
        
        # 统计信息
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        
        # 视频推送器（延迟初始化）
        self.video_pusher: Optional[VideoPusher] = None
        
        # 满足条件的视频列表（用于推送）
        self.satisfied_videos: list[str] = []
        
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
        remaining = self.task_queue.get_download_remaining()
        videos_to_add = videos[:remaining] if remaining > 0 else []
        
        if len(videos) > remaining > 0:
            self.logger.warning(f"队列剩余容量不足，仅添加前 {remaining} 个视频（共 {len(videos)} 个待添加）")
        
        added_count = 0
        added_video_names = []
        for video in videos_to_add:
            bvid = video.get('bvid', '')
            title = video.get('title', '未知')
            
            if bvid:
                success = self.dynamic_pool.add_download_task(bvid, title)
                if success:
                    added_count += 1
                    added_video_names.append(f"{title} (BV: {bvid})")
        
        skipped_videos = videos[remaining:] if remaining > 0 else videos
        
        if added_video_names:
            self.logger.debug(f"[下载队列] 已添加视频: {', '.join(added_video_names)}")
        
        if skipped_videos:
            skipped_video_names = []
            for video in skipped_videos:
                bvid = video.get('bvid', '')
                title = video.get('title', '未知')
                skipped_video_names.append(f"{title} (BV: {bvid})")
            self.logger.debug(f"[下载队列] 待添加视频: {', '.join(skipped_video_names)}")
        
        self.logger.info(f"已添加 {added_count} 个下载任务，剩余 {len(skipped_videos)} 个待添加")
        return added_count, skipped_videos
    
    def start(self):
        """启动流水线"""
        self.logger.info(f"启动流水线...")
        self.logger.info(f"总线程数: {self.dynamic_pool.total_workers}")
        
        # 启动动态线程池
        self.dynamic_pool.start()
        
        # 创建并启动监控线程（整合统计和停止控制）
        self.monitor_thread = PipelineMonitor(
            name="PipelineMonitor",
            interval=self.stats_interval,
            get_statistics_callback=self._output_statistics,
            check_stop_callback=self._check_stop_condition,
            stop_callback=self._graceful_shutdown
        )
        self.monitor_thread.start()
        self.logger.info("监控线程已启动")
        
        # 记录开始时间
        self.start_time = time.time()
        
        self.logger.info(f"流水线已启动")
    
    def stop(self):
        """停止流水线（快速停止）"""
        self.logger.info(f"停止流水线...")
        
        # 停止推送监控线程
        self.push_monitor_running = False
        if self.push_monitor_thread:
            self.push_monitor_thread.join(timeout=10)
        
        # 停止监控线程
        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.join(timeout=5)
        
        # 停止动态线程池
        self.dynamic_pool.stop()
        
        # 记录结束时间
        self.end_time = time.time()
        
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
                              f"满足={len(self.satisfied_videos)}")
            stats_logger.info(f"[线程池统计] 总线程={pool_stats['total_workers']}, "
                              f"下载线程={pool_stats['download_workers']}, "
                              f"分析线程={pool_stats['analyze_workers']}")
        except Exception as e:
            stats_logger = get_stats_logger()
            stats_logger.error(f"统计监控线程异常: {str(e)}")
    
    def _check_stop_condition(self) -> bool:
        """检查是否需要停止流水线（供监控线程调用）"""
        completed = self.task_queue.get_completed_count()
        satisfied = len(self.satisfied_videos)
        
        # 输出当前目标值和实际值，便于调试
        stats_logger = get_stats_logger()
        stats_logger.info(f"[停止条件检查] target_count={self.target_count}, "
                          f"target_satisfied={self.target_satisfied}, "
                          f"completed={completed}, "
                          f"satisfied={satisfied}")
        
        # 检查是否达到目标满足数量
        if self.target_satisfied > 0 and satisfied >= self.target_satisfied:
            self.logger.info(f"已达到目标满足数量 ({satisfied}/{self.target_satisfied} 个)")
            return True
        
        # 检查是否达到目标完成数量
        if self.target_count > 0 and completed >= self.target_count:
            self.logger.info(f"已达到目标完成数量 ({completed}/{self.target_count} 个)")
            return True
        
        # 如果没有设置目标数量，不自动停止（需要手动调用 stop()）
        return False
    
    def _graceful_shutdown(self):
        """
        优雅关闭流程：
        1. 设置停止事件，通知主线程退出
        2. 主线程负责清理工作
        """
        self.logger.info("开始优雅关闭流程...")
        
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
    
    def _push_monitor_loop(self):
        """
        推送监控线程循环
        
        负责从推送队列中获取视频路径并推送，与分析线程完全隔离
        """
        while self.push_monitor_running:
            try:
                # 等待队列中有视频（最多等待1秒）
                video_path = self._push_queue.get(timeout=1)
                
                self._process_push_task(video_path)
                
                # 标记任务完成
                self._push_queue.task_done()
            except Exception:
                # 队列空或其他异常，继续循环
                continue
        
        # 处理队列中剩余的视频
        while not self._push_queue.empty():
            try:
                video_path = self._push_queue.get_nowait()
                self._process_push_task(video_path)
                self._push_queue.task_done()
            except Exception:
                break
        
        self.logger.info("推送监控线程已停止")
    
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
        
        try:
            if isinstance(self.video_pusher, AsyncVideoPusher):
                # 异步推送器：在独立线程中执行，避免阻塞监控循环
                result = self.video_pusher.push_videos_sync([video_path], wait=False)
                if result and result[0].get('status') == 'success':
                    self.logger.info(f"[视频推送] 成功: {os.path.basename(video_path)}")
                    self._delete_video_file(video_path)
                else:
                    self.logger.warning(f"[视频推送] 失败: {os.path.basename(video_path)}")
            else:
                # 同步推送器：直接推送
                result = self.video_pusher.push_video(video_path, wait=False)
                if result.get('status') == 'success':
                    self.logger.info(f"[视频推送] 成功: {os.path.basename(video_path)}")
                    self._delete_video_file(video_path)
                else:
                    self.logger.warning(f"[视频推送] 失败: {os.path.basename(video_path)}")
        except Exception as e:
            self.logger.error(f"[视频推送] 异常: {os.path.basename(video_path)}, {str(e)}")
    
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
            return
        
        while not self._stop_event.is_set():
            # 打印统计信息
            self.print_statistics()
            
            # 等待（停止条件由监控线程检查）
            time.sleep(check_interval)
        
        # 收到停止事件，执行清理工作
        self._cleanup_after_shutdown()
        
        if self.start_time and not self.end_time:
            self.end_time = time.time()
    
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
        
        # 4. 停止推送监控线程（等待队列中所有视频推送完成）
        self.push_monitor_running = False
        if self.push_monitor_thread:
            self.push_monitor_thread.join(timeout=30)
            self.logger.info("推送监控线程已停止")
        
        # 5. 推送剩余未推送的视频（如果有）
        if self.satisfied_videos:
            existing_videos = [v for v in self.satisfied_videos if os.path.exists(v)]
            if existing_videos:
                self.logger.info(f"开始推送 {len(existing_videos)} 个剩余视频...")
                self.push_satisfied_videos(wait=False)
        
        # 6. 停止监控线程
        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.join(timeout=5)
            self.logger.info("监控线程已停止")
        
        # 7. 停止线程池
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
                         f"满足={len(self.satisfied_videos)}")
        self.logger.info(f"[线程池统计] 总线程={pool_stats['total_workers']}, "
                         f"下载线程={pool_stats['download_workers']}, "
                         f"分析线程={pool_stats['analyze_workers']}")
        
        return {
            'queue_stats': queue_stats,
            'pool_stats': pool_stats,
            'satisfied_count': len(self.satisfied_videos),
            'elapsed_time': time.time() - self.start_time if self.start_time else 0
        }
