# J.A.R.V.I.S. — 私人 AI 助手框架

> Just A Rather Very Intelligent System · v0.4.1

钢铁侠式私人助手的 Python 骨架：**可插拔 LLM 大脑 + 流式输出 + 工具调用 + 长期记忆 + 日程提醒 + 受控命令执行 + TUI**。
离线 Echo 模式即可跑通全链路，接上 API Key 就换成真大脑。

## 快速开始

```bash
cd /d/tmp/jarvis
uv sync                 # 安装依赖到项目 venv

uv run jarvis           # 离线模式直接体验（含流式与工具调用演示）
uv run pytest           # 跑测试（58 项，全部离线）
```

## 接入真实 LLM（任选一家 OpenAI 兼容服务）

```bash
cp .env.example .env    # 然后编辑 .env
```

```ini
JARVIS_PROVIDER=openai_compat
JARVIS_API_KEY=sk-xxxx
JARVIS_BASE_URL=https://api.deepseek.com/v1
JARVIS_MODEL=deepseek-chat
```

## v0.2 新增能力

**① 流式输出** — 模型边生成边显示，不用干等整段回复。

```
你 › 介绍一下你自己
···· 面板实时逐字刷新 ····
```

**② 工具调用（Agent Loop）** — 本地技能被描述成 OpenAI 风格 function 交给模型，
模型自己决定何时调用；执行结果回填消息链后，模型再说人话。

```
你 › 帮我算一下 (12+8)*3/4 是多少
⚙ 调用工具 calculate(expression='(12+8)*3/4')
   ↳ (12+8)*3/4 = 15
┌───────────── JARVIS ─────────────┐
│ （模型把结果组织成自然语言回答）    │
└──────────────────────────────────┘
```

一次 `think()` 的循环：

```
用户输入 → 流式请求模型
    ├─ 模型只是说话 → 文本流给界面 → 写入记忆 → 结束
    └─ 模型要调工具 → 本地执行 → 结果回填 → 再次请求模型
                      （最多 JARVIS_MAX_TOOL_ROUNDS 轮，防死循环）
```

**③ 两条触发路径** — 同一份技能，既能被正则命中直接本地执行（零延迟），也能被 LLM 当工具调用：
TUI 里用 `/local off` 可关掉快速路径，让所有输入都走「LLM + 工具」链路。

**④ 长期记忆（v0.3）** — 会话记忆关机即散，长期记忆落在本地 JSON（`data/memory.json`）：

- 模型可自主存取：`save_memory` / `recall_memory` / `forget_memory` 三个工具；
- **自动召回**：每轮对话前，按关键词相关度把最相关的几条记忆注入 system prompt（RAG-lite），
  主人不用提醒，贾维斯自己想起来；
- 检索零依赖：拉丁词 + 中文字/双字词元重叠打分，记忆量大了再换 sqlite/向量库，接口不变；
- TUI：`/memory` 查看、`/remember <内容>` 直存、`/memory del <编号|关键词>` 删除。

**⑤ 日程提醒（v0.4）** — 中文时间解析（`10分钟后`、`明天9点`、`下午3点半`、ISO），JSON 持久化，
后台线程到点主动打印提醒；离线期间到期的启动时补发。

**⑥ 受控命令执行（v0.4）** — `run_command` 工具，**默认禁用**，三层防线：

1. 总开关 `JARVIS_SHELL_ENABLED`（默认 false）；
2. 白名单前缀 `JARVIS_SHELL_ALLOW`（如 `python,git status,dir`）；
3. 黑名单正则一票否决（递归删除/格式化/注册表/关机/计划任务等），就算进了白名单也拦。

外加超时控制与输出截断。

**⑦ 不会卡死（v0.4.1）** — 工具失败、模型犯轴、进程不退，都不该让界面失去响应：

- **重复调用熔断**：同一轮里模型再次要「同一个工具 + 同一组参数」，直接采用已有结果收口，
  不再重复执行、也不再追加请求（真实模型被拒绝后反复重试的典型行为）；
- **拒绝类结果附禁重试提示**：工具返回"默认关闭 / 不在白名单 / 黑名单 / 执行失败"时，
  写进消息链的文本会加一句"不要重复调用该工具"，界面显示的仍是原文；
- **请求超时可控**：`JARVIS_REQUEST_TIMEOUT`（默认 45s，原先硬编码 120s），
  超时/连不上都会给出中文可读错误，而不是沉默几分钟；
