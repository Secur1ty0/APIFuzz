# -*- coding: utf-8 -*-
"""
WSDL 自定义类型定义解析器
用于解析类似 bin.xml 格式的WSDL自定义接口定义文件，提取操作和参数类型信息
"""

import xml.etree.ElementTree as ET
import requests
from typing import Dict, List, Any, Optional, Union
from urllib.parse import urlparse


class WSDLTypesParser:
    """WSDL自定义类型定义解析器，用于解析接口定义库文件"""
    
    def __init__(self, types_source: str):
        """
        初始化WSDL自定义类型解析器
        
        Args:
            types_source: WSDL自定义类型定义文件路径或URL
        """
        self.types_source = types_source
        self.library_info = {}
        self.services = {}
        self.operations = {}
        self.type_mappings = {}
        
        # 数据类型映射 - WSDL自定义类型 -> 标准类型 -> 测试值
        self.datatype_mappings = {
            'String': {
                'standard_type': 'string',
                'test_values': ['test_string', '', 'admin', '<script>alert(1)</script>', "'OR 1=1--", 'A' * 255],
                'default': 'test_string'
            },
            'Integer': {
                'standard_type': 'integer',
                'test_values': [1, 0, -1, 999999, -999999, 2147483647, -2147483648],
                'default': 1
            },
            'Variant': {
                'standard_type': 'any',
                'test_values': ['test_variant', 1, True, {'key': 'value'}, ['item1', 'item2']],
                'default': 'test_variant'
            },
            'Boolean': {
                'standard_type': 'boolean',
                'test_values': [True, False, 'true', 'false', 1, 0],
                'default': True
            },
            'DateTime': {
                'standard_type': 'datetime',
                'test_values': ['2024-01-01T12:00:00Z', '2024-12-31T23:59:59Z', '1900-01-01T00:00:00Z'],
                'default': '2024-01-01T12:00:00Z'
            }
        }
        
        self.parse()
    
    def parse(self) -> None:
        """解析WSDL自定义类型定义文件"""
        try:
            # 加载XML内容
            xml_content = self._load_types_content()
            root = ET.fromstring(xml_content)
            
            # 解析库信息
            self._parse_library_info(root)
            
            # 解析服务和操作
            self._parse_services(root)
            
            print(f"[+] WSDL自定义类型解析完成: {len(self.services)} 个服务, {len(self.operations)} 个操作")
            
        except Exception as e:
            print(f"[!] WSDL自定义类型解析失败: {e}")
            raise
    
    def _load_types_content(self) -> str:
        """加载WSDL自定义类型内容（支持本地文件和HTTP URL）"""
        if self._is_url(self.types_source):
            # HTTP URL
            try:
                response = requests.get(self.types_source, timeout=10)
                response.raise_for_status()
                return response.text
            except Exception as e:
                raise ValueError(f"无法从URL加载WSDL自定义类型文件: {e}")
        else:
            # 本地文件
            try:
                with open(self.types_source, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                raise ValueError(f"无法加载本地WSDL自定义类型文件: {e}")
    
    def _is_url(self, source: str) -> bool:
        """检查是否为有效的URL"""
        try:
            result = urlparse(source)
            return all([result.scheme, result.netloc])
        except:
            return False
    
    def _parse_library_info(self, root: ET.Element) -> None:
        """解析库信息"""
        self.library_info = {
            'name': root.get('Name', 'Unknown'),
            'uid': root.get('UID', ''),
            'version': root.get('Version', '1.0')
        }
    
    def _parse_services(self, root: ET.Element) -> None:
        """解析服务和操作"""
        services_elem = root.find('Services')
        if services_elem is None:
            return
        
        for service_elem in services_elem.findall('Service'):
            service_name = service_elem.get('Name')
            service_uid = service_elem.get('UID')
            
            if not service_name:
                continue
            
            self.services[service_name] = {
                'uid': service_uid,
                'operations': {}
            }
            
            # 解析接口和操作
            interfaces_elem = service_elem.find('Interfaces')
            if interfaces_elem is not None:
                for interface_elem in interfaces_elem.findall('Interface'):
                    operations_elem = interface_elem.find('Operations')
                    if operations_elem is not None:
                        for operation_elem in operations_elem.findall('Operation'):
                            self._parse_operation(service_name, operation_elem)
    
    def _parse_operation(self, service_name: str, operation_elem: ET.Element) -> None:
        """解析操作定义"""
        operation_name = operation_elem.get('Name')
        operation_uid = operation_elem.get('UID')
        
        if not operation_name:
            return
        
        # 构建操作的完整标识
        full_operation_name = f"{service_name}_{operation_name}"
        
        operation_info = {
            'service': service_name,
            'name': operation_name,
            'uid': operation_uid,
            'input_params': [],
            'output_params': [],
            'result_param': None
        }
        
        # 解析参数
        parameters_elem = operation_elem.find('Parameters')
        if parameters_elem is not None:
            for param_elem in parameters_elem.findall('Parameter'):
                param_info = self._parse_parameter(param_elem)
                
                if param_info['flag'] == 'In':
                    operation_info['input_params'].append(param_info)
                elif param_info['flag'] == 'Out':
                    operation_info['output_params'].append(param_info)
                elif param_info['flag'] == 'Result':
                    operation_info['result_param'] = param_info
        
        # 存储操作信息
        self.operations[full_operation_name] = operation_info
        self.services[service_name]['operations'][operation_name] = operation_info
    
    def _parse_parameter(self, param_elem: ET.Element) -> Dict[str, Any]:
        """解析参数定义"""
        return {
            'name': param_elem.get('Name'),
            'datatype': param_elem.get('DataType'),
            'flag': param_elem.get('Flag'),  # In, Out, Result
            'required': param_elem.get('Flag') == 'In'  # 输入参数默认为必需
        }
    
    def get_operation_input_types(self, service_name: str, operation_name: str) -> Dict[str, str]:
        """获取操作的输入参数类型映射"""
        full_operation_name = f"{service_name}_{operation_name}"
        operation = self.operations.get(full_operation_name)
        
        if not operation:
            return {}
        
        type_mapping = {}
        for param in operation['input_params']:
            param_name = param['name']
            param_datatype = param['datatype']
            
            # 映射到标准类型
            if param_datatype in self.datatype_mappings:
                standard_type = self.datatype_mappings[param_datatype]['standard_type']
                type_mapping[param_name] = standard_type
            else:
                # 未知类型默认为字符串
                type_mapping[param_name] = 'string'
        
        return type_mapping
    
    def generate_test_value(self, datatype: str, param_name: str = None) -> Any:
        """根据WSDL自定义数据类型生成测试值"""
        if datatype in self.datatype_mappings:
            mapping = self.datatype_mappings[datatype]
            # 优先返回默认值，也可以随机选择测试值
            return mapping['default']
        
        # 未知类型的兜底处理
        return f"test_{param_name}" if param_name else "test_value"
    
    def get_all_test_values(self, datatype: str) -> List[Any]:
        """获取指定数据类型的所有测试值"""
        if datatype in self.datatype_mappings:
            return self.datatype_mappings[datatype]['test_values']
        
        # 未知类型返回通用测试值
        return ["test_value", "", "admin", "<script>alert(1)</script>", "'OR 1=1--"]
    
    def get_operations_by_service(self, service_name: str) -> Dict[str, Dict]:
        """获取指定服务的所有操作"""
        service = self.services.get(service_name, {})
        return service.get('operations', {})
    
    def get_all_operations(self) -> Dict[str, Dict]:
        """获取所有操作"""
        return self.operations
    
    def get_library_info(self) -> Dict[str, str]:
        """获取库信息"""
        return self.library_info
    
    def has_operation(self, service_name: str, operation_name: str) -> bool:
        """检查是否存在指定的操作"""
        full_operation_name = f"{service_name}_{operation_name}"
        return full_operation_name in self.operations


# 工厂函数
def create_wsdl_types_parser(types_source: str) -> Optional[WSDLTypesParser]:
    """创建WSDL自定义类型解析器实例"""
    try:
        return WSDLTypesParser(types_source)
    except Exception as e:
        print(f"[!] 创建WSDL自定义类型解析器失败: {e}")
        return None 