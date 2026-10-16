"""
视频推送模块
用于在分析完成后将满足条件的视频推送给 EdgeCrafter 服务器
"""
import os
import time
import asyncio
import threading
from typing import Optional, Dict, Any, List
from .edgecrafter_client import EdgeCrafterClient, AsyncEdgeCrafterClient


class VideoPusher:
    """视频推送器（同步版本）"""
    
    def __init__(self, api_url: str = 'http://localhost:8000', conf_threshold: float = 0.5):
        """
        初始化视频推送器
        
        Args:
            api_url: EdgeCrafter API服务地址
            conf_threshold: 置信度阈值
        """
        self.client = EdgeCrafterClient(api_url)
        self.conf_threshold = conf_threshold
        self.logger = None
        
    def set_logger(self, logger):
        """设置日志器"""
        self.logger = logger
    
    def _log(self, message: str, level: str = 'info'):
        """日志输出"""
        if self.logger:
            if level == 'error':
                self.logger.error(message)
            elif level == 'warning':
                self.logger.warning(message)
            else:
                self.logger.info(message)
        else:
            print(message)
    
    def push_video(self, video_path: str, wait: bool = False, poll_interval: float = 2.0) -> Dict[str, Any]:
        """
        推送单个视频到服务器（同步）
        
        Args:
            video_path: 视频文件路径
            wait: 是否等待处理完成
            poll_interval: 轮询间隔（秒）
        
        Returns:
            推送结果
        """
        if not os.path.exists(video_path):
            error_msg = f"视频文件不存在: {video_path}"
            self._log(error_msg, 'error')
            return {"status": "error", "message": error_msg}
        
        try:
            self._log(f"开始推送视频: {os.path.basename(video_path)}")
            
            # 上传视频
            result = self.client.upload_video(video_path, conf_threshold=self.conf_threshold)
            
            # 检查是否出错
            if result.get('status') == 'error':
                error_msg = result.get('message', str(result))
                self._log(f"视频推送失败: {error_msg}", 'error')
                return result
            
            # 检查是否成功（包含 task_id 表示成功）
            task_id = result.get('task_id')
            if task_id:
                self._log(f"视频推送成功，任务ID: {task_id}")
                
                # 如果需要等待完成
                if wait:
                    self._log(f"等待任务处理完成...")
                    try:
                        final_status = self.client.wait_for_completion(task_id, poll_interval=poll_interval)
                        self._log(f"任务处理完成，状态: {final_status.status}")
                        # 返回成功状态
                        return {
                            "status": "success",
                            "task_id": task_id,
                            "final_status": final_status.status,
                            "total_frames": final_status.total_frames,
                            "total_detections": final_status.total_detections,
                            "processing_time": final_status.processing_time,
                            "output_dir": final_status.output_dir
                        }
                    except TimeoutError:
                        self._log("任务处理超时", 'warning')
                        return {"status": "timeout", "task_id": task_id}
                
                # 不等待完成，返回上传成功
                return {
                    "status": "success",
                    "task_id": task_id,
                    "filename": result.get('filename'),
                    "message": result.get('message', '视频已上传')
                }
            else:
                # 没有 task_id，认为失败
                error_msg = f"视频推送失败: 未返回任务ID，响应: {result}"
                self._log(error_msg, 'error')
                return {"status": "error", "message": error_msg}
            
        except Exception as e:
            error_msg = f"视频推送异常: {str(e)}"
            self._log(error_msg, 'error')
            return {"status": "error", "message": error_msg}
    
    def push_videos(self, video_paths: List[str], wait: bool = False, poll_interval: float = 2.0) -> List[Dict[str, Any]]:
        """
        批量推送多个视频（同步）
        
        Args:
            video_paths: 视频文件路径列表
            wait: 是否等待处理完成
            poll_interval: 轮询间隔（秒）
        
        Returns:
            推送结果列表
        """
        results = []
        for video_path in video_paths:
            result = self.push_video(video_path, wait, poll_interval)
            results.append(result)
            # 避免频繁请求
            time.sleep(0.5)
        return results


