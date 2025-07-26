# -*- coding: utf-8 -*-
# APIFuzz.py

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
from lib.util import resolve_urls, load_openapi_spec, get_status_color, parse_headers_arg
from core import create_fuzzer, detect_version, get_version_info

# 初始化 colorama 自动重置颜色样式
init(autoreset=True)
# 忽略 HTTPS 证书警告
urllib3.disable_warnings()

# 启动 ASCII 图标 Banner
BANNER = r"""
───────────────────────────────────────────────────────────────────────

        
         █████╗ ██████╗ ██╗███████╗██╗   ██╗███████╗███████╗
        ██╔══██╗██╔══██╗██║██╔════╝██║   ██║╚══███╔╝╚══███╔╝
        ███████║██████╔╝██║█████╗  ██║   ██║  ███╔╝   ███╔╝ 
        ██╔══██║██╔═══╝ ██║██╔══╝  ██║   ██║ ███╔╝   ███╔╝  
        ██║  ██║██║     ██║██║     ╚██████╔╝███████╗███████╗
        ╚═╝  ╚═╝╚═╝     ╚═╝╚═╝      ╚═════╝ ╚══════╝╚══════╝
                                                    
                                                                        
                                                      -- APIFuzz v2.0                      
───────────────────────────────────────────────────────────────────────
"""

# 命令行参数解析及主程序入口
def main():
    print(BANNER)
    parser = argparse.ArgumentParser(description="APIFuzz - Universal API Security Testing Tool")
    parser.add_argument("-f", "--file", help="API文档本地文件路径，支持JSON/XML格式")
    parser.add_argument("-u", "--url", help="Base URL 或完整的 API 文档地址", required=True)
    parser.add_argument("-p", "--proxy", nargs='?', const="http://127.0.0.1:8080", help="设置代理，不加参数使用默认代理 http://127.0.0.1:8080，加参数使用指定代理")
    parser.add_argument("-t", "--threads", help="线程数", type=int, default=1)
    parser.add_argument("-o", "--output", help="输出格式", choices=["csv"], default="csv")
    parser.add_argument("-d", "--delay", help="请求间隔（秒）", type=float, default=0.1)
    parser.add_argument("--header", action="append", help='自定义请求头，例如 --header="Authorization: Bearer xxx"')
    parser.add_argument("--type", help="自定义类型定义文件路径或URL（用于增强WSDL测试），支持XML格式")

    args = parser.parse_args()

    try:
        # 加载API文档
        swagger_url, base_api = resolve_urls(args.url, args.file)
        spec = load_openapi_spec(args.file, swagger_url)
        
        # 检测版本并显示信息
        version = detect_version(spec)
        version_info = get_version_info(spec)
        
        print(f"{Fore.CYAN}[+] 检测到API文档版本: {version}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}[+] API标题: {version_info.get('title', 'Unknown')}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}[+] API版本: {version_info.get('version_info', 'Unknown')}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}[+] 规范版本: {version_info.get('version', 'Unknown')}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}[+] 基础URL: {base_api}{Style.RESET_ALL}")
        print()
        
        # 使用工厂函数创建对应的Fuzzer实例
        fuzzer = create_fuzzer(
            spec=spec,
            base_url=base_api,
            proxy=args.proxy,
            threads=args.threads,
            output_format=args.output,
            delay=args.delay,
            extra_headers=parse_headers_arg(args.header),
            type_definition=args.type
        )
        
        # 开始模糊测试
        fuzzer.fuzz()
        
    except ValueError as e:
        raise e
        print(f"{Fore.RED}[!] 版本检测失败: {e}{Style.RESET_ALL}")
        return
    except Exception as e:
        raise e
        print(f"{Fore.RED}[!] 加载 API 规范失败: {e}{Style.RESET_ALL}")
        return


if __name__ == '__main__':
    main() 