"""
主窗口视图类
"""
import tkinter as tk
from tkinter import ttk, messagebox
from view.components import SearchFrame, DownloadPathFrame, ResultPanel, LogPanel

class MainWindow(tk.Tk):
    """主窗口类"""
    
    def __init__(self):
        super().__init__()
        self.title("Bilibili视频爬虫")
        self.geometry("1000x700")
        
        self.setup_styles()
        self.create_widgets()
        
        # 回调函数
        self.search_callback = None
        self.download_callback = None
        self.view_user_callback = None
        self.load_more_callback = None
    
    def setup_styles(self):
        """设置样式"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # 配置按钮样式
        style.configure('Search.TButton', font=('Arial', 12), padding=10)
        style.configure('Action.TButton', font=('Arial', 10), padding=5)
        style.configure('Download.TButton', font=('Arial', 10), padding=5, 
                       foreground='white', background='#ff6b6b')
        
        # 配置标签样式
        style.configure('Title.TLabel', font=('Arial', 16, 'bold'))
    
    def create_widgets(self):
        """创建界面组件"""
        # 主框架
        main_frame = ttk.Frame(self, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 标题
        title_label = ttk.Label(main_frame, text="Bilibili视频爬虫", style='Title.TLabel')
        title_label.grid(row=0, column=0, columnspan=4, pady=(0, 20))
        
        # 搜索框架
        self.search_frame = SearchFrame(main_frame, self.on_search)
        self.search_frame.grid(row=1, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # 下载路径选择
        self.path_frame = DownloadPathFrame(main_frame)
        self.path_frame.grid(row=2, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # 进度条
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.grid(row=3, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=(10, 10))
        
        # 结果展示区域
        result_frame = ttk.Frame(main_frame)
        result_frame.grid(row=4, column=0, columnspan=4, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.result_panel = ResultPanel(result_frame)
        self.result_panel.pack(fill=tk.BOTH, expand=True)
        
        # 下载日志区域
        log_frame = ttk.Frame(main_frame)
        log_frame.grid(row=5, column=0, columnspan=4, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(10, 0))
        
        self.log_panel = LogPanel(log_frame)
        self.log_panel.pack(fill=tk.BOTH, expand=True)
        
        # 配置网格权重
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=3)
        main_frame.rowconfigure(5, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
    
    def on_search(self, keyword, search_type):
        """搜索事件处理"""
        if self.search_callback:
            self.search_callback(keyword, search_type)
    
    def on_download(self, videos):
        """下载事件处理"""
        if self.download_callback:
            self.download_callback(videos)
    
    def on_view_user(self, name):
        """查看用户视频事件处理"""
        if self.view_user_callback:
            self.view_user_callback(name)
    
    def on_load_more(self):
        """加载更多事件处理"""
        if self.load_more_callback:
            self.load_more_callback()
    
    def set_search_callback(self, callback):
        """设置搜索回调"""
        self.search_callback = callback
    
    def set_download_callback(self, callback):
        """设置下载回调"""
        self.download_callback = callback
        self.result_panel.set_download_callback(self.on_download)
    
    def set_view_user_callback(self, callback):
        """设置查看用户回调"""
        self.view_user_callback = callback
        self.result_panel.set_view_user_callback(self.on_view_user)
    
    def set_load_more_callback(self, callback):
        """设置加载更多回调"""
        self.load_more_callback = callback
        self.result_panel.set_load_more_callback(self.on_load_more)
    
    def set_search_button_state(self, state):
        """设置搜索按钮状态"""
        self.search_frame.set_search_button_state(state)
    
    def clear_results(self):
        """清空结果"""
        self.log_panel.clear_log()
    
    def start_progress(self):
        """开始进度条"""
        self.progress.start()
    
    def stop_progress(self):
        """停止进度条"""
        self.progress.stop()
    
    def update_results(self, data, data_type, page=1, total=0):
        """更新结果展示"""
        if data_type == 'video':
            self.result_panel.display_videos(data, page=page, total=total)
        elif data_type == 'tv':
            self.result_panel.display_tvs(data, page=page, total=total)
        else:
            self.result_panel.display_users(data)
    
    def append_results(self, data, data_type, page=1, total=0):
        """追加结果展示"""
        if data_type == 'video':
            self.result_panel.append_videos(data, page=page, total=total)
        elif data_type == 'tv':
            self.result_panel.append_tvs(data, page=page, total=total)
    
    def show_error(self, message):
        """显示错误信息"""
        messagebox.showerror("错误", message)
        # 重置加载状态
        self.result_panel.reset_loading_state()
    
    def add_log(self, message):
        """添加日志"""
        self.log_panel.add_log(message)
    
    def get_download_path(self):
        """获取下载路径"""
        return self.path_frame.get_path()
    
    def set_keyword(self, keyword):
        """设置关键词"""
        self.search_frame.keyword_entry.delete(0, tk.END)
        self.search_frame.keyword_entry.insert(0, keyword)
        self.search_frame.search_type_var.set('video')