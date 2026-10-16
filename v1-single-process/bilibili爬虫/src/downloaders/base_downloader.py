"""
基础下载器类
提供通用的下载功能和工具方法
"""
import os
import subprocess
import re
import requests
import shutil
from abc import ABC, abstractmethod

class BaseDownloader(ABC):
    """基础下载器抽象类"""
    
    def __init__(self):
        self.download_path = os.path.join(os.path.expanduser('~'), 'Downloads', 'bilibili')
        self.progress_callback = None
        self.cookies_path = None
        self.use_ytdlp = False
        self.ffmpeg_path = self._find_ffmpeg()
        self.download_audio = True  # 新增：是否下载音频
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.bilibili.com/',
            'Origin': 'https://www.bilibili.com',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
        }
    
    def _find_ffmpeg(self):
        """查找系统中的ffmpeg可执行文件"""
        ffmpeg_path = shutil.which('ffmpeg')
        if ffmpeg_path:
            return ffmpeg_path
        
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
    
    def _parse_ytdlp_progress(self, line):
        """解析yt-dlp的进度输出"""
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
        match = re.search(r'\[download\]\s*([\d.]+)%\s*\(([\d.]+)/([\d.]+)\s*MB\)\s*at\s*([\d.]+)\s*MB/s', line)
        if match:
            return {
                'progress': float(match.group(1)),
                'downloaded': float(match.group(2)),
                'total': float(match.group(3)),
                'speed': float(match.group(4))
            }
        return None
    
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
    
    def _download_with_youget(self, url, title):
        """使用you-get下载（带进度显示）"""
        try:
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)
            output_path = os.path.join(self.download_path, safe_title)
            
            cmd = ['you-get', '-o', self.download_path, '--no-caption']
            
            if self.cookies_path and os.path.exists(self.cookies_path):
                cmd.extend(['--cookies', self.cookies_path])
            
            # 如果只下载视频，添加视频格式参数
            if not self.download_audio:
                cmd.extend(['--format', 'flv'])
            
            cmd.append(url)
            
            print(f"[下载命令] {' '.join(cmd)}")
            
            # 使用Popen实时读取输出
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            # 实时读取进度
            for line in process.stdout:
                line = line.strip()
                if line:
                    # 解析进度
                    progress_info = self._parse_progress(line)
                    if progress_info:
                        # 调用进度回调
                        if self.progress_callback:
                            self.progress_callback(title, progress_info)
                        # 打印进度到命令行
                        progress = progress_info.get('progress', 0)
                        downloaded = progress_info.get('downloaded', 0)
                        total = progress_info.get('total', 0)
                        speed = progress_info.get('speed', 0)
                        print(f"[下载进度] {title}: {progress:.1f}% ({downloaded:.1f}/{total:.1f} MB) @ {speed:.1f} MB/s")
            
            process.wait(timeout=300)
            
            if process.returncode == 0:
                print(f"[下载成功] {title}")
                return (True, f"下载成功: {output_path}")
            else:
                print(f"[下载失败] {title}")
                return (False, f"下载失败")
                
        except subprocess.TimeoutExpired:
            return (False, "下载超时")
        except Exception as e:
            return (False, str(e))
    
    def _download_with_ytdlp(self, url, title):
        """使用yt-dlp下载（带进度显示）"""
        try:
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)
            
            cmd = ['yt-dlp', '-o', os.path.join(self.download_path, safe_title + '.%(ext)s')]
            
            if self.cookies_path and os.path.exists(self.cookies_path):
                cmd.extend(['--cookies', self.cookies_path])
            
            # 添加反反爬配置 - 使用类中已有的headers
            cmd.extend(['--user-agent', self.headers['User-Agent']])
            cmd.extend(['--referer', self.headers['Referer']])
            for key, value in self.headers.items():
                if key not in ['User-Agent', 'Referer']:
                    cmd.extend(['--add-header', f'{key}:{value}'])
            
            # 如果只下载视频，添加只下载视频流的参数
            if not self.download_audio:
                # 只下载视频流，不下载音频
                cmd.extend(['-f', 'bestvideo[ext=mp4]/bestvideo'])
            else:
                # 下载最佳质量视频+音频
                cmd.extend(['-f', 'bestvideo+bestaudio/best', '--merge-output-format', 'mp4'])
            
            cmd.append(url)
            
            print(f"[下载命令] {' '.join(cmd)}")
            
            # 使用Popen实时读取输出
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            # 收集所有输出
            all_output = []
            
            # 实时读取进度
            for line in process.stdout:
                line = line.strip()
                if line:
                    all_output.append(line)
                    # 解析进度
                    progress_info = self._parse_ytdlp_progress(line)
                    if progress_info:
                        # 调用进度回调
                        if self.progress_callback:
                            self.progress_callback(title, progress_info)
                        # 打印进度到命令行
                        progress = progress_info.get('progress', 0)
                        downloaded = progress_info.get('downloaded', 0)
                        speed = progress_info.get('speed', 0)
                        print(f"[下载进度] {title}: {progress:.1f}% ({downloaded:.1f} MB) @ {speed:.1f} MB/s")
            
            process.wait(timeout=300)
            
            if process.returncode == 0:
                print(f"[下载成功] {title}")
                return (True, f"下载成功")
            else:
                print(f"[下载失败] {title}")
                # 打印错误信息
                if all_output:
                    print("[错误信息]")
                    for line in all_output[-10:]:  # 只显示最后10行
                        print(f"  {line}")
                return (False, f"下载失败 (返回码: {process.returncode})")
                
        except subprocess.TimeoutExpired:
            return (False, "下载超时")
        except Exception as e:
            return (False, str(e))
    
    @abstractmethod
    def download(self, *args, **kwargs):
        """下载方法（需子类实现）"""
        pass