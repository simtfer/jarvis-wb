"""贾维斯 TUI 入口：终端对话界面。

启动:  uv run jarvis   （或 python -m jarvis）
命令:  /help /skills /reset /provider /exit
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from .config import settings
from .core import Brain
from .providers import available_providers
from .providers.base import ProviderError
from .skills import dispatch, list_skills, load_builtin_skills

console = Console()

BANNER = """[bold cyan]J.A.R.V.I.S.[/]
[dim]Just A Rather Very Intelligent System · 私人助手框架 v0.1[/]"""

HELP = """[bold]可用命令[/]
  /help     显示本帮助
  /skills   查看已挂载的本地技能
  /reset    清空会话记忆
  /provider 查看当前 LLM 提供商
  /exit     退出"""


def _print_reply(text: str) -> None:
    console.print(Panel(Markdown(text), title="[cyan]JARVIS[/]", border_style="cyan"))


def _print_status(brain: Brain) -> None:
    info = brain.provider.describe()
    console.print(f"[dim]大脑:[/] {info.get('model', info['name'])}  [dim]|[/] "
                  f"提供商: {info['name']}  [dim]|[/] "
                  f"记忆: {len(brain.memory)} 条消息")


def main() -> int:
    cfg = settings.load()
    load_builtin_skills()

    try:
        brain = Brain()
    except ProviderError as e:
        console.print(f"[red]初始化失败:[/] {e}")
        return 1

    console.print(Panel(BANNER, border_style="cyan"))
    _print_status(brain)
    console.print("[dim]输入消息开始对话，/help 查看命令，/exit 退出。[/]\n")

    while True:
        try:
            user_text = console.input("[bold green]你 ›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]贾维斯离线。[/]")
            return 0

        if not user_text:
            continue

        # ---- 斜杠命令 ----
        if user_text.startswith("/"):
            cmd = user_text.lower()
            if cmd in ("/exit", "/quit"):
                console.print("[dim]贾维斯离线。[/]")
                return 0
            if cmd == "/help":
                console.print(HELP)
            elif cmd == "/skills":
                table = Table(title="本地技能", show_lines=False)
                table.add_column("名称")
                table.add_column("说明")
                for s in list_skills():
                    table.add_row(s.name, s.description)
                console.print(table)
            elif cmd == "/reset":
                brain.reset()
                console.print("[dim]记忆已清空。[/]")
            elif cmd == "/provider":
                _print_status(brain)
                console.print(f"[dim]可选提供商: {', '.join(available_providers())}[/]")
            else:
                console.print(f"[yellow]未知命令:[/] {user_text}（/help 查看帮助）")
            continue

        # ---- 本地技能优先 ----
        skill_result = dispatch(user_text)
        if skill_result is not None:
            _print_reply(skill_result)
            brain.memory.add("user", user_text)
            brain.memory.add("assistant", skill_result)
            continue

        # ---- 交给大脑（LLM）----
        try:
            with console.status("[cyan]贾维斯思考中…[/]"):
                reply = brain.think(user_text)
            _print_reply(reply)
        except ProviderError as e:
            console.print(f"[red]大脑出错:[/] {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
