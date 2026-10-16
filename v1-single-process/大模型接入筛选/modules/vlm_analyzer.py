#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
VLM分析模块
使用 OpenAI 兼容方式调用智谱VLM模型分析图片内容
"""

import base64
from typing import Tuple, Optional

from pydantic import BaseModel, Field


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
                print(f"[VLMAnalyzer] 分析视频帧: {timestamp:.1f}秒")
            print(f"[VLMAnalyzer] 图片base64长度: {len(image_base64)}")
            
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
            
            print(f"[VLMAnalyzer] 开始调用模型: {self.model}")
            
            # 使用链式调用：llm | StrOutputParser() | PydanticOutputParser
            # PydanticOutputParser会直接返回AnalysisResult对象
            chain = self.llm | self.str_parser | self.output_parser
            result = chain.invoke(messages)
            
            print(f"[VLMAnalyzer] 模型返回类型: {type(result)}")
            print(f"[VLMAnalyzer] 模型返回结果: {result}")
            
            # PydanticOutputParser直接返回AnalysisResult对象
            if isinstance(result, AnalysisResult):
                print(f"[VLMAnalyzer] 解析成功: satisfied={result.satisfied}, reason={result.reason[:30]}...")
                return True, result
            else:
                print(f"[VLMAnalyzer] 返回类型不是AnalysisResult，尝试解析")
                return self._parse_raw_result(result, prompt)
            
        except Exception as e:
            import traceback
            print(f"[VLMAnalyzer] 调用失败，尝试回退: {traceback.format_exc()}")
            
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
            
            print(f"[VLMAnalyzer] 回退模式 - 开始调用模型: {self.model}")
            
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
            print(f"[VLMAnalyzer] 回退模式 - 模型返回内容: {content[:200]}...")
            
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
                
                print(f"[VLMAnalyzer] 回退模式 - 解析成功: satisfied={result.satisfied}")
                return True, result
                
            except json.JSONDecodeError as e:
                print(f"[VLMAnalyzer] 回退模式 - JSON解析失败: {e}")
                # 如果JSON解析失败，使用简单文本解析
                satisfied = 'yes' in content.lower() or '满足' in content or 'true' in content.lower()
                return True, AnalysisResult(
                    satisfied=satisfied,
                    reason=content,
                    confidence=0.6
                )
            
        except Exception as e:
            import traceback
            print(f"[VLMAnalyzer] 回退模式 - 调用失败: {traceback.format_exc()}")
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