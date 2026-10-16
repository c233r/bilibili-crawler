"""
V3 持久化版 - 断点续传管理器

负责保存流水线运行时状态，支持重启后恢复未完成任务继续处理。

核心流程:
    启动时 -> 检查是否有未完成的 run
           -> 有: 加载断点，恢复未完成视频，继续处理
           -> 无: 创建新 run，正常开始

    运行时 -> 定期保存进度快照（checkpoint）
           -> 每个视频状态变更实时写入数据库
"""

import uuid
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from .database import DatabaseManager
from .models import (
    Run, Video, AnalysisResult, Checkpoint, UploadRecord,
    RunStatus, VideoStatus, UploadStatus, SearchType, AnalysisMode,
    LineageBuilder,
)
from .repos import RunRepo, VideoRepo, ResultRepo, CheckpointRepo, UploadRepo


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class CheckpointManager:
    """
    断点续传管理器

    使用示例:
        db = get_database()
        cpm = CheckpointManager(db)

        # 启动或恢复
        run = cpm.start_or_resume("美食", target_count=10, total_workers=5)

        # 定时保存进度
        cpm.save_progress(run.run_id, {"page": 5, "satisfied_count": 3})

        # 视频状态变更
        cpm.on_video_status(run.run_id, "BVxxx", VideoStatus.DOWNLOADED, download_path="/path/to/video.mp4")

        # 完成
        cpm.finish(run.run_id)
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.was_resumed = False

    # ─── 启动 / 恢复 ─────────────────────────────────────────

    def start_or_resume(
        self,
        keyword: str,
        search_type: str = SearchType.VIDEO,
        target_count: int = 0,
        use_refined: bool = False,
        filter_prompt: str = "",
        total_workers: int = 5,
        force_new: bool = False,
    ) -> Run:
        """
        启动新运行或恢复未完成的运行

        Args:
            keyword: 搜索关键词
            search_type: 'video' | 'up'
            target_count: 目标下载数量
            use_refined: 是否精细化分析
            filter_prompt: 筛选Prompt
            total_workers: 线程总数
            force_new: 是否强制创建新运行（不检查断点）

        Returns:
            Run 对象
        """
        if not force_new:
            # 检查是否有同名关键词的未完成任务
            run = self._find_resumable_run(keyword)
            if run:
                print(f"[断点续传] 发现未完成的运行记录: {run.run_id}")
                print(f"  - 关键词: {run.keyword}")
                print(f"  - 开始时间: {run.started_at}")
                print(f"  - 筛选Prompt: {run.filter_prompt[:30] if run.filter_prompt else '无'}...")
                # 恢复运行时将状态改为 running
                RunRepo.update_status(self.db, run.run_id, RunStatus.RUNNING)
                run.status = RunStatus.RUNNING
                self.was_resumed = True
                return run

        # 创建新运行
        self.was_resumed = False
        run = Run(
            run_id=self._generate_run_id(),
            keyword=keyword,
            search_type=search_type,
            target_count=target_count,
            use_refined=use_refined,
            filter_prompt=filter_prompt,
            total_workers=total_workers,
            started_at=_now(),
            status=RunStatus.RUNNING,
        )
        RunRepo.create(self.db, run)
        print(f"[数据库] 创建新运行记录: {run.run_id}")
        return run

    def _find_resumable_run(self, keyword: str) -> Optional[Run]:
        """查找可恢复的运行（相同关键词 + RUNNING状态 + 有未完成任务）"""
        unfinished = RunRepo.list_unfinished(self.db)
        for run in unfinished:
            if run.keyword == keyword:
                # 有未完成的视频或待上传的记录才真正可恢复
                pending = VideoRepo.list_unfinished(self.db, run.run_id)
                if pending:
                    return run
                # 检查是否有待上传的记录
                uploads = UploadRepo.get_pending(self.db, run.run_id)
                if uploads:
                    return run
        return None

    def get_unfinished_videos(self, run_id: str) -> List[Video]:
        """获取未完成的视频列表（用于断点续传）"""
        return VideoRepo.list_unfinished(self.db, run_id)

    # ─── 进度保存 ────────────────────────────────────────────

    def save_progress(self, run_id: str, progress: dict):
        """
        保存进度快照

        Args:
            progress: 自定义进度数据，如 {"page": 5, "satisfied_count": 3, "pending_items": [...]}
        """
        CheckpointRepo.save(self.db, run_id, "progress", progress)

    def load_progress(self, run_id: str) -> Optional[dict]:
        """加载进度快照"""
        return CheckpointRepo.load(self.db, run_id, "progress")

    def save_pending_items(self, run_id: str, pending_items: List[dict]):
        """保存队列满时暂存的视频"""
        CheckpointRepo.save(self.db, run_id, "pending_items", {"items": pending_items})

    def load_pending_items(self, run_id: str) -> List[dict]:
        """加载暂存的视频"""
        data = CheckpointRepo.load(self.db, run_id, "pending_items")
        return (data or {}).get("items", [])

    # ─── 视频状态变更 ───────────────────────────────────────

    def on_video_discovered(
        self,
        run_id: str,
        bvid: str,
        title: str,
        page: int = 1,
    ):
        """视频被发现（搜索到但尚未下载）"""
        video = Video(
            run_id=run_id,
            bvid=bvid,
            title=title,
            page=page,
            status=VideoStatus.PENDING,
        )
        VideoRepo.batch_create(self.db, [video])

    def on_video_downloading(self, run_id: str, bvid: str):
        VideoRepo.update_status(self.db, run_id, bvid, VideoStatus.DOWNLOADING)

    def on_video_downloaded(self, run_id: str, bvid: str, download_path: str):
        VideoRepo.update_status(
            self.db, run_id, bvid,
            VideoStatus.DOWNLOADED,
            download_path=download_path,
        )

    def on_video_analyzing(self, run_id: str, bvid: str):
        VideoRepo.update_status(self.db, run_id, bvid, VideoStatus.ANALYZING)

    def on_video_completed(self, run_id: str, bvid: str):
        VideoRepo.update_status(self.db, run_id, bvid, VideoStatus.COMPLETED)

    def on_video_failed(self, run_id: str, bvid: str, error_message: str = ""):
        VideoRepo.update_status(
            self.db, run_id, bvid,
            VideoStatus.FAILED,
            error_message=error_message,
        )

    # ─── 分析结果 ────────────────────────────────────────────

    def save_analysis_result(
        self,
        bvid: str,
        satisfied: bool,
        analysis_mode: str,
        prompt_used: str,
        run_id: str = None,
        video_id: int = None,
        confidence: float = 0.0,
        result_detail: dict = None,
        segment_paths: list = None,
        source_frame_count: int = 0,
        satisfied_frame_count: int = 0,
        duration_ms: float = 0.0,
        api_duration_ms: float = 0.0,
    ) -> int:
        """
        保存分析结果（自动构建数据血缘）

        Args:
            bvid: 视频ID
            satisfied: 是否满足条件
            analysis_mode: 分析模式
            prompt_used: 使用的提示词
            run_id: 运行ID（可选，用于自动查找video_id）
            video_id: 视频记录ID（可选，可通过run_id+bvid自动查找）
            ...

        Returns:
            结果记录的自增 ID
        """
        if run_id and video_id is None:
            video = VideoRepo.get_by_bvid(self.db, run_id, bvid)
            video_id = video.id if video else 0
        elif video_id is None:
            video_id = 0
        
        video_lineage = {}
        if run_id:
            video = VideoRepo.get_by_bvid(self.db, run_id, bvid)
            video_lineage = LineageBuilder.for_video(video) if video else {}

        lineage = LineageBuilder.for_analysis(
            video_lineage=video_lineage,
            analysis_mode=analysis_mode,
            prompt_used=prompt_used,
            source_frame_count=source_frame_count,
            satisfied_frame_count=satisfied_frame_count,
        )

        result = AnalysisResult(
            video_id=video_id,
            run_id=run_id,
            bvid=bvid,
            satisfied=satisfied,
            confidence=confidence,
            analysis_mode=analysis_mode,
            prompt_used=prompt_used,
            result_detail=json.dumps(result_detail, ensure_ascii=False) if result_detail else "",
            segment_paths=json.dumps(segment_paths, ensure_ascii=False) if segment_paths else "",
            source_frame_count=source_frame_count,
            satisfied_frame_count=satisfied_frame_count,
            duration_ms=duration_ms,
            api_duration_ms=api_duration_ms,
            lineage=json.dumps(lineage, ensure_ascii=False),
        )
        return ResultRepo.create(self.db, result)

    # ─── 上传记录 ────────────────────────────────────────────

    def on_upload_pending(self, run_id: str, bvid: str, title: str, video_path: str) -> int:
        """
        记录待上传的视频
        
        Args:
            run_id: 运行ID
            bvid: 视频BV号
            title: 视频标题
            video_path: 视频文件路径
        
        Returns:
            上传记录的自增ID
        """
        record = UploadRecord(
            run_id=run_id,
            bvid=bvid,
            title=title,
            video_path=video_path,
            status=UploadStatus.PENDING,
        )
        return UploadRepo.create(self.db, record)

    def on_upload_success(self, record_id: int):
        """
        标记上传成功
        
        Args:
            record_id: 上传记录ID
        """
        UploadRepo.update_status(self.db, record_id, UploadStatus.SUCCESS)
        # 上传成功后可以删除记录，保留痕迹以免重复推送
        UploadRepo.delete(self.db, record_id)

    def on_upload_failed(self, record_id: int, error_message: str = ""):
        """
        标记上传失败
        
        Args:
            record_id: 上传记录ID
            error_message: 错误信息
        """
        UploadRepo.update_status(
            self.db, record_id, UploadStatus.FAILED,
            error_message=error_message,
        )
        UploadRepo.increment_retry(self.db, record_id)

    def get_pending_uploads(self, run_id: str) -> list[UploadRecord]:
        """
        获取待上传的记录（断点续传用）
        
        Args:
            run_id: 运行ID
        
        Returns:
        
            待上传记录列表
        """
        return UploadRepo.get_pending(self.db, run_id)

    # ─── 完成 / 清理 ─────────────────────────────────────────

    def finish(self, run_id: str):
        """标记运行完成"""
        RunRepo.update_status(self.db, run_id, RunStatus.COMPLETED)
        CheckpointRepo.cleanup(self.db, run_id)
        print(f"[数据库] 运行完成: {run_id}")

    def stop(self, run_id: str):
        """标记运行停止（保留断点以便恢复）"""
        RunRepo.update_status(self.db, run_id, RunStatus.PAUSED)
        print(f"[数据库] 运行已暂停: {run_id}")

    def cancel(self, run_id: str):
        """取消运行（不保留断点）"""
        RunRepo.update_status(self.db, run_id, RunStatus.STOPPED)
        CheckpointRepo.cleanup(self.db, run_id)
        print(f"[数据库] 运行已取消: {run_id}")

    # ─── 查询 ────────────────────────────────────────────────

    def get_recent_runs(self, limit: int = 10) -> List[Run]:
        """获取最近的运行记录"""
        return RunRepo.list_recent(self.db, limit)

    def get_statistics(self, run_id: str) -> dict:
        """获取当前运行的完整统计"""
        run = RunRepo.get_by_id(self.db, run_id)
        video_stats = VideoRepo.get_statistics(self.db, run_id)
        satisfied_count = ResultRepo.get_satisfied_count(self.db, run_id)
        progress = self.load_progress(run_id) or {}

        return {
            "run_id": run_id,
            "keyword": run.keyword if run else "",
            "status": run.status if run else "",
            "started_at": run.started_at if run else "",
            "target_count": run.target_count if run else 0,
            **video_stats,
            "satisfied_count": satisfied_count,
            "progress": progress,
        }

    def export_lineage(self, run_id: str) -> List[dict]:
        """导出完整数据血缘"""
        return ResultRepo.export_lineage(self.db, run_id)

    # ─── 工具 ────────────────────────────────────────────────

    @staticmethod
    def _generate_run_id() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
