#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
视频统计模块
对每个视频的提取帧进行satisfied统计，判断视频是否满足要求
"""

import json
import os
from datetime import datetime
from typing import Dict, Any, List, Optional


class VideoStatistics:
    """
    视频统计类
    统计每个视频的帧分析结果，判断是否满足要求
    """
    
    def __init__(self, threshold: float = 0.6):
        """
        初始化统计器
        
        Args:
            threshold: satisfied占比阈值，默认0.6（60%）
                      如果satisfied=True占比超过阈值，则视频满足要求
        """
        self.threshold = threshold
        self.video_stats: Dict[str, Dict[str, Any]] = {}
    
    def add_frame_result(self, video_path: str, satisfied: bool, 
                         timestamp: float = None, reason: str = None) -> None:
        """
        添加单帧分析结果
        
        Args:
            video_path: 视频路径
            satisfied: 该帧是否满足条件
            timestamp: 帧时间戳（可选）
            reason: 分析理由（可选）
        """
        if video_path not in self.video_stats:
            self.video_stats[video_path] = {
                "video_path": video_path,
                "total_frames": 0,
                "satisfied_frames": 0,
                "unsatisfied_frames": 0,
                "frame_details": [],
                "status": "pending"
            }
        
        stats = self.video_stats[video_path]
        stats["total_frames"] += 1
        
        if satisfied:
            stats["satisfied_frames"] += 1
        else:
            stats["unsatisfied_frames"] += 1
        
        # 记录帧详情
        if timestamp is not None:
            stats["frame_details"].append({
                "timestamp": timestamp,
                "satisfied": satisfied,
                "reason": reason
            })
    
    def calculate_result(self, video_path: str) -> Dict[str, Any]:
        """
        计算单个视频的最终结果
        
        Args:
            video_path: 视频路径
            
        Returns:
            包含统计结果的字典
        """
        if video_path not in self.video_stats:
            return {"error": "未找到该视频的统计数据"}
        
        stats = self.video_stats[video_path]
        
        # 计算satisfied占比
        total = stats["total_frames"]
        satisfied = stats["satisfied_frames"]
        
        if total == 0:
            ratio = 0.0
        else:
            ratio = satisfied / total
        
        # 判断是否满足要求：satisfied占比超过阈值才算满足
        is_satisfied = ratio > self.threshold
        
        # 更新统计结果
        stats["satisfied_ratio"] = round(ratio, 4)
        stats["threshold"] = self.threshold
        stats["is_satisfied"] = is_satisfied
        stats["status"] = "completed"
        stats["completed_at"] = datetime.now().isoformat()
        
        return stats
    
    def get_all_results(self) -> List[Dict[str, Any]]:
        """
        获取所有视频的统计结果
        
        Returns:
            所有视频的统计结果列表
        """
        results = []
        for video_path in self.video_stats:
            results.append(self.calculate_result(video_path))
        return results
    
    def print_result(self, video_path: str) -> None:
        """
        打印单个视频的统计结果
        
        Args:
            video_path: 视频路径
        """
        stats = self.calculate_result(video_path)
        
        if "error" in stats:
            print(f"错误: {stats['error']}")
            return
        
        # 输出结果
        print(f"\n{'='*60}")
        print(f"视频统计结果")
        print(f"{'='*60}")
        print(f"视频路径: {video_path}")
        print(f"总帧数: {stats['total_frames']}")
        print(f"满足条件帧数: {stats['satisfied_frames']}")
        print(f"不满足条件帧数: {stats['unsatisfied_frames']}")
        print(f"满足占比: {stats['satisfied_ratio']*100:.2f}%")
        print(f"阈值: {stats['threshold']*100:.2f}%")
        
        # 判断结果
        if stats['is_satisfied']:
            print(f"最终判定: YES (满足要求)")
        else:
            print(f"最终判定: NO (不满足要求)")
        
        print(f"{'='*60}")
    
    def print_summary(self) -> None:
        """
        打印所有视频的汇总统计
        """
        results = self.get_all_results()
        
        total_videos = len(results)
        satisfied_videos = sum(1 for r in results if r.get("is_satisfied", False))
        unsatisfied_videos = total_videos - satisfied_videos
        
        print(f"\n{'#'*60}")
        print(f"视频统计汇总报告")
        print(f"{'#'*60}")
        print(f"统计阈值: satisfied占比超过 {self.threshold*100:.2f}% 才算满足要求")
        print(f"总视频数: {total_videos}")
        print(f"满足要求视频数: {satisfied_videos}")
        print(f"不满足要求视频数: {unsatisfied_videos}")
        print(f"{'#'*60}")
        
        # 打印详细列表
        print(f"\n详细结果:")
        print("-" * 60)
        for r in results:
            status = "YES" if r.get("is_satisfied", False) else "NO"
            ratio = r.get("satisfied_ratio", 0) * 100
            print(f"{status} | {ratio:.1f}% | {r['video_path']}")
        print("-" * 60)
    
    def save_results(self, output_path: str) -> None:
        """
        保存统计结果到JSON文件
        
        Args:
            output_path: 输出文件路径
        """
        results = self.get_all_results()
        
        output_data = {
            "threshold": self.threshold,
            "description": f"satisfied占比超过{self.threshold*100:.2f}%才算满足要求",
            "summary": {
                "total_videos": len(results),
                "satisfied_videos": sum(1 for r in results if r.get("is_satisfied", False)),
                "unsatisfied_videos": len(results) - sum(1 for r in results if r.get("is_satisfied", False))
            },
            "details": results,
            "generated_at": datetime.now().isoformat()
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        print(f"[VideoStatistics] 统计结果已保存到: {output_path}")


def analyze_result_file(result_file: str, threshold: float = 0.6, 
                         output_file: str = None) -> VideoStatistics:
    """
    从已有的result.json文件分析视频统计
    
    Args:
        result_file: 已有的分析结果文件路径
        threshold: satisfied占比阈值
        output_file: 输出文件路径（可选）
        
    Returns:
        VideoStatistics实例
    """
    if not os.path.exists(result_file):
        print(f"错误: 结果文件不存在: {result_file}")
        return None
    
    with open(result_file, 'r', encoding='utf-8') as f:
        results = json.load(f)
    
    # 创建统计器
    stats = VideoStatistics(threshold=threshold)
    
    # 遍历每个视频的结果
    for video_result in results:
        video_path = video_result.get("video_path", "")
        
        # 遍历每个帧的结果
        for frame in video_result.get("details", []):
            satisfied = frame.get("satisfied", False)
            timestamp = frame.get("timestamp", None)
            reason = frame.get("analysis", None)
            
            stats.add_frame_result(video_path, satisfied, timestamp, reason)
    
    # 打印汇总
    stats.print_summary()
    
    # 保存结果
    if output_file:
        stats.save_results(output_file)
    
    return stats


if __name__ == "__main__":
    # 测试代码
    import argparse
    
    parser = argparse.ArgumentParser(description="视频帧统计工具")
    parser.add_argument("result_file", help="分析结果文件路径 (result.json)")
    parser.add_argument("--threshold", "-t", type=float, default=0.6,
                        help="satisfied占比阈值 (默认0.6)")
    parser.add_argument("--output", "-o", default="statistics.json",
                        help="输出文件路径")
    
    args = parser.parse_args()
    
    analyze_result_file(args.result_file, args.threshold, args.output)