#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
视频筛选API接口
提供简单的接口供爬虫调用，实现视频下载后的自动筛选功能
支持普通分析和精细化分析两种模式
"""

import os
import sys
import threading

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules import (
    FrameExtractor,
    VLMAnalyzer,
    SimpleVLMAnalyzer,
    AsyncVLMAnalyzer,
    VideoStatistics,
    AnalysisResult,
    RefinedAnalyzer,
    AsyncRefinedAnalyzer
)


class VideoFilterAPI:
    """
    视频筛选API
    提供简单的接口供爬虫调用
    支持普通分析和精细化分析两种模式
    """
    
    def __init__(self, api_key: str, model: str = "glm-4v-flash", 
                 interval_seconds: int = 60, threshold: float = 0.6,
                 use_structured_output: bool = True, enable_refined: bool = False,
                 logger=None):
        """
        初始化筛选API
        
        Args:
            api_key: 智谱API Key
            model: 使用的模型
            interval_seconds: 帧提取间隔（秒）
            threshold: satisfied占比阈值
            use_structured_output: 是否使用结构化输出
            enable_refined: 是否启用精细化分析模式
            logger: 默认日志记录器，可选
        """
        self.api_key = api_key
        self.model = model
        self.interval_seconds = interval_seconds
        self.threshold = threshold
        self.use_structured_output = use_structured_output
        self.enable_refined = enable_refined
        self.default_logger = logger
        
        self._thread_local = threading.local()
        
        # 初始化组件
        self.extractor = FrameExtractor(interval_seconds=interval_seconds, logger=logger)
        
        if use_structured_output:
            self.analyzer = VLMAnalyzer(api_key=api_key, model=model)
        else:
            self.analyzer = SimpleVLMAnalyzer(api_key=api_key, model=model)
        
        # 异步分析器（按需初始化）
        self.async_analyzer = None
        
        # 精细化分析器（按需初始化）
        self.refined_analyzer = None
    
    @property
    def logger(self):
        """获取当前线程的日志记录器"""
        if hasattr(self._thread_local, 'logger'):
            return self._thread_local.logger
        return self.default_logger
    
    @logger.setter
    def logger(self, value):
        """设置当前线程的日志记录器"""
        self._thread_local.logger = value
    
    def set_logger(self, logger):
        """设置当前线程的日志记录器"""
        self.logger = logger
        if self.extractor:
            self.extractor.logger = logger
        if self.async_analyzer:
            self.async_analyzer.logger = logger
        if self.refined_analyzer:
            self.refined_analyzer.logger = logger
    
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
            # print(f"[VLM分析] 正在分析视频: {os.path.basename(video_path)}")
            
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
            
            # print(f"[VLM分析] 提取了 {len(frames)} 帧")
            
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
                # print(f"[VLM分析] [{timestamp}s] {status}")
            
            # 计算结果
            result = statistics.calculate_result(video_path)
            
            is_satisfied = result.get("is_satisfied", False)
            ratio = result.get("satisfied_ratio", 0.0)
            total_frames = result.get("total_frames", 0)
            satisfied_frames = result.get("satisfied_frames", 0)
            
            message = f"分析完成: satisfied占比 {ratio*100:.1f}%, 阈值 {self.threshold*100:.1f}% -> {'YES' if is_satisfied else 'NO'}"
            # print(f"[VLM分析] {message}")
            self.logger.info(message)
            
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
            # print(f"\n{'='*60}")
            # print(f"[精细化分析] 正在分析视频: {os.path.basename(video_path)}")
            # print(f"{'='*60}")
            # print("精细化分析策略:")
            # print("  - >70%: 直接保存")
            # print("  - 50%-70%: 递归精细化分析")
            # print("  - <50%: 不保存")
            
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
            # print(f"[精细化分析] 状态: {status}")
            # print(f"[精细化分析] 原因: {reason}")
            # print(f"[精细化分析] 初始满足率: {initial_ratio*100:.1f}%")
            # print(f"[精细化分析] 最终满足率: {final_ratio*100:.1f}%")
            # print(f"[精细化分析] 结果: {'YES' if is_satisfied else 'NO'}")
            # print(f"{'='*60}")
            
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
            # print(f"[精细化分析] 分析错误: {str(e)}")
            self.logger.error(f"精细化分析错误: {str(e)}")
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


    async def analyze_video_async(self, video_path: str, prompt: str) -> dict:
        """
        异步分析单个视频（并发处理帧，提升吞吐量）
        
        Args:
            video_path: 视频文件路径
            prompt: 检测prompt
            
        Returns:
            分析结果字典
        """
        import asyncio
        import time
        
        start_time = time.time()
        
        if not os.path.exists(video_path):
            return {
                "success": False,
                "is_satisfied": False,
                "satisfied_ratio": 0.0,
                "total_frames": 0,
                "satisfied_frames": 0,
                "message": f"视频文件不存在: {video_path}",
                "analysis_mode": "async_normal",
                "duration_ms": 0
            }
        
        try:
            if self.logger:
                self.logger.info(f"[AsyncVLM分析] 正在分析视频: {os.path.basename(video_path)}")
            else:
                print(f"[AsyncVLM分析] 正在分析视频: {os.path.basename(video_path)}")
            
            # 提取帧
            extract_start = time.time()
            frames = self.extractor.extract(video_path)
            extract_duration = (time.time() - extract_start) * 1000
            
            if not frames:
                return {
                    "success": False,
                    "is_satisfied": False,
                    "satisfied_ratio": 0.0,
                    "total_frames": 0,
                    "satisfied_frames": 0,
                    "message": "无法提取视频帧",
                    "analysis_mode": "async_normal",
                    "duration_ms": (time.time() - start_time) * 1000
                }
            
            if self.logger:
                self.logger.info(f"[AsyncVLM分析] 提取了 {len(frames)} 帧 (耗时: {extract_duration:.2f}ms)")
            else:
                print(f"[AsyncVLM分析] 提取了 {len(frames)} 帧 (耗时: {extract_duration:.2f}ms)")
            
            # 初始化异步分析器
            if not self.async_analyzer:
                self.async_analyzer = AsyncVLMAnalyzer(api_key=self.api_key, model=self.model, logger=self.logger)
            
            # 创建统计器
            statistics = VideoStatistics(threshold=self.threshold)
            
            # 并发分析所有帧
            tasks = [
                self.async_analyzer.analyze(frame_data, prompt, timestamp)
                for frame_data, timestamp in frames
            ]
            
            if self.logger:
                self.logger.info(f"[AsyncVLM分析] 开始并发分析 {len(tasks)} 帧...")
            else:
                print(f"[AsyncVLM分析] 开始并发分析 {len(tasks)} 帧...")
            
            api_start = time.time()
            results = await asyncio.gather(*tasks)
            api_duration = (time.time() - api_start) * 1000
            
            if self.logger:
                self.logger.info(f"[AsyncVLM分析] 并发分析完成 (API耗时: {api_duration:.2f}ms)")
            else:
                print(f"[AsyncVLM分析] 并发分析完成 (API耗时: {api_duration:.2f}ms)")
            
            # 处理结果
            frame_results = []
            for (success, analysis_result), (frame_data, timestamp) in zip(results, frames):
                satisfied = analysis_result.satisfied if success else False
                
                statistics.add_frame_result(
                    video_path, satisfied, timestamp, 
                    str(analysis_result.reason) if success else "分析失败"
                )
                
                status = "满足条件" if satisfied else "不满足条件"
                frame_results.append((timestamp, status))
            
            # 计算结果
            result = statistics.calculate_result(video_path)
            
            is_satisfied = result.get("is_satisfied", False)
            ratio = result.get("satisfied_ratio", 0.0)
            total_frames = result.get("total_frames", 0)
            satisfied_frames = result.get("satisfied_frames", 0)
            
            total_duration = (time.time() - start_time) * 1000
            
            message = f"异步分析完成: satisfied占比 {ratio*100:.1f}%, 阈值 {self.threshold*100:.1f}% -> {'YES' if is_satisfied else 'NO'}, " \
                      f"总耗时: {total_duration:.2f}ms (提取: {extract_duration:.2f}ms, API: {api_duration:.2f}ms)"
            if self.logger:
                self.logger.info(f"[AsyncVLM分析] {message}")
            else:
                print(f"[AsyncVLM分析] {message}")
            
            return {
                "success": True,
                "is_satisfied": is_satisfied,
                "satisfied_ratio": ratio,
                "total_frames": total_frames,
                "satisfied_frames": satisfied_frames,
                "message": message,
                "analysis_mode": "async_normal",
                "duration_ms": total_duration,
                "extract_duration_ms": extract_duration,
                "api_duration_ms": api_duration,
                "frame_count": len(frames)
            }
            
        except Exception as e:
            import traceback
            total_duration = (time.time() - start_time) * 1000
            # print(f"[AsyncVLM分析] 分析错误: {traceback.format_exc()} (耗时: {total_duration:.2f}ms)")
            self.logger.error(f"异步分析错误: {str(e)}")

            return {
                "success": False,
                "is_satisfied": False,
                "satisfied_ratio": 0.0,
                "total_frames": 0,
                "satisfied_frames": 0,
                "message": f"异步分析错误: {str(e)} (耗时: {total_duration:.2f}ms)",
                "analysis_mode": "async_normal",
                "duration_ms": total_duration
            }

    async def analyze_video_refined_async(self, video_path: str, prompt: str) -> dict:
        """
        异步精细化分析单个视频（并发处理帧，提升吞吐量）
        
        Args:
            video_path: 视频文件路径
            prompt: 检测prompt
            
        Returns:
            分析结果字典，包含:
                - success: bool, 是否分析成功
                - is_satisfied: bool, 视频是否满足要求
                - satisfied_ratio: float, satisfied占比
                - total_frames: int, 总帧数
                - satisfied_frames: int, 满足条件帧数
                - message: str, 结果消息
                - analysis_mode: str, 分析模式（'async_refined'）
                - status: str, 精细化分析状态（'saved', 'discarded', 'error', 'needs_review'）
                - output_paths: list, 保存的文件路径列表
                - duration_ms: float, 总耗时（毫秒）
        """
        import asyncio
        import time
        
        start_time = time.time()
        
        if not os.path.exists(video_path):
            return {
                "success": False,
                "is_satisfied": False,
                "satisfied_ratio": 0.0,
                "total_frames": 0,
                "satisfied_frames": 0,
                "message": f"视频文件不存在: {video_path}",
                "analysis_mode": "async_refined",
                "duration_ms": 0
            }
        
        try:
            if self.logger:
                self.logger.info(f"[AsyncRefined分析] 正在分析视频: {os.path.basename(video_path)}")
            else:
                print(f"[AsyncRefined分析] 正在分析视频: {os.path.basename(video_path)}")
            
            if not self.async_analyzer:
                self.async_analyzer = AsyncVLMAnalyzer(api_key=self.api_key, model=self.model, logger=self.logger)
            
            if not self.refined_analyzer:
                self.refined_analyzer = AsyncRefinedAnalyzer(
                    analyzer=self.async_analyzer,
                    interval_seconds=self.interval_seconds,
                    prompt=prompt,
                    logger=self.logger
                )
            
            output_dir = os.path.join(os.path.dirname(video_path), "refined_output")
            
            result = await self.refined_analyzer.analyze_video(video_path, output_dir, prompt)
            
            total_duration = result.get('duration_ms', (time.time() - start_time) * 1000)
            
            status = result.get('status', 'discarded')
            is_satisfied = status == 'saved'
            
            message = f"异步精细化分析完成: status={status}, " \
                      f"满足率 {result.get('final_ratio', result.get('initial_ratio', 0))*100:.1f}%, " \
                      f"总耗时: {total_duration:.2f}ms"
            if self.logger:
                self.logger.info(f"[AsyncRefined分析] {message}")
            else:
                print(f"[AsyncRefined分析] {message}")
            
            return {
                "success": True,
                "is_satisfied": is_satisfied,
                "satisfied_ratio": result.get('final_ratio', result.get('initial_ratio', 0)),
                "total_frames": result.get('total_frames', 0),
                "satisfied_frames": result.get('satisfied_frames', 0),
                "message": message,
                "analysis_mode": "async_refined",
                "status": status,
                "output_paths": result.get('output_paths', []),
                "analysis_level": result.get('analysis_level', 'initial'),
                "iterations": result.get('iterations', 1),
                "duration_ms": total_duration
            }
            
        except Exception as e:
            import traceback
            total_duration = (time.time() - start_time) * 1000
            # print(f"[AsyncRefined分析] 分析错误: {traceback.format_exc()} (耗时: {total_duration:.2f}ms)")
            self.logger.error(f"异步精细化分析错误: {str(e)}")
            return {
                "success": False,
                "is_satisfied": False,
                "satisfied_ratio": 0.0,
                "total_frames": 0,
                "satisfied_frames": 0,
                "message": f"异步精细化分析错误: {str(e)} (耗时: {total_duration:.2f}ms)",
                "analysis_mode": "async_refined",
                "duration_ms": total_duration
            }


def create_filter_api_from_config(config_path: str = "config.json", enable_refined: bool = None, logger=None) -> VideoFilterAPI:
    """
    从配置文件创建筛选API实例
    
    Args:
        config_path: 配置文件路径
        enable_refined: 是否启用精细化分析（None表示使用配置文件中的设置）
        logger: 日志记录器，可选
        
    Returns:
        VideoFilterAPI实例
    """
    import json
    
    default_config = {
        "api_key": "",
        "model": "",
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
        enable_refined=refined_enabled,
        logger=logger
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
    
    # print("\n分析结果:")
    # print(f"成功: {result['success']}")
    # print(f"分析模式: {result.get('analysis_mode', 'normal')}")
    # print(f"满足要求: {'YES' if result['is_satisfied'] else 'NO'}")
    # print(f"满足占比: {result['satisfied_ratio']*100:.1f}%")
    # print(f"总帧数: {result['total_frames']}")
    # print(f"满足帧数: {result['satisfied_frames']}")
    # print(f"消息: {result['message']}")
    
    # 如果是精细化分析，输出更多信息
    # if result.get('analysis_mode') == 'refined':
    #     print(f"状态: {result.get('status', '')}")
    #     print(f"初始满足率: {result.get('initial_ratio', 0.0)*100:.1f}%")
    #     print(f"迭代次数: {result.get('iterations', 1)}")
    #     print(f"分析级别: {result.get('analysis_level', '')}")
