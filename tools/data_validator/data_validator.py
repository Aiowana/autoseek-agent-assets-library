import re
from typing import Annotated
from pydantic import Field
from ...tools.Tools import Tool
from ...tools.types import ToolResult, TextBlock

@Tool.register(package="dynamic")
async def validate_email(
    email: Annotated[str, Field(description="需要验证的邮箱地址")],
    agent: Annotated[Any, Field(description="Agent实例")] = None
) -> ToolResult:
    '''验证邮箱地址格式是否正确'''
    # 邮箱验证正则表达式
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if re.match(email_pattern, email):
        return ToolResult.success(
            text=f"邮箱验证通过: {email}",
            metadata={
                "email": email,
                "is_valid": True,
                "validation_type": "email"
            }
        )
    else:
        return ToolResult.error(
            text=f"邮箱格式无效: {email}",
            metadata={
                "email": email,
                "is_valid": False,
                "validation_type": "email"
            }
        )

@Tool.register(package="dynamic")
async def validate_phone(
    phone: Annotated[str, Field(description="需要验证的手机号码")],
    country_code: Annotated[str, Field(description="国家代码，如 '86' 表示中国", default="86")] = "86",
    agent: Annotated[Any, Field(description="Agent实例")] = None
) -> ToolResult:
    '''验证手机号码格式是否正确'''
    # 根据不同国家代码进行验证
    validation_rules = {
        "86": r'^1[3-9]\d{9}$',  # 中国手机号
        "1": r'^[2-9]\d{9}$',    # 美国/加拿大手机号
        "44": r'^7[1-9]\d{8}$',  # 英国手机号
        "81": r'^[7-9]0\d{8}$',  # 日本手机号
        "82": r'^01[0-9]\d{7,8}$',  # 韩国手机号
    }
    
    # 移除可能的空格和特殊字符
    phone_clean = re.sub(r'[+\-\s()]', '', phone)
    
    # 如果包含国家代码，提取纯数字部分
    if phone_clean.startswith(country_code):
        phone_number = phone_clean[len(country_code):]
    else:
        phone_number = phone_clean
    
    # 获取对应国家的验证规则
    pattern = validation_rules.get(country_code, r'^\d{10,15}$')  # 默认验证10-15位数字
    
    if re.match(pattern, phone_number):
        return ToolResult.success(
            text=f"手机号验证通过: {phone} (国家代码: {country_code})",
            metadata={
                "phone": phone,
                "phone_number": phone_number,
                "country_code": country_code,
                "is_valid": True,
                "validation_type": "phone"
            }
        )
    else:
        return ToolResult.error(
            text=f"手机号格式无效: {phone} (国家代码: {country_code})",
            metadata={
                "phone": phone,
                "phone_number": phone_number,
                "country_code": country_code,
                "is_valid": False,
                "validation_type": "phone"
            }
        )

@Tool.register(package="dynamic")
async def validate_data(
    data_type: Annotated[str, Field(description="数据类型: 'email' 或 'phone'")],
    value: Annotated[str, Field(description="需要验证的值")],
    country_code: Annotated[str, Field(description="手机号的国家代码，仅当 data_type='phone' 时有效", default="86")] = "86",
    agent: Annotated[Any, Field(description="Agent实例")] = None
) -> ToolResult:
    '''通用数据验证函数，根据数据类型调用对应的验证方法'''
    if data_type.lower() == 'email':
        return await validate_email(email=value, agent=agent)
    elif data_type.lower() == 'phone':
        return await validate_phone(phone=value, country_code=country_code, agent=agent)
    else:
        return ToolResult.error(
            text=f"不支持的数据类型: {data_type}。支持的类型: 'email', 'phone'",
            metadata={
                "data_type": data_type,
                "value": value,
                "is_valid": False,
                "error": "unsupported_data_type"
            }
        )