"""
视图层 - GUI界面组件
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import os
import requests
from PIL import Image, ImageTk
from io import BytesIO

class SearchFrame(ttk.Frame):
    """搜索框架组件"""
    
    def __init__(self, parent, search_callback):
        super().__init__(parent)
        self.search_callback = search_callback
        self.create_widgets()
    
    def create_widgets(self):
        # 搜索类型选择
        search_type_label = ttk.Label(self, text="搜索类型:")
        search_type_label.grid(row=0, column=0, padx=(0, 5))
        
        self.search_type_var = tk.StringVar(value='video')
        search_type_combo = ttk.Combobox(self, textvariable=self.search_type_var, 
                                         values=['video', 'up', 'tv'], state='readonly', width=8)
        search_type_combo.grid(row=0, column=1, padx=(0, 10))
        
        # 关键词标签
        keyword_label = ttk.Label(self, text="关键词:")
        keyword_label.grid(row=0, column=2, padx=(10, 5))
        
        # 关键词输入框
        self.keyword_entry = ttk.Entry(self, width=40, font=('Arial', 11))
        self.keyword_entry.grid(row=0, column=3, padx=(0, 10))
        self.keyword_entry.bind('<Return>', lambda e: self.on_search())
        
        # 搜索按钮
        search_button = ttk.Button(self, text="搜索", command=self.on_search)
        search_button.grid(row=0, column=4)
        self.search_button = search_button
        
        # 清除按钮
        clear_button = ttk.Button(self, text="清除", command=self.on_clear)
        clear_button.grid(row=0, column=5, padx=(10, 0))
    
    def on_search(self):
        """搜索按钮点击事件"""
        keyword = self.keyword_entry.get().strip()
        search_type = self.search_type_var.get()
        if keyword and self.search_callback:
            self.search_callback(keyword, search_type)
    
    def on_clear(self):
        """清除按钮点击事件"""
        self.keyword_entry.delete(0, tk.END)
    
    def get_keyword(self):
        """获取关键词"""
        return self.keyword_entry.get().strip()
    
    def set_search_button_state(self, state):
        """设置搜索按钮状态"""
        self.search_button.config(state=state)

class DownloadPathFrame(ttk.Frame):
    """下载路径选择框架"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.create_widgets()
    
    def create_widgets(self):
        path_label = ttk.Label(self, text="下载路径:")
        path_label.grid(row=0, column=0, padx=(0, 5))
        
        self.path_var = tk.StringVar(value=os.path.join(os.path.expanduser('~'), 'Downloads', 'bilibili'))
        self.path_entry = ttk.Entry(self, textvariable=self.path_var, width=60)
        self.path_entry.grid(row=0, column=1, padx=(0, 10))
        
        browse_button = ttk.Button(self, text="浏览", command=self.on_browse)
        browse_button.grid(row=0, column=2)
    
    def on_browse(self):
        """浏览按钮点击事件"""
        path = filedialog.askdirectory()
        if path:
            self.path_var.set(path)
    
    def get_path(self):
        """获取下载路径"""
        return self.path_var.get()

