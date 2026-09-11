"""系统信息技能：报告本机运行环境，演示"无需模型也能给出实时数据"。

全部使用标准库，不引入额外依赖。
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from .base import Skill


def _memory_line() -> str | None:
    """Windows 下用 ctypes 读物理内存；其他平台尽力而为。"""
    try:
        if sys.platform == "win32":
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MemoryStatusEx()
            stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total = stat.ullTotalPhys / 1024**3
                avail = stat.ullAvailPhys / 1024**3
                return f"内存：{avail:.1f} GB 可用 / 共 {total:.1f} GB（已用 {stat.dwMemoryLoad}%）"
        else:
            page = 4096
            total = os.sysconf("SC_PHYS_PAGES") * page / 1024**3
            avail = os.sysconf("SC_AVPHYS_PAGES") * page / 1024**3
            return f"内存：{avail:.1f} GB 可用 / 共 {total:.1f} GB"
    except Exception:  # 环境探测失败不值得报错
        return None


def _disk_line(path: Path) -> str | None:
    try:
        usage = shutil.disk_usage(path)
        anchor = path.anchor or "/"
        return (
            f"磁盘 {anchor}：{usage.free / 1024**3:.1f} GB 可用 / "
            f"共 {usage.total / 1024**3:.1f} GB（已用 {usage.used / usage.total * 100:.0f}%）"
        )
    except OSError:
        return None


class SystemInfoSkill(Skill):
    name = "system_info"
    description = "获取本机运行环境信息：操作系统、CPU 核数、内存与磁盘占用。"
    keywords = ["系统", "内存", "磁盘", "机器", "主机", "配置", "system"]
    patterns = [
        r"(系统|机器|主机|电脑).{0,6}(信息|状态|配置|情况)",
        r"\bsystem\b",
    ]
    parameters: dict[str, Any] = {}
    required: list[str] = []

    def run(self, text: str = "", **kwargs: Any) -> str:
        lines = [
            f"操作系统：{platform.system()} {platform.release()} ({platform.machine()})",
            f"CPU：{platform.processor() or '未知'} · {os.cpu_count()} 核",
            f"Python：{platform.python_version()} @ {sys.executable}",
        ]
        for extra in (_memory_line(), _disk_line(Path.cwd())):
            if extra:
                lines.append(extra)
        lines.append(f"当前工作目录：{Path.cwd()}")
        return "\n".join(lines)
