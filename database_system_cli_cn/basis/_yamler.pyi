from typing import overload


class yamler:
    @overload
    def __init__(self, yaml_path): ...
    @overload
    def read(self) -> object: ...
    @overload
    def writer(self, path: str): ...
