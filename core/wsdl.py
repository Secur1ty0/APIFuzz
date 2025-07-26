# -*- coding: utf-8 -*-
# core/wsdl.py
"""
WSDL/SOAP 处理模块
专门处理 WSDL (Web Services Description Language) 和 SOAP 协议的API文档
"""

import xml.etree.ElementTree as ET
import requests
import random
import string
import time
import csv
import json
import queue
from typing import Dict, Any, List, Tuple, Optional
from .base import BaseFuzzer
from .wsdl_types import create_wsdl_types_parser
from tqdm import tqdm

class WSDLFuzzer(BaseFuzzer):
    """WSDL/SOAP API 模糊测试器"""
    
    def __init__(self, spec_data: Dict[str, Any], base_url: str, proxy: Optional[str] = None,
                 threads: int = 1, output_format: str = "csv", delay: float = 0,
                 extra_headers: Optional[Dict[str, str]] = None, type_definition: Optional[str] = None):
        super().__init__(spec_data, base_url, proxy, threads, output_format, delay, extra_headers)
        
        # WSDL 特定属性
        self.wsdl_data = spec_data
        self.services = {}
        self.port_types = {}
        self.messages = {}
        self.bindings = {}
        self.types = {}
        
        # SOAP 特定测试值
        self.soap_test_values = {
            # 基础类型
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
            "unicode": "测试中文🚀🎉",
        }
        
        # 进度条相关
        self.progress = None
        self.notable_results = []  # 存储值得注意的结果（2xx, 3xx, 5xx）
        
        # WSDL自定义类型定义支持
        self.type_definition = type_definition
        self.types_parser = None
        if type_definition:
            self._load_type_definition()
        
        # 解析 WSDL
        self.parse_wsdl()
    
    def _load_type_definition(self) -> None:
        """加载WSDL自定义类型定义文件"""
        try:
            self.types_parser = create_wsdl_types_parser(self.type_definition)
            if self.types_parser:
                print(f"[+] 成功加载类型定义: {self.types_parser.get_library_info()['name']}")
                # 更新测试值映射
                self._enhance_test_values_with_types()
            else:
                print(f"[!] 类型定义加载失败，将使用默认测试值")
        except Exception as e:
            print(f"[!] 类型定义加载异常: {e}，将使用默认测试值")
    
    def _enhance_test_values_with_types(self) -> None:
        """使用WSDL自定义类型定义增强测试值"""
        if not self.types_parser:
            return
        
        # 获取自定义类型定义中的数据类型映射
        types_mappings = self.types_parser.datatype_mappings
        
        # 增强现有的测试值
        for custom_type, mapping in types_mappings.items():
            standard_type = mapping['standard_type']
            test_values = mapping['test_values']
            
            # 将自定义类型的测试值合并到现有测试值中
            if standard_type in self.soap_test_values:
                # 合并测试值，去重
                existing_values = self.soap_test_values[standard_type]
                if isinstance(existing_values, list):
                    combined_values = list(set(existing_values + test_values))
                    self.soap_test_values[standard_type] = combined_values
            else:
                # 添加新的类型映射
                self.soap_test_values[standard_type] = test_values
        
        print(f"[+] 已使用自定义类型定义增强 {len(types_mappings)} 种数据类型的测试值")
    
    def add_custom_test_values(self, value_type: str, test_values: List[Any]) -> None:
        """添加自定义测试值（用户可扩展）"""
        if value_type not in self.soap_test_values:
            self.soap_test_values[value_type] = []
        
        if isinstance(self.soap_test_values[value_type], list):
            # 合并自定义测试值
            self.soap_test_values[value_type].extend(test_values)
            # 去重
            self.soap_test_values[value_type] = list(set(self.soap_test_values[value_type]))
        else:
            # 转为列表并添加
            self.soap_test_values[value_type] = [self.soap_test_values[value_type]] + test_values
    
    def get_comprehensive_test_values(self, param_name: str, param_type: str) -> List[Any]:
        """获取全面的测试值（包括WSDL自定义类型、WSDL默认和智能推断）"""
        test_values = []
        
        # 1. 从WSDL自定义类型定义获取测试值
        if self.types_parser:
            for operation_name, operation_info in self.types_parser.get_all_operations().items():
                for input_param in operation_info.get('input_params', []):
                    if input_param['name'] == param_name:
                        custom_datatype = input_param['datatype']
                        custom_values = self.types_parser.get_all_test_values(custom_datatype)
                        test_values.extend(custom_values)
        
        # 2. 从WSDL类型映射获取测试值
        type_name = param_type.split(':')[-1] if ':' in param_type else param_type
        if type_name in self.soap_test_values:
            wsdl_values = self.soap_test_values[type_name]
            if isinstance(wsdl_values, list):
                test_values.extend(wsdl_values)
            else:
                test_values.append(wsdl_values)
        
        # 3. 添加基于参数名称的智能测试值
        intelligent_values = self._get_intelligent_test_values(param_name)
        test_values.extend(intelligent_values)
        
        # 4. 添加边界值测试
        boundary_values = self._get_boundary_test_values()
        test_values.extend(boundary_values)
        
        # 去重并返回
        return list(set(str(v) for v in test_values if v is not None))
    
    def _get_intelligent_test_values(self, param_name: str) -> List[str]:
        """基于参数名称生成智能测试值"""
        param_lower = param_name.lower() if param_name else ""
        
        # 通用安全测试模式
        base_values = [
            "",  # 空值
            " ",  # 空格
            "null",  # null字符串
            "undefined",  # undefined
            "0",  # 零值
            "-1",  # 负数
            "999999999",  # 大数
        ]
        
        # 基于名称模式的智能值
        if any(keyword in param_lower for keyword in ['id', 'uid']):
            base_values.extend([
                "1", "100", "12345", "0", "-1", 
                "999999999", "test_id"
            ])
        elif any(keyword in param_lower for keyword in ['name', 'username', 'user']):
            base_values.extend([
                "admin", "test_user", "guest", "user123", 
                "TestUser", "demo_user"
            ])
        elif any(keyword in param_lower for keyword in ['password', 'pass', 'pwd']):
            base_values.extend([
                "password", "123456", "test123", "password123",
                "demo_password", ""
            ])
        elif any(keyword in param_lower for keyword in ['email', 'mail']):
            base_values.extend([
                "test@example.com", "user@test.com", "demo@example.org",
                "admin@localhost", "invalid-email", "@", "test@"
            ])
        elif any(keyword in param_lower for keyword in ['url', 'uri', 'link']):
            base_values.extend([
                "http://example.com", "https://test.com", "http://localhost",
                "ftp://test.com", "mailto:test@example.com"
            ])
        
        return base_values
    
    def _get_boundary_test_values(self) -> List[str]:
        """获取边界值测试数据"""
        return [
            # 空值和特殊值
            "",
            " ",
            "null",
            "undefined",
            "0",
            "1",
            "-1",
            
            # 长度边界测试
            "a",  # 最小长度
            "a" * 50,  # 中等长度
            "a" * 255,  # 常见最大长度
            "a" * 1000,  # 超长字符串
            
            # 数字边界值
            "2147483647",  # int32 最大值
            "-2147483648",  # int32 最小值
            "9223372036854775807",  # int64 最大值
            "999999999",
            
            # 特殊字符测试
            "中文测试",
            "test@example.com",
            "Test 123",
            "test_value",
            "TEST-VALUE",
            
            # JSON格式测试
            '{"test": "value"}',
            '[]',
            '{}',
            
            # XML格式测试  
            '<test>value</test>',
            '<?xml version="1.0"?><root>test</root>',
        ]
    
    def parse_wsdl(self) -> None:
        """解析 WSDL 文档"""
        try:
            # 如果 spec_data 是字符串，解析为 XML
            if isinstance(self.wsdl_data, str):
                root = ET.fromstring(self.wsdl_data)
            else:
                # 假设已经是解析后的数据
                return
            
            # 定义命名空间
            namespaces = {
                'wsdl': 'http://schemas.xmlsoap.org/wsdl/',
                'xs': 'http://www.w3.org/2001/XMLSchema',
                'soap': 'http://schemas.xmlsoap.org/wsdl/soap/',
                'tns': root.get('targetNamespace', '')
            }
            
            # 解析消息定义
            for message in root.findall('.//wsdl:message', namespaces):
                message_name = message.get('name')
                parts = []
                for part in message.findall('.//wsdl:part', namespaces):
                    parts.append({
                        'name': part.get('name'),
                        'type': part.get('type'),
                        'element': part.get('element')
                    })
                self.messages[message_name] = parts
            
            # 解析端口类型
            for port_type in root.findall('.//wsdl:portType', namespaces):
                port_name = port_type.get('name')
                operations = []
                for operation in port_type.findall('.//wsdl:operation', namespaces):
                    op_name = operation.get('name')
                    input_msg = operation.find('.//wsdl:input', namespaces)
                    output_msg = operation.find('.//wsdl:output', namespaces)
                    
                    # 处理消息引用中的命名空间前缀
                    input_message = input_msg.get('message') if input_msg is not None else None
                    output_message = output_msg.get('message') if output_msg is not None else None
                    
                    operations.append({
                        'name': op_name,
                        'input': input_message,
                        'output': output_message
                    })
                self.port_types[port_name] = operations
            
            # 解析绑定
            for binding in root.findall('.//wsdl:binding', namespaces):
                binding_name = binding.get('name')
                port_type = binding.get('type')
                soap_binding = binding.find('.//soap:binding', namespaces)
                
                operations = []
                for op_binding in binding.findall('.//wsdl:operation', namespaces):
                    op_name = op_binding.get('name')
                    soap_op = op_binding.find('.//soap:operation', namespaces)
                    
                    operations.append({
                        'name': op_name,
                        'soapAction': soap_op.get('soapAction') if soap_op is not None else None,
                        'style': soap_op.get('style') if soap_op is not None else 'rpc'
                    })
                
                self.bindings[binding_name] = {
                    'portType': port_type,
                    'style': soap_binding.get('style') if soap_binding is not None else 'rpc',
                    'transport': soap_binding.get('transport') if soap_binding is not None else None,
                    'operations': operations
                }
            
            # 解析服务
            for service in root.findall('.//wsdl:service', namespaces):
                service_name = service.get('name')
                ports = []
                for port in service.findall('.//wsdl:port', namespaces):
                    port_name = port.get('name')
                    binding = port.get('binding')
                    soap_address = port.find('.//soap:address', namespaces)
                    location = soap_address.get('location') if soap_address is not None else None
                    
                    ports.append({
                        'name': port_name,
                        'binding': binding,
                        'location': location
                    })
                self.services[service_name] = ports
            
            print(f"[+] WSDL 解析完成: {len(self.services)} 个服务, {len(self.port_types)} 个端口类型, {len(self.messages)} 个消息")
                
        except Exception as e:
            print(f"[!] 解析 WSDL 失败: {e}")
            import traceback
            traceback.print_exc()
    
    def extract_endpoints(self) -> None:
        """提取 SOAP 端点"""
        self.endpoints = []
        
        for service_name, ports in self.services.items():
            for port in ports:
                binding_name = port['binding']
                # 处理命名空间前缀
                if ':' in binding_name:
                    binding_name = binding_name.split(':')[-1]
                
                if binding_name in self.bindings:
                    binding = self.bindings[binding_name]
                    port_type_name = binding['portType']
                    # 处理命名空间前缀
                    if ':' in port_type_name:
                        port_type_name = port_type_name.split(':')[-1]
                    
                    if port_type_name in self.port_types:
                        operations = self.port_types[port_type_name]
                        
                        for operation in operations:
                            endpoint = {
                                'service': service_name,
                                'port': port['name'],
                                'binding': binding_name,
                                'portType': port_type_name,
                                'operation': operation['name'],
                                'input_message': operation['input'],
                                'output_message': operation['output'],
                                'location': port['location'],
                                'soapAction': self._get_soap_action(binding_name, operation['name'], service_name)
                            }
                            self.endpoints.append(endpoint)
                else:
                    print(f"[!] 未找到绑定: {binding_name}")
        
        print(f"[+] 从 WSDL 中提取到 {len(self.endpoints)} 个 SOAP 操作")
    
    def _get_soap_action(self, binding_name: str, operation_name: str, service_name: str = None) -> str:
        """获取 SOAP Action - 符合RemObjects SDK格式"""
        # 首先尝试从WSDL中获取
        if binding_name in self.bindings:
            binding = self.bindings[binding_name]
            for op in binding['operations']:
                if op['name'] == operation_name and op['soapAction']:
                    return f'"{op["soapAction"]}"'
        
        # 如果WSDL中没有定义，动态生成SOAPAction - 通用方法
        if service_name:
            soap_action = self._generate_soap_action_from_context(service_name, operation_name)
        else:
            # 最基本的兜底格式
            soap_action = f'"{operation_name}"'
        
        return soap_action
    
    def _get_interface_namespace(self, service_name: str, endpoint: Dict[str, Any]) -> str:
        """动态获取接口命名空间 - 通用方法"""
        # 首先尝试从WSDL的绑定信息中提取命名空间
        binding_name = endpoint.get('binding', '')
        port_type_name = endpoint.get('portType', '')
        
        # 方法1: 从已有的SOAPAction中推断 (如果有的话)
        soap_action = endpoint.get('soapAction', '')
        if soap_action and '#' in soap_action:
            namespace_part = soap_action.split('#')[0].strip('"')
            if namespace_part.startswith('urn:'):
                return namespace_part
        
        # 方法2: 从WSDL的targetNamespace和service/binding信息构建
        # 检查WSDL根元素的targetNamespace
        try:
            if isinstance(self.wsdl_data, str):
                root = ET.fromstring(self.wsdl_data)
                target_namespace = root.get('targetNamespace', '')
                
                # 常见的命名空间模式分析
                if target_namespace:
                    # 模式1: 直接使用targetNamespace (如 http://tempuri.org/)
                    if target_namespace == "http://tempuri.org/":
                        # 检查绑定名或端口类型名来构建更具体的命名空间
                        if binding_name or port_type_name:
                            # 提取接口名（通常是绑定名去掉后缀）
                            interface_name = self._extract_interface_name(binding_name, port_type_name)
                            if interface_name:
                                return f"urn:{interface_name}"
                    
                    # 模式2: 其他自定义命名空间
                    return target_namespace
        except Exception as e:
            print(f"[!] 解析命名空间时出错: {e}")
        
        # 方法3: 基于服务名的智能推断 (兜底逻辑)
        return self._infer_namespace_from_service_name(service_name)
    
    def _extract_interface_name(self, binding_name: str, port_type_name: str) -> str:
        """从绑定名或端口类型名提取接口名"""
        # 优先使用端口类型名，因为它通常更接近接口名
        if port_type_name:
            return port_type_name
        
        # 如果没有端口类型名，从绑定名推断
        if binding_name:
            # 移除常见的后缀
            interface_name = binding_name.replace('binding', '').replace('Binding', '')
            return interface_name
        
        return ""
    
    def _infer_namespace_from_service_name(self, service_name: str) -> str:
        """基于服务名推断命名空间 - 兜底方法"""
        # 移除常见的服务后缀
        clean_name = service_name.replace('ServiceService', 'Service').replace('Service', '').replace('service', '')
        
        # 常见的命名空间模式
        if clean_name:
            return f"urn:{clean_name}"
        else:
            return "urn:default"
    
    def _generate_soap_action_from_context(self, service_name: str, operation_name: str) -> str:
        """基于上下文动态生成SOAPAction"""
        # 首先尝试从已解析的绑定信息中查找模式
        example_action = self._find_example_soap_action()
        
        if example_action and '#' in example_action:
            # 从示例中提取模式
            namespace_part = example_action.split('#')[0].strip('"')
            return f'"{namespace_part}#{operation_name}"'
        
        # 如果没有示例，使用推断的命名空间
        interface_namespace = self._infer_namespace_from_service_name(service_name)
        return f'"{interface_namespace}#{operation_name}"'
    
    def _find_example_soap_action(self) -> str:
        """查找一个示例SOAPAction来推断模式"""
        for binding_name, binding in self.bindings.items():
            for operation in binding.get('operations', []):
                soap_action = operation.get('soapAction')
                if soap_action and '#' in soap_action:
                    return soap_action
        return ""
    
    def prepare_request(self, method: str, path: str, details: Dict[str, Any]) -> Tuple[str, str, Dict[str, str], Dict[str, Any], Optional[str], Optional[Dict]]:
        """准备 SOAP 请求 - 符合RemObjects SDK规范"""
        # SOAP 请求总是 POST
        method = "POST"
        url = details['location']
        
        # 确保SOAPAction格式正确
        soap_action = details.get('soapAction', '')
        if soap_action and not soap_action.startswith('"'):
            soap_action = f'"{soap_action}"'
        
        # 准备 SOAP 头部 - 符合RemObjects SDK要求
        headers = {
            'Content-Type': 'text/xml; charset=utf-8',
            'SOAPAction': soap_action,
            'User-Agent': self.user_agent
        }
        
        # 添加自定义头部
        if self.extra_headers:
            headers.update(self.extra_headers)
        
        # 生成 SOAP 消息体
        soap_body = self._generate_soap_message(details)
        
        return method, url, headers, {}, soap_body, None
    
    def _generate_soap_message(self, endpoint: Dict[str, Any]) -> str:
        """生成 SOAP 消息 - 符合RemObjects SDK规范"""
        operation_name = endpoint['operation']
        input_message = endpoint['input_message']
        service_name = endpoint.get('service', 'Unknown')
        
        # 获取输入消息的参数
        params = []
        if input_message:
            # 处理命名空间前缀
            if ':' in input_message:
                input_message = input_message.split(':')[-1]
            
            if input_message in self.messages:
                params = self.messages[input_message]
        
        # 动态确定正确的接口命名空间 - 通用方法
        interface_namespace = self._get_interface_namespace(service_name, endpoint)
        interface_prefix = "tran"  # 使用tran作为业务接口前缀
        
        # 生成 SOAP 信封 - 符合RemObjects SDK规范
        soap_envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" 
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:{interface_prefix}="{interface_namespace}">
  <soap:Header/>
  <soap:Body>
    <{interface_prefix}:{operation_name}>
