# -*- coding: utf-8 -*-
# core/__init__.py
"""
核心模块初始化文件
提供版本检测和工厂函数
"""

from typing import Dict, Any, Optional, Union
from core.base import BaseFuzzer
from core.swagger2 import Swagger2Fuzzer
from core.openapi3 import OpenAPI3Fuzzer
from core.wsdl import WSDLFuzzer
from core.asmx import ASMXFuzzer
from lib.util import is_asmx_service_html






def detect_version(spec: Union[Dict[str, Any], str]) -> str:
    """
    检测API文档版本（增强版）
    
    Args:
        spec: API文档规范字典或XML字符串
        
    Returns:
        版本标识字符串: "swagger2", "openapi3", "wsdl", "asmx"
        
    Raises:
        ValueError: 当无法识别版本时抛出异常
    """
    # 检查是否为字符串格式
    if isinstance(spec, str):
        # 检查是否为WSDL/SOAP
        if "<definitions" in spec and ("xmlns:wsdl" in spec or "http://schemas.xmlsoap.org/wsdl/" in spec):
            return "wsdl"
        # 检查是否为ASP.NET .asmx服务页面（HTML格式）
        elif is_asmx_service_html(spec):
            #print("检测到ASP.NET .asmx服务页面")
            return "asmx"
        else:
            #print("检测到其他格式")
            # 尝试解析为JSON格式
            try:
                import json
                spec_dict = json.loads(spec)
                # 递归调用自身处理JSON字典
                return detect_version(spec_dict)
            except json.JSONDecodeError:
                raise ValueError("无法识别的文档格式（既不是有效的XML也不是有效的JSON）")

    
    # 1. 标准字段判断
    if "swagger" in spec:
        version = spec["swagger"]
        if version == "2.0":
            return "swagger2"
        else:
            raise ValueError(f"不支持的Swagger版本: {version}")
    if "openapi" in spec:
        version = spec["openapi"]
        if version.startswith("3."):
            return "openapi3"
        else:
            raise ValueError(f"不支持的OpenAPI版本: {version}")
    # 2. 结构性特征辅助判断
    # OpenAPI 3.x 独有结构
    if "components" in spec and isinstance(spec["components"], dict):
        comp = spec["components"]
        if any(k in comp for k in ("schemas", "securitySchemes", "parameters", "responses")):
            return "openapi3"
    if "servers" in spec and isinstance(spec["servers"], list):
        return "openapi3"
    # Swagger 2.0 独有结构
    if "definitions" in spec or "securityDefinitions" in spec:
        return "swagger2"
    if any(k in spec for k in ("host", "basePath", "schemes")):
        return "swagger2"
    if any(k in spec for k in ("consumes", "produces")):
        return "swagger2"
    # 兜底
    raise ValueError("无法识别API文档版本（无标准字段且结构特征不明显）")


def create_fuzzer(spec: Union[Dict[str, Any], str], base_url: str, proxy: Optional[str] = None, 
                 threads: int = 1, output_format: str = "csv", delay: float = 0, 
                 extra_headers: Optional[Dict[str, str]] = None, 
                 type_definition: Optional[str] = None) -> BaseFuzzer:
    """
    工厂函数：根据API文档版本自动创建对应的Fuzzer实例
    
    Args:
        spec: API文档规范字典或XML字符串
        base_url: 基础URL
        proxy: 代理设置
        threads: 线程数
        output_format: 输出格式
        delay: 请求延迟
        extra_headers: 额外请求头
        type_definition: 类型定义文件路径或URL（用于增强WSDL测试）
        
    Returns:
        对应版本的Fuzzer实例
        
    Raises:
        ValueError: 当无法识别版本时抛出异常
    """
    version = detect_version(spec)
    
    if version == "swagger2":
        return Swagger2Fuzzer(
            spec_data=spec,
            base_url=base_url,
            proxy=proxy,
            threads=threads,
            output_format=output_format,
            delay=delay,
            extra_headers=extra_headers
        )
    elif version == "openapi3":
        return OpenAPI3Fuzzer(
            spec_data=spec,
            base_url=base_url,
            proxy=proxy,
            threads=threads,
            output_format=output_format,
            delay=delay,
            extra_headers=extra_headers
        )
    elif version == "wsdl":
        return WSDLFuzzer(
            spec_data=spec,
            base_url=base_url,
            proxy=proxy,
            threads=threads,
            output_format=output_format,
            delay=delay,
            extra_headers=extra_headers,
            type_definition=type_definition
        )
    elif version == "asmx":
        return ASMXFuzzer(
            spec_data=spec,
            base_url=base_url,
            proxy=proxy,
            threads=threads,
            output_format=output_format,
            delay=delay,
            extra_headers=extra_headers,
            type_definition=type_definition
        )
    else:
        raise ValueError(f"不支持的API版本: {version}")


def get_version_info(spec: Union[Dict[str, Any], str]) -> Dict[str, str]:
    """
    获取API文档版本信息
    
    Args:
        spec: API文档规范字典或XML字符串
        
    Returns:
        包含版本信息的字典
    """
    version = detect_version(spec)
    
    if version == "swagger2":
        return {
            "title": spec.get("info", {}).get("title", "Unknown"),
            "version_info": spec.get("info", {}).get("version", ""),
            "version": spec.get("swagger", "unknown")
        }
    elif version == "openapi3":
        return {
            "title": spec.get("info", {}).get("title", "Unknown"),
            "version_info": spec.get("info", {}).get("version", ""),
            "version": spec.get("openapi", "unknown")
        }
    elif version == "wsdl":
        # 解析WSDL基本信息
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(spec)
            name = root.get('name', 'Unknown WSDL')
            target_namespace = root.get('targetNamespace', '')
            return {
                "title": f"WSDL Service: {name}",
                "version_info": "1.1",
                "version": target_namespace or "WSDL 1.1"
            }
        except Exception:
            return {
                "title": "WSDL Service",
                "version_info": "1.1", 
                "version": "WSDL 1.1"
            }
    elif version == "asmx":
        # 解析ASMX基本信息
        import re
        try:
            service_match = re.search(r'<h1[^>]*>([^<]+)</h1>', spec, re.IGNORECASE)
            service_name = service_match.group(1).strip() if service_match else "Unknown ASMX"
            return {
                "title": f"ASMX Service: {service_name}",
                "version_info": "1.0",
                "version": "ASP.NET Web Service"
            }
        except Exception:
            return {
                "title": "ASMX Service",
                "version_info": "1.0",
                "version": "ASP.NET Web Service"
            }
    else:
        return {
            "title": "Unknown",
            "version_info": "",
            "version": "unknown"
        }
