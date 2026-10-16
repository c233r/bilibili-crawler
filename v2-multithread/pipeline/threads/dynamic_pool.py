"""
动态线程池管理器
支持根据队列状态动态分配线程资源
"""
import threading
import time
import os
import sys
import asyncio
from typing import Optional, Callable, List

# 添加爬虫模块路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'bilibili爬虫', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '大模型接入筛选'))

from downloaders.video_downloader import VideoDownloader
from ..control.task_queue import TaskQueue, DownloadTask, TaskStatus
from ..log.logger import get_download_logger, get_analyzer_logger, get_dynamic_logger


class DynamicWorker:
    """动态工作线程
    可以在下载和分析任务之间切换
    """
    
    def __init__(self, worker_id: int, task_queue: TaskQueue, 
                 downloader: VideoDownloader = None, filter_api = None,
                 filter_prompt: str = "", use_refined: bool = False,
                 on_satisfied_callback: Optional[Callable[[List[str]], None]] = None):
        """
        初始化动态工作线程
        
        Args:
            worker_id: 工作线程ID
            task_queue: 任务队列
            downloader: 视频下载器实例
            filter_api: 筛选API实例
            filter_prompt: 筛选提示词
            use_refined: 是否使用精细化分析
            on_satisfied_callback: 满足条件视频的回调函数（接收视频路径列表）
        """
        self.worker_id = worker_id
        self.task_queue = task_queue
        self.downloader = downloader
        self.filter_api = filter_api
        self.filter_prompt = filter_prompt
        self.use_refined = use_refined
        self.on_satisfied_callback = on_satisfied_callback
        
        self.is_running = False
        self.is_blocked = False
        self.current_role = 'idle'  # 'download', 'analyze', 'idle'
        self.target_role = 'idle'   # 目标角色，用于延迟切换
        self.is_processing = False  # 是否正在处理任务
        self.thread: Optional[threading.Thread] = None
        
        # 统计信息
        self.downloaded_count = 0
        self.analyzed_count = 0
        self.satisfied_count = 0
        self.failed_count = 0
        
        # 日志器
        self.logger = get_dynamic_logger(worker_id)
    
    def start(self):
        """启动工作线程"""
        self.is_running = True
        self.is_blocked = False
        self.thread = threading.Thread(target=self._run, name=f"DynamicWorker-{self.worker_id}")
        self.thread.daemon = True
        self.thread.start()
        self.logger.info(f"动态线程-{self.worker_id} 已启动")
    
    def stop(self):
        """停止工作线程"""
        self.is_running = False
        self.logger.info(f"动态线程-{self.worker_id} 已收到停止信号")
    
    def block(self):
        """阻塞线程（暂停执行任务）"""
        self.is_blocked = True
        self.logger.info(f"动态线程-{self.worker_id} 已被阻塞")
    
    def unblock(self):
        """解除阻塞"""
        self.is_blocked = False
        self.logger.info(f"动态线程-{self.worker_id} 已解除阻塞")
    
    def set_role(self, role: str):
        """
        设置线程目标角色（延迟切换，当前任务完成后生效）
        
        Args:
            role: 'download', 'analyze', 或 'idle'
        """
        if self.current_role != role:
            self.target_role = role
            self.logger.info(f"动态线程-{self.worker_id} 收到角色切换指令: {self.current_role} -> {role}")
    
    def _apply_role_switch(self):
        """应用角色切换（仅在任务完成时调用）"""
        if self.target_role != self.current_role:
            self.current_role = self.target_role
            self.target_role = self.current_role
            self.logger.info(f"动态线程-{self.worker_id} 角色切换完成: {self.current_role}")

    def _run_async(self, coro, timeout, description=""):
        """
        使用线程持久化的事件循环运行异步协程
        
        避免 asyncio.run() 每次创建/销毁事件循环的开销，
        防止事件循环关闭时因取消挂起任务导致的长时间阻塞
        
        Args:
            coro: 异步协程
            timeout: 超时秒数
            description: 描述信息（用于日志）
        """
        # 首次调用或事件循环已关闭时创建新的事件循环
        if not hasattr(self, '_async_loop') or self._async_loop.is_closed():
            self._async_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._async_loop)
        
        try:
            return self._async_loop.run_until_complete(
                asyncio.wait_for(coro, timeout=timeout)
            )
        except asyncio.TimeoutError:
            self.logger.warning(f"[AsyncRunner] {description}超时({timeout}秒)")
            raise
    
    def _run(self):
        """工作线程主循环"""
        from ..log.logger import ThreadLogger
        ThreadLogger.set_current_logger(self.logger)
        
        empty_loops = 0  # 连续无任务循环计数
        
        while self.is_running:
            # 检查是否被阻塞
            while self.is_blocked:
                time.sleep(0.5)
                if not self.is_running:
                    return
            
            # 每次循环都检查角色切换（不依赖任务完成）
            if self.target_role != self.current_role:
                self._apply_role_switch()
            
            if self.current_role == 'idle':
                continue
            
            # 根据角色执行任务
            if self.current_role == 'download' and self.downloader:
                processed = self._do_download()
                if processed:
                    empty_loops = 0
                else:
                    empty_loops += 1
            elif self.current_role == 'analyze' and self.filter_api:
                processed = self._do_analyze()
                if processed:
                    empty_loops = 0
                else:
                    empty_loops += 1
            else:
                empty_loops += 1
            
            # 空闲时输出DEBUG信息（每5秒一次）
            if empty_loops > 0 and empty_loops % 10 == 0:
                download_q = self.task_queue.get_download_queue_size()
                video_q = self.task_queue.get_video_queue_size()
                self.logger.debug(f"[空闲检测] role={self.current_role}, target={self.target_role}, "
                                  f"download_q={download_q}, video_q={video_q}, empty_loops={empty_loops}")
            
            if empty_loops > 0:
                time.sleep(0.5)
    
    def _do_download(self) -> bool:
        """
        执行下载任务
        
        Returns:
            True: 实际处理了任务, False: 无任务可处理
        """
        if not self.is_running or self.is_blocked:
            return False
        
        task = self.task_queue.get_download_task(timeout=1.0)
        
        if task is None:
            return False
        
        self.is_processing = True
        task.status = TaskStatus.DOWNLOADING
        self.logger.info(f"开始下载: {task.title} (BV: {task.bvid})")
        
        if self.downloader and hasattr(self.downloader, 'logger'):
            self.downloader.logger = self.logger
        
        try:
            success, msg = self.downloader.download(task.bvid, task.title)
            
            if success:
                video_path = self._find_video_file(task.title)
                if video_path:
                    self.logger.info(f"下载成功: {task.title}")
                    self.downloaded_count += 1
                    self.task_queue.mark_task_downloaded(task, video_path)
                else:
                    error_msg = f"未找到下载的视频文件: {task.title}"
                    self.logger.warning(error_msg)
                    self.failed_count += 1
                    self.task_queue.mark_task_failed(task, error_msg)
            else:
                error_msg = f"下载失败: {msg}"
                self.logger.error(error_msg)
                self.failed_count += 1
                self.task_queue.mark_task_failed(task, error_msg)
                
                # 清理下载失败时可能残留的文件
                self._cleanup_downloaded_files(task.title)
                
        except Exception as e:
            error_msg = f"下载异常: {str(e)}"
            self.logger.exception(error_msg)
            self.failed_count += 1
            self.task_queue.mark_task_failed(task, error_msg)
        finally:
            self.is_processing = False
            return True  # 实际处理了任务（无论成功失败）
    
    def _do_analyze(self) -> bool:
        """
        执行分析任务
        
        Returns:
            True: 实际处理了任务, False: 无任务可处理
        """
        if not self.is_running or self.is_blocked:
            return False
        
        task = self.task_queue.get_video_task(timeout=1.0)
        
        if task is None:
            return False
        
        self.is_processing = True
        task.status = TaskStatus.ANALYZING
        self.logger.info(f"开始分析: {task.title}")
        
        try:
            if self.filter_api and hasattr(self.filter_api, 'set_logger'):
                self.filter_api.set_logger(self.logger)
            
            if not self.is_running:
                self.logger.info(f"分析已取消（线程正在停止）: {task.title}")
                self.task_queue.mark_task_failed(task, "分析已取消（线程正在停止）")
                return True  # 实际领取了任务，计入处理
            
            if self.use_refined:
                result = self._analyze_refined(task)
            else:
                result = self._analyze_basic(task)
            
            self.analyzed_count += 1
            
            if result.get('satisfied', False):
                self.satisfied_count += 1
                task.status = TaskStatus.COMPLETED
                
                if self.on_satisfied_callback:
                    # 收集所有需要上传的视频路径
                    videos_to_upload = []
                    if self.use_refined and result.get('output_paths'):
                        # 精细化分析：传递所有片段
                        videos_to_upload = result['output_paths']
                    elif task.video_path:
                        # 基础分析：传递原始视频
                        videos_to_upload = [task.video_path]
                    
                    if videos_to_upload:
                        self.on_satisfied_callback(videos_to_upload)
                
                self.task_queue.mark_task_completed(task)
            else:
                task.status = TaskStatus.FAILED
                self.task_queue.mark_task_failed(task, "视频不满足条件")
                
        except Exception as e:
            error_msg = f"分析异常: {str(e)}"
            self.logger.exception(error_msg)
            self.failed_count += 1
            self.task_queue.mark_task_failed(task, error_msg)
        finally:
            # 删除原始视频（多路径尝试）
            deleted = False
            if task.video_path:
                paths_to_try = [task.video_path]
                # 如果主路径不存在，尝试搜索下载目录
                if not os.path.exists(task.video_path):
                    self.logger.debug(f"[视频清理] task.video_path 不存在: {task.video_path}")
                    alt_path = self._find_video_file(task.title)
                    if alt_path:
                        self.logger.debug(f"[视频清理] 备用路径: {alt_path}")
                        paths_to_try.append(alt_path)
                
                for p in paths_to_try:
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                            self.logger.info(f"[视频清理] 分析完成，删除原始视频: {p}")
                            deleted = True
                            break
                        except Exception as e:
                            self.logger.warning(f"[视频清理] 删除原始视频失败: {p}, {str(e)}")
            else:
                self.logger.debug(f"[视频清理] task.video_path 为空")
            
            if not deleted and task.video_path:
                self.logger.debug(f"[视频清理] 未找到可删除的视频文件: {task.title}")
            self.is_processing = False
            return True  # 实际处理了任务
    
    def _analyze_basic(self, task: DownloadTask) -> dict:
        """基础分析（使用异步并发）"""
        if not task.video_path:
            return {'satisfied': False, 'reason': '视频路径为空'}
        
        if not self.filter_api:
            self.logger.error("筛选API未初始化，无法进行基础分析")
            return {'satisfied': False, 'reason': '筛选API未初始化'}
        
        self.logger.info(f"[FilterAPI] 分析视频: {task.title}")
        
        # 给基础分析加总超时
        BASIC_TIMEOUT = 60  # 基础分析最多等60秒，超时则丢弃任务
        
        try:
            filter_result = self._run_async(
                self.filter_api.analyze_video_async(task.video_path, self.filter_prompt),
                timeout=BASIC_TIMEOUT,
                description="基础分析"
            )
        except asyncio.TimeoutError:
            self.logger.warning(f"[FilterAPI] 基础分析总超时({BASIC_TIMEOUT}秒)，强制结束")
            return {'satisfied': False, 'reason': f'基础分析超时({BASIC_TIMEOUT}秒)', 'is_timeout': True}
        except Exception as e:
            self.logger.error(f"异步分析失败: {str(e)}")
            return {'satisfied': False, 'reason': f"异步分析失败: {str(e)}"}
        
        duration_ms = filter_result.get('duration_ms', 0)
        api_duration_ms = filter_result.get('api_duration_ms', 0)
        frame_count = filter_result.get('frame_count', 0)
        
        self.logger.info(f"[AsyncVLM] 分析完成: {task.title}, "
                         f"总耗时: {duration_ms:.2f}ms, "
                         f"API耗时: {api_duration_ms:.2f}ms, "
                         f"帧数量: {frame_count}, "
                         f"满足: {filter_result.get('is_satisfied', False)}")
        
        if not filter_result.get('success', False):
            return {'satisfied': False, 'reason': filter_result.get('message', 'API返回为空')}
        
        return {
            'satisfied': filter_result.get('is_satisfied', False),
            'reason': filter_result.get('message', ''),
            'confidence': filter_result.get('satisfied_ratio', 0)
        }
    
    def _analyze_refined(self, task: DownloadTask) -> dict:
        """精细化分析（使用异步并发）"""
        if not task.video_path:
            return {'satisfied': False, 'reason': '视频路径为空'}
        
        if not self.filter_api:
            self.logger.error("筛选API未初始化，无法进行精细化分析")
            return {'satisfied': False, 'reason': '筛选API未初始化'}
        
        self.logger.info(f"[RefinedAnalyzer] 开始精细化分析: {task.title}")
        
        # 给精细化分析加总超时，避免递归嵌套的gather导致长时间卡死
        REFINED_TIMEOUT = 120  # 精细化分析最多等120秒，超时则丢弃任务
        
        try:
            filter_result = self._run_async(
                self.filter_api.analyze_video_refined_async(task.video_path, self.filter_prompt),
                timeout=REFINED_TIMEOUT,
                description="精细化分析"
            )
        except asyncio.TimeoutError:
            self.logger.warning(f"[RefinedAnalyzer] 精细化分析总超时({REFINED_TIMEOUT}秒)，强制结束")
            return {'satisfied': False, 'reason': f'精细化分析超时({REFINED_TIMEOUT}秒)', 'is_timeout': True}
        except Exception as e:
            self.logger.error(f"[RefinedAnalyzer] 精细化分析异常: {str(e)}")
            return {'satisfied': False, 'reason': f'精细化分析异常: {str(e)}'}
        
        self.logger.info(f"[RefinedAnalyzer] 精细化分析返回结果: {task.title}")
        
        duration_ms = filter_result.get('duration_ms', 0)
        iterations = filter_result.get('iterations', 1)
        analysis_level = filter_result.get('analysis_level', 'refined')
        output_paths = filter_result.get('output_paths', [])
        
        self.logger.info(f"[AsyncRefined] 精细化分析完成: {task.title}, "
                         f"总耗时: {duration_ms:.2f}ms, "
                         f"迭代次数: {iterations}, "
                         f"分析级别: {analysis_level}, "
                         f"满足: {filter_result.get('is_satisfied', False)}")
        
        # 如果视频满足条件且已保存片段，删除原始视频
        if filter_result.get('is_satisfied', False) and output_paths:
            self.logger.info(f"[视频清理] 删除原始视频: {task.video_path}")
            try:
                if os.path.exists(task.video_path):
                    os.remove(task.video_path)
                    self.logger.info(f"[视频清理] 原始视频已删除，保留 {len(output_paths)} 个片段")
            except Exception as e:
                self.logger.warning(f"[视频清理] 删除原始视频失败: {str(e)}")
        
        if not filter_result.get('success', False):
            return {'satisfied': False, 'reason': filter_result.get('message', '分析失败')}
        
        return {
            'satisfied': filter_result.get('is_satisfied', False),
            'reason': filter_result.get('message', ''),
            'confidence': filter_result.get('satisfied_ratio', 0),
            'total_frames': filter_result.get('total_frames', 0),
            'satisfied_frames': filter_result.get('satisfied_frames', 0),
            'output_paths': output_paths
        }
    
    def _find_video_file(self, title: str) -> Optional[str]:
        """查找下载的视频文件"""
        import re
        
        download_path = self.downloader.download_path
        
        if not download_path or not os.path.exists(download_path):
            return None
        
        title_clean = re.sub(r'[\\/:*?"<>|]', '_', title).strip()
        
        for ext in ['.mp4', '.flv', '.webm', '.mkv']:
            video_path = os.path.join(download_path, title_clean + ext)
            if os.path.exists(video_path):
                return video_path
        
        return None
    
    def _cleanup_downloaded_files(self, title: str):
        """清理下载失败时可能残留的文件"""
        import re
        
        download_path = self.downloader.download_path
        
        if not download_path or not os.path.exists(download_path):
            return
        
        title_clean = re.sub(r'[\\/:*?"<>|]', '_', title).strip()
        
        deleted_count = 0
        for root, dirs, files in os.walk(download_path):
            for file in files:
                if title_clean in file:
                    file_path = os.path.join(root, file)
                    try:
                        os.remove(file_path)
                        self.logger.info(f"[清理] 删除下载失败残留文件: {file}")
                        deleted_count += 1
                    except Exception as e:
                        self.logger.warning(f"[清理] 删除文件失败: {file}, {str(e)}")
        
        if deleted_count > 0:
            self.logger.info(f"[清理] 共删除 {deleted_count} 个下载失败残留文件")
    
    def get_statistics(self) -> dict:
        """获取工作线程统计信息"""
        return {
            'worker_id': self.worker_id,
            'role': self.current_role,
            'downloaded_count': self.downloaded_count,
            'analyzed_count': self.analyzed_count,
            'satisfied_count': self.satisfied_count,
            'failed_count': self.failed_count,
            'is_running': self.is_running,
            'is_blocked': self.is_blocked
        }


