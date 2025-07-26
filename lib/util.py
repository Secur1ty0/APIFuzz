# -*- coding: utf-8 -*-
# lib/util.py

import json
import os
import requests
from urllib.parse import urlparse
from colorama import Fore


def get_status_color(status):
    """获取状态码对应的颜色"""
    if status.startswith("2"):
        return Fore.GREEN  # 成功
    elif status == "401" or status == "403":
        return Fore.RESET   # 授权失败，正常拦截
    elif status.startswith("5"):
        return Fore.RED  # 服务端错误
    elif status in ["400", "422"]:
        return Fore.YELLOW  # 客户端参数问题
    elif status.startswith("3"):
        return Fore.BLUE  # 跳转状态
    elif status == "error":  # 自定义内部错误标记
        return Fore.MAGENTA
    else:
        return Fore.RESET  # 其他


def is_asmx_service_html(content):
    """
    判断是否为ASMX HTML页面
    统一函数，供多个模块使用
    """
    # 检查HTML标签或列表项
    html_tags = ("<li", "<td", "<h1")
    list_items = ("* ", "- ")  # 支持 * 和 - 列表项
    has_structure = any(tag in content for tag in html_tags) or any(item in content for item in list_items)

    # 检查ASMX关键字
    asmx_keywords = [
        "SOAP 1.1", "SOAPAction:",
        "The following operations are supported",
        "支持下列操作",
        "Test form", "SOAP",
        "http://tempuri.org/",
        "WebService", "Namespace",
        ".asmx", ".asmx?wsdl"
    ]
    has_keywords = any(kw in content for kw in asmx_keywords)

    return has_structure and has_keywords


def load_openapi_spec(file_path, swagger_url):
    """
    加载API规范文档（支持JSON和XML/WSDL格式）
    """
    if file_path and os.path.isfile(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            # 检查是否为XML/WSDL格式
            if content.strip().startswith("<?xml") or "<definitions" in content:
                return content  # 返回原始XML字符串
            else:
                # JSON格式
                return json.loads(content)
    else:
        resp = requests.get(swagger_url, verify=False)
        resp.raise_for_status()
        
        content = resp.text
        
        # 检查是否为XML/WSDL格式
        if content.strip().startswith("<?xml") or "<definitions" in content:
            return content  # 返回原始XML字符串
        
        # 检查是否为ASMX HTML页面
        if is_asmx_service_html(content):
            return content  # 返回原始HTML字符串
        
        # 检查响应内容类型
        content_type = resp.headers.get('content-type', '').lower()
        if 'xml' in content_type:
            return content  # 返回原始XML字符串
        else:
            # 尝试解析为JSON格式
            try:
                return resp.json()
            except json.JSONDecodeError:
                # 如果JSON解析失败，返回原始内容让detect_version处理
                return content


def resolve_urls(base_url, file_path):
    """
    只做url和file的拼接，不做严格校验，允许url为任意路径。
    返回swagger_url和base_api。
    """
    parsed = urlparse(base_url)
    # 如果url本身就是json或all结尾，直接用
    if parsed.path.endswith(".json") or parsed.path.endswith("all"):
        swagger_url = base_url
        base_api = f"{parsed.scheme}://{parsed.netloc}"
    else:
        # 允许url为任意路径（如/v3/api-docs/），不再强制要求file参数
        swagger_url = base_url
        base_api = f"{parsed.scheme}://{parsed.netloc}"
    return swagger_url, base_api


def parse_headers_arg(headers_list):
    """解析命令行参数中的请求头"""
    headers = {}
    if headers_list:
        for h in headers_list:
            if ":" in h:
                k, v = h.split(":", 1)
                headers[k.strip()] = v.strip()
    return headers 