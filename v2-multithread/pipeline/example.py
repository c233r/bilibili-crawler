"""
流水线使用示例
演示如何使用多线程并行下载和分析流水线
"""
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(__file__))

from pipeline import VideoPipeline


def example_1_basic_download():
    """示例1: 基础下载功能（不使用筛选）"""
    print("\n" + "="*60)
    print("示例1: 基础下载功能")
    print("="*60)
    
    # 创建流水线实例（2个下载线程，3个分析线程）
    with VideoPipeline(num_download_workers=2, num_analyze_workers=3) as pipeline:
        
        # 方式1: 手动添加视频任务
        videos = [
            {'bvid': 'BV1GJ411x7h7', 'title': 'B站视频示例1'},
            {'bvid': 'BV1ap4y1k7ZF', 'title': 'B站视频示例2'},
            {'bvid': 'BV1uJ411476M', 'title': 'B站视频示例3'},
        ]
        pipeline.add_download_tasks(videos)
        
        # 等待所有任务完成
        pipeline.wait_until_complete()
        
        # 打印最终统计信息
        pipeline.print_statistics()


def example_2_search_and_download():
    """示例2: 搜索并下载视频"""
    print("\n" + "="*60)
    print("示例2: 搜索并下载视频")
    print("="*60)
    
    # 创建流水线实例
    with VideoPipeline(num_download_workers=2, num_analyze_workers=3) as pipeline:
        
        # 搜索关键词并下载前5个视频
        keyword = input("请输入搜索关键词: ").strip()
        max_count = int(input("请输入要下载的视频数量: ").strip())
        
        pipeline.search_and_add_videos(keyword, max_count=max_count)
        
        # 等待所有任务完成
        pipeline.wait_until_complete()
        
        # 打印最终统计信息
        pipeline.print_statistics()


def example_3_search_up_and_download():
    """示例3: 搜索UP主并下载其视频"""
    print("\n" + "="*60)
    print("示例3: 搜索UP主并下载其视频")
    print("="*60)
    
    # 创建流水线实例
    with VideoPipeline(num_download_workers=2, num_analyze_workers=3) as pipeline:
        
        # 搜索UP主并下载其视频
        up_name = input("请输入UP主名称: ").strip()
        max_count = int(input("请输入要下载的视频数量: ").strip())
        
        pipeline.search_up_and_add_videos(up_name, max_count=max_count)
        
        # 等待所有任务完成
        pipeline.wait_until_complete()
        
        # 打印最终统计信息
        pipeline.print_statistics()


def example_4_with_filter():
    """示例4: 带筛选功能的下载"""
    print("\n" + "="*60)
    print("示例4: 带筛选功能的下载")
    print("="*60)
    
    # 创建流水线实例
    with VideoPipeline(num_download_workers=2, num_analyze_workers=3) as pipeline:
        
        # 设置筛选提示词
        filter_prompt = input("请输入筛选提示词: ").strip()
        use_refined = input("是否使用精细化分析? (y/n): ").strip().lower() == 'y'
        
        pipeline.set_filter_prompt(filter_prompt, use_refined=use_refined)
        
        # 搜索并下载视频
        keyword = input("请输入搜索关键词: ").strip()
        max_count = int(input("请输入要下载的视频数量: ").strip())
        
        pipeline.search_and_add_videos(keyword, max_count=max_count)
        
        # 等待所有任务完成
        pipeline.wait_until_complete()
        
        # 打印最终统计信息
        pipeline.print_statistics()
        
        # 获取最终报告
        report = pipeline.get_final_report()
        print(f"\n[最终报告]")
        print(f"  总任务数: {report['total_tasks']}")
        print(f"  完成任务: {report['completed_tasks']}")
        print(f"  失败任务: {report['failed_tasks']}")
        print(f"  成功率: {report['success_rate']:.1f}%")
        print(f"  下载成功: {report['downloaded_count']}")
        print(f"  分析完成: {report['analyzed_count']}")
        print(f"  满足条件: {report['satisfied_count']}")
        print(f"  满足率: {report['satisfaction_rate']:.1f}%")
        print(f"  运行时间: {report['elapsed_time']:.1f} 秒")


def example_5_custom_configuration():
    """示例5: 自定义配置"""
    print("\n" + "="*60)
    print("示例5: 自定义配置")
    print("="*60)
    
    # 创建流水线实例（自定义线程数量）
    with VideoPipeline(num_download_workers=3, num_analyze_workers=5) as pipeline:
        
        # 设置筛选提示词（使用精细化分析）
        pipeline.set_filter_prompt(
            "视频是否包含编程教程内容",
            use_refined=True
        )
        
        # 手动添加视频任务
        videos = [
            {'bvid': 'BV1GJ411x7h7', 'title': 'Python编程教程'},
            {'bvid': 'BV1ap4y1k7ZF', 'title': 'Java编程入门'},
            {'bvid': 'BV1uJ411476M', 'title': 'C++基础教程'},
            {'bvid': 'BV1xx411c7mD', 'title': 'JavaScript高级'},
            {'bvid': 'BV1yy411c7mE', 'title': 'Go语言实战'},
        ]
        pipeline.add_download_tasks(videos)
        
        # 等待所有任务完成
        pipeline.wait_until_complete()
        
        # 打印最终统计信息
        pipeline.print_statistics()


def main():
    """主函数"""
    print("="*60)
    print("      B站视频下载与分析流水线 - 使用示例")
    print("="*60)
    print("1. 基础下载功能（不使用筛选）")
    print("2. 搜索并下载视频")
    print("3. 搜索UP主并下载其视频")
    print("4. 带筛选功能的下载")
    print("5. 自定义配置")
    print("0. 退出")
    print("="*60)
    
    while True:
        choice = input("\n请选择示例 (0-5): ").strip()
        
        if choice == '0':
            print("退出程序")
            break
        elif choice == '1':
            example_1_basic_download()
        elif choice == '2':
            example_2_search_and_download()
        elif choice == '3':
            example_3_search_up_and_download()
        elif choice == '4':
            example_4_with_filter()
        elif choice == '5':
            example_5_custom_configuration()
        else:
            print("无效选项，请重新选择")


if __name__ == '__main__':
    main()