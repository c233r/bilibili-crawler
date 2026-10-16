"""
B站爬虫 + 大模型筛选整合命令行界面（多线程版）
主入口文件，使用流水线架构实现并行下载和分析
"""

import os
import sys
import json
from datetime import datetime
import time

# 添加模块路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bilibili爬虫', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'pipeline'))

from pipeline.control.pipeline_main import VideoPipeline
from pipeline.log.logger import get_main_logger
from model.bilibili_api import BilibiliAPI

class IntegratedCLIMultiproc:
    """集成CLI多线程版本"""
    
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
        
        # 日志器
        self.logger = get_main_logger()
        
        print("[信息] 多线程CLI已初始化")
        print(f"[信息] 下载路径: {self.download_path}")
    
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
        
        print("="*60)
        print("      B站爬虫 + 大模型筛选整合界面（多线程版）")
        print("="*60)
        print("1. 搜索视频（多线程下载+筛选）")
        print("2. 搜索UP主（多线程下载+筛选）")
        # print("3. 搜索视频（精细化分析）")
        # print("4. 搜索UP主（精细化分析）")
        print("5. 设置下载路径")
        print("6. 设置线程数量")
        print("7. 退出")
        print("="*60)
        print(f"当前配置:")
        print(f"  下载路径: {self.download_path}")
        print(f"  筛选功能: {'可用' if self.filter_enabled else '未启用'}")
        if self.filter_enabled:
            print(f"  筛选Prompt: {self.filter_prompt}")
            print(f"  分析模式: {'精细化分析' if self.use_refined_analysis else '普通分析'}")
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
    
    def _init_pipeline(self, total_workers: int = 5):
        """初始化流水线"""
        print(f"[流水线] 初始化中... (总线程数: {total_workers})")
        self.pipeline = VideoPipeline(total_workers=total_workers)
        
        while True:
            enable_push = input("是否启用视频推送至EdgeCrafter服务器？(y/n): ").strip().lower()
            if enable_push in ['y', 'n']:
                break
            print("请输入 y 或 n")
        
        if enable_push == 'y':
            api_url = input("请输入EdgeCrafter API地址（默认: http://localhost:8000）: ").strip()
            if not api_url:
                api_url = 'http://localhost:8000'
            self.pipeline.enable_video_push(api_url=api_url)
        
        print("[流水线] 初始化完成")
    
    def search_and_download_video(self, use_refined=False):
        """搜索并下载视频（多线程版）"""
        if not self._enable_filter_with_prompt(use_refined=use_refined):
            return
        
        keyword = input("\n请输入搜索关键词: ").strip()
        if not keyword:
            print("关键词不能为空")
            return
        
        while True:
            count_input = input("请输入要下载的数量（0表示全部下载）: ").strip()
            if count_input.isdigit():
                download_count = int(count_input)
                if download_count >= 0:
                    break
            print("请输入有效的非负整数")
        
        while True:
            worker_input = input("请输入总线程数量（默认5，动态分配下载和分析）: ").strip()
            if worker_input == "":
                total_workers = 5
                break
            if worker_input.isdigit() and int(worker_input) > 0:
                total_workers = int(worker_input)
                break
            print("请输入有效的正整数")
        
        print(f"\n[下载] 开始下载（目标: {'全部' if download_count == 0 else download_count} 个满足条件的视频）")
        print(f"[下载] 筛选模式: 启用，检测Prompt: {self.filter_prompt}")
        print(f"[下载] 分析模式: {'精细化分析' if self.use_refined_analysis else '普通分析'}")
        print(f"[下载] 线程配置: {total_workers}个线程（动态分配）")
        
        self._init_pipeline(total_workers=total_workers)
        
        self.pipeline.set_filter_prompt(self.filter_prompt, self.use_refined_analysis)
        
        try:
            # 搜索视频
            api = BilibiliAPI()
            page = 1
            page_size =20
            total_videos_found = 0
            
            # 启动流水线（只启动一次）
            self.pipeline.start()
            
            # 立即设置目标条件数量，让监控线程开始监控
            self.pipeline.target_satisfied = download_count
            if download_count > 0:
                self.logger.info(f"[监控] 目标满足条件视频数已设置为: {download_count}")
            else:
                self.logger.info(f"[监控] 未设置目标条件数（全部下载）")
            
            pending_items = []  # 暂存队列满时未能添加的视频
            
            while True:
                # 检查是否达到目标数量（在获取新页面前先检查）
                stats = self.pipeline.print_statistics()
                satisfied_count = stats.get('satisfied_count', 0)
                
                if download_count > 0 and satisfied_count >= download_count:
                    print(f"\n[完成] 已达到设定的下载数量 ({satisfied_count} 个)")
                    break
                
                # 先尝试添加之前暂存的视频
                if pending_items:
                    _, pending_items = self.pipeline.add_download_tasks(pending_items)
                
                print(f"\n[获取] 正在获取第 {page} 页...")
                
                try:
                    items, total = api.search_videos(keyword, page=page, page_size=page_size)
                except Exception as e:
                    print(f"[错误] 获取第 {page} 页失败: {str(e)}")
                    page += 1
                    continue
                
                if not items:
                    print("[完成] 已获取全部内容")
                    break
                
                total_videos_found += len(items)
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
                stats = self.pipeline.print_statistics()
                satisfied_count = stats.get('satisfied_count', 0)
                
                if download_count > 0 and satisfied_count >= download_count:
                    print(f"\n[完成] 已达到设定的下载数量 ({satisfied_count} 个)")
                    break
                
                # 翻页继续获取
                page += 1
            
            # 所有搜索结果都获取完毕，等待最终完成
            self.pipeline.wait_until_complete(target_satisfied=download_count)
            
            # 推送满足条件的视频
            self.pipeline.push_satisfied_videos()
            
            # 打印最终统计
            self.pipeline.print_statistics()
            
        finally:
            # 停止流水线
            if self.pipeline:
                self.pipeline.stop()
        
        # 重置筛选状态
        self.filter_enabled = False
    
    def search_up_and_download(self, use_refined=False):
        """搜索UP主并下载其视频（多线程版）"""
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
        
        # 获取下载数量
        while True:
            count_input = input("请输入要下载的数量（0表示全部下载）: ").strip()
            if count_input.isdigit():
                download_count = int(count_input)
                if download_count >= 0:
                    break
            print("请输入有效的非负整数")
        
        # 获取线程数量
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
        
        print(f"\n[下载] 开始下载UP主: {user_name} 的视频")
        print(f"[下载] 目标: {'全部' if download_count == 0 else download_count} 个满足条件的视频")
        print(f"[下载] 筛选模式: 启用，检测Prompt: {self.filter_prompt}")
        print(f"[下载] 分析模式: {'精细化分析' if self.use_refined_analysis else '普通分析'}")
        print(f"[下载] 线程配置: {download_workers}个下载线程, {analyze_workers}个分析线程")
        
        # 初始化流水线
        total_workers = download_workers + analyze_workers
        self._init_pipeline(total_workers=total_workers)
        
        # 设置筛选Prompt
        self.pipeline.set_filter_prompt(self.filter_prompt, self.use_refined_analysis)
        
        try:
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
            self.pipeline.wait_until_complete(target_satisfied=download_count)
            
            # 推送满足条件的视频
            self.pipeline.push_satisfied_videos()
            
            # 打印最终统计
            self.pipeline.print_statistics()
            
        finally:
            # 停止流水线
            if self.pipeline:
                self.pipeline.stop()
        
        # 重置筛选状态
        self.filter_enabled = False
    
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
                choice = self.input_choice("请输入选择: ", ['1', '2', '5', '6', '7'])
                
                if choice == '1':
                    self.search_and_download_video(use_refined=True)
                elif choice == '2':
                    self.search_up_and_download(use_refined=True)
                # elif choice == '3':
                #     self.search_and_download_video(use_refined=True)
                # elif choice == '4':
                #     self.search_up_and_download(use_refined=True)
                elif choice == '5':
                    self.set_download_path()
                elif choice == '6':
                    print("[功能] 线程数量在执行任务时设置")
                elif choice == '7':
                    # 退出前停止流水线
                    if self.pipeline:
                        print("[退出] 正在停止流水线...")
                        self.pipeline.stop()
                        print("[退出] 流水线已停止")
                        # 设置为 None，下次进入菜单时重新初始化
                        self.pipeline = None
                    print("再见!")
                
                # 等待3秒缓冲，确保后台线程完成清理
                time.sleep(3)
                input("\n按回车键继续...")
        except KeyboardInterrupt:
            # 用户按 Ctrl+C 中断
            if self.pipeline:
                print("\n[中断] 正在停止流水线...")
                self.pipeline.stop()
            print("再见!")
            # 强制退出主线程，守护线程会被立即终止
            import sys
            sys.exit(0)
        finally:
            # 确保流水线被停止
            if self.pipeline:
                self.pipeline.stop()

if __name__ == '__main__':
    cli = IntegratedCLIMultiproc()
    cli.run()
