# ComfyUI 文生图技能

> 通过本地 ComfyUI 服务器生成高质量 AI 图像

## 技能概述

本技能集成了 ComfyUI - 强大的节点式 Stable Diffusion 图像生成系统，支持：
- 多种 SD 模型（SD1.5、SDXL、SD3 等）
- 自定义工作流
- LoRA 和 ControlNet
- 批量生成

## 系统要求

- ComfyUI 服务运行在 `http://127.0.0.1:8188`
- 推荐使用 GPU 加速（Apple Silicon 或 NVIDIA）
- 至少 8GB RAM

## 快速开始

### 1. 启动 ComfyUI

```bash
cd /Users/xujian/ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

### 2. 测试 API

```bash
curl http://127.0.0.1:8188/system_stats
```

### 3. 基础文生图

```python
from skills.comfyui_text2image import ComfyUI Text2Image

# 创建客户端
client = ComfyUIText2Image()

# 生成图像
result = await client.generate(
    prompt="beautiful mountain landscape at sunset, photorealistic, 8k",
    negative_prompt="blurry, low quality",
    width=1024,
    height=1024,
    steps=20
)

# 保存图像
result.save("output.png")
```

## 功能特性

### 基础文生图

```python
result = await client.generate(
    prompt="a cat wearing a hat, digital art",
    negative_prompt="blurry, low quality",
    width=1024,
    height=1024,
    steps=20,
    cfg_scale=7.0,
    seed=-1  # -1 表示随机种子
)
```

### 批量生成

```python
results = await client.batch_generate(
    prompt="beautiful flower",
    count=4,  # 生成 4 张
    width=512,
    height=512
)
```

### 自定义工作流

```python
# 使用 ComfyUI 导出的工作流 API 格式
workflow = {
    "3": {
        "inputs": {
            "seed": 123456,
            "steps": 20,
            "cfg": 7,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0]
        },
        "class_type": "KSampler"
    },
    # ... 更多节点
}

result = await client.execute_workflow(workflow)
```

## 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `prompt` | str | 必填 | 正向提示词，描述想要生成的图像 |
| `negative_prompt` | str | "" | 负向提示词，描述不想要的内容 |
| `width` | int | 1024 | 图像宽度（需是 8 的倍数） |
| `height` | int | 1024 | 图像高度（需是 8 的倍数） |
| `steps` | int | 20 | 采样步数，越多越精细但越慢 |
| `cfg_scale` | float | 7.0 | CFG 强度，控制对提示词的遵循程度 |
| `seed` | int | -1 | 随机种子，-1 表示随机 |
| `model` | str | None | 指定模型名称 |

## 提示词技巧

### 优质提示词结构

```
[主体], [环境], [风格], [质量修饰词]

示例：
"portrait of a young woman, in a garden, soft natural lighting,
professional photography, 8k, highly detailed"
```

### 常用质量修饰词

- `photorealistic` - 照片级真实
- `8k, highly detailed` - 高细节
- `digital art` - 数字艺术
- `oil painting` - 油画风格
- `cinematic lighting` - 电影级光照

### 负向提示词

```
blurry, low quality, distorted, ugly, bad anatomy,
extra limbs, watermark, text
```

## 高级功能

### ControlNet 支持

```python
result = await client.generate_with_controlnet(
    prompt="beautiful landscape",
    controlnet_model="control_v11p_sd15_canny",
    control_image="input.png"
)
```

### LoRA 加载

```python
result = await client.generate_with_lora(
    prompt="anime character",
    lora_name="anime_style",
    lora_strength=0.8
)
```

## 故障排除

### ComfyUI 连接失败

```bash
# 检查 ComfyUI 是否运行
curl http://127.0.0.1:8188/system_stats

# 启动 ComfyUI
cd /Users/xujian/ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

### 内存不足

- 降低图像分辨率（512x512 而非 1024x1024）
- 减少采样步数（15-20 步）
- 关闭其他应用释放内存

### 图像质量不佳

- 增加 `steps`（25-30）
- 调整 `cfg_scale`（6-10）
- 改进提示词描述
- 尝试不同模型

## 工作流 API

ComfyUI 使用节点式工作流系统。你可以：

1. 在 ComfyUI 界面设计工作流
2. 点击 "Save (API Format)" 导出
3. 使用 `execute_workflow()` 执行

## 参考资源

- [ComfyUI GitHub](https://github.com/comfyanonymous/ComfyUI)
- [ComfyUI 文档](https://docs.comfy.org/)
- [SD 提示词指南](https://prompthero.com/stable-diffusion-prompts)

## 许可证

本技能遵循 MIT 许可证。ComfyUI 遵循 GPL-3.0 许可证。
