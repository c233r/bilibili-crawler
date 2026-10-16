"""
视频下载器
负责下载普通B站视频
"""
import os
import re
import sys
from .base_downloader import BaseDownloader

# 添加项目根目录到路径
# sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ffmpeg.merger import FFMpegMerger

class VideoDownloader(BaseDownloader):
    """普通视频下载器"""
    
    def __init__(self):
        super().__init__()
        # 设置视频专用下载路径
        self.download_path = os.path.join(os.path.expanduser('~'), 'Downloads', 'bilibili', 'videos')
        self.merger = FFMpegMerger()
    
    def download(self, bvid, title):
        """下载单个视频
        
        Args:
            bvid: 视频BV号
            title: 视频标题
        
        Returns:
            (success, message)
        """
        try:
            # 确保下载目录存在
            if not os.path.exists(self.download_path):
                os.makedirs(self.download_path)
            
            video_url = f"https://www.bilibili.com/video/{bvid}"
            print(f"[视频下载] 开始下载: {title}")
            print(f"[视频下载] 链接: {video_url}")
            
            if self.use_ytdlp:
                success, msg = self._download_with_ytdlp(video_url, title)
            else:
                success, msg = self._download_with_youget(video_url, title)
            
            return (success, msg)
                
        except Exception as e:
            print(f"[视频下载错误] {title} - {str(e)}")
            return (False, f"下载错误: {title} - {str(e)}")