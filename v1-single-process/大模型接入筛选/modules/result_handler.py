#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
结果处理模块
负责处理和输出分析结果
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional


def create_result(video_path: str) -> Dict[str, Any]:
    """
    创建单个视频的结果结构
    
    Args:
        video_path: 视频文件路径
        
    Returns:
        结果字典
    """
    return {
        "video_path": video_path,
        "status": "pending",
        "frames_analyzed": 0,
        "satisfied": False,
        "satisfied_frames": 0,
        "details": [],
        "timestamp": datetime.now().isoformat()
    }


def add_frame_result(result: Dict[str, Any], timestamp: float, success: bool, 
                      analysis: str, satisfied: bool = False) -> None:
    """
    添加帧分析结果
    
    Args:
        result: 结果字典
        timestamp: 帧时间戳
        success: 是否成功分析
        analysis: 分析结果
        satisfied: 是否满足条件
    """
    frame_result = {
        "timestamp": timestamp,
        "success": success,
        "analysis": analysis,
        "satisfied": satisfied
    }
    result["details"].append(frame_result)
    result["frames_analyzed"] += 1
    
    if satisfied:
        result["satisfied_frames"] = result.get("satisfied_frames", 0) + 1


def finalize_result(result: Dict[str, Any]) -> None:
    """
    完成结果处理，设置最终状态
    
    Args:
        result: 结果字典
    """
    result["status"] = "completed"
    result["satisfied"] = result.get("satisfied_frames", 0) > 0
    result["completed_at"] = datetime.now().isoformat()


def print_result(result: Dict[str, Any]) -> None:
    """
    打印单个视频的结果
    
    Args:
        result: 结果字典
    """
    status = "YES" if result["satisfied"] else "NO"
    print(f"\n{'='*60}")
    print(f"视频: {result['video_path']}")
    print(f"状态: {result['status']}")
    print(f"分析帧数: {result['frames_analyzed']}")
    print(f"满足条件帧数: {result.get('satisfied_frames', 0)}")
    print(f"最终结果: {status}")
    print(f"{'='*60}")


def save_results(results: List[Dict[str, Any]], output_path: str) -> None:
    """
    保存结果到JSON文件
    
    Args:
        results: 结果列表
        output_path: 输出文件路径
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"[ResultHandler] 结果已保存到: {output_path}")


def print_summary(results: List[Dict[str, Any]]) -> None:
    """
    打印汇总信息
    
    Args:
        results: 结果列表
    """
    total = len(results)
    yes_count = sum(1 for r in results if r.get("satisfied", False))
    no_count = total - yes_count
    
    print(f"\n{'#'*60}")
    print(f"汇总报告")
    print(f"{'#'*60}")
    print(f"总视频数: {total}")
    print(f"满足条件 (YES): {yes_count}")
    print(f"不满足条件 (NO): {no_count}")
    print(f"{'#'*60}")


class ResultHandler:
    """结果处理器类"""
    
    def __init__(self, output_file: str = "result.json"):
        """
        初始化结果处理器
        
        Args:
            output_file: 输出文件路径
        """
        self.output_file = output_file
        self.results: List[Dict[str, Any]] = []
    
    def create_result(self, video_path: str) -> Dict[str, Any]:
        """
        创建并添加新结果
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            结果字典
        """
        result = create_result(video_path)
        self.results.append(result)
        return result
    
    def add_frame_result(self, result: Dict[str, Any], timestamp: float, 
                         success: bool, analysis: str, satisfied: bool = False) -> None:
        """
        添加帧分析结果
        """
        add_frame_result(result, timestamp, success, analysis, satisfied)
    
    def finalize_result(self, result: Dict[str, Any]) -> None:
        """
        完成结果处理
        """
        finalize_result(result)
    
    def print_result(self, result: Dict[str, Any]) -> None:
        """
        打印结果
        """
        print_result(result)
    
    def save(self) -> None:
        """
        保存所有结果到文件
        """
        save_results(self.results, self.output_file)
    
    def print_summary(self) -> None:
        """
        打印汇总信息
        """
        print_summary(self.results)
    
    def get_results(self) -> List[Dict[str, Any]]:
        """
        获取所有结果
        
        Returns:
            结果列表
        """
        return self.results