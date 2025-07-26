# main.py

import argparse
import json
import re
import threading
import requests
import csv
import time
from urllib.parse import urljoin, unquote, urlencode, quote
from queue import Queue
from datetime import datetime
from tqdm import tqdm
import urllib3
from colorama import init, Fore, Style
from util import resolve_urls, load_openapi_spec, get_status_color, parse_headers_arg

# 初始化 colorama 自动重置颜色样式
init(autoreset=True)
# 忽略 HTTPS 证书警告
urllib3.disable_warnings()

# 启动 ASCII 图标 Banner
BANNER = r"""
────────────────────────────────────────────────────────────────────────────────────────────
  █████████                           ███████████           
 ███░░░░░███                         ░░███░░░░░░█           
░███    ░░░  █████ ███ █████  ███████ ░███   █ ░   █████████
░░█████████ ░░███ ░███░░███  ███░░███ ░███████    ░█░░░░███ 
 ░░░░░░░░███ ░███ ░███ ░███ ░███ ░███ ░███░░░█    ░   ███░  
 ███    ░███ ░░███████████  ░███ ░███ ░███  ░       ███░   █
░░█████████   ░░████░████   ░░███████ █████        █████████
 ░░░░░░░░░     ░░░░ ░░░░     ░░░░░███░░░░░        ░░░░░░░░░ 
                             ███ ░███                       
                            ░░██████                        
                             ░░░░░░                         -- Swagger API Auto Fuzzer v1.0
────────────────────────────────────────────────────────────────────────────────────────────
"""

# 支持的请求方法列表
SUPPORTED_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]

# 各种类型的默认测试值
TEST_VALUES = {
    "string": "test",
    "integer": 1,
    "number": 1.23,
    "boolean": True,
    "array": ["item"],
    "object": {"key": "value"},
    "date": "2023-01-01",
    "date-time": "2023-01-01T00:00:00Z",
    "uuid": "123e4567-e89b-12d3-a456-426614174000"
}