class DynamicThreadPool:
    """动态线程池管理器"""
    
    def __init__(self, total_workers: int = 5, task_queue: Optional[TaskQueue] = None):
        """
        初始化动态线程池
        
        Args:
            total_workers: 总线程数量
            task_queue: 任务队列
        """
        self.total_workers = total_workers
        self.task_queue = task_queue or TaskQueue()
        self.workers: List[DynamicWorker] = []
        self.is_running = False
        self.lock = threading.Lock()
        
        # 配置
        self.downloader = VideoDownloader()
        self.filter_api = None
        self.filter_prompt = ""
        self.use_refined = False
        self.on_satisfied_callback: Optional[Callable[[List[str]], None]] = None
        
        # 动态分配参数
        self.min_download_workers = 1
        self.min_analyze_workers = 1
        self.balance_interval = 10.0  # 平衡间隔（秒）
        
        # 状态监控线程
        self.monitor_thread: Optional[threading.Thread] = None
        
        # 初始化时就配置下载器（从配置文件加载）
        self._configure_downloader()
    
    def _configure_downloader(self):
        """配置下载器"""
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        config_file = os.path.join(project_root, 'bilibili爬虫', 'config.json')
        
        if os.path.exists(config_file):
            import json
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                    download_path = config.get('download_path', '')
                    if download_path:
                        self.downloader.download_path = os.path.join(download_path, 'videos')
                    
                    cookies_path = config.get('cookies_path', '')
                    if cookies_path and os.path.exists(cookies_path):
                        self.downloader.cookies_path = cookies_path
                    
                    self.downloader.use_ytdlp = config.get('use_ytdlp', True)
                    
            except Exception as e:
                print(f"[动态线程池] 加载配置文件失败: {e}")
    
    def set_downloader(self, downloader: VideoDownloader):
        """设置下载器"""
        self.downloader = downloader
    
    def set_filter_api(self, filter_api, filter_prompt: str = "", use_refined: bool = False):
        """设置筛选API"""
        self.filter_api = filter_api
        self.filter_prompt = filter_prompt
        self.use_refined = use_refined
    
    def set_callback(self, callback: Callable[[str], None]):
        """设置回调函数"""
        self.on_satisfied_callback = callback
    
    def set_download_path(self, path: str):
        """设置下载路径"""
        if self.downloader:
            self.downloader.download_path = os.path.join(path, 'videos')
    
    def start(self):
        """启动线程池"""
        with self.lock:
            if self.is_running:
                print("[动态线程池] 线程池已在运行")
                return
            
            self.is_running = True
            
            # 创建工作线程
            for i in range(self.total_workers):
                worker = DynamicWorker(
                    worker_id=i + 1,
                    task_queue=self.task_queue,
                    downloader=self.downloader,
                    filter_api=self.filter_api,
                    filter_prompt=self.filter_prompt,
                    use_refined=self.use_refined,
                    on_satisfied_callback=self.on_satisfied_callback
                )
                worker.start()
                self.workers.append(worker)
            
            # 默认分配：前2个下载，后3个分析
            for i, worker in enumerate(self.workers):
                if i < len(self.workers) / 2:
                    worker.set_role('download')
                else:
                    worker.set_role('analyze')
            
            # 启动状态监控线程
            self.monitor_thread = threading.Thread(target=self._monitor_loop, name="PoolMonitor")
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            
            print(f"[动态线程池] 已启动 {self.total_workers} 个动态线程")
    
    def stop(self):
        """停止线程池"""
        with self.lock:
            if not self.is_running:
                print("[动态线程池] 线程池未运行")
                return
            
            self.is_running = False
            
            # 停止所有工作线程
            for worker in self.workers:
                worker.stop()
            
            self.workers.clear()
            print(f"[动态线程池] 已停止所有线程")
    
    def block_all(self):
        """阻塞所有线程"""
        with self.lock:
            for worker in self.workers:
                worker.block()
            print(f"[动态线程池] 已阻塞所有线程")
    
    def unblock_all(self):
        """解除所有线程阻塞"""
        with self.lock:
            for worker in self.workers:
                worker.unblock()
            print(f"[动态线程池] 已解除所有线程阻塞")
    
    def add_download_task(self, bvid: str, title: str) -> bool:
        """添加下载任务"""
        return self.task_queue.add_download_task(bvid, title)
    
    def clear_queues(self):
        """清空所有队列"""
        self.task_queue.clear()
        print("[动态线程池] 已清空所有任务队列")
    
    def _monitor_loop(self):
        """状态监控循环"""
        while self.is_running:
            try:
                self._balance_workers()
            except Exception as e:
                print(f"[动态线程池] 监控线程异常: {e}")
            
            time.sleep(self.balance_interval)
    
    def _balance_workers(self):
        """
        动态平衡线程分配
        
        根据队列状态动态调整线程角色：
        - 如果下载队列为空且有多余下载线程，转为分析线程
        - 如果分析队列为空且有多余分析线程，转为下载线程
        - 如果分析队列有积压且下载队列空闲，切换下载线程到分析
        - 保证最小线程数
        """
        # 获取队列当前大小
        download_queue_size = self.task_queue.download_queue.qsize()
        analyze_queue_size = self.task_queue.video_queue.qsize()
        
        # 获取当前角色分配
        download_workers = sum(1 for w in self.workers if w.current_role == 'download')
        analyze_workers = sum(1 for w in self.workers if w.current_role == 'analyze')
        
        # 策略1: 如果下载队列为空，且有多余下载线程，转为分析线程
        if download_queue_size == 0 and download_workers > self.min_download_workers:
            for worker in self.workers:
                if worker.current_role == 'download' and worker.current_role == worker.target_role:
                    worker.set_role('analyze')
                    download_workers -= 1
                    analyze_workers += 1
                    return
        
        # 策略2: 如果分析队列为空，且有多余分析线程，转为下载线程
        if analyze_queue_size == 0 and analyze_workers > self.min_analyze_workers:
            for worker in self.workers:
                if worker.current_role == 'analyze' and worker.current_role == worker.target_role:
                    worker.set_role('download')
                    analyze_workers -= 1
                    download_workers += 1
                    
                    return
        
        # 策略3: 如果分析队列积压严重（任务数 >= 线程数）且下载队列为空，切换更多下载线程到分析
        if analyze_queue_size >= analyze_workers and download_workers > self.min_download_workers:
            for worker in self.workers:
                if worker.current_role == 'download' and worker.current_role == worker.target_role:
                    worker.set_role('analyze')
                    download_workers -= 1
                    analyze_workers += 1
                    
                    return
    
    def get_statistics(self) -> dict:
        """获取线程池统计信息"""
        download_workers = sum(1 for w in self.workers if w.current_role == 'download')
        analyze_workers = sum(1 for w in self.workers if w.current_role == 'analyze')
        
        return {
            'total_workers': self.total_workers,
            'download_workers': download_workers,
            'analyze_workers': analyze_workers,
            'download_queue_size': self.task_queue.download_queue.qsize(),
            'analyze_queue_size': self.task_queue.video_queue.qsize(),
            'worker_stats': [w.get_statistics() for w in self.workers]
        }
