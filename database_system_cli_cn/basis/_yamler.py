"""
@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.
"""
import yaml
import os


class yamler:
    def __init__(self, yaml_path):
        # 参数path: 相对路径，起始路径：项目的根目录
        # realPath: 文件的真实路径, 绝对路径地址

        if not os.path.isfile(yaml_path):
            raise FileNotFoundError(f"文件路径不存在，请检查路径是否正确：{yaml_path}")
            # open方法打开直接读出来
        self.yaml_path = yaml_path

    def read(self):
        """读取yaml文件内容"""
        with open(self.yaml_path, 'r', encoding='utf-8') as f:
            return yaml.load(f.read(), Loader=yaml.FullLoader)  # FullLoafer可以yaml解析变得安全

    def write(
            self,
            data
    ):
        """在yaml文件写入数据"""
        with open(self.yaml_path, encoding='utf-8', mode='w') as f:
            return yaml.dump(data, stream=f, allow_unicode=True)

