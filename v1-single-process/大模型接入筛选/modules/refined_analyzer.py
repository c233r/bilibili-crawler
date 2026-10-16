#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
精细化分析模块
对视频进行多层次分析和处理
"""

import os
import shutil
from typing import List, Dict, Any, Optional, Tuple
from .frame_extractor import FrameExtractor, get_video_duration
from .vlm_analyzer import VLMAnalyzer, AnalysisResult, image_to_base64


class RefinedAnalyzer:
    """
    精细化分析器
    实现多层次视频分析：
    - >70%: 直接保存到output目录
    - 50%-70%: 精细化分析，可多次迭代
    - <50%: 不保存
    """
    
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
        # 保存prompt供后续使用
        if prompt:
            self.prompt = prompt
        
        # 第一步：初始分析（按interval_seconds间隔提取帧）
        initial_result = self._initial_analysis(video_path, self.prompt)
        
        # 判断处理方式
        ratio = initial_result['satisfied_ratio']
        video_name = os.path.basename(video_path)
        
        if ratio > 0.7:
            # >70%: 直接保存整个视频，不进行分段
            return self._handle_high_confidence(video_path, output_dir, initial_result)
        
        elif 0.5 <= ratio <= 0.7:
            # 50%-70%: 精细化分析（可多次迭代）
            return self._handle_medium_confidence(video_path, output_dir, initial_result, self.prompt)
        
        else:
            # <50%: 不保存
            return self._handle_low_confidence(video_path, initial_result)
    
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
        
        print(f"[RefinedAnalyzer] 精细化分析间隔: {refined_interval}秒")
        
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
            
            result = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if result.returncode == 0:
                return result.stdout
            
        except Exception as e:
            print(f"[RefinedAnalyzer] 提取帧失败: {e}")
        
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
                         duration: float) -> List[Tuple[float, float]]:
        """
        扩展片段前后时间（interval_seconds/2）
        
        Args:
            segments: 原始片段列表
            duration: 视频总时长
            
        Returns:
            扩展后的片段列表
        """
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
                print(f"[RefinedAnalyzer] 保存 {len(segments)} 个视频片段")
                
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
                    
                    result = subprocess.run(
                        cmd,
                        shell=False,
                        capture_output=True,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    
                    if result.returncode == 0:
                        print(f"[RefinedAnalyzer] 视频片段已保存: {output_path}")
                        output_paths.append(output_path)
                    else:
                        print(f"[RefinedAnalyzer] 视频片段保存失败: {result.stderr.decode('utf-8', errors='ignore')}")
                
            else:
                # 保存整个视频
                output_path = os.path.join(output_dir, video_name)
                
                # 检查是否已存在
                counter = 1
                while os.path.exists(output_path):
                    output_path = os.path.join(output_dir, f"{name}_{counter}{ext}")
                    counter += 1
                
                shutil.copy2(video_path, output_path)
                print(f"[RefinedAnalyzer] 视频已保存: {output_path}")
                output_paths.append(output_path)
            
            return {
                "video_path": video_path,
                "status": "saved",
                "reason": f"满足率 {analysis_result['satisfied_ratio']*100:.1f}% > 70%",
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
        处理中等置信度视频（50%-70%）- 递归精细化分析
        继续划分直到满足率超出50%-70%范围或时间间隔达到最小（5秒）
        
        Args:
            video_path: 视频文件路径
            output_dir: 输出目录
            initial_result: 初始分析结果
            prompt: 分析提示词
            
        Returns:
            处理结果字典
        """
        print(f"[RefinedAnalyzer] 中等置信度 {initial_result['satisfied_ratio']*100:.1f}%，进行精细化分析")
        
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
        
        print(f"[RefinedAnalyzer] 第{iteration}轮精细化分析:")
        print(f"  找到 {len(segments)} 个满足片段，扩展并合并后为 {len(merged_segments)} 个")
        for i, (start, end) in enumerate(merged_segments):
            print(f"  片段 {i+1}: {start:.1f}s - {end:.1f}s")
        
        # 进行精细化分析（按interval_seconds/2间隔，最短5秒）
        refined_result = self._refined_analysis(video_path, merged_segments, prompt)
        
        final_ratio = refined_result['satisfied_ratio']
        current_interval = refined_result['refined_interval']
        
        print(f"[RefinedAnalyzer] 第{iteration}轮分析完成，满足率: {final_ratio*100:.1f}%")
        
        # 判断是否需要继续迭代
        if final_ratio > 0.7:
            # >70%: 保存
            refined_result['initial_ratio'] = previous_ratio
            refined_result['iterations'] = iteration
            return self._handle_high_confidence(video_path, output_dir, refined_result, merged_segments)
        
        elif final_ratio < 0.5:
            # <50%: 不保存
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
            # 仍在50%-70%之间
            if current_interval <= 5:
                # 时间间隔已达到最小（5秒），无法继续细分
                # 只有满足率>70%才保存，否则丢弃
                print(f"[RefinedAnalyzer] 时间间隔已达最小5秒，无法继续细分")
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
            print(f"[RefinedAnalyzer] 视频已保存到审核目录: {output_path}")
            
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
        处理低置信度视频（<50%）
        
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
        print(f"\n{'='*60}")
        print(f"处理视频: {video_path}")
        print(f"{'='*60}")
        
        result = refined_analyzer.analyze_video(video_path, output_dir, prompt)
        results.append(result)
        
        # 打印结果
        print(f"状态: {result['status']}")
        print(f"原因: {result['reason']}")
        if 'output_path' in result:
            print(f"输出路径: {result['output_path']}")
    
    return results