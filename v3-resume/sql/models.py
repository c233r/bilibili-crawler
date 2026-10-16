"""
V3 持久化版 - 数据模型

轻量级 ORM 风格模型，每个模型对应数据库一张表。
提供 to_dict / from_row 等方法便于序列化。
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any


# ─── 枚举常量 ───────────────────────────────────────────────

class RunStatus:
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"


class VideoStatus:
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"

    UNFINISHED = {PENDING, DOWNLOADING, DOWNLOADED, FAILED}


class UploadStatus:
    PENDING = "pending"
    UPLOADING = "uploading"
    SUCCESS = "success"
    FAILED = "failed"


class SearchType:
    VIDEO = "video"
    UP = "up"


class AnalysisMode:
    BASIC = "basic"
    REFINED = "refined"


# ─── 数据模型 ───────────────────────────────────────────────

@dataclass
class Run:
    """流水线运行记录"""
    run_id: str
    keyword: str
    search_type: str = SearchType.VIDEO
    status: str = RunStatus.RUNNING
    target_count: int = 0
    use_refined: bool = False
    filter_prompt: str = ""
    total_workers: int = 5
    started_at: str = ""
    finished_at: str = ""
    created_at: str = ""
    id: Optional[int] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["use_refined"] = int(d["use_refined"])
        return d

    @classmethod
    def from_row(cls, row) -> "Run":
        d = dict(row)
        d["use_refined"] = bool(d.get("use_refined", 0))
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__ if k != "id"})


@dataclass
class Video:
    """视频任务"""
    run_id: str
    bvid: str
    title: str
    page: int = 1
    status: str = VideoStatus.PENDING
    download_path: str = ""
    error_message: str = ""
    retry_count: int = 0
    max_retries: int = 3
    created_at: str = ""
    updated_at: str = ""
    id: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "Video":
        d = dict(row)
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__ if k != "id"})


@dataclass
class AnalysisResult:
    """分析结果（含数据血缘）"""
    video_id: int
    run_id: str
    bvid: str
    satisfied: bool = False
    confidence: float = 0.0
    analysis_mode: str = AnalysisMode.BASIC
    prompt_used: str = ""
    result_detail: str = ""
    segment_paths: str = ""
    source_frame_count: int = 0
    satisfied_frame_count: int = 0
    duration_ms: float = 0.0
    api_duration_ms: float = 0.0
    lineage: str = ""
    created_at: str = ""
    id: Optional[int] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["satisfied"] = int(d["satisfied"])
        return d

    @classmethod
    def from_row(cls, row) -> "AnalysisResult":
        d = dict(row)
        d["satisfied"] = bool(d.get("satisfied", 0))
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__ if k != "id"})

    def get_lineage_dict(self) -> dict:
        if not self.lineage:
            return {}
        try:
            return json.loads(self.lineage)
        except json.JSONDecodeError:
            return {"raw": self.lineage}

    def get_segment_paths_list(self) -> List[str]:
        if not self.segment_paths:
            return []
        try:
            return json.loads(self.segment_paths)
        except json.JSONDecodeError:
            return []

    def get_result_detail_dict(self) -> dict:
        if not self.result_detail:
            return {}
        try:
            return json.loads(self.result_detail)
        except json.JSONDecodeError:
            return {"raw": self.result_detail}


@dataclass
class UploadRecord:
    """上传记录（待上传 / 已上传的视频）"""
    run_id: str
    bvid: str
    title: str
    video_path: str
    status: str = UploadStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    error_message: str = ""
    created_at: str = ""
    updated_at: str = ""
    id: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "UploadRecord":
        d = dict(row)
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__ if k != "id"})


@dataclass
class Checkpoint:
    """断点数据"""
    run_id: str
    checkpoint_key: str
    checkpoint_data: str
    created_at: str = ""
    id: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "Checkpoint":
        d = dict(row)
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__ if k != "id"})

    def get_data(self) -> Any:
        try:
            return json.loads(self.checkpoint_data)
        except json.JSONDecodeError:
            return None


# ─── 数据血缘构建器 ─────────────────────────────────────────

class LineageBuilder:
    """数据血缘构建工具"""

    @staticmethod
    def for_video(video: Video) -> dict:
        return {
            "source": "bilibili_api",
            "source_type": "video_search",
            "bvid": video.bvid,
            "title": video.title,
            "download_path": video.download_path,
            "downloaded_at": video.updated_at,
        }

    @staticmethod
    def for_analysis(
        video_lineage: dict,
        analysis_mode: str,
        prompt_used: str,
        source_frame_count: int,
        satisfied_frame_count: int,
    ) -> dict:
        return {
            "pipeline_version": "v3.0",
            "source": video_lineage,
            "processing": {
                "module": "vlm_analyzer" if analysis_mode == AnalysisMode.BASIC else "refined_analyzer",
                "analysis_mode": analysis_mode,
                "prompt_used": prompt_used,
                "source_frame_count": source_frame_count,
                "satisfied_frame_count": satisfied_frame_count,
            },
            "output": {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        }

    @staticmethod
    def for_segment(
        parent_lineage: dict,
        segment_index: int,
        segment_path: str,
        frame_range: tuple,
    ) -> dict:
        lineage = dict(parent_lineage)
        lineage["segment"] = {
            "index": segment_index,
            "path": segment_path,
            "frame_range": list(frame_range),
        }
        return lineage