class AsyncVideoPusher:
    """视频推送器（异步版本）"""
    
    def __init__(self, api_url: str = 'http://localhost:8000', conf_threshold: float = 0.5):
        """
        初始化异步视频推送器
        
        Args:
            api_url: EdgeCrafter API服务地址
            conf_threshold: 置信度阈值
        """
        self.client = AsyncEdgeCrafterClient(api_url)
        self.conf_threshold = conf_threshold
        self.logger = None
        self._thread_local = threading.local()  # 每个线程持有一个持久事件循环
        
    def set_logger(self, logger):
        """设置日志器"""
        self.logger = logger
    
    def _log(self, message: str, level: str = 'info'):
        """日志输出"""
        if self.logger:
            if level == 'error':
                self.logger.error(message)
            elif level == 'warning':
                self.logger.warning(message)
            else:
                self.logger.info(message)
        else:
            print(message)
    
    async def push_video(self, video_path: str, wait: bool = False, poll_interval: float = 2.0) -> Dict[str, Any]:
        """
        推送单个视频到服务器（异步）
        
        Args:
            video_path: 视频文件路径
            wait: 是否等待处理完成
            poll_interval: 轮询间隔（秒）
        
        Returns:
            推送结果
        """
        if not os.path.exists(video_path):
            error_msg = f"视频文件不存在: {video_path}"
            self._log(error_msg, 'error')
            return {"status": "error", "message": error_msg}
        
        try:
            self._log(f"开始推送视频: {os.path.basename(video_path)}")
            
            # 上传视频（异步）
            result = await self.client.upload_video(video_path, conf_threshold=self.conf_threshold)
            
            # 检查是否出错
            if result.get('status') == 'error':
                error_msg = result.get('message', str(result))
                self._log(f"视频推送失败: {error_msg}", 'error')
                return result
            
            # 检查是否成功（包含 task_id 表示成功）
            task_id = result.get('task_id')
            if task_id:
                self._log(f"视频推送成功，任务ID: {task_id}")
                
                # 如果需要等待完成
                if wait:
                    self._log(f"等待任务处理完成...")
                    try:
                        final_status = await self.client.wait_for_completion(task_id, poll_interval=poll_interval)
                        self._log(f"任务处理完成，状态: {final_status.status}")
                        # 返回成功状态
                        return {
                            "status": "success",
                            "task_id": task_id,
                            "final_status": final_status.status,
                            "total_frames": final_status.total_frames,
                            "total_detections": final_status.total_detections,
                            "processing_time": final_status.processing_time,
                            "output_dir": final_status.output_dir
                        }
                    except TimeoutError:
                        self._log("任务处理超时", 'warning')
                        return {"status": "timeout", "task_id": task_id}
                
                # 不等待完成，返回上传成功
                return {
                    "status": "success",
                    "task_id": task_id,
                    "filename": result.get('filename'),
                    "message": result.get('message', '视频已上传')
                }
            else:
                # 没有 task_id，认为失败
                error_msg = f"视频推送失败: 未返回任务ID，响应: {result}"
                self._log(error_msg, 'error')
                return {"status": "error", "message": error_msg}
            
        except Exception as e:
            error_msg = f"视频推送异常: {str(e)}"
            self._log(error_msg, 'error')
            return {"status": "error", "message": error_msg}
    
    async def push_videos(self, video_paths: List[str], wait: bool = False, poll_interval: float = 2.0) -> List[Dict[str, Any]]:
        """
        批量推送多个视频（异步）
        
        Args:
            video_paths: 视频文件路径列表
            wait: 是否等待处理完成
            poll_interval: 轮询间隔（秒）
        
        Returns:
            推送结果列表
        """
        # 并发推送所有视频
        tasks = [self.push_video(video_path, wait, poll_interval) for video_path in video_paths]
        results = await asyncio.gather(*tasks)
        return results
    
    def push_videos_sync(self, video_paths: List[str], wait: bool = False, poll_interval: float = 2.0) -> List[Dict[str, Any]]:
        """
        批量推送多个视频（同步调用异步方法）
        
        使用调用者线程的持久事件循环（PushMonitor 线程），
        确保 Semaphore 与事件循环始终在同一线程，避免跨循环绑定冲突。
        
        Args:
            video_paths: 视频文件路径列表
            wait: 是否等待处理完成
            poll_interval: 轮询间隔（秒）
        
        Returns:
            推送结果列表
        """
        if not hasattr(self._thread_local, '_async_loop') or self._thread_local._async_loop.is_closed():
            self._thread_local._async_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._thread_local._async_loop)
        
        return self._thread_local._async_loop.run_until_complete(
            self.push_videos(video_paths, wait, poll_interval)
        )
