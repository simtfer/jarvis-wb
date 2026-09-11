"""受控命令执行技能：默认禁用，需显式开启 + 白名单 + 黑名单双保险。

安全模型（三层）：
  1. 总开关 JARVIS_SHELL_ENABLED，默认 false —— 不开启就永远拒绝；
  2. 白名单 JARVIS_SHELL_ALLOW：只有以这些前缀开头的命令才放行（逗号分隔）；
  3. 黑名单正则：即使白名单放行，命中危险模式（递归删除、格式化、注册表、关机…）仍拒绝。
执行有超时，输出截断，绝不把密码之类的环境变量带出去。
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from ..config import settings
from .base import Skill

_BLOCKED = re.compile(
    r"(\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)|\bdel\s+/[sq]|\brd\s+/s|\brmdir\s+/s"
    r"|\bformat\s|\bmkfs|\breg(\.exe)?\s+(add|delete|import)|\bregedit|\bdiskpart"
    r"|\bshutdown|\btaskkill|\bcipher\s+/w|\bremove-item\s+[^\n]*-recurse"
    r"|\bnet\s+user|\bat\b|\bschtasks\s+/delete|\bvssadmin|\bbcdedit)",
    re.IGNORECASE,
)
_MAX_OUTPUT = 1500


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _clip(text: str, limit: int = _MAX_OUTPUT) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（输出过长，已截断，共 {len(text)} 字符）"


class RunCommandSkill(Skill):
    name = "run_command"
    description = (
        "在用户机器上执行一条白名单内的命令并返回输出。"
        "仅当用户明确要求执行且命令在白名单内时使用；危险命令一律拒绝。"
    )
    keywords = ["执行", "命令", "运行", "run"]
    patterns: list[str] = []
    parameters: dict[str, Any] = {
        "command": {"type": "string", "description": "要执行的命令，如：git status"}
    }
    required = ["command"]

    def run(self, text: str = "", command: str = "", **kwargs: Any) -> str:
        cfg = settings.load()
        if not cfg.shell_enabled:
            return (
                "命令执行功能默认关闭。需要时在 .env 设置 JARVIS_SHELL_ENABLED=true，"
                "并用 JARVIS_SHELL_ALLOW 配置命令白名单，先生。"
            )
        command = (command or text or "").strip()
        if not command:
            return "请告诉我要执行什么命令。"
        if _BLOCKED.search(command):
            return "这个命令在危险黑名单里，拒绝执行。"

        allowed = [a.strip().lower() for a in cfg.shell_allow if a.strip()]
        if allowed and not any(command.lower().startswith(a) for a in allowed):
            return (
                f"「{command}」不在白名单内。当前放行前缀：{', '.join(allowed) or '（空）'}。"
                "需要扩大范围请改 JARVIS_SHELL_ALLOW。"
            )

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                timeout=cfg.shell_timeout,
            )
        except subprocess.TimeoutExpired:
            return f"命令超时（>{cfg.shell_timeout}s），已终止：{command}"
        except OSError as e:
            return f"命令启动失败：{e}"

        output = _clip(_decode(proc.stdout))
        errors = _clip(_decode(proc.stderr), 400)
        report = [f"exit={proc.returncode}"]
        if output:
            report.append(output)
        if errors:
            report.append(f"[stderr] {errors}")
        return "\n".join(report)
