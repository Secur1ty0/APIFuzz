# -*- coding: utf-8 -*-
# core/openapi3.py
"""
OpenAPI 3.x 处理模块
专门处理 OpenAPI 3.0 和 3.1 格式的API文档
参考swagger2.py的设计模式，实现简洁高效的处理
"""

import json
import random
import string
import time
import csv
from typing import Dict, Any, List, Tuple, Optional
from .base import BaseFuzzer
from colorama import Fore, Style
from tqdm import tqdm

class OpenAPI3Fuzzer(BaseFuzzer):
    """OpenAPI 3.x API 模糊测试器"""
    
    def __init__(self, spec_data: Dict[str, Any], base_url: str, proxy: Optional[str] = None,
                 threads: int = 1, output_format: str = "csv", delay: float = 0,
                 extra_headers: Optional[Dict[str, str]] = None):
        super().__init__(spec_data, base_url, proxy, threads, output_format, delay, extra_headers)
        
        # 直接访问spec_data，参考swagger2.py的简洁方式
        self.components = spec_data.get("components", {})
        self.schemas = self.components.get("schemas", {})
        
        # 支持的HTTP方法
        self.supported_methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
        
        # 基类已包含所有共通测试值，无需重复定义
        
        # 进度条相关 - 参考swagger2.py
        self.progress = None
        self.notable_results = []  # 存储值得注意的结果（2xx, 3xx, 5xx）
    
    def fuzz(self) -> None:
        """开始模糊测试 - 参考swagger2.py的完整实现"""
        print(f"[+] 开始 OpenAPI 3.x 模糊测试，线程数: {self.threads}")
        
        # 提取端点
        self.extract_endpoints()
        
        if not self.endpoints:
            print("[!] 没有找到可测试的 API 端点")
            return
        
        # 将端点添加到队列
        for endpoint in self.endpoints:
            self.queue.put(endpoint)
        
        # 初始化进度条 - 限制长度与banner平齐
        self.progress = tqdm(total=len(self.endpoints), desc="Fuzzing", 
                           bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]',
                           ncols=80)
        
        # 启动工作线程
        self.run_threads()
        
        # 关闭进度条
        if self.progress:
            self.progress.close()
        
        # 显示结果摘要
        self.show_summary()
        
        # 保存结果
        self.save_results()
    
    def worker(self) -> None:
        """工作线程函数 - 完全参考1.0版本风格"""
        while not self.queue.empty():
            try:
                method, path, details = self.queue.get()
                method, url, headers, params, body, files = self.prepare_request(method, path, details)
                time.sleep(self.delay)
                try:
                    resp = self.send_request(method, url, headers, params, body, files)
                    content_type = resp.headers.get("Content-Type", "")
                    status = str(resp.status_code)

                    if status == "200" and b"Burp Suite" in resp.content:
                        status = "error"

                    self.results.append((
                        method, url, status, len(resp.content), content_type,
                        json.dumps(headers), body if isinstance(body, str) else "<binary>",
                        json.dumps(dict(resp.headers)), resp.text[:200]
                    ))

                    status_color = self.get_status_color(status)
                    if self.progress:
                        self.progress.write(f"{status_color}[{method:<7}] {url:<80} -> {status:<4} {Style.RESET_ALL}")
                    else:
                        print(f"{status_color}[{method:<7}] {url:<80} -> {status:<4} {Style.RESET_ALL}")
                        
                except Exception as err:
                    simplified_error = self.simplify_error_message(str(err))
                    if self.progress:
                        self.progress.write(f"{Fore.LIGHTBLACK_EX}[{method:<7}] {url:<80} -> ERROR: {simplified_error}{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.LIGHTBLACK_EX}[{method:<7}] {url:<80} -> ERROR: {simplified_error}{Style.RESET_ALL}")
                        
                if self.progress:
                    self.progress.update(1)
            finally:
                self.queue.task_done()
    

    
    def _show_all_result(self, method: str, url: str, status: str, error_info: str = None) -> None:
        """显示所有结果 - 完全匹配1.0版本风格"""
        # 使用基类的get_status_color方法，确保风格一致
        status_color = self.get_status_color(status)
        
        # 如果有错误信息且状态为ERROR，在状态后追加错误信息
        if status == "ERROR" and error_info:
            display_status = f"{status}: {error_info}"
        else:
            display_status = status
        
        # 完全匹配1.0版本的格式：颜色包围整行，状态码左对齐4字符
        tqdm.write(f"{status_color}[{method:<6}  ] {url:<80} -> {display_status:<20}{Style.RESET_ALL}")
    


    def extract_endpoints(self) -> None:
        """提取所有API端点 - OpenAPI 3.x版本"""
        paths = self.spec_data.get("paths", {})
        total_paths = len(paths)
        total_operations = 0
        
        for path, methods in paths.items():
            for method, details in methods.items():
                if method.upper() in self.supported_methods:
                    # 增强端点信息
                    endpoint_info = {
                        "method": method.upper(),
                        "path": path,
                        "summary": details.get("summary", ""),
                        "description": details.get("description", ""),
                        "parameters": details.get("parameters", []),
                        "requestBody": details.get("requestBody", {}),
                        "responses": details.get("responses", {}),
                    }
                    self.endpoints.append((method.upper(), path, endpoint_info))
                    total_operations += 1
        
        print(f"[+] OpenAPI 3.x 解析完成: {total_paths} 个路径, {total_operations} 个操作")
        print(f"[+] 从 OpenAPI 3.x 中提取到 {len(self.endpoints)} 个 API 端点")

    def prepare_request(self, method: str, path: str, details: Dict[str, Any]) -> Tuple[str, str, Dict[str, str], Dict[str, Any], Optional[str], Optional[Dict]]:
        """
        准备请求参数 - OpenAPI 3.x版本
        返回: (method, url, headers, params, body, files)
        """
        headers = {"User-Agent": "APIFuzz/2.0"}
        params = {}
        body = None
        files = None
        
        # HEAD和OPTIONS方法过滤：不需要查询参数和请求体
        if method.upper() in ["HEAD", "OPTIONS"]:
            url = self.base_url + path
            
            # 只处理路径参数（必需的）和必要的头部参数
            parameters = details.get("parameters", [])
            for param in parameters:
                param_in = param.get("in", "query")
                if param_in == "path":
                    name = param["name"]
                    value = self._generate_param_value(param)
                    url = url.replace(f"{{{name}}}", str(value))
                elif param_in == "header" and param.get("required", False):
                    # 只添加必需的头部参数
                    name = param["name"]
                    value = self._generate_param_value(param)
                    headers[name] = str(value)
            
            return method, url, headers, params, body, files
        
        parameters = details.get("parameters", [])
        request_body = details.get("requestBody", {})
        
        # 处理路径参数
        url = self.base_url + path
        for param in parameters:
            if param.get("in") == "path":
                name = param["name"]
                value = self._generate_param_value(param)
                url = url.replace(f"{{{name}}}", str(value))
        
        # 处理查询参数
        for param in parameters:
            if param.get("in") == "query":
                name = param["name"]
                value = self._generate_param_value(param)
                params[name] = value
        
        # 处理头部参数
        for param in parameters:
            if param.get("in") == "header":
                name = param["name"]
                value = self._generate_param_value(param)
                headers[name] = str(value)
        
        # 兼容 GET 方法 body 参数为 query 参数，且对象参数平铺
        if method.upper() == "GET":
            body_params = [param for param in parameters if param.get("in") == "body"]
            for param in body_params:
                param_name = param.get("name", "param")
                param_schema = param.get("schema", {})
                param_value = self.mock_schema(param_schema)
                if isinstance(param_value, dict):
                    for k, v in param_value.items():
                        params[k] = v
                else:
                    params[param_name] = param_value
        
        # 处理请求体 - OpenAPI 3.x的requestBody
        if request_body and method.upper() in ["POST", "PUT", "PATCH", "DELETE"]:
            body, files = self._handle_request_body(request_body, headers)
        
        return method, url, headers, params, body, files
    
    def _generate_param_value(self, param: Dict[str, Any]) -> Any:
        """为单个参数生成值 - OpenAPI 3.x版本"""
        # OpenAPI 3.x参数结构：schema包含类型信息
        schema = param.get("schema", {})
        param_type = schema.get("type", "string")
        param_format = schema.get("format")
        param_enum = schema.get("enum")
        
        return self.generate_test_value(param_type, param_format, enum=param_enum)
    
    def _handle_request_body(self, request_body: Dict[str, Any], headers: Dict[str, str]) -> Tuple[Optional[str], Optional[Dict]]:
        """
        处理OpenAPI 3.x的requestBody
        返回: (body, files)
        """
        content = request_body.get("content", {})
        if not content:
            return None, None
        
        # 选择第一个content-type进行处理
        for content_type, content_info in content.items():
            schema = content_info.get("schema", {})
            mock_data = self.mock_schema(schema)
            
            return self._handle_content_type(content_type, mock_data, headers)
        
        return None, None
    
    def _handle_content_type(self, content_type: str, mock_data: Any, headers: Dict[str, str]) -> Tuple[Optional[str], Optional[Dict]]:
        """
        根据content-type处理数据 - 参考swagger2.py和1.0版本
        返回: (body, files)
        """
        body = None
        files = None
        
        if content_type.endswith("+json") or content_type == "application/json":
            # 智能检测：检查是否包含二进制数据，如果是则转换为字符串格式
            if self._contains_binary_data(mock_data):
                mock_data = self._convert_binary_to_string(mock_data)
            
            # 安全JSON序列化
            try:
                body = json.dumps(mock_data)
                headers["Content-Type"] = content_type
            except (TypeError, ValueError) as e:
                # 如果JSON序列化仍然失败，尝试进一步清理数据
                mock_data = self._sanitize_for_json(mock_data)
                body = json.dumps(mock_data)
                headers["Content-Type"] = content_type
            
        elif content_type == "multipart/form-data":
            # multipart/form-data处理 - 参考swagger2.py
            files = {}
            if isinstance(mock_data, dict):
                for key, value in mock_data.items():
                    if isinstance(value, bytes):
                        files[key] = (f"{key}.bin", value, "application/octet-stream")
                    else:
                        files[key] = (None, str(value))
            # 不设置Content-Type，让requests自动处理
            
        elif content_type == "application/x-www-form-urlencoded":
            # URL编码表单处理
            if isinstance(mock_data, dict):
                from urllib.parse import urlencode
                body = urlencode(mock_data)
                headers["Content-Type"] = content_type
                
        elif content_type == "application/octet-stream":
            # 二进制流 - 1.0版本启发
            body = self.test_values["octet-stream"]
            headers["Content-Type"] = content_type
            
        elif content_type == "application/pdf":
            # PDF文件 - 1.0版本启发
            body = self.test_values["pdf"]
            headers["Content-Type"] = content_type
            
        elif content_type == "application/zip":
            # ZIP文件 - 1.0版本启发
            body = self.test_values["zip"]
            headers["Content-Type"] = content_type
            
        elif content_type == "text/plain":
            # 纯文本 - 1.0版本启发
            body = self.test_values["plain-text"]
            headers["Content-Type"] = content_type
            
        elif content_type == "application/xml" or content_type.endswith("+xml"):
            # XML处理 - 1.0版本启发
            body = self.test_values["xml"]
            headers["Content-Type"] = content_type
            
        else:
            # 默认JSON处理
            body = json.dumps(mock_data) if mock_data else json.dumps({"default": "test"})
            headers["Content-Type"] = "application/json"
        
        return body, files
    
    def _contains_binary_data(self, data: Any) -> bool:
        """
        递归检查数据中是否包含二进制数据
        """
        if isinstance(data, bytes):
            return True
        elif isinstance(data, dict):
            return any(self._contains_binary_data(value) for value in data.values())
        elif isinstance(data, list):
            return any(self._contains_binary_data(item) for item in data)
        elif isinstance(data, str):
            # 检查字符串是否看起来像base64编码的二进制数据
            return len(data) > 100 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' for c in data)
        return False
    
    def _convert_binary_to_string(self, data: Any) -> Any:
        """
        将二进制数据转换为字符串格式，保持JSON兼容性
        """
        if isinstance(data, bytes):
            # 将bytes转换为base64字符串
            import base64
            return base64.b64encode(data).decode('utf-8')
        elif isinstance(data, dict):
            # 递归处理字典
            return {key: self._convert_binary_to_string(value) for key, value in data.items()}
        elif isinstance(data, list):
            # 递归处理列表
            return [self._convert_binary_to_string(item) for item in data]
        else:
            # 其他类型保持不变
            return data
    
    def _sanitize_for_json(self, data: Any) -> Any:
        """
        进一步清理数据以确保JSON序列化成功
        """
        if isinstance(data, dict):
            # 递归处理字典，移除无法序列化的键值对
            result = {}
            for key, value in data.items():
                try:
                    # 尝试序列化单个值
                    json.dumps(value)
                    result[key] = value
                except (TypeError, ValueError):
                    # 如果单个值无法序列化，转换为字符串
                    result[key] = str(value)
            return result
        elif isinstance(data, list):
            # 递归处理列表
            result = []
            for item in data:
                try:
                    json.dumps(item)
                    result.append(item)
                except (TypeError, ValueError):
                    result.append(str(item))
            return result
        else:
            # 其他类型转换为字符串
            return str(data)
    
    def generate_test_value(self, param_type: str, param_format: Optional[str] = None, 
                          items: Optional[Dict] = None, enum: Optional[List] = None) -> Any:
        """
        生成测试值 - 参考swagger2.py的实现
        """
        # 如果有枚举值，随机选择一个
        if enum:
            return random.choice(enum)
        
        # 处理数组类型
        if param_type == "array":
            if items:
                item_type = items.get("type", "string")
                item_format = items.get("format")
                item_enum = items.get("enum")
                return [self.generate_test_value(item_type, item_format, enum=item_enum)]
            return self.test_values["array"]
        
        # 处理文件类型
        if param_type == "file":
            return self.test_values["file"]
        
        # 处理数值类型
        if param_type in ["integer", "int"]:
            if param_format == "int32":
                return self.test_values["int32"]
            elif param_format == "int64":
                return self.test_values["int64"]
            else:
                return self.test_values["integer"]
        
        if param_type == "number":
            if param_format == "double":
                return self.test_values["double"]
            elif param_format == "float":
                return self.test_values["float"]
            else:
                return self.test_values["number"]
        
        # 处理字符串类型及其格式
        if param_type == "string":
            if param_format:
                format_mapping = {
                    "date": self.test_values["date"],
                    "date-time": self.test_values["date-time"],
                    "uuid": self.test_values["uuid"],
                    "email": self.test_values["email"],
                    "uri": self.test_values["uri"],
                    "url": self.test_values["uri"],
                    "password": self.test_values["password"],
                    "byte": self.test_values["byte"],
                    "binary": self.test_values["binary"],  # 1.0版本启发
                    "int32": str(self.test_values["int32"]),
                    "int64": str(self.test_values["int64"]),
                    "double": str(self.test_values["double"]),
                }
                return format_mapping.get(param_format, self.test_values["string"])
            return self.test_values["string"]
        
        # 处理布尔类型
        if param_type == "boolean":
            return self.test_values["boolean"]
        
        # 处理对象类型
        if param_type == "object":
            return self.test_values["object"]
        
        # 兜底返回字符串
        return self.test_values.get(param_type, "test")
    
    def resolve_schema_ref(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """解析 $ref 引用 - OpenAPI 3.x版本"""
        if "$ref" in schema:
            ref = schema["$ref"]
            if ref.startswith("#/components/schemas/"):
                schema_name = ref.replace("#/components/schemas/", "")
                return self.schemas.get(schema_name, {})
        return schema
    
    def mock_schema(self, schema: Dict[str, Any], components: Optional[Dict] = None, 
                   visited_refs: Optional[set] = None) -> Any:
        """
        根据 schema 生成模拟数据 - OpenAPI 3.x版本，参考swagger2.py
        """
        if visited_refs is None:
            visited_refs = set()
        
        # 解析 $ref
        if "$ref" in schema:
            ref = schema["$ref"]
            if ref in visited_refs:
                # 防止循环引用 - 1.0版本启发
                return "<circular-ref>"
            visited_refs.add(ref)
            resolved_schema = self.resolve_schema_ref(schema)
            result = self.mock_schema(resolved_schema, components, visited_refs)
            visited_refs.remove(ref)
            return result
        
        schema_type = schema.get("type", "object")
        schema_format = schema.get("format")
        enum_values = schema.get("enum")
        
        # 使用专门的生成函数处理所有类型
        if schema_type in ["string", "integer", "number", "boolean", "file"]:
            return self.generate_test_value(schema_type, schema_format, enum=enum_values)
        
        # 特殊处理：如果schema_type是string但format是binary，直接返回二进制数据
        if schema_type == "string" and schema_format == "binary":
            return self.test_values["binary"]
        
        # 处理数组
        if schema_type == "array":
            items = schema.get("items", {})
            if items:
                item_value = self.mock_schema(items, components, visited_refs)
                return [item_value]  # 只生成一个元素，保持简洁
            return ["test"]
        
        # 处理对象
        if schema_type == "object":
            properties = schema.get("properties", {})
            if properties:
                result = {}
                # 限制属性数量，避免过大的测试数据 - 参考swagger2.py
                property_items = list(properties.items())[:3]  # 最多取3个属性
                for prop_name, prop_schema in property_items:
                    result[prop_name] = self.mock_schema(prop_schema, components, visited_refs)
                return result
            return self.test_values["object"]
        
        # 兜底处理
        return self.generate_test_value(schema_type, schema_format, enum=enum_values)
