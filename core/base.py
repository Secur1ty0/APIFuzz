# -*- coding: utf-8 -*-
# core/base.py

import requests
import time
import threading
import queue
import csv
from typing import Dict, Any, Optional, Union
from colorama import Fore, Style
from lib.util import get_status_color


class BaseFuzzer:
    """API模糊测试基类"""
    
    def __init__(self, spec_data: Dict[str, Any], base_url: str, proxy: Optional[str] = None,
                 threads: int = 1, output_format: str = "csv", delay: float = 0,
                 extra_headers: Optional[Dict[str, str]] = None):
        self.spec_data = spec_data
        self.base_url = base_url
        self.proxy = proxy
        self.threads = threads
        self.output_format = output_format
        self.delay = delay
        self.extra_headers = extra_headers or {}
        
        # 结果存储
        self.results = []
        self.notable_results = []
        self.endpoints = []
        self.queue = queue.Queue()
        self.lock = threading.Lock()
        
        # 进度条
        self.progress = None
        
        # 统一的测试值定义 - 避免重复定义
        self.test_values = {
            # === 基础类型 - 官方文档完全一致 ===
            "string": "test",
            "integer": 1,
            "number": 1.23,
            "boolean": True,
            "array": ["item"],
            "object": {"key": "value"},
            # === 格式类型 - 官方文档完全一致 ===
            "date": "2023-01-01",
            "date-time": "2023-01-01T00:00:00Z",
            "uuid": "123e4567-e89b-12d3-a456-426614174000",
            "email": "test@example.com",
            "password": "test_password",
            "uri": "https://example.com",
            "file": "test_file.txt",
            "int32": 123,
            "int64": 123456789,
            "long": 123456789,
            "double": 123.45,
            "float": 123.45,
            "ipv4": "192.168.1.1",
            "ipv6": "2001:db8::1",
            # === 跨版本兼容的特殊类型 ===
            "byte": "dGVzdA==",  # base64编码的"test"
            "binary": b"test_binary_data",
            "octet-stream": b"test_octet_stream",
            "pdf": b"%PDF-1.4\nFake PDF\n%%EOF",
            "zip": b"PK\x03\x04\x14\x00\x00\x00\x08\x00",
            "plain-text": "test plain text content",
            "xml": "<test>content</test>"
        }
    
    def send_request(self, method: str, url: str, headers: Dict[str, str], 
                    params: Dict[str, Any], body: Optional[str], files: Optional[Dict]) -> Any:
        """发送HTTP请求"""
        try:
            # 设置代理
            proxies = None
            if self.proxy:
                proxies = {
                    'http': self.proxy,
                    'https': self.proxy
                }
            
            # 发送请求
            start_time = time.time()
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=body,
                files=files,
                proxies=proxies,
                timeout=30,
                verify=False
            )
            response._response_time = time.time() - start_time
            
            return response
            
        except requests.exceptions.Timeout:
            # 超时处理 - 参考1.0版本，直接抛出异常
            raise Exception("timeout")
        except Exception as e:
            # 其他错误处理 - 参考1.0版本，直接抛出异常
            raise e
    
    def run_threads(self) -> None:
        """运行工作线程 - 参考1.0版本"""
        threads = []
        for i in range(self.threads):
            t = threading.Thread(target=self.worker)
            t.daemon = True
            t.start()
            threads.append(t)
        
        # 等待所有任务完成
        self.queue.join()
    
    def worker(self) -> None:
        """工作线程（子类实现）"""
        raise NotImplementedError
    
    def _show_all_result(self, method: str, url: str, status: str, error_info: str = None) -> None:
        """显示所有结果"""
        # 使用基类的get_status_color方法，确保风格一致
        status_color = self.get_status_color(status)
        
        # 如果有错误信息且状态为ERROR，在状态后追加错误信息
        if status == "ERROR" and error_info:
            display_status = f"{status}: {error_info}"
        else:
            display_status = status
        
        # 使用tqdm.write确保不干扰进度条
        if self.progress:
            self.progress.write(f"{status_color}[{method:<7}  ] {url:<80} -> {display_status:<20}{Style.RESET_ALL}")
        else:
            print(f"{status_color}[{method:<7}  ] {url:<80} -> {display_status:<20}{Style.RESET_ALL}")
    
    def show_summary(self) -> None:
        """显示测试结果摘要 - 参考1.0版本"""
        from colorama import Fore, Style
        
        print(f"\n{Fore.CYAN}=== Summary ==={Style.RESET_ALL}")
        for r in self.results:
            if r[2] not in ["401", "403", "404"]:  # 跳过这些状态码
                method = r[0]
                url = r[1]
                status = r[2]
                color = self.get_status_color(status)
                print(f"{color}[{method:<7}] {url:<80} -> {status:<4}{Style.RESET_ALL}")
    
    def save_results(self) -> None:
        """保存测试结果 - 参考1.0版本"""
        if not self.results:
            print("[!] 没有结果可保存")
            return
        
        filename = f"fuzzer_results_{int(time.time())}.{self.output_format}"
        
        if self.output_format == "csv":
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Method", "URL", "Status", "Length", "Content-Type",
                    "Request Headers", "Request Body", "Response Headers", "Response Snippet"
                ])
                for row in self.results:
                    writer.writerow(row)
        
        print(f"[+] 测试结果已保存到: {filename}")
    
    def get_status_color(self, status: str) -> str:
        """获取状态码对应的颜色"""
        return get_status_color(status)
    
    def simplify_error_message(self, error_msg: str) -> str:
        """简化错误信息显示"""
        if not error_msg:
            return "Unknown error"
        
        # 处理常见的连接错误
        if "Connection aborted" in error_msg:
            return "Connection aborted"
        elif "Connection reset by peer" in error_msg:
            return "Connection reset"
        elif "timeout" in error_msg.lower():
            return "timeout"
        elif "Connection refused" in error_msg:
            return "Connection refused"
        elif "Name or service not known" in error_msg:
            return "DNS resolution failed"
        elif "No route to host" in error_msg:
            return "No route to host"
        elif "Network is unreachable" in error_msg:
            return "Network unreachable"
        
        # 如果错误信息太长，截取前50个字符
        if len(error_msg) > 50:
            return error_msg[:47] + "..."
        
        return error_msg
    
    def _is_notable_status(self, status: str) -> bool:
        """判断是否为值得注意的状态码"""
        if not status or not status.isdigit():
            return True  # 非数字状态码（如ERROR）值得注意
        
        status_code = int(status)
        return status_code >= 400  # 4xx和5xx状态码值得注意
    
    def extract_endpoints(self) -> None:
        """提取端点（子类实现）"""
        raise NotImplementedError
    
    def prepare_request(self, method: str, path: str, details: Dict[str, Any]) -> tuple:
        """准备请求（子类实现）"""
        raise NotImplementedError
    
    def fuzz(self) -> None:
        """开始模糊测试（子类实现）"""
        raise NotImplementedError 