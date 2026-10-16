"""
视频下载工具模块
支持 you-get 和 yt-dlp 两种下载方式
"""
import os
import subprocess
import sys
import re
import requests
import shutil

class VideoDownloader:
    """视频下载器类"""
    
    def __init__(self):
        self.download_path = os.path.join(os.path.expanduser('~'), 'Downloads', 'bilibili')
        self.progress_callback = None
        self.cookies_path = None  # Cookie文件路径
        self.use_ytdlp = False  # 是否使用yt-dlp
        self.ffmpeg_path = self._find_ffmpeg()  # ffmpeg路径
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.bilibili.com/'
        }
    
    def _find_ffmpeg(self):
        """查找系统中的ffmpeg可执行文件"""
        # 优先从系统PATH查找
        ffmpeg_path = shutil.which('ffmpeg')
        if ffmpeg_path:
            return ffmpeg_path
        
        # 尝试常见安装路径
        common_paths = [
            r'C:\ffmpeg\bin\ffmpeg.exe',
            r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
            r'C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe',
            os.path.join(os.path.dirname(__file__), 'ffmpeg', 'bin', 'ffmpeg.exe'),
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ffmpeg', 'bin', 'ffmpeg.exe')
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def _merge_audio_video(self, video_path, audio_path, output_path):
        """使用ffmpeg合并音视频"""
        if not self.ffmpeg_path:
            print("[警告] 未找到ffmpeg，无法合并音视频")
            return False, "未找到ffmpeg，请安装后重试"
        
        try:
            print(f"[合并音视频] video: {video_path}, audio: {audio_path}, output: {output_path}")
            
            # 构建ffmpeg命令
            # -i: 输入文件
            # -c:v copy: 视频流直接拷贝（不重新编码）
            # -c:a copy: 音频流直接拷贝（不重新编码）
            # -y: 覆盖输出文件
            command = [
                self.ffmpeg_path,
                '-i', video_path,
                '-i', audio_path,
                '-c:v', 'copy',
                '-c:a', 'copy',
                '-y',
                output_path
            ]
            
            print(f"[合并命令] {' '.join(command)}")
            
            # 执行命令
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=300
            )
            
            if result.returncode == 0:
                print("[合并成功] 音视频已合并")
                # 删除临时文件
                try:
                    os.remove(video_path)
                    os.remove(audio_path)
                    print("[清理] 已删除临时音视频文件")
                except Exception as e:
                    print(f"[清理警告] 删除临时文件失败: {e}")
                return True, f"合并成功: {output_path}"
            else:
                print(f"[合并失败] ffmpeg返回错误: {result.stderr}")
                return False, f"合并失败: {result.stderr}"
                
        except subprocess.TimeoutExpired:
            return False, "合并超时"
        except Exception as e:
            print(f"[合并错误] {str(e)}")
            return False, f"合并错误: {str(e)}"
    
    def set_download_path(self, path):
        """设置下载路径"""
        self.download_path = path
    
    def set_cookies_path(self, path):
        """设置Cookie文件路径"""
        self.cookies_path = path
    
    def set_progress_callback(self, callback):
        """设置进度回调函数"""
        self.progress_callback = callback
    
    def set_use_ytdlp(self, use_ytdlp):
        """设置是否使用yt-dlp"""
        self.use_ytdlp = use_ytdlp
    
    def _parse_ytdlp_progress(self, line):
        """解析yt-dlp的进度输出"""
        # yt-dlp进度格式示例: [download]   50.0% of   12.3MiB at  1.2MiB/s ETA 00:10
        match = re.search(r'\[download\]\s*([\d.]+)%\s+of\s*([\d.]+)[KMG]iB\s+at\s*([\d.]+)[KMG]iB/s', line)
        if match:
            return {
                'progress': float(match.group(1)),
                'downloaded': float(match.group(2)),
                'speed': float(match.group(3))
            }
        return None
    
    def _parse_progress(self, line):
        """解析you-get的进度输出"""
        # you-get进度格式示例: [download]  50.0% (12.3/24.6 MB) at 1.2 MB/s ETA 00:10
        match = re.search(r'\[download\]\s*([\d.]+)%\s*\(([\d.]+)/([\d.]+)\s*MB\)\s*at\s*([\d.]+)\s*MB/s', line)
        if match:
            return {
                'progress': float(match.group(1)),
                'downloaded': float(match.group(2)),
                'total': float(match.group(3)),
                'speed': float(match.group(4))
            }
        return None
    
    def download_video(self, bvid, title):
        """下载单个视频（支持you-get和yt-dlp）"""
        try:
            # 确保下载目录存在
            if not os.path.exists(self.download_path):
                os.makedirs(self.download_path)
            
            # 构建视频URL
            video_url = f"https://www.bilibili.com/video/{bvid}"
            
            if self.use_ytdlp:
                # 使用yt-dlp下载（支持更多视频）
                success, msg = self._download_with_ytdlp(video_url, title)
            else:
                # 使用you-get下载
                success, msg = self._download_with_youget(video_url, title)
            
            # 如果下载成功，尝试合并分离的音视频文件
            if success and self.ffmpeg_path:
                print(f"[合并检查] 检查是否有分离的音视频文件需要合并...")
                self.merger.batch_merge(self.download_path)
            
            return (success, msg)
                
        except subprocess.TimeoutExpired:
            print(f"[下载超时] {title}")
            return (False, f"下载超时: {title}")
        except Exception as e:
            print(f"[下载错误] {title} - {str(e)}")
            return (False, f"下载错误: {title} - {str(e)}")
    
    def download_tv(self, season_id, title, selected_episodes=None):
        """下载TV剧集（支持下载整部剧集或指定集数）"""
        try:
            print(f"[TV下载开始] 剧集: {title}, season_id: {season_id}")
            
            # 获取剧集信息
            episodes = self._get_tv_episodes(season_id)
            
            if not episodes:
                print(f"[TV下载失败] 未获取到剧集信息")
                return (False, "未获取到剧集信息")
            
            print(f"[TV下载] 共找到 {len(episodes)} 集")
            
            # 如果指定了集数，只下载指定的
            if selected_episodes:
                episodes = [ep for i, ep in enumerate(episodes) if i in selected_episodes]
                print(f"[TV下载] 选择下载 {len(episodes)} 集")
            
            # 清理标题中的非法字符
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)
            safe_title = safe_title.strip()
            
            # 创建剧集目录
            tv_dir = os.path.join(self.download_path, safe_title)
            if not os.path.exists(tv_dir):
                os.makedirs(tv_dir)
            print(f"[TV下载] 下载目录: {tv_dir}")
            
            # 保存原始下载路径
            original_path = self.download_path
            self.download_path = tv_dir
            
            # 逐个下载每一集
            success_count = 0
            fail_count = 0
            results = []
            
            for i, episode in enumerate(episodes):
                ep_title = episode.get('title', f"第{i+1}集")
                ep_long_title = episode.get('long_title', '')
                
                # 使用完整标题
                full_title = f"第{i+1}集 - {ep_title}"
                if ep_long_title:
                    full_title = f"第{i+1}集 - {ep_long_title}"
                
                ep_url = episode.get('url', '')
                
                print(f"[TV下载] 正在下载第{i+1}/{len(episodes)}集: {full_title}")
                print(f"[TV下载] 播放链接: {ep_url}")
                
                try:
                    if self.use_ytdlp:
                        success, msg = self._download_with_ytdlp(ep_url, full_title)
                    else:
                        success, msg = self._download_with_youget(ep_url, full_title)
                    
                    if success:
                        success_count += 1
                        print(f"[TV下载] 第{i+1}集下载成功")
                    else:
                        fail_count += 1
                        print(f"[TV下载] 第{i+1}集下载失败: {msg}")
                    
                    results.append((full_title, success, msg))
                    
                    # 下载间隔，避免请求过快
                    if i < len(episodes) - 1:
                        import time
                        time.sleep(2)
                        
                except Exception as e:
                    fail_count += 1
                    error_msg = f"第{i+1}集下载异常: {str(e)}"
                    print(f"[TV下载] {error_msg}")
                    results.append((full_title, False, error_msg))
            
            # 恢复原始下载路径
            self.download_path = original_path
            
            # 生成下载报告
            report = f"[TV下载完成] {title}\n"
            report += f"==================================================\n"
            report += f"总集数: {len(episodes)}\n"
            report += f"成功: {success_count} 集\n"
            report += f"失败: {fail_count} 集\n"
            
            # 如果下载成功且有ffmpeg，尝试合并分离的音视频文件
            if success_count > 0 and self.ffmpeg_path:
                print(f"[TV合并检查] 检查是否有分离的音视频文件需要合并...")
                self.merger.batch_merge(tv_dir)
            
            if fail_count > 0:
                report += "\n[失败列表]\n"
                for ep_title, success, msg in results:
                    if not success:
                        report += f"  - {ep_title}: {msg}\n"
            
            print(report)
            
            return (success_count > 0, report)
            
        except Exception as e:
            print(f"[TV下载错误] {title} - {str(e)}")
            return (False, f"下载错误: {title} - {str(e)}")
    
    def _get_tv_episodes(self, season_id):
        """获取剧集的所有集数信息（使用官方API）"""
        episodes = []
        
        try:
            print(f"[获取剧集信息] season_id: {season_id}")
            
            # 方法1: 使用 pgc/web/season/section API
            url = f"https://api.bilibili.com/pgc/web/season/section?season_id={season_id}"
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            print(f"[DEBUG] API响应 code: {data.get('code')}")
            
            if data.get('code') == 0:
                sections = data.get('result', {}).get('main_section', {}).get('sections', [])
                print(f"[DEBUG] 找到 {len(sections)} 个章节")
                
                for section in sections:
                    eps = section.get('episodes', [])
                    print(f"[DEBUG] 章节包含 {len(eps)} 集")
                    
                    for ep in eps:
                        episode_info = {
                            'id': ep.get('id', ''),
                            'title': ep.get('title', ''),
                            'long_title': ep.get('long_title', ''),
                            'url': f"https://www.bilibili.com/bangumi/play/ep{ep.get('id', '')}",
                            'cover': ep.get('cover', ''),
                            'duration': ep.get('duration', 0),
                            'cid': ep.get('cid', ''),
                            'aid': ep.get('aid', ''),
                            'bvid': ep.get('bvid', '')
                        }
                        episodes.append(episode_info)
                        print(f"[DEBUG] 添加剧集: {episode_info['title']} - {episode_info['url']}")
            
            # 如果方法1失败或返回空，尝试方法2
            if not episodes:
                print("[DEBUG] 方法1返回空，尝试方法2")
                url = f"https://api.bilibili.com/pgc/view/web/season?season_id={season_id}"
                response = requests.get(url, headers=self.headers, timeout=15)
                response.raise_for_status()
                data = response.json()
                
                if data.get('code') == 0:
                    eps = data.get('result', {}).get('episodes', [])
                    for ep in eps:
                        episode_info = {
                            'id': ep.get('id', ''),
                            'title': ep.get('title', ''),
                            'long_title': ep.get('long_title', ''),
                            'url': f"https://www.bilibili.com/bangumi/play/ep{ep.get('id', '')}",
                            'cover': ep.get('cover', ''),
                            'duration': ep.get('duration', 0),
                            'cid': ep.get('cid', ''),
                            'aid': ep.get('aid', ''),
                            'bvid': ep.get('bvid', '')
                        }
                        episodes.append(episode_info)
            
            # 如果还是空，尝试方法3: 通过解析网页获取
            if not episodes:
                print("[DEBUG] 方法2返回空，尝试方法3")
                episodes = self._get_tv_episodes_from_web(season_id)
            
            print(f"[获取剧集信息完成] 共找到 {len(episodes)} 集")
            
        except Exception as e:
            print(f"[获取剧集信息失败] {str(e)}")
        
        return episodes
    
    def _get_tv_episodes_from_web(self, season_id):
        """通过解析网页获取剧集信息（备用方法）"""
        episodes = []
        
        try:
            # 先获取 season_id
            url = f"https://www.bilibili.com/bangumi/media/{season_id}"
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            html = response.text
            
            # 从HTML中提取 season_id
            import re
            season_id_match = re.search(r'season_id\s*[=:]\s*["\']?(\d+)["\']?', html)
            if season_id_match:
                season_id = season_id_match.group(1)
                print(f"[DEBUG] 从网页提取 season_id: {season_id}")
                
                # 调用API获取集数
                url = f"https://api.bilibili.com/pgc/web/season/section?season_id={season_id}"
                response = requests.get(url, headers=self.headers, timeout=15)
                response.raise_for_status()
                data = response.json()
                
                if data.get('code') == 0:
                    sections = data.get('result', {}).get('main_section', {}).get('sections', [])
                    for section in sections:
                        eps = section.get('episodes', [])
                        for ep in eps:
                            episodes.append({
                                'id': ep.get('id', ''),
                                'title': ep.get('title', ''),
                                'long_title': ep.get('long_title', ''),
                                'url': f"https://www.bilibili.com/bangumi/play/ep{ep.get('id', '')}",
                                'cover': ep.get('cover', ''),
                                'duration': ep.get('duration', 0),
                                'cid': ep.get('cid', ''),
                                'aid': ep.get('aid', ''),
                                'bvid': ep.get('bvid', '')
                            })
                            
        except Exception as e:
            print(f"[网页解析获取剧集失败] {str(e)}")
        
        return episodes
    
    def _download_with_youget(self, video_url, title):
        """使用you-get下载"""
        # 构建you-get命令
        command = [sys.executable, "-m", "you_get", "-o", self.download_path]
        
        # 如果设置了Cookie文件，添加--cookies参数
        if self.cookies_path:
            print(f"[Cookie调试] Cookie路径设置为: {self.cookies_path}")
            if os.path.exists(self.cookies_path):
                command.extend(["--cookies", self.cookies_path])
                print(f"[Cookie] 使用Cookie文件: {self.cookies_path}")
            else:
                print(f"[Cookie警告] Cookie文件不存在: {self.cookies_path}")
        else:
            print("[Cookie警告] 未设置Cookie文件路径")
        
        command.append(video_url)
        
        print(f"[下载开始] {title}")
        print(f"[下载URL] {video_url}")
        print(f"[使用工具] you-get")
        
        # 使用Popen异步执行，实时读取输出
        process = subprocess.Popen(command, 
                                  stdout=subprocess.PIPE, 
                                  stderr=subprocess.STDOUT,
                                  text=True,
                                  encoding='utf-8',
                                  errors='ignore',
                                  bufsize=1)
        
        # 实时读取输出
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            if line:
                line = line.strip()
                print(f"[下载进度] {line}")
                
                # 解析进度信息
                progress_info = self._parse_progress(line)
                if progress_info and self.progress_callback:
                    self.progress_callback(title, progress_info)
        
        # 获取返回码
        return_code = process.wait()
        
        if return_code == 0:
            print(f"[下载完成] {title}")
            return (True, f"下载成功: {title}")
        else:
            print(f"[下载失败] {title} (code={return_code})")
            return (False, f"下载失败: {title}")
    
    def _download_with_ytdlp(self, video_url, title):
        """使用yt-dlp下载（支持受限视频）"""
        # 构建yt-dlp命令
        command = [sys.executable, "-m", "yt_dlp", "-o", os.path.join(self.download_path, "%(title)s.%(ext)s")]
        
        # 添加B站特定选项
        command.extend([
            "--extractor-args", "bilibili:force_old_login=1",  # 强制旧版登录方式
            "--hls-prefer-native",  # 使用原生HLS下载
            "--no-check-certificate",  # 不检查证书
        ])
        
        # 如果设置了Cookie文件，添加--cookies参数
        if self.cookies_path:
            print(f"[Cookie调试] Cookie路径设置为: {self.cookies_path}")
            if os.path.exists(self.cookies_path):
                command.extend(["--cookies", self.cookies_path])
                print(f"[Cookie] 使用Cookie文件: {self.cookies_path}")
            else:
                print(f"[Cookie警告] Cookie文件不存在: {self.cookies_path}")
        else:
            print("[Cookie警告] 未设置Cookie文件路径")
        
        command.append(video_url)
        
        print(f"[下载开始] {title}")
        print(f"[下载URL] {video_url}")
        print(f"[使用工具] yt-dlp")
        
        # 使用Popen异步执行，实时读取输出
        process = subprocess.Popen(command, 
                                  stdout=subprocess.PIPE, 
                                  stderr=subprocess.STDOUT,
                                  text=True,
                                  encoding='utf-8',
                                  errors='ignore',
                                  bufsize=1)
        
        # 实时读取输出
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            if line:
                line = line.strip()
                print(f"[下载进度] {line}")
                
                # 解析进度信息
                progress_info = self._parse_ytdlp_progress(line)
                if progress_info and self.progress_callback:
                    self.progress_callback(title, progress_info)
        
        # 获取返回码
        return_code = process.wait()
        
        if return_code == 0:
            print(f"[下载完成] {title}")
            return (True, f"下载成功: {title}")
        else:
            print(f"[下载失败] {title} (code={return_code})")
            return (False, f"下载失败: {title}")