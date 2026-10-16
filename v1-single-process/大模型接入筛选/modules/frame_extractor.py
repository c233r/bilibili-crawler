#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
视频帧提取模块
负责从视频中按指定间隔提取帧图片
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional

# 支持的视频格式
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm', '.m4v'}


def find_video_files(directory: str) -> List[str]:
    """
    递归查找目录中的所有视频文件
    
    Args:
        directory: 要扫描的目录路径
        
    Returns:
        视频文件路径列表
    """
    video_files = []
    directory = Path(directory)
    
    # Windows文件系统大小写不敏感，只需要查找小写扩展名
    for ext in VIDEO_EXTENSIONS:
        video_files.extend(directory.rglob(f'*{ext}'))
    
    # 使用集合去重并保持顺序
    seen = set()
    unique_files = []
    for f in video_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(str(f))
    
    return unique_files


def get_video_duration(video_path: str) -> Optional[float]:
    """
    获取视频时长（秒）
    
    Args:
        video_path: 视频文件路径
        
    Returns:
        视频时长（秒），失败返回None
    """
    try:
        # Windows下处理中文路径
        if sys.platform == 'win32':
            # 使用shell=True并确保路径正确编码
            cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_path}"'
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                encoding='utf-8',
                errors='ignore'
            )
        else:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
                capture_output=True,
                text=True
            )
        
        if result.returncode == 0:
            output = result.stdout.strip()
            if output:
                return float(output)
            else:
                print(f"[FrameExtractor] ffprobe输出为空")
        else:
            print(f"[FrameExtractor] ffprobe返回码: {result.returncode}")
            stderr_output = result.stderr if result.stderr else "无"
            print(f"[FrameExtractor] ffprobe错误信息: {stderr_output}")
    except Exception as e:
        print(f"[FrameExtractor] 获取视频时长失败: {video_path}, 错误: {e}")
    return None


def extract_frames(video_path: str, interval_seconds: int = 60) -> List[Tuple[bytes, float]]:
    """
    从视频中按间隔提取帧（直接存储在内存中，不创建临时文件）
    
    Args:
        video_path: 视频文件路径
        interval_seconds: 提取间隔（秒），默认60秒
        
    Returns:
        [(图片字节数据, 时间戳), ...] 列表
    """
    frames = []
    duration = get_video_duration(video_path)
    
    if duration is None or duration <= 0:
        print(f"[FrameExtractor] 无法获取视频时长: {video_path}")
        return frames
    
    # 计算需要提取的时间点
    timestamps = list(range(0, int(duration), interval_seconds))
    if not timestamps or timestamps[-1] < duration - 1:
        timestamps.append(int(duration) - 1)  # 添加最后一帧
    
    print(f"[FrameExtractor] 视频时长: {duration:.1f}秒, 提取时间点: {timestamps}")
    
    for i, ts in enumerate(timestamps):
        try:
            # 使用管道输出，直接获取图片字节数据，不创建临时文件
            if sys.platform == 'win32':
                # Windows下使用shell=True处理中文路径
                cmd = f'ffmpeg -y -ss {ts} -i "{video_path}" -vframes 1 -q:v 2 -f image2pipe -'
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                result = subprocess.run(
                    ['ffmpeg', '-y', '-ss', str(ts), '-i', video_path,
                     '-vframes', '1', '-q:v', '2', '-f', 'image2pipe', '-'],
                    capture_output=True
                )
            
            if result.returncode == 0 and result.stdout:
                frames.append((result.stdout, ts))
                print(f"[FrameExtractor] 提取帧成功: {ts}秒")
            else:
                print(f"[FrameExtractor] 提取帧失败: {ts}秒")
                
        except Exception as e:
            print(f"[FrameExtractor] 提取帧异常: {video_path} @ {ts}s, 错误: {e}")
    
    return frames


class FrameExtractor:
    """视频帧提取器类"""
    
    def __init__(self, interval_seconds: int = 60):
        """
        初始化帧提取器
        
        Args:
            interval_seconds: 提取间隔（秒）
        """
        self.interval_seconds = interval_seconds
    
    def extract(self, video_path: str) -> List[Tuple[bytes, float]]:
        """
        从视频中提取帧（直接返回字节数据，不创建临时文件）
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            [(图片字节数据, 时间戳), ...] 列表
        """
        return extract_frames(video_path, self.interval_seconds)
    
    @staticmethod
    def find_videos(directory: str) -> List[str]:
        """
        查找目录中的视频文件
        
        Args:
            directory: 目录路径
            
        Returns:
            视频文件路径列表
        """
        return find_video_files(directory)