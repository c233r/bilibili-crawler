"""
FFmpeg合并器
负责合并分离的音视频文件
"""
import os
import subprocess
import re
import shutil

class FFMpegMerger:
    """FFmpeg音视频合并器"""
    
    def __init__(self):
        self.ffmpeg_path = self._find_ffmpeg()
    
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
    
    def merge_audio_video(self, video_path, audio_path, output_path):
        """合并单个音视频文件"""
        if not self.ffmpeg_path:
            print("[FFmpeg警告] 未找到ffmpeg，无法合并音视频")
            return False, "未找到ffmpeg，请安装后重试"
        
        try:
            print(f"[FFmpeg] 合并: {video_path} + {audio_path} -> {output_path}")
            
            # 构建ffmpeg命令
            command = [
                self.ffmpeg_path,
                '-i', video_path,
                '-i', audio_path,
                '-c:v', 'copy',
                '-c:a', 'copy',
                '-y',
                output_path
            ]
            
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=300
            )
            
            if result.returncode == 0:
                print("[FFmpeg] 合并成功")
                # 删除临时文件
                try:
                    os.remove(video_path)
                    os.remove(audio_path)
                    print("[FFmpeg] 已删除临时音视频文件")
                except Exception as e:
                    print(f"[FFmpeg警告] 删除临时文件失败: {e}")
                return True, f"合并成功: {output_path}"
            else:
                print(f"[FFmpeg] 合并失败: {result.stderr}")
                return False, f"合并失败: {result.stderr}"
                
        except subprocess.TimeoutExpired:
            return False, "合并超时"
        except Exception as e:
            print(f"[FFmpeg错误] {str(e)}")
            return False, f"合并错误: {str(e)}"
    
    def batch_merge(self, directory):
        """批量合并目录中的所有分离音视频文件（递归遍历所有子目录）
        
        文件名匹配规则：按`.`划分，第一部分相同的为一对
        例如：
            第1集 - 冒险的结束.f30125.mp4  (视频)
            第1集 - 冒险的结束.f30280.m4a  (音频)
            这两个文件的第一部分都是"第1集 - 冒险的结束"，会被匹配合并
        """
        if not self.ffmpeg_path:
            print("[FFmpeg警告] 未找到ffmpeg，跳过批量合并")
            return []
        
        if not os.path.exists(directory):
            print(f"[FFmpeg错误] 目录不存在: {directory}")
            return []
        
        merged_files = []
        total_scanned = 0
        total_found = 0
        
        print(f"[FFmpeg] 开始批量合并，扫描目录: {directory}")
        
        # 支持的视频扩展名
        video_extensions = ['.mp4', '.m4v', '.webm', '.flv']
        # 支持的音频扩展名
        audio_extensions = ['.m4a', '.aac', '.mp3']
        
        for root, dirs, files in os.walk(directory):
            # 先收集所有文件，按第一部分分组
            file_groups = {}
            
            for file in files:
                total_scanned += 1
                
                # 获取文件名的第一部分（按.划分）
                first_part = file.split('.')[0]
                
                if first_part not in file_groups:
                    file_groups[first_part] = {
                        'videos': [],
                        'audios': []
                    }
                
                # 判断是视频还是音频文件
                lower_file = file.lower()
                if any(lower_file.endswith(ext) for ext in video_extensions):
                    file_groups[first_part]['videos'].append(file)
                elif any(lower_file.endswith(ext) for ext in audio_extensions):
                    file_groups[first_part]['audios'].append(file)
            
            # 遍历每个分组，进行合并
            for first_part, group in file_groups.items():
                videos = group['videos']
                audios = group['audios']
                
                if videos and audios:
                    total_found += 1
                    print(f"[FFmpeg] 发现分离文件组: {first_part}")
                    print(f"[FFmpeg]   视频文件: {videos}")
                    print(f"[FFmpeg]   音频文件: {audios}")
                    
                    # 找到最合适的视频和音频文件进行合并
                    video_path = None
                    audio_path = None
                    
                    # 优先选择.mp4和.m4a的组合
                    for v in videos:
                        if v.lower().endswith('.mp4'):
                            video_path = os.path.join(root, v)
                            break
                    if not video_path and videos:
                        video_path = os.path.join(root, videos[0])
                    
                    for a in audios:
                        if a.lower().endswith('.m4a'):
                            audio_path = os.path.join(root, a)
                            break
                    if not audio_path and audios:
                        audio_path = os.path.join(root, audios[0])
                    
                    if video_path and audio_path:
                        # 构建输出路径（使用第一部分作为基础名）
                        output_path = os.path.join(root, f"{first_part}.mp4")
                        
                        # 如果已存在合并后的文件，跳过
                        if os.path.exists(output_path):
                            print(f"[FFmpeg] 已存在，跳过: {os.path.relpath(output_path, directory)}")
                            continue
                        
                        success, msg = self.merge_audio_video(video_path, audio_path, output_path)
                        if success:
                            merged_files.append(output_path)
                            print(f"[FFmpeg] 合并成功: {os.path.relpath(output_path, directory)}")
                        else:
                            print(f"[FFmpeg] 合并失败: {msg}")
        
        # 输出统计信息
        print(f"\n[FFmpeg批量合并完成]")
        print(f"==================================================")
        print(f"扫描文件数: {total_scanned}")
        print(f"发现分离文件组: {total_found}")
        print(f"成功合并: {len(merged_files)}")
        print(f"失败: {total_found - len(merged_files)}")
        
        if merged_files:
            print("\n[合并成功的文件]")
            for f in merged_files:
                print(f"  - {os.path.relpath(f, directory)}")
        
        return merged_files