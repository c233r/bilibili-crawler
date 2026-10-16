#!/usr/bin/env python3
"""
B站爬虫命令行界面
适用于服务器环境，无需图形界面
"""

import os
import sys
import json

# 添加src目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from model.bilibili_api import BilibiliAPI
from downloaders.video_downloader import VideoDownloader
from downloaders.tv_downloader import TvDownloader
from downloaders.download_manager import DownloadManager, PaginatedDownloadManager
from ffmpeg.merger import FFMpegMerger

class BilibiliCLI:
    """B站爬虫命令行界面"""
    
    def __init__(self):
        # 配置文件路径
        self.config_file = os.path.join(os.path.dirname(__file__), '..', 'config.json')
        
        # 加载配置
        self.config = self._load_config()
        
        # 初始化组件
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
    
    def _load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[警告] 加载配置文件失败: {e}")
        return {}
    
    def _save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[错误] 保存配置文件失败: {e}")
            return False
    
    def print_menu(self):
        """打印主菜单"""
        print("="*60)
        print("          B站爬虫命令行界面")
        print("="*60)
        print("1. 搜索视频")
        print("2. 搜索UP主")
        print("3. 搜索TV剧集")
        print("4. 批量合并分离音视频")
        print("5. 设置下载路径")
        print("6. 设置Cookie路径")
        print("7. 退出")
        print("="*60)
        # 显示当前配置
        print(f"当前配置:")
        print(f"  下载路径: {self.download_path}")
        print(f"  Cookie路径: {'已设置' if self.video_downloader.cookies_path else '未设置'}")
        print("="*60)
    
    def input_choice(self, prompt, valid_choices=None):
        """获取用户输入并验证"""
        while True:
            choice = input(prompt).strip()
            if valid_choices and choice not in valid_choices:
                print(f"无效选项，请输入: {', '.join(valid_choices)}")
                continue
            return choice
    
    def _select_download_mode(self):
        """选择下载模式"""
        print("\n" + "="*60)
        print("                    下载模式选择")
        print("="*60)
        print("1. 选择特定序号下载")
        print("2. 指定下载数量（自动从前往后）")
        print("3. 下载全部（自动翻页）")
        print("4. 返回")
        print("="*60)
        
        while True:
            choice = input("请选择下载模式 (1-4): ").strip()
            if choice in ['1', '2', '3', '4']:
                break
            print("请输入有效的选项")
        
        if choice == '4':
            return 'cancel', 0
        
        if choice == '1':
            # 选择特定序号下载
            return 'select', 0
        elif choice == '2':
            # 指定下载数量
            while True:
                count_input = input("\n请输入要下载的数量: ").strip()
                if count_input.isdigit():
                    count = int(count_input)
                    if count > 0:
                        break
                print("请输入有效的正整数")
            return 'count', count
        elif choice == '3':
            # 下载全部
            return 'all', 0
    
    def search_and_download_video(self):
        """搜索并下载视频（支持翻页）"""
        # 先选择下载模式
        download_mode, download_count = self._select_download_mode()
        
        if download_mode == 'cancel':
            return
        
        keyword = input("\n请输入搜索关键词: ").strip()
        if not keyword:
            print("关键词不能为空")
            return
        
        # 创建下载目录
        os.makedirs(self.download_path, exist_ok=True)
        self.video_downloader.download_path = os.path.join(self.download_path, 'videos')
        
        # 如果是自动下载模式（指定数量或全部下载）
        if download_mode in ['count', 'all']:
            # 使用分页下载管理器
            manager = PaginatedDownloadManager(
                downloader=self.video_downloader,
                api_getter=self.api.search_videos,
                api_params={'keyword': keyword}
            )
            manager.download_with_pagination(download_count=download_count)
            return
        
        # 选择序号模式，手动选择下载
        current_page = 1
        page_size = 20
        all_videos = []
        
        while True:
            print(f"\n[搜索] 正在搜索视频: {keyword} (第 {current_page} 页)...")
            videos, total = self.api.search_videos(keyword, page=current_page, page_size=page_size)
            
            if not videos and current_page == 1:
                print("未找到相关视频")
                return
            
            # 累计视频列表
            all_videos.extend(videos)
            
            # 计算显示范围
            start_idx = (current_page - 1) * page_size + 1
            end_idx = min(start_idx + page_size - 1, len(all_videos))
            
            print(f"\n[搜索结果] 第 {current_page} 页，共找到约 {total} 个视频")
            print(f"当前显示: 第 {start_idx}-{end_idx} 个")
            print("-"*60)
            
            for i, video in enumerate(videos, start_idx):
                print(f"{i:3d}. {video['title']}")
                print(f"        UP主: {video.get('author', '未知')}")
                play_count = video.get('play') or 0
                danmaku_count = video.get('danmaku') or 0
                print(f"        播放量: {play_count:,} | 弹幕: {danmaku_count:,}")
                print(f"        BV号: {video.get('bvid', '')}")
                print()
            
            # 显示操作选项
            print("-"*60)
            print("操作选项:")
            print("  n - 下一页")
            print("  p - 上一页")
            print("  数字 - 跳转到指定页")
            print("  序号 - 下载指定视频（如: 1,3,5）")
            print("  q - 返回主菜单")
            
            choice = input("\n请输入操作: ").strip().lower()
            
            if choice == 'q':
                return
            elif choice == 'n':
                if end_idx >= total:
                    print("已经是最后一页")
                    continue
                current_page += 1
            elif choice == 'p':
                if current_page > 1:
                    current_page -= 1
                else:
                    print("已经是第一页")
            elif choice.isdigit():
                num = int(choice)
                if num <= 0:
                    print("无效输入")
                    continue
                
                total_pages = (total + page_size - 1) // page_size
                if num <= total_pages:
                    current_page = num
                else:
                    if num <= len(all_videos):
                        self._handle_video_selection([all_videos[num-1]])
                    else:
                        print("视频序号超出范围")
            elif ',' in choice:
                try:
                    indices = [int(x.strip())-1 for x in choice.split(',') if x.strip().isdigit()]
                    selected_videos = [all_videos[i] for i in indices if 0 <= i < len(all_videos)]
                    if selected_videos:
                        self._handle_video_selection(selected_videos)
                    else:
                        print("无效的选择")
                except ValueError:
                    print("输入格式错误")
            else:
                print("无效输入")
    
    def _handle_video_selection(self, videos):
        """处理视频选择后的操作"""
        print(f"\n[选择] 已选择 {len(videos)} 个视频")
        
        # 显示选择的视频列表
        for i, video in enumerate(videos, 1):
            print(f"{i:2d}. {video['title']}")
            print(f"      BV号: {video.get('bvid', '')}")
            print(f"      UP主: {video.get('author', '未知')}")
        
        # 使用下载管理器
        manager = DownloadManager(self.video_downloader)
        
        print("\n操作选项:")
        print("  d - 下载视频（含音频）")
        print("  v - 只下载视频（无音频）")
        print("  i - 仅查看详细信息")
        print("  q - 返回搜索结果")
        
        choice = input("\n请选择操作: ").strip().lower()
        
        if choice == 'd':
            self.video_downloader.download_audio = True
            self._download_selected_videos(videos)
        elif choice == 'v':
            self.video_downloader.download_audio = False
            self._download_selected_videos(videos)
            self.video_downloader.download_audio = True  # 恢复默认
        elif choice == 'i':
            self._show_video_details(videos)
        elif choice == 'q':
            return
        else:
            print("无效输入")
    
    def _download_selected_videos(self, videos):
        """下载选中的视频（使用下载管理器）"""
        print(f"\n[下载] 准备下载 {len(videos)} 个视频")
        if not self.video_downloader.download_audio:
            print("[下载] 模式: 只下载视频（无音频）")
        
        # 创建下载目录
        os.makedirs(self.download_path, exist_ok=True)
        self.video_downloader.download_path = os.path.join(self.download_path, 'videos')
        
        # 使用下载管理器下载
        manager = DownloadManager(self.video_downloader)
        success_count = manager.download_items(videos, item_type='video')
        
        print(f"\n下载完成！成功下载 {success_count} 个视频")
    
    def _show_video_details(self, videos):
        """显示视频详细信息"""
        print("\n" + "="*60)
        print("                    视频详细信息")
        print("="*60)
        
        for i, video in enumerate(videos, 1):
            print(f"\n视频 {i}:")
            print(f"  标题: {video.get('title', '未知')}")
            print(f"  BV号: {video.get('bvid', '')}")
            print(f"  UP主: {video.get('author', '未知')}")
            print(f"  UID: {video.get('mid', '')}")
            print(f"  播放量: {video.get('play', 0):,}")
            print(f"  弹幕数: {video.get('danmaku', 0):,}")
            print(f"  收藏数: {video.get('favorites', 0):,}")
            print(f"  点赞数: {video.get('like', 0):,}")
            print(f"  评论数: {video.get('review', 0):,}")
            print(f"  时长: {video.get('duration', '')}")
            print(f"  发布时间: {video.get('pubdate', '')}")
            print(f"  标签: {video.get('tag', '')}")
            print(f"  简介: {video.get('desc', '')[:100]}...")
            print(f"  播放链接: https://www.bilibili.com/video/{video.get('bvid', '')}")
        
        input("\n按回车键继续...")
    
    def search_up(self):
        """搜索UP主并下载其视频"""
        keyword = input("请输入UP主名称: ").strip()
        if not keyword:
            print("关键词不能为空")
            return
        
        print(f"\n[搜索] 正在搜索UP主: {keyword}...")
        users = self.api.search_users(keyword, max_results=10)
        total = len(users)
        
        if not users:
            print("未找到相关UP主")
            return
        
        print(f"\n[搜索结果] 共找到 {total} 个UP主，显示前10个")
        print("-"*60)
        
        for i, user in enumerate(users, 1):
            print(f"{i:2d}. {user['name']}")
            print(f"      UID: {user.get('mid', '')}")
            print(f"      粉丝数: {user.get('follower', 0):,} | 视频数: {user.get('archive_count', 0)}")
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
            if not count_input.isdigit():
                print("请输入有效的数字")
                continue
            
            download_count = int(count_input)
            if download_count >= 0:
                break
            else:
                print("请输入非负整数")
        
        # 开始获取并下载视频
        # 使用分页下载管理器
        manager = PaginatedDownloadManager(
            downloader=self.video_downloader,
            api_getter=self.api.get_user_videos,
            api_params={'mid': selected_user['mid']}
        )
        manager.download_with_pagination(download_count=download_count)
    
    def search_and_download_tv(self):
        """搜索并下载TV剧集（支持翻页）"""
        keyword = input("请输入剧集名称: ").strip()
        if not keyword:
            print("关键词不能为空")
            return
        
        current_page = 1
        page_size = 10
        all_tvs = []
        
        while True:
            print(f"\n[搜索] 正在搜索剧集: {keyword} (第 {current_page} 页)...")
            tvs, total = self.api.search_tv(keyword, page=current_page, page_size=page_size)
            
            if not tvs and current_page == 1:
                print("未找到相关剧集")
                return
            
            # 累计剧集列表
            all_tvs.extend(tvs)
            
            # 计算显示范围
            start_idx = (current_page - 1) * page_size + 1
            end_idx = min(start_idx + page_size - 1, len(all_tvs))
            
            print(f"\n[搜索结果] 第 {current_page} 页，共找到约 {total} 部剧集")
            print(f"当前显示: 第 {start_idx}-{end_idx} 部")
            print("-"*60)
            
            for i, tv in enumerate(tvs, start_idx):
                print(f"{i:2d}. {tv['title']}")
                print(f"        类型: {tv.get('type', '')} | 集数: {tv.get('episodes', 0)}")
                print(f"        评分: {tv.get('score', 0)} | 地区: {tv.get('areas', '')}")
                print(f"        season_id: {tv.get('season_id', '')}")
                print(f"        media_id: {tv.get('media_id', '')}")
                print()
            
            # 显示操作选项
            print("-"*60)
            print("操作选项:")
            print("  n - 下一页")
            print("  p - 上一页")
            print("  数字 - 下载指定剧集（输入序号即可下载该剧集的全部内容）")
            print("  q - 返回主菜单")
            
            choice = input("\n请输入操作: ").strip().lower()
            
            if choice == 'q':
                return
            elif choice == 'n':
                if end_idx >= total:
                    print("已经是最后一页")
                    continue
                current_page += 1
            elif choice == 'p':
                if current_page > 1:
                    current_page -= 1
                else:
                    print("已经是第一页")
            elif choice.isdigit():
                num = int(choice)
                if num <= 0:
                    print("无效输入")
                    continue
                
                # 作为剧集序号处理，下载该剧集的全部内容
                if num <= len(all_tvs):
                    self._handle_tv_selection([all_tvs[num-1]])
                else:
                    print("剧集序号超出范围")
            else:
                print("无效输入")
    
    def _handle_tv_selection(self, tvs):
        """处理剧集选择后的操作（直接下载全部剧集）"""
        print(f"\n[选择] 已选择 {len(tvs)} 部剧集")
        
        # 显示选择的剧集列表
        for i, tv in enumerate(tvs, 1):
            print(f"{i:2d}. {tv['title']}")
            print(f"      season_id: {tv.get('season_id', '')}")
            print(f"      集数: {tv.get('episodes', 0)}")
        
        # 创建下载目录
        os.makedirs(self.download_path, exist_ok=True)
        self.tv_downloader.download_path = os.path.join(self.download_path, 'tv')
        
        # 使用下载管理器直接下载全部剧集，不显示选择菜单
        manager = DownloadManager(self.tv_downloader)
        success_count = manager.download_items(tvs, item_type='tv')
        
        print(f"\n下载完成！成功下载 {success_count} 部剧集")
    
    def batch_merge_files(self):
        """批量合并分离音视频"""
        path = input(f"请输入要合并的目录路径（默认: {self.download_path}）: ").strip()
        if not path:
            path = self.download_path
        
        if not os.path.exists(path):
            print(f"目录不存在: {path}")
            return
        
        print(f"\n[合并] 开始批量合并，扫描目录: {path}")
        merged_files = self.merger.batch_merge(path)
        
        if merged_files:
            print(f"\n[成功] 共合并 {len(merged_files)} 个文件")
        else:
            print("\n[信息] 未发现需要合并的分离文件")
    
    def set_download_path(self):
        """设置下载路径"""
        new_path = input(f"请输入新的下载路径（当前: {self.download_path}）: ").strip()
        if not new_path:
            print("路径不能为空")
            return
        
        # 尝试创建目录
        try:
            os.makedirs(new_path, exist_ok=True)
            self.download_path = new_path
            self.video_downloader.download_path = os.path.join(new_path, 'videos')
            self.tv_downloader.download_path = os.path.join(new_path, 'tv')
            
            # 保存到配置文件
            self.config['download_path'] = new_path
            if self._save_config():
                print(f"下载路径已设置为: {new_path}")
                print("[提示] 配置已自动保存到 config.json")
            else:
                print(f"下载路径已设置为: {new_path}")
                print("[警告] 配置保存失败，请手动保存")
        except Exception as e:
            print(f"设置路径失败: {str(e)}")
    
    def set_cookies_path(self):
        """设置Cookie文件路径"""
        print("\n[设置Cookie]")
        print("提示: Cookie文件用于绕过B站反爬和获取高清视频权限")
        print("支持格式: cookies.txt (Netscape格式) 或 cookies.json")
        print()
        
        current_path = self.video_downloader.cookies_path or "未设置"
        path = input(f"请输入Cookie文件路径（当前: {current_path}）: ").strip()
        
        if not path:
            print("路径不能为空")
            return
        
        # 检查文件是否存在
        if os.path.exists(path):
            self.video_downloader.cookies_path = path
            self.tv_downloader.cookies_path = path
            
            # 保存到配置文件
            self.config['cookies_path'] = path
            if self._save_config():
                print(f"Cookie路径已设置为: {path}")
                print("[提示] 配置已自动保存到 config.json")
                print("[提示] 设置Cookie后可以下载高清视频并绕过部分反爬机制")
            else:
                print(f"Cookie路径已设置为: {path}")
                print("[警告] 配置保存失败，请手动保存")
        else:
            print(f"文件不存在: {path}")
            print("请确保Cookie文件路径正确")
    
    def run(self):
        """运行命令行界面"""
        print("欢迎使用B站爬虫命令行界面！")
        print(f"默认下载路径: {self.download_path}")
        print()
        
        while True:
            self.print_menu()
            choice = self.input_choice("请输入选项 (1-7): ", ['1', '2', '3', '4', '5', '6', '7'])
            
            if choice == '1':
                self.search_and_download_video()
            elif choice == '2':
                self.search_up()
            elif choice == '3':
                self.search_and_download_tv()
            elif choice == '4':
                self.batch_merge_files()
            elif choice == '5':
                self.set_download_path()
            elif choice == '6':
                self.set_cookies_path()
            elif choice == '7':
                print("感谢使用，再见！")
                break
            
            input("\n按回车键继续...")

if __name__ == "__main__":
    cli = BilibiliCLI()
    cli.run()
