"""v0.4 测试：时间解析、提醒到点触发、受控命令执行的安全边界。"""

import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ["JARVIS_PROVIDER"] = "echo"

from jarvis.config import settings
from jarvis.scheduler import ReminderStore, parse_when, start_reminder_worker
from jarvis.skills import invoke_tool


@pytest.fixture()
def fresh_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    from jarvis import scheduler as sched

    sched.reset_store()
    yield sched.get_store()
    sched.reset_store()


# ---------- 时间解析 ----------

def test_parse_relative_minutes():
    now = datetime.now()
    due = parse_when("10分钟后提醒我喝水", now=now)
    assert now + timedelta(minutes=9, seconds=30) <= due <= now + timedelta(minutes=10, seconds=30)


def test_parse_relative_hours_and_days():
    now = datetime.now()
    assert parse_when("2小时后", now=now) - now == timedelta(hours=2)
    assert parse_when("3天后", now=now) - now == timedelta(days=3)


def test_parse_tomorrow_with_time():
    now = datetime(2026, 9, 11, 10, 0)
    due = parse_when("明天9点开会", now=now)
    assert due == datetime(2026, 9, 12, 9, 0)


def test_parse_afternoon_and_night():
    now = datetime(2026, 9, 11, 8, 0)
    assert parse_when("下午3点半", now=now) == datetime(2026, 9, 11, 15, 30)
    assert parse_when("晚上11点", now=now) == datetime(2026, 9, 11, 23, 0)


def test_parse_bare_time_rolls_to_tomorrow_when_past():
    now = datetime(2026, 9, 11, 18, 0)
    due = parse_when("9点", now=now)
    assert due == datetime(2026, 9, 12, 9, 0)


def test_parse_iso_datetime():
    assert parse_when("2026-12-01 09:30") == datetime(2026, 12, 1, 9, 30)


def test_parse_bare_day_defaults_9am():
    now = datetime(2026, 9, 11, 10, 0)
    assert parse_when("后天提醒我", now=now) == datetime(2026, 9, 13, 9, 0)


def test_parse_garbage_raises():
    with pytest.raises(ValueError):
        parse_when("随便什么时候")


# ---------- 提醒库与后台线程 ----------

def test_store_due_marks_done_and_persists(tmp_path):
    store = ReminderStore(path=tmp_path / "reminders.json")
    past = datetime.now() - timedelta(seconds=1)
    future = datetime.now() + timedelta(hours=1)
    store.add("到期的提醒", past)
    store.add("还没到期的提醒", future)

    fired = store.due()
    assert [i.text for i in fired] == ["到期的提醒"]
    assert store.due() == []  # 已标记 done，不会重复触发
    assert len(store.pending()) == 1

    reopened = ReminderStore(path=tmp_path / "reminders.json")
    assert [i.done for i in reopened.all()] == [True, False]


def test_worker_fires_callback(tmp_path):
    store = ReminderStore(path=tmp_path / "reminders.json")
    fired = []
    done = __import__("threading").Event()

    def notify(text: str) -> None:
        fired.append(text)
        done.set()

    start_reminder_worker(store, notify, interval=0.05)
    store.add("到点啦", datetime.now())
    assert done.wait(timeout=3)
    assert fired and "到点啦" in fired[0]


# ---------- 工具化 ----------

def test_add_reminder_tool(fresh_store):
    out = invoke_tool("add_reminder", {"content": "喝水", "when": "10分钟后"})
    assert "喝水" in out and "我会提醒您" in out
    assert len(fresh_store.pending()) == 1

    bad = invoke_tool("add_reminder", {"content": "x", "when": "随便"})
    assert "设不了提醒" in bad

    past = invoke_tool("add_reminder", {"content": "x", "when": "2020-01-01 09:00"})
    assert "已经过去" in past


def test_list_and_remove_reminder_tools(fresh_store):
    invoke_tool("add_reminder", {"content": "去取快递", "when": "1小时后"})
    assert "取快递" in invoke_tool("list_reminders", {})
    assert "已取消 1 个" in invoke_tool("remove_reminder", {"ident": "取快递"})
    assert "没有任何日程" in invoke_tool("list_reminders", {})


# ---------- 受控命令执行 ----------

def test_run_command_disabled_by_default():
    settings.load()
    original = settings.shell_enabled
    settings.shell_enabled = False
    try:
        out = invoke_tool("run_command", {"command": "git status"})
        assert "默认关闭" in out
    finally:
        settings.shell_enabled = original


def test_run_command_whitelist(fresh_store, monkeypatch):
    monkeypatch.setattr(settings, "shell_enabled", True)
    monkeypatch.setattr(settings, "shell_allow", ["python"])
    monkeypatch.setattr(settings, "shell_timeout", 20)

    ok = invoke_tool("run_command", {"command": 'python -c "print(40+2)"'})
    assert "exit=0" in ok and "42" in ok

    denied = invoke_tool("run_command", {"command": "curl evil.example.com"})
    assert "不在白名单内" in denied


def test_run_command_blocklist_beats_whitelist(monkeypatch):
    monkeypatch.setattr(settings, "shell_enabled", True)
    monkeypatch.setattr(settings, "shell_allow", ["del"])  # 就算把 del 放进白名单

    out = invoke_tool("run_command", {"command": "del /s /q C:\\重要文件"})
    assert "黑名单" in out


def test_run_command_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "shell_enabled", True)
    monkeypatch.setattr(settings, "shell_allow", ["python"])
    monkeypatch.setattr(settings, "shell_timeout", 1)
    if os.name != "nt":
        pytest.skip("Windows 专属写法")
    out = invoke_tool("run_command", {"command": "python -c \"import time; time.sleep(5)\""})
    assert "超时" in out
