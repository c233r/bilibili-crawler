"""
V3 持久化版 - 数据仓库

每个仓库对应数据库一张表，封装 CRUD + 业务查询操作。
所有方法均为无状态的静态/类方法形式，接收 DatabaseManager 实例。
"""

import json
from datetime import datetime
from typing import Optional, List
from .database import DatabaseManager
from .models import (
    Run, Video, AnalysisResult, Checkpoint,
    RunStatus, VideoStatus, SearchType, AnalysisMode,
    UploadRecord, UploadStatus,
)

# ─── 工具函数 ──────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ─── Run 仓库 ──────────────────────────────────────────────

class RunRepo:
    """流水线运行记录仓库"""

    @staticmethod
    def create(db: DatabaseManager, run: Run) -> int:
        """创建运行记录，返回自增 ID"""
        conn = db.get_connection()
        data = run.to_dict()
        data["created_at"] = _now()
        data["started_at"] = data.get("started_at") or _now()

        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        values = list(data.values())

        cursor = conn.execute(
            f"INSERT OR REPLACE INTO runs ({columns}) VALUES ({placeholders})",
            values
        )
        conn.commit()
        return cursor.lastrowid

    @staticmethod
    def update_status(db: DatabaseManager, run_id: str, status: str):
        conn = db.get_connection()
        conn.execute(
            "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
            (status, _now(), run_id)
        )
        if status in (RunStatus.COMPLETED, RunStatus.STOPPED):
            conn.execute(
                "UPDATE runs SET finished_at = ? WHERE run_id = ?",
                (_now(), run_id)
            )
        conn.commit()

    @staticmethod
    def get_by_id(db: DatabaseManager, run_id: str) -> Optional[Run]:
        row = db.get_connection().execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return Run.from_row(row) if row else None

    @staticmethod
    def list_unfinished(db: DatabaseManager) -> List[Run]:
        """获取所有未完成的运行记录（用于断点续传）"""
        rows = db.get_connection().execute(
            "SELECT * FROM runs WHERE status IN (?, ?)",
            (RunStatus.RUNNING, RunStatus.PAUSED)
        ).fetchall()
        return [Run.from_row(r) for r in rows]

    @staticmethod
    def list_recent(db: DatabaseManager, limit: int = 10) -> List[Run]:
        rows = db.get_connection().execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [Run.from_row(r) for r in rows]

    @staticmethod
    def delete(db: DatabaseManager, run_id: str):
        db.get_connection().execute(
            "DELETE FROM runs WHERE run_id = ?", (run_id,)
        )
        db.get_connection().commit()


# ─── Video 仓库 ────────────────────────────────────────────

