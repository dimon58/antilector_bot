import operator
from functools import reduce

import torch


def is_cuda(device: torch.device) -> bool:
    return device.type == "cuda"


def get_byte_size_of_tensor(tensor: torch.Tensor) -> float:
    """
    Возвращает размер данных, хранящихся в тензоре в байтах
    """
    return reduce(operator.mul, tensor.size(), 1) * tensor.itemsize
