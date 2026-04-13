import json
from typing import Annotated, Optional
from pydantic import Field
from ...tools.Tools import Tool
from ...tools.types import ToolResult, TextBlock

@Tool.register(package="dynamic")
async def json_formatter(
    json_string: Annotated[str, Field(description="需要格式化的JSON字符串")],
    indent: Annotated[Optional[int], Field(description="缩进空格数，默认为2")] = 2,
    sort_keys: Annotated[Optional[bool], Field(description="是否按键名排序，默认为True")] = True,
    ensure_ascii: Annotated[Optional[bool], Field(description="是否确保ASCII编码，默认为False")] = False,
    agent: Annotated[Any, Field(description="Agent实例")] = None
) -> ToolResult:
    '''格式化JSON字符串，支持美化输出和验证'''
    try:
        # 解析JSON字符串
        parsed_json = json.loads(json_string)
        
        # 格式化JSON
        formatted_json = json.dumps(
            parsed_json,
            indent=indent,
            sort_keys=sort_keys,
            ensure_ascii=ensure_ascii
        )
        
        # 计算统计信息
        stats = {
            "type": type(parsed_json).__name__,
            "length": len(parsed_json) if isinstance(parsed_json, (dict, list)) else 1,
            "valid": True
        }
        
        return ToolResult.success(
            text=f"✅ JSON格式化成功

**格式化后的JSON：**
