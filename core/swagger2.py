# -*- coding: utf-8 -*-
# core/swagger2.py
"""
Swagger 2.0 处理模块
专门处理 Swagger 2.0 (OpenAPI 2.0) 格式的API文档
"""

import json
import random
import string
import time
import re
from urllib.parse import urlencode, quote
from typing import Dict, Any, List, Tuple, Optional
from .base import BaseFuzzer
from colorama import Fore, Style
from tqdm import tqdm

class Swagger2Fuzzer(BaseFuzzer):
    """Swagger 2.0 API 模糊测试器"""
    
    def __init__(self, spec_data: Dict[str, Any], base_url: str, proxy: Optional[str] = None,
                 threads: int = 1, output_format: str = "csv", delay: float = 0,
                 extra_headers: Optional[Dict[str, str]] = None):
        super().__init__(spec_data, base_url, proxy, threads, output_format, delay, extra_headers)
        
        # 直接访问spec_data，不需要parser层
        self.definitions = spec_data.get("definitions", {})
        
        # 进度条相关
        self.progress = None
        self.notable_results = []  # 存储值得注意的结果（2xx, 3xx, 5xx）
        
        # 测试值定义
        self.test_values = {
            "string": "test_string",
            "integer": 123,
            "int32": 123,
            "int64": 123456789,
            "long": 123456789,
            "number": 123.45,
            "double": 123.45,
            "float": 123.45,
            "boolean": True,
            "array": ["item1", "item2"],
            "object": {"key": "value"},
            "file": "test_file.txt",
            "date": "2023-01-01",
            "date-time": "2023-01-01T12:00:00Z",
            "email": "test@example.com",
            "password": "test_password",
            "uuid": "123e4567-e89b-12d3-a456-426614174000",
            "uri": "https://example.com",
            "ipv4": "192.168.1.1",
            "ipv6": "2001:db8::1"
        }
    
    def fuzz(self) -> None:
        """开始模糊测试 - 重写版本，添加进度条"""
        print(f"[+] 开始 Swagger 2.0 模糊测试，线程数: {self.threads}")
        
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

    def generate_test_value(self, param_type: str, param_format: Optional[str] = None, 
                          items: Optional[Dict] = None, enum: Optional[List] = None) -> Any:
        """
        专门的数据类型生成函数
        根据类型和格式生成合适的测试值
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
        
        # 处理数值类型（包括format）
        if param_type in ["integer", "int"]:
            if param_format == "int32":
                return self.test_values["int32"]
            elif param_format == "int64":
                return self.test_values["int64"]
            else:
                return self.test_values["integer"]
        
        if param_type == "long":
            return self.test_values["long"]
        
        if param_type == "number":
            if param_format == "double":
                return self.test_values["double"]
            elif param_format == "float":
                return self.test_values["float"]
            else:
                return self.test_values["number"]
        
        # 处理字符串类型（包括format）
        if param_type == "string":
            if param_format == "date":
                return self.test_values["date"]
            elif param_format == "date-time":
                return self.test_values["date-time"]
            elif param_format == "email":
                return self.test_values["email"]
            elif param_format == "password":
                return self.test_values["password"]
            elif param_format == "uuid":
                return self.test_values["uuid"]
            elif param_format == "uri":
                return self.test_values["uri"]
            elif param_format == "ipv4":
                return self.test_values["ipv4"]
            elif param_format == "ipv6":
                return self.test_values["ipv6"]
            else:
                return self.test_values["string"]
        
        # 处理布尔类型
        if param_type == "boolean":
            return self.test_values["boolean"]
        
        # 处理对象类型
        if param_type == "object":
            return self.test_values["object"]
        
        # 默认返回字符串
        return self.test_values["string"]
    
    def resolve_schema_ref(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """解析schema引用"""
        if "$ref" in schema:
            ref = schema["$ref"]
            if ref.startswith("#/definitions/"):
                definition_name = ref.split("/")[-1]
                return self.definitions.get(definition_name, {})
        return schema
    
    def mock_schema(self, schema: Dict[str, Any], components: Optional[Dict] = None, 
                   visited_refs: Optional[set] = None) -> Any:
        """根据schema生成模拟数据"""
        if visited_refs is None:
            visited_refs = set()
        
        # 解析引用
        schema = self.resolve_schema_ref(schema)
        
        # 处理数组类型
        if schema.get("type") == "array":
            items = schema.get("items", {})
            if isinstance(items, list):
                return [self.mock_schema(item, components, visited_refs) for item in items]
            else:
                return [self.mock_schema(items, components, visited_refs)]
        
        # 处理对象类型
        if schema.get("type") == "object" or "properties" in schema:
            properties = schema.get("properties", {})
            result = {}
            for prop_name, prop_schema in properties.items():
                if prop_name not in visited_refs:
                    visited_refs.add(prop_name)
                    result[prop_name] = self.mock_schema(prop_schema, components, visited_refs)
                    visited_refs.remove(prop_name)
            return result
        
        # 处理基本类型
        param_type = schema.get("type", "string")
        param_format = schema.get("format")
        enum = schema.get("enum")
        
        return self.generate_test_value(param_type, param_format, enum=enum)
    
    def extract_endpoints(self) -> None:
        """提取API端点"""
        paths = self.spec_data.get("paths", {})
        
        for path, path_item in paths.items():
            for method, operation in path_item.items():
                if method.upper() in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
                    self.endpoints.append((method.upper(), path, operation))
        
        print(f"[+] Swagger 2.0 解析完成: {len(paths)} 个路径, {len(self.endpoints)} 个操作")
        print(f"[+] 从 Swagger 2.0 中提取到 {len(self.endpoints)} 个 API 端点")
    
    def replace_path_params(self, path: str, parameters: List[Dict[str, Any]]) -> str:
        """替换URL中的路径参数 {id} -> 测试值 - 参考1.0版本"""
        def replace(match):
            name = match.group(1)
            param_type = "string"
            for p in parameters:
                if p.get("in") == "path" and p.get("name") == name:
                    param_type = p.get("schema", {}).get("type", "string")
                    break
            value = self.test_values.get(param_type, "test")
            return quote(str(value))
        return re.sub(r"{([^}]+)}", replace, path)
    
    def prepare_request(self, method: str, path: str, details: Dict[str, Any]) -> Tuple[str, str, Dict[str, str], Dict[str, Any], Optional[str], Optional[Dict]]:
        """准备请求 - 参考1.0版本设计，修复HEAD/OPTIONS/GET传参问题"""
        # 替换路径参数
        full_path = self.replace_path_params(path, details.get("parameters", []))
        url = f"{self.base_url.rstrip('/')}{full_path}"
        
        # 初始化请求头
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 GLS/100.10.9939.100"
        }
        headers.update(self.extra_headers)
        
        # 处理参数
        params = {}
        body = None
        files = None
        parameters = details.get("parameters", [])

        # HEAD/OPTIONS方法：只允许path参数和必需header参数
        if method.upper() in ["HEAD", "OPTIONS"]:
            for param in parameters:
                name = param["name"]
                param_in = param.get("in")
                schema = param.get("schema", {})
                ptype = schema.get("type", "string")
                value = self.test_values.get(ptype, "test")
                if param_in == "path":
                    url = url.replace("{" + name + "}", str(value))
                elif param_in == "header" and param.get("required", False):
                    headers[name] = str(value)
            return method, url, headers, params, body, files

        # 处理查询参数、头部参数、路径参数
        for param in parameters:
            name = param["name"]
            param_in = param.get("in")
            schema = param.get("schema", {})
            ptype = schema.get("type", "string")
            value = self.test_values.get(ptype, "test")
            if param_in == "query":
                params[name] = value
            elif param_in == "header":
                headers[name] = str(value)
            elif param_in == "path":
                url = url.replace("{" + name + "}", str(value))
        
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
        
        # 处理请求体，仅限 POST/PUT/PATCH/DELETE
        # 1. 处理 Swagger 2.0 的 parameters 中的 body 参数
        body_params = [param for param in parameters if param.get("in") == "body"]
        if body_params and method.upper() in ["POST", "PUT", "PATCH", "DELETE"]:
            # 如果有多个body参数，合并成一个对象
            body_data = {}
            for param in body_params:
                param_name = param.get("name", "param")
                param_schema = param.get("schema", {})
                param_value = self.mock_schema(param_schema)
                body_data[param_name] = param_value
            
            # 根据 consumes 设置 Content-Type
            consumes = details.get("consumes", ["application/json"])
            content_type = consumes[0] if consumes else "application/json"
            
            if content_type.endswith("+json") or content_type == "application/json":
                body = json.dumps(body_data)
                headers["Content-Type"] = content_type
            elif content_type == "application/x-www-form-urlencoded":
                body = urlencode(body_data)
                headers["Content-Type"] = content_type
            elif content_type == "multipart/form-data":
                files = {}
                for key, value in body_data.items():
                    if isinstance(value, bytes):
                        files[key] = (f"{key}.bin", value, "application/octet-stream")
                    else:
                        files[key] = (None, str(value))
                headers["Content-Type"] = content_type
            elif content_type == "application/octet-stream":
                body = b"\x00\x01\x02\x03\x04 test binary"
                headers["Content-Type"] = content_type
            elif content_type == "application/pdf":
                body = b"%PDF-1.4\nFake PDF\n%%EOF"
                headers["Content-Type"] = content_type
            elif content_type == "application/zip":
                body = b"PK\x03\x04 test zip"
                headers["Content-Type"] = content_type
            elif content_type == "text/plain" or content_type.startswith("text/"):
                body = "This is a test plain text body"
                headers["Content-Type"] = content_type
            elif content_type == "application/xml" or content_type.endswith("+xml"):
                body = "<?xml version=\"1.0\"?><root><test>data</test></root>"
                headers["Content-Type"] = content_type
        
        # 2. 处理 OpenAPI 3.x 的 requestBody（向后兼容）
        content = details.get("requestBody", {}).get("content", {})
        if content and method.upper() in ["POST", "PUT", "PATCH", "DELETE"] and not body:
            for ctype, cinfo in content.items():
                schema = cinfo.get("schema", {})
                mock_data = self.mock_schema(schema)
                if ctype.endswith("+json") or ctype == "application/json":
                    body = json.dumps(mock_data)
                    headers["Content-Type"] = ctype
                elif ctype == "application/x-www-form-urlencoded":
                    body = urlencode(mock_data)
                    headers["Content-Type"] = ctype
                elif ctype == "multipart/form-data":
                    files = {}
                    for key, value in mock_data.items():
                        if isinstance(value, bytes):
                            files[key] = (f"{key}.bin", value, "application/octet-stream")
                        else:
                            files[key] = (None, str(value))
                    headers["Content-Type"] = ctype
                elif ctype == "application/octet-stream":
                    body = b"\x00\x01\x02\x03\x04 test binary"
                    headers["Content-Type"] = ctype
                elif ctype == "application/pdf":
                    body = b"%PDF-1.4\nFake PDF\n%%EOF"
                    headers["Content-Type"] = ctype
                elif ctype == "application/zip":
                    body = b"PK\x03\x04 test zip"
                    headers["Content-Type"] = ctype
                elif ctype == "text/plain" or ctype.startswith("text/"):
                    body = "This is a test plain text body"
                    headers["Content-Type"] = ctype
                elif ctype == "application/xml" or ctype.endswith("+xml"):
                    body = "<?xml version=\"1.0\"?><root><test>data</test></root>"
                    headers["Content-Type"] = ctype
                break  # 只处理一种 content-type
        return method, url, headers, params, body, files
    
    def _generate_param_value(self, param: Dict[str, Any]) -> Any:
        """生成参数值"""
        param_type = param.get("type", "string")
        param_format = param.get("format")
        enum = param.get("enum")
        
        # 如果有schema，使用schema生成
        if "schema" in param:
            return self.mock_schema(param["schema"])
        
        return self.generate_test_value(param_type, param_format, enum=enum)
    
    def _handle_request_body_by_content_type(self, method: str, body_params: List[Dict], 
                                           form_params: List[Dict], content_type: str, 
                                           headers: Dict[str, str]) -> Tuple[Optional[str], Optional[Dict]]:
        """根据内容类型处理请求体"""
        if "application/json" in content_type:
            # JSON格式
            body_data = {}
            for param in body_params:
                param_name = param.get("name", f"param_{len(body_data)}")
                param_value = self._generate_param_value(param)
                body_data[param_name] = param_value
            
            # 清理数据以确保JSON序列化成功
            body_data = self._sanitize_for_json(body_data)
            body = json.dumps(body_data, ensure_ascii=False)
            headers["Content-Type"] = "application/json"
            return body, None
            
        elif "application/x-www-form-urlencoded" in content_type:
            # 表单格式
            form_data = {}
            for param in form_params:
                param_name = param.get("name", f"param_{len(form_data)}")
                param_value = self._generate_param_value(param)
                form_data[param_name] = param_value
            
            # 清理数据
            form_data = self._sanitize_for_json(form_data)
            body = "&".join([f"{k}={v}" for k, v in form_data.items()])
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            return body, None
            
        elif "multipart/form-data" in content_type:
            # 文件上传格式
            files = {}
            for param in form_params:
                param_name = param.get("name", f"file_{len(files)}")
                if self._is_file_parameter(param):
                    # 创建临时文件
                    import tempfile
                    import os
                    
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
                    temp_file.write(b"test file content")
                    temp_file.close()
                    
                    files[param_name] = (temp_file.name, "text/plain")
                else:
                    param_value = self._generate_param_value(param)
                    files[param_name] = (None, str(param_value))
            
            headers["Content-Type"] = "multipart/form-data"
            return None, files
        
        else:
            # 默认处理
            return None, None
    

    
    def _is_file_parameter(self, param: Dict[str, Any]) -> bool:
        """判断参数是否为文件类型"""
        # 检查参数名
        if param.get("name", "").lower() in ["file", "upload", "attachment", "document"]:
            return True
        
        # 检查描述
        description = param.get("description", "").lower()
        if any(keyword in description for keyword in ["file", "upload", "附件", "文件"]):
            return True
        
        # 检查schema引用
        schema = param.get("schema", {})
        if "$ref" in schema:
            ref = schema["$ref"]
            if "file" in ref.lower():
                return True
        
        # 检查类型
        if param.get("type") == "file":
            return True
        
        return False
    
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
    
    def _sanitize_json_body(self, body: str) -> str:
        """
        清理JSON字符串，确保格式正确
        """
        try:
            # 尝试解析并重新序列化
            parsed = json.loads(body)
            return json.dumps(parsed)
        except (TypeError, ValueError):
            # 如果无法解析，返回一个安全的默认值
            return json.dumps({"error": "Invalid JSON data"})
