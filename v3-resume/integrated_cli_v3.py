"""
B站爬虫 + 大模型筛选整合命令行界面（V3持久化版）
主入口文件，集成SQLite数据库持久化和断点续传功能

相比 multiproc 版本的增强:
  1. 每次运行自动创建 run 记录，状态实时持久化
  2. 支持断点续传：相同关键词自动恢复未完成的任务
  3. 完整的数据血缘：每个分析结果都可追溯来源
  4. 数据库查询：可查看历史运行记录
"""

import os
import sys
import json
from datetime import datetime
import time

# 添加模块路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bilibili爬虫', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'pipeline'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.control.pipeline_main import VideoPipeline
from pipeline.log.logger import get_main_logger
from model.bilibili_api import BilibiliAPI
from sql import get_database, CheckpointManager, SearchType, AnalysisMode, VideoStatus, VideoRepo
from utils import get_video_searcher


class IntegratedCLIV3:
    """V3 集成CLI - 支持持久化与断点续传"""

    def __init__(self):
        # 配置文件路径
        self.config_file = os.path.join(os.path.dirname(__file__), 'bilibili爬虫', 'config.json')

        # 加载配置
        self.config = self._load_config()

        # 下载路径
        self.download_path = self.config.get('download_path', os.path.join(os.path.dirname(__file__), 'downloads'))

        # 筛选功能相关
        self.filter_enabled = False
        self.filter_prompt = ""
        self.use_refined_analysis = True
        self.default_filter_prompt = ""

        # 初始化默认筛选Prompt
        self._init_default_prompt()

        # 流水线实例
        self.pipeline = None

        # V3 数据库相关
        self.db = get_database()
        self.cpm = CheckpointManager(self.db)

        # 日志器
        self.logger = get_main_logger()

        print("[信息] V3持久化CLI已初始化")
        print(f"[信息] 下载路径: {self.download_path}")
        print(f"[信息] 数据库路径: {self.db.db_path}")

    def _load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[警告] 加载配置文件失败: {e}")
        return {}

    def _init_default_prompt(self):
        """初始化默认筛选Prompt"""
        try:
            filter_config_path = os.path.join(os.path.dirname(__file__), '大模型接入筛选', 'config.json')
            if os.path.exists(filter_config_path):
                with open(filter_config_path, 'r', encoding='utf-8') as f:
                    filter_config = json.load(f)
                    self.default_filter_prompt = filter_config.get('prompt', '')
                    if self.default_filter_prompt:
                        print(f"[信息] 已加载默认筛选Prompt: {self.default_filter_prompt[:30]}...")

            self.filter_enabled = True if self.default_filter_prompt else False
        except Exception as e:
            print(f"[信息] 加载默认Prompt失败: {e}")

    def print_menu(self):
        """打印主菜单"""
        # 如果流水线未初始化，先进行初始化
        if self.pipeline is None:
            self._init_pipeline(total_workers=10)

        # 查询数据库统计
        stats = self.db.get_stats()

        print("\n" + "="*60)
        print("   B站爬虫 + 大模型筛选整合界面（V3 持久化版）")
        print("="*60)
        print("1. 搜索视频（多线程下载+筛选）")
        print("2. 搜索UP主（多线程下载+筛选）")
        print("3. 断点续传 - 恢复未完成的任务")
        print("4. 查看历史运行记录")
        print("5. 查看数据血缘")
        print("6. 设置下载路径")
        print("7. 设置线程数量")
        print("8. 退出")
        print("="*60)
        print(f"当前配置:")
        print(f"  下载路径: {self.download_path}")
        print(f"  筛选功能: {'可用' if self.filter_enabled else '未启用'}")
        if self.filter_enabled:
            print(f"  筛选Prompt: {self.filter_prompt}")
            print(f"  分析模式: {'精细化分析' if self.use_refined_analysis else '普通分析'}")
        print("-"*60)
        print(f"数据库统计:")
        print(f"  历史运行数: {stats['total_runs']}")
        print(f"  历史视频数: {stats['total_videos']}")
        print(f"  分析结果数: {stats['total_results']}")
        print(f"  数据库大小: {stats['db_size_mb']:.2f} MB")
        print("="*60)

    def input_choice(self, prompt, valid_choices=None):
        """获取用户输入并验证"""
        while True:
            choice = input(prompt).strip()
            if valid_choices and choice not in valid_choices:
                print(f"无效选项，请输入: {', '.join(valid_choices)}")
                continue
            return choice

    def _enable_filter_with_prompt(self, use_refined: bool = False):
        """启用筛选功能并获取检测prompt"""
        self.use_refined_analysis = use_refined

        if self.default_filter_prompt:
            self.filter_prompt = self.default_filter_prompt
            self.filter_enabled = True
            mode_text = "精细化分析" if use_refined else "普通分析"
            print(f"[筛选] 已启用筛选功能（{mode_text}），使用配置文件中的默认Prompt")
            return True

        prompt = input("请输入筛选检测的Prompt: ").strip()
        if not prompt:
            print("Prompt不能为空")
            return False

        self.filter_prompt = prompt
        self.filter_enabled = True
        mode_text = "精细化分析" if use_refined else "普通分析"
        print(f"[筛选] 已启用筛选功能（{mode_text}），检测Prompt: {prompt}")
        return True

    def _get_download_params(self, mode: str = "video", ask_resume: bool = True) -> dict:
        """
        获取下载参数（共用函数）
        
        Args:
            mode: 'video' - 动态分配线程（输入总线程数）
                  'up' - 分别输入下载和分析线程数
            ask_resume: 是否询问断点续传（选项1默认不询问，始终重新开始）
        
        Returns:
            dict: {'use_resume', 'download_count', 'total_workers', ...}
        """
        params = {}

        # 下载数量
        while True:
            count_input = input("请输入要下载的数量（0表示全部下载）: ").strip()
            if count_input.isdigit():
                download_count = int(count_input)
                if download_count >= 0:
                    break
            print("请输入有效的非负整数")
        params['download_count'] = download_count

        # 线程参数
        if mode == "video":
            while True:
                worker_input = input("请输入总线程数量（默认5，动态分配下载和分析）: ").strip()
                if worker_input == "":
                    total_workers = 5
                    break
                if worker_input.isdigit() and int(worker_input) > 0:
                    total_workers = int(worker_input)
                    break
                print("请输入有效的正整数")
            params['total_workers'] = total_workers
        else:
            while True:
                worker_input = input("请输入下载线程数量（默认2）: ").strip()
                if worker_input == "":
                    download_workers = 2
                    break
                if worker_input.isdigit() and int(worker_input) > 0:
                    download_workers = int(worker_input)
                    break
                print("请输入有效的正整数")

            while True:
                worker_input = input("请输入分析线程数量（默认3）: ").strip()
                if worker_input == "":
                    analyze_workers = 3
                    break
                if worker_input.isdigit() and int(worker_input) > 0:
                    analyze_workers = int(worker_input)
                    break
                print("请输入有效的正整数")
            params['download_workers'] = download_workers
            params['analyze_workers'] = analyze_workers
            params['total_workers'] = download_workers + analyze_workers

        # 断点续传（选项1不询问，始终重新开始）
        if ask_resume:
            while True:
                resume_input = input("是否启用断点续传？(y/n，默认y): ").strip().lower()
                if resume_input in ['', 'y', 'n']:
                    use_resume = resume_input in ['', 'y']
                    break
                print("请输入 y 或 n")
        else:
            use_resume = False
        params['use_resume'] = use_resume

        return params

    def _print_download_config(self, keyword: str, download_count: int, total_workers: int,
                               use_resume: bool, target_name: str = None,
                               download_workers: int = None, analyze_workers: int = None):
        """打印下载配置信息（共用函数）"""
        print(f"\n[下载] 开始下载（目标: {'全部' if download_count == 0 else download_count} 个满足条件的视频）")
        print(f"[下载] 关键词: {keyword}")
        if target_name:
            print(f"[下载] 目标: {target_name}")
        print(f"[下载] 筛选模式: 启用，检测Prompt: {self.filter_prompt}")
        print(f"[下载] 分析模式: {'精细化分析' if self.use_refined_analysis else '普通分析'}")
        if download_workers and analyze_workers:
            print(f"[下载] 线程配置: {download_workers}个下载线程, {analyze_workers}个分析线程")
        else:
            print(f"[下载] 线程配置: {total_workers}个线程（动态分配）")
        print(f"[下载] 断点续传: {'启用' if use_resume else '禁用'}")

    def _init_pipeline(self, total_workers: int = 5):
        """初始化流水线"""
        print(f"[流水线] 初始化中... (总线程数: {total_workers})")
        self.pipeline = VideoPipeline(total_workers=total_workers)

        while True:
            enable_push = input("是否启用视频推送至EdgeCrafter服务器？(y/n，默认y): ").strip().lower()
            if enable_push in ['', 'y', 'n']:
                enable_push = 'y' if enable_push == '' else enable_push
                break
            print("请输入 y 或 n")

        if enable_push == 'y':
            api_url = input("请输入EdgeCrafter API地址（默认: http://localhost:8000）: ").strip()
            if not api_url:
                api_url = 'http://localhost:8000'
            self.pipeline.enable_video_push(api_url=api_url)

        print("[流水线] 初始化完成")

    def _start_run_with_db(self, keyword: str, search_type: str, target_count: int, force_new: bool = False):
        """启动/恢复运行（V3持久化）"""
        self.pipeline.start_run(
            keyword=keyword,
            search_type=search_type,
            target_count=target_count,
            use_refined=self.use_refined_analysis,
            filter_prompt=self.filter_prompt,
            force_new=force_new,
        )

        if self.cpm.was_resumed:
            print(f"[断点续传] ✅ 成功恢复运行: {self.pipeline.current_run.run_id}")
        else:
            print(f"[数据库] 🆕 创建新运行: {self.pipeline.current_run.run_id}")

    def search_and_download_video(self, use_refined=False):
        """搜索并下载视频（多线程版 + V3持久化）"""
        if not self._enable_filter_with_prompt(use_refined=use_refined):
            return

        keyword = input("\n请输入搜索关键词: ").strip()
        if not keyword:
            print("关键词不能为空")
            return

        # 获取下载参数（选项1无需问续传，始终重新开始）
        params = self._get_download_params(mode="video", ask_resume=False)
        download_count = params['download_count']
        total_workers = params['total_workers']
        use_resume = params['use_resume']

        # 打印配置
        self._print_download_config(keyword, download_count, total_workers, use_resume)

        self._init_pipeline(total_workers=total_workers)
        self.pipeline.set_filter_prompt(self.filter_prompt, self.use_refined_analysis)

        try:
            # V3: 启动/恢复运行
            self._start_run_with_db(keyword, SearchType.VIDEO, download_count, force_new=not use_resume)

            # 启动流水线（只启动一次）
            self.pipeline.start()

            # 立即设置目标条件数量，让监控线程开始监控
            self.pipeline.target_satisfied = download_count
            if download_count > 0:
                self.logger.info(f"[监控] 目标满足条件视频数已设置为: {download_count}")
            else:
                self.logger.info(f"[监控] 未设置目标条件数（全部下载）")

            pending_items = []  # 暂存队列满时未能添加的视频

            # 如果是断点续传，先加载未完成的视频
            if self.cpm.was_resumed:
                unfinished = self.cpm.get_unfinished_videos(self.pipeline.current_run.run_id)
                if unfinished:
                    print(f"[断点续传] 发现 {len(unfinished)} 个未完成视频，将重新加入处理队列")
                    for v in unfinished:
                        pending_items.append({
                            "bvid": v.bvid,
                            "title": v.title,
                            "page": v.page,
                        })

            # 使用通用搜索工具
            searcher = get_video_searcher()
            total_videos_found, pending_items = searcher.search_and_download(
                keyword=keyword,
                pipeline=self.pipeline,
                target_count=download_count,
                start_page=1,
                page_size=20,
                pending_items=pending_items,
            )

            # 所有搜索结果都获取完毕，等待最终完成
            stop_reason = self.pipeline.wait_until_complete(target_satisfied=download_count)

            # V3: 根据停止原因标记运行状态
            if stop_reason == "completed":
                self.cpm.finish(self.pipeline.current_run.run_id)
                print(f"[数据库] ✅ 运行已完成并保存: {self.pipeline.current_run.run_id}")
            else:
                self.cpm.stop(self.pipeline.current_run.run_id)
                print(f"[数据库] ⏸️ 运行已暂停，可断点续传: {self.pipeline.current_run.run_id}")

            # 打印最终统计
            self.pipeline.print_statistics()

        except KeyboardInterrupt:
            # V3: 中断时标记为暂停状态，保留断点
            if self.pipeline and self.pipeline.current_run:
                self.cpm.stop(self.pipeline.current_run.run_id)
                print(f"\n[中断] 运行已暂停，下次输入相同关键词可恢复: {self.pipeline.current_run.run_id}")
            raise

        finally:
            # 停止流水线
            if self.pipeline:
                self.pipeline.stop()

        # 重置筛选状态
        self.filter_enabled = False

    def search_up_and_download(self, use_refined=False):
        """搜索UP主并下载其视频（多线程版 + V3持久化）"""
        # 检查并启用筛选
        if not self._enable_filter_with_prompt(use_refined=use_refined):
            return

        keyword = input("请输入UP主名称: ").strip()
        if not keyword:
            print("关键词不能为空")
            return

        print(f"\n[搜索] 正在搜索UP主: {keyword}...")

        api = BilibiliAPI()
        users = api.search_users(keyword, max_results=10)

        if not users:
            print("未找到相关UP主")
            return

        print(f"\n[搜索结果] 共找到 {len(users)} 个UP主")
        print("-"*60)

        for i, user in enumerate(users, 1):
            print(f"{i:2d}. {user['name']}")
            print(f"      UID: {user.get('mid', '')}")
            follower_count = user.get('follower') or 0
            archive_count = user.get('archive_count') or 0
            print(f"      粉丝数: {follower_count:,} | 视频数: {archive_count}")
            print(f"      简介: {user.get('sign', '')[:50]}...")
            print()

        # 选择UP主
        while True:
            choice = input("请输入要查看的UP主序号（q返回）: ").strip()
            if choice.lower() == 'q':
                return
            if choice.isdigit() and 1 <= int(choice) <= len(users):
                selected_user = users[int(choice)-1]
                break
            print("请输入有效的序号")

        uid = selected_user.get('mid')
        user_name = selected_user.get('name', '未知')

        print(f"\n[选择] 已选择UP主: {user_name} (UID: {uid})")

        # 获取下载参数
        params = self._get_download_params(mode="up")
        download_count = params['download_count']
        download_workers = params['download_workers']
        analyze_workers = params['analyze_workers']
        total_workers = params['total_workers']
        use_resume = params['use_resume']

        # UP主搜索的run标识: UP_{uid}
        run_keyword = f"UP_{uid}_{user_name}"

        # 打印配置
        self._print_download_config(
            run_keyword, download_count, total_workers, use_resume,
            target_name=f"UP主: {user_name}",
            download_workers=download_workers,
            analyze_workers=analyze_workers,
        )

        # 初始化流水线
        self._init_pipeline(total_workers=total_workers)

        # 设置筛选Prompt
        self.pipeline.set_filter_prompt(self.filter_prompt, self.use_refined_analysis)

        try:
            # V3: 启动/恢复运行
            self._start_run_with_db(run_keyword, SearchType.UP, download_count, force_new=not use_resume)

            page = 1
            page_size = 50

            # 启动流水线（只启动一次）
            self.pipeline.start()

            # 立即设置目标条件数量，让监控线程开始监控
            self.pipeline.target_satisfied = download_count
            if download_count > 0:
                self.logger.info(f"[监控] 目标满足条件视频数已设置为: {download_count}")
            else:
                self.logger.info(f"[监控] 未设置目标条件数（全部下载）")

            pending_items = []  # 暂存队列满时未能添加的视频

            # 如果是断点续传，先加载未完成的视频
            if self.cpm.was_resumed:
                unfinished = self.cpm.get_unfinished_videos(self.pipeline.current_run.run_id)
                if unfinished:
                    print(f"[断点续传] 发现 {len(unfinished)} 个未完成视频，将重新加入处理队列")
                    for v in unfinished:
                        pending_items.append({
                            "bvid": v.bvid,
                            "title": v.title,
                            "page": v.page,
                        })

            while True:
                # 检查是否达到目标数量（在获取新页面前先检查）
                stats = self.pipeline.get_statistics()
                satisfied_count = stats.get('satisfied_count', 0)

                if download_count > 0 and satisfied_count >= download_count:
                    print(f"\n[完成] 已达到设定的下载数量 ({satisfied_count} 个)")
                    break

                # 先尝试添加之前暂存的视频
                if pending_items:
                    _, pending_items = self.pipeline.add_download_tasks(pending_items)

                # 检查断点续传是否已完成
                if self.cpm.was_resumed and not pending_items and page > 1:
                    if self.pipeline.task_queue.get_download_queue_size() == 0:
                        print("[断点续传] 未完成视频已全部重新处理")
                        break

                print(f"\n[获取] 正在获取UP主第 {page} 页视频...")

                try:
                    items = api.get_user_videos(uid, page=page, page_size=page_size)
                except Exception as e:
                    print(f"[错误] 获取第 {page} 页失败: {str(e)}")
                    page += 1
                    continue

                if not items:
                    print("[完成] 已获取全部内容")
                    break

                print(f"[获取] 第 {page} 页找到 {len(items)} 个视频")

                # 等待下载队列待处理数低于20个再添加新任务（按需补充，避免堆积）
                while True:
                    pending_count = self.pipeline.task_queue.get_download_queue_size()
                    if pending_count < 20:
                        break
                    time.sleep(0.5)

                # 添加下载任务
                added_count, skipped_videos = self.pipeline.add_download_tasks(items)
                if skipped_videos:
                    # 队列已满，暂存未能添加的视频
                    pending_items.extend(skipped_videos)

                # 检查是否达到目标数量
                stats = self.pipeline.get_statistics()
                satisfied_count = stats.get('satisfied_count', 0)

                if download_count > 0 and satisfied_count >= download_count:
                    print(f"\n[完成] 已达到设定的下载数量 ({satisfied_count} 个)")
                    break

                # 翻页继续获取
                page += 1

            # 所有搜索结果都获取完毕，等待最终完成
            stop_reason = self.pipeline.wait_until_complete(target_satisfied=download_count)

            # V3: 根据停止原因标记运行状态
            if stop_reason == "completed":
                self.cpm.finish(self.pipeline.current_run.run_id)
                print(f"[数据库] ✅ 运行已完成并保存: {self.pipeline.current_run.run_id}")
            else:
                self.cpm.stop(self.pipeline.current_run.run_id)
                print(f"[数据库] ⏸️ 运行已暂停，可断点续传: {self.pipeline.current_run.run_id}")

            # 打印最终统计
            self.pipeline.print_statistics()

        except KeyboardInterrupt:
            if self.pipeline and self.pipeline.current_run:
                self.cpm.stop(self.pipeline.current_run.run_id)
                print(f"\n[中断] 运行已暂停，下次可恢复: {self.pipeline.current_run.run_id}")
            raise

        finally:
            # 停止流水线
            if self.pipeline:
                self.pipeline.stop()

        # 重置筛选状态
        self.filter_enabled = False

    def resume_run(self):
        """断点续传 - 恢复未完成的任务"""
        print("\n" + "="*60)
        print("   断点续传 - 选择要恢复的运行")
        print("="*60)

        # 列出所有未完成的运行
        from sql.repos import RunRepo
        unfinished = RunRepo.list_unfinished(self.db)

        if not unfinished:
            print("[信息] 没有未完成的运行")
            return

        print(f"\n发现 {len(unfinished)} 个未完成的运行:")
        print("-"*60)
        for i, run in enumerate(unfinished, 1):
            stats = self.cpm.get_statistics(run.run_id)
            print(f"{i:2d}. [{run.run_id[:16]}...]")
            print(f"      关键词: {run.keyword}")
            print(f"      类型: {run.search_type}")
            print(f"      开始时间: {run.started_at}")
            print(f"      进度: 完成={stats.get('completed', 0)}, 失败={stats.get('failed', 0)}, "
                  f"满足={stats.get('satisfied_count', 0)}")
            print()

        while True:
            choice = input("请选择要恢复的运行序号（q返回）: ").strip()
            if choice.lower() == 'q':
                return
            if choice.isdigit() and 1 <= int(choice) <= len(unfinished):
                selected_run = unfinished[int(choice)-1]
                break
            print("请输入有效的序号")

        # 恢复运行
        keyword = selected_run.keyword
        self.use_refined_analysis = selected_run.use_refined
        self.filter_prompt = selected_run.filter_prompt
        self.filter_enabled = True
        target_count = selected_run.target_count

        print(f"\n[断点续传] 准备恢复: {keyword}")
        print(f"[断点续传] 目标数量: {target_count}")
        print(f"[断点续传] 分析模式: {'精细化' if self.use_refined_analysis else '普通'}")

        # 重新初始化流水线
        self._init_pipeline(total_workers=selected_run.total_workers or 5)
        self.pipeline.set_filter_prompt(self.filter_prompt, self.use_refined_analysis)

        # 恢复run
        self._start_run_with_db(keyword, selected_run.search_type, target_count, force_new=False)

        # 启动流水线
        self.pipeline.start()
        self.pipeline.target_satisfied = target_count

        # 加载未完成的视频并添加到流水线
        unfinished_videos = self.cpm.get_unfinished_videos(self.pipeline.current_run.run_id)
        pending_items = []
        if unfinished_videos:
            print(f"[断点续传] 重新加入 {len(unfinished_videos)} 个未完成视频")
            for v in unfinished_videos:
                if v.status == VideoStatus.PENDING or v.status == VideoStatus.FAILED:
                    # 重新下载
                    self.pipeline.dynamic_pool.add_download_task(v.bvid, v.title)
                elif v.status == VideoStatus.DOWNLOADED and v.download_path:
                    # 直接分析
                    from pipeline.control.task_queue import DownloadTask
                    task = DownloadTask(
                        bvid=v.bvid,
                        title=v.title,
                        video_path=v.download_path,
                        retry_count=v.retry_count,
                        max_retries=v.max_retries
                    )
                    self.pipeline.task_queue.add_video_task(task)

        # 计算起始页码
        page_size = 20
        processed_count = VideoRepo.count_by_status(
            self.db, self.pipeline.current_run.run_id, VideoStatus.COMPLETED
        ) + VideoRepo.count_by_status(
            self.db, self.pipeline.current_run.run_id, VideoStatus.FAILED
        )
        start_page = (processed_count // page_size) + 1
        print(f"[断点续传] 已处理 {processed_count} 个视频，从第 {start_page} 页继续搜索")

        # 使用通用搜索工具
        searcher = get_video_searcher()
        total_videos_found, pending_items = searcher.search_and_download(
            keyword=keyword,
            pipeline=self.pipeline,
            target_count=target_count,
            start_page=start_page,
            page_size=page_size,
            pending_items=pending_items,
        )

        # 等待处理完成
        try:
            stop_reason = self.pipeline.wait_until_complete(target_satisfied=target_count)
            if stop_reason == "completed":
                self.cpm.finish(self.pipeline.current_run.run_id)
                print(f"[数据库] ✅ 恢复运行完成: {self.pipeline.current_run.run_id}")
            else:
                self.cpm.stop(self.pipeline.current_run.run_id)
                print(f"[数据库] ⏸️ 运行已暂停，可再次断点续传: {self.pipeline.current_run.run_id}")
        except KeyboardInterrupt:
            if self.pipeline.current_run:
                self.cpm.stop(self.pipeline.current_run.run_id)
            raise
        finally:
            if self.pipeline:
                self.pipeline.stop()

        self.filter_enabled = False

    def show_history(self):
        """查看历史运行记录"""
        print("\n" + "="*60)
        print("   历史运行记录")
        print("="*60)

        recent_runs = self.cpm.get_recent_runs(limit=20)

        if not recent_runs:
            print("[信息] 没有历史运行记录")
            return

        print(f"\n显示最近 {len(recent_runs)} 条运行记录:")
        print("-"*60)
        for i, run in enumerate(recent_runs, 1):
            stats = self.cpm.get_statistics(run.run_id)
            status_text = {
                'running': '🟢 运行中',
                'completed': '✅ 已完成',
                'paused': '⏸️  暂停',
                'stopped': '🛑 已停止',
                'failed': '❌ 失败',
            }.get(run.status, run.status)

            print(f"{i:2d}. [{run.run_id[:16]}...] {status_text}")
            print(f"      关键词: {run.keyword}")
            print(f"      类型: {run.search_type} | 目标: {run.target_count or '全部'}")
            print(f"      开始: {run.started_at} | 结束: {run.finished_at or '进行中'}")
            print(f"      进度: 总={stats.get('total', 0)}, "
                  f"完成={stats.get('completed', 0) or 0}, "
                  f"失败={stats.get('failed', 0) or 0}, "
                  f"满足={stats.get('satisfied_count', 0)}")
            print()

    def show_lineage(self):
        """查看数据血缘"""
        print("\n" + "="*60)
        print("   数据血缘查询")
        print("="*60)

        recent_runs = self.cpm.get_recent_runs(limit=10)

        if not recent_runs:
            print("[信息] 没有可用的运行记录")
            return

        print(f"\n选择要查看血缘的运行:")
        print("-"*60)
        for i, run in enumerate(recent_runs, 1):
            print(f"{i:2d}. [{run.run_id[:16]}...] {run.keyword} ({run.status})")
        print()

        while True:
            choice = input("请选择运行序号（q返回）: ").strip()
            if choice.lower() == 'q':
                return
            if choice.isdigit() and 1 <= int(choice) <= len(recent_runs):
                selected_run = recent_runs[int(choice)-1]
                break
            print("请输入有效的序号")

        # 导出该运行的血缘
        lineage = self.cpm.export_lineage(selected_run.run_id)

        if not lineage:
            print(f"\n[信息] 运行 [{selected_run.run_id[:16]}...] 暂无分析结果血缘")
            return

        print(f"\n运行 [{selected_run.run_id[:16]}...] {selected_run.keyword}")
        print(f"共 {len(lineage)} 条血缘记录:")
        print("="*60)

        for i, item in enumerate(lineage[:10], 1):  # 只显示前10条
            print(f"\n[{i}] BVID: {item['source']['bvid']}")
            print(f"    标题: {item['source'].get('title', '')}")
            print(f"    来源: {item['source']['source']} ({item['source']['source_type']})")
            print(f"    下载时间: {item['source'].get('downloaded_at', 'N/A')}")
            print(f"    处理模块: {item['processing']['module']}")
            print(f"    分析模式: {item['processing']['analysis_mode']}")
            print(f"    Prompt: {item['processing']['prompt_used'][:50]}...")
            print(f"    帧统计: 源 {item['processing']['source_frame_count']} / "
                  f"满足 {item['processing']['satisfied_frame_count']}")
            print(f"    生成时间: {item['output']['generated_at']}")

        if len(lineage) > 10:
            print(f"\n... 还有 {len(lineage) - 10} 条记录未显示")

    def set_download_path(self):
        """设置下载路径"""
        path = input("请输入新的下载路径: ").strip()
        if path:
            # 标准化路径
            path = os.path.normpath(path)
            os.makedirs(path, exist_ok=True)
            self.download_path = path

            # 更新配置文件
            self.config['download_path'] = path
            try:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, ensure_ascii=False, indent=2)
                print(f"[信息] 下载路径已更新为: {path}")
            except Exception as e:
                print(f"[警告] 更新配置文件失败: {e}")
        else:
            print("路径不能为空")

    def run(self):
        """运行主循环"""
        try:
            while True:
                self.print_menu()
                choice = self.input_choice("请输入选择: ", ['1', '2', '3', '4', '5', '6', '7', '8'])

                if choice == '1':
                    self.search_and_download_video(use_refined=True)
                elif choice == '2':
                    self.search_up_and_download(use_refined=True)
                elif choice == '3':
                    self.resume_run()
                elif choice == '4':
                    self.show_history()
                elif choice == '5':
                    self.show_lineage()
                elif choice == '6':
                    self.set_download_path()
                elif choice == '7':
                    print("[功能] 线程数量在执行任务时设置")
                elif choice == '8':
                    # 退出前停止流水线
                    if self.pipeline:
                        print("[退出] 正在停止流水线...")
                        self.pipeline.stop()
                        print("[退出] 流水线已停止")
                        self.pipeline = None
                    print("再见!")
                    return

                # 等待3秒缓冲，确保后台线程完成清理
                time.sleep(3)
                input("\n按回车键继续...")
        except KeyboardInterrupt:
            # 用户按 Ctrl+C 中断
            if self.pipeline:
                print("\n[中断] 正在停止流水线...")
                # V3: 中断时保留断点
                if self.pipeline.current_run:
                    self.cpm.stop(self.pipeline.current_run.run_id)
                    print(f"[中断] 运行已暂停: {self.pipeline.current_run.run_id}")
                self.pipeline.stop()
            print("再见!")
            import sys
            sys.exit(0)
        finally:
            # 确保流水线被停止
            if self.pipeline:
                self.pipeline.stop()


if __name__ == '__main__':
    cli = IntegratedCLIV3()
    cli.run()
