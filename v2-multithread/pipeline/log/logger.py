#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多线程日志管理模块
支持按线程类型分离日志文件
"""

import os
import sys
import logging
import threading
from datetime import datetime
from typing import Optional


class ThreadNameFilter(logging.Filter):
    """自定义过滤器，添加thread_name属性"""
    
    def __init__(self, thread_name: str):
        super().__init__()
        self.thread_name = thread_name
    
    def filter(self, record):
        record.thread_name = self.thread_name
        return True


class ThreadLogger:
    """
    线程专用日志类
    每个线程类型有独立的日志文件
    """
    
    # 日志级别
    LOG_LEVEL_DEBUG = logging.DEBUG
    LOG_LEVEL_INFO = logging.INFO
    LOG_LEVEL_WARNING = logging.WARNING
    LOG_LEVEL_ERROR = logging.ERROR
    
    # 线程类型
    THREAD_MAIN = "main"
    THREAD_DOWNLOAD = "download"
    THREAD_ANALYZER = "analyzer"
    THREAD_DYNAMIC = "dynamic"
    THREAD_STATS = "stats"
    
    _loggers = {}
    _lock = threading.Lock()
    
    # 线程局部存储，用于传递日志器到子模块
    _thread_local = threading.local()
    
    def __init__(self, thread_type: str, thread_id: int = 0):
        """
        初始化线程日志器
        
        Args:
            thread_type: 线程类型 (main/download/analyzer)
            thread_id: 线程ID (用于区分同一类型的不同线程)
        """
        self.thread_type = thread_type
        self.thread_id = thread_id
        self.logger = self._get_or_create_logger(thread_type, thread_id)
    
    @classmethod
    def _get_or_create_logger(cls, thread_type: str, thread_id: int) -> logging.Logger:
        """
        获取或创建线程日志器
        
        Args:
            thread_type: 线程类型
            thread_id: 线程ID
        
        Returns:
            日志器实例
        """
        logger_name = f"{thread_type}_{thread_id}"
        
        with cls._lock:
            if logger_name in cls._loggers:
                return cls._loggers[logger_name]
            
            # 创建日志器
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.DEBUG)
            logger.propagate = False  # 防止日志重复输出到根日志器
            
            # 设置线程ID属性，用于日志格式
            thread_name = f"{thread_type.capitalize()}-{thread_id}"
            logger.thread_name = thread_name
            
            # 添加自定义过滤器
            logger.addFilter(ThreadNameFilter(thread_name))
            
            # 创建日志目录
            log_dir = os.path.join(os.path.dirname(__file__), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            
            # 创建格式化器
            formatter = logging.Formatter(
                '%(asctime)s | %(thread_name)s | %(levelname)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            # 创建文件处理器（每个线程类型一个文件）
            timestamp = datetime.now().strftime("%Y%m%d")
            if thread_type == cls.THREAD_MAIN:
                log_file = os.path.join(log_dir, f"main_{timestamp}.log")
            elif thread_type == cls.THREAD_DOWNLOAD:
                log_file = os.path.join(log_dir, f"download_{thread_id}_{timestamp}.log")
            elif thread_type == cls.THREAD_ANALYZER:
                log_file = os.path.join(log_dir, f"analyzer_{thread_id}_{timestamp}.log")
            elif thread_type == cls.THREAD_STATS:
                log_file = os.path.join(log_dir, f"stats_{timestamp}.log")
            else:
                log_file = os.path.join(log_dir, f"other_{thread_id}_{timestamp}.log")
            
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            
            # 创建控制台处理器（不同线程类型不同级别）
            console_handler = logging.StreamHandler(sys.stdout)
            if thread_type == cls.THREAD_DYNAMIC:
                console_handler.setLevel(logging.ERROR)
            else:
                console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            
            # 添加处理器
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)
            
            cls._loggers[logger_name] = logger
            return logger
    
    def debug(self, message: str):
        """DEBUG级别日志"""
        self.logger.debug(message)
    
    def info(self, message: str):
        """INFO级别日志"""
        self.logger.info(message)
    
    def warning(self, message: str):
        """WARNING级别日志"""
        self.logger.warning(message)
    
    def error(self, message: str):
        """ERROR级别日志"""
        self.logger.error(message)
    
    def exception(self, message: str, exc_info: bool = True):
        """异常日志"""
        self.logger.exception(message, exc_info=exc_info)
    
    @classmethod
    def set_current_logger(cls, logger):
        """
        设置当前线程的上下文日志器
        
        Args:
            logger: ThreadLogger实例或None
        """
        cls._thread_local.logger = logger
    
    @classmethod
    def get_current_logger(cls):
        """
        获取当前线程的上下文日志器
        
        Returns:
            ThreadLogger实例，如果没有设置则返回None
        """
        return getattr(cls._thread_local, 'logger', None)
    
    @classmethod
    def log(cls, message: str, level: int = LOG_LEVEL_INFO):
        """
        便捷方法：通过上下文日志器记录日志，如果没有则使用print
        
        Args:
            message: 日志消息
            level: 日志级别
        """
        logger = cls.get_current_logger()
        if logger:
            if level == cls.LOG_LEVEL_DEBUG:
                logger.debug(message)
            elif level == cls.LOG_LEVEL_INFO:
                logger.info(message)
            elif level == cls.LOG_LEVEL_WARNING:
                logger.warning(message)
            elif level == cls.LOG_LEVEL_ERROR:
                logger.error(message)
            else:
                logger.info(message)
        else:
            print(message)


def get_main_logger() -> ThreadLogger:
    """获取主线程日志器"""
    return ThreadLogger(ThreadLogger.THREAD_MAIN, 0)


def get_download_logger(thread_id: int) -> ThreadLogger:
    """获取下载线程日志器"""
    return ThreadLogger(ThreadLogger.THREAD_DOWNLOAD, thread_id)


def get_analyzer_logger(thread_id: int) -> ThreadLogger:
    """获取分析线程日志器"""
    return ThreadLogger(ThreadLogger.THREAD_ANALYZER, thread_id)


def get_dynamic_logger(thread_id: int) -> ThreadLogger:
    """获取动态线程日志器"""
    return ThreadLogger(ThreadLogger.THREAD_DYNAMIC, thread_id)


def get_stats_logger() -> ThreadLogger:
    """获取统计监控线程日志器"""
    return ThreadLogger(ThreadLogger.THREAD_STATS, 0)