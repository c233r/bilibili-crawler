#!/usr/bin/env python3
"""
批量合并分离的音视频文件
支持递归遍历目录中的所有子目录
"""

import os
import sys

# 添加src目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from ffmpeg.merger import FFMpegMerger

def main():
    # 默认下载路径
    default_path = r'./downloads/tv'
    
    # 获取用户输入的路径
    if len(sys.argv) > 1:
        directory = sys.argv[1]
    else:
        directory = input(f"请输入要合并的目录路径（默认: {default_path}）: ").strip()
        if not directory:
            directory = default_path
    
    # 检查路径是否存在
    if not os.path.exists(directory):
        print(f"错误: 目录不存在 - {directory}")
        sys.exit(1)
    
    # 创建合并器
    merger = FFMpegMerger()
    
    if not merger.ffmpeg_path:
        print("错误: 未找到ffmpeg，请先安装ffmpeg并添加到系统PATH")
        print("安装方法：")
        print("  1. 下载ffmpeg: https://ffmpeg.org/download.html")
        print("  2. 解压到 C:\\ffmpeg")
        print("  3. 将 C:\\ffmpeg\\bin 添加到系统PATH")
        sys.exit(1)
    
    print(f"[批量合并] 使用ffmpeg: {merger.ffmpeg_path}")
    print(f"[批量合并] 目标目录: {directory}")
    print("="*60)
    
    # 执行批量合并
    merged_files = merger.batch_merge(directory)
    
    print("="*60)
    if merged_files:
        print(f"批量合并完成！成功合并 {len(merged_files)} 个文件")
    else:
        print("未找到需要合并的分离音视频文件")

if __name__ == "__main__":
    main()
