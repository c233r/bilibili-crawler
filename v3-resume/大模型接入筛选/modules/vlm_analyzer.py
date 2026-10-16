#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
VLM分析模块
使用 OpenAI 兼容方式调用智谱VLM模型分析图片内容
"""

import base64
from typing import Tuple, Optional

from pydantic import BaseModel, Field

# 尝试导入日志模块，如果失败则使用print
try:
    from pipeline.logger import ThreadLogger
    _has_logger = True
except ImportError:
    _has_logger = False


class AnalysisResult(BaseModel):
    """分析结果结构化输出模型"""
    satisfied: bool = Field(
        description="图片内容是否满足检测条件，满足为True，不满足为False"
    )
    reason: str = Field(
        description="判断理由的简要说明"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="判断的置信度，范围0-1"
    )


def image_to_base64(image_path_or_bytes) -> str:
    """
    将图片转换为base64编码（支持文件路径或字节数据）
    
    Args:
        image_path_or_bytes: 图片文件路径或图片字节数据
        
    Returns:
        base64编码字符串
    """
    if isinstance(image_path_or_bytes, str):
        # 如果是文件路径，读取文件
        with open(image_path_or_bytes, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    elif isinstance(image_path_or_bytes, bytes):
        # 如果是字节数据，直接编码
        return base64.b64encode(image_path_or_bytes).decode('utf-8')
    else:
        raise ValueError("image_path_or_bytes 必须是文件路径字符串或字节数据")


class VLMAnalyzer:
    """
    VLM分析器类
    使用 LangChain + PydanticOutputParser 确保大模型输出结构化JSON
    直接复用现有的 AnalysisResult Pydantic 模型
    """
    
    def __init__(self, api_key: str, model: str = "glm-4v-flash"):
        """
        初始化VLM分析器（使用OpenAI兼容接口）
        
        Args:
            api_key: 智谱API Key
            model: 使用的模型名称
        """

        from langchain_openai import ChatOpenAI
        from langchain_core.output_parsers import StrOutputParser, PydanticOutputParser
        
        self.model = model
        self.api_key = api_key
        
        # 使用智谱的OpenAI兼容接口
        self.llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            temperature=0.1,  # 低温度使输出更稳定
        )
        
        # 使用 PydanticOutputParser（推荐方式，直接复用 AnalysisResult 模型）
        self.output_parser = PydanticOutputParser(pydantic_object=AnalysisResult)
        self.str_parser = StrOutputParser()
        
        # 获取格式说明（由 Pydantic 模型自动生成）
        self.format_instructions = self.output_parser.get_format_instructions()
    
    def _log(self, message: str, level: int = 1):
        """日志输出（优先使用上下文日志器，回退到print）"""
        ThreadLogger.log(message, level)
    
    def analyze(self, image_path: str, prompt: str, timestamp: float = None) -> Tuple[bool, AnalysisResult]:
        """
        分析图片并返回结构化结果（使用LangChain链式调用，StrOutputParser + PydanticOutputParser）
        
        Args:
            image_path: 图片文件路径或字节数据
            prompt: 分析提示词
            timestamp: 当前帧在视频中的时间位置（秒）
            
        Returns:
            (是否成功, AnalysisResult对象)
        """
        try:
            from langchain_core.messages import HumanMessage
            from langchain_core.prompts import PromptTemplate
            
            # 读取图片并转换为base64
            image_base64 = image_to_base64(image_path)
            
            # 打印时间戳信息
            if timestamp is not None:
                self._log(f"[VLMAnalyzer] 分析视频帧: {timestamp:.1f}秒", level=0)
            self._log(f"[VLMAnalyzer] 图片base64长度: {len(image_base64)}", level=0)
            
            # 构建Prompt模板（使用PydanticOutputParser自动生成的格式说明）
            # System Prompt：包含格式说明和分析问题
            system_template = """你是一个专业的图像分析助手。

{format_instructions}

不要使用Markdown代码块包裹JSON！只返回纯JSON格式！

