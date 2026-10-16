"""
分析线程池
实现多线程并行视频分析功能
"""
import threading
import time
import os
import sys
from typing import Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

# 添加大模型筛选模块路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '大模型接入筛选'))

from ..control.task_queue import TaskQueue, DownloadTask, TaskStatus
from ..log.logger import get_analyzer_logger


class AnalyzerWorker:
    """分析工作线程"""
    
    def __init__(self, worker_id: int, filter_api, task_queue: TaskQueue, 
                 filter_prompt: str = "", use_refined: bool = False,
                 on_satisfied_callback: Optional[Callable[[str], None]] = None):
        """
        初始化分析工作线程
        
        Args:
            worker_id: 工作线程ID
            filter_api: 筛选API实例
            task_queue: 任务队列
            filter_prompt: 筛选提示词
            use_refined: 是否使用精细化分析
            on_satisfied_callback: 满足条件视频的回调函数
        """
        self.worker_id = worker_id
        self.filter_api = filter_api
        self.task_queue = task_queue
        self.filter_prompt = filter_prompt
        self.use_refined = use_refined
        self.on_satisfied_callback = on_satisfied_callback
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.analyzed_count = 0
        self.satisfied_count = 0
        self.failed_count = 0
        self.logger = get_analyzer_logger(worker_id)
    
    def start(self):
        """启动工作线程"""
        self.is_running = True
        self.thread = threading.Thread(target=self._run, name=f"AnalyzerWorker-{self.worker_id}")
        self.thread.daemon = True
        self.thread.start()
        self.logger.info(f"分析线程-{self.worker_id} 已启动")
    
    def stop(self):
        """停止工作线程
        
        设置 is_running 为 False，线程会在以下时机停止：
        1. 当前分析任务完成后，在主循环检查 is_running 时退出
        2. 如果主线程退出，由于线程是守护线程(daemon=True)，会被立即强制终止
        
        如果需要强制立即停止，主线程可以直接退出，守护线程会自动终止。
        """
        self.is_running = False
        self.logger.info(f"分析线程-{self.worker_id} 已收到停止信号")
    
    def _run(self):
        """工作线程主循环"""
        # 设置当前线程的上下文日志器
        from ..log.logger import ThreadLogger
        ThreadLogger.set_current_logger(self.logger)
        
        while self.is_running:
            # 从队列获取任务
            task = self.task_queue.get_video_task(timeout=1.0)
            
            if task is None:
                # 队列为空，继续等待
                continue
            
            # 执行分析任务
            self._analyze_task(task)
    
    def _analyze_task(self, task: DownloadTask):
        """
        执行分析任务
        
        Args:
            task: 下载任务
        """
        task.status = TaskStatus.ANALYZING
        self.logger.info(f"开始分析: {task.title}")
        
        try:
            # 检查是否需要停止
            if not self.is_running:
                self.logger.info(f"分析已取消（线程正在停止）: {task.title}")
                self.task_queue.mark_task_failed(task, "分析已取消（线程正在停止）")
                return
                
            if not self.filter_api:
                self.logger.warning("筛选API未初始化，跳过分析")
                self.task_queue.mark_task_completed(task)
                self.analyzed_count += 1
                return
            
            # 执行视频分析
            filter_result = self.filter_api.analyze_video(
                task.video_path, 
                self.filter_prompt, 
                use_refined=self.use_refined
            )
            
            # 分析完成后立即检查是否需要停止
            # 注意：analyze_video 内部会循环分析多个帧，每个帧之间没有检查停止信号
            # 所以这里只能在整个视频分析完成后检查
            if not self.is_running:
                self.logger.info(f"分析已完成但线程正在停止，跳过后续处理: {task.title}")
                return
            
            self.analyzed_count += 1
            
            if filter_result['success']:
                is_satisfied = filter_result['is_satisfied']
                analysis_mode = filter_result.get('analysis_mode', 'normal')
                mode_text = "精细化分析" if analysis_mode == 'refined' else "普通分析"
                
                self.logger.info(f"分析完成: {task.title}")
                self.logger.debug(f"  分析模式: {mode_text}")
                self.logger.debug(f"  筛选结果: {'YES' if is_satisfied else 'NO'}")
                self.logger.debug(f"  满足率: {filter_result['satisfied_ratio']*100:.1f}%")
                
                # 如果是精细化分析，输出更多信息
                if analysis_mode == 'refined':
                    self.logger.debug(f"  状态: {filter_result.get('status', '')}")
                    self.logger.debug(f"  初始满足率: {filter_result.get('initial_ratio', 0.0)*100:.1f}%")
                    self.logger.debug(f"  迭代次数: {filter_result.get('iterations', 1)}")
                
                # 只有满足条件才标记为已完成
                if is_satisfied:
                    self.satisfied_count += 1
                    self.task_queue.mark_task_completed(task)
                    self.logger.info(f"视频满足条件，标记为已完成")
                    
                    # 调用回调函数通知流水线
                    if self.on_satisfied_callback and task.video_path:
                        try:
                            self.on_satisfied_callback(task.video_path)
                        except Exception as e:
                            self.logger.error(f"调用满足条件回调函数失败: {e}")
                else:
                    # 不满足条件标记为失败
                    reason = f"视频不满足条件 (满足率: {filter_result['satisfied_ratio']*100:.1f}%)"
                    self.logger.info(f"视频不满足条件，标记为未通过: {reason}")
                    self.task_queue.mark_task_failed(task, reason)
            else:
                error_msg = f"分析失败: {filter_result['message']}"
                self.logger.error(error_msg)
                self.failed_count += 1
                self.task_queue.mark_task_failed(task, error_msg)
                
        except Exception as e:
            error_msg = f"分析异常: {str(e)}"
            self.logger.exception(error_msg)
            self.failed_count += 1
            self.task_queue.mark_task_failed(task, error_msg)
    
    def get_statistics(self) -> dict:
        """
        获取工作线程统计信息
        
        Returns:
            统计信息字典
        """
        return {
            'worker_id': self.worker_id,
            'analyzed_count': self.analyzed_count,
            'satisfied_count': self.satisfied_count,
            'failed_count': self.failed_count,
            'is_running': self.is_running
        }