"""
        
        # 添加参数
        for param in params:
            param_name = param['name']
            param_type = param['type']
            param_value = self._generate_param_value(param_type, param_name)
            soap_envelope += f"      <{param_name}>{param_value}</{param_name}>\n"
        
        soap_envelope += f"""    </{interface_prefix}:{operation_name}>
  </soap:Body>
</soap:Envelope>"""
        
        return soap_envelope
    
    def _generate_param_value(self, param_type: str, param_name: str) -> str:
        """生成参数值 - 增强版本，支持WSDL自定义类型定义"""
        if not param_type:
            return self._get_random_test_value("string")
        
        # 首先尝试从WSDL自定义类型定义获取增强的值
        if self.types_parser and param_name:
            types_value = self._get_types_enhanced_value(param_name, param_type)
            if types_value is not None:
                return str(types_value)
        
        # 提取类型名称（去掉命名空间）
        type_name = param_type.split(':')[-1] if ':' in param_type else param_type
        
        # 根据类型生成测试值
        if type_name == "string":
            return self._get_random_test_value("string")
        elif type_name == "int":
            return str(self._get_random_test_value("int"))
        elif type_name == "boolean":
            return str(self._get_random_test_value("boolean")).lower()
        elif type_name == "double" or type_name == "float":
            return str(self._get_random_test_value("double"))
        elif type_name == "date":
            return self._get_random_test_value("date")
        elif type_name == "dateTime":
            return self._get_random_test_value("dateTime")
        else:
            # 默认使用字符串，但尝试更智能的类型推断
            return self._get_enhanced_default_value(param_name, type_name)
    
    def _get_types_enhanced_value(self, param_name: str, param_type: str) -> Any:
        """从WSDL自定义类型定义获取增强的参数值"""
        if not self.types_parser:
            return None
        
        # 尝试从当前操作的上下文中查找参数类型定义
        # 这里可以根据实际的WSDL操作名称来查找对应的自定义类型操作
        for operation_name, operation_info in self.types_parser.get_all_operations().items():
            for input_param in operation_info.get('input_params', []):
                if input_param['name'] == param_name:
                    # 找到匹配的参数，使用自定义类型的数据类型生成值
                    custom_datatype = input_param['datatype']
                    return self.types_parser.generate_test_value(custom_datatype, param_name)
        
        return None
    
    def _get_enhanced_default_value(self, param_name: str, type_name: str) -> str:
        """获取增强的默认值（基于参数名称推断）"""
        # 基于参数名称的智能推断
        param_lower = param_name.lower() if param_name else ""
        
        # ID类型参数
        if any(keyword in param_lower for keyword in ['id', 'uid', 'guid']):
            return random.choice(['1', '12345', 'test-id-001', str(random.randint(1, 99999))])
        
        # URL类型参数
        elif any(keyword in param_lower for keyword in ['url', 'uri', 'link', 'address']):
            return random.choice([
                'http://example.com',
                'https://test.com/api',
                'ftp://files.example.com',
                'file:///etc/passwd',
                'javascript:alert(1)'
            ])
        
        # 邮箱类型参数
        elif any(keyword in param_lower for keyword in ['email', 'mail']):
            return random.choice([
                'test@example.com',
                'admin@test.com',
                'user+test@domain.co.uk',
                'invalid-email',
                'test@'
            ])
        
        # 路径类型参数
        elif any(keyword in param_lower for keyword in ['path', 'file', 'dir', 'folder']):
            return random.choice([
                '/tmp/test.txt',
                'C:\\Users\\test\\file.txt',
                'test/file.txt',
                'data/config.xml',
                '/home/user/document.pdf'
            ])
        
        # 状态/代码类型参数
        elif any(keyword in param_lower for keyword in ['status', 'code', 'state']):
            return random.choice(['0', '1', '200', '404', '500', 'active', 'inactive', 'pending'])
        
        # 用户名类型参数
        elif any(keyword in param_lower for keyword in ['user', 'username', 'account']):
            return random.choice(['admin', 'user', 'test', 'guest', 'demo_user', 'test_account'])
        
        # 数据/消息类型参数
        elif any(keyword in param_lower for keyword in ['data', 'message', 'content', 'body']):
            return random.choice([
                '{"test": "data"}',
                '<xml>test</xml>',
                'test message content',
                'sample data payload',
                'A' * 100  # 中等长度测试
            ])
        
        # 默认返回通用测试值
        else:
            return self._get_random_test_value("string")
    
    def _get_random_test_value(self, value_type: str) -> Any:
        """获取随机测试值"""
        if value_type in self.soap_test_values:
            values = self.soap_test_values[value_type]
            if isinstance(values, list):
                return random.choice(values)
            else:
                return values
        else:
            return "test"
    
    def mock_schema(self, schema: Dict[str, Any], components: Optional[Dict] = None, visited_refs: Optional[set] = None) -> Any:
        """根据 schema 生成模拟数据 - WSDL 版本"""
        # WSDL 使用简单的类型系统，直接返回测试值
        schema_type = schema.get('type', 'string')
        return self._get_random_test_value(schema_type)
    
    def fuzz(self) -> None:
        """开始 SOAP 模糊测试"""
        print(f"[+] 开始 SOAP 模糊测试，线程数: {self.threads}")
        
        # 提取端点
        self.extract_endpoints()
        
        if not self.endpoints:
            print("[!] 没有找到可测试的 SOAP 端点")
            return
        
        # 将端点添加到队列
        for endpoint in self.endpoints:
            self.queue.put(endpoint)
        
        # 初始化进度条
        self.progress = tqdm(total=len(self.endpoints), desc="Fuzzing", 
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
    
    def worker(self, thread_id: int) -> None:
        """工作线程函数 - 保持与swagger2一致的风格"""
        while True:
            try:
                endpoint = self.queue.get(timeout=1)
                
                try:
                    # 准备请求
                    method, url, headers, params, body, files = self.prepare_request("POST", "", endpoint)
                    
                    # 发送请求
                    response = self.send_request(method, url, headers, params, body, files)
                    
                    # 获取状态码和错误信息
                    try:
                        status = str(response.status_code)
                        error_info = getattr(response, '_error', None)
                    except Exception:
                        status = "ERROR"
                        error_info = "Request failed"
                    
                    # 记录结果
                    with self.lock:
                        self.results.append({
                            "method": method,
                            "url": url,
                            "service": endpoint['service'],
                            "operation": endpoint['operation'],
                            "status": status,
                            "response_time": getattr(response, '_response_time', 0) if response else 0,
                            "content_length": len(response.content) if response and response.content else 0,
                            "error": error_info
                        })
                        
                        # 检查是否为值得注意的状态码（用于Summary）
                        if self._is_notable_status(status):
                            self.notable_results.append({
                                "method": method,
                                "url": url,
                                "service": endpoint['service'],
                                "operation": endpoint['operation'],
                                "status": status
                            })
                    
                    # 显示所有结果 - 保持与swagger2一致的风格
                    self._show_all_result(method, url, status, error_info)
                    
                    # 更新进度条
                    if self.progress:
                        self.progress.update(1)
                    
                    # 延迟
                    if self.delay > 0:
                        time.sleep(self.delay)
                        
                except Exception as e:
                    error_msg = str(e)
                    with self.lock:
                        self.results.append({
                            "method": "POST",
                            "url": endpoint.get('location', ''),
                            "service": endpoint['service'],
                            "operation": endpoint['operation'],
                            "status": "ERROR",
                            "response_time": 0,
                            "content_length": 0,
                            "error": error_msg
                        })
                    
                    # 显示错误结果
                    self._show_all_result("POST", endpoint.get('location', ''), "ERROR", error_msg)
                    
                    # 更新进度条
                    if self.progress:
                        self.progress.update(1)
                
                self.queue.task_done()
                
            except queue.Empty:
                break
            except Exception as e:
                break
    

    
    def _show_all_result(self, method: str, url: str, status: str, error_info: str = None) -> None:
        """显示所有结果 - 完全匹配swagger2风格"""
        from colorama import Style
        from tqdm import tqdm
        
        # 使用基类的get_status_color方法，确保风格一致
        status_color = self.get_status_color(status)
        
        # 如果有错误信息且状态为ERROR，在状态后追加错误信息
        if status == "ERROR" and error_info:
            display_status = f"{status}: {error_info}"
        else:
            display_status = status
        
        # 完全匹配swagger2的格式：颜色包围整行，状态码左对齐4字符
        tqdm.write(f"{status_color}[{method:<6}  ] {url:<80} -> {display_status:<20}{Style.RESET_ALL}")
    
    def save_results(self) -> None:
        """保存测试结果"""
        if not self.results:
            print("[!] 没有结果可保存")
            return
        
        filename = f"soap_fuzzer_results_{int(time.time())}.{self.output_format}"
        
        if self.output_format == "csv":
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                fieldnames = ["method", "url", "service", "operation", "status", "response_time", "content_length", "error"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.results)
        
        elif self.output_format == "json":
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.results, f, indent=2, ensure_ascii=False)
        
        print(f"[+] SOAP 测试结果已保存到: {filename}")
    



class WSDLParser:
    """WSDL 解析器"""
    
    def __init__(self, wsdl_content: str):
        self.wsdl_content = wsdl_content
        self.parsed_data = {}
    
    def parse(self) -> Dict[str, Any]:
        """解析 WSDL 内容"""
        try:
            root = ET.fromstring(self.wsdl_content)
            
            # 提取基本信息
            self.parsed_data = {
                'name': root.get('name'),
                'targetNamespace': root.get('targetNamespace'),
                'services': self._parse_services(root),
                'portTypes': self._parse_port_types(root),
                'bindings': self._parse_bindings(root),
                'messages': self._parse_messages(root),
                'types': self._parse_types(root)
            }
            
            return self.parsed_data
            
        except Exception as e:
            print(f"[!] 解析 WSDL 失败: {e}")
            return {}
    
    def _parse_services(self, root: ET.Element) -> Dict[str, Any]:
        """解析服务定义"""
        services = {}
        namespaces = {'wsdl': 'http://schemas.xmlsoap.org/wsdl/'}
        
        for service in root.findall('.//wsdl:service', namespaces):
            service_name = service.get('name')
            ports = []
            
            for port in service.findall('.//wsdl:port', namespaces):
                port_data = {
                    'name': port.get('name'),
                    'binding': port.get('binding'),
                    'location': self._get_soap_address(port)
                }
                ports.append(port_data)
            
            services[service_name] = ports
        
        return services
    
    def _parse_port_types(self, root: ET.Element) -> Dict[str, Any]:
        """解析端口类型"""
        port_types = {}
        namespaces = {'wsdl': 'http://schemas.xmlsoap.org/wsdl/'}
        
        for port_type in root.findall('.//wsdl:portType', namespaces):
            port_name = port_type.get('name')
            operations = []
            
            for operation in port_type.findall('.//wsdl:operation', namespaces):
                op_data = {
                    'name': operation.get('name'),
                    'input': self._get_message_ref(operation, 'input'),
                    'output': self._get_message_ref(operation, 'output')
                }
                operations.append(op_data)
            
            port_types[port_name] = operations
        
        return port_types
    
    def _parse_bindings(self, root: ET.Element) -> Dict[str, Any]:
        """解析绑定"""
        bindings = {}
        namespaces = {
            'wsdl': 'http://schemas.xmlsoap.org/wsdl/',
            'soap': 'http://schemas.xmlsoap.org/wsdl/soap/'
        }
        
        for binding in root.findall('.//wsdl:binding', namespaces):
            binding_name = binding.get('name')
            soap_binding = binding.find('.//soap:binding', namespaces)
            
            binding_data = {
                'type': binding.get('type'),
                'style': soap_binding.get('style') if soap_binding is not None else 'rpc',
                'transport': soap_binding.get('transport') if soap_binding is not None else None,
                'operations': self._parse_binding_operations(binding, namespaces)
            }
            
            bindings[binding_name] = binding_data
        
        return bindings
    
    def _parse_messages(self, root: ET.Element) -> Dict[str, Any]:
        """解析消息定义"""
        messages = {}
        namespaces = {'wsdl': 'http://schemas.xmlsoap.org/wsdl/'}
        
        for message in root.findall('.//wsdl:message', namespaces):
            message_name = message.get('name')
            parts = []
            
            for part in message.findall('.//wsdl:part', namespaces):
                part_data = {
                    'name': part.get('name'),
                    'type': part.get('type'),
                    'element': part.get('element')
                }
                parts.append(part_data)
            
            messages[message_name] = parts
        
        return messages
    
    def _parse_types(self, root: ET.Element) -> Dict[str, Any]:
        """解析类型定义"""
        types = {}
        namespaces = {'xs': 'http://www.w3.org/2001/XMLSchema'}
        
        for schema in root.findall('.//xs:schema', namespaces):
            # 这里可以添加更复杂的类型解析逻辑
            types['schema'] = schema.get('targetNamespace')
        
        return types
    
    def _get_soap_address(self, port: ET.Element) -> Optional[str]:
        """获取 SOAP 地址"""
        namespaces = {'soap': 'http://schemas.xmlsoap.org/wsdl/soap/'}
        address = port.find('.//soap:address', namespaces)
        return address.get('location') if address is not None else None
    
    def _get_message_ref(self, operation: ET.Element, direction: str) -> Optional[str]:
        """获取消息引用"""
        namespaces = {'wsdl': 'http://schemas.xmlsoap.org/wsdl/'}
        msg_elem = operation.find(f'.//wsdl:{direction}', namespaces)
        return msg_elem.get('message') if msg_elem is not None else None
    
    def _parse_binding_operations(self, binding: ET.Element, namespaces: Dict[str, str]) -> List[Dict[str, Any]]:
        """解析绑定操作"""
        operations = []
        
        for op_binding in binding.findall('.//wsdl:operation', namespaces):
            op_name = op_binding.get('name')
            soap_op = op_binding.find('.//soap:operation', namespaces)
            
            op_data = {
                'name': op_name,
                'soapAction': soap_op.get('soapAction') if soap_op is not None else None,
                'style': soap_op.get('style') if soap_op is not None else 'rpc'
            }
            operations.append(op_data)
        
        return operations