分析问题：{prompt}
"""
            
            system_prompt_template = PromptTemplate(
                template=system_template,
                input_variables=["prompt"],
                partial_variables={"format_instructions": self.format_instructions}
            )
            
            # Human Prompt：只包含图片
            human_prompt = "请分析这张图片。"
            
            # 构建消息列表
            messages = [
                # System消息：包含格式说明和分析问题
                {
                    "role": "system",
                    "content": system_prompt_template.format(prompt=prompt)
                },
                # Human消息：包含图片
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": human_prompt
                        }
                    ]
                }
            ]
            
            self._log(f"[VLMAnalyzer] 开始调用模型: {self.model}", level=0)
            
            # 使用链式调用：llm | StrOutputParser() | PydanticOutputParser
            # PydanticOutputParser会直接返回AnalysisResult对象
            chain = self.llm | self.str_parser | self.output_parser
            result = chain.invoke(messages)
            
            self._log(f"[VLMAnalyzer] 模型返回类型: {type(result)}", level=0)
            self._log(f"[VLMAnalyzer] 模型返回结果: {result}", level=0)
            
            # PydanticOutputParser直接返回AnalysisResult对象
            if isinstance(result, AnalysisResult):
                self._log(f"[VLMAnalyzer] 解析成功: satisfied={result.satisfied}, reason={result.reason[:30]}...", level=0)
                return True, result
            else:
                self._log(f"[VLMAnalyzer] 返回类型不是AnalysisResult，尝试解析", level=1)
                return self._parse_raw_result(result, prompt)
            
        except Exception as e:
            import traceback
            self._log(f"[VLMAnalyzer] 调用失败，尝试回退: {traceback.format_exc()}", level=3)
            
            # 回退到直接使用OpenAI客户端
            return self._fallback_analyze(image_path, prompt)
    
    def _parse_raw_result(self, result, prompt: str) -> Tuple[bool, AnalysisResult]:
        """解析非结构化的返回结果"""
        try:
            # 如果是字典，尝试直接构建AnalysisResult
            if isinstance(result, dict):
                return True, AnalysisResult(
                    satisfied=result.get('satisfied', False),
                    reason=result.get('reason', '未提供理由'),
                    confidence=result.get('confidence', 1.0)
                )
            # 如果是字符串，尝试解析
            elif isinstance(result, str):
                # 清理markdown代码块标记
                cleaned_result = self._clean_json_string(result)
                
                # 尝试解析为JSON
                try:
                    import json
                    parsed = json.loads(cleaned_result)
                    return True, AnalysisResult(
                        satisfied=parsed.get('satisfied', False),
                        reason=parsed.get('reason', '未提供理由'),
                        confidence=parsed.get('confidence', 1.0)
                    )
                except json.JSONDecodeError:
                    # 如果不是JSON，使用简单文本解析
                    satisfied = 'yes' in result.lower() or '满足' in result
                    return True, AnalysisResult(
                        satisfied=satisfied,
                        reason=result,
                        confidence=0.7
                    )
            else:
                return False, AnalysisResult(
                    satisfied=False,
                    reason=f"无法解析返回结果: {type(result)}",
                    confidence=0.0
                )
        except Exception as e:
            return False, AnalysisResult(
                satisfied=False,
                reason=f"解析失败: {str(e)}",
                confidence=0.0
            )
    
    def _clean_json_string(self, json_str: str) -> str:
        """清理JSON字符串中的markdown代码块标记"""
        import re
        
        # 移除markdown代码块标记 ```json ... ```
        json_str = re.sub(r'^```json\s*', '', json_str.strip())
        json_str = re.sub(r'^```\s*', '', json_str.strip())
        json_str = re.sub(r'\s*```$', '', json_str.strip())
        
        return json_str
    
    def _fallback_analyze(self, image_path: str, prompt: str) -> Tuple[bool, AnalysisResult]:
        """回退到直接使用OpenAI客户端调用"""
        try:
            from openai import OpenAI
            
            # 创建OpenAI客户端
            client = OpenAI(
                api_key=self.api_key,
                base_url="https://open.bigmodel.cn/api/paas/v4/"
            )
            
            # 读取图片并转换为base64
            image_base64 = image_to_base64(image_path)
            
            # 构建强制JSON输出的prompt
            json_prompt = f"""
