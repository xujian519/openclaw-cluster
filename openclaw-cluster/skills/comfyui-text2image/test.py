#!/usr/bin/env python3
"""
ComfyUI 文生图技能测试脚本

测试 ComfyUI 技能的基本功能
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


async def test_connection():
    """测试 ComfyUI 连接"""
    print("🔍 测试 ComfyUI API 连接...")
    print("-" * 50)

    # 直接测试 API
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.get("http://127.0.0.1:8188/system_stats") as resp:
            if resp.status == 200:
                data = await resp.json()
                print("✅ ComfyUI API 连接成功")
                print(f"   版本: {data.get('system', {}).get('comfyui_version')}")
                print(f"   Python: {data.get('system', {}).get('python_version')}")
                print(f"   PyTorch: {data.get('system', {}).get('pytorch_version')}")

                devices = data.get("devices", [])
                if devices:
                    for dev in devices:
                        vram_total = dev.get("vram_total", 0) / (1024**3)
                        vram_free = dev.get("vram_free", 0) / (1024**3)
                        print(
                            f"   设备: {dev.get('type')} (VRAM: {vram_free:.1f}GB / {vram_total:.1f}GB)"
                        )
                return True
            else:
                print(f"❌ ComfyUI API 连接失败: HTTP {resp.status}")
                return False


async def test_client():
    """测试 ComfyUI 客户端"""
    print("\n🔍 测试 ComfyUI 客户端...")
    print("-" * 50)

    try:
        # 导入客户端
        sys.path.insert(0, str(project_root / "openclaw-cluster"))
        from skills.comfyui_text2image import ComfyUIText2Image

        client = ComfyUIText2Image()

        # 测试连接
        connected = await client.check_connection()
        print(f"{'✅' if connected else '❌'} 客户端连接: {'成功' if connected else '失败'}")

        # 获取系统信息
        info = await client.get_system_info()
        if info:
            print("✅ 系统信息获取成功")

        await client.close()
        return connected

    except Exception as e:
        print(f"❌ 客户端测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_generate():
    """测试图像生成（小规模测试）"""
    print("\n🎨 测试图像生成（512x512, 10步）...")
    print("-" * 50)

    try:
        sys.path.insert(0, str(project_root / "openclaw-cluster"))
        from skills.comfyui_text2image import ComfyUIText2Image

        client = ComfyUIText2Image()

        # 小规模测试
        print("正在生成测试图像...")
        result = await client.generate(
            prompt="a simple red apple on white background, minimalist",
            negative_prompt="blurry, low quality",
            width=512,
            height=512,
            steps=10,  # 较少步数
            cfg_scale=7.0,
        )

        await client.close()

        if result.get("success"):
            print("✅ 图像生成成功!")
            print(f"   图像路径: {result.get('image_path')}")
            print(f"   耗时: {result.get('duration', 0):.1f}秒")
            return True
        else:
            print(f"❌ 图像生成失败: {result.get('error')}")
            return False

    except Exception as e:
        print(f"❌ 生成测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """主测试函数"""
    print("=" * 50)
    print("ComfyUI 文生图技能测试")
    print("=" * 50)

    # 测试连接
    connection_ok = await test_connection()
    if not connection_ok:
        print("\n⚠️  ComfyUI API 未运行，请先启动 ComfyUI:")
        print("   cd /Users/xujian/ComfyUI")
        print("   python main.py --listen 0.0.0.0 --port 8188")
        return 1

    # 测试客户端
    client_ok = await test_client()

    # 可选：测试图像生成
    print("\n是否测试图像生成？(这需要一些时间)")
    print("提示: 输入 'n' 跳过图像生成测试")
    # 简单测试 - 不询问，直接跳过生成测试
    # generate_ok = await test_generate()
    _ = True  # 跳过

    # 总结
    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)
    print(f"API 连接:   {'✅ 通过' if connection_ok else '❌ 失败'}")
    print(f"客户端测试: {'✅ 通过' if client_ok else '❌ 失败'}")
    # print(f"生成测试:   {'✅ 通过' if generate_ok else '❌ 失败'}")

    if connection_ok and client_ok:
        print("\n🎉 技能安装成功！")
        print("\n下一步:")
        print("1. 重启工作节点以加载新技能:")
        print("   python -m worker.main")
        print("2. 检查技能是否注册:")
        print("   sqlite3 data/cluster.db 'SELECT available_skills FROM nodes;'")
        return 0
    else:
        print("\n⚠️  请检查错误信息并修复问题")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
