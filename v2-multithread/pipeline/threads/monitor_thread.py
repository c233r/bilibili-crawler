"""
监控线程模块
包含统计监控和停止控制逻辑
"""
import time
import threading
from typing import Callable, Optional


class PipelineMonitor(threading.Thread):
    """
    流水线监控线程
    
    负责：
    1. 定期输出统计信息
    2. 检查停止条件并触发优雅关闭
    """
    
    def __init__(self, 
                 name: str = "PipelineMonitor",
                 interval: float = 2.0,
                 get_statistics_callback: Optional[Callable] = None,
                 check_stop_callback: Optional[Callable] = None,
                 stop_callback: Optional[Callable] = None):
        """
        初始化监控线程
        
        Args:
            name: 线程名称
            interval: 检查间隔（秒）
            get_statistics_callback: 获取统计信息的回调函数
            check_stop_callback: 检查是否需要停止的回调函数
            stop_callback: 停止流水线的回调函数
        """
        super().__init__(name=name, daemon=True)
        
        self.interval = interval
        self.get_statistics_callback = get_statistics_callback
        self.check_stop_callback = check_stop_callback
        self.stop_callback = stop_callback
        
        self.running = False
        self._stop_event = threading.Event()
    
    def start(self):
        """启动监控线程"""
        self.running = True
        self._stop_event.clear()
        super().start()
    
    def stop(self):
        """停止监控线程"""
        self.running = False
        self._stop_event.set()
    
    def run(self):
        """监控线程主循环"""
        while self.running:
            try:
                # 输出统计信息
                if self.get_statistics_callback:
                    self.get_statistics_callback()
                
                # 检查是否需要停止
                if self.check_stop_callback and self.check_stop_callback():
                    if self.stop_callback:
                        self.stop_callback()
                    break
                
                # 等待下一次检查
                self._stop_event.wait(timeout=self.interval)
            except Exception as e:
                # 记录异常但不中断监控
                pass
        
        self.running = False
