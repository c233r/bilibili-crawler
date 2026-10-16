#!/usr/bin/env python3
"""
下载管理器模块
提供通用的视频下载逻辑，支持多种下载模式
"""

import os


class DownloadManager:
    """下载管理器"""
    
    def __init__(self, downloader):
        """
        初始化下载管理器
        
        Args:
            downloader: 下载器实例（VideoDownloader或TvDownloader）
        """
        self.downloader = downloader
    
    def download_by_selection(self, items, item_type='video'):
        """
        交互式选择下载模式
        
        Args:
            items: 项目列表（视频或剧集）
            item_type: 项目类型 ('video', 'tv', 'up_video')
        
        Returns:
            下载成功的数量
        """
        print("\n" + "="*60)
        print("                    下载模式选择")
        print("="*60)
        print("1. 选择特定序号下载")
        print("2. 指定下载数量（自动从前往后）")
        print("3. 下载全部")
        print("4. 返回")
        print("="*60)
        
        while True:
            choice = input("请选择下载模式 (1-4): ").strip()
            if choice in ['1', '2', '3', '4']:
                break
            print("请输入有效的选项")
        
        if choice == '4':
            return 0
        
        success_count = 0
        if choice == '1':
            success_count = self._download_selected(items, item_type)
        elif choice == '2':
            success_count = self._download_by_count(items, item_type)
        elif choice == '3':
            success_count = self._download_all(items, item_type)
        
        # # 所有下载完成后执行批量合并
        # if success_count > 0:
        #     self._batch_merge_after_download()
        
        return success_count
    
    def _download_selected(self, items, item_type='video'):
        """
        选择特定序号下载
        
        Args:
            items: 项目列表
            item_type: 项目类型
        
        Returns:
            下载成功的数量
        """
        print("\n请输入要下载的序号（用逗号分隔，如: 1,3,5）: ")
        selection = input("序号: ").strip()
        
        if not selection:
            print("未选择任何项目")
            return 0
        
        # 解析选择的序号
        try:
            indices = [int(x.strip()) - 1 for x in selection.split(',') if x.strip().isdigit()]
        except ValueError:
            print("输入格式错误")
            return 0
        
        # 验证序号有效性
        valid_indices = [i for i in indices if 0 <= i < len(items)]
        if not valid_indices:
            print("没有有效的序号")
            return 0
        
        # 去重并排序
        valid_indices = sorted(list(set(valid_indices)))
        
        print(f"\n[下载] 准备下载 {len(valid_indices)} 个项目")
        
        success_count = 0
        for idx in valid_indices:
            item = items[idx]
            success = self._download_item(item, idx + 1, len(valid_indices), item_type)
            if success:
                success_count += 1
        
        return success_count
    
    def _download_by_count(self, items, item_type='video'):
        """
        指定数量下载（自动从前往后）
        
        Args:
            items: 项目列表
            item_type: 项目类型
        
        Returns:
            下载成功的数量
        """
        while True:
            count_input = input("\n请输入要下载的数量: ").strip()
            if count_input.isdigit():
                count = int(count_input)
                if count > 0:
                    break
            print("请输入有效的正整数")
        
        # 实际下载数量（不超过列表长度）
        actual_count = min(count, len(items))
        
        print(f"\n[下载] 准备下载前 {actual_count} 个项目")
        
        success_count = 0
        for i in range(actual_count):
            item = items[i]
            success = self._download_item(item, i + 1, actual_count, item_type)
            if success:
                success_count += 1
        
        return success_count
    
    def _download_all(self, items, item_type='video'):
        """
        下载全部项目
        
        Args:
            items: 项目列表
            item_type: 项目类型
        
        Returns:
            下载成功的数量
        """
        print(f"\n[下载] 准备下载全部 {len(items)} 个项目")
        
        success_count = 0
        for i, item in enumerate(items):
            success = self._download_item(item, i + 1, len(items), item_type)
            if success:
                success_count += 1
        
        return success_count
    
    def _download_item(self, item, current, total, item_type='video'):
        """
        下载单个项目
        
        Args:
            item: 项目信息
            current: 当前序号
            total: 总数
            item_type: 项目类型
        
        Returns:
            bool: 是否下载成功
        """
        try:
            if item_type == 'video' or item_type == 'up_video':
                bvid = item.get('bvid', '')
                title = item.get('title', '未知')
                
                if not bvid:
                    print(f"[{current}/{total}] [跳过] 无BV号: {title}")
                    return False
                
                print(f"\n[{current}/{total}] 正在下载: {title}")
                print(f"      BV号: {bvid}")
                
                success, msg = self.downloader.download(bvid, title)
                
                if success:
                    print(f"      [成功] 下载完成")
                    return True
                else:
                    print(f"      [失败] {msg}")
                    return False
            
            elif item_type == 'tv':
                season_id = item.get('season_id', '')
                title = item.get('title', '未知')
                
                if not season_id:
                    print(f"[{current}/{total}] [跳过] 无season_id: {title}")
                    return False
                
                print(f"\n[{current}/{total}] 正在下载剧集: {title}")
                print(f"      season_id: {season_id}")
                
                success, msg = self.downloader.download(season_id, title)
                
                if success:
                    print(f"      [成功] 下载完成")
                    return True
                else:
                    print(f"      [失败] {msg}")
                    return False
            
            else:
                print(f"[{current}/{total}] [跳过] 未知类型: {item_type}")
                return False
                
        except Exception as e:
            print(f"[{current}/{total}] [错误] {str(e)}")
            return False
    
    def download_items(self, items, item_type='video'):
        """
        直接下载项目列表（不显示交互式选择）
        
        Args:
            items: 项目列表
            item_type: 项目类型
        
        Returns:
            下载成功的数量
        """
        print(f"\n[下载] 准备下载 {len(items)} 个项目")
        
        success_count = 0
        for i, item in enumerate(items):
            success = self._download_item(item, i + 1, len(items), item_type)
            if success:
                success_count += 1
        
        # 所有下载完成后执行批量合并
        if success_count > 0:
            self._batch_merge_after_download()
        
        print(f"\n[完成] 下载结束，共下载 {success_count} 个视频")
        
        return success_count
    
    def _batch_merge_after_download(self):
        """所有下载完成后执行批量合并"""
        print(f"\n[合并] 开始批量合并分离的音视频文件...")
        download_path = getattr(self.downloader, 'download_path', '')
        if download_path and os.path.exists(download_path):
            merger = getattr(self.downloader, 'merger', None)
            if merger:
                merger.batch_merge(download_path)
            else:
                print(f"[合并警告] 未找到合并器")
        else:
            print(f"[合并警告] 下载路径不存在: {download_path}")


