#!/usr/bin/env python3
"""
B站爬虫 + 大模型筛选整合命令行界面
主入口文件
"""

import os
import sys
import json

# 添加爬虫模块路径（爬虫核心库位于 bilibili爬虫/src）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bilibili爬虫', 'src'))

# 导入爬虫原有组件
from model.bilibili_api import BilibiliAPI
from downloaders.video_downloader import VideoDownloader
from downloaders.tv_downloader import TvDownloader
from downloaders.download_manager import DownloadManager, PaginatedDownloadManager
from ffmpeg.merger import FFMpegMerger

# 添加大模型筛选模块路径（筛选模块在 大模型接入筛选 目录）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '大模型接入筛选'))

class IntegratedCLI:
    """整合爬虫和大模型筛选的命令行界面"""
    
    def __init__(self):
        # 配置文件路径（爬虫的配置文件）
        self.config_file = os.path.join(os.path.dirname(__file__), 'bilibili爬虫', 'config.json')
        
        # 加载配置
        self.config = self._load_config()
        
        # 初始化爬虫组件
        self.api = BilibiliAPI()
        self.video_downloader = VideoDownloader()
        self.tv_downloader = TvDownloader()
        self.merger = FFMpegMerger()
        
        # 从配置加载下载路径
        self.download_path = self.config.get('download_path', os.path.join(os.path.expanduser('~'), 'Downloads', 'bilibili'))
        
        # 设置下载器路径（与配置文件同步）
        self.video_downloader.download_path = os.path.join(self.download_path, 'videos')
        self.tv_downloader.download_path = os.path.join(self.download_path, 'tv')
        
        # 从配置加载Cookie路径
        cookies_path = self.config.get('cookies_path', '')
        if cookies_path and os.path.exists(cookies_path):
            self.video_downloader.cookies_path = cookies_path
            self.tv_downloader.cookies_path = cookies_path
        
        # 从配置加载下载器设置
        self.video_downloader.use_ytdlp = self.config.get('use_ytdlp', True)
        self.tv_downloader.use_ytdlp = self.config.get('use_ytdlp', True)
        
        # 检查ffmpeg
        if not self.merger.ffmpeg_path:
            print("[警告] 未找到ffmpeg，音视频合并功能将不可用")
        else:
            print(f"[信息] ffmpeg路径: {self.merger.ffmpeg_path}")
        
        # 筛选功能相关
        self.filter_enabled = False
        self.filter_prompt = ""
        self.filter_api = None
        self.use_refined_analysis = False
        self._init_filter_api()
    
    def _init_filter_api(self):
        """初始化筛选API（延迟导入）"""
        try:
            # 导入大模型筛选模块
            from filter_api import VideoFilterAPI, create_filter_api_from_config
            
            # 构建配置文件路径：大模型接入筛选/config.json
            # 当前文件路径: integrated_cli.py
            filter_config_path = os.path.join(os.path.dirname(__file__), '大模型接入筛选', 'config.json')
            
            if os.path.exists(filter_config_path):
                with open(filter_config_path, 'r', encoding='utf-8') as f:
                    filter_config = json.load(f)
                    api_key = filter_config.get('api_key', '')
                    
                    # 读取配置文件中的prompt
                    self.default_filter_prompt = filter_config.get('prompt', '')
                    
                    if api_key:
                        self.filter_api = create_filter_api_from_config(filter_config_path)
                        print(f"[信息] 视频筛选API已初始化")
                        if self.default_filter_prompt:
                            print(f"[信息] 已加载默认筛选Prompt: {self.default_filter_prompt[:30]}...")
                        else:
                            print(f"[信息] 未配置默认筛选Prompt")
                    else:
                        print("[信息] 未配置智谱API Key，筛选功能不可用")
            else:
                print(f"[信息] 未找到筛选配置文件: {filter_config_path}")
                self.default_filter_prompt = ""
                
        except ImportError as e:
            print(f"[信息] 无法导入筛选模块: {str(e)}")
            print(f"[信息] 请确保 大模型接入筛选 目录在正确路径下")
            self.default_filter_prompt = ""
        except Exception as e:
            print(f"[信息] 初始化筛选API失败: {str(e)}")
            self.default_filter_prompt = ""
    
    def _load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[警告] 加载配置文件失败: {e}")
        return {}
    
    def print_menu(self):
        """打印主菜单"""
        print("="*60)
        print("      B站爬虫 + 大模型筛选整合界面")
        print("="*60)
        print("1. 搜索视频（普通下载）")
        print("2. 搜索UP主（普通下载）")
        print("3. 搜索TV剧集（普通下载）")
        print("4. 搜索视频（下载后筛选）")
        print("5. 搜索UP主（下载后筛选）")
        print("6. 搜索视频（精细化分析）")
        print("7. 搜索UP主（精细化分析）")
        print("8. 批量合并分离音视频")
        print("9. 设置下载路径")
        print("10. 设置Cookie路径")
        print("11. 退出")
        print("="*60)
        print(f"当前配置:")
        print(f"  下载路径: {self.download_path}")
        print(f"  Cookie路径: {'已设置' if self.video_downloader.cookies_path else '未设置'}")
        print(f"  筛选功能: {'可用' if self.filter_api else '不可用'}")
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
        """启用筛选功能并获取检测prompt（优先使用配置文件中的默认prompt）"""
        if not self.filter_api:
            print("[错误] 筛选功能不可用，请检查智谱API Key配置")
            return False
        
        # 设置分析模式
        self.use_refined_analysis = use_refined
        
        # 如果配置文件中有默认prompt，直接使用
        if self.default_filter_prompt:
            self.filter_prompt = self.default_filter_prompt
            self.filter_enabled = True
            mode_text = "精细化分析" if use_refined else "普通分析"
            print(f"[筛选] 已启用筛选功能（{mode_text}），使用配置文件中的默认Prompt: {self.filter_prompt}")
            return True
        
        # 否则让用户输入
        prompt = input("请输入筛选检测的Prompt: ").strip()
        if not prompt:
            print("Prompt不能为空")
            return False
        
        self.filter_prompt = prompt
        self.filter_enabled = True
        mode_text = "精细化分析" if use_refined else "普通分析"
        print(f"[筛选] 已启用筛选功能（{mode_text}），检测Prompt: {prompt}")
        return True
    
    def _analyze_downloaded_video(self, video_path):
        """分析已下载的视频"""
        if not self.filter_enabled or not self.filter_api:
            return True
        
        print(f"\n[筛选] 开始筛选视频: {os.path.basename(video_path)}")
        
        # 根据设置决定使用普通分析还是精细化分析
        filter_result = self.filter_api.analyze_video(video_path, self.filter_prompt, use_refined=self.use_refined_analysis)
        
        if filter_result['success']:
            is_satisfied = filter_result['is_satisfied']
            analysis_mode = filter_result.get('analysis_mode', 'normal')
            mode_text = "精细化分析" if analysis_mode == 'refined' else "普通分析"
            
            print(f"[筛选] 分析模式: {mode_text}")
            print(f"[筛选] 视频筛选结果: {'YES' if is_satisfied else 'NO'}")
            print(f"[筛选] satisfied占比: {filter_result['satisfied_ratio']*100:.1f}%")
            
            # 如果是精细化分析，输出更多信息
            if analysis_mode == 'refined':
                print(f"[筛选] 状态: {filter_result.get('status', '')}")
                print(f"[筛选] 初始满足率: {filter_result.get('initial_ratio', 0.0)*100:.1f}%")
                print(f"[筛选] 迭代次数: {filter_result.get('iterations', 1)}")
            
            return is_satisfied
        else:
            print(f"[筛选] 筛选失败: {filter_result['message']}")
            return True  # 筛选失败时默认继续
    
    def _get_downloaded_video_path(self, title):
        """获取已下载视频的路径"""
        download_path = getattr(self.video_downloader, 'download_path', '')
        
        if not download_path or not os.path.exists(download_path):
            return None
        
        # 清理标题中的非法字符
        import re
        title_clean = re.sub(r'[\\/:*?"<>|]', '_', title).strip()
        
        # 查找下载的视频文件
        for ext in ['.mp4', '.flv', '.webm', '.mkv']:
            video_path = os.path.join(download_path, title_clean + ext)
            if os.path.exists(video_path):
                return video_path
            
            # 尝试带序号的文件名
            for i in range(1, 10):
                video_path = os.path.join(download_path, f"{title_clean}_{i}{ext}")
                if os.path.exists(video_path):
                    return video_path
        
        # 如果找不到精确匹配，尝试模糊匹配
        for filename in os.listdir(download_path):
            if title_clean[:10] in filename and filename.endswith(('.mp4', '.flv', '.webm', '.mkv')):
                return os.path.join(download_path, filename)
        
        return None
    
    def search_and_download_video_with_filter(self, use_refined: bool = False):
        """搜索并下载视频（带筛选功能）"""
        # 检查并启用筛选
        if not self._enable_filter_with_prompt(use_refined=use_refined):
            return
        
        keyword = input("\n请输入搜索关键词: ").strip()
        if not keyword:
            print("关键词不能为空")
            return
        
        # 创建下载目录
        os.makedirs(self.download_path, exist_ok=True)
        self.video_downloader.download_path = os.path.join(self.download_path, 'videos')
        
        # 获取下载数量
        while True:
            count_input = input("请输入要下载的数量（0表示全部下载）: ").strip()
            if count_input.isdigit():
                download_count = int(count_input)
                if download_count >= 0:
                    break
            print("请输入有效的非负整数")
        
        print(f"\n[下载] 开始下载（目标: {'全部' if download_count == 0 else download_count} 个满足条件的视频）")
        print(f"[下载] 筛选模式: 启用，检测Prompt: {self.filter_prompt}")
        print(f"[下载] 分析模式: {'精细化分析' if self.use_refined_analysis else '普通分析'}")
        
        page = 1
        page_size = 20
        downloaded_count = 0
        
        while True:
            # 重置标志位（每进入新的一页就重置）
            reached_target = False
            
            print(f"\n[获取] 正在获取第 {page} 页...")
            
            try:
                items, total = self.api.search_videos(keyword, page=page, page_size=page_size)
            except Exception as e:
                print(f"[错误] 获取第 {page} 页失败: {str(e)}")
                page += 1
                continue
            
            if not items:
                print("[完成] 已获取全部内容")
                break
            
            # 检查是否已经达到下载数量（在处理当前页之前检查）
            if download_count > 0 and downloaded_count >= download_count:
                break
            
            print(f"[下载] 当前页有 {len(items)} 个视频，已下载 {downloaded_count}/{download_count if download_count > 0 else '?'} 个满足条件的视频")
            
            # 下载当前页的所有项目（必须全部遍历，不能遗漏）
            for item in items:
                bvid = item.get('bvid', '')
                title = item.get('title', '未知')
                
                if not bvid:
                    print(f"[{downloaded_count + 1}/{'?' if download_count == 0 else download_count}] [跳过] 无BV号: {title}")
                    continue
                
                print(f"\n[{downloaded_count + 1}/{'?' if download_count == 0 else download_count}] 正在下载: {title}")
                print(f"      BV号: {bvid}")
                
                success, msg = self.video_downloader.download(bvid, title)
                
                if success:
                    print(f"      [成功] 下载完成")
                    
                    # 调用筛选功能
                    video_path = self._get_downloaded_video_path(title)
                    if video_path:
                        is_satisfied = self._analyze_downloaded_video(video_path)
                        
                        # 根据分析结果决定是否计入下载数量
                        if is_satisfied:
                            downloaded_count += 1
                            print(f"      [筛选] 视频满足要求，计入下载数量")
                            
                            # 检查是否达到下载数量（达到后立即退出循环）
                            if download_count > 0 and downloaded_count >= download_count:
                                print(f"\n[完成] 已达到设定的下载数量 ({downloaded_count} 个)")
                                # 使用标志位退出多层循环
                                reached_target = True
                                break
                        else:
                            print(f"      [筛选] 视频不满足要求，不计入下载数量")
                    else:
                        print(f"      [筛选警告] 未找到下载的视频文件")
                        # 未找到文件时不计入下载数量（下载失败）
                        
                        # 检查是否达到下载数量
                        if download_count > 0 and downloaded_count >= download_count:
                            print(f"\n[完成] 已达到设定的下载数量 ({downloaded_count} 个)")
                            reached_target = True
                            break
                else:
                    print(f"      [失败] {msg}")
            
            # 如果已经达到目标数量，退出外层循环
            if reached_target:
                break
            
            # 检查是否达到下载数量（在当前页全部处理完后检查）
            if download_count > 0 and downloaded_count >= download_count:
                print(f"\n[完成] 已达到设定的下载数量 ({downloaded_count} 个)")
                break
            
            # 翻页
            page += 1
        
        print(f"\n[完成] 下载结束，共下载 {downloaded_count} 个视频")
        
        # 重置筛选状态
        self.filter_enabled = False
    
    def search_up_with_filter(self, use_refined: bool = False):
        """搜索UP主并下载其视频（带筛选功能）"""
        # 检查并启用筛选
        if not self._enable_filter_with_prompt(use_refined=use_refined):
            return
        
        keyword = input("请输入UP主名称: ").strip()
        if not keyword:
            print("关键词不能为空")
            return
        
        print(f"\n[搜索] 正在搜索UP主: {keyword}...")
        users = self.api.search_users(keyword, max_results=10)
        
        if not users:
            print("未找到相关UP主")
            return
        
        print(f"\n[搜索结果] 共找到 {len(users)} 个UP主，显示前10个")
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
            
            if not choice.isdigit():
                print("请输入有效的数字")
                continue
            
            idx = int(choice) - 1
            if 0 <= idx < len(users):
                selected_user = users[idx]
                break
            else:
                print("请输入有效的序号")
        
        print(f"\n[选择] 已选择UP主: {selected_user['name']} (UID: {selected_user['mid']})")
        
        # 获取下载数量
        while True:
            count_input = input("请输入要下载的视频数量（0表示全部下载）: ").strip()
            if count_input.isdigit():
                download_count = int(count_input)
                if download_count >= 0:
                    break
            else:
                print("请输入有效的数字")
        
        print(f"\n[下载] 开始下载（目标: {'全部' if download_count == 0 else download_count} 个满足条件的视频）")
        print(f"[下载] 筛选模式: 启用，检测Prompt: {self.filter_prompt}")
        print(f"[下载] 分析模式: {'精细化分析' if self.use_refined_analysis else '普通分析'}")
        
        page = 1
        page_size = 20
        downloaded_count = 0
        
        while True:
            # 重置标志位（每进入新的一页就重置）
            reached_target = False
            
            print(f"\n[获取] 正在获取第 {page} 页...")
            
            try:
                items, total = self.api.get_user_videos(mid=selected_user['mid'], page=page, page_size=page_size)
            except Exception as e:
                print(f"[错误] 获取第 {page} 页失败: {str(e)}")
                page += 1
                continue
            
            if not items:
                print("[完成] 已获取全部内容")
                break
            
            # 计算当前页需要下载的数量
            if download_count > 0:
                remaining = download_count - downloaded_count
                if remaining <= 0:
                    break
                to_download = min(remaining, len(items))
            else:
                to_download = len(items)
            
            # 下载当前页的项目
            for i in range(to_download):
                item = items[i]
                bvid = item.get('bvid', '')
                title = item.get('title', '未知')
                
                if not bvid:
                    print(f"[{downloaded_count + 1}/{'?' if download_count == 0 else download_count}] [跳过] 无BV号: {title}")
                    continue
                
                print(f"\n[{downloaded_count + 1}/{'?' if download_count == 0 else download_count}] 正在下载: {title}")
                print(f"      BV号: {bvid}")
                
                success, msg = self.video_downloader.download(bvid, title)
                
                if success:
                    print(f"      [成功] 下载完成")
                    
                    # 调用筛选功能
                    video_path = self._get_downloaded_video_path(title)
                    if video_path:
                        is_satisfied = self._analyze_downloaded_video(video_path)
                        
                        # 根据分析结果决定是否计入下载数量
                        if is_satisfied:
                            downloaded_count += 1
                            print(f"      [筛选] 视频满足要求，计入下载数量")
                        else:
                            print(f"      [筛选] 视频不满足要求，不计入下载数量")
                    else:
                        print(f"      [筛选警告] 未找到下载的视频文件")
                        # 未找到文件时不计入下载数量（下载失败）
                else:
                    print(f"      [失败] {msg}")
                
                # 检查是否达到下载数量
                if download_count > 0 and downloaded_count >= download_count:
                    print(f"\n[完成] 已达到设定的下载数量 ({downloaded_count} 个)")
                    break
            
            # 检查是否达到下载数量
            if download_count > 0 and downloaded_count >= download_count:
                break
            
            # 翻页
            page += 1
        
        print(f"\n[完成] 下载结束，共下载 {downloaded_count} 个视频")
        
        # 重置筛选状态
        self.filter_enabled = False
    
    def search_and_download_video(self):
        """搜索并下载视频（普通模式）"""
        from cli import BilibiliCLI
        original_cli = BilibiliCLI()
        original_cli.search_and_download_video()
    
    def search_up(self):
        """搜索UP主并下载（普通模式）"""
        from cli import BilibiliCLI
        original_cli = BilibiliCLI()
        original_cli.search_up()
    
    def search_and_download_tv(self):
        """搜索TV剧集（普通模式）"""
        from cli import BilibiliCLI
        original_cli = BilibiliCLI()
        original_cli.search_and_download_tv()
    
    def batch_merge_files(self):
        """批量合并（调用原有方法）"""
        from cli import BilibiliCLI
        original_cli = BilibiliCLI()
        original_cli.batch_merge_files()
    
    def set_download_path(self):
        """设置下载路径"""
        from cli import BilibiliCLI
        original_cli = BilibiliCLI()
        original_cli.set_download_path()
        # 更新自身的下载路径
        self.download_path = original_cli.download_path
    
    def set_cookies_path(self):
        """设置Cookie路径"""
        from cli import BilibiliCLI
        original_cli = BilibiliCLI()
        original_cli.set_cookies_path()
    
    def run(self):
        """运行整合命令行界面"""
        print("欢迎使用B站爬虫 + 大模型筛选整合界面！")
        print(f"默认下载路径: {self.download_path}")
        print()
        
        while True:
            self.print_menu()
            choice = self.input_choice("请输入选项 (1-11): ", ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11'])
            
            if choice == '1':
                self.search_and_download_video()
            elif choice == '2':
                self.search_up()
            elif choice == '3':
                self.search_and_download_tv()
            elif choice == '4':
                self.search_and_download_video_with_filter(use_refined=False)
            elif choice == '5':
                self.search_up_with_filter(use_refined=False)
            elif choice == '6':
                self.search_and_download_video_with_filter(use_refined=True)
            elif choice == '7':
                self.search_up_with_filter(use_refined=True)
            elif choice == '8':
                self.batch_merge_files()
            elif choice == '9':
                self.set_download_path()
            elif choice == '10':
                self.set_cookies_path()
            elif choice == '11':
                print("感谢使用，再见！")
                break
            
            input("\n按回车键继续...")

if __name__ == "__main__":
    cli = IntegratedCLI()
    cli.run()