class VideoRepo:
    """视频任务仓库"""

    @staticmethod
    def batch_create(db: DatabaseManager, videos: List[Video]) -> int:
        """批量创建视频记录，返回插入数量（遇到重复 bvid 则跳过）"""
        conn = db.get_connection()
        count = 0
        for v in videos:
            data = v.to_dict()
            data["created_at"] = _now()
            data["updated_at"] = _now()

            columns = ", ".join(data.keys())
            placeholders = ", ".join("?" for _ in data)
            values = list(data.values())

            cursor = conn.execute(
                f"INSERT OR IGNORE INTO videos ({columns}) VALUES ({placeholders})",
                values
            )
            if cursor.rowcount > 0:
                count += 1
        conn.commit()
        return count

    @staticmethod
    def update_status(
        db: DatabaseManager,
        run_id: str,
        bvid: str,
        status: str,
        download_path: str = None,
        error_message: str = None,
    ):
        conn = db.get_connection()
        set_parts = ["status = ?", "updated_at = ?"]
        params = [status, _now()]

        if download_path is not None:
            set_parts.append("download_path = ?")
            params.append(download_path)
        if error_message is not None:
            set_parts.append("error_message = ?")
            params.append(error_message)

        params.extend([run_id, bvid])
        conn.execute(
            f"UPDATE videos SET {', '.join(set_parts)} WHERE run_id = ? AND bvid = ?",
            params
        )
        conn.commit()

    @staticmethod
    def increment_retry(db: DatabaseManager, run_id: str, bvid: str):
        conn = db.get_connection()
        conn.execute(
            "UPDATE videos SET retry_count = retry_count + 1, updated_at = ? WHERE run_id = ? AND bvid = ?",
            (_now(), run_id, bvid)
        )
        conn.commit()

    @staticmethod
    def get_by_bvid(db: DatabaseManager, run_id: str, bvid: str) -> Optional[Video]:
        row = db.get_connection().execute(
            "SELECT * FROM videos WHERE run_id = ? AND bvid = ?",
            (run_id, bvid)
        ).fetchone()
        return Video.from_row(row) if row else None

    @staticmethod
    def list_by_status(
        db: DatabaseManager,
        run_id: str,
        status: str = None,
    ) -> List[Video]:
        conn = db.get_connection()
        if status:
            rows = conn.execute(
                "SELECT * FROM videos WHERE run_id = ? AND status = ?",
                (run_id, status)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM videos WHERE run_id = ?",
                (run_id,)
            ).fetchall()
        return [Video.from_row(r) for r in rows]

    @staticmethod
    def list_unfinished(db: DatabaseManager, run_id: str) -> List[Video]:
        """获取未完成的视频（用于断点续传）"""
        placeholders = ", ".join("?" for _ in VideoStatus.UNFINISHED)
        rows = db.get_connection().execute(
            f"SELECT * FROM videos WHERE run_id = ? AND status IN ({placeholders})",
            [run_id] + list(VideoStatus.UNFINISHED)
        ).fetchall()
        
        videos = []
        conn = db.get_connection()
        for row in rows:
            video = Video.from_row(row)
            if video.status == VideoStatus.FAILED:
                if "返回码: 1" in (video.error_message or "") and video.retry_count < video.max_retries:
                    conn.execute(
                        "UPDATE videos SET status = ?, retry_count = retry_count + 1, updated_at = ? WHERE id = ?",
                        (VideoStatus.PENDING, _now(), video.id)
                    )
                    video.status = VideoStatus.PENDING
                    video.retry_count += 1
                    videos.append(video)
            else:
                videos.append(video)
        conn.commit()
        return videos

    @staticmethod
    def list_all(db: DatabaseManager, run_id: str) -> List[Video]:
        """获取所有视频"""
        return VideoRepo.list_by_status(db, run_id)

    @staticmethod
    def count_by_status(db: DatabaseManager, run_id: str, status: str = None) -> int:
        conn = db.get_connection()
        if status:
            row = conn.execute(
                "SELECT COUNT(*) FROM videos WHERE run_id = ? AND status = ?",
                (run_id, status)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM videos WHERE run_id = ?",
                (run_id,)
            ).fetchone()
        return row[0] if row else 0

    @staticmethod
    def get_statistics(db: DatabaseManager, run_id: str) -> dict:
        """获取统计信息"""
        conn = db.get_connection()
        row = conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'downloading' THEN 1 ELSE 0 END) as downloading,
                SUM(CASE WHEN status = 'downloaded' THEN 1 ELSE 0 END) as downloaded
            FROM videos WHERE run_id = ?""",
            (run_id,)
        ).fetchone()
        return dict(row) if row else {}


# ─── Result 仓库 ───────────────────────────────────────────

class ResultRepo:
    """分析结果仓库"""

    @staticmethod
    def create(db: DatabaseManager, result: AnalysisResult) -> int:
        conn = db.get_connection()
        data = result.to_dict()
        data["created_at"] = _now()

        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        values = list(data.values())

        cursor = conn.execute(
            f"INSERT INTO results ({columns}) VALUES ({placeholders})",
            values
        )
        conn.commit()
        return cursor.lastrowid

    @staticmethod
    def get_by_video_id(db: DatabaseManager, video_id: int) -> Optional[AnalysisResult]:
        row = db.get_connection().execute(
            "SELECT * FROM results WHERE video_id = ?", (video_id,)
        ).fetchone()
        return AnalysisResult.from_row(row) if row else None

    @staticmethod
    def list_by_run(
        db: DatabaseManager,
        run_id: str,
        satisfied_only: bool = False,
    ) -> List[AnalysisResult]:
        conn = db.get_connection()
        if satisfied_only:
            rows = conn.execute(
                "SELECT * FROM results WHERE run_id = ? AND satisfied = 1",
                (run_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM results WHERE run_id = ?",
                (run_id,)
            ).fetchall()
        return [AnalysisResult.from_row(r) for r in rows]

    @staticmethod
    def get_satisfied_count(db: DatabaseManager, run_id: str) -> int:
        row = db.get_connection().execute(
            "SELECT COUNT(*) FROM results WHERE run_id = ? AND satisfied = 1",
            (run_id,)
        ).fetchone()
        return row[0] if row else 0

    @staticmethod
    def export_lineage(db: DatabaseManager, run_id: str) -> List[dict]:
        """导出完整数据血缘链"""
        results = ResultRepo.list_by_run(db, run_id, satisfied_only=True)
        lineage_list = []
        for r in results:
            lineage_list.append(r.get_lineage_dict())
        return lineage_list


# ─── Checkpoint 仓库 ───────────────────────────────────────

class CheckpointRepo:
    """断点数据仓库（支持 JSON 读写和 TTL）"""

    @staticmethod
    def save(db: DatabaseManager, run_id: str, key: str, data: dict):
        conn = db.get_connection()
        conn.execute(
            """INSERT OR REPLACE INTO checkpoints (run_id, checkpoint_key, checkpoint_data, created_at)
               VALUES (?, ?, ?, ?)""",
            (run_id, key, json.dumps(data, ensure_ascii=False), _now())
        )
        conn.commit()

    @staticmethod
    def load(db: DatabaseManager, run_id: str, key: str) -> Optional[dict]:
        row = db.get_connection().execute(
            "SELECT checkpoint_data FROM checkpoints WHERE run_id = ? AND checkpoint_key = ?",
            (run_id, key)
        ).fetchone()
        if row:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return None
        return None

    @staticmethod
    def load_all(db: DatabaseManager, run_id: str) -> dict:
        """加载某个 run 的所有断点数据"""
        rows = db.get_connection().execute(
            "SELECT checkpoint_key, checkpoint_data FROM checkpoints WHERE run_id = ?",
            (run_id,)
        ).fetchall()
        result = {}
        for row in rows:
            try:
                result[row[0]] = json.loads(row[1])
            except json.JSONDecodeError:
                result[row[0]] = row[1]
        return result

    @staticmethod
    def delete(db: DatabaseManager, run_id: str, key: str):
        db.get_connection().execute(
            "DELETE FROM checkpoints WHERE run_id = ? AND checkpoint_key = ?",
            (run_id, key)
        )
        db.get_connection().commit()

    @staticmethod
    def cleanup(db: DatabaseManager, run_id: str):
        """清理某个 run 的所有断点数据"""
        db.get_connection().execute(
            "DELETE FROM checkpoints WHERE run_id = ?",
            (run_id,)
        )
        db.get_connection().commit()


# ─── Upload 仓库 ───────────────────────────────────────────

class UploadRepo:
    """上传记录仓库"""

    @staticmethod
    def create(db: DatabaseManager, record: UploadRecord) -> int:
        """创建上传记录，返回自增 ID"""
        conn = db.get_connection()
        data = record.to_dict()
        data.pop("id", None)
        data["created_at"] = _now()
        data["updated_at"] = _now()

        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        values = list(data.values())

        cursor = conn.execute(
            f"INSERT INTO pending_uploads ({columns}) VALUES ({placeholders})",
            values
        )
        conn.commit()
        return cursor.lastrowid

    @staticmethod
    def update_status(
        db: DatabaseManager,
        record_id: int,
        status: str,
        error_message: str = None,
    ):
        """更新上传状态"""
        conn = db.get_connection()
        set_parts = ["status = ?", "updated_at = ?"]
        params = [status, _now()]

        if error_message is not None:
            set_parts.append("error_message = ?")
            params.append(error_message)

        params.append(record_id)
        conn.execute(
            f"UPDATE pending_uploads SET {', '.join(set_parts)} WHERE id = ?",
            params
        )
        conn.commit()

    @staticmethod
    def increment_retry(db: DatabaseManager, record_id: int):
        """增加重试次数"""
        conn = db.get_connection()
        conn.execute(
            "UPDATE pending_uploads SET retry_count = retry_count + 1, updated_at = ? WHERE id = ?",
            (_now(), record_id)
        )
        conn.commit()

    @staticmethod
    def get_by_run(db: DatabaseManager, run_id: str) -> list[UploadRecord]:
        """获取某个 run 的所有上传记录"""
        rows = db.get_connection().execute(
            "SELECT * FROM pending_uploads WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,)
        ).fetchall()
        return [UploadRecord.from_row(r) for r in rows]

    @staticmethod
    def get_pending(db: DatabaseManager, run_id: str) -> list[UploadRecord]:
        """获取待上传的记录（断点续传用）"""
        rows = db.get_connection().execute(
            "SELECT * FROM pending_uploads WHERE run_id = ? AND status IN (?, ?) ORDER BY created_at ASC",
            (run_id, UploadStatus.PENDING, UploadStatus.FAILED)
        ).fetchall()
        return [UploadRecord.from_row(r) for r in rows]

    @staticmethod
    def delete(db: DatabaseManager, record_id: int):
        """删除上传记录（上传成功后清理）"""
        db.get_connection().execute(
            "DELETE FROM pending_uploads WHERE id = ?",
            (record_id,)
        )
        db.get_connection().commit()

    @staticmethod
    def cleanup_run(db: DatabaseManager, run_id: str):
        """清理某个 run 的所有上传记录"""
        db.get_connection().execute(
            "DELETE FROM pending_uploads WHERE run_id = ?",
            (run_id,)
        )
        db.get_connection().commit()
