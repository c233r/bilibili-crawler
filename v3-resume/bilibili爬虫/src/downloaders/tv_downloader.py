import json
"""
TV剧集下载器
负责下载B站剧集（番剧、电视剧等）
"""
import os
import re
import time
import requests
import sys
from .base_downloader import BaseDownloader

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ffmpeg.merger import FFMpegMerger

class TvDownloader(BaseDownloader):
    """TV剧集下载器"""
    
    def __init__(self):
        super().__init__()
        # 设置TV专用下载路径
        self.download_path = os.path.join(os.path.expanduser('~'), 'Downloads', 'bilibili', 'tv')
        self.merger = FFMpegMerger()
    
    def _get_tv_episodes(self, season_id):
        """获取剧集的所有集数信息"""
        episodes = []
        
        try:
            print(f"[获取剧集信息] season_id: {season_id}")
            
            # 方法1: 使用 pgc/web/season/section API
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
            
            # 如果方法1失败，尝试方法2
            if not episodes:
                url = f"https://api.bilibili.com/pgc/view/web/season?season_id={season_id}"
                response = requests.get(url, headers=self.headers, timeout=15)
                response.raise_for_status()
                data = response.json()
                
                if data.get('code') == 0:
                    eps = data.get('result', {}).get('episodes', [])
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
            
            print(f"[获取剧集信息完成] 共找到 {len(episodes)} 集")
            
        except Exception as e:
            print(f"[获取剧集信息失败] {str(e)}")
        
        return episodes
    
    def download(self, season_id, title, selected_episodes=None):
        """下载TV剧集
        
        Args:
            season_id: 剧集ID
            title: 剧集标题
            selected_episodes: 指定下载的集数（可选）
        
        Returns:
            (success, message)
        """
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
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', title).strip()
            
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
                
                full_title = f"第{i+1}集 - {ep_title}"
                if ep_long_title:
                    full_title = f"第{i+1}集 - {ep_long_title}"
                
                ep_url = episode.get('url', '')
                
                print(f"[TV下载] 正在处理第{i+1}/{len(episodes)}集: {full_title}")
                
                # 获取视频大小信息
                size_mb = self._get_video_size(ep_url)
                
                # 如果小于20MB，跳过（可能是预告片）
                # if size_mb is not None and size_mb < 0.1:
                #     print(f"[TV下载] 跳过第{i+1}集（{full_title}）: 文件大小 {size_mb:.1f} MB < 0.1MB，可能是预告片")
                #     continue
                
                print(f"[TV下载] 正在下载第{i+1}/{len(episodes)}集: {full_title} (大小: {size_mb:.1f} MB)")
                
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
                    
                    if i < len(episodes) - 1:
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
    
    def _get_video_size(self, url):
        """获取视频大小（MB）"""
        try:
            # 从URL中提取episode ID
            match = re.search(r'/ep(\d+)', url)
            if not match:
                print(f"[TV下载] 无法从URL提取ep_id: {url}")
                return None
            
            ep_id = match.group(1)
            print(f"[TV下载] 获取视频大小，ep_id: {ep_id}")
            
            # 根据B站API文档，使用正确的端点
            # https://api.bilibili.com/pgc/player/web/playurl
            api_url = "https://api.bilibili.com/pgc/player/web/playurl"
            
            # 构建请求参数
            params = {
                'ep_id': ep_id,
                'qn': 120,           # 720P高清
                'fnval': 16,        # DASH方式（音视频分流）
                'fnver': 0,         # 固定为0
                'fourk': 1          # 允许4K
            }
            
            # 添加必要的请求头
            headers = self.headers.copy()
            headers['Referer'] = 'https://www.bilibili.com'
            
            response = requests.get(api_url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            print(f"[TV下载] API响应code: {data.get('code')}")
            
            if data.get('code') == 0 and data.get('result'):
                result = data['result']
                print(f"[TV下载] API返回结果: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}...")
                
                # 获取视频大小（字节）
                total_size = 0
                
                # 尝试DASH方式（音视频分流）
                if 'video' in result and 'dash' in result['video']:
                    dash_data = result['video']['dash']
                    
                    # 视频流大小
                    video_streams = dash_data.get('video', [])
                    for stream in video_streams:
                        stream_size = stream.get('size', 0)
                        total_size += stream_size
                        print(f"[TV下载] 视频流 {stream.get('id')}: {stream_size / (1024*1024):.2f} MB")
                    
                    # 音频流大小
                    audio_streams = dash_data.get('audio', [])
                    for stream in audio_streams:
                        stream_size = stream.get('size', 0)
                        total_size += stream_size
                        print(f"[TV下载] 音频流 {stream.get('id')}: {stream_size / (1024*1024):.2f} MB")
                
                # 尝试FLV方式（单文件）
                elif 'durl' in result:
                    for durl in result['durl']:
                        total_size += durl.get('size', 0)
                        print(f"[TV下载] FLV段: {durl.get('size') / (1024*1024):.2f} MB")
                
                # 转换为MB
                size_mb = total_size / (1024 * 1024)
                print(f"[TV下载] 总大小: {size_mb:.2f} MB")
                return size_mb
            else:
                print(f"[TV下载] API返回错误: {data.get('message', '未知错误')}")
                return None
        
        except requests.exceptions.RequestException as e:
            print(f"[TV下载] 网络请求失败: {str(e)}")
            return None
        except Exception as e:
            print(f"[TV下载] 获取视频大小异常: {str(e)}")
            import traceback
            traceback.print_exc()
            return None