class PaginatedDownloadManager(DownloadManager):
    """
    分页下载管理器
    支持自动翻页下载，适用于UP主视频等需要分页获取的场景
    """
    
    def __init__(self, downloader, api_getter, api_params=None):
        """
        初始化分页下载管理器
        
        Args:
            downloader: 下载器实例
            api_getter: API获取函数，签名: api_getter(page, page_size) -> (items, total)
            api_params: 额外的API参数
        """
        super().__init__(downloader)
        self.api_getter = api_getter
        self.api_params = api_params or {}
    
    def download_with_pagination(self, download_count=0):
        """
        分页下载
        
        Args:
            download_count: 指定下载总数（0表示全部下载，默认由用户输入）
        
        Returns:
            下载成功的数量
        """
        page = 1
        page_size = 20
        downloaded_count = 0
        
        # 如果未指定下载数量，则询问用户
        if download_count == 0:
            print("\n" + "="*60)
            print("                    分页下载设置")
            print("="*60)
            
            # 获取下载数量
            while True:
                count_input = input(f"请输入要下载的数量（0表示全部下载）: ").strip()
                if count_input.isdigit():
                    download_count = int(count_input)
                    if download_count >= 0:
                        break
                print("请输入有效的非负整数")
        
        print(f"\n[下载] 开始下载（目标: {'全部' if download_count == 0 else download_count} 个）")
        
        while True:
            print(f"\n[获取] 正在获取第 {page} 页...")
            
            try:
                items, total = self.api_getter(page=page, page_size=page_size, **self.api_params)
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
                
                success, msg = self.downloader.download(bvid, title)
                
                if success:
                    downloaded_count += 1
                    print(f"      [成功] 下载完成")
                else:
                    print(f"      [失败] {msg}")
                
                # 检查是否达到下载数量
                if download_count > 0 and downloaded_count >= download_count:
                    print(f"\n[完成] 已达到设定的下载数量 ({downloaded_count} 个)")
                    # 下载完成后执行批量合并
                    self._batch_merge_after_download()
                    return downloaded_count
            
            # 翻页
            page += 1
        
        print(f"\n[完成] 下载结束，共下载 {downloaded_count} 个视频")
        
        # 所有下载完成后执行批量合并
        if downloaded_count > 0:
            self._batch_merge_after_download()
        
        return downloaded_count