class ResultPanel(ttk.Frame):
    """结果展示面板"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.videos = []
        self.selected_indices = set()
        self.image_cache = {}  # 缓存图片对象，防止被垃圾回收
        self.load_more_callback = None
        self.is_loading_more = False
        self.create_widgets()
    
    def create_widgets(self):
        # 结果数量标签和操作按钮
        self.result_bar_frame = ttk.Frame(self)
        self.result_bar_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.result_count_label = ttk.Label(self.result_bar_frame, text="")
        self.result_count_label.pack(side=tk.LEFT)
        
        # 全选/取消全选按钮
        self.select_all_button = ttk.Button(self.result_bar_frame, text="全选", command=self.on_select_all)
        self.select_all_button.pack(side=tk.LEFT, padx=(20, 5))
        
        self.deselect_all_button = ttk.Button(self.result_bar_frame, text="取消全选", command=self.on_deselect_all)
        self.deselect_all_button.pack(side=tk.LEFT, padx=(5, 5))
        
        # 下载选中按钮
        self.download_selected_button = ttk.Button(self.result_bar_frame, text="下载选中", 
                                                   command=self.on_download_selected,
                                                   style='Download.TButton')
        self.download_selected_button.pack(side=tk.LEFT, padx=(20, 0))
        
        # 滚动容器
        self.canvas = tk.Canvas(self)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # 添加滚轮滚动支持
        self.canvas.bind('<MouseWheel>', self.on_mouse_wheel)
        self.scrollable_frame.bind('<MouseWheel>', self.on_mouse_wheel)
        # Linux/Mac 平台
        self.canvas.bind('<Button-4>', self.on_mouse_wheel)
        self.canvas.bind('<Button-5>', self.on_mouse_wheel)
        self.scrollable_frame.bind('<Button-4>', self.on_mouse_wheel)
        self.scrollable_frame.bind('<Button-5>', self.on_mouse_wheel)
        
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 加载更多提示标签
        self.load_more_label = ttk.Label(self.scrollable_frame, text="", foreground='#0066cc')
        self.load_more_label.pack(pady=10)
    
    def on_mouse_wheel(self, event):
        """滚轮滚动事件处理"""
        # 根据平台处理滚轮事件
        if event.delta:
            # Windows平台
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        else:
            # Linux/Mac平台
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")
        
        # 检查是否滚动到底部
        self.check_scroll_position()
    
    def check_scroll_position(self):
        """检查滚动位置，如果接近底部则触发加载更多"""
        if not self.load_more_callback or self.is_loading_more:
            return
        
        # 延迟检查以避免频繁触发
        if hasattr(self, '_scroll_check_job') and self._scroll_check_job:
            return
        
        self._scroll_check_job = self.after(200, self._do_check_scroll)
    
    def _do_check_scroll(self):
        """实际执行滚动位置检查"""
        self._scroll_check_job = None
        
        if not self.load_more_callback or self.is_loading_more:
            return
        
        # 获取当前可见区域
        y_view = self.canvas.yview()
        # 滚动到底部时触发加载更多
        if y_view[1] >= 0.95:
            self.is_loading_more = True
            self.load_more_label.config(text="加载中...")
            if self.load_more_callback:
                self.load_more_callback()
    
    def reset_loading_state(self):
        """重置加载状态"""
        self.is_loading_more = False
    
    def display_videos(self, videos, page=1, total=0):
        """显示视频列表"""
        # 清空现有内容
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        
        # 清空图片缓存
        self.image_cache.clear()
        
        # 重新创建加载更多标签
        self.load_more_label = ttk.Label(self.scrollable_frame, text="", foreground='#0066cc')
        self.load_more_label.pack(pady=10)
        self.is_loading_more = False
        
        self.videos = videos
        self.selected_indices = set()
        
        if not videos:
            messagebox.showinfo("提示", "未找到相关视频")
            return
        
        for i, video in enumerate(videos):
            self._add_video_widget(i, video)
        
        # 更新结果数量标签
        loaded_count = len(videos)
        self.result_count_label.config(text=f"已加载 {loaded_count} / {total} 个视频")
        
        # 如果还有更多数据，显示加载更多提示
        if loaded_count < total:
            self.load_more_label.config(text=f"↓ 滚动到底部加载更多（还有 {total - loaded_count} 个）", cursor='hand2')
            self.load_more_label.bind('<Button-1>', lambda e: self._on_load_more_click())
        else:
            self.load_more_label.config(text="已加载全部视频")
    
    def append_videos(self, videos, page=1, total=0):
        """追加视频列表（用于加载更多）"""
        if not videos:
            return
        
        start_index = len(self.videos)
        self.videos.extend(videos)
        
        for i, video in enumerate(videos):
            self._add_video_widget(start_index + i, video)
        
        # 更新结果数量标签
        loaded_count = len(self.videos)
        self.result_count_label.config(text=f"已加载 {loaded_count} / {total} 个视频")
        
        # 更新加载更多提示
        if loaded_count < total:
            self.load_more_label.config(text=f"↓ 滚动到底部加载更多（还有 {total - loaded_count} 个）", cursor='hand2')
            self.load_more_label.bind('<Button-1>', lambda e: self._on_load_more_click())
        else:
            self.load_more_label.config(text="已加载全部视频")
        
        # 重置加载状态
        self.is_loading_more = False
        
        # 更新滚动区域
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    
    def _on_load_more_click(self):
        """加载更多按钮点击事件"""
        if not self.is_loading_more and self.load_more_callback:
            self.is_loading_more = True
            self.load_more_label.config(text="加载中...")
            self.load_more_callback()
    
    def _add_video_widget(self, i, video):
        """添加单个视频widget"""
        video_frame = ttk.Frame(self.scrollable_frame, padding=10, relief=tk.RIDGE)
        video_frame.pack(fill=tk.X, pady=5)
        
        # 选择框
        var = tk.BooleanVar()
        checkbox = ttk.Checkbutton(video_frame, variable=var, 
                                   command=lambda idx=i, v=var: self.toggle_select(idx, v))
        checkbox.pack(side=tk.LEFT, padx=(0, 10))
        
        # 封面图片
        cover_frame = ttk.Frame(video_frame)
        cover_frame.pack(side=tk.LEFT, padx=(0, 15))
        
        # 尝试加载封面图片
        cover_label = ttk.Label(cover_frame, text="加载中...", width=15)
        cover_label.pack()
        
        if video.get('pic'):
            print(f"[DEBUG] 视频{i+1}封面URL: {video['pic']}")
            try:
                # 智能处理URL
                pic_url = video['pic']
                if pic_url.startswith('//'):
                    pic_url = 'https:' + pic_url
                elif not pic_url.startswith('http'):
                    pic_url = 'https://' + pic_url
                
                # 下载并显示封面图片
                response = requests.get(pic_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
                print(f"[DEBUG] 响应状态码: {response.status_code}")
                
                if response.status_code == 200:
                    print(f"[DEBUG] 响应内容长度: {len(response.content)}")
                    image = Image.open(BytesIO(response.content))
                    print(f"[DEBUG] 图片原始尺寸: {image.size}")
                    image.thumbnail((120, 90), Image.Resampling.LANCZOS)
                    print(f"[DEBUG] 图片缩放后尺寸: {image.size}")
                    photo = ImageTk.PhotoImage(image)
                    self.image_cache[i] = photo  # 缓存图片对象
                    cover_label.config(image=photo, text="")
                    print(f"[DEBUG] 封面加载成功")
                else:
                    print(f"[DEBUG] HTTP错误: {response.status_code}")
                    cover_label.config(text=f"HTTP {response.status_code}")
            except Exception as e:
                print(f"[DEBUG] 图片加载异常: {type(e).__name__}: {str(e)}")
                cover_label.config(text="加载失败")
        else:
            print(f"[DEBUG] 视频{i+1}没有封面URL")
        
        # 视频信息
        info_frame = ttk.Frame(video_frame)
        info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 标题
        title_label = ttk.Label(info_frame, text=f"{i+1}. {video['title']}", 
                                font=('Arial', 11, 'bold'), foreground='#0066cc', wraplength=500)
        title_label.pack(anchor=tk.W)
        
        # 链接和作者
        video_url = f"https://www.bilibili.com/video/{video['bvid']}"
        url_label = ttk.Label(info_frame, text=f"链接: {video_url}", font=('Arial', 9))
        url_label.pack(anchor=tk.W)
        
        author_label = ttk.Label(info_frame, text=f"UP主: {video['author']}", font=('Arial', 9))
        author_label.pack(anchor=tk.W)
        
        # 统计信息
        stats_text = f"播放量: {video['play']} | 弹幕: {video['video_review']} | 时长: {video['duration']} | 发布时间: {video['pubdate']}"
        stats_label = ttk.Label(info_frame, text=stats_text, font=('Arial', 9), foreground='#666666')
        stats_label.pack(anchor=tk.W)
        
        # 简介
        if video['description']:
            desc = video['description'][:80] + "..." if len(video['description']) > 80 else video['description']
            desc_label = ttk.Label(info_frame, text=f"简介: {desc}", font=('Arial', 9), wraplength=500)
            desc_label.pack(anchor=tk.W)
        
        # 单独下载按钮
        download_button = ttk.Button(video_frame, text="下载", style='Download.TButton',
                                     command=lambda bvid=video['bvid'], title=video['title']: 
                                     self.on_download_single(bvid, title))
        download_button.pack(side=tk.RIGHT, padx=10)
    
    def display_users(self, users):
        """显示UP主列表"""
        # 清空现有内容
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        
        # 清空图片缓存
        self.image_cache.clear()
        
        # 重新创建加载更多标签
        self.load_more_label = ttk.Label(self.scrollable_frame, text="", foreground='#0066cc')
        self.load_more_label.pack(pady=10)
        
        if not users:
            messagebox.showinfo("提示", "未找到相关UP主")
            return
        
        for user in users:
            user_frame = ttk.Frame(self.scrollable_frame, padding=10, relief=tk.RIDGE)
            user_frame.pack(fill=tk.X, pady=5)
            
            # 头像图片
            face_frame = ttk.Frame(user_frame)
            face_frame.pack(side=tk.LEFT, padx=(0, 15))
            
            face_label = ttk.Label(face_frame, text="加载中...", width=10)
            face_label.pack()
            
            if user.get('face'):
                try:
                    # 智能处理URL：如果以//开头则添加https:，否则直接使用
                    face_url = user['face']
                    if face_url.startswith('//'):
                        face_url = 'https:' + face_url
                    elif not face_url.startswith('http'):
                        face_url = 'https://' + face_url
                    
                    print(f"[UP主头像调试] UP主: {user.get('name', 'unknown')}, 头像URL: {face_url}")
                    
                    response = requests.get(face_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
                    print(f"[UP主头像调试] 响应状态码: {response.status_code}")
                    
                    if response.status_code == 200:
                        from io import BytesIO
                        image = Image.open(BytesIO(response.content))
                        image.thumbnail((80, 80), Image.Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(image)
                        self.image_cache[user['mid']] = photo
                        face_label.config(image=photo, text="")
                        print(f"[UP主头像] {user.get('name', 'unknown')} 头像加载成功")
                    else:
                        print(f"[UP主头像失败] HTTP {response.status_code}")
                        face_label.config(text="加载失败")
                except Exception as e:
                    print(f"[UP主头像错误] {user.get('name', 'unknown')} - {str(e)}")
                    face_label.config(text="加载失败")
            else:
                print(f"[UP主头像警告] UP主: {user.get('name', 'unknown')}, 没有face字段")
                print(f"[UP主头像调试] user字典内容: {user}")
            
            # 用户信息
            info_frame = ttk.Frame(user_frame)
            info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            name_label = ttk.Label(info_frame, text=f"UP主: {user['name']}", font=('Arial', 11, 'bold'))
            name_label.pack(anchor=tk.W)
            
            stats_label = ttk.Label(info_frame, text=f"粉丝数: {user['fans']} | 视频数: {user['videos']}", font=('Arial', 9))
            stats_label.pack(anchor=tk.W)
            
            if user['description']:
                desc_label = ttk.Label(info_frame, text=f"简介: {user['description'][:60]}...", font=('Arial', 9))
                desc_label.pack(anchor=tk.W)
            
            # 查看视频按钮
            view_button = ttk.Button(user_frame, text="搜索该UP主视频", 
                                     command=lambda name=user['name']: self.on_view_user_videos(name))
            view_button.pack(side=tk.RIGHT, padx=10)
        
        self.result_count_label.config(text=f"找到 {len(users)} 个UP主")
        self.load_more_label.config(text="")
    
    def display_tvs(self, tvs, page=1, total=0):
        """显示剧集列表"""
        # 清空现有内容
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        
        # 清空图片缓存
        self.image_cache.clear()
        
        # 重新创建加载更多标签
        self.load_more_label = ttk.Label(self.scrollable_frame, text="", foreground='#0066cc')
        self.load_more_label.pack(pady=10)
        self.is_loading_more = False
        
        self.videos = tvs
        self.selected_indices = set()
        
        if not tvs:
            messagebox.showinfo("提示", "未找到相关剧集")
            return
        
        for i, tv in enumerate(tvs):
            self._add_tv_widget(i, tv)
        
        # 更新结果数量标签
        loaded_count = len(tvs)
        self.result_count_label.config(text=f"已加载 {loaded_count} / {total} 部剧集")
        
        # 如果还有更多数据，显示加载更多提示
        if loaded_count < total:
            self.load_more_label.config(text=f"↓ 滚动到底部加载更多（还有 {total - loaded_count} 部）", cursor='hand2')
            self.load_more_label.bind('<Button-1>', lambda e: self._on_load_more_click())
        else:
            self.load_more_label.config(text="已加载全部剧集")
    
    def append_tvs(self, tvs, page=1, total=0):
        """追加剧集列表（用于加载更多）"""
        if not tvs:
            return
        
        start_index = len(self.videos)
        self.videos.extend(tvs)
        
        for i, tv in enumerate(tvs):
            self._add_tv_widget(start_index + i, tv)
        
        # 更新结果数量标签
        loaded_count = len(self.videos)
        self.result_count_label.config(text=f"已加载 {loaded_count} / {total} 部剧集")
        
        # 更新加载更多提示
        if loaded_count < total:
            self.load_more_label.config(text=f"↓ 滚动到底部加载更多（还有 {total - loaded_count} 部）", cursor='hand2')
            self.load_more_label.bind('<Button-1>', lambda e: self._on_load_more_click())
        else:
            self.load_more_label.config(text="已加载全部剧集")
        
        # 重置加载状态
        self.is_loading_more = False
        
        # 更新滚动区域
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    
    def _add_tv_widget(self, i, tv):
        """添加单个剧集widget"""
        tv_frame = ttk.Frame(self.scrollable_frame, padding=10, relief=tk.RIDGE)
        tv_frame.pack(fill=tk.X, pady=5)
        
        # 选择框
        var = tk.BooleanVar()
        checkbox = ttk.Checkbutton(tv_frame, variable=var, 
                                   command=lambda idx=i, v=var: self.toggle_select(idx, v))
        checkbox.pack(side=tk.LEFT, padx=(0, 10))
        
        # 封面图片
        cover_frame = ttk.Frame(tv_frame)
        cover_frame.pack(side=tk.LEFT, padx=(0, 15))
        
        cover_label = ttk.Label(cover_frame, text="加载中...", width=15)
        cover_label.pack()
        
        if tv.get('pic'):
            try:
                # 智能处理URL
                pic_url = tv['pic']
                if pic_url.startswith('//'):
                    pic_url = 'https:' + pic_url
                elif not pic_url.startswith('http'):
                    pic_url = 'https://' + pic_url
                
                response = requests.get(pic_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
                
                if response.status_code == 200:
                    image = Image.open(BytesIO(response.content))
                    image.thumbnail((120, 90), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(image)
                    self.image_cache[i] = photo
                    cover_label.config(image=photo, text="")
                else:
                    cover_label.config(text=f"HTTP {response.status_code}")
            except Exception as e:
                cover_label.config(text="加载失败")
        
        # 剧集信息
        info_frame = ttk.Frame(tv_frame)
        info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 标题
        title_label = ttk.Label(info_frame, text=f"{i+1}. {tv['title']}", 
                                font=('Arial', 11, 'bold'), foreground='#0066cc', wraplength=500)
        title_label.pack(anchor=tk.W)
        
        # 链接
        url_label = ttk.Label(info_frame, text=f"链接: {tv['url']}", font=('Arial', 9))
        url_label.pack(anchor=tk.W)
        
        # 统计信息
        stats_text = f"类型: {tv['type']} | 集数: {tv['episodes']} | 评分: {tv['score']}"
        if tv.get('season'):
            stats_text += f" | 季度: {tv['season']}"
        if tv.get('areas'):
            stats_text += f" | 地区: {tv['areas']}"
        if tv.get('styles'):
            stats_text += f" | 风格: {tv['styles']}"
        stats_label = ttk.Label(info_frame, text=stats_text, font=('Arial', 9), foreground='#666666')
        stats_label.pack(anchor=tk.W)
        
        # 简介（如果有）
        if tv.get('desc'):
            desc_text = tv['desc'][:100] + '...' if len(tv['desc']) > 100 else tv['desc']
            desc_label = ttk.Label(info_frame, text=f"简介: {desc_text}", font=('Arial', 9), foreground='#888888', wraplength=500)
            desc_label.pack(anchor=tk.W)
        
        # 下载按钮
        download_button = ttk.Button(tv_frame, text="下载", 
                                     command=lambda tv_data=tv: 
                                     self.on_download_single(tv_data))
        download_button.pack(side=tk.RIGHT, padx=10)
    
    def toggle_select(self, idx, var):
        """切换选择状态"""
        if var.get():
            self.selected_indices.add(idx)
        else:
            self.selected_indices.discard(idx)
    
    def on_select_all(self):
        """全选"""
        for widget in self.scrollable_frame.winfo_children():
            if isinstance(widget, ttk.Frame):
                checkboxes = [child for child in widget.winfo_children() if isinstance(child, ttk.Checkbutton)]
                if checkboxes:
                    checkboxes[0].state(['selected'])
        self.selected_indices = set(range(len(self.videos)))
    
    def on_deselect_all(self):
        """取消全选"""
        for widget in self.scrollable_frame.winfo_children():
            if isinstance(widget, ttk.Frame):
                checkboxes = [child for child in widget.winfo_children() if isinstance(child, ttk.Checkbutton)]
                if checkboxes:
                    checkboxes[0].state(['!selected'])
        self.selected_indices = set()
    
    def on_download_single(self, video_data):
        """下载单个视频或剧集"""
        if self.download_callback:
            self.download_callback([video_data])
    
    def on_download_selected(self):
        """下载选中的视频"""
        if not self.selected_indices:
            messagebox.showwarning("警告", "请先选择要下载的视频！")
            return
        
        selected_videos = [self.videos[idx] for idx in self.selected_indices if idx < len(self.videos)]
        if self.download_callback:
            self.download_callback(selected_videos)
    
    def on_view_user_videos(self, name):
        """查看UP主视频"""
        if self.view_user_callback:
            self.view_user_callback(name)
    
    def set_download_callback(self, callback):
        """设置下载回调"""
        self.download_callback = callback
    
    def set_view_user_callback(self, callback):
        """设置查看用户视频回调"""
        self.view_user_callback = callback
    
    def set_load_more_callback(self, callback):
        """设置加载更多回调"""
        self.load_more_callback = callback

class LogPanel(ttk.Frame):
    """日志面板"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.create_widgets()
    
    def create_widgets(self):
        log_label = ttk.Label(self, text="下载日志:")
        log_label.pack(anchor=tk.W)
        
        self.log_text = scrolledtext.ScrolledText(self, wrap=tk.WORD, height=5, font=('Arial', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
    
    def add_log(self, message):
        """添加日志消息"""
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
    
    def clear_log(self):
        """清空日志"""
        self.log_text.delete(1.0, tk.END)