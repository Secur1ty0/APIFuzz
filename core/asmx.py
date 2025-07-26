# -*- coding: utf-8 -*-
# core/asmx.py

import re
import requests
import random
import time
import csv
import queue
from typing import Dict, Any, List, Tuple, Optional
from .base import BaseFuzzer
from tqdm import tqdm
import threading
import os


class ASMXFuzzer(BaseFuzzer):
    """ASP.NET .asmx 服务模糊测试器"""
    
    def __init__(self, spec_data: Dict[str, Any], base_url: str, proxy: Optional[str] = None,
                 threads: int = 1, output_format: str = "csv", delay: float = 0,
                 extra_headers: Optional[Dict[str, str]] = None, type_definition: Optional[str] = None):
        super().__init__(spec_data, base_url, proxy, threads, output_format, delay, extra_headers)
        
        # ASMX 特定数据
        self.asmx_data = spec_data
        self.operations = []
        self.service_name = ""
        self.service_url = base_url
        self.operation_details = {}  # 存储每个操作的详情页面内容
        
        # 测试值映射
        self.asmx_test_values = {
            "string": ["test", "admin", "user", "guest", "null", "", "a" * 1000],
            "int": [1, 0, -1, 999999, -999999],
            "boolean": [True, False],
            "double": [1.0, 0.0, -1.0, 3.14159, 1e10, -1e10],
            "date": ["2023-01-01", "2023-12-31", "1970-01-01", "2099-12-31"],
            "dateTime": ["2023-01-01T00:00:00Z", "2023-12-31T23:59:59Z"],
            
            # 特殊值
            "null": None,
            "empty": "",
            "long_string": "a" * 10000,
            "special_chars": "!@#$%^&*()_+-=[]{}|;':\",./<>?",
            "unicode": "test_unicode",
        }
        
        # 进度条相关
        self.progress = None
        self.notable_results = []
        
        # 解析 ASMX 服务
        # self.parse_asmx() # 移除此行，只保留 fuzz() 里的解析
    
    def parse_asmx(self) -> None:
        """解析 ASP.NET .asmx 服务页面"""
        try:
            # 如果 spec_data 是字符串，直接解析
            if isinstance(self.asmx_data, str):
                content = self.asmx_data
            else:
                # 从 URL 获取内容
                response = requests.get(self.service_url, verify=False, timeout=10)
                response.raise_for_status()
                content = response.text
            
            # 提取服务名称
            service_match = re.search(r'<h1[^>]*>([^<]+)</h1>', content, re.IGNORECASE)
            if service_match:
                self.service_name = service_match.group(1).strip()
            else:
                # 从 URL 提取服务名称
                self.service_name = self.service_url.split('/')[-1].replace('.asmx', '')
            
            # 提取操作列表
            operations = []
            
            # 方法1：从 h2 标签中提取操作名称（标准 ASMX 格式）
            h2_matches = re.findall(r'<h2[^>]*>([^<]+)</h2>', content, re.IGNORECASE)
            for op_name in h2_matches:
                op_name = op_name.strip()
                if op_name and not op_name.lower() in ['test', 'soap 1.1', 'soap 1.2', 'http get', 'http post']:
                    operations.append(op_name)
            
            # 方法2：从 * 列表项中提取（主页面）
            if not operations:
                operation_matches = re.findall(r'\*\s*([^\n\r]+)', content, re.IGNORECASE)
                for op_name in operation_matches:
                    op_name = op_name.strip()
                    if op_name and not op_name.lower() in ['service description', 'wsdl', '服务说明', 'operation', 'description']:
                        operations.append(op_name)
            
            # 方法3：从列表项中提取（主页面）
            if not operations:
                operation_matches = re.findall(r'<li[^>]*>\s*<a[^>]*>([^<]+)</a>', content, re.IGNORECASE)
                for op_name in operation_matches:
                    if op_name.strip() and not op_name.strip().lower() in ['service description', 'wsdl', '服务说明']:
                        operations.append(op_name.strip())
            
            # 方法4：从表格中提取
            if not operations:
                table_matches = re.findall(r'<td[^>]*>([^<]+)</td>', content, re.IGNORECASE)
                for cell in table_matches:
                    cell_content = cell.strip()
                    if cell_content and not cell_content.lower() in ['operation', 'description', 'service description', 'wsdl', '操作', '描述', '服务说明']:
                        operations.append(cell_content)
            
            # 方法5：从URL参数中提取操作名
            if not operations:
                import urllib.parse
                try:
                    parsed_url = urllib.parse.urlparse(self.service_url)
                    query_params = urllib.parse.parse_qs(parsed_url.query)
                    if 'op' in query_params:
                        op_name = query_params['op'][0]
                        operations.append(op_name)
                except:
                    pass
            
            # 去重并过滤
            self.operations = list(set([op for op in operations if op and len(op) > 1]))
            
            # 提取并请求每个操作的详情页面
            self._fetch_operation_details(content)
            
            print(f"[+] ASMX 解析完成: 服务 '{self.service_name}', {len(self.operations)} 个操作")
            if self.operations:
                print(f"[+] 发现的操作: {', '.join(self.operations)}")
                
        except Exception as e:
            print(f"[!] 解析 ASMX 服务失败: {e}")
            import traceback
            traceback.print_exc()
    
    def extract_endpoints(self) -> None:
        """提取 ASMX 端点"""
        if not self.operations:
            print("[!] 没有找到可测试的操作")
            return
        
        for operation in self.operations:
            endpoint_info = {
                'operation': operation,
                'url': self.service_url,
                'method': 'POST',
                'content_type': 'text/xml; charset=utf-8'
            }
            self.endpoints.append(('POST', f"/{operation}", endpoint_info))
        
        print(f"[+] 从 ASMX 服务中提取到 {len(self.endpoints)} 个操作")
    
    def prepare_request(self, method: str, path: str, details: Dict[str, Any], namespace_override=None) -> Tuple[str, str, Dict[str, str], Dict[str, Any], Optional[str], Optional[Dict], bool, str, str]:
        """准备 ASMX 请求，支持 namespace 覆盖"""
        operation = details['operation']
        url = details['url']
        # 生成 SOAP 消息
        soap_body, used_details = self._generate_soap_message(operation, namespace_override)
        # 从输入的 URL 提取 Host
        host = self._extract_host_from_url(url)
        # 选择 namespace
        namespace = namespace_override if namespace_override else self._extract_namespace_from_page()
        # SOAPAction
        soap_action = f'"{namespace}{operation}"'
        headers = {
            'Content-Type': details['content_type'],
            'SOAPAction': soap_action,
            'Host': host,
            'User-Agent': 'APIFuzz/2.0'
        }
        return method, url, headers, {}, soap_body, None, used_details, namespace, soap_action

    def _generate_soap_message(self, operation: str, namespace_override=None) -> Tuple[str, bool]:
        """生成 ASMX SOAP 消息，支持 namespace 覆盖"""
        safe_operation = self._sanitize_operation_name(operation)
        params, used_details = self._extract_params_from_page(operation)
        if not params:
            params = self._generate_random_params(operation)
            used_details = False
        if not params:
            params = "      <param1>test</param1>"
            used_details = False
        namespace = namespace_override if namespace_override else self._extract_namespace_from_page()
        soap_envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
               xmlns:xsd="http://www.w3.org/2001/XMLSchema" 
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <{safe_operation} xmlns=\"{namespace}\">\n{params}\n    </{safe_operation}>
  </soap:Body>