请分析这张图片，并严格按照以下JSON格式返回结果：

{{
    "satisfied": true或false,
    "reason": "判断理由",
    "confidence": 0.0到1.0之间的数值
}}

分析问题：{prompt}

要求：
1. 只返回JSON格式，不要包含其他任何内容
2. 不要使用Markdown代码块包裹
3. satisfied字段表示图片内容是否满足检测条件
4. reason字段给出简要的判断理由
5. confidence字段表示您对判断的置信度
"""
            
            self._log(f"[VLMAnalyzer] 回退模式 - 开始调用模型: {self.model}", level=0)
            
            # 调用模型
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}"
                                }
                            },
                            {
                                "type": "text",
                                "text": json_prompt
                            }
                        ]
                    }
                ],
                temperature=0.1
            )
            
            # 获取响应内容
            content = response.choices[0].message.content
            self._log(f"[VLMAnalyzer] 回退模式 - 模型返回内容: {content[:200]}...", level=0)
            
            # 清理并解析JSON
            cleaned_content = self._clean_json_string(content)
            
            try:
                import json
                parsed = json.loads(cleaned_content)
                
                result = AnalysisResult(
                    satisfied=parsed.get('satisfied', False),
                    reason=parsed.get('reason', '未提供理由'),
                    confidence=parsed.get('confidence', 1.0)
                )
                
                self._log(f"[VLMAnalyzer] 回退模式 - 解析成功: satisfied={result.satisfied}", level=0)
                return True, result
                
            except json.JSONDecodeError as e:
                self._log(f"[VLMAnalyzer] 回退模式 - JSON解析失败: {e}", level=3)
                # 如果JSON解析失败，使用简单文本解析
                satisfied = 'yes' in content.lower() or '满足' in content or 'true' in content.lower()
                return True, AnalysisResult(
                    satisfied=satisfied,
                    reason=content,
                    confidence=0.6
                )
            
        except Exception as e:
            import traceback
            self._log(f"[VLMAnalyzer] 回退模式 - 调用失败: {traceback.format_exc()}", level=3)
            return False, AnalysisResult(
                satisfied=False,
                reason=f"回退分析也失败: {str(e)}",
                confidence=0.0
            )
    
    def check_satisfaction(self, image_path: str, prompt: str) -> Tuple[bool, str, bool]:
        """
        分析图片并检查是否满足条件
        
        Args:
            image_path: 图片文件路径或字节数据
            prompt: 分析提示词
            
        Returns:
            (是否成功, 分析结果描述, 是否满足条件)
        """
        success, result = self.analyze(image_path, prompt)
        
        if not success:
            return False, result.reason, False
        
        return True, result.reason, result.satisfied


class SimpleVLMAnalyzer:
    """
    简单VLM分析器类（不使用结构化输出）
    使用 OpenAI 兼容方式调用智谱API，适用于不需要严格输出格式的场景
    """
    
    def __init__(self, api_key: str, model: str = "glm-4v-flash"):
        """
        初始化简单VLM分析器（使用OpenAI兼容接口）
        
        Args:
            api_key: 智谱API Key
            model: 使用的模型名称
        """
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("请先安装openai库: pip install openai")
        
        self.model = model
        # 使用智谱的OpenAI兼容接口
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://open.bigmodel.cn/api/paas/v4/"
        )
    
    def analyze(self, image_path: str, prompt: str) -> Tuple[bool, AnalysisResult]:
        """
        分析图片
        
        Args:
            image_path: 图片文件路径或字节数据
            prompt: 分析提示词
            
        Returns:
            (是否成功, AnalysisResult对象)
        """
        try:
            image_base64 = image_to_base64(image_path)
            image_url = f"data:image/jpeg;base64,{image_base64}"
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": image_url
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
            )
            
            result = response.choices[0].message.content
            
            # 尝试解析结果
            satisfied = 'yes' in result.lower() or '满足' in result or 'true' in result.lower()
            
            return True, AnalysisResult(
                satisfied=satisfied,
                reason=result,
                confidence=0.7
            )
            
        except Exception as e:
            return False, AnalysisResult(
                satisfied=False,
                reason=f"API调用失败: {str(e)}",
                confidence=0.0
            )
    
    def check_satisfaction(self, image_path: str, prompt: str) -> Tuple[bool, str, bool]:
        """
        分析图片并检查是否满足条件（兼容旧接口）
        
        Args:
            image_path: 图片文件路径或字节数据
            prompt: 分析提示词
            
        Returns:
            (是否成功, 分析结果, 是否满足条件)
        """
        success, result = self.analyze(image_path, prompt)
        
        return success, result.reason, result.satisfied


class AsyncVLMAnalyzer:
    """
    异步VLM分析器类
    使用 asyncio + AsyncOpenAI 并发调用API，提升单线程吞吐量
    """
    
    def __init__(self, api_key: str, model: str = "glm-4v-flash", 
                 max_retries: int = 10, timeout: int = 30, logger=None):
        """
        初始化异步VLM分析器
        
        Args:
            api_key: 智谱API Key
            model: 使用的模型名称
            max_retries: 最大重试次数，默认10次
            timeout: 请求超时时间（秒）
            logger: 默认日志记录器，可选
        """
        import threading
        
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("请先安装openai库: pip install openai")
        
        self.model = model
        self.api_key = api_key
        self.max_retries = max_retries
        self.timeout = timeout
        self.default_logger = logger
        self._thread_local = threading.local()
        
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            timeout=timeout
        )
    
    @property
    def logger(self):
        """获取当前线程的日志记录器"""
        if hasattr(self._thread_local, 'logger'):
            return self._thread_local.logger
        return self.default_logger
    
    @logger.setter
    def logger(self, value):
        """设置当前线程的日志记录器"""
        self._thread_local.logger = value
    
    def _log(self, message: str, level: str = 'info'):
        """日志辅助方法"""
        if level == 'debug':
            self.logger.debug(message)
        elif level == 'info':
            self.logger.info(message)
        elif level == 'warning':
            self.logger.warning(message)
        else:
            self.logger.error(message)
    
    async def analyze(self, image_path: str, prompt: str, timestamp: float = None, 
                      max_retries: int = None) -> Tuple[bool, AnalysisResult]:
        """
        异步分析图片
        
        Args:
            image_path: 图片文件路径或字节数据
            prompt: 分析提示词
            timestamp: 当前帧在视频中的时间位置（秒）
            max_retries: 最大重试次数，None表示使用实例默认值
            
        Returns:
            (是否成功, AnalysisResult对象)
        """
        import asyncio
        import time
        import random
        
        if max_retries is None:
            max_retries = self.max_retries
        
        image_base64 = image_to_base64(image_path)
        
        if timestamp is not None:
            self._log(f"[AsyncVLMAnalyzer] 分析视频帧: {timestamp:.1f}秒")
        
        json_prompt = f"""
