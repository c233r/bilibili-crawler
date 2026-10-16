#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
视频筛选API接口
提供简单的接口供爬虫调用，实现视频下载后的自动筛选功能
支持普通分析和精细化分析两种模式
"""

import os
import sys

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules import (
    FrameExtractor,
    VLMAnalyzer,
    SimpleVLMAnalyzer,
    VideoStatistics,
    AnalysisResult,
    RefinedAnalyzer
)


class VideoFilterAPI:
    """
    视频筛选API
    提供简单的接口供爬虫调用
    支持普通分析和精细化分析两种模式
    """
    
    def __init__(self, api_key: str, model: str = "glm-4v-flash", 
                 interval_seconds: int = 60, threshold: float = 0.6,
                 use_structured_output: bool = True, enable_refined: bool = False):
        """
        初始化筛选API
        
        Args:
            api_key: 智谱API Key
            model: 使用的模型
            interval_seconds: 帧提取间隔（秒）
            threshold: satisfied占比阈值
            use_structured_output: 是否使用结构化输出
            enable_refined: 是否启用精细化分析模式
        """
        self.api_key = api_key
        self.model = model
        self.interval_seconds = interval_seconds
        self.threshold = threshold
        self.use_structured_output = use_structured_output
        self.enable_refined = enable_refined
        
        # 初始化组件
        self.extractor = FrameExtractor(interval_seconds=interval_seconds)
        
        if use_structured_output:
            self.analyzer = VLMAnalyzer(api_key=api_key, model=model)
        else:
            self.analyzer = SimpleVLMAnalyzer(api_key=api_key, model=model)
        
        # 精细化分析器（按需初始化）
        self.refined_analyzer = None
    
    def analyze_video(self, video_path: str, prompt: str, use_refined: bool = None) -> dict:
        """
        分析单个视频
        
        Args:
            video_path: 视频文件路径
            prompt: 检测prompt
            use_refined: 是否使用精细化分析模式（None表示使用初始化时的设置）
            
        Returns:
            分析结果字典，包含:
                - success: bool, 是否分析成功
                - is_satisfied: bool, 视频是否满足要求
                - satisfied_ratio: float, satisfied占比
                - total_frames: int, 总帧数
                - satisfied_frames: int, 满足条件帧数
                - message: str, 结果消息
                - analysis_mode: str, 分析模式（'normal' 或 'refined'）
                - status: str, 精细化分析状态（'saved', 'discarded', 'error', 'needs_review'）
        """
        if not os.path.exists(video_path):
            return {
                "success": False,
                "is_satisfied": False,
                "satisfied_ratio": 0.0,
                "total_frames": 0,
                "satisfied_frames": 0,
                "message": f"视频文件不存在: {video_path}",
                "analysis_mode": "normal"
            }
        
        # 确定是否使用精细化分析
        should_use_refined = use_refined if use_refined is not None else self.enable_refined
        
        if should_use_refined:
            return self._analyze_video_refined(video_path, prompt)
        else:
            return self._analyze_video_normal(video_path, prompt)
    
    def _analyze_video_normal(self, video_path: str, prompt: str) -> dict:
        """
        使用普通模式分析单个视频
        
        Args:
            video_path: 视频文件路径
            prompt: 检测prompt
            
        Returns:
            分析结果字典
        """
        try:
            print(f"[VLM分析] 正在分析视频: {os.path.basename(video_path)}")
            
            # 提取帧
            frames = self.extractor.extract(video_path)
            
            if not frames:
                return {
                    "success": False,
                    "is_satisfied": False,
                    "satisfied_ratio": 0.0,
                    "total_frames": 0,
                    "satisfied_frames": 0,
                    "message": "无法提取视频帧",
                    "analysis_mode": "normal"
                }
            
            print(f"[VLM分析] 提取了 {len(frames)} 帧")
            
            # 创建统计器
            statistics = VideoStatistics(threshold=self.threshold)
            
            # 分析每一帧
            for frame_data, timestamp in frames:
                success, analysis_result = self.analyzer.analyze(frame_data, prompt)
                satisfied = analysis_result.satisfied if success else False
                
                statistics.add_frame_result(
                    video_path, satisfied, timestamp, 
                    str(analysis_result.reason) if success else "分析失败"
                )
                
                status = "满足条件" if satisfied else "不满足条件"
                print(f"[VLM分析] [{timestamp}s] {status}")
            
            # 计算结果
            result = statistics.calculate_result(video_path)
            
            is_satisfied = result.get("is_satisfied", False)
            ratio = result.get("satisfied_ratio", 0.0)
            total_frames = result.get("total_frames", 0)
            satisfied_frames = result.get("satisfied_frames", 0)
            
            message = f"分析完成: satisfied占比 {ratio*100:.1f}%, 阈值 {self.threshold*100:.1f}% -> {'YES' if is_satisfied else 'NO'}"
            print(f"[VLM分析] {message}")
            
            return {
                "success": True,
                "is_satisfied": is_satisfied,
                "satisfied_ratio": ratio,
                "total_frames": total_frames,
                "satisfied_frames": satisfied_frames,
                "message": message,
                "analysis_mode": "normal"
            }
            
        except Exception as e:
            return {
                "success": False,
                "is_satisfied": False,
                "satisfied_ratio": 0.0,
                "total_frames": 0,
                "satisfied_frames": 0,
                "message": f"分析错误: {str(e)}",
                "analysis_mode": "normal"
            }
    
    def _analyze_video_refined(self, video_path: str, prompt: str) -> dict:
        """
        使用精细化分析模式分析单个视频
        
        精细化分析策略：
        - >70%: 直接保存（满足要求）
        - 50%-70%: 递归精细化分析，直到满足率>70%或达到最小间隔5秒
        - <50%: 不保存（不满足要求）
        
        Args:
            video_path: 视频文件路径
            prompt: 检测prompt
            
        Returns:
            分析结果字典
        """
        try:
            print(f"\n{'='*60}")
            print(f"[精细化分析] 正在分析视频: {os.path.basename(video_path)}")
            print(f"{'='*60}")
            print("精细化分析策略:")
            print("  - >70%: 直接保存")
            print("  - 50%-70%: 递归精细化分析")
            print("  - <50%: 不保存")
            
            # 初始化精细化分析器
            if not self.refined_analyzer:
                self.refined_analyzer = RefinedAnalyzer(
                    self.analyzer, 
                    self.interval_seconds, 
                    prompt
                )
            
            # 创建临时输出目录
            temp_output_dir = os.path.join(os.path.dirname(video_path), "refined_output")
            os.makedirs(temp_output_dir, exist_ok=True)
            
            # 使用精细化分析
            result = self.refined_analyzer.analyze_video(video_path, temp_output_dir, prompt)
            
            # 解析结果
            status = result.get('status', 'error')
            reason = result.get('reason', '')
            initial_ratio = result.get('initial_ratio', 0.0)
            final_ratio = result.get('final_ratio', initial_ratio)
            
            # 判断是否满足要求
            # >70% 满足，<50% 不满足，50%-70% 经过精细化分析后决定
            is_satisfied = status == 'saved'
            
            message = f"精细化分析完成: {reason}"
            print(f"[精细化分析] 状态: {status}")
            print(f"[精细化分析] 原因: {reason}")
            print(f"[精细化分析] 初始满足率: {initial_ratio*100:.1f}%")
            print(f"[精细化分析] 最终满足率: {final_ratio*100:.1f}%")
            print(f"[精细化分析] 结果: {'YES' if is_satisfied else 'NO'}")
            print(f"{'='*60}")
            
            return {
                "success": True,
                "is_satisfied": is_satisfied,
                "satisfied_ratio": final_ratio,
                "total_frames": result.get('total_frames', 0),
                "satisfied_frames": result.get('satisfied_frames', 0),
                "message": message,
                "analysis_mode": "refined",
                "status": status,
                "initial_ratio": initial_ratio,
                "iterations": result.get('iterations', 1),
                "analysis_level": result.get('analysis_level', 'initial'),
                "output_paths": result.get('output_paths', []),
                "segments": result.get('segments', None)
            }
            
        except Exception as e:
            print(f"[精细化分析] 分析错误: {str(e)}")
            return {
                "success": False,
                "is_satisfied": False,
                "satisfied_ratio": 0.0,
                "total_frames": 0,
                "satisfied_frames": 0,
                "message": f"精细化分析错误: {str(e)}",
                "analysis_mode": "refined",
                "status": "error"
            }


def create_filter_api_from_config(config_path: str = "config.json", enable_refined: bool = None) -> VideoFilterAPI:
    """
    从配置文件创建筛选API实例
    
    Args:
        config_path: 配置文件路径
        enable_refined: 是否启用精细化分析（None表示使用配置文件中的设置）
        
    Returns:
        VideoFilterAPI实例
    """
    import json
    
    default_config = {
        "api_key": "",
        "model": "glm-4v-flash",
        "interval_seconds": 60,
        "threshold": 0.6,
        "use_structured_output": True,
        "enable_refined": False
    }
    
    config = default_config.copy()
    
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            user_config = json.load(f)
            config.update(user_config)
    
    # 使用参数或配置文件中的设置
    refined_enabled = enable_refined if enable_refined is not None else config.get('enable_refined', False)
    
    return VideoFilterAPI(
        api_key=config['api_key'],
        model=config['model'],
        interval_seconds=config['interval_seconds'],
        threshold=config['threshold'],
        use_structured_output=config.get('use_structured_output', True),
        enable_refined=refined_enabled
    )


if __name__ == "__main__":
    # 测试代码
    import argparse
    
    parser = argparse.ArgumentParser(description="视频筛选API测试")
    parser.add_argument("video_path", help="视频文件路径")
    parser.add_argument("--prompt", "-p", required=True, help="检测prompt")
    parser.add_argument("--config", "-c", default="config.json", help="配置文件路径")
    parser.add_argument("--refined", "-r", action="store_true", help="启用精细化分析模式")
    
    args = parser.parse_args()
    
    # 创建API实例
    api = create_filter_api_from_config(args.config, enable_refined=args.refined)
    
    # 分析视频
    result = api.analyze_video(args.video_path, args.prompt)
    
    print("\n分析结果:")
    print(f"成功: {result['success']}")
    print(f"分析模式: {result.get('analysis_mode', 'normal')}")
    print(f"满足要求: {'YES' if result['is_satisfied'] else 'NO'}")
    print(f"满足占比: {result['satisfied_ratio']*100:.1f}%")
    print(f"总帧数: {result['total_frames']}")
    print(f"满足帧数: {result['satisfied_frames']}")
    print(f"消息: {result['message']}")
    
    # 如果是精细化分析，输出更多信息
    if result.get('analysis_mode') == 'refined':
        print(f"状态: {result.get('status', '')}")
        print(f"初始满足率: {result.get('initial_ratio', 0.0)*100:.1f}%")
        print(f"迭代次数: {result.get('iterations', 1)}")
        print(f"分析级别: {result.get('analysis_level', '')}")
