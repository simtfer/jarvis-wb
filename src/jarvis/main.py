"""贾维斯 TUI 入口：终端对话界面（流式输出 + 工具调用可视化）。

启动:  uv run jarvis   （或 python -m jarvis）
命令:  /help /skills /tools /local /reset /provider /exit
"""

from __future__ import annotations

import sys

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .config import settings
from .core import Brain
from .providers import available_providers
from .providers.base import ProviderError, ToolCall
from .skills import dispatch, list_skills

console = Console()

BANNER = f"""[bold cyan]J.A.R.V.I.S.[/]
[dim]Just A Rather Very Intelligent System · 私人助手框架 v{__version__}[/]"""

HELP = """[bold]可用命令[/]
  /help           显示本帮助
  /skills         查看已挂载的本地技能
  /tools          查看暴露给 LLM 的工具定义
  /local [on|off] 切换"正则快速路径"（命中不走 LLM，默认 on）
  /reset          清空会话记忆
  /provider       查看当前 LLM 提供商与能力
  /exit           退出"""


# ---------- 流式渲染 ----------

def _preview(text: str, limit: int = 90) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


class StreamView:
    """把流式文本增量与工具调用过程实时画到终端上。"""

    def __init__(self, console: Console) -> None:
        self.console = console
        self.live: Live | None = None
        self.buffer: list[str] = []
        self.notes: list[str] = []

    # ---- 回调 ----

    def on_text(self, chunk: str) -> None:
        self.buffer.append(chunk)
        self.refresh()

    def on_tool(self, call: ToolCall, result: str) -> None:
        pending = "".join(self.buffer).strip()
        self.buffer.clear()  # 换一轮：上一轮的话已入记忆，不再重复显示
        if pending:
            self.notes.append(f"[dim italic]“{_preview(pending, 60)}”[/]")
        args = ", ".join(f"{key}={value!r}" for key, value in (call.arguments or {}).items())
        self.notes.append(
            f"[yellow]⚙ 调用工具[/] [bold cyan]{call.name}[/][dim]({args})[/]"
        )
        self.notes.append(f"[dim]   ↳ {_preview(result)}[/]")
        self.refresh()

    # ---- 渲染 ----

    def render(self):
        parts: list = list(self.notes)
        content = "".join(self.buffer)
        if content:
            parts.append(Panel(Markdown(content), title="[cyan]JARVIS[/]", border_style="cyan"))
        elif not parts:
            parts.append(Panel("[dim]······[/]", title="[cyan]JARVIS[/]", border_style="cyan"))
        return Group(*parts)

    def refresh(self) -> None:
        if self.live is not None:
            self.live.update(self.render())


def ask_brain(brain: Brain, user_text: str) -> None:
    """把一句话交给大脑，流式显示过程与结果。"""
    view = StreamView(console)
    try:
        with Live(view.render(), console=console, refresh_per_second=12) as live:
            view.live = live
            reply = brain.think(user_text, on_text=view.on_text, on_tool=view.on_tool)
            live.update(view.render())
    except ProviderError as e:
        console.print(Panel(f"[red]{e}[/]", title="[red]大脑出错[/]", border_style="red"))
        return
    except KeyboardInterrupt:
        console.print("\n[yellow]已打断本轮生成。[/]")
        return
    if not reply:
        console.print("[dim]（模型没有输出内容）[/]")


# ---------- 状态与命令 ----------

def print_status(brain: Brain) -> None:
    info = brain.describe()
    flags = []
    flags.append("[green]流式 on[/]" if info.get("stream") else "[dim]流式 off[/]")
    flags.append("[green]工具 on[/]" if info.get("tools") else "[dim]工具 off[/]")
    flags.append(f"记忆 {info.get('memory', 0)} 条")
    console.print(
        f"[dim]大脑:[/] {info.get('model', info['name'])}  [dim]|[/] "
        f"提供商: {info['name']}  [dim]|[/] " + "  [dim]|[/] ".join(flags)
    )


def print_skills() -> None:
    table = Table(title="本地技能")
    table.add_column("名称", style="cyan")
    table.add_column("说明")
    table.add_column("触发关键词", style="dim")
    for skill in list_skills():
        table.add_row(skill.name, skill.description, "、".join(skill.keywords))
    console.print(table)


def print_tools() -> None:
    table = Table(title="暴露给 LLM 的工具（function calling）")
    table.add_column("工具", style="cyan")
    table.add_column("参数")
    table.add_column("必填", style="green")
    for skill in list_skills():
        params = "、".join(skill.parameters) or "—"
        table.add_row(skill.name, params, "、".join(skill.required) or "—")
    console.print(table)
    console.print("[dim]提示：模型自行决定何时调用；用 /local off 可让所有输入都走 LLM+工具链路。[/]")


def handle_command(brain: Brain, user_text: str, local_mode: list[bool]) -> list[bool]:
    """处理斜杠命令，返回（可能被修改的）状态。"""
    cmd, _, arg = user_text.partition(" ")
    cmd, arg = cmd.lower(), arg.strip().lower()

    if cmd in ("/exit", "/quit"):
        console.print("[dim]贾维斯离线。[/]")
        raise SystemExit(0)
    if cmd == "/help":
        console.print(HELP)
    elif cmd == "/skills":
        print_skills()
    elif cmd == "/tools":
        print_tools()
    elif cmd == "/local":
        if arg in ("on", "off"):
            local_mode[0] = arg == "on"
        console.print(f"[dim]正则快速路径：{'on' if local_mode[0] else 'off'}[/]")
    elif cmd == "/reset":
        brain.reset()
        console.print("[dim]记忆已清空。[/]")
    elif cmd == "/provider":
        print_status(brain)
        console.print(f"[dim]可选提供商: {', '.join(available_providers())}[/]")
    else:
        console.print(f"[yellow]未知命令:[/] {user_text}（/help 查看帮助）")
    return local_mode


def main() -> int:
    cfg = settings.load()
    try:
        brain = Brain()
    except ProviderError as e:
        console.print(f"[red]初始化失败:[/] {e}")
        return 1

    console.print(Panel(BANNER, border_style="cyan"))
    print_status(brain)
    console.print("[dim]输入消息开始对话，/help 查看命令，/exit 退出。[/]\n")

    local_mode = [cfg.local_skills]

    while True:
        try:
            user_text = console.input("[bold green]你 ›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]贾维斯离线。[/]")
            return 0

        if not user_text:
            continue

        if user_text.startswith("/"):
            try:
                handle_command(brain, user_text, local_mode)
            except SystemExit as e:
                return int(e.code or 0)
            continue

        # ---- 正则快速路径：命中即本地执行，零延迟 ----
        if local_mode[0]:
            hit = dispatch(user_text)
            if hit is not None:
                console.print(
                    Panel(Markdown(hit), title="[cyan]JARVIS[/] [dim]· 本地技能[/]",
                          border_style="cyan")
                )
                brain.remember(user_text, hit)
                continue

        # ---- 交给大脑：流式 + 工具调用 ----
        ask_brain(brain, user_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
