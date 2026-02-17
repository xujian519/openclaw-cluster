#!/usr/bin/env python3
"""
OpenClaw 集群系统安装脚本
"""
from setuptools import setup, find_packages
import os

# 读取 README
def read_file(filename):
    here = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(here, filename), encoding='utf-8') as f:
        return f.read()

setup(
    name='openclaw-cluster',
    version='0.1.0-alpha',
    author='xujian',
    author_email='xujian519@gmail.com',
    description='多节点 AI 代理协作平台',
    long_description=read_file('README.md'),
    long_description_content_type='text/markdown',
    url='https://github.com/your-repo/openclaw-cluster',
    packages=find_packages(exclude=['tests', 'tests.*', 'docs', 'scripts']),
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
    ],
    python_requires='>=3.9',
    install_requires=[
        'nats-py>=2.13.0',
        'fastapi>=0.109.0',
        'uvicorn[standard]>=0.27.0',
        'sqlalchemy>=2.0.0',
        'aiosqlite>=0.19.0',
        'pydantic>=2.5.0',
        'pyyaml>=6.0.0',
        'python-dotenv>=1.0.0',
        'structlog>=24.1.0',
    ],
    extras_require={
        'dev': [
            'pytest>=7.4.0',
            'pytest-asyncio>=0.23.0',
            'pytest-cov>=4.1.0',
            'black>=24.1.0',
            'mypy>=1.8.0',
        ],
    },
    entry_points={
        'console_scripts': [
            'openclaw-coordinator=coordinator.main:main',
            'openclaw-worker=worker.main:main',
        ],
    },
)
