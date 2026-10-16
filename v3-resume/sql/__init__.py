"""
V3 持久化版 - SQL 模块

提供 SQLite 数据库管理、数据模型、仓库CRUD、断点续传功能。

主要组件:
    database  - DatabaseManager (连接管理、建表)
    models    - Run / Video / AnalysisResult / Checkpoint 数据模型
    repos     - RunRepo / VideoRepo / ResultRepo / CheckpointRepo 仓库
    checkpoint - CheckpointManager (断点续传管理器)
"""

from .database import DatabaseManager, get_database
from .models import (
    Run, Video, AnalysisResult, Checkpoint, UploadRecord,
    RunStatus, VideoStatus, UploadStatus, SearchType, AnalysisMode,
    LineageBuilder,
)
from .repos import RunRepo, VideoRepo, ResultRepo, CheckpointRepo, UploadRepo
from .checkpoint import CheckpointManager

__all__ = [
    "DatabaseManager",
    "get_database",
    "Run", "Video", "AnalysisResult", "Checkpoint", "UploadRecord",
    "RunStatus", "VideoStatus", "UploadStatus", "SearchType", "AnalysisMode",
    "LineageBuilder",
    "RunRepo", "VideoRepo", "ResultRepo", "CheckpointRepo", "UploadRepo",
    "CheckpointManager",
]
