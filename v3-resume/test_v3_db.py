"""
V3 持久化版 - 测试脚本

验证数据库初始化、表创建、断点续传等功能
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sql import (
    get_database, CheckpointManager,
    RunStatus, VideoStatus, SearchType, AnalysisMode,
)


def test_database_init():
    print("="*60)
    print("测试1: 数据库初始化")
    print("="*60)
    
    db = get_database()
    stats = db.get_stats()
    print(f"数据库统计: {stats}")
    print(f"数据库路径: {db.db_path}")
    print("数据库初始化成功!")


def test_run_operations():
    print("\n" + "="*60)
    print("测试2: Run记录操作")
    print("="*60)
    
    db = get_database()
    cpm = CheckpointManager(db)
    
    run = cpm.start_or_resume(
        keyword="测试关键词",
        search_type=SearchType.VIDEO,
        target_count=5,
        use_refined=True,
        filter_prompt="测试Prompt",
        total_workers=3,
        force_new=True,
    )
    print(f"创建Run: {run.run_id}")
    print(f"关键词: {run.keyword}")
    print(f"状态: {run.status}")
    
    found = cpm._find_resumable_run("测试关键词")
    assert found is None, "force_new=True 不应找到可恢复的run"
    print("force_new测试通过")
    
    run2 = cpm.start_or_resume(
        keyword="测试关键词2",
        force_new=True,
    )
    print(f"创建Run2: {run2.run_id}")
    
    stats = cpm.get_statistics(run2.run_id)
    print(f"统计信息: {stats}")
    
    cpm.finish(run2.run_id)
    print(f"标记完成后状态: {cpm._find_resumable_run('测试关键词2')}")
    print("Run操作测试通过!")


def test_video_operations():
    print("\n" + "="*60)
    print("测试3: Video记录操作")
    print("="*60)
    
    db = get_database()
    cpm = CheckpointManager(db)
    
    run = cpm.start_or_resume(
        keyword="视频测试",
        force_new=True,
    )
    
    cpm.on_video_discovered(run.run_id, "BV12345678901", "测试视频1", page=1)
    cpm.on_video_discovered(run.run_id, "BV12345678902", "测试视频2", page=1)
    print("视频发现记录已保存")
    
    cpm.on_video_downloading(run.run_id, "BV12345678901")
    cpm.on_video_downloaded(run.run_id, "BV12345678901", "/path/to/video1.mp4")
    cpm.on_video_analyzing(run.run_id, "BV12345678901")
    cpm.on_video_completed(run.run_id, "BV12345678901")
    print("视频状态流转测试通过")
    
    cpm.on_video_failed(run.run_id, "BV12345678902", "下载失败")
    print("视频失败记录测试通过")
    
    stats = cpm.get_statistics(run.run_id)
    print(f"统计: {stats}")
    
    cpm.finish(run.run_id)
    print("Video操作测试通过!")


def test_analysis_result():
    print("\n" + "="*60)
    print("测试4: 分析结果与数据血缘")
    print("="*60)
    
    db = get_database()
    cpm = CheckpointManager(db)
    
    run = cpm.start_or_resume(
        keyword="血缘测试",
        force_new=True,
    )
    
    cpm.on_video_discovered(run.run_id, "BVLINEAGE001", "血缘测试视频", page=1)
    cpm.on_video_downloaded(run.run_id, "BVLINEAGE001", "/path/to/lineage.mp4")
    
    result_id = cpm.save_analysis_result(
        run_id=run.run_id,
        bvid="BVLINEAGE001",
        satisfied=True,
        analysis_mode=AnalysisMode.REFINED,
        prompt_used="测试Prompt",
        confidence=0.95,
        segment_paths=["/path/seg1.mp4", "/path/seg2.mp4"],
        source_frame_count=100,
        satisfied_frame_count=80,
        duration_ms=5000.0,
        api_duration_ms=4500.0,
    )
    print(f"保存分析结果ID: {result_id}")
    
    lineage = cpm.export_lineage(run.run_id)
    print(f"数据血缘: {lineage}")
    
    assert len(lineage) == 1
    assert lineage[0]['pipeline_version'] == 'v3.0'
    assert lineage[0]['source']['bvid'] == 'BVLINEAGE001'
    assert lineage[0]['processing']['analysis_mode'] == 'refined'
    print("数据血缘测试通过!")
    
    cpm.finish(run.run_id)


def test_checkpoint():
    print("\n" + "="*60)
    print("测试5: 断点保存与加载")
    print("="*60)
    
    db = get_database()
    cpm = CheckpointManager(db)
    
    run = cpm.start_or_resume(
        keyword="断点测试",
        force_new=True,
    )
    
    cpm.save_progress(run.run_id, {"page": 3, "satisfied_count": 2})
    cpm.save_pending_items(run.run_id, [{"bvid": "BV1", "title": "暂存视频1"}])
    print("断点数据已保存")
    
    loaded_progress = cpm.load_progress(run.run_id)
    loaded_items = cpm.load_pending_items(run.run_id)
    
    assert loaded_progress == {"page": 3, "satisfied_count": 2}
    assert loaded_items == [{"bvid": "BV1", "title": "暂存视频1"}]
    print("断点加载测试通过!")
    
    cpm.finish(run.run_id)


def test_resume():
    print("\n" + "="*60)
    print("测试6: 断点续传恢复")
    print("="*60)
    
    db = get_database()
    cpm = CheckpointManager(db)
    
    run = cpm.start_or_resume(
        keyword="续传测试",
        force_new=True,
    )
    
    cpm.on_video_discovered(run.run_id, "BVRESUME001", "续传视频1")
    cpm.on_video_discovered(run.run_id, "BVRESUME002", "续传视频2")
    cpm.on_video_downloading(run.run_id, "BVRESUME001")
    
    resumed = cpm.start_or_resume("续传测试")
    assert resumed.run_id == run.run_id
    print(f"成功恢复相同关键词的run: {resumed.run_id}")
    
    unfinished = cpm.get_unfinished_videos(run.run_id)
    assert len(unfinished) == 2
    print(f"发现 {len(unfinished)} 个未完成视频")
    
    cpm.finish(run.run_id)
    print("断点续传恢复测试通过!")


def main():
    print("\nV3 持久化版 - 数据库测试套件")
    print("="*60)
    
    try:
        test_database_init()
        test_run_operations()
        test_video_operations()
        test_analysis_result()
        test_checkpoint()
        test_resume()
        
        print("\n" + "="*60)
        print("所有测试通过! ✅")
        print("="*60)
        
        final_stats = get_database().get_stats()
        print(f"\n最终数据库统计: {final_stats}")
        
    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
