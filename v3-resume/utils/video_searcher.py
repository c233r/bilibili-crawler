"""
视频搜索与下载工具（通用）

封装通用的视频搜索和下载逻辑，支持：
- 分页搜索视频
- 自动添加到流水线
- 队列满时暂存
- 达到目标数量自动停止
- 断点续传支持
"""

import time
from typing import Optional, Callable, List, Dict, Tuple
from model.bilibili_api import BilibiliAPI


class VideoSearcher:
    """视频搜索器（单例模式）"""
    
    _instance = None
    _lock = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._lock = None
        return cls._instance
    
    def __init__(self):
        if self._lock is None:
            import threading
            self._lock = threading.Lock()
            self.api = BilibiliAPI()
    
    def search_and_download(
        self,
        keyword: str,
        pipeline,
        target_count: int = 0,
        start_page: int = 1,
        page_size: int = 20,
        pending_items: Optional[List[Dict]] = None,
        on_page_callback: Optional[Callable[[int, List[Dict]], None]] = None,
        on_complete_callback: Optional[Callable[[int], None]] = None,
        on_error_callback: Optional[Callable[[int, Exception], None]] = None,
    ) -> Tuple[int, List[Dict]]:
        """
        搜索并下载视频
        
        Args:
            keyword: 搜索关键词
            pipeline: VideoPipeline 实例
            target_count: 目标下载数量（0表示全部）
            start_page: 起始页码
            page_size: 每页数量
            pending_items: 待处理的视频列表（断点续传时使用）
            on_page_callback: 每页回调函数 (page, items) -> None
            on_complete_callback: 完成回调函数 (total_found) -> None
            on_error_callback: 错误回调函数 (page, error) -> None
        
        Returns:
            (总找到的视频数, 剩余待处理的视频列表)
        """
        if pending_items is None:
            pending_items = []
        
        page = start_page
        total_videos_found = 0
        
        while True:
            # 检查是否达到目标数量
            stats = pipeline.print_statistics()
            satisfied_count = stats.get('satisfied_count', 0)
            
            if target_count > 0 and satisfied_count >= target_count:
                print(f"\n[完成] 已达到设定的下载数量 ({satisfied_count} 个)")
                break
            
            # 先尝试添加之前暂存的视频
            if pending_items:
                _, pending_items = pipeline.add_download_tasks(pending_items)
            
            # 检查断点续传是否已完成
            if not pending_items and page > start_page:
                if pipeline.task_queue.get_download_queue_size() == 0:
                    print("[完成] 所有视频已处理完毕")
                    break
            
            print(f"\n[获取] 正在获取第 {page} 页...")
            
            try:
                items, total = self.api.search_videos(keyword, page=page, page_size=page_size)
            except Exception as e:
                print(f"[错误] 获取第 {page} 页失败: {str(e)}")
                if on_error_callback:
                    on_error_callback(page, e)
                page += 1
                continue
            
            if not items:
                print("[完成] 已获取全部内容")
                break
            
            total_videos_found += len(items)
            print(f"[获取] 第 {page} 页找到 {len(items)} 个视频")
            
            # 调用每页回调
            if on_page_callback:
                on_page_callback(page, items)
            
            # 等待下载队列待处理数低于20个再添加新任务
            while True:
                pending_count = pipeline.task_queue.get_download_queue_size()
                if pending_count < 20:
                    break
                time.sleep(0.5)
            
            # 添加下载任务
            added_count, skipped_videos = pipeline.add_download_tasks(items)
            if skipped_videos:
                # 队列已满，暂存未能添加的视频
                pending_items.extend(skipped_videos)
            
            # 检查是否达到目标数量
            stats = pipeline.print_statistics()
            satisfied_count = stats.get('satisfied_count', 0)
            
            if target_count > 0 and satisfied_count >= target_count:
                print(f"\n[完成] 已达到设定的下载数量 ({satisfied_count} 个)")
                break
            
            # 翻页继续获取
            page += 1
        
        # 调用完成回调
        if on_complete_callback:
            on_complete_callback(total_videos_found)
        
        return total_videos_found, pending_items


# 单例实例
_searcher_instance = None


def get_video_searcher() -> VideoSearcher:
    """获取视频搜索器单例"""
    global _searcher_instance
    if _searcher_instance is None:
        _searcher_instance = VideoSearcher()
    return _searcher_instance