</soap:Envelope>"""
        return soap_envelope, used_details

    def _sanitize_operation_name(self, operation: str) -> str:
        """清理操作名称，确保是 ASCII 安全的"""
        try:
            # 尝试编码为 ASCII
            operation.encode('ascii')
            return operation
        except UnicodeEncodeError:
            # 如果包含非 ASCII 字符，使用安全的替代名称
            if '参数' in operation:
                return 'parameters'
            elif 'username' in operation.lower():
                return 'username'
            elif 'download' in operation.lower():
                return 'download'
            elif 'create' in operation.lower():
                return 'create'
            elif 'user' in operation.lower():
                return 'user'
            else:
                return 'operation'
    
    def _sanitize_param_value(self, value: str) -> str:
        """清理参数值，确保是 ASCII 安全的"""
        try:
            # 尝试编码为 ASCII
            value.encode('ascii')
            return value
        except UnicodeEncodeError:
            # 如果包含非 ASCII 字符，使用安全的替代值
            return "test_value"
    
    def _extract_params_from_page(self, operation: str) -> Tuple[str, bool]:
        """从页面内容中提取实际的参数信息，返回(参数内容, 是否使用了详情页面)"""
        try:
            # 优先使用操作详情页面内容
            if operation in self.operation_details:
                content = self.operation_details[operation]
                used_details = True
            else:
                # 如果 spec_data 是字符串，直接使用
                content = self.asmx_data if isinstance(self.asmx_data, str) else ""
                used_details = False
            
            # 方法1：从 SOAP 示例中提取参数
            operation_pattern = rf'<{operation}[^>]*xmlns="[^"]*">\s*([^<]*(?:<[^>]+>[^<]*</[^>]+>[^<]*)*)\s*</{operation}>'
            match = re.search(operation_pattern, content, re.IGNORECASE | re.DOTALL)
            
            if match:
                params_content = match.group(1)
                # 提取参数名和类型
                param_matches = re.findall(r'<([^>]+)>([^<]*)</\1>', params_content)
                if param_matches:
                    params = []
                    for param_name, param_type in param_matches:
                        if param_name and param_type:
                            # 根据参数类型生成测试值
                            test_value = self._get_test_value_by_type(param_type.strip())
                            # 确保参数值是 ASCII 安全的
                            safe_value = self._sanitize_param_value(str(test_value))
                            params.append(f"      <{param_name}>{safe_value}</{param_name}>")
                    return '\n'.join(params), used_details
            
            # 方法2：从表单字段中提取参数
            form_matches = re.findall(r'<input[^>]*name=["\']([^"\']+)["\'][^>]*>', content, re.IGNORECASE)
            if form_matches:
                params = []
                for param_name in form_matches:
                    if param_name and param_name.lower() not in ['submit', 'button']:
                        test_value = self._get_random_test_value("string")
                        # 确保参数值是 ASCII 安全的
                        safe_value = self._sanitize_param_value(str(test_value))
                        params.append(f"      <{param_name}>{safe_value}</{param_name}>")
                return '\n'.join(params), used_details
            
            # 方法3：从参数描述中提取（标准 ASMX 格式）
            # 查找类似 "string username:用户ID" 的模式
            param_desc_pattern = r'<font[^>]*color="#FF00FF"[^>]*>([^<]+)</font>\s+([^:]+):([^<]*)'
            param_desc_matches = re.findall(param_desc_pattern, content, re.IGNORECASE)
            if param_desc_matches:
                params = []
                for param_type, param_name, param_desc in param_desc_matches:
                    param_name = param_name.strip()
                    if param_name and param_name.lower() not in ['返回值']:
                        test_value = self._get_test_value_by_type(param_type.strip())
                        # 确保参数值是 ASCII 安全的
                        safe_value = self._sanitize_param_value(str(test_value))
                        params.append(f"      <{param_name}>{safe_value}</{param_name}>")
                return '\n'.join(params), used_details
            
            return "", used_details
        except Exception:
            return "", False
    
    def _extract_namespace_from_page(self) -> str:
        """从页面内容中提取命名空间"""
        try:
            # 优先使用操作详情页面内容（如果有的话）
            content = ""
            if self.operation_details:
                # 使用第一个操作的详情页面
                first_operation = list(self.operation_details.keys())[0]
                content = self.operation_details[first_operation]
            elif isinstance(self.asmx_data, str):
                content = self.asmx_data
            
            # 方法1：从 SOAP 示例中查找命名空间
            namespace_match = re.search(r'xmlns="([^"]+)"', content)
            if namespace_match:
                return namespace_match.group(1)
            
            # 方法2：从页面文本中查找命名空间信息
            tempuri_match = re.search(r'http://tempuri\.org/', content)
            if tempuri_match:
                return "http://tempuri.org/"
            
            # 方法3：查找其他命名空间模式
            namespace_patterns = [
                r'Namespace="([^"]+)"',
                r'命名空间[：:]\s*([^\s\n]+)',
                r'namespace[：:]\s*([^\s\n]+)'
            ]
            
            for pattern in namespace_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    return match.group(1)
            
            # 默认命名空间
            return "http://tempuri.org/"
        except Exception:
            return "http://tempuri.org/"
    
    def _get_test_value_by_type(self, param_type: str) -> str:
        """根据参数类型生成测试值"""
        param_type = param_type.lower()
        if param_type in ['string', 'str']:
            return self._get_random_test_value("string")
        elif param_type in ['int', 'integer']:
            return str(self._get_random_test_value("int"))
        elif param_type in ['boolean', 'bool']:
            return str(self._get_random_test_value("boolean")).lower()
        elif param_type in ['double', 'float']:
            return str(self._get_random_test_value("double"))
        else:
            return self._get_random_test_value("string")
    
    def _get_random_test_value(self, value_type: str) -> Any:
        """获取随机测试值"""
        if value_type in self.asmx_test_values:
            values = self.asmx_test_values[value_type]
            if isinstance(values, list):
                value = random.choice(values)
            else:
                value = values
        else:
            value = "test"
        
        # 确保值是 ASCII 安全的
        try:
            if isinstance(value, str):
                value.encode('ascii')
            return value
        except UnicodeEncodeError:
            # 如果包含非 ASCII 字符，使用安全的替代值
            if value_type == "string":
                return "test_string"
            elif value_type == "int":
                return 123
            elif value_type == "boolean":
                return True
            elif value_type == "double":
                return 123.45
            else:
                return "test"
    
    def _extract_host_from_url(self, url: str) -> str:
        """从 URL 中提取 Host"""
        try:
            import urllib.parse
            parsed_url = urllib.parse.urlparse(url)
            host = parsed_url.netloc
            
            # 如果包含端口号，保留端口号
            if ':' in host:
                return host
            else:
                # 根据协议添加默认端口
                if parsed_url.scheme == 'https':
                    return f"{host}:443"
                else:
                    return f"{host}:80"
        except Exception:
            # 如果解析失败，尝试简单提取
            if '://' in url:
                host_part = url.split('://')[1].split('/')[0]
                return host_part
            else:
                return url
    
    def _get_fallback_namespace(self):
        from urllib.parse import urlparse
        parsed = urlparse(self.service_url)
        scheme = parsed.scheme or "http"
        host = parsed.hostname
        # 提取服务名（去掉路径和扩展名）
        path = parsed.path
        service = os.path.splitext(os.path.basename(path))[0] or "Service"
        return f"{scheme}://{host}/{service}/"
    
    def _generate_random_params(self, operation: str) -> str:
        """为操作生成随机参数"""
        # 根据操作名称智能推断参数
        params = []
        
        # 常见参数模式
        param_patterns = {
            'debug': ['debug', 'level', 'message'],
            'download': ['filename', 'path', 'url'],
            'execute': ['command', 'sql', 'script'],
            'get': ['id', 'name', 'key', 'path'],
            'user': ['username', 'password', 'email'],
            'file': ['filename', 'path', 'content'],
            'log': ['message', 'level', 'timestamp']
        }
        
        # 根据操作名称匹配参数模式
        for pattern, param_names in param_patterns.items():
            if pattern.lower() in operation.lower():
                for param_name in param_names:
                    param_value = self._get_random_test_value("string")
                    params.append(f"      <{param_name}>{param_value}</{param_name}>")
                break
        
        # 如果没有匹配的模式，使用通用参数
        if not params:
            generic_params = ['param1', 'param2', 'value', 'data']
            for param_name in generic_params[:2]:  # 最多2个参数
                param_value = self._get_random_test_value("string")
                params.append(f"      <{param_name}>{param_value}</{param_name}>")
        
        return '\n'.join(params)
    
    def _get_random_test_value(self, value_type: str) -> Any:
        """获取随机测试值"""
        if value_type in self.asmx_test_values:
            values = self.asmx_test_values[value_type]
            if isinstance(values, list):
                return random.choice(values)
            else:
                return values
        return "test"
    
    def mock_schema(self, schema: Dict[str, Any], components: Optional[Dict] = None, visited_refs: Optional[set] = None) -> Any:
        """模拟 ASMX 模式（占位符）"""
        return "test"
    
    def fuzz(self) -> None:
        """开始模糊测试"""
        print(f"[+] 开始 ASMX 模糊测试，线程数: {self.threads}")
        
        # 解析ASMX服务
        self.parse_asmx()
        
        # 提取端点
        self.extract_endpoints()
        
        if not self.endpoints:
            print("[!] 没有找到可测试的 API 端点")
            return
        
        # 将端点添加到队列
        for endpoint in self.endpoints:
            self.queue.put(endpoint)
        
        # 初始化进度条
        self.progress = tqdm(total=len(self.endpoints), desc="Fuzzing", ncols=80, 
                           bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]')
        
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
        """工作线程，支持双 namespace/Action 请求"""
        import queue
        while True:
            try:
                endpoint = self.queue.get(timeout=1)
            except queue.Empty:
                break
            method, path, details = endpoint
            try:
                # 1. 页面 namespace
                method1, url1, headers1, params1, body1, files1, used_details1, ns1, action1 = self.prepare_request(method, path, details)
                # 2. fallback namespace
                fallback_ns = self._get_fallback_namespace()
                need_fallback = ns1.rstrip('/') != fallback_ns.rstrip('/')
                # 先请求页面 namespace
                response1 = self.send_request(method1, url1, headers1, params1, body1, files1)
                self._show_all_result(method1, url1, str(getattr(response1, 'status_code', getattr(response1, '_error', 'ERR'))), None, getattr(response1, '_response_time', 0), len(getattr(response1, 'content', b'')), used_details1, details.get('operation', '') + (f" [ns:{ns1}]" if need_fallback else ""))
                # 如果 namespace/action 不一致，再请求 fallback
                if need_fallback:
                    method2, url2, headers2, params2, body2, files2, used_details2, ns2, action2 = self.prepare_request(method, path, details, namespace_override=fallback_ns)
                    response2 = self.send_request(method2, url2, headers2, params2, body2, files2)
                    self._show_all_result(method2, url2, str(getattr(response2, 'status_code', getattr(response2, '_error', 'ERR'))), None, getattr(response2, '_response_time', 0), len(getattr(response2, 'content', b'')), used_details2, details.get('operation', '') + f" [ns:{ns2}]")
                # 进度条更新：每个操作只更新一次，不管发送了几个请求
                if self.progress:
                    self.progress.update(1)
                if self.delay > 0:
                    time.sleep(self.delay)
            except Exception as e:
                error_msg = str(e)
                error_url = details.get('url', 'unknown')
                self._show_all_result(method, error_url, error_msg, None, 0, 0, False, details.get('operation', ''))
                if self.progress:
                    self.progress.update(1)
            finally:
                self.queue.task_done()
    
    def _fetch_operation_details(self, content: str) -> None:
        """提取并请求每个操作的详情页面"""
        try:
            import urllib.parse
            from colorama import Fore, Style
            
            # 提取所有 href 链接
            href_matches = re.findall(r'<a\s+href=["\']([^"\']+)["\']', content, re.IGNORECASE)
            
            print(f"[+] 发现 {len(href_matches)} 个链接")
            
            # 统计操作链接数量
            op_links = [href for href in href_matches if "?op=" in href]
            print(f"[+] 其中 {len(op_links)} 个是操作详情链接")
            
            # 存储操作详情页面内容
            self.operation_details = {}
            
            for href in href_matches:
                if "?op=" in href:
                    # 构建完整 URL
                    full_url = urllib.parse.urljoin(self.service_url, href)
                    
                    try:
                        # 从 URL 中提取操作名
                        parsed_url = urllib.parse.urlparse(full_url)
                        query_params = urllib.parse.parse_qs(parsed_url.query)
                        operation_name = query_params.get('op', ['unknown'])[0]
                        
                        # 发送请求
                        resp = requests.get(full_url, timeout=10, verify=False)
                        resp.raise_for_status()
                        
                        # 保存详情页面内容
                        self.operation_details[operation_name] = resp.text
                        
                        # 显示成功结果（绿色）
                        print(f"[Fetch  ] {full_url:<60} -> {Fore.GREEN}success{Style.RESET_ALL}")
                        
                    except Exception as e:
                        # 显示失败结果（浅红色）
                        print(f"[Fetch  ] {full_url:<60} -> {Fore.LIGHTRED_EX}failed{Style.RESET_ALL}")
                        
        except Exception as e:
            print(f"[!] 获取操作详情失败: {e}")
    
    def _show_all_result(self, method: str, url: str, status: str, error_info: str = None, response_time: float = 0, content_length: int = 0, used_details: bool = False, operation: str = '') -> None:
        """显示测试结果"""
        color = self.get_status_color(status)
        # 构建结果行 - 使用固定宽度格式化
        if error_info:
            simplified_error = self.simplify_error_message(error_info)
            result_line = f"[{method:<7}] {url:<80} -> {color}{status}{color} -> {simplified_error}"
        else:
            result_line = f"[{method:<7}] {url:<80} -> {color}{status}{color}"
        # 添加操作名称
        if operation:
            result_line += f" [{operation}]"
        # 删除参数提取信息输出
        # if used_details:
        #     result_line += " [详情页面参数]"
        if self.progress:
            self.progress.write(result_line)
        else:
            print(result_line)
        with self.lock:
            self.results.append({
                "method": method,
                "url": url,
                "status": status,
                "response_time": response_time,
                "content_length": content_length,
                "error": error_info if error_info else "",
                "operation": operation
            })
    
    def save_results(self) -> None:
        """保存测试结果"""
        if not self.results:
            print("[!] 没有结果可保存")
            return
        
        filename = f"asmx_fuzzer_results_{int(time.time())}.{self.output_format}"
        
        if self.output_format == "csv":
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=["method", "url", "status", "response_time", "content_length", "error", "operation"])
                writer.writeheader()
                writer.writerows(self.results)
        
        print(f"[+] ASMX 测试结果已保存到: {filename}")
    
    def show_summary(self) -> None:
        """显示测试结果摘要 - ASMX版本，包含操作名称"""
        from colorama import Fore, Style
        
        print(f"\n{Fore.CYAN}=== Summary ==={Style.RESET_ALL}")
        
        # 按状态码分类显示所有结果
        status_groups = {}
        for result in self.results:
            status = result["status"]
            status_prefix = status[0] if status and status.isdigit() else "OTHER"
            
            if status_prefix not in status_groups:
                status_groups[status_prefix] = []
            status_groups[status_prefix].append(result)
        
        # 优先显示成功和错误的结果
        for prefix in ["2", "5", "3", "4", "OTHER"]:
            if prefix in status_groups:
                for result in status_groups[prefix]:
                    method = result["method"]
                    url = result["url"]
                    status = result["status"]
                    operation = result.get("operation", "")
                    color = self.get_status_color(status)
                    
                    # 添加操作名称到摘要 - 使用固定宽度格式化
                    if operation:
                        print(f"{color}[{method:<7}] {url:<80} -> {status:<4}{Style.RESET_ALL} [{operation}]")
                    else:
                        print(f"{color}[{method:<7}] {url:<80} -> {status:<4}{Style.RESET_ALL}")


 