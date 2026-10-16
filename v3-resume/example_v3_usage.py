"""
V3 持久化版 - 完整调用示例

展示如何在实际爬虫流程中集成数据库持久化和断点续传
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.control.pipeline_main import VideoPipeline
from sql import get_database, CheckpointManager


def example_basic_usage():
    """基础用法：创建并启动带有持久化的流水线"""
    print("="*60)
    print("示例1: 基础用法 - 启动新的持久化流水线")
    print("="*60)
    
    pipeline = VideoPipeline(total_workers=5)
    
    pipeline.start_run(
        keyword="猫咪视频",
        search_type='video',
        target_count=10,
        use_refined=True,
        filter_prompt="画面中是否有可爱的猫咪",
        force_new=True,
    )
    
    print(f"当前Run ID: {pipeline.current_run.run_id}")
    print(f"关键词: {pipeline.current_run.keyword}")
    print(f"状态: {pipeline.current_run.status}")
    
    pipeline.stop()


def example_resume_run():
    """断点续传：恢复之前未完成的任务"""
    print("\n" + "="*60)
    print("示例2: 断点续传 - 恢复未完成的任务")
    print("="*60)
    
    db = get_database()
    cpm = CheckpointManager(db)
    
    run = cpm.start_or_resume(
        keyword="猫咪视频",
        force_new=False,
    )
    
    if cpm.was_resumed:
        print(f"✅ 成功恢复运行: {run.run_id}")
        
        unfinished = cpm.get_unfinished_videos(run.run_id)
        print(f"发现 {len(unfinished)} 个未完成视频:")
        for video in unfinished:
            print(f"  - {video.bvid}: {video.title} ({video.status})")
        
        pipeline = VideoPipeline(total_workers=5)
        pipeline.start_run(keyword="猫咪视频", force_new=False)
        
        pipeline.stop()
    else:
        print(f"🔄 创建新运行: {run.run_id}")


def example_query_history():
    """查询历史：查看数据库中的运行记录"""
    print("\n" + "="*60)
    print("示例3: 查询历史 - 查看数据库统计")
    print("="*60)
    
    db = get_database()
    cpm = CheckpointManager(db)
    
    stats = db.get_stats()
    print(f"数据库统计:")
    print(f"  总运行次数: {stats['total_runs']}")
    print(f"  总视频数: {stats['total_videos']}")
    print(f"  总分析结果: {stats['total_results']}")
    print(f"  数据库大小: {stats['db_size_mb']:.2f} MB")
    
    recent_runs = cpm.get_recent_runs(limit=5)
    print(f"\n最近5次运行:")
    for run in recent_runs:
        run_stats = cpm.get_statistics(run.run_id)
        print(f"  [{run.run_id[:16]}...] {run.keyword}")
        print(f"     状态: {run_stats['status']}, 完成: {run_stats['completed']}, "
              f"失败: {run_stats['failed']}, 满足: {run_stats['satisfied_count']}")


def example_lineage_export():
    """数据血缘：导出某运行的数据血缘信息"""
    print("\n" + "="*60)
    print("示例4: 数据血缘 - 导出分析结果的血缘信息")
    print("="*60)
    
    db = get_database()
    cpm = CheckpointManager(db)
    
    recent_runs = cpm.get_recent_runs(limit=3)
    for run in recent_runs:
        lineage = cpm.export_lineage(run.run_id)
        if lineage:
            print(f"\n运行 {run.run_id[:16]}... 的数据血缘 ({len(lineage)}条):")
            for item in lineage[:2]:
                print(f"  来源: {item['source']['bvid']}")
                print(f"  处理模式: {item['processing']['analysis_mode']}")
                print(f"  提示词: {item['processing']['prompt_used'][:30]}...")
                print(f"  生成时间: {item['output']['generated_at']}")


def example_integrated_flow():
    """完整流程：模拟一次完整的爬虫+分析+持久化流程"""
    print("\n" + "="*60)
    print("示例5: 完整流程 - 模拟爬虫流程集成")
    print("="*60)
    
    pipeline = VideoPipeline(total_workers=3)
    
    pipeline.start_run(
        keyword="测试完整流程",
        target_count=3,
        force_new=True,
    )
    
    print(f"启动运行: {pipeline.current_run.run_id}")
    
    videos = [
        {"bvid": "BVTEST001", "title": "测试视频1"},
        {"bvid": "BVTEST002", "title": "测试视频2"},
        {"bvid": "BVTEST003", "title": "测试视频3"},
    ]
    
    added, failed = pipeline.add_download_tasks(videos)
    print(f"添加任务: 成功 {added} 个, 失败 {len(failed)} 个")
    
    time.sleep(2)
    
    db = get_database()
    stats = db.get_stats()
    print(f"\n数据库当前状态:")
    print(f"  视频数: {stats['total_videos']}")
    
    pipeline.stop()
    
    run_stats = pipeline.checkpoint_manager.get_statistics(pipeline.current_run.run_id)
    print(f"\n运行统计:")
    print(f"  总视频: {run_stats['total']}")
    print(f"  完成: {run_stats['completed']}")
    print(f"  失败: {run_stats['failed']}")


def main():
    print("\nV3 持久化版 - 完整调用示例")
    print("="*60)
    
    try:
        example_basic_usage()
        example_resume_run()
        example_query_history()
        example_lineage_export()
        example_integrated_flow()
        
        print("\n" + "="*60)
        print("所有示例执行完成! ✅")
        print("="*60)
        
    except Exception as e:
        print(f"\n执行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