# Swagger 模糊测试核心类
class SwaggerFuzzer:
    def __init__(self, openapi_doc, base_url, proxy=None, threads=1, output_format="csv", delay=0, extra_headers=None):
        self.openapi_doc = openapi_doc
        self.base_url = base_url.rstrip("/")
        self.proxy = {"http": proxy, "https": proxy} if proxy else None
        self.threads = threads
        self.output_format = output_format
        self.delay = delay
        self.queue = Queue()
        self.results = []
        self.extra_headers = extra_headers or {}
        self.progress = None

    # 模糊测试主函数
    def fuzz(self):
        self.extract_endpoints()   # 提取所有接口定义
        self.progress = tqdm(total=self.queue.qsize(), desc="Fuzzing")
        self.run_threads()         # 多线程运行测试
        self.save_results()        # 保存结果
        self.show_summary()        # 控制台打印总结

    # 从 OpenAPI 文档提取所有接口 path+method+详情 加入队列
    def extract_endpoints(self):
        paths = self.openapi_doc.get("paths", {})
        for raw_path, path_item in paths.items():
            path = unquote(raw_path)
            for method, details in path_item.items():
                if method.upper() in SUPPORTED_METHODS:
                    self.queue.put((method.upper(), path, details))

    # 启动多个线程并执行 worker
    def run_threads(self):
        threads = []
        for _ in range(self.threads):
            t = threading.Thread(target=self.worker)
            t.daemon = True
            t.start()
            threads.append(t)
        self.queue.join()

    # 替换 URL 中的路径参数 {id} -> 测试值
    def replace_path_params(self, path, parameters):
        def replace(match):
            name = match.group(1)
            param_type = "string"
            for p in parameters:
                if p.get("in") == "path" and p.get("name") == name:
                    param_type = p.get("schema", {}).get("type", "string")
                    break
            value = TEST_VALUES.get(param_type, "test")
            return quote(str(value))
        return re.sub(r"{([^}]+)}", replace, path)

    # 构造单个请求的 URL、headers、参数、body、files
    def prepare_request(self, method, path, details):
        full_path = self.replace_path_params(path, details.get("parameters", []))
        url = urljoin(self.base_url + "/", full_path.lstrip("/"))
        params = {}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 GLS/100.10.9939.100",
            **self.extra_headers
        }
        body = None
        files = None

        parameters = details.get("parameters", [])
        for param in parameters:
            name = param["name"]
            param_in = param.get("in")
            schema = param.get("schema", {})
            ptype = schema.get("type", "string")
            value = TEST_VALUES.get(ptype, "test")

            if param_in == "query":
                params[name] = value
            elif param_in == "header":
                headers[name] = str(value)
            elif param_in == "path":
                url = url.replace("{" + name + "}", str(value))

        content = details.get("requestBody", {}).get("content", {})
        if content:
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
        else:
            # 没有定义 requestBody，默认发一个 application/json 请求
            headers["Content-Type"] = "application/json"
            body = json.dumps({"default": "test"})

        return method, url, headers, params, body, files

    def resolve_ref(self, ref):
        """解析本地 $ref 引用"""
        if not ref.startswith("#/"):
            raise ValueError(f"Unsupported $ref: {ref}")
        parts = ref.lstrip("#/").split("/")
        result = self.openapi_doc
        for part in parts:
            result = result.get(part)
            if result is None:
                raise KeyError(f"Invalid $ref: {ref}")
        return result
    # 根据 schema 构造模拟数据
    def mock_schema(self, schema, components=None, visited_refs=None):
        components = components or self.openapi_doc.get("components", {}).get("schemas", {})
        visited_refs = visited_refs or set()

        # 处理 $ref 引用
        if "$ref" in schema:
            ref = schema["$ref"]
            if ref in visited_refs:
                return "<circular-ref>"  # 防止死循环

            visited_refs.add(ref)
            if ref.startswith("#/components/schemas/"):
                name = ref.split("/")[-1]
                ref_schema = components.get(name)
                if ref_schema:
                    return self.mock_schema(ref_schema, components, visited_refs)

        if not schema:
            return {}

        schema_type = schema.get("type")

        if schema_type == "object":
            result = {}
            for prop, prop_schema in schema.get("properties", {}).items():
                result[prop] = self.mock_schema(prop_schema, components, visited_refs)
            return result

        elif schema_type == "array":
            item_schema = schema.get("items", {})
            return [self.mock_schema(item_schema, components, visited_refs)]

        elif schema.get("format") == "binary":
            return b"fake-binary-data"

        return TEST_VALUES.get(schema_type, "test")

    # 工作线程函数：提取请求，发送，记录响应
    def worker(self):
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

                    status_color = get_status_color(status)
                    tqdm.write(f"{status_color}[{method:<6}] {url:<80} -> {status:<4} {Style.RESET_ALL}")
                except Exception as err:
                    tqdm.write(f"{Fore.LIGHTBLACK_EX}[{method:<6}] {url} -> ERROR: {str(err)}{Style.RESET_ALL}")
                self.progress.update(1)
            finally:
                self.queue.task_done()

    # 发送 HTTP 请求
    def send_request(self, method, url, headers, params, body, files):
        func = getattr(requests, method.lower())
        is_json = headers.get("Content-Type") == "application/json"
        return func(
            url,
            headers=headers,
            params=params,
            data=None if is_json or files else body,
            json=json.loads(body) if is_json else None,
            files=files,
            verify=False,
            proxies=self.proxy,
            timeout=10
        )

    # 保存测试结果到 CSV 文件
    def save_results(self):
        filename = f"swagger_fuzz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{self.output_format}"
        with open(filename, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Method", "URL", "Status", "Length", "Content-Type",
                "Request Headers", "Request Body", "Response Headers", "Response Snippet"
            ])
            for row in self.results:
                writer.writerow(row)
        print(f"\n[+] Report saved to {filename}")

    # 控制台展示请求结果总结
    def show_summary(self):
        print(f"\n{Fore.CYAN}=== Summary ==={Style.RESET_ALL}")
        for r in self.results:
            status = r[2]
            if status.startswith("401") or status.startswith("403") or status.startswith("404"):
                pass
            else:
                print(f"{get_status_color(status)}[{r[0]}] {r[1]} -> {status}{Style.RESET_ALL}")


# 命令行参数解析及主程序入口
def main():
    print(BANNER)
    parser = argparse.ArgumentParser(description="Swagger/OpenAPI API Auto Fuzzer")
    parser.add_argument("-f", "--file", help="OpenAPI 本地文件路径或相对路径，如 /swagger/v1/swagger.json")
    parser.add_argument("-u", "--url", help="Base URL 或完整的 OpenAPI JSON 地址", required=True)
    parser.add_argument("-p", "--proxy", help="设置代理，例如 http://127.0.0.1:8080")
    parser.add_argument("-t", "--threads", help="线程数", type=int, default=1)
    parser.add_argument("-o", "--output", help="输出格式", choices=["csv"], default="csv")
    parser.add_argument("-d", "--delay", help="请求间隔（秒）", type=float, default=0)
    parser.add_argument("--header", action="append", help='自定义请求头，例如 --header="Authorization: Bearer xxx"')

    args = parser.parse_args()

    try:
        swagger_url, base_api = resolve_urls(args.url, args.file)
        spec = load_openapi_spec(args.file, swagger_url)
    except Exception as e:
        print(f"{Fore.RED}[!] 加载 OpenAPI 规范失败: {e}{Style.RESET_ALL}")
        return

    fuzzer = SwaggerFuzzer(
        openapi_doc=spec,
        base_url=base_api,
        proxy=args.proxy,
        threads=args.threads,
        output_format=args.output,
        delay=args.delay,
        extra_headers=parse_headers_arg(args.header)
    )
    fuzzer.fuzz()


if __name__ == '__main__':
    main()
