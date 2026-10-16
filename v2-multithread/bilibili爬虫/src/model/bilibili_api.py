"""
B站API模块
提供视频搜索、用户搜索、剧集搜索等功能
"""
import json
import random
import re
import time
from urllib.parse import quote

import requests

class BilibiliAPI:
    """B站API封装类"""
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://search.bilibili.com/',
            'Cookie': ''
        }
        self.wbi_keys = None
    
    def _get_wbi_signature(self, params):
        """生成WBI签名（简化版本）"""
        try:
            # 获取wbi密钥
            if not self.wbi_keys:
                resp = requests.get('https://api.bilibili.com/x/web-interface/nav', headers=self.headers)
                data = resp.json()
                if data.get('code') == 0:
                    wbi_img = data.get('data', {}).get('wbi_img', {})
                    img_key = wbi_img.get('img_url', '').split('/')[-1].split('.')[0]
                    sub_key = wbi_img.get('sub_url', '').split('/')[-1].split('.')[0]
                    self.wbi_keys = img_key + sub_key
            
            if self.wbi_keys:
                # 简单的签名生成（实际需要更复杂的算法）
                import hashlib
                params_str = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
                signature = hashlib.md5((params_str + self.wbi_keys).encode()).hexdigest()
                return signature
        except Exception as e:
            print(f"[WBI签名错误] {str(e)}")
        
        return None
    
    def search_videos(self, keyword, page=1, page_size=50):
        """搜索视频（支持分页）"""
        videos = []
        
        # B站搜索API有参数限制，最大page_size通常为50
        if page_size > 50:
            page_size = 50
        
        # 准备参数
        params = {
            'keyword': keyword,
            'page': page,
            'page_size': page_size
        }
        
        # 生成WBI签名
        signature = self._get_wbi_signature(params)
        
        if signature:
            params['w_rid'] = signature
        
        # 构建请求URL
        search_url = f"https://api.bilibili.com/x/web-interface/search/all/v2"
        
        print(f"[DEBUG] 请求URL: {search_url}")
        print(f"[DEBUG] 请求参数: {params}")
        
        try:
            response = requests.get(search_url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('code') == 0:
                result = data.get('data', {}).get('result', [])
                for item in result:
                    if isinstance(item, dict) and item.get('result_type') == 'video':
                        video_list = item.get('data', [])
                        for video in video_list:
                            videos.append({
                                'bvid': video.get('bvid', ''),
                                'title': self._clean_html(video.get('title', '')),
                                'author': video.get('author', ''),
                                'play': video.get('play', 0),
                                'video_review': video.get('video_review', 0),
                                'duration': video.get('duration', ''),
                                'description': video.get('description', ''),
                                'pic': video.get('pic', ''),
                                'pubdate': self._format_timestamp(video.get('pubdate', 0))
                            })
                        break
                    time.sleep(random.uniform(0.5, 1.0))
                
                # 返回视频列表和总数
                total = data.get('data', {}).get('numResults', len(video_list))
                return videos, total
            else:
                raise Exception(f"搜索失败: {data.get('message', '未知错误')} (code={data.get('code')})")
        except requests.exceptions.RequestException as e:
            raise Exception(f"网络请求错误: {str(e)}")
        except json.JSONDecodeError:
            raise Exception("数据解析错误")
            
        return videos, 0
    
    def search_users(self, keyword, max_results=10):
        """搜索UP主"""
        users = []
        search_url = f"https://api.bilibili.com/x/web-interface/search/all/v2?keyword={quote(keyword)}"
        
        try:
            response = requests.get(search_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('code') == 0:
                result = data.get('data', {}).get('result', [])
                for item in result:
                    if item.get('result_type') == 'bili_user':
                        user_list = item.get('data', [])
                        for user in user_list[:max_results]:
                            mid = user.get('mid', '')
                            user_info = {
                                'name': user.get('uname', ''),
                                'mid': mid,
                                'face': user.get('face', ''),
                                'fans': self._format_number(user.get('fans', 0)),
                                'videos': user.get('videos', 0),
                                'description': user.get('sign', '')
                            }
                            
                            # 如果face为空，调用用户信息API获取头像
                            if not user_info['face'] and mid:
                                user_info['face'] = self._get_user_face(mid)
                            
                            users.append(user_info)
                        break
                    time.sleep(random.uniform(0.5, 1.0))
            else:
                raise Exception(f"搜索失败: {data.get('message', '未知错误')}")
        except requests.exceptions.RequestException as e:
            raise Exception(f"网络请求错误: {str(e)}")
        except json.JSONDecodeError:
            raise Exception("数据解析错误")
        
        return users
    
    def _get_user_face(self, mid):
        """通过第三方API获取用户头像"""
        try:
            from uapi import UapiClient
            from uapi.errors import UapiError
            
            client = UapiClient("https://uapis.cn")
            result = client.social.get_social_bilibili_userinfo(uid=str(mid))
            
            if result:
                # uapi返回的数据格式：face字段是头像
                face = result.get('face', '')
                print(f"[用户头像API] mid={mid}, face={face}")
                if face:  # 确保face不为空
                    return face
                else:
                    print(f"[用户头像API警告] mid={mid}, face字段为空")
            else:
                print(f"[用户头像API失败] mid={mid}, result={result}")
        except UapiError as exc:
            print(f"[用户头像API错误] mid={mid}, UapiError: {exc}")
        except ImportError:
            # 如果 uapi 库未安装，回退到 requests 方式
            print(f"[用户头像 API] uapi 库未安装，使用 requests 方式")
            try:
                url = f"https://uapis.cn/api/v1/social/bilibili/userinfo?uid={mid}"
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                # requests方式：face字段是头像
                face = data.get('data', {}).get('face', '')
                print(f"[用户头像 API] mid={mid}, face={face}")
                if face:
                    return face
                else:
                    print(f"[用户头像 API 警告] mid={mid}, face 字段为空")
            
            except Exception as e:
                print(f"[用户头像 API 错误] mid={mid}, error={str(e)}")
        except Exception as e:
            print(f"[用户头像API错误] mid={mid}, error={str(e)}")
        
        return ''
    
    def get_user_videos(self, mid, page=1, page_size=20):
        """获取UP主的视频列表（使用uapis.cn API）"""
        videos = []
        try:
            # 使用uapis.cn的API获取UP主视频列表
            url = f"https://uapis.cn/api/v1/social/bilibili/archives?mid={mid}&page={page}&page_size={page_size}"
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # 根据实际返回的数据结构解析
            # 返回格式: {'total': 170, 'page': 1, 'size': 20, 'videos': [...]}
            video_list = data.get('videos', [])
            total = data.get('total', 0)
            
            if video_list:
                for video in video_list:
                    videos.append({
                        'title': video.get('title', ''),
                        'bvid': video.get('bvid', ''),
                        'aid': video.get('aid', ''),
                        'author': video.get('name', ''),
                        'mid': mid,
                        'play': video.get('play_count', 0),
                        'danmaku': video.get('danmaku', 0),
                        'favorites': video.get('favorites', 0),
                        'like': video.get('like', 0),
                        'review': video.get('review', 0),
                        'duration': video.get('duration', ''),
                        'pubdate': video.get('publish_time', ''),
                        'tag': video.get('tag', ''),
                        'desc': video.get('desc', ''),
                    })
                
                return videos, total
            else:
                print(f"[UP主视频API] 返回数据格式异常: {data}")
                
        except Exception as e:
            print(f"[UP主视频API错误] mid={mid}, error={str(e)}")
        
        return videos, 0
    
    def search_tv(self, keyword, page=1, page_size=50):
        """搜索剧集（支持分页）"""
        tvs = []
        
        # B站搜索API有参数限制，最大page_size通常为50
        if page_size > 50:
            page_size = 50
        
        # 准备参数
        params = {
            'keyword': keyword,
            'page': page,
            'page_size': page_size
        }
        
        # 生成WBI签名
        signature = self._get_wbi_signature(params)
        
        if signature:
            params['w_rid'] = signature
        
        # 构建请求URL
        search_url = f"https://api.bilibili.com/x/web-interface/search/all/v2"
        
        print(f"[DEBUG] 请求URL: {search_url}")
        print(f"[DEBUG] 请求参数: {params}")
        
        try:
            response = requests.get(search_url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('code') == 0:
                result = data.get('data', {}).get('result', [])
                # print(f"[DEBUG] 原始响应数据: {result}")
                
                for item in result:
                    if isinstance(item, dict):
                        result_type = item.get('result_type', '')
                        # 处理剧集类型（包括 media_bangumi 和 media_ft）
                        if result_type in ['media_bangumi', 'media_ft']:
                            item_data = item.get('data', [])
                            print(f"[DEBUG] result_type: {result_type}")
                            print(f"[DEBUG] item_data 类型：{type(item_data)}")
                            
                            if isinstance(item_data, list):
                                # data 是列表，直接遍历
                                for tv in item_data:
                                    if isinstance(tv, dict):
                                        print(f"[DEBUG] 剧集原始数据: {json.dumps(tv, ensure_ascii=False, indent=2)}")
                                        
                                        # 提取season_id（优先使用pgc_season_id，其次season_id）
                                        season_id = tv.get('pgc_season_id') or tv.get('season_id') or tv.get('media_id')
                                        media_id = tv.get('media_id', '')
                                        
                                        print(f"[DEBUG] 提取的 season_id: {season_id}")
                                        print(f"[DEBUG] 提取的 media_id: {media_id}")
                                        
                                        # 提取剧集信息
                                        tvs.append({
                                            'bvid': tv.get('bvid', ''),
                                            'title': self._clean_html(tv.get('title', '')),
                                            'url': tv.get('url', f"https://www.bilibili.com/bangumi/media/{media_id}"),
                                            'pic': tv.get('cover', ''),
                                            'season': tv.get('season_title', tv.get('org_title', '')),
                                            'episodes': tv.get('ep_size', len(tv.get('eps', []))),
                                            'score': tv.get('media_score', {}).get('score', 0) if isinstance(tv.get('media_score'), dict) else 0,
                                            'type': tv.get('season_type_name', tv.get('type_name', '')),
                                            'media_id': media_id,
                                            'season_id': season_id,
                                            'desc': self._clean_html(tv.get('desc', '')),
                                            'areas': tv.get('areas', ''),
                                            'styles': tv.get('styles', '')
                                        })
                            elif isinstance(item_data, dict):
                                # data 是字典，从 items 中获取
                                tv_list = item_data.get('items', [])
                                print(f"[DEBUG] data是字典，items数量: {len(tv_list)}")
                                
                                for tv in tv_list:
                                    print(f"[DEBUG] 剧集原始数据: {json.dumps(tv, ensure_ascii=False, indent=2)}")
                                    
                                    # 提取season_id
                                    season_id = tv.get('pgc_season_id') or tv.get('season_id') or tv.get('media_id')
                                    media_id = tv.get('media_id', '')
                                    
                                    print(f"[DEBUG] 提取的 season_id: {season_id}")
                                    print(f"[DEBUG] 提取的 media_id: {media_id}")
                                    
                                    tvs.append({
                                        'bvid': tv.get('bvid', ''),
                                        'title': self._clean_html(tv.get('title', '')),
                                        'url': f"https://www.bilibili.com/bangumi/media/{media_id}",
                                        'pic': tv.get('cover', ''),
                                        'season': tv.get('season_title', ''),
                                        'episodes': tv.get('episodes', 0),
                                        'score': tv.get('score', 0),
                                        'type': tv.get('type_name', ''),
                                        'media_id': media_id,
                                        'season_id': season_id,
                                        'desc': '',
                                        'areas': '',
                                        'styles': ''
                                    })
                
                # 返回剧集列表和总数
                total = data.get('data', {}).get('numResults', len(tvs))
                return tvs, total
            else:
                raise Exception(f"搜索失败: {data.get('message', '未知错误')} (code={data.get('code')})")
        except requests.exceptions.RequestException as e:
            raise Exception(f"网络请求错误: {str(e)}")
        except json.JSONDecodeError:
            raise Exception("数据解析错误")
            
        return tvs, 0
            
    def _clean_html(self, text):
        """清理HTML标签"""
        if not text:
            return ""
        clean = re.sub(r'<[^>]+>', '', text)
        clean = clean.replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        return clean.strip()
    
    def _format_number(self, num):
        """格式化数字（如 10000 -> 1万）"""
        if num >= 100000000:
            return f"{num/100000000:.2f}亿"
        elif num >= 10000:
            return f"{num/10000:.1f}万"
        else:
            return str(num)
    
    def _format_timestamp(self, timestamp):
        """格式化时间戳"""
        if not timestamp:
            return ""
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
