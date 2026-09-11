# J.A.R.V.I.S. — 私人 AI 助手框架

> Just A Rather Very Intelligent System · v0.2

钢铁侠式私人助手的 Python 骨架：**可插拔 LLM 大脑 + 流式输出 + 工具调用（function calling）+ 会话记忆 + TUI 对话入口**。
离线 Echo 模式即可跑通全链路，接上 API Key 就换成真大脑。

## 快速开始

```bash
cd /d/tmp/jarvis
uv sync                 # 安装依赖到项目 venv

uv run jarvis           # 离线模式直接体验（含流式与工具调用演示）
uv run pytest           # 跑测试（19 项，全部离线）
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

## 架构

```
src/jarvis/
├── main.py              # TUI 入口：流式渲染、工具调用可视化、斜杠命令
├── config.py            # 配置中心（.env / 环境变量）
├── core/
│   ├── brain.py         # 大脑 = 提供商 + 记忆 + 工具编排（Agent Loop）
│   └── memory.py        # 会话记忆：按"轮"存储，裁剪不破坏工具调用链
├── providers/           # 可插拔 LLM 后端
│   ├── base.py          # 事件模型：Chunk / ToolCallsEvent / AssistantTurn
│   ├── echo.py          # 离线演示（流式 + 模拟工具调用，无需 Key）
│   └── openai_compat.py # OpenAI 兼容接口（SSE 流式 + tool_calls 增量拼接）
└── skills/              # 本地技能 = 工具
    ├── base.py          # Skill 基类：patterns（正则） + tool_spec()/invoke()（工具）
    ├── time_skill.py    # get_time：无参数工具
    ├── calc_skill.py    # calculate：带参数工具（AST 白名单求值，不用 eval）
    └── system_skill.py  # system_info：实时系统状态
```

### 斜杠命令

| 命令 | 作用 |
|---|---|
| `/help` | 帮助 |
| `/skills` | 本地技能列表 |
| `/tools` | 暴露给 LLM 的工具定义 |
| `/local [on\|off]` | 切换正则快速路径 |
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
- [ ] v0.3 长期记忆（本地向量库 / 文件笔记）
- [ ] v0.4 系统控制技能（日程、提醒、执行命令）
- [ ] v0.5 语音交互（STT + TTS），喊一声 "Jarvis"
