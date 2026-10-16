"""
EdgeCrafter API 客户端
用于与 EdgeCrafter 服务进行通信
"""
import os
import json
import requests
import asyncio
import aiohttp
from typing import Optional, Dict, Any


class TaskStatus:
    """任务状态对象"""
    
    def __init__(self, **kwargs):
        self.task_id = kwargs.get('task_id')
        self.filename = kwargs.get('filename')
        self.status = kwargs.get('status')
        self.progress = kwargs.get('progress')
        self.message = kwargs.get('message')
        self.total_frames = kwargs.get('total_frames')
        self.total_detections = kwargs.get('total_detections')
        self.output_dir = kwargs.get('output_dir')
        self.processing_time = kwargs.get('processing_time')


class EdgeCrafterClient:
    """EdgeCrafter API 客户端（同步版本）"""
    
    def __init__(self, url: str = 'http://localhost:8000'):
        """
        初始化客户端
        
        Args:
            url: API服务地址
        """
        # 确保URL有正确的协议前缀
        if not url.startswith(('http://', 'https://')):
            url = f'http://{url}'
        self.url = url.rstrip('/')
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            response = requests.get(f"{self.url}/health")
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        try:
            response = requests.get(f"{self.url}/status")
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_queue_status(self) -> Dict[str, Any]:
        """获取队列状态"""
        try:
            response = requests.get(f"{self.url}/queue/status")
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def upload_video(self, video_path: str, conf_threshold: float = 0.5) -> Dict[str, Any]:
        """
        上传视频（同步）
        
        Args:
            video_path: 视频文件路径
            conf_threshold: 置信度阈值
        
        Returns:
            任务信息
        """
        try:
            filename = os.path.basename(video_path)
            with open(video_path, 'rb') as f:
                files = {'file': (filename, f)}
                data = {'conf_threshold': conf_threshold}
                response = requests.post(f"{self.url}/infer/video", files=files, data=data)
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_task_status(self, task_id: str) -> TaskStatus:
        """
        查询任务状态
        
        Args:
            task_id: 任务ID
        
        Returns:
            任务状态对象
        """
        try:
            response = requests.get(f"{self.url}/tasks/{task_id}")
            data = response.json()
            return TaskStatus(**data)
        except Exception as e:
            return TaskStatus(status="error", message=str(e))
    
    def list_tasks(self) -> Dict[str, Any]:
        """列出所有任务"""
        try:
            response = requests.get(f"{self.url}/tasks")
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def delete_task(self, task_id: str) -> Dict[str, Any]:
        """删除任务记录"""
        try:
            response = requests.delete(f"{self.url}/tasks/{task_id}")
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def wait_for_completion(self, task_id: str, poll_interval: float = 2.0, timeout: float = 300.0) -> TaskStatus:
        """
        等待任务完成（同步）
        
        Args:
            task_id: 任务ID
            poll_interval: 轮询间隔（秒）
            timeout: 超时时间（秒）
        
        Returns:
            最终任务状态对象
        
        Raises:
            TimeoutError: 任务超时
        """
        import time
        
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                raise TimeoutError(f"任务超时（{timeout}秒）")
            
            status = self.get_task_status(task_id)
            if status.status in ['completed', 'failed']:
                return status
            
            time.sleep(poll_interval)


class AsyncEdgeCrafterClient:
    """EdgeCrafter API 客户端（异步版本）"""
    
    def __init__(self, url: str = 'http://localhost:8000'):
        """
        初始化异步客户端
        
        Args:
            url: API服务地址
        """
        # 确保URL有正确的协议前缀
        if not url.startswith(('http://', 'https://')):
            url = f'http://{url}'
        self.url = url.rstrip('/')
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查（异步）"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.url}/health") as response:
                    return await response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def get_status(self) -> Dict[str, Any]:
        """获取服务状态（异步）"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.url}/status") as response:
                    return await response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def get_queue_status(self) -> Dict[str, Any]:
        """获取队列状态（异步）"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.url}/queue/status") as response:
                    return await response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def upload_video(self, video_path: str, conf_threshold: float = 0.5) -> Dict[str, Any]:
        """
        上传视频（异步）
        
        Args:
            video_path: 视频文件路径
            conf_threshold: 置信度阈值
        
        Returns:
            任务信息
        """
        try:
            filename = os.path.basename(video_path)
            with open(video_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('file', f, filename=filename)
                data.add_field('conf_threshold', str(conf_threshold))
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(f"{self.url}/infer/video", data=data) as response:
                        return await response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def get_task_status(self, task_id: str) -> TaskStatus:
        """
        查询任务状态（异步）
        
        Args:
            task_id: 任务ID
        
        Returns:
            任务状态对象
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.url}/tasks/{task_id}") as response:
                    data = await response.json()
                    return TaskStatus(**data)
        except Exception as e:
            return TaskStatus(status="error", message=str(e))
    
    async def list_tasks(self) -> Dict[str, Any]:
        """列出所有任务（异步）"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.url}/tasks") as response:
                    return await response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def delete_task(self, task_id: str) -> Dict[str, Any]:
        """删除任务记录（异步）"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(f"{self.url}/tasks/{task_id}") as response:
                    return await response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def wait_for_completion(self, task_id: str, poll_interval: float = 2.0, timeout: float = 300.0) -> TaskStatus:
        """
        等待任务完成（异步）
        
        Args:
            task_id: 任务ID
            poll_interval: 轮询间隔（秒）
            timeout: 超时时间（秒）
        
        Returns:
            最终任务状态对象
        
        Raises:
            TimeoutError: 任务超时
        """
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                raise TimeoutError(f"任务超时（{timeout}秒）")
            
            status = await self.get_task_status(task_id)
            if status.status in ['completed', 'failed']:
                return status
            
            await asyncio.sleep(poll_interval)
