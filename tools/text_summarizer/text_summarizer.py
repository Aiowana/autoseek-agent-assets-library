import re
from typing import Annotated, Optional, Any, Literal
from pydantic import Field
from ...tools.Tools import Tool
from ...tools.types import ToolResult, TextBlock

@Tool.register(package="dynamic")
async def text_summarizer(
    text: Annotated[str, Field(description="需要摘要的文本内容")],
    summary_type: Annotated[Literal["extractive", "abstractive", "key_points"], Field(description="摘要类型：extractive(抽取式)、abstractive(生成式)、key_points(关键点)")] = "extractive",
    max_length: Annotated[Optional[int], Field(description="摘要最大长度（字符数），默认为原文的20%")] = None,
    min_length: Annotated[Optional[int], Field(description="摘要最小长度（字符数）")] = None,
    language: Annotated[Literal["zh", "en"], Field(description="文本语言：zh(中文)、en(英文)")] = "zh",
    agent: Annotated[Any, Field(description="Agent实例")] = None
) -> ToolResult:
    '''文本摘要工具，支持多种摘要模式和长度控制'''
    try:
        # 参数验证
        if len(text.strip()) == 0:
            return ToolResult.error(text="❌ 输入文本不能为空")
        
        if max_length is not None and max_length <= 0:
            return ToolResult.error(text="❌ 最大长度必须大于0")
        
        if min_length is not None and min_length <= 0:
            return ToolResult.error(text="❌ 最小长度必须大于0")
        
        if max_length is not None and min_length is not None and max_length < min_length:
            return ToolResult.error(text="❌ 最大长度不能小于最小长度")
        
        # 计算文本统计信息
        text_length = len(text)
        char_count = len(text)
        word_count = len(text.split())
        sentence_count = len(re.split(r'[。！？.!?]', text))
        paragraph_count = len([p for p in text.split('\n') if p.strip()])
        
        # 设置默认摘要长度
        if max_length is None:
            max_length = max(100, int(text_length * 0.2))  # 默认20%，至少100字符
        
        if min_length is None:
            min_length = max(50, int(max_length * 0.5))  # 默认最大长度的50%，至少50字符
        
        # 根据摘要类型生成摘要
        if summary_type == "extractive":
            summary = _extractive_summarize(text, max_length, language)
        elif summary_type == "abstractive":
            summary = _abstractive_summarize(text, max_length, language)
        elif summary_type == "key_points":
            summary = _key_points_summarize(text, max_length, language)
        else:
            return ToolResult.error(text=f"❌ 不支持的摘要类型：{summary_type}")
        
        # 确保摘要长度在范围内
        summary = _adjust_summary_length(summary, min_length, max_length)
        
        # 计算摘要统计
        summary_length = len(summary)
        compression_ratio = summary_length / text_length if text_length > 0 else 0
        
        # 构建成功响应
        success_text = f"""✅ 文本摘要生成成功

**原文统计：**
- 字符数：{char_count}
- 词数：{word_count}
- 句子数：{sentence_count}
- 段落数：{paragraph_count}

**摘要信息：**
- 摘要类型：{summary_type}
- 摘要语言：{language}
- 摘要长度：{summary_length} 字符
- 压缩比例：{compression_ratio:.1%}
- 长度范围：{min_length}-{max_length} 字符

**生成的摘要：**
{summary}

"""
        
        # 根据摘要类型添加额外信息
        if summary_type == "key_points":
            points = summary.split('\n')
            success_text += f"\n**关键点数量：** {len([p for p in points if p.strip() and p.strip().startswith(('•', '-', '1.', '2.', '3.'))])}"
        
        return ToolResult.success(
            text=success_text,
            metadata={
                "original_text": text,
                "summary": summary,
                "summary_type": summary_type,
                "language": language,
                "stats": {
                    "original_length": text_length,
                    "summary_length": summary_length,
                    "compression_ratio": compression_ratio,
                    "char_count": char_count,
                    "word_count": word_count,
                    "sentence_count": sentence_count,
                    "paragraph_count": paragraph_count
                },
                "length_constraints": {
                    "min_length": min_length,
                    "max_length": max_length
                }
            }
        )
        
    except Exception as e:
        return ToolResult.error(
            text=f"❌ 生成摘要时发生错误：{str(e)}\n\n错误类型：{type(e).__name__}",
            metadata={
                "error_type": type(e).__name__,
                "error_message": str(e)
            }
        )

