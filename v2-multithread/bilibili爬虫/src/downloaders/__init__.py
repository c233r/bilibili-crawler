"""
下载器模块
包含视频、TV剧集等不同类型的下载器
"""
from .base_downloader import BaseDownloader
from .video_downloader import VideoDownloader
from .tv_downloader import TvDownloader

__all__ = ['BaseDownloader', 'VideoDownloader', 'TvDownloader']