class AnalyzerPool:
    """分析线程池"""
    
    def __init__(self, num_workers: int = 3, task_queue: Optional[TaskQueue] = None):
        """
        初始化分析线程池
        
        Args:
            num_workers: 工作线程数量
            task_queue: 任务队列（可选，如未提供则创建新队列）
        """
        self.num_workers = num_workers
        self.task_queue = task_queue or TaskQueue()
        self.workers: list[AnalyzerWorker] = []
        self.is_running = False
        self.lock = threading.Lock()
        self.filter_api = None
        self.filter_prompt = ""
        self.use_refined = False
        
        # 满足条件视频回调函数
        self.on_satisfied_callback: Optional[Callable[[str], None]] = None
        
        # 初始化筛选API
        self._init_filter_api()
    
    def _init_filter_api(self):
        """初始化筛选API"""
        try:
            from filter_api import create_filter_api_from_config
            
            # 构建配置文件路径
            filter_config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
                '大模型接入筛选', 
                'config.json'
            )
            
            if os.path.exists(filter_config_path):
                import json
                with open(filter_config_path, 'r', encoding='utf-8') as f:
                    filter_config = json.load(f)
                    api_key = filter_config.get('api_key', '')
                    
                    # 读取配置文件中的prompt
                    self.default_filter_prompt = filter_config.get('prompt', '')
                    
                    if api_key:
                        self.filter_api = create_filter_api_from_config(filter_config_path)
                        print(f"[分析池] 筛选API已初始化")
                        if self.default_filter_prompt:
                            print(f"[分析池] 已加载默认筛选Prompt: {self.default_filter_prompt[:30]}...")
                    else:
                        print(f"[分析池] 未配置智谱API Key，筛选功能不可用")
            else:
                print(f"[分析池] 未找到筛选配置文件: {filter_config_path}")
                self.default_filter_prompt = ""
                
        except ImportError as e:
            print(f"[分析池] 无法导入筛选模块: {str(e)}")
            self.default_filter_prompt = ""
        except Exception as e:
            print(f"[分析池] 初始化筛选API失败: {str(e)}")
            self.default_filter_prompt = ""
    
    def set_filter_prompt(self, prompt: str, use_refined: bool = False):
        """
        设置筛选提示词
        
        Args:
            prompt: 筛选提示词
            use_refined: 是否使用精细化分析
        """
        self.filter_prompt = prompt or self.default_filter_prompt
        self.use_refined = use_refined
        
        if not self.filter_prompt:
            print("[分析池] 警告: 筛选提示词为空")
        
        mode_text = "精细化分析" if use_refined else "普通分析"
        print(f"[分析池] 已设置筛选Prompt: {self.filter_prompt[:50]}... ({mode_text})")
    
    def set_on_satisfied_callback(self, callback: Callable[[str], None]):
        """
        设置满足条件视频的回调函数
        
        Args:
            callback: 回调函数，接收视频路径作为参数
        """
        self.on_satisfied_callback = callback
    
    def start(self):
        """启动线程池"""
        with self.lock:
            if self.is_running:
                print("[分析池] 线程池已在运行")
                return
            
            if not self.filter_api:
                print("[分析池] 警告: 筛选API未初始化，分析功能将不可用")
            
            self.is_running = True
            
            # 创建并启动工作线程
            for i in range(self.num_workers):
                worker = AnalyzerWorker(
                    i + 1, 
                    self.filter_api, 
                    self.task_queue,
                    self.filter_prompt,
                    self.use_refined,
                    self.on_satisfied_callback
                )
                worker.start()
                self.workers.append(worker)
            
            print(f"[分析池] 已启动 {self.num_workers} 个分析线程")
    
    def stop(self):
        """停止线程池
        
        停止机制说明：
        1. 设置 is_running = False，通知所有工作线程停止
        2. 每个工作线程会在完成当前分析任务后，检查 is_running 并退出
        3. 如果需要强制立即停止（不等待当前分析完成），主线程可以直接退出
           由于工作线程是守护线程(daemon=True)，主线程退出时会被强制终止
        
        优雅停止流程：设置 is_running=False → 等待当前分析任务完成 → 线程退出
        强制停止流程：主线程调用 sys.exit() → 守护线程立即终止（不管当前是否在分析）
        """
        with self.lock:
            if not self.is_running:
                print("[分析池] 线程池未运行")
                return
            
            self.is_running = False
            
            # 通知所有工作线程停止
            for worker in self.workers:
                worker.stop()
            
            self.workers.clear()
            print(f"[分析池] 已发送停止信号给所有分析线程")
    
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
        total_analyzed = sum(w['analyzed_count'] for w in workers_stats)
        total_satisfied = sum(w['satisfied_count'] for w in workers_stats)
        total_failed = sum(w['failed_count'] for w in workers_stats)
        
        return {
            'num_workers': self.num_workers,
            'is_running': self.is_running,
            'total_analyzed': total_analyzed,
            'total_satisfied': total_satisfied,
            'total_failed': total_failed,
            'satisfaction_rate': (total_satisfied / total_analyzed * 100) if total_analyzed > 0 else 0,
            'workers': workers_stats
        }
    
    def print_statistics(self):
        """打印线程池统计信息"""
        stats = self.get_statistics()
        print(f"\n[分析池统计]")
        print(f"  线程数: {stats['num_workers']}")
        print(f"  运行状态: {'运行中' if stats['is_running'] else '已停止'}")
        print(f"  总分析: {stats['total_analyzed']}")
        print(f"  满足条件: {stats['total_satisfied']}")
        print(f"  失败: {stats['total_failed']}")
        print(f"  满足率: {stats['satisfaction_rate']:.1f}%")
        print(f"  各线程详情:")
        for worker_stat in stats['workers']:
            print(f"    线程-{worker_stat['worker_id']}: 分析 {worker_stat['analyzed_count']}, 满足 {worker_stat['satisfied_count']}, 失败 {worker_stat['failed_count']}")
    
    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.stop()