请分析这张图片，并严格按照以下JSON格式返回结果：

{{
    "satisfied": true或false,
    "reason": "判断理由",
    "confidence": 0.0到1.0之间的数值
}}

分析问题：{prompt}

要求：
1. 只返回JSON格式，不要包含其他任何内容
2. 不要使用Markdown代码块包裹
3. satisfied字段表示图片内容是否满足检测条件
4. reason字段给出简要的判断理由
5. confidence字段表示您对判断的置信度
"""
        
        max_retry_time = self.timeout * 3  # 总重试时间上限 = 3倍超时时间（如 90秒）
        retry_start = time.monotonic()
        
        # 每个事件循环创建独立的信号量（asyncio.run每次创建新事件循环）
        current_loop = asyncio.get_running_loop()
        loop_id = id(current_loop)
        if not hasattr(self._thread_local, '_loop_id') or self._thread_local._loop_id != loop_id:
            self._thread_local._semaphore = asyncio.Semaphore(3)
            self._thread_local._loop_id = loop_id
        semaphore = self._thread_local._semaphore
        
        for attempt in range(max_retries):
            # 检查是否超过总重试时间上限
            elapsed = time.monotonic() - retry_start
            if elapsed > max_retry_time:
                self._log(f"[AsyncVLMAnalyzer] 总重试时间已达上限({max_retry_time:.0f}秒)，放弃重试", level='warning')
                break
            
            try:
                async with semaphore:
                    response = await asyncio.wait_for(
                        self.client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:image/jpeg;base64,{image_base64}"
                                            }
                                        },
                                        {
                                            "type": "text",
                                            "text": json_prompt
                                        }
                                    ]
                                }
                            ],
                            temperature=0.1
                        ),
                        timeout=self.timeout
                    )
                
                content = response.choices[0].message.content
                
                try:
                    import json
                    cleaned_content = _clean_json_string(content)
                    parsed = json.loads(cleaned_content)
                    
                    result = AnalysisResult(
                        satisfied=parsed.get('satisfied', False),
                        reason=parsed.get('reason', '未提供理由'),
                        confidence=parsed.get('confidence', 1.0)
                    )
                    
                    return True, result
                    
                except json.JSONDecodeError:
                    satisfied = 'yes' in content.lower() or '满足' in content or 'true' in content.lower()
                    return True, AnalysisResult(
                        satisfied=satisfied,
                        reason=content,
                        confidence=0.6
                    )
                    
            except asyncio.TimeoutError:
                error_msg = f"[AsyncVLMAnalyzer] 第{attempt+1}/{max_retries}次调用超时"
                self._log(error_msg, level='error')
                if attempt < max_retries - 1:
                    wait_time = random.uniform(2, 5) + (attempt * 2)
                    self._log(f"[AsyncVLMAnalyzer] 等待 {wait_time:.1f}秒 后重试...", level='warning')
                    await asyncio.sleep(wait_time)
                    
            except Exception as e:
                from openai import APIConnectionError, APIError, RateLimitError
                from openai import APIStatusError
                
                error_msg = f"[AsyncVLMAnalyzer] 第{attempt+1}/{max_retries}次调用失败: {str(e)}"
                self._log(error_msg, level='error')
                
                is_retriable = False
                wait_time = 2 + (attempt * 2)
                
                if isinstance(e, APIStatusError):
                    if e.status_code == 412:
                        error_msg = f"[AsyncVLMAnalyzer] 第{attempt+1}/{max_retries}次调用返回412状态码（条件不满足）"
                        self._log(error_msg, level='error')
                        is_retriable = True
                        wait_time = random.uniform(10, 20) + (attempt * 5)
                    elif e.status_code in [429, 500, 502, 503, 504]:
                        is_retriable = True
                        wait_time = random.uniform(5, 10) + (attempt * 3)
                elif isinstance(e, (APIConnectionError, APIError)):
                    is_retriable = True
                    wait_time = random.uniform(3, 6) + (attempt * 2)
                elif isinstance(e, RateLimitError):
                    is_retriable = True
                    wait_time = random.uniform(10, 15) + (attempt * 5)
                
                if is_retriable and attempt < max_retries - 1:
                    self._log(f"[AsyncVLMAnalyzer] 等待 {wait_time:.1f}秒 后重试...", level='warning')
                    await asyncio.sleep(wait_time)
                else:
                    break
        
        self._log(f"[AsyncVLMAnalyzer] 所有{max_retries}次重试均失败", level='error')
        return False, AnalysisResult(
            satisfied=False,
            reason=f"API调用失败，已重试{max_retries}次",
            confidence=0.0
        )


def _clean_json_string(json_str: str) -> str:
    """清理JSON字符串中的markdown代码块标记（独立函数）"""
    import re
    
    json_str = re.sub(r'^```json\s*', '', json_str.strip())
    json_str = re.sub(r'^```\s*', '', json_str.strip())
    json_str = re.sub(r'\s*```$', '', json_str.strip())
    
    return json_str