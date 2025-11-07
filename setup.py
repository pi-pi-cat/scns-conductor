"""
SCNS-Conductor 安装配置
"""
from setuptools import setup, find_packages

setup(
    name="scns-conductor",
    version="1.0.0",
    description="轻量级作业调度系统",
    author="SCNS-Conductor Team",
    author_email="",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        # 从 requirements.txt 读取
    ],
    entry_points={
        "console_scripts": [
            "scns-api=api.main:main",
            "scns-worker=worker.main:main",
        ],
    },
)

