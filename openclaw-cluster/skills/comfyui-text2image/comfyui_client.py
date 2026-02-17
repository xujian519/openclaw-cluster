"""
ComfyUI 文生图技能实现

与本地 ComfyUI 服务器通信，执行文本到图像生成任务
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp


class ComfyUIText2Image:
    """
    ComfyUI 文生图客户端

    通过 ComfyUI API 执行图像生成任务
    """

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:8188",
        default_model: Optional[str] = None,
    ):
        """
        初始化 ComfyUI 客户端

        Args:
            api_url: ComfyUI API 地址
            default_model: 默认使用的模型名称
        """
        self.api_url = api_url.rstrip("/")
        self.default_model = default_model
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP 会话"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=300)  # 5分钟超时
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        """关闭客户端"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def check_connection(self) -> bool:
        """
        检查 ComfyUI 服务连接状态

        Returns:
            是否连接成功
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self.api_url}/system_stats") as resp:
                return resp.status == 200
        except Exception:
            return False

    async def get_system_info(self) -> Optional[Dict[str, Any]]:
        """
        获取 ComfyUI 系统信息

        Returns:
            系统信息字典
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self.api_url}/system_stats") as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
        return None

    async def get_models(self) -> Dict[str, List[str]]:
        """
        获取可用模型列表

        Returns:
            模型分类字典 {
                "checkpoints": ["model1.safetensors", ...],
                "loras": ["lora1.safetensors", ...],
                ...
            }
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self.api_url}/object_info") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = {}

                    # 提取不同类型的模型
                    for node_id, node_data in data.items():
                        if "input" in node_data:
                            for input_name, input_data in node_data["input"].items():
                                if input_name in ["ckpt_name", "lora_name"]:
                                    if input_name not in models:
                                        models[input_name] = []
                                    if isinstance(input_data.get("list"), list):
                                        models[input_name].extend(input_data["list"])

                    return models
        except Exception:
            pass
        return {}

    def _create_basic_workflow(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        cfg_scale: float = 7.0,
        seed: int = -1,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        创建基础文生图工作流

        Args:
            prompt: 正向提示词
            negative_prompt: 负向提示词
            width: 图像宽度
            height: 图像高度
            steps: 采样步数
            cfg_scale: CFG 强度
            seed: 随机种子
            model: 模型名称

        Returns:
            ComfyUI 工作流字典
        """
        # 使用当前时间戳作为种子（如果 seed=-1）
        if seed == -1:
            seed = int(datetime.now().timestamp() * 1000) % 2147483647

        # 基础 KSampler 工作流
        workflow = {
            "3": {
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg_scale,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
                "class_type": "KSampler",
            },
            "4": {
                "inputs": {
                    "ckpt_name": model or self.default_model or "model.safetensors",
                },
                "class_type": "CheckpointLoaderSimple",
            },
            "5": {
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": 1,
                },
                "class_type": "EmptyLatentImage",
            },
            "6": {
                "inputs": {
                    "text": prompt,
                    "clip": ["4", 1],
                },
                "class_type": "CLIPTextEncode",
            },
            "7": {
                "inputs": {
                    "text": negative_prompt,
                    "clip": ["4", 1],
                },
                "class_type": "CLIPTextEncode",
            },
            "8": {
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2],
                },
                "class_type": "VAEDecode",
            },
            "9": {
                "inputs": {
                    "filename_prefix": "ComfyUI",
                    "images": ["8", 0],
                },
                "class_type": "SaveImage",
            },
        }

        return workflow

    async def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        cfg_scale: float = 7.0,
        seed: int = -1,
        model: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        生成图像

        Args:
            prompt: 正向提示词
            negative_prompt: 负向提示词
            width: 图像宽度（需是 8 的倍数）
            height: 图像高度（需是 8 的倍数）
            steps: 采样步数
            cfg_scale: CFG 强度
            seed: 随机种子
            model: 模型名称
            output_dir: 输出目录

        Returns:
            生成结果 {
                "success": bool,
                "image_path": str,
                "prompt": str,
                "seed": int,
                "duration": float,
                "error": str (如果失败)
            }
        """
        start_time = datetime.now()

        try:
            # 创建工作流
            workflow = self._create_basic_workflow(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                steps=steps,
                cfg_scale=cfg_scale,
                seed=seed,
                model=model,
            )

            # 提交工作流
            result = await self.execute_workflow(workflow)

            if result.get("success"):
                duration = (datetime.now() - start_time).total_seconds()
                result["duration"] = duration
                result["prompt"] = prompt
                result["seed"] = seed

            return result

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "prompt": prompt,
            }

    async def batch_generate(
        self,
        prompt: str,
        count: int = 4,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        cfg_scale: float = 7.0,
    ) -> List[Dict[str, Any]]:
        """
        批量生成图像

        Args:
            prompt: 正向提示词
            count: 生成数量
            negative_prompt: 负向提示词
            width: 图像宽度
            height: 图像高度
            steps: 采样步数
            cfg_scale: CFG 强度

        Returns:
            生成结果列表
        """
        tasks = []
        for i in range(count):
            task = self.generate(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                steps=steps,
                cfg_scale=cfg_scale,
                seed=-1,  # 每个图像随机种子
            )
            tasks.append(task)

        return await asyncio.gather(*tasks)

    async def execute_workflow(
        self,
        workflow: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        执行自定义工作流

        Args:
            workflow: ComfyUI 工作流字典

        Returns:
            执行结果
        """
        try:
            session = await self._get_session()

            # 获取队列状态
            async with session.get(f"{self.api_url}/queue") as resp:
                if resp.status == 200:
                    queue_data = await resp.json()
                    # 检查是否需要等待队列
                    if queue_data.get("queue_running", 0) > 0:
                        await asyncio.sleep(1)

            # 提交工作流到队列
            prompt_data = {"prompt": workflow}
            async with session.post(
                f"{self.api_url}/prompt",
                json=prompt_data,
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return {
                        "success": False,
                        "error": f"提交工作流失败: {text}",
                    }

                result = await resp.json()
                prompt_id = result.get("prompt_id")

                if not prompt_id:
                    return {
                        "success": False,
                        "error": "未获取到 prompt_id",
                    }

            # 等待生成完成
            image_path = await self._wait_for_completion(prompt_id)

            if image_path:
                return {
                    "success": True,
                    "image_path": image_path,
                    "prompt_id": prompt_id,
                }
            else:
                return {
                    "success": False,
                    "error": "图像生成超时或失败",
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    async def _wait_for_completion(
        self,
        prompt_id: str,
        timeout: int = 300,
    ) -> Optional[str]:
        """
        等待任务完成

        Args:
            prompt_id: 任务 ID
            timeout: 超时时间（秒）

        Returns:
            图像路径，如果失败返回 None
        """
        start_time = datetime.now()

        while True:
            # 检查超时
            if (datetime.now() - start_time).total_seconds() > timeout:
                return None

            try:
                session = await self._get_session()

                # 检查历史记录
                async with session.get(f"{self.api_url}/history/{prompt_id}") as resp:
                    if resp.status == 200:
                        history = await resp.json()
                        if prompt_id in history:
                            # 任务完成
                            data = history[prompt_id]
                            outputs = data.get("outputs", {})

                            # 查找生成的图像
                            for node_id, node_output in outputs.items():
                                if "images" in node_output:
                                    images = node_output["images"]
                                    if images:
                                        image_info = images[0]
                                        filename = image_info.get("filename")
                                        subfolder = image_info.get("subfolder", "")
                                        image_type = image_info.get("type", "output")

                                        if filename:
                                            # 构建图像路径
                                            if subfolder:
                                                path = f"view?filename={filename}&subfolder={subfolder}&type={image_type}"
                                            else:
                                                path = f"view?filename={filename}&type={image_type}"

                                            return f"{self.api_url}/{path}"

                # 等待一段时间后再检查
                await asyncio.sleep(1)

            except Exception:
                await asyncio.sleep(2)
                continue


# 便捷函数
async def generate_image(
    prompt: str,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg_scale: float = 7.0,
    seed: int = -1,
    api_url: str = "http://127.0.0.1:8188",
) -> Dict[str, Any]:
    """
    便捷函数：生成单张图像

    Args:
        prompt: 正向提示词
        negative_prompt: 负向提示词
        width: 图像宽度
        height: 图像高度
        steps: 采样步数
        cfg_scale: CFG 强度
        seed: 随机种子
        api_url: ComfyUI API 地址

    Returns:
        生成结果
    """
    client = ComfyUIText2Image(api_url=api_url)
    try:
        result = await client.generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
        )
        return result
    finally:
        await client.close()
