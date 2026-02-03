"""
HTTP Request Tool Handler

发送 HTTP 请求并返回响应。
"""

import json
from typing import Any, Dict, Optional

import requests


def run(url: str, method: str = "GET", headers: Optional[str] = None,
        body: Optional[str] = None, timeout: int = 30) -> Dict[str, Any]:
    """
    执行 HTTP 请求

    Args:
        url: 请求的 URL 地址
        method: HTTP 方法 (GET, POST, PUT, DELETE)
        headers: JSON 格式的请求头
        body: JSON 格式的请求体
        timeout: 超时时间（秒）

    Returns:
        包含响应状态、头部、内容的字典
    """
    try:
        # 解析 headers
        request_headers = {}
        if headers:
            request_headers = json.loads(headers)

        # 解析 body
        request_body = None
        if body:
            request_body = json.loads(body)

        # 发送请求
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=request_headers,
            json=request_body,
            timeout=timeout,
        )

        return {
            "success": True,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "content": response.text,
            "json": _try_parse_json(response.text),
        }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "请求超时",
            "error_type": "timeout",
        }
    except requests.exceptions.ConnectionError as e:
        return {
            "success": False,
            "error": f"连接错误: {str(e)}",
            "error_type": "connection_error",
        }
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "error": f"JSON 解析失败: {str(e)}",
            "error_type": "json_error",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": "unknown",
        }


def _try_parse_json(text: str) -> Optional[Dict]:
    """尝试解析 JSON，失败返回 None"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


if __name__ == "__main__":
    # 测试
    result = run(url="https://httpbin.org/get")
    print(json.dumps(result, ensure_ascii=False, indent=2))
