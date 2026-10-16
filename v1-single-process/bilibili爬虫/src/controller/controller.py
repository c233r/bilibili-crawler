"""
控制器层 - 协调Model和View
"""
import threading
from model.bilibili_api import BilibiliAPI
from downloaders.video_downloader import VideoDownloader
from downloaders.tv_downloader import TvDownloader

class BilibiliController:
    """B站爬虫控制器"""
    
    def __init__(self, view, page_size=50, max_videos=0, cookies_path=None, use_ytdlp=False):
        self.view = view
        self.api = BilibiliAPI()
        
        # 使用新的下载器
        self.video_downloader = VideoDownloader()
        self.tv_downloader = TvDownloader()
        
        # 配置参数
        self.page_size = page_size
        self.max_videos = max_videos
        self.cookies_path = cookies_path
        self.use_ytdlp = use_ytdlp
        
        # 设置Cookie文件
        if cookies_path:
            self.video_downloader.set_cookies_path(cookies_path)
            self.tv_downloader.set_cookies_path(cookies_path)
        
        # 设置是否使用yt-dlp
        self.video_downloader.set_use_ytdlp(use_ytdlp)
        self.tv_downloader.set_use_ytdlp(use_ytdlp)
        
        # 搜索状态
        self.current_keyword = ''
        self.search_type = 'tv'  # 当前搜索类型
        self.current_page = 1
        self.total_videos = 0
        self.loaded_videos = 0
        self.is_loading = False
        self.lock = threading.Lock()
        
        # 设置回调
        self.view.set_search_callback(self.handle_search)
        self.view.set_download_callback(self.handle_download)
        self.view.set_view_user_callback(self.handle_view_user)
        self.view.set_load_more_callback(self.handle_load_more)
    
    def handle_search(self, keyword, search_type):
        """处理搜索请求"""
        with self.lock:
            self.current_keyword = keyword
            self.search_type = search_type  # 保存搜索类型
            self.current_page = 1
            self.loaded_videos = 0
            self.is_loading = True
        
        self.view.set_search_button_state('disabled')
        self.view.clear_results()
        self.view.start_progress()
        
        # 在新线程中执行搜索
        search_thread = threading.Thread(target=self.perform_search, args=(keyword, search_type, 1))
        search_thread.daemon = True
        search_thread.start()
    
    def perform_search(self, keyword, search_type, page):
        """执行搜索"""
        try:
            if search_type == 'up':
                # 搜索UP主（不分页）
                users = self.api.search_users(keyword)
                self.view.update_results(users, 'user')
            elif search_type == 'tv':
                # 搜索剧集
                tvs, total = self.api.search_tv(keyword, page=page, page_size=self.page_size)
                with self.lock:
                    self.total_videos = total
                    self.loaded_videos += len(tvs)
                    self.is_loading = False
                
                # 如果有最大限制，更新total
                if self.max_videos > 0 and self.total_videos > self.max_videos:
                    self.total_videos = self.max_videos
                
                self.view.update_results(tvs, 'tv', page=page, total=self.total_videos)
            else:
                # 搜索视频（分页）
                videos, total = self.api.search_videos(keyword, page=page, page_size=self.page_size)
                with self.lock:
                    self.total_videos = total
                    self.loaded_videos += len(videos)
                    self.is_loading = False
                
                # 如果有最大限制，更新total
                if self.max_videos > 0 and self.total_videos > self.max_videos:
                    self.total_videos = self.max_videos
                
                self.view.update_results(videos, 'video', page=page, total=self.total_videos)
        except Exception as e:
            self.view.show_error(str(e))
            with self.lock:
                self.is_loading = False
        finally:
            self.view.stop_progress()
            self.view.set_search_button_state('normal')
    
    def handle_load_more(self):
        """处理加载更多请求"""
        with self.lock:
            if self.is_loading:
                return
            
            # 检查是否达到最大限制
            if self.max_videos > 0 and self.loaded_videos >= self.max_videos:
                return
            
            # 检查是否还有更多数据
            if self.current_page * self.page_size >= self.total_videos and self.total_videos > 0:
                return
            
            self.is_loading = True
            self.current_page += 1
            page = self.current_page
        
        self.view.start_progress()
        # 在新线程中加载更多
        load_thread = threading.Thread(target=self.perform_load_more, args=(page,))
        load_thread.daemon = True
        load_thread.start()
    
    def perform_load_more(self, page):
        """执行加载更多"""
        try:
            # 根据当前搜索类型加载更多
            if self.search_type == 'tv':
                items, total = self.api.search_tv(self.current_keyword, page=page, page_size=self.page_size)
            else:
                items, total = self.api.search_videos(self.current_keyword, page=page, page_size=self.page_size)
            
            with self.lock:
                self.total_videos = total
                self.loaded_videos += len(items)
                self.is_loading = False
            
            # 如果有最大限制，更新total
            if self.max_videos > 0 and self.total_videos > self.max_videos:
                self.total_videos = self.max_videos
            
            # 根据类型追加结果
            result_type = 'tv' if self.search_type == 'tv' else 'video'
            self.view.append_results(items, result_type, page=page, total=self.total_videos)
        except Exception as e:
            self.view.show_error(str(e))
            with self.lock:
                self.is_loading = False
        finally:
            self.view.stop_progress()
    
    def handle_download(self, videos):
        """处理下载请求"""
        # 获取下载路径
        download_path = self.view.get_download_path()
        
        # 设置下载路径
        self.video_downloader.set_download_path(download_path)
        self.tv_downloader.set_download_path(download_path)
        
        # 设置进度回调
        self.video_downloader.set_progress_callback(self.on_download_progress)
        self.tv_downloader.set_progress_callback(self.on_download_progress)
        
        # 在新线程中执行下载
        download_thread = threading.Thread(target=self.perform_download, args=(videos,))
        download_thread.daemon = True
        download_thread.start()
    
    def on_download_progress(self, title, progress_info):
        """下载进度回调"""
        progress = progress_info.get('progress', 0)
        downloaded = progress_info.get('downloaded', 0)
        total = progress_info.get('total', 0)
        speed = progress_info.get('speed', 0)
        
        # 构建进度文本
        if total > 0:
            progress_text = f"下载进度 [{title}]: {progress:.1f}% ({downloaded:.1f}/{total:.1f} MB) @ {speed:.1f} MB/s"
        else:
            progress_text = f"下载进度 [{title}]: {progress:.1f}% ({downloaded:.1f} MB) @ {speed:.1f} MB/s"
        
        # 打印到命令行
        print(progress_text)
        
        # 添加到GUI日志
        self.view.add_log(progress_text)
    
    def perform_download(self, videos):
        """执行下载（支持视频和TV剧集）"""
        for video in videos:
            bvid = video.get('bvid')
            title = video.get('title', '未知标题')
            season_id = video.get('season_id', '')
            media_id = video.get('media_id', '')
            
            self.view.add_log(f"开始下载: {title}")

            print(video)
            # 判断是普通视频还是TV剧集
            if season_id or media_id:
                # TV剧集下载（优先使用season_id，其次使用media_id）
                tv_id = season_id if season_id else media_id
                success, message = self.tv_downloader.download(tv_id, title)
            else:
                # 普通视频下载
                success, message = self.video_downloader.download(bvid, title)
            
            self.view.add_log(message)
            
            # 间隔2秒避免请求过快
            import time
            time.sleep(2)
    
    def handle_view_user(self, name):
        """处理查看UP主视频请求"""
        self.view.set_keyword(name)
        self.handle_search(name, 'video')