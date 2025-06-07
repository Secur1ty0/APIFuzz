# util.py

import json
import os
import requests
from urllib.parse import urlparse
from colorama import Fore


def get_status_color(status):
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


def load_openapi_spec(file_path, swagger_url):
    if file_path and os.path.isfile(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        resp = requests.get(swagger_url, verify=False)
        resp.raise_for_status()
        return resp.json()


def resolve_urls(base_url, file_path):
    parsed = urlparse(base_url)
    if parsed.path.endswith(".json"):
        swagger_url = base_url
        base_api = f"{parsed.scheme}://{parsed.netloc}"
    else:
        if not file_path:
            raise ValueError("When -u is not a .json URL, you must specify -f for OpenAPI relative path.")
        if not file_path.startswith("/"):
            file_path = "/" + file_path
        swagger_url = f"{parsed.scheme}://{parsed.netloc}{file_path}"
        base_api = base_url.rstrip("/")
    return swagger_url, base_api


def parse_headers_arg(headers_list):
    headers = {}
    if headers_list:
        for h in headers_list:
            if ":" in h:
                k, v = h.split(":", 1)
                headers[k.strip()] = v.strip()
    return headers