def _extractive_summarize(text: str, max_length: int, language: str) -> str:
    """抽取式摘要：提取原文中的重要句子"""
    # 分割句子
    if language == "zh":
        sentences = re.split(r'[。！？]', text)
    else:
        sentences = re.split(r'[.!?]', text)
    
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if not sentences:
        return "无法提取有效句子进行摘要"
    
    # 简单的句子重要性评分（基于长度和位置）
    scored_sentences = []
    for i, sentence in enumerate(sentences):
        score = len(sentence) * 0.5  # 长度权重
        position_weight = 1.0 - (i / len(sentences)) * 0.3  # 位置权重（前面的句子更重要）
        score *= position_weight
        scored_sentences.append((score, sentence))
    
    # 按分数排序
    scored_sentences.sort(reverse=True, key=lambda x: x[0])
    
    # 选择最重要的句子，直到达到最大长度
    selected_sentences = []
    current_length = 0
    
    for score, sentence in scored_sentences:
        if current_length + len(sentence) <= max_length:
            selected_sentences.append(sentence)
            current_length += len(sentence)
        else:
            break
    
    # 按原文顺序排序
    selected_sentences = [s for s in sentences if s in selected_sentences]
    
    if language == "zh":
        return "。".join(selected_sentences) + "。"
    else:
        return ". ".join(selected_sentences) + "."

def _abstractive_summarize(text: str, max_length: int, language: str) -> str:
    """生成式摘要：生成新的摘要文本"""
    # 这里使用简化的生成式摘要
    # 在实际应用中，可以集成更复杂的NLP模型
    
    # 首先进行抽取式摘要
    extractive_summary = _extractive_summarize(text, max_length * 2, language)
    
    # 然后进行简化和重写
    if language == "zh":
        # 中文简化规则
        summary = extractive_summary.replace("非常", "").replace("极其", "").replace("特别", "")
        summary = re.sub(r'的+', '的', summary)
        summary = re.sub(r'了+', '了', summary)
    else:
        # 英文简化规则
        summary = extractive_summary.replace("very ", "").replace("extremely ", "").replace("particularly ", "")
        summary = re.sub(r'\s+', ' ', summary)
    
    return summary[:max_length]

def _key_points_summarize(text: str, max_length: int, language: str) -> str:
    """关键点摘要：提取关键信息点"""
    # 分割段落
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    
    if not paragraphs:
        return "无法提取关键点"
    
    key_points = []
    
    # 提取每个段落的关键信息
    for i, paragraph in enumerate(paragraphs[:5]):  # 最多处理前5个段落
        if language == "zh":
            # 中文关键点提取
            sentences = re.split(r'[。！？]', paragraph)
            sentences = [s.strip() for s in sentences if s.strip()]
            
            if sentences:
                # 取第一个句子作为关键点
                first_sentence = sentences[0]
                if len(first_sentence) > 10:  # 避免太短的句子
                    key_points.append(f"• {first_sentence}")
        else:
            # 英文关键点提取
            sentences = re.split(r'[.!?]', paragraph)
            sentences = [s.strip() for s in sentences if s.strip()]
            
            if sentences:
                first_sentence = sentences[0]
                if len(first_sentence) > 20:  # 避免太短的句子
                    key_points.append(f"• {first_sentence}")
    
    # 如果没有提取到关键点，使用抽取式摘要
    if not key_points:
        extractive = _extractive_summarize(text, max_length, language)
        sentences = re.split(r'[。！？.!?]', extractive)
        key_points = [f"• {s.strip()}" for s in sentences if s.strip()]
    
    # 限制长度
    result = "\n".join(key_points)
    if len(result) > max_length:
        result = result[:max_length].rsplit('\n', 1)[0]
    
    return result

def _adjust_summary_length(summary: str, min_length: int, max_length: int) -> str:
    """调整摘要长度到指定范围"""
    current_length = len(summary)
    
    if current_length < min_length:
        # 如果摘要太短，添加说明
        return summary + f"\n\n[摘要较短，建议增加输入文本的详细程度]"
    elif current_length > max_length:
        # 如果摘要太长，截断到最大长度
        return summary[:max_length].rsplit('。', 1)[0] + '。'
    
    return summary