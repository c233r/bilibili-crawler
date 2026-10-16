"""
B站爬虫应用主入口
支持命令行参数配置
"""
import argparse
from view.main_window import MainWindow
from controller.controller import BilibiliController

def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='B站视频爬虫')
    parser.add_argument('--page-size', '-s', type=int, default=50, 
                        help='每页加载的视频数量（默认50，最大50）')
    parser.add_argument('--download-path', '-d', type=str, 
                        default="./downloads", help='默认下载路径')
    parser.add_argument('--max-videos', '-m', type=int, default=0, 
                        help='最大视频数量限制（0表示不限制）')
    parser.add_argument('--cookies', '-c', type=str, 
                        default=None, help='B站Cookie文件路径（用于下载720P+高清视频）')
    parser.add_argument('--use-ytdlp', action='store_true', 
                        help='使用yt-dlp下载（支持受限视频）')
    
    args = parser.parse_args()
    
    # 创建主窗口
    app = MainWindow()
    
    # 创建控制器（传入配置参数）
    controller = BilibiliController(app, 
                                    page_size=args.page_size, 
                                    max_videos=args.max_videos,
                                    cookies_path=args.cookies,
                                    use_ytdlp=args.use_ytdlp)
    
    # 设置默认下载路径
    if args.download_path:
        app.path_frame.path_var.set(args.download_path)
    
    # 启动主循环
    app.mainloop()

if __name__ == "__main__":
    main()