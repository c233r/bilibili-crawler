"""
任务队列管理
实现生产者-消费者模式的消息队列
"""
import threading
import queue
from dataclasses import dataclass
from typing import Optional, Callable
from enum import Enum
import time


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"      # 待处理
    DOWNLOADING = "downloading"  # 下载中
    DOWNLOADED = "downloaded"    # 已下载
    ANALYZING = "analyzing"      # 分析中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"          # 失败


@dataclass
class DownloadTask:
    """下载任务"""
    bvid: str
    title: str
    page: int = 1  # 分集号（多P视频）
    status: TaskStatus = TaskStatus.PENDING
    video_path: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    
    def __lt__(self, other):
        """用于优先级队列排序"""
        return self.retry_count < other.retry_count
    
    @property
    def task_key(self) -> str:
        """去重用的唯一键（bvid + page）"""
        return f"{self.bvid}_p{self.page}"


class TaskQueue:
    """任务队列管理类"""
    
    def __init__(self, max_size: int = 100):
        """
        初始化任务队列
        
        Args:
            max_size: 队列最大容量
        """
        self.download_queue = queue.Queue(maxsize=max_size)
        self.video_queue = queue.Queue(maxsize=max_size)
        self.completed_tasks = []
        self.failed_tasks = []
        self.lock = threading.Lock()
        self.total_tasks = 0
        self.completed_count = 0
        self.failed_count = 0
        self.progress_callback: Optional[Callable] = None
        self.status_change_callback: Optional[Callable] = None
        self.pending_task_keys = set()  # 去重键（bvid_p{page}）
        self._draining = False  # 排空模式：禁止添加新下载任务
    
    def set_draining(self, draining: bool = True):
        """设置排空模式，禁止添加新下载任务"""
        self._draining = draining
    
    def set_progress_callback(self, callback: Callable):
        """设置进度回调函数"""
        self.progress_callback = callback
    
    def set_status_change_callback(self, callback: Callable):
        """设置状态变更回调函数（V3持久化）"""
        self.status_change_callback = callback
    
    def add_download_task(self, bvid: str, title: str, page: int = 1) -> bool:
        """
        添加下载任务到队列（带去重检查）
        
        Args:
            bvid: 视频BV号
            title: 视频标题
            page: 分集号（默认1，多P视频使用）
        
        Returns:
            是否添加成功
        """
        if self._draining:
            return False
        
        task_key = f"{bvid}_p{page}"
        
        with self.lock:
            if task_key in self.pending_task_keys:
                print(f"[队列] 任务已存在，跳过: {title} (BV: {bvid}, P{page})")
                return False
            
            task = DownloadTask(bvid=bvid, title=title, page=page)
            
            try:
                self.download_queue.put(task, block=False)
                self.pending_task_keys.add(task_key)
                self.total_tasks += 1
                return True
            except queue.Full:
                print(f"[队列] 下载队列已满，无法添加任务: {title}")
                return False
    
    def get_download_task(self, timeout: float = 1.0) -> Optional[DownloadTask]:
        """
        从下载队列获取任务
        
        Args:
            timeout: 超时时间（秒）
        
        Returns:
            下载任务或None
        """
        try:
            # queue.Queue 内部锁 任务分配 ✅ 关键
            task = self.download_queue.get(timeout=timeout)
            return task
        except queue.Empty:
            return None
    
    def add_video_task(self, task: DownloadTask, timeout: float = 30.0) -> bool:
        """
        添加已下载的视频到分析队列
        
        Args:
            task: 下载任务
            timeout: 等待超时时间（秒），默认30秒
        
        Returns:
            是否添加成功
        """
        try:
            self.video_queue.put(task, block=True, timeout=timeout)
            return True
        except queue.Full:
            print(f"[队列] 视频队列已满（等待{timeout}秒），无法添加任务: {task.title}")
            return False
    
    def get_video_task(self, timeout: float = 1.0) -> Optional[DownloadTask]:
        """
        从视频队列获取任务
        
        Args:
            timeout: 超时时间（秒）
        
        Returns:
            视频任务或None
        """
        try:
            # queue.Queue 内部锁 任务分配 ✅ 关键
            task = self.video_queue.get(timeout=timeout)
            return task
        except queue.Empty:
            return None
    
    def mark_task_downloaded(self, task: DownloadTask, video_path: str):
        """
        标记任务为已下载
        
        Args:
            task: 下载任务
            video_path: 视频文件路径
        """
        task.status = TaskStatus.DOWNLOADED
        task.video_path = video_path
        
        # V3 持久化 - 通知状态变更
        if self.status_change_callback:
            self.status_change_callback('downloaded', task, video_path=video_path)
        
        # 添加到视频队列（阻塞等待，最多30秒）
        if not self.add_video_task(task):
            # 队列满了超时，标记为失败以便重试
            error_msg = "视频队列已满，分析线程处理不过来"
            print(f"[队列] {error_msg}: {task.title}")
            with self.lock:
                self.failed_tasks.append(task)
                self.failed_count += 1
            task.status = TaskStatus.FAILED
            task.error_message = error_msg
            # 通知进度回调
            if self.progress_callback:
                self.progress_callback('failed', task)
            return
        
        # 通知进度回调
        if self.progress_callback:
            self.progress_callback('downloaded', task)
    
    def mark_task_failed(self, task: DownloadTask, error_message: str):
        """
        标记任务为失败
        
        Args:
            task: 下载任务
            error_message: 错误信息
        """
        task.status = TaskStatus.FAILED
        task.error_message = error_message
        
        # V3 持久化 - 通知状态变更
        if self.status_change_callback:
            self.status_change_callback('failed', task, error_message=error_message)
        
        with self.lock:
            self.failed_tasks.append(task)
            self.failed_count += 1
            self.pending_task_keys.discard(task.task_key)
        
        # 通知进度回调
        if self.progress_callback:
            self.progress_callback('failed', task)
    
    def mark_task_completed(self, task: DownloadTask):
        """
        标记任务为已完成
        
        Args:
            task: 下载任务
        """
        task.status = TaskStatus.COMPLETED
        
        # V3 持久化 - 通知状态变更
        if self.status_change_callback:
            self.status_change_callback('completed', task)
        
        with self.lock:
            self.completed_tasks.append(task)
            self.completed_count += 1
            self.pending_task_keys.discard(task.task_key)
        
        # 通知进度回调
        if self.progress_callback:
            self.progress_callback('completed', task)
    
    def retry_task(self, task: DownloadTask) -> bool:
        """
        重试失败的任务
        
        Args:
            task: 失败的任务
        
        Returns:
            是否可以重试
        """
        if task.retry_count < task.max_retries:
            task.retry_count += 1
            task.status = TaskStatus.PENDING
            task.error_message = None
            
            # 重新添加到下载队列
            try:
                self.download_queue.put(task, block=False)
                return True
            except queue.Full:
                print(f"[队列] 队列已满，无法重试任务: {task.title}")
                return False
        else:
            print(f"[队列] 任务已达到最大重试次数: {task.title}")
            return False
    
    def get_statistics(self) -> dict:
        """
        获取队列统计信息
        
        Returns:
            统计信息字典
        """
        with self.lock:
            return {
                'total_tasks': self.total_tasks,
                'completed_count': self.completed_count,
                'failed_count': self.failed_count,
                'pending_download': self.download_queue.qsize(),
                'pending_analysis': self.video_queue.qsize(),
                'success_rate': (self.completed_count / self.total_tasks * 100) if (self.total_tasks > 0 and self.completed_count is not None) else 0
            }
    
    def print_statistics(self):
        """打印队列统计信息"""
        stats = self.get_statistics()
        print(f"\n[队列统计]")
        print(f"  总任务数: {stats['total_tasks']}")
        print(f"  已完成: {stats['completed_count']}")
        print(f"  失败: {stats['failed_count']}")
        print(f"  待下载: {stats['pending_download']}")
        print(f"  待分析: {stats['pending_analysis']}")
        print(f"  成功率: {stats['success_rate']:.1f}%")
    
    def is_empty(self) -> bool:
        """检查队列是否为空"""
        return self.download_queue.empty() and self.video_queue.empty()
    
    def get_completed_count(self) -> int:
        """获取已完成任务数量"""
        with self.lock:
            return self.completed_count
    
    def get_download_remaining(self) -> int:
        """
        获取下载队列剩余容量
        
        Returns:
            剩余可添加的任务数量
        """
        return self.download_queue.maxsize - self.download_queue.qsize()
    
    def get_download_queue_size(self) -> int:
        """
        获取下载队列当前待处理任务数
        
        Returns:
            队列中待下载的任务数量
        """
        return self.download_queue.qsize()
    
    def get_video_queue_size(self) -> int:
        """
        获取视频队列当前待处理任务数
        
        Returns:
            队列中待分析的任务数量
        """
        return self.video_queue.qsize()
    
    def get_video_remaining(self) -> int:
        """
        获取视频队列剩余容量
        
        Returns:
            剩余可添加的任务数量
        """
        return self.video_queue.maxsize - self.video_queue.qsize()
    
    def wait_until_empty(self, check_interval: float = 1.0):
        """
        等待直到队列为空
        
        Args:
            check_interval: 检查间隔（秒）
        """
        while not self.is_empty():
            time.sleep(check_interval)
    
    def clear_download_queue(self) -> int:
        """
        仅清空下载队列（保留分析队列）
        
        Returns:
            int: 清空的任务数量
        """
        count = 0
        while not self.download_queue.empty():
            try:
                self.download_queue.get_nowait()
                count += 1
            except queue.Empty:
                break
        return count
    
    def clear(self):
        """清空队列"""
        while not self.download_queue.empty():
            try:
                self.download_queue.get_nowait()
            except queue.Empty:
                break
        
        while not self.video_queue.empty():
            try:
                self.video_queue.get_nowait()
            except queue.Empty:
                break
        
        with self.lock:
            self.completed_tasks.clear()
            self.failed_tasks.clear()
            self.pending_task_keys.clear()
            self.total_tasks = 0
            self.completed_count = 0
            self.failed_count = 0