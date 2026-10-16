"""
V3 持久化版 - 核心数据库管理器

提供 SQLite 连接管理、表创建、版本迁移等功能。
所有数据库操作均通过此类统一管理连接。
"""

import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional


# 数据库版本号，用于自动迁移
DB_VERSION = 1

# 建表 SQL
CREATE_TABLES_SQL = """
-- 流水线运行记录表（每次搜索/download为一个run）
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL UNIQUE,
    keyword         TEXT NOT NULL,
    search_type     TEXT NOT NULL DEFAULT 'video',
    status          TEXT NOT NULL DEFAULT 'running',
    target_count    INTEGER DEFAULT 0,
    use_refined     INTEGER DEFAULT 0,
    filter_prompt   TEXT,
    total_workers   INTEGER DEFAULT 5,
    started_at      TEXT,
    finished_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 视频任务表
CREATE TABLE IF NOT EXISTS videos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    bvid            TEXT NOT NULL,
    title           TEXT NOT NULL,
    page            INTEGER DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'pending',
    download_path   TEXT,
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 3,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(run_id, bvid),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

-- 分析结果表（数据血缘）
CREATE TABLE IF NOT EXISTS results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id            INTEGER,
    run_id              TEXT NOT NULL,
    bvid                TEXT NOT NULL,
    satisfied           INTEGER NOT NULL DEFAULT 0,
    confidence          REAL DEFAULT 0.0,
    analysis_mode       TEXT NOT NULL DEFAULT 'basic',
    prompt_used         TEXT,
    result_detail       TEXT,
    segment_paths       TEXT,
    source_frame_count  INTEGER DEFAULT 0,
    satisfied_frame_count INTEGER DEFAULT 0,
    duration_ms         REAL DEFAULT 0.0,
    api_duration_ms     REAL DEFAULT 0.0,
    lineage             TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

-- 断点保存表
CREATE TABLE IF NOT EXISTS checkpoints (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    checkpoint_key  TEXT NOT NULL,
    checkpoint_data TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(run_id, checkpoint_key),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

-- 待上传视频记录表（满足条件但尚未完成上传的视频）
CREATE TABLE IF NOT EXISTS pending_uploads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    bvid            TEXT NOT NULL,
    title           TEXT NOT NULL,
    video_path      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    retry_count     INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 3,
    error_message   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_videos_run_id ON videos(run_id);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_bvid ON videos(bvid);
CREATE INDEX IF NOT EXISTS idx_results_run_id ON results(run_id);
CREATE INDEX IF NOT EXISTS idx_results_video_id ON results(video_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_run_id ON checkpoints(run_id);
CREATE INDEX IF NOT EXISTS idx_uploads_run_id ON pending_uploads(run_id);
CREATE INDEX IF NOT EXISTS idx_uploads_status ON pending_uploads(status);
"""


class DatabaseManager:
    """
    SQLite 数据库管理器（线程安全、连接复用）

    使用方式:
        db = DatabaseManager("data/pipeline.db")
        db.initialize()

        with db.get_connection() as conn:
            conn.execute("SELECT ...")
    """

    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: 数据库文件路径，默认为 sql/data/pipeline.db
        """
        if db_path is None:
            sql_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.join(sql_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "pipeline.db")

        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self):
        """初始化数据库（建表 + 建索引）"""
        with self._lock:
            if self._initialized:
                return

            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(CREATE_TABLES_SQL)
            conn.commit()
            conn.close()

            self._initialized = True

    def get_connection(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接（线程局部，自动复用）"""
        if not hasattr(self._local, "connection") or self._local.connection is None:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.connection = conn
        return self._local.connection

    def close(self):
        """关闭当前线程的数据库连接"""
        if hasattr(self._local, "connection") and self._local.connection is not None:
            self._local.connection.close()
            self._local.connection = None

    def vacuum(self):
        """压缩数据库文件"""
        conn = self.get_connection()
        conn.execute("VACUUM")

    def get_stats(self) -> dict:
        """获取数据库统计信息"""
        conn = self.get_connection()
        return {
            "total_runs": conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
            "total_videos": conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0],
            "total_results": conn.execute("SELECT COUNT(*) FROM results").fetchone()[0],
            "db_size_mb": round(os.path.getsize(self.db_path) / (1024 * 1024), 2) if os.path.exists(self.db_path) else 0,
        }


# 全局单例（线程安全延迟初始化）
_db_instance: Optional[DatabaseManager] = None
_db_lock = threading.Lock()


def get_database(db_path: str = None) -> DatabaseManager:
    """获取全局数据库管理器单例"""
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = DatabaseManager(db_path)
                _db_instance.initialize()
    return _db_instance
