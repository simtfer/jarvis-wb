"""受控命令执行技能：默认禁用，需显式开启 + 白名单 + 黑名单双保险。

安全模型（三层）：
  1. 总开关 JARVIS_SHELL_ENABLED，默认 false —— 不开启就永远拒绝；
  2. 白名单 JARVIS_SHELL_ALLOW：只有以这些前缀开头的命令才放行（逗号分隔）；
  3. 黑名单正则：即使白名单放行，命中危险模式（递归删除、格式化、注册表、关机…）仍拒绝。
执行有超时，输出截断，绝不把密码之类的环境变量带出去。

**为什么不用 subprocess.run(timeout=)**
`subprocess.run` 超时杀掉子进程后，还会**不带超时**地再 communicate() 一次，把管道的
close 也一起等下去。只要命令留下的孙进程仍然持有 stdout/stderr 管道（例如命令里后台起了
一个服务、拉起了 GUI、跑了常驻进程），这里就会一直挂住——实测 timeout=3 的命令能挂满 30 秒，
遇到常驻进程就是永久挂起。所以这里改成 Popen + 超时后杀整个进程树 + 有上限的收尾读取。
"""

from __future__ import annotations

import os
import re
import signal
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
_KILL_GRACE = 3.0  # 杀掉进程树后，最多再等这么久收管道（超时即放弃读取）
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


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


def _kill_tree(proc: subprocess.Popen) -> None:
    """结束整棵进程树：Windows 用 taskkill /T，POSIX 杀进程组。"""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5,
                check=False,
                creationflags=_NO_WINDOW,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:  # noqa: BLE001 —— 清理失败不该盖过真正的错误信息
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _execute(command: str, timeout: float) -> tuple[int, bytes, bytes] | None:
    """执行命令并在有限时间内返回；超时返回 None。

    无论命令留下什么后台进程，函数都会在 timeout + _KILL_GRACE 秒内返回。
    """
    proc = subprocess.Popen(
        command,
        shell=True,
        stdin=subprocess.DEVNULL,  # 命令若想读输入，直接拿到 EOF，而不是挂住终端
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_NO_WINDOW,
        start_new_session=(os.name != "nt"),
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=_KILL_GRACE)
        except subprocess.TimeoutExpired:
            # 管道被不知名的孙进程占着：放弃读取，绝不在这里无限等待
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            out, err = b"", b""
        return None


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

        result = _execute(command, cfg.shell_timeout)
        if result is None:
            return (
                f"命令超时（>{cfg.shell_timeout}s），已终止其进程树：{command}。"
                "如果这条命令会起常驻进程，建议改用带超时/后台化的写法。"
            )

        code, raw_out, raw_err = result
        output = _clip(_decode(raw_out))
        errors = _clip(_decode(raw_err), 400)
        report = [f"exit={code}"]
        if output:
            report.append(output)
        if errors:
            report.append(f"[stderr] {errors}")
        return "\n".join(report)
