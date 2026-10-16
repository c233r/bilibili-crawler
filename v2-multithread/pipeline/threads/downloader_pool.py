"""
下载线程池
实现多线程并行下载功能
"""
import threading
import time
import os
import sys
from typing import Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

# 添加爬虫模块路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'bilibili爬虫', 'src'))

from downloaders.video_downloader import VideoDownloader
from ..control.task_queue import TaskQueue, DownloadTask, TaskStatus
from ..log.logger import get_download_logger


class DownloadWorker:
    """下载工作线程"""
    
    def __init__(self, worker_id: int, downloader: VideoDownloader, task_queue: TaskQueue):
        """
        初始化下载工作线程
        
        Args:
            worker_id: 工作线程ID
            downloader: 视频下载器实例
            task_queue: 任务队列
        """
        self.worker_id = worker_id
        self.downloader = downloader
        self.task_queue = task_queue
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.downloaded_count = 0
        self.failed_count = 0
        self.logger = get_download_logger(worker_id)
    
    def start(self):
        """启动工作线程"""
        self.is_running = True
        self.thread = threading.Thread(target=self._run, name=f"DownloadWorker-{self.worker_id}")
        self.thread.daemon = True
        self.thread.start()
        self.logger.info(f"下载线程-{self.worker_id} 已启动")
    
    def stop(self):
        """停止工作线程"""
        self.is_running = False
        # 守护线程会在主线程退出时自动终止，不需要等待
        # 这里不调用 join()，让线程在主线程退出时立即终止
        self.logger.info(f"下载线程-{self.worker_id} 已停止")
    
    def _run(self):
        """工作线程主循环"""
        # 设置当前线程的上下文日志器
        from ..log.logger import ThreadLogger
        ThreadLogger.set_current_logger(self.logger)
        
        while self.is_running:
            # 从队列获取任务
            task = self.task_queue.get_download_task(timeout=1.0)
            
            if task is None:
                # 队列为空，继续等待
                continue
            
            # 执行下载任务
            self._download_task(task)
    
    def _download_task(self, task: DownloadTask):
        """
        执行下载任务
        
        Args:
            task: 下载任务
        """
        task.status = TaskStatus.DOWNLOADING
        self.logger.info(f"开始下载: {task.title} (BV: {task.bvid})")
        
        try:
            # 执行下载
            success, msg = self.downloader.download(task.bvid, task.title)
            
            if success:
                # 查找下载的视频文件
                video_path = self._find_video_file(task.title)
                
                if video_path:
                    self.logger.info(f"下载成功: {task.title}")
                    self.downloaded_count += 1
                    
                    # 标记任务为已下载
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
                
        except Exception as e:
            error_msg = f"下载异常: {str(e)}"
            self.logger.exception(error_msg)
            self.failed_count += 1
            self.task_queue.mark_task_failed(task, error_msg)
    
    def _find_video_file(self, title: str) -> Optional[str]:
        """
        查找下载的视频文件
        
        Args:
            title: 视频标题
        
        Returns:
            视频文件路径或None
        """
        import re
        
        download_path = self.downloader.download_path
        
        if not download_path or not os.path.exists(download_path):
            return None
        
        # 清理标题中的非法字符
        title_clean = re.sub(r'[\\/:*?"<>|]', '_', title).strip()
        
        # 查找下载的视频文件
        for ext in ['.mp4', '.flv', '.webm', '.mkv']:
            video_path = os.path.join(download_path, title_clean + ext)
            if os.path.exists(video_path):
                return video_path
            
            # 尝试带序号的文件名
            for i in range(1, 10):
                video_path = os.path.join(download_path, f"{title_clean}_{i}{ext}")
                if os.path.exists(video_path):
                    return video_path
        
        # 如果找不到精确匹配，尝试模糊匹配
        for filename in os.listdir(download_path):
            if title_clean[:10] in filename and filename.endswith(('.mp4', '.flv', '.webm', '.mkv')):
                return os.path.join(download_path, filename)
        
        return None
    
    def get_statistics(self) -> dict:
        """
        获取工作线程统计信息
        
        Returns:
            统计信息字典
        """
        return {
            'worker_id': self.worker_id,
            'downloaded_count': self.downloaded_count,
            'failed_count': self.failed_count,
            'is_running': self.is_running
        }


