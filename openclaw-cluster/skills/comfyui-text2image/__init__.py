"""
ComfyUI 文生图技能

提供与本地 ComfyUI 服务器的集成，支持文本到图像生成
"""
from .comfyui_client import ComfyUIText2Image, generate_image

__all__ = [
    "ComfyUIText2Image",
    "generate_image",
]

__version__ = "1.0.0"
__author__ = "xujian"
