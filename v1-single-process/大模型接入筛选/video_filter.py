#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
视频筛选工具 - 主程序
根据目录检索视频文件，按指定间隔提取帧图片，使用智谱VLM模型检测是否满足prompt要求

模块结构:
- modules/frame_extractor.py: 视频帧提取
- modules/vlm_analyzer.py: VLM模型调用
- modules/result_handler.py: 结果处理与输出
- modules/video_statistics.py: 视频帧统计与最终判定
- modules/refined_analyzer.py: 精细化分析（50%-70%区间视频的二次分析）
"""

import os
import sys
import json
import argparse

# 导入自定义模块
from modules import (
    FrameExtractor,
    VLMAnalyzer,
    SimpleVLMAnalyzer,
    ResultHandler,
    VideoStatistics,
    RefinedAnalyzer,
    process_videos_with_refined_analysis
)

# 默认配置
DEFAULT_CONFIG = {
    "api_key": "",  # 智谱API Key
    "model": "glm-4v-flash",  # 使用的模型
    "interval_seconds": 60,  # 提取帧的间隔（秒）
    "prompt": "请描述这张图片的内容",  # 默认prompt
    "use_structured_output": True,  # 是否使用结构化输出（LangChain + Pydantic）
    "output_file": "result.json",  # 输出文件
    "statistics_file": "statistics.json",  # 统计结果文件
    "threshold": 0.6,  # satisfied占比阈值（超过60%才算满足要求）
}


def load_config(config_path: str) -> dict:
    """
    加载配置文件
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        配置字典
    """
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            user_config = json.load(f)
            config.update(user_config)
    return config


def process_video(video_path: str, config: dict, 
                  extractor: FrameExtractor, 
                  analyzer: VLMAnalyzer,
                  result_handler: ResultHandler,
                  statistics: VideoStatistics) -> dict:
    """
    处理单个视频
    
    Args:
        video_path: 视频文件路径
        config: 配置字典
        extractor: 帧提取器实例
        analyzer: VLM分析器实例
        result_handler: 结果处理器实例
        statistics: 统计器实例
        
    Returns:
        处理结果字典
    """
    # 创建结果记录
    result = result_handler.create_result(video_path)
    
    print(f"\n处理视频: {video_path}")
    
    # 提取帧（直接返回字节数据，不创建临时文件）
    frames = extractor.extract(video_path)
    
    if not frames:
        result["status"] = "error"
        result["details"].append({"error": "无法提取视频帧"})
        return result
    
    print(f"  提取了 {len(frames)} 帧")
    
    # 分析每一帧
    for frame_data, timestamp in frames:
        # 调用VLM分析（直接传入字节数据）
        success, analysis_result = analyzer.analyze(frame_data, config['prompt'])
        
        # 获取satisfied状态
        satisfied = analysis_result.satisfied if success else False
        
        # 记录结果
        result_handler.add_frame_result(
            result, timestamp, success, str(analysis_result.reason), satisfied
        )
        
        # 添加到统计器
        statistics.add_frame_result(video_path, satisfied, timestamp, str(analysis_result.reason))
        
        # 打印进度
        if success:
            status = "满足条件" if satisfied else "不满足条件"
            print(f"  [{timestamp}s] {status}")
        else:
            print(f"  [{timestamp}s] 分析失败: {str(analysis_result.reason)[:50]}...")
    
    # 完成处理
    result_handler.finalize_result(result)
    result_handler.print_result(result)
    
    # 打印统计结果
    statistics.print_result(video_path)
    
    return result


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='视频筛选工具 - 使用智谱VLM模型检测视频内容',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python video_filter.py "D:\\videos"                    # 使用默认配置
  python video_filter.py "D:\\videos" -p "是否包含猫？"   # 自定义prompt
  python video_filter.py "D:\\videos" -c my_config.json  # 使用自定义配置文件
  python video_filter.py "D:\\videos" -t 0.5             # 设置阈值50%
  python video_filter.py "D:\\videos" --refined          # 使用精细化分析
        """
    )
    parser.add_argument('directory', help='要扫描的视频目录')
    parser.add_argument('--config', '-c', default='config.json', 
                        help='配置文件路径 (默认: config.json)')
    parser.add_argument('--prompt', '-p', help='检测prompt (覆盖配置文件)')
    parser.add_argument('--output', '-o', help='输出文件路径 (覆盖配置文件)')
    parser.add_argument('--statistics', '-s', dest='statistics_file',
                        help='统计结果文件路径 (覆盖配置文件)')
    parser.add_argument('--output-dir', '-d', default='output',
                        help='满足条件视频的输出目录 (默认: output)')
    parser.add_argument('--api-key', '-k', help='智谱API Key (覆盖配置文件)')
    parser.add_argument('--interval', '-i', type=int, 
                        help='帧提取间隔(秒) (覆盖配置文件)')
    parser.add_argument('--model', '-m', help='使用的模型 (覆盖配置文件)')
    parser.add_argument('--threshold', '-t', type=float,
                        help='satisfied占比阈值 (默认0.6，即60%)')
    parser.add_argument('--refined', action='store_true',
                        help='启用精细化分析模式')
    parser.add_argument('--simple', action='store_true',
                        help='使用简单模式（不使用LangChain结构化输出）')
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_config(args.config)
    
    # 命令行参数覆盖配置
    if args.prompt:
        config['prompt'] = args.prompt
    if args.output:
        config['output_file'] = args.output
    if args.statistics_file:
        config['statistics_file'] = args.statistics_file
    if args.api_key:
        config['api_key'] = args.api_key
    if args.interval:
        config['interval_seconds'] = args.interval
    if args.model:
        config['model'] = args.model
    if args.threshold:
        config['threshold'] = args.threshold
    
    # 检查API Key
    if not config['api_key']:
        print("错误: 请在配置文件中设置api_key或通过命令行参数--api-key提供")
        print("提示: 在 config.json 中设置 api_key 字段")
        sys.exit(1)
    
    # 检查目录
    if not os.path.isdir(args.directory):
        print(f"错误: 目录不存在: {args.directory}")
        sys.exit(1)
    
    # 初始化各模块
    print("=" * 60)
    print("视频筛选工具")
    print("=" * 60)
    print(f"扫描目录: {args.directory}")
    print(f"提取间隔: {config['interval_seconds']}秒")
    print(f"使用模型: {config['model']}")
    print(f"结构化输出: {config.get('use_structured_output', True)}")
    print(f"检测Prompt: {config['prompt']}")
    print(f"统计阈值: satisfied占比超过 {config['threshold']*100:.2f}% 才算满足要求")
    
    if args.refined:
        print(f"精细化分析: 启用")
        print(f"输出目录: {args.output_dir}")
    
    print("=" * 60)
    
    # 初始化VLM分析器（根据配置选择）
    if config.get('use_structured_output', True):
        print("使用 LangChain + Pydantic 结构化输出")
        analyzer = VLMAnalyzer(api_key=config['api_key'], model=config['model'])
    else:
        print("使用简单模式（直接SDK调用）")
        analyzer = SimpleVLMAnalyzer(api_key=config['api_key'], model=config['model'])
    
    # 查找视频文件
    video_files = FrameExtractor.find_videos(args.directory)
    
    if not video_files:
        print("未找到视频文件")
        sys.exit(0)
    
    print(f"\n找到 {len(video_files)} 个视频文件")
    print("-" * 60)
    
    # 判断使用哪种模式
    if args.refined:
        # 使用精细化分析模式
        # 在视频搜索目录下创建output文件夹
        output_dir = os.path.join(args.directory, args.output_dir)
        
        print("\n使用精细化分析模式:")
        print("  - >70%: 直接保存到输出目录")
        print("  - 50%-70%: 递归精细化分析，直到满足率>70%或达到最小间隔5秒")
        print("  - <50%: 不保存")
        
        results = process_videos_with_refined_analysis(
            video_files, analyzer, output_dir, config['interval_seconds'], config['prompt']
        )
        
        # 统计结果
        saved_count = sum(1 for r in results if r['status'] == 'saved')
        discarded_count = sum(1 for r in results if r['status'] == 'discarded')
        error_count = sum(1 for r in results if r['status'] == 'error')
        
        print(f"\n{'#'*60}")
        print(f"精细化分析汇总")
        print(f"{'#'*60}")
        print(f"总视频数: {len(results)}")
        print(f"已保存: {saved_count}")
        print(f"已丢弃: {discarded_count}")
        print(f"错误: {error_count}")
        print(f"{'#'*60}")
        
        # 保存详细结果
        with open(config['output_file'], 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n详细结果已保存到: {config['output_file']}")
        
    else:
        # 使用普通模式
        # 初始化帧提取器
        extractor = FrameExtractor(interval_seconds=config['interval_seconds'])
        
        # 初始化结果处理器
        result_handler = ResultHandler(output_file=config['output_file'])
        
        # 初始化统计器
        statistics = VideoStatistics(threshold=config['threshold'])
        
        # 处理每个视频
        for i, video_path in enumerate(video_files, 1):
            print(f"\n[{i}/{len(video_files)}]")
            process_video(video_path, config, extractor, analyzer, result_handler, statistics)
        
        # 保存结果
        result_handler.save()
        
        # 打印汇总
        result_handler.print_summary()
        
        # 打印统计汇总
        statistics.print_summary()
        
        # 保存统计结果
        statistics.save_results(config['statistics_file'])


if __name__ == '__main__':
    main()