class DownloadPool:
    """下载线程池"""
    
    def __init__(self, num_workers: int = 2, task_queue: Optional[TaskQueue] = None):
        """
        初始化下载线程池
        
        Args:
            num_workers: 工作线程数量
            task_queue: 任务队列（可选，如未提供则创建新队列）
        """
        self.num_workers = num_workers
        self.task_queue = task_queue or TaskQueue()
        self.workers: list[DownloadWorker] = []
        self.is_running = False
        self.lock = threading.Lock()  # 用于保护任务队列访问，是不可重入锁，不可同时读写
        
        # 创建下载器实例
        self.downloader = VideoDownloader()
        
        # 配置下载器
        self._configure_downloader()
    
    def _configure_downloader(self):
        """配置下载器"""
        # 从配置文件加载设置
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        config_file = os.path.join(project_root, 'bilibili爬虫', 'config.json')
        
        if os.path.exists(config_file):
            import json
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                    # 设置下载路径
                    download_path = config.get('download_path', '')
                    if download_path:
                        self.downloader.download_path = os.path.join(download_path, 'videos')
                    
                    # 设置Cookie路径
                    cookies_path = config.get('cookies_path', '')
                    if cookies_path and os.path.exists(cookies_path):
                        self.downloader.cookies_path = cookies_path
                    
                    # 设置是否使用yt-dlp
                    self.downloader.use_ytdlp = config.get('use_ytdlp', True)
                    
            except Exception as e:
                print(f"[下载池] 加载配置文件失败: {e}")
    
    def set_download_path(self, path: str):
        """
        设置下载路径
        
        Args:
            path: 下载路径
        """
        self.downloader.download_path = os.path.join(path, 'videos')
    
    def set_cookies_path(self, path: str):
        """
        设置Cookie文件路径
        
        Args:
            path: Cookie文件路径
        """
        if os.path.exists(path):
            self.downloader.cookies_path = path
    
    def set_use_ytdlp(self, use_ytdlp: bool):
        """
        设置是否使用yt-dlp
        
        Args:
            use_ytdlp: 是否使用yt-dlp
        """
        self.downloader.use_ytdlp = use_ytdlp
    
    def start(self):
        """启动线程池"""
        # DownloadPool.lock 线程池状态 ❌ 不相关
        # 由于DownloadWorker一般只有一个进程进行操作，那就不需要加锁，这里是为了安全考虑
        with self.lock:
            if self.is_running:
                print("[下载池] 线程池已在运行")
                return
            
            self.is_running = True
            
            # 创建并启动工作线程
            for i in range(self.num_workers):
                worker = DownloadWorker(i + 1, self.downloader, self.task_queue)
                worker.start()
                self.workers.append(worker)
            
            print(f"[下载池] 已启动 {self.num_workers} 个下载线程")
    
    def stop(self):
        """停止线程池"""
        with self.lock:
            if not self.is_running:
                print("[下载池] 线程池未运行")
                return
            
            self.is_running = False
            
            # 停止所有工作线程
            for worker in self.workers:
                worker.stop()
            
            self.workers.clear()
            print(f"[下载池] 已停止所有下载线程")
    
    def add_task(self, bvid: str, title: str) -> bool:
        """
        添加下载任务
        
        Args:
            bvid: 视频BV号
            title: 视频标题
        
        Returns:
            是否添加成功
        """
        return self.task_queue.add_download_task(bvid, title)
    
    def wait_until_empty(self, check_interval: float = 1.0):
        """
        等待直到队列为空
        
        Args:
            check_interval: 检查间隔（秒）
        """
        self.task_queue.wait_until_empty(check_interval)
    
    def get_statistics(self) -> dict:
        """
        获取线程池统计信息
        
        Returns:
            统计信息字典
        """
        workers_stats = [worker.get_statistics() for worker in self.workers]
        total_downloaded = sum(w['downloaded_count'] for w in workers_stats)
        total_failed = sum(w['failed_count'] for w in workers_stats)
        
        return {
            'num_workers': self.num_workers,
            'is_running': self.is_running,
            'total_downloaded': total_downloaded,
            'total_failed': total_failed,
            'workers': workers_stats
        }
    
    def print_statistics(self):
        """打印线程池统计信息"""
        stats = self.get_statistics()
        print(f"\n[下载池统计]")
        print(f"  线程数: {stats['num_workers']}")
        print(f"  运行状态: {'运行中' if stats['is_running'] else '已停止'}")
        print(f"  总下载: {stats['total_downloaded']}")
        print(f"  总失败: {stats['total_failed']}")
        print(f"  各线程详情:")
        for worker_stat in stats['workers']:
            print(f"    线程-{worker_stat['worker_id']}: 下载 {worker_stat['downloaded_count']}, 失败 {worker_stat['failed_count']}")
    
    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.stop()