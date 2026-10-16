#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
精细化分析模块
对视频进行多层次分析和处理
"""

import os
import sys
import time
import random
import subprocess
import shutil
import threading
from typing import List, Dict, Any, Optional, Tuple
from .frame_extractor import FrameExtractor, get_video_duration
from .vlm_analyzer import VLMAnalyzer, AsyncVLMAnalyzer, AnalysisResult, image_to_base64


class RefinedAnalyzer:
    """
    精细化分析器
    实现多层次视频分析：
    - >HIGH_CONFIDENCE_THRESHOLD: 直接保存到output目录
    - MEDIUM_CONFIDENCE_THRESHOLD-HIGH_CONFIDENCE_THRESHOLD: 精细化分析，可多次迭代
    - <MEDIUM_CONFIDENCE_THRESHOLD: 不保存
    """
    
    # 全局阈值配置
    HIGH_CONFIDENCE_THRESHOLD = 0.8  # 高置信度阈值
    MEDIUM_CONFIDENCE_THRESHOLD = 0.4  # 中等置信度阈值
    
    def __init__(self, analyzer: VLMAnalyzer, interval_seconds: int = 60, prompt: str = ""):
        """
        初始化精细化分析器
        
        Args:
            analyzer: VLM分析器实例
            interval_seconds: 初始分析间隔（秒）
            prompt: 分析提示词
        """
        self.analyzer = analyzer
        self.interval_seconds = interval_seconds
        self.prompt = prompt
    
    def analyze_video(self, video_path: str, output_dir: str, prompt: str = "") -> Dict[str, Any]:
        """
        对单个视频进行完整的精细化分析
        
        Args:
            video_path: 视频文件路径
            output_dir: 输出目录
            prompt: 分析提示词
            
        Returns:
            分析结果字典
        """
        # 保存原始interval_seconds，在分析完成后恢复（保证每个视频独立分析）
        original_interval = self.interval_seconds
        
        try:
            # 保存prompt供后续使用
            if prompt:
                self.prompt = prompt
            
            # 第一步：初始分析（按interval_seconds间隔提取帧）
            initial_result = self._initial_analysis(video_path, self.prompt)
            
            # 判断处理方式
            ratio = initial_result['satisfied_ratio']
            video_name = os.path.basename(video_path)
            
            if ratio > self.HIGH_CONFIDENCE_THRESHOLD:
                # >HIGH_CONFIDENCE_THRESHOLD: 直接保存整个视频，不进行分段
                return self._handle_high_confidence(video_path, output_dir, initial_result)
            
            elif self.MEDIUM_CONFIDENCE_THRESHOLD <= ratio <= self.HIGH_CONFIDENCE_THRESHOLD:
                # MEDIUM_CONFIDENCE_THRESHOLD-HIGH_CONFIDENCE_THRESHOLD: 精细化分析（可多次迭代）
                return self._handle_medium_confidence(video_path, output_dir, initial_result, self.prompt)
            
            else:
                # <MEDIUM_CONFIDENCE_THRESHOLD: 不保存
                return self._handle_low_confidence(video_path, initial_result)
        
        finally:
            # 恢复原始interval_seconds，确保每个视频分析都是独立的
            self.interval_seconds = original_interval
    
    def _initial_analysis(self, video_path: str, prompt: str = "") -> Dict[str, Any]:
        """
        初始分析：按interval_seconds间隔提取帧并分析
        
        Args:
            video_path: 视频文件路径
            prompt: 分析提示词
            
        Returns:
            分析结果字典
        """
        extractor = FrameExtractor(interval_seconds=self.interval_seconds)
        frames = extractor.extract(video_path)
        
        results = []
        satisfied_count = 0
        
        for frame_data, timestamp in frames:
            success, analysis_result = self.analyzer.analyze(frame_data, prompt, timestamp)
            satisfied = analysis_result.satisfied if success else False
            
            results.append({
                "timestamp": timestamp,
                "satisfied": satisfied,
                "reason": analysis_result.reason
            })
            
            if satisfied:
                satisfied_count += 1
        
        total_frames = len(results)
        ratio = satisfied_count / total_frames if total_frames > 0 else 0.0
        
        return {
            "video_path": video_path,
            "total_frames": total_frames,
            "satisfied_frames": satisfied_count,
            "satisfied_ratio": ratio,
            "frame_results": results,
            "analysis_level": "initial"
        }
    
    def _refined_analysis(self, video_path: str, 
                          target_segments: List[Tuple[float, float]],
                          prompt: str = "") -> Dict[str, Any]:
        """
        精细化分析：对指定片段进行更细粒度的分析
        
        Args:
            video_path: 视频文件路径
            target_segments: 需要分析的时间片段列表 [(start, end), ...]
            prompt: 分析提示词
            
        Returns:
            分析结果字典
        """
        # 获取视频时长
        duration = get_video_duration(video_path)
        
        # 计算精细化分析的时间间隔
        # 如果视频时长较短，使用视频时长的一半作为间隔（但不小于5秒）
        if duration and duration < self.interval_seconds:
            # 视频时长小于初始间隔，使用视频时长的一半作为精细化间隔
            refined_interval = max(duration / 2, 5)
        else:
            # 使用原逻辑：interval_seconds//2，最短5秒
            refined_interval = max(self.interval_seconds // 2, 5)
        
        # print(f"[RefinedAnalyzer] 精细化分析间隔: {refined_interval}秒")
        
        all_results = []
        satisfied_count = 0
        
        for start_time, end_time in target_segments:
            # 生成该片段内的采样点
            timestamps = []
            current = start_time
            
            while current <= end_time:
                timestamps.append(current)
                current += refined_interval
            
            # 提取并分析每个时间点的帧
            for timestamp in timestamps:
                if duration and timestamp > duration:
                    continue
                
                # 使用ffmpeg提取单帧
                frame_data = self._extract_single_frame(video_path, timestamp)
                
                if frame_data:
                    success, analysis_result = self.analyzer.analyze(frame_data, prompt, timestamp)
                    satisfied = analysis_result.satisfied if success else False
                    
                    all_results.append({
                        "timestamp": timestamp,
                        "satisfied": satisfied,
                        "reason": analysis_result.reason,
                        "segment": (start_time, end_time)
                    })
                    
                    if satisfied:
                        satisfied_count += 1
        
        total_frames = len(all_results)
        ratio = satisfied_count / total_frames if total_frames > 0 else 0.0
        
        return {
            "video_path": video_path,
            "total_frames": total_frames,
            "satisfied_frames": satisfied_count,
            "satisfied_ratio": ratio,
            "frame_results": all_results,
            "analysis_level": "refined",
            "refined_interval": refined_interval,
            "target_segments": target_segments
        }
    
    def _extract_single_frame(self, video_path: str, timestamp: float) -> Optional[bytes]:
        """
        从视频中提取指定时间点的单帧
        
        Args:
            video_path: 视频文件路径
            timestamp: 时间点（秒）
            
        Returns:
            帧的字节数据，如果失败返回None
        """
        import subprocess
        import sys
        
        try:
            cmd = [
                'ffmpeg', '-ss', str(timestamp), '-i', video_path,
                '-vframes', '1', '-f', 'image2pipe', '-'
            ]
            
            if sys.platform == 'win32':
                result = subprocess.run(
                    cmd,
                    shell=False,
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                result = subprocess.run(
                    cmd,
                    shell=False,
                    capture_output=True
                )
            
            if result.returncode == 0:
                return result.stdout
            
        except Exception as e:
            self._log(f"[RefinedAnalyzer] 提取帧失败: {e}", level='error')
        
        return None
    
    def _find_satisfied_segments(self, frame_results: List[Dict[str, Any]]) -> List[Tuple[float, float]]:
        """
        从帧分析结果中找到连续的satisfied片段
        
        Args:
            frame_results: 帧分析结果列表
            
        Returns:
            连续satisfied片段列表 [(start, end), ...]
        """
        segments = []
        current_segment = None
        
        # 按时间戳排序
        sorted_results = sorted(frame_results, key=lambda x: x['timestamp'])
        
        for frame in sorted_results:
            if frame['satisfied']:
                if current_segment is None:
                    # 开始新片段
                    current_segment = [frame['timestamp'], frame['timestamp']]
                else:
                    # 扩展当前片段
                    current_segment[1] = frame['timestamp']
            else:
                if current_segment is not None:
                    # 结束当前片段
                    segments.append((current_segment[0], current_segment[1]))
                    current_segment = None
        
        # 添加最后一个片段
        if current_segment is not None:
            segments.append((current_segment[0], current_segment[1]))
        
        return segments
    
    def _expand_segments(self, segments: List[Tuple[float, float]], 
                         duration: float, expand_time: float = None) -> List[Tuple[float, float]]:
        """
        扩展片段前后时间
        
        Args:
            segments: 原始片段列表
            duration: 视频总时长
            expand_time: 扩展时间（秒），默认使用 interval_seconds/2
            
        Returns:
            扩展后的片段列表
        """
        if expand_time is None:
            expand_time = self.interval_seconds / 2
        
        expanded = []
        for start, end in segments:
            new_start = max(0, start - expand_time)
            new_end = min(duration, end + expand_time)
            expanded.append((new_start, new_end))
        
        return expanded
    
    def _merge_overlapping_segments(self, segments: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """
        合并重叠的片段
        
        Args:
            segments: 片段列表
            
        Returns:
            合并后的片段列表
        """
        if not segments:
            return []
        
        # 按开始时间排序
        sorted_segments = sorted(segments, key=lambda x: x[0])
        
        merged = [list(sorted_segments[0])]
        for current in sorted_segments[1:]:
            last = merged[-1]
            if current[0] <= last[1]:
                # 重叠，合并
                last[1] = max(last[1], current[1])
            else:
                # 不重叠，添加新片段
                merged.append(list(current))
        
        return [(s, e) for s, e in merged]
    
    def _handle_high_confidence(self, video_path: str, output_dir: str, 
                                analysis_result: Dict[str, Any],
                                segments: List[Tuple[float, float]] = None) -> Dict[str, Any]:
        """
        处理高置信度视频（>70%）
        
        Args:
            video_path: 视频文件路径
            output_dir: 输出目录
            analysis_result: 分析结果
            segments: 需要保存的时间片段列表 [(start, end), ...]，如果为None则保存整个视频
            
        Returns:
            处理结果字典
        """
        import subprocess
        
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        
        video_name = os.path.basename(video_path)
        name, ext = os.path.splitext(video_name)
        output_paths = []
        
        try:
            if segments and len(segments) > 0:
                # 保存视频片段
                # print(f"[RefinedAnalyzer] 保存 {len(segments)} 个视频片段")
                
                for i, (start_time, end_time) in enumerate(segments):
                    # 生成输出文件名：原名称_片段序号_start-end
                    segment_name = f"{name}_{i+1}_{int(start_time)}-{int(end_time)}{ext}"
                    output_path = os.path.join(output_dir, segment_name)
                    
                    # 检查是否已存在
                    counter = 1
                    while os.path.exists(output_path):
                        segment_name = f"{name}_{i+1}_{int(start_time)}-{int(end_time)}_{counter}{ext}"
                        output_path = os.path.join(output_dir, segment_name)
                        counter += 1
                    
                    # 使用ffmpeg裁剪视频片段
                    duration = end_time - start_time
                    cmd = [
                        'ffmpeg', '-ss', str(start_time),
                        '-i', video_path,
                        '-t', str(duration),
                        '-c', 'copy',
                        '-avoid_negative_ts', 'make_zero',
                        output_path,
                        '-y'
                    ]
                    
                    if sys.platform == 'win32':
                        result = subprocess.run(
                            cmd,
                            shell=False,
                            capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )
                    else:
                        result = subprocess.run(
                            cmd,
                            shell=False,
                            capture_output=True
                        )
                    
                    if result.returncode == 0:
                        self._log(f"[RefinedAnalyzer] 视频片段已保存: {output_path}")
                        output_paths.append(output_path)
                    else:
                        self._log(f"[RefinedAnalyzer] 视频片段保存失败: {result.stderr.decode('utf-8', errors='ignore')}")
                
            else:
                # 保存整个视频
                output_path = os.path.join(output_dir, video_name)
                
                # 检查是否已存在
                counter = 1
                while os.path.exists(output_path):
                    output_path = os.path.join(output_dir, f"{name}_{counter}{ext}")
                    counter += 1
                
                shutil.copy2(video_path, output_path)
                # print(f"[RefinedAnalyzer] 视频已保存: {output_path}")
                output_paths.append(output_path)
            
            return {
                "video_path": video_path,
                "status": "saved",
                "reason": f"满足率 {analysis_result['satisfied_ratio']*100:.1f}% > {self.HIGH_CONFIDENCE_THRESHOLD*100:.0f}%",
                "output_paths": output_paths,
                "initial_ratio": analysis_result.get('initial_ratio', analysis_result['satisfied_ratio']),
                "final_ratio": analysis_result['satisfied_ratio'],
                "analysis_level": analysis_result['analysis_level'],
                "segments": segments
            }
        
        except Exception as e:
            return {
                "video_path": video_path,
                "status": "error",
                "reason": f"保存失败: {str(e)}",
                "initial_ratio": analysis_result.get('initial_ratio', analysis_result['satisfied_ratio'])
            }
    
    def _handle_medium_confidence(self, video_path: str, output_dir: str, 
                                  initial_result: Dict[str, Any],
                                  prompt: str = "") -> Dict[str, Any]:
        """
        处理中等置信度视频（{self.MEDIUM_CONFIDENCE_THRESHOLD*100:.0f}%-{self.HIGH_CONFIDENCE_THRESHOLD*100:.0f}%）- 递归精细化分析
        继续划分直到满足率超出{self.MEDIUM_CONFIDENCE_THRESHOLD*100:.0f}%-{self.HIGH_CONFIDENCE_THRESHOLD*100:.0f}%范围或时间间隔达到最小（5秒）
        
        Args:
            video_path: 视频文件路径
            output_dir: 输出目录
            initial_result: 初始分析结果
            prompt: 分析提示词
            
        Returns:
            处理结果字典
        """
        # print(f"[RefinedAnalyzer] 中等置信度 {initial_result['satisfied_ratio']*100:.1f}%，进行精细化分析")
        
        # 获取视频时长
        duration = get_video_duration(video_path)
        
        if duration is None:
            return {
                "video_path": video_path,
                "status": "error",
                "reason": "无法获取视频时长",
                "initial_ratio": initial_result['satisfied_ratio']
            }
        
        # 开始递归精细化分析
        return self._recursive_refined_analysis(
            video_path, output_dir, duration, 
            initial_result['frame_results'], 
            initial_result['satisfied_ratio'],
            iteration=1,
            prompt=prompt
        )
    
    def _recursive_refined_analysis(self, video_path: str, output_dir: str, 
                                    duration: float, frame_results: List[Dict[str, Any]],
                                    previous_ratio: float, iteration: int,
                                    prompt: str = "") -> Dict[str, Any]:
        """
        递归精细化分析
        
        Args:
            video_path: 视频文件路径
            output_dir: 输出目录
            duration: 视频总时长
            frame_results: 当前帧分析结果
            previous_ratio: 上一轮的满足率
            iteration: 当前迭代次数
            prompt: 分析提示词
            
        Returns:
            处理结果字典
        """
        # 找到satisfied片段
        segments = self._find_satisfied_segments(frame_results)
        
        if not segments:
            return {
                "video_path": video_path,
                "status": "discarded",
                "reason": f"精细化分析第{iteration}轮后无满足片段",
                "initial_ratio": previous_ratio,
                "final_ratio": 0.0,
                "analysis_level": f"refined_iteration_{iteration}",
                "iterations": iteration
            }
        
        # 扩展片段前后各interval_seconds/2时间
        expanded_segments = self._expand_segments(segments, duration)
        
        # 合并重叠片段
        merged_segments = self._merge_overlapping_segments(expanded_segments)
        
        # print(f"[RefinedAnalyzer] 第{iteration}轮精细化分析:")
        # print(f"  找到 {len(segments)} 个满足片段，扩展并合并后为 {len(merged_segments)} 个")
        for i, (start, end) in enumerate(merged_segments):
            # print(f"  片段 {i+1}: {start:.1f}s - {end:.1f}s")
            self._log(f"  片段 {i+1}: {start:.1f}s - {end:.1f}s")
        
        # 进行精细化分析（按interval_seconds/2间隔，最短5秒）
        refined_result = self._refined_analysis(video_path, merged_segments, prompt)
        
        final_ratio = refined_result['satisfied_ratio']
        current_interval = refined_result['refined_interval']
        
        # 更新interval_seconds为当前使用的精细化间隔（用于下一轮递归）
        self.interval_seconds = current_interval
        
        # print(f"[RefinedAnalyzer] 第{iteration}轮分析完成，满足率: {final_ratio*100:.1f}%")
        self._log(f"[RefinedAnalyzer] 第{iteration}轮分析完成，满足率: {final_ratio*100:.1f}%")
        
        # 判断是否需要继续迭代
        if final_ratio > self.HIGH_CONFIDENCE_THRESHOLD:
            # >HIGH_CONFIDENCE_THRESHOLD: 保存
            refined_result['initial_ratio'] = previous_ratio
            refined_result['iterations'] = iteration
            return self._handle_high_confidence(video_path, output_dir, refined_result, merged_segments)
        
        elif final_ratio < self.MEDIUM_CONFIDENCE_THRESHOLD:
            # <MEDIUM_CONFIDENCE_THRESHOLD: 不保存
            return {
                "video_path": video_path,
                "status": "discarded",
                "reason": f"精细化分析第{iteration}轮后满足率 {final_ratio*100:.1f}% < 50%",
                "initial_ratio": previous_ratio,
                "final_ratio": final_ratio,
                "analysis_level": f"refined_iteration_{iteration}",
                "iterations": iteration
            }
        
        else:
            # 仍在MEDIUM_CONFIDENCE_THRESHOLD-HIGH_CONFIDENCE_THRESHOLD之间
            if current_interval <= 5:
                # 时间间隔已达到最小（5秒），无法继续细分
                # 只有满足率>HIGH_CONFIDENCE_THRESHOLD才保存，否则丢弃
                # print(f"[RefinedAnalyzer] 时间间隔已达最小5秒，无法继续细分")
                return {
                    "video_path": video_path,
                    "status": "discarded",
                    "reason": f"精细化分析第{iteration}轮后时间间隔已达最小5秒，满足率 {final_ratio*100:.1f}% 未超过70%",
                    "initial_ratio": previous_ratio,
                    "final_ratio": final_ratio,
                    "analysis_level": f"refined_iteration_{iteration}",
                    "iterations": iteration
                }
            else:
                # 继续递归精细化分析
                return self._recursive_refined_analysis(
                    video_path, output_dir, duration,
                    refined_result['frame_results'],
                    previous_ratio,
                    iteration + 1,
                    prompt=prompt
                )
    
    def _handle_needs_review(self, video_path: str, output_dir: str, 
                             analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理需要人工审核的视频（精细化分析后仍在50%-70%）
        
        Args:
            video_path: 视频文件路径
            output_dir: 输出目录
            analysis_result: 分析结果
            
        Returns:
            处理结果字典
        """
        # 创建needs_review子目录
        review_dir = os.path.join(output_dir, "needs_review")
        os.makedirs(review_dir, exist_ok=True)
        
        # 复制视频到审核目录
        try:
            video_name = os.path.basename(video_path)
            output_path = os.path.join(review_dir, video_name)
            
            # 检查是否已存在
            counter = 1
            while os.path.exists(output_path):
                name, ext = os.path.splitext(video_name)
                output_path = os.path.join(review_dir, f"{name}_{counter}{ext}")
                counter += 1
            
            shutil.copy2(video_path, output_path)
            # print(f"[RefinedAnalyzer] 视频已保存到审核目录: {output_path}") 
            
            return {
                "video_path": video_path,
                "status": "needs_review",
                "reason": f"精细化分析后满足率 {analysis_result['satisfied_ratio']*100:.1f}%，需要人工审核",
                "output_path": output_path,
                "initial_ratio": analysis_result.get('initial_ratio', analysis_result['satisfied_ratio']),
                "final_ratio": analysis_result['satisfied_ratio'],
                "analysis_level": analysis_result['analysis_level']
            }
        
        except Exception as e:
            return {
                "video_path": video_path,
                "status": "error",
                "reason": f"保存失败: {str(e)}",
                "initial_ratio": analysis_result.get('initial_ratio', analysis_result['satisfied_ratio'])
            }
    
    def _handle_low_confidence(self, video_path: str, 
                               initial_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理低置信度视频（<{self.MEDIUM_CONFIDENCE_THRESHOLD*100:.0f}%）
        
        Args:
            video_path: 视频文件路径
            initial_result: 初始分析结果
            
        Returns:
            处理结果字典
        """
        return {
            "video_path": video_path,
            "status": "discarded",
            "reason": f"满足率 {initial_result['satisfied_ratio']*100:.1f}% < 50%",
            "initial_ratio": initial_result['satisfied_ratio'],
            "analysis_level": "initial"
        }


def process_videos_with_refined_analysis(video_paths: List[str], analyzer: VLMAnalyzer,
                                         output_dir: str, interval_seconds: int = 60,
                                         prompt: str = "") -> List[Dict[str, Any]]:
    """
    批量处理视频，使用精细化分析
    
    Args:
        video_paths: 视频文件路径列表
        analyzer: VLM分析器实例
        output_dir: 输出目录
        interval_seconds: 初始分析间隔（秒）
        prompt: 分析提示词
        
    Returns:
        所有视频的处理结果列表
    """
    refined_analyzer = RefinedAnalyzer(analyzer, interval_seconds, prompt)
    results = []
    
    for video_path in video_paths:
        # print(f"\n{'='*60}")
        # print(f"处理视频: {video_path}")
        # print(f"{'='*60}")
        
        result = refined_analyzer.analyze_video(video_path, output_dir, prompt)
        results.append(result)
        
        # 打印结果
        # print(f"状态: {result['status']}")
        # print(f"原因: {result['reason']}")
        # if 'output_path' in result:
            # print(f"输出路径: {result['output_path']}")
    
    return results


class AsyncRefinedAnalyzer:
    """
    异步精细化分析器
    实现多层次视频分析，使用异步并发提升吞吐量
    """
    
    HIGH_CONFIDENCE_THRESHOLD = 0.8
    MEDIUM_CONFIDENCE_THRESHOLD = 0.4
    
    def __init__(self, analyzer: AsyncVLMAnalyzer, interval_seconds: int = 60, prompt: str = "", logger=None):
        """
        初始化异步精细化分析器
        
        Args:
            analyzer: 异步VLM分析器实例
            interval_seconds: 初始分析间隔（秒）
            prompt: 分析提示词
            logger: 默认日志记录器，可选
        """
        self.analyzer = analyzer
        self.interval_seconds = interval_seconds
        self.prompt = prompt
        self.default_logger = logger
        self._thread_local = threading.local()
    
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
    
    def _log(self, message: str, level: int = 1):
        """日志辅助方法"""
        if self.logger:
            if level == 0:
                self.logger.debug(message)
            elif level == 1:
                self.logger.info(message)
            elif level == 2:
                self.logger.warning(message)
            else:
                self.logger.error(message)
        else:
            print(message)
    
    async def analyze_video(self, video_path: str, output_dir: str, prompt: str = "") -> Dict[str, Any]:
        """
        对单个视频进行完整的精细化分析（异步）
        
        Args:
            video_path: 视频文件路径
            output_dir: 输出目录
            prompt: 分析提示词
            
        Returns:
            分析结果字典
        """
        import time
        
        start_time = time.time()
        original_interval = self.interval_seconds
        
        try:
            if prompt:
                self.prompt = prompt
            
            initial_result = await self._initial_analysis(video_path, self.prompt)
            
            ratio = initial_result['satisfied_ratio']
            video_name = os.path.basename(video_path)
            
            if ratio > self.HIGH_CONFIDENCE_THRESHOLD:
                # 计算初始分析中的满足片段，分别保存每个片段而非整个视频
                segments = self._find_satisfied_segments(initial_result.get('frame_results', []))
                if segments:
                    dur = get_video_duration(video_path)
                    if dur:
                        segments = self._expand_segments(segments, dur)
                        segments = self._merge_overlapping_segments(segments)
                self._log(f"[AsyncRefinedAnalyzer] 高置信度(ratio={ratio*100:.1f}%)，找到 {len(segments) if segments else 0} 个满足片段", level=1)
                result = self._handle_high_confidence(video_path, output_dir, initial_result, segments)
                result['duration_ms'] = (time.time() - start_time) * 1000
                return result
            
            elif self.MEDIUM_CONFIDENCE_THRESHOLD <= ratio <= self.HIGH_CONFIDENCE_THRESHOLD:
                result = await self._handle_medium_confidence(video_path, output_dir, initial_result, self.prompt)
                result['duration_ms'] = (time.time() - start_time) * 1000
                return result
            
            else:
                result = self._handle_low_confidence(video_path, initial_result)
                result['duration_ms'] = (time.time() - start_time) * 1000
                return result
        
        finally:
            self.interval_seconds = original_interval
    
    async def _initial_analysis(self, video_path: str, prompt: str = "") -> Dict[str, Any]:
        """
        初始分析：并发分析所有帧（批量重试，避免每帧独立重试导致 gather 卡死）
        
        Args:
            video_path: 视频文件路径
            prompt: 分析提示词
            
        Returns:
            分析结果字典
        """
        import asyncio
        
        extractor = FrameExtractor(interval_seconds=self.interval_seconds, logger=self.logger)
        frames = extractor.extract(video_path)
        
        if not frames:
            return {
                "video_path": video_path,
                "total_frames": 0,
                "satisfied_frames": 0,
                "satisfied_ratio": 0.0,
                "frame_results": [],
                "analysis_level": "initial"
            }
        
        # 批量重试分析：每帧只尝试1次，失败帧整批重试
        # 超时时间根据帧数动态计算：每帧预留10秒（并发执行，实际以单帧最慢为准），最低60秒
        BATCH_TIMEOUT = max(60, len(frames) * 10)
        MAX_BATCH_RETRIES = 3
        
        batch_results = {}  # timestamp -> (success, analysis_result)
        pending_frames = [(frame_data, timestamp) for frame_data, timestamp in frames]
        
        for batch_attempt in range(MAX_BATCH_RETRIES):
            if not pending_frames:
                break
            
            if batch_attempt > 0:
                wait_time = random.uniform(3, 5)
                self._log(f"[AsyncRefinedAnalyzer] 初始分析批量重试第{batch_attempt}轮: {len(pending_frames)}帧，等待{wait_time:.1f}秒", level=1)
                await asyncio.sleep(wait_time)
            
            tasks = [
                self.analyzer.analyze(frame_data, prompt, timestamp, max_retries=1)
                for frame_data, timestamp in pending_frames
            ]
            
            try:
                batch_start = time.monotonic()
                results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=BATCH_TIMEOUT)
                elapsed = time.monotonic() - batch_start
                if batch_attempt > 0:
                    self._log(f"[AsyncRefinedAnalyzer] 初始分析批量重试完成: 成功={sum(1 for r in results if r[0])}/{len(results)}，耗时{elapsed:.1f}秒", level=1)
            except asyncio.TimeoutError:
                self._log(f"[AsyncRefinedAnalyzer] 初始分析批量超时({BATCH_TIMEOUT}秒)，返回部分结果", level=2)
                results = []
            
            new_pending = []
            for (success, analysis_result), (frame_data, timestamp) in zip(results, pending_frames):
                if success:
                    batch_results[timestamp] = (success, analysis_result)
                else:
                    new_pending.append((frame_data, timestamp))
            
            pending_frames = new_pending
        
        frame_results = []
        satisfied_count = 0
        
        for frame_data, timestamp in frames:
            if timestamp in batch_results:
                success, analysis_result = batch_results[timestamp]
            else:
                success = False
                analysis_result = AnalysisResult(satisfied=False, reason="所有批量重试均失败", confidence=0.0)
            
            satisfied = analysis_result.satisfied if success else False
            
            frame_results.append({
                "timestamp": timestamp,
                "satisfied": satisfied,
                "reason": analysis_result.reason
            })
            
            if satisfied:
                satisfied_count += 1
        
        total_frames = len(frame_results)
        ratio = satisfied_count / total_frames if total_frames > 0 else 0.0
        
        return {
            "video_path": video_path,
            "total_frames": total_frames,
            "satisfied_frames": satisfied_count,
            "satisfied_ratio": ratio,
            "frame_results": frame_results,
            "analysis_level": "initial"
        }
    
    async def _refined_analysis(self, video_path: str, 
                                target_segments: List[Tuple[float, float]],
                                prompt: str = "", refined_interval: float = None) -> Dict[str, Any]:
        """
        精细化分析：对指定片段进行更细粒度的并发分析
        
        Args:
            video_path: 视频文件路径
            target_segments: 需要分析的时间片段列表 [(start, end), ...]
            prompt: 分析提示词
            refined_interval: 精细化分析间隔（可选，自动计算）
            
        Returns:
            分析结果字典
        """
        import asyncio
        
        duration = get_video_duration(video_path)
        
        if refined_interval is not None:
            interval = refined_interval
        elif duration and duration < self.interval_seconds:
            interval = max(duration / 2, 5)
        else:
            interval = max(self.interval_seconds // 2, 5)
        
        self._log(f"[AsyncRefinedAnalyzer] 精细化分析间隔: {interval}秒", level=1)
        
        all_frame_data = []
        
        for start_time, end_time in target_segments:
            timestamps = []
            current = start_time
            while current <= end_time:
                timestamps.append(current)
                current += interval
            
            for timestamp in timestamps:
                if duration and timestamp > duration:
                    continue
                
                frame_data = self._extract_single_frame(video_path, timestamp)
                if frame_data:
                    all_frame_data.append((frame_data, timestamp, (start_time, end_time)))
        
        if not all_frame_data:
            return {
                "video_path": video_path,
                "total_frames": 0,
                "satisfied_frames": 0,
                "satisfied_ratio": 0.0,
                "frame_results": [],
                "analysis_level": "refined",
                "refined_interval": interval,
                "target_segments": target_segments
            }
        
        # 批量重试分析：避免每个帧独立重试导致 gather 卡死
        # 第一轮：所有帧并发分析（每个帧只尝试1次，不独立重试）
        # 后续轮：只重试失败的帧
        # 超时时间根据帧数动态计算（Semaphore(3)限制并发，耗时与帧数成正比）
        BATCH_TIMEOUT = max(60, len(all_frame_data) * 10)  # 每批超时
        MAX_BATCH_RETRIES = 3  # 最大批量重试次数
        
        batch_results = {}  # timestamp -> (success, analysis_result)
        pending_frames = [(frame_data, timestamp, segment) for frame_data, timestamp, segment in all_frame_data]
        
        for batch_attempt in range(MAX_BATCH_RETRIES):
            if not pending_frames:
                break
            
            if batch_attempt > 0:
                wait_time = random.uniform(3, 5)
                self._log(f"[AsyncRefinedAnalyzer] 批量重试第{batch_attempt}轮: {len(pending_frames)}帧，等待{wait_time:.1f}秒", level=1)
                await asyncio.sleep(wait_time)
            
            tasks = [
                self.analyzer.analyze(frame_data, prompt, timestamp, max_retries=1)
                for frame_data, timestamp, segment in pending_frames
            ]
            
            try:
                batch_start = time.monotonic()
                results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=BATCH_TIMEOUT)
                elapsed = time.monotonic() - batch_start
                
                if batch_attempt > 0:
                    self._log(f"[AsyncRefinedAnalyzer] 批量重试完成: 成功={sum(1 for r in results if r[0])}/{len(results)}，耗时{elapsed:.1f}秒", level=1)
            except asyncio.TimeoutError:
                self._log(f"[AsyncRefinedAnalyzer] 批量分析超时({BATCH_TIMEOUT}秒)，返回部分结果", level=2)
                results = []
            
            new_pending = []
            for (success, analysis_result), (frame_data, timestamp, segment) in zip(results, pending_frames):
                if success:
                    batch_results[timestamp] = (success, analysis_result)
                else:
                    new_pending.append((frame_data, timestamp, segment))
            
            pending_frames = new_pending
        
        # 处理最终结果
        all_results = []
        satisfied_count = 0
        
        for frame_data, timestamp, segment in all_frame_data:
            if timestamp in batch_results:
                success, analysis_result = batch_results[timestamp]
            else:
                success = False
                analysis_result = AnalysisResult(satisfied=False, reason="所有批量重试均失败", confidence=0.0)
            
            satisfied = analysis_result.satisfied if success else False
            
            all_results.append({
                "timestamp": timestamp,
                "satisfied": satisfied,
                "reason": analysis_result.reason,
                "segment": segment
            })
            
            if satisfied:
                satisfied_count += 1
        
        total_frames = len(all_results)
        ratio = satisfied_count / total_frames if total_frames > 0 else 0.0
        
        return {
            "video_path": video_path,
            "total_frames": total_frames,
            "satisfied_frames": satisfied_count,
            "satisfied_ratio": ratio,
            "frame_results": all_results,
            "analysis_level": "refined",
            "refined_interval": interval,
            "target_segments": target_segments
        }
    
    def _extract_single_frame(self, video_path: str, timestamp: float) -> Optional[bytes]:
        """从视频中提取指定时间点的单帧（复用父类方法）"""
        import subprocess
        
        try:
            cmd = [
                'ffmpeg', '-ss', str(timestamp), '-i', video_path,
                '-vframes', '1', '-f', 'image2pipe', '-'
            ]
            
            if sys.platform == 'win32':
                result = subprocess.run(
                    cmd, shell=False, capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                result = subprocess.run(
                    cmd, shell=False, capture_output=True
                )
            
            if result.returncode == 0:
                return result.stdout
                
        except Exception as e:
            self._log(f"[AsyncRefinedAnalyzer] 提取帧失败: {e}", level=3)
        
        return None
    
    def _find_satisfied_segments(self, frame_results: List[Dict[str, Any]]) -> List[Tuple[float, float]]:
        """找到连续的satisfied片段（复用父类逻辑）"""
        segments = []
        current_segment = None
        
        sorted_results = sorted(frame_results, key=lambda x: x['timestamp'])
        
        for frame in sorted_results:
            if frame['satisfied']:
                if current_segment is None:
                    current_segment = [frame['timestamp'], frame['timestamp']]
                else:
                    current_segment[1] = frame['timestamp']
            else:
                if current_segment is not None:
                    segments.append((current_segment[0], current_segment[1]))
                    current_segment = None
        
        if current_segment is not None:
            segments.append((current_segment[0], current_segment[1]))
        
        return segments
    
    def _expand_segments(self, segments: List[Tuple[float, float]], 
                         duration: float, expand_time: float = None) -> List[Tuple[float, float]]:
        """扩展片段前后时间（复用父类逻辑）"""
        if expand_time is None:
            expand_time = self.interval_seconds / 2
        
        expanded = []
        for start, end in segments:
            new_start = max(0, start - expand_time)
            new_end = min(duration, end + expand_time)
            expanded.append((new_start, new_end))
        
        return expanded
    
    def _merge_overlapping_segments(self, segments: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """合并重叠的片段（复用父类逻辑）"""
        if not segments:
            return []
        
        sorted_segments = sorted(segments, key=lambda x: x[0])
        merged = [list(sorted_segments[0])]
        
        for current in sorted_segments[1:]:
            last = merged[-1]
            if current[0] <= last[1]:
                last[1] = max(last[1], current[1])
            else:
                merged.append(list(current))
        
        return [(s, e) for s, e in merged]
    
    def _handle_high_confidence(self, video_path: str, output_dir: str, 
                                analysis_result: Dict[str, Any],
                                segments: List[Tuple[float, float]] = None) -> Dict[str, Any]:
        """处理高置信度视频（复用父类逻辑）"""
        import subprocess
        
        os.makedirs(output_dir, exist_ok=True)
        video_name = os.path.basename(video_path)
        name, ext = os.path.splitext(video_name)
        output_paths = []
        
        try:
            if segments and len(segments) > 0:
                for i, (start_time, end_time) in enumerate(segments):
                    segment_name = f"{name}_{i+1}_{int(start_time)}-{int(end_time)}{ext}"
                    output_path = os.path.join(output_dir, segment_name)
                    
                    counter = 1
                    while os.path.exists(output_path):
                        segment_name = f"{name}_{i+1}_{int(start_time)}-{int(end_time)}_{counter}{ext}"
                        output_path = os.path.join(output_dir, segment_name)
                        counter += 1
                    
                    duration = end_time - start_time
                    cmd = [
                        'ffmpeg', '-ss', str(start_time), '-i', video_path,
                        '-t', str(duration), '-c', 'copy',
                        '-avoid_negative_ts', 'make_zero', output_path, '-y'
                    ]
                    
                    if sys.platform == 'win32':
                        result = subprocess.run(cmd, shell=False, capture_output=True,
                                              creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        result = subprocess.run(cmd, shell=False, capture_output=True)
                    
                    if result.returncode == 0:
                        output_paths.append(output_path)
                    
            else:
                output_path = os.path.join(output_dir, video_name)
                counter = 1
                while os.path.exists(output_path):
                    output_path = os.path.join(output_dir, f"{name}_{counter}{ext}")
                    counter += 1
                
                shutil.copy2(video_path, output_path)
                output_paths.append(output_path)
            
            return {
                "video_path": video_path,
                "status": "saved",
                "reason": f"满足率 {analysis_result['satisfied_ratio']*100:.1f}% > {self.HIGH_CONFIDENCE_THRESHOLD*100:.0f}%",
                "output_paths": output_paths,
                "initial_ratio": analysis_result.get('initial_ratio', analysis_result['satisfied_ratio']),
                "final_ratio": analysis_result['satisfied_ratio'],
                "analysis_level": analysis_result['analysis_level'],
                "segments": segments
            }
        
        except Exception as e:
            return {
                "video_path": video_path,
                "status": "error",
                "reason": f"保存失败: {str(e)}",
                "initial_ratio": analysis_result.get('initial_ratio', analysis_result['satisfied_ratio'])
            }
    
    async def _handle_medium_confidence(self, video_path: str, output_dir: str, 
                                        initial_result: Dict[str, Any],
                                        prompt: str = "") -> Dict[str, Any]:
        """处理中等置信度视频（异步）"""
        self._log(f"[AsyncRefinedAnalyzer] 中等置信度 {initial_result['satisfied_ratio']*100:.1f}%，进行精细化分析", level=1)
        
        duration = get_video_duration(video_path)
        
        if duration is None:
            return {
                "video_path": video_path,
                "status": "error",
                "reason": "无法获取视频时长",
                "initial_ratio": initial_result['satisfied_ratio']
            }
        
        return await self._recursive_refined_analysis(
            video_path, output_dir, duration, 
            initial_result['frame_results'], 
            initial_result['satisfied_ratio'],
            iteration=1,
            prompt=prompt
        )
    
    async def _recursive_refined_analysis(self, video_path: str, output_dir: str, 
                                          duration: float, frame_results: List[Dict[str, Any]],
                                          previous_ratio: float, iteration: int,
                                          prompt: str = "",
                                          recursion_interval: float = None) -> Dict[str, Any]:
        """递归精细化分析（异步）- 对每个片段独立判断"""
        # 重新获取视频总时长（避免递归时传入片段时长导致扩展范围错误）
        video_duration = get_video_duration(video_path)
        if video_duration is None:
            video_duration = duration  # 降级使用传入值
        
        # 最大递归深度保护（最多20轮）
        MAX_RECURSION = 100
        if iteration > MAX_RECURSION:
            self._log(f"[AsyncRefinedAnalyzer] 递归深度已达上限({MAX_RECURSION})，丢弃", level=1)
            return {
                "video_path": video_path,
                "status": "discarded",
                "reason": f"递归深度已达上限({MAX_RECURSION}轮)，仍无法判断",
                "initial_ratio": previous_ratio,
                "final_ratio": previous_ratio,
                "analysis_level": f"refined_iteration_{iteration}",
                "iterations": iteration,
                "saved_segment_count": 0,
                "output_paths": []
            }
        
        segments = self._find_satisfied_segments(frame_results)
        
        if not segments:
            return {
                "video_path": video_path,
                "status": "discarded",
                "reason": f"精细化分析第{iteration}轮后无满足片段",
                "initial_ratio": previous_ratio,
                "final_ratio": 0.0,
                "analysis_level": f"refined_iteration_{iteration}",
                "iterations": iteration,
                "saved_segment_count": 0,
                "output_paths": []
            }
        
        # 使用传入的递归间隔，如果不传则使用实例默认值
        if recursion_interval is None:
            recursion_interval = self.interval_seconds
        
        # 根据当前递归间隔计算扩展时间（递归时逐步缩小扩展范围）
        current_expand_time = max(recursion_interval / 2, 2.5)
        expanded_segments = self._expand_segments(segments, video_duration, expand_time=current_expand_time)
        merged_segments = self._merge_overlapping_segments(expanded_segments)
        
        self._log(f"[AsyncRefinedAnalyzer] 第{iteration}轮精细化分析:", level=1)
        self._log(f"  找到 {len(segments)} 个满足片段，扩展({current_expand_time:.1f}秒)并合并后为 {len(merged_segments)} 个", level=1)
        
        saved_segments = []
        all_output_paths = []
        
        self._log(f"[AsyncRefinedAnalyzer] 第{iteration}轮：共 {len(merged_segments)} 个候选片段", level=1)
        
        for idx, segment in enumerate(merged_segments):
            start_time, end_time = segment
            segment_duration = end_time - start_time
            
            self._log(f"[AsyncRefinedAnalyzer] 分析片段 {idx+1}/{len(merged_segments)}: {int(start_time)}-{int(end_time)}秒", level=1)
            
            if segment_duration <= 5:
                self._log(f"[AsyncRefinedAnalyzer] 片段过短({segment_duration:.1f}秒)，直接丢弃", level=1)
                continue
            
            # 如果当前间隔 >= 片段时长，先做精细化分析提取更多帧
            if recursion_interval >= segment_duration:
                self._log(f"[AsyncRefinedAnalyzer] 当前间隔({recursion_interval}秒) >= 片段时长({segment_duration:.1f}秒)，进行精细化分析", level=1)
                refined_interval = max(recursion_interval // 2, 5)
                segment_refined_result = await self._refined_analysis(
                    video_path, [segment], prompt, refined_interval
                )
                
                seg_ratio = segment_refined_result['satisfied_ratio']
                if seg_ratio > self.HIGH_CONFIDENCE_THRESHOLD:
                    self._log(f"[AsyncRefinedAnalyzer] 精细化分析后片段满足条件({seg_ratio*100:.1f}%)，保存", level=1)
                    saved_segments.append(segment)
                elif seg_ratio < self.MEDIUM_CONFIDENCE_THRESHOLD:
                    self._log(f"[AsyncRefinedAnalyzer] 精细化分析后片段不满足条件({seg_ratio*100:.1f}%)，丢弃", level=1)
                else:
                    # 精细化后仍在中等区间，递归继续
                    self._log(f"[AsyncRefinedAnalyzer] 精细化后仍在中等区间({seg_ratio*100:.1f}%)，继续递归", level=1)
                    sub_refined_result = await self._recursive_refined_analysis(
                        video_path, output_dir, segment_duration,
                        segment_refined_result.get('frame_results', []),
                        seg_ratio, iteration=iteration+1, prompt=prompt,
                        recursion_interval=refined_interval
                    )
                    if sub_refined_result['status'] == 'saved':
                        saved_segments.append(segment)
                        if sub_refined_result.get('output_paths'):
                            all_output_paths.extend(sub_refined_result['output_paths'])
                    else:
                        self._log(f"[AsyncRefinedAnalyzer] 递归后片段仍不满足条件，丢弃", level=1)
                continue
            
            segment_frame_results = self._extract_segment_frames(frame_results, start_time, end_time)
            
            if not segment_frame_results:
                self._log(f"[AsyncRefinedAnalyzer] 片段无满足帧，进行精细化分析", level=1)
                refined_interval = max(recursion_interval // 2, 5)
                segment_refined_result = await self._refined_analysis(
                    video_path, [segment], prompt, refined_interval
                )
                
                if segment_refined_result['satisfied_ratio'] > self.HIGH_CONFIDENCE_THRESHOLD:
                    self._log(f"[AsyncRefinedAnalyzer] 精细化分析后片段满足条件，保存", level=1)
                    saved_segments.append(segment)
                else:
                    self._log(f"[AsyncRefinedAnalyzer] 精细化分析后片段仍不满足条件，丢弃", level=1)
                continue
            
            segment_satisfied_count = sum(1 for r in segment_frame_results if r.get('satisfied', False))
            segment_ratio = segment_satisfied_count / len(segment_frame_results)
            
            self._log(f"[AsyncRefinedAnalyzer] 片段满足率: {segment_ratio*100:.1f}%", level=1)
            
            if segment_ratio > self.HIGH_CONFIDENCE_THRESHOLD:
                self._log(f"[AsyncRefinedAnalyzer] 片段满足条件，保存", level=1)
                saved_segments.append(segment)
            elif segment_ratio < self.MEDIUM_CONFIDENCE_THRESHOLD:
                self._log(f"[AsyncRefinedAnalyzer] 片段不满足条件，丢弃", level=1)
            else:
                # 中等置信度区间：继续递归分析
                if recursion_interval <= 5:
                    self._log(f"[AsyncRefinedAnalyzer] 片段置信度中等，间隔已达最小({recursion_interval}秒)，丢弃", level=1)
                else:
                    refined_interval = max(recursion_interval // 2, 5)
                    self._log(f"[AsyncRefinedAnalyzer] 片段置信度中等，继续递归分析(间隔:{refined_interval}秒)", level=1)
                    
                    segment_refined_result = await self._recursive_refined_analysis(
                        video_path, output_dir, segment_duration,
                        segment_frame_results, segment_ratio,
                        iteration=iteration+1, prompt=prompt,
                        recursion_interval=refined_interval
                    )
                    
                    if segment_refined_result['status'] == 'saved':
                        self._log(f"[AsyncRefinedAnalyzer] 递归后片段满足条件，保存", level=1)
                        saved_segments.append(segment)
                        if segment_refined_result.get('output_paths'):
                            all_output_paths.extend(segment_refined_result['output_paths'])
                    else:
                        self._log(f"[AsyncRefinedAnalyzer] 递归后片段仍不满足条件，丢弃", level=1)
        
        if saved_segments:
            video_name = os.path.basename(video_path)
            name, ext = os.path.splitext(video_name)
            
            # 确保输出目录存在
            os.makedirs(output_dir, exist_ok=True)
            
            for i, (start_time, end_time) in enumerate(saved_segments):
                segment_name = f"{name}_{i+1}_{int(start_time)}-{int(end_time)}{ext}"
                output_path = os.path.join(output_dir, segment_name)
                
                counter = 1
                while os.path.exists(output_path):
                    segment_name = f"{name}_{i+1}_{int(start_time)}-{int(end_time)}_{counter}{ext}"
                    output_path = os.path.join(output_dir, segment_name)
                    counter += 1
                
                seg_duration = end_time - start_time
                cmd = [
                    'ffmpeg', '-ss', str(start_time), '-i', video_path,
                    '-t', str(seg_duration), '-c', 'copy',
                    '-avoid_negative_ts', 'make_zero', output_path, '-y'
                ]
                
                try:
                    if sys.platform == 'win32':
                        result = subprocess.run(cmd, shell=False, capture_output=True,
                                              creationflags=subprocess.CREATE_NO_WINDOW,
                                              timeout=60)
                    else:
                        result = subprocess.run(cmd, shell=False, capture_output=True,
                                              timeout=60)
                    
                    if result.returncode == 0:
                        all_output_paths.append(output_path)
                        self._log(f"[AsyncRefinedAnalyzer] 视频片段已保存: {output_path}", level=1)
                    else:
                        stderr = result.stderr.decode('utf-8', errors='ignore') if result.stderr else ''
                        self._log(f"[AsyncRefinedAnalyzer] 片段裁剪失败: {segment_name}, ffmpeg返回码={result.returncode}, 错误: {stderr[:200]}", level=1)
                except subprocess.TimeoutExpired:
                    self._log(f"[AsyncRefinedAnalyzer] 片段裁剪超时: {segment_name}", level=1)
                except Exception as e:
                    self._log(f"[AsyncRefinedAnalyzer] 片段裁剪异常: {segment_name}, {str(e)}", level=1)
        
        if all_output_paths:
            return {
                "video_path": video_path,
                "status": "saved",
                "reason": f"精细化分析第{iteration}轮后，保存了 {len(all_output_paths)} 个片段",
                "initial_ratio": previous_ratio,
                "final_ratio": len(saved_segments) / len(merged_segments) if merged_segments else 0.0,
                "analysis_level": f"refined_iteration_{iteration}",
                "iterations": iteration,
                "saved_segment_count": len(all_output_paths),
                "output_paths": all_output_paths,
                "segments": saved_segments
            }
        elif saved_segments:
            return {
                "video_path": video_path,
                "status": "saved",
                "reason": f"精细化分析第{iteration}轮后，{len(saved_segments)} 个片段满足条件，但所有片段裁剪失败",
                "initial_ratio": previous_ratio,
                "final_ratio": len(saved_segments) / len(merged_segments) if merged_segments else 0.0,
                "analysis_level": f"refined_iteration_{iteration}",
                "iterations": iteration,
                "saved_segment_count": len(saved_segments),
                "output_paths": [],
                "segments": saved_segments
            }
        else:
            return {
                "video_path": video_path,
                "status": "discarded",
                "reason": f"精细化分析第{iteration}轮后所有片段均不满足条件",
                "initial_ratio": previous_ratio,
                "final_ratio": 0.0,
                "analysis_level": f"refined_iteration_{iteration}",
                "iterations": iteration,
                "saved_segment_count": 0,
                "output_paths": []
            }
    
    def _extract_segment_frames(self, frame_results: List[Dict[str, Any]], 
                                start_time: float, end_time: float) -> List[Dict[str, Any]]:
        """提取指定时间范围内的帧结果"""
        return [r for r in frame_results if start_time <= r.get('timestamp', 0) <= end_time]
    
    def _handle_low_confidence(self, video_path: str, 
                               initial_result: Dict[str, Any]) -> Dict[str, Any]:
        """处理低置信度视频（复用父类逻辑）"""
        return {
            "video_path": video_path,
            "status": "discarded",
            "reason": f"满足率 {initial_result['satisfied_ratio']*100:.1f}% < 50%",
            "initial_ratio": initial_result['satisfied_ratio'],
            "analysis_level": "initial"
        }