- **命令超时必返回**：`subprocess.run(timeout=)` 在 Windows 上会二次无超时地等管道，
  命令一旦留下后台子进程就会挂住（实测 `timeout=3` 拖到 25~30s，常驻进程则永久挂起）。
  现在改为杀整棵进程树 + 有上限的收尾读取，超时后固定 `timeout + 3s` 内返回；
- **等待可见**：面板会显示「第 N 轮 · 等待模型响应…」，静默超过 6 秒后显示已等待时长，
  工具行附本轮耗时——慢就是慢，但一眼能看出没死。

## 架构

```
src/jarvis/
├── main.py              # TUI 入口：流式渲染、工具调用可视化、斜杠命令
├── config.py            # 配置中心（.env / 环境变量）
├── ltm.py               # 长期记忆：JSON 持久化 + 关键词检索（零外部依赖）
├── scheduler.py         # 提醒调度：中文时间解析 + 持久化 + 后台线程
├── core/
│   ├── brain.py         # 大脑 = 提供商 + 记忆 + 工具编排（Agent Loop + 自动召回）
│   └── memory.py        # 会话记忆：按"轮"存储，裁剪不破坏工具调用链
├── providers/           # 可插拔 LLM 后端
│   ├── base.py          # 事件模型：Chunk / ToolCallsEvent / AssistantTurn
│   ├── echo.py          # 离线演示（流式 + 模拟工具调用，无需 Key）
│   └── openai_compat.py # OpenAI 兼容接口（SSE 流式 + tool_calls 增量拼接）
└── skills/              # 本地技能 = 工具
    ├── base.py          # Skill 基类：patterns（正则） + tool_spec()/invoke()（工具）
    ├── time_skill.py    # get_time：无参数工具
    ├── calc_skill.py    # calculate：带参数工具（AST 白名单求值，不用 eval）
    ├── system_skill.py  # system_info：实时系统状态
    ├── memory_skill.py  # save/recall/forget_memory：长期记忆存取
    ├── reminder_skill.py  # add/list/remove_reminder：日程提醒
    └── shell_skill.py  # run_command：受控命令执行（默认禁用）
```

### 斜杠命令

| 命令 | 作用 |
|---|---|
| `/help` | 帮助 |
| `/skills` | 本地技能列表 |
| `/tools` | 暴露给 LLM 的工具定义 |
| `/local [on\|off]` | 切换正则快速路径 |
| `/memory` | 查看长期记忆（`/memory del <编号\|关键词>` 删除） |
| `/remember <内容>` | 直接存一条长期记忆 |
| `/remind <时间> <内容>` | 设提醒（如 `/remind 10分钟后 喝水`） |
| `/reminders` | 查看待提醒（`del` 子命令取消） |
| `/reset` | 清空会话记忆 |
| `/provider` | 当前提供商与能力 |
| `/exit` | 退出 |

## 怎么扩展

**加一个工具（带参数）**：继承 `Skill`，声明 `description`/`parameters`/`keywords`/`patterns`，实现 `run()`：

```python
class WeatherSkill(Skill):
    name = "get_weather"
    description = "查询指定城市的实时天气。"      # 模型靠这句话决定何时调用
    keywords = ["天气", "weather"]
    patterns = [r"天气"]                          # 快速路径（可留空）
    parameters = {"city": {"type": "string", "description": "城市名"}}
    required = ["city"]

    def run(self, text: str = "", city: str = "", **kwargs) -> str:
        return f"{city} 今天晴，26℃。"
```

在 `skills/__init__.py` 的 `load_builtin_skills()` 里挂载一行即可，
两条路径（正则 / 工具）自动生效。

**加一个新大脑**：继承 `BaseProvider`，实现 `complete()`（`stream()` 可选，默认降级为非流式），用 `@register` 注册。

## 路线图

- [x] v0.1 框架：TUI + 插件式大脑 + 记忆 + 技能系统
- [x] v0.2 流式输出 + 工具调用（LLM 主动调用本地技能）
- [x] v0.3 长期记忆（本地 JSON + 关键词自动召回）
- [x] v0.4 系统控制（日程提醒 + 受控命令执行）
- [x] v0.4.1 韧性加固（熔断/超时/进程树清理，不再卡住）
- [ ] v0.5 语音交互（STT + TTS），喊一声 "Jarvis"
