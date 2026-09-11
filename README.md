# J.A.R.V.I.S. — 私人 AI 助手框架

> Just A Rather Very Intelligent System · v0.1（框架阶段）

钢铁侠式私人助手的 Python 骨架：**可插拔 LLM 大脑 + 会话记忆 + 本地技能系统 + TUI 对话入口**。
当前版本先用离线 Echo 模式跑通全链路，接上 API Key 即可换上真大脑。

## 快速开始

```bash
cd /d/tmp/jarvis
uv sync                 # 安装依赖到项目 venv

uv run jarvis           # 离线模式直接体验
# 或
uv run pytest           # 跑冒烟测试
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

## 架构

```
src/jarvis/
├── main.py             # TUI 入口：命令处理、技能路由、对话循环
├── config.py           # 配置中心（.env / 环境变量）
├── core/
│   ├── brain.py        # 大脑 = 提供商 + 记忆
│   └── memory.py       # 会话记忆（自动裁剪旧轮次）
├── providers/          # 可插拔 LLM 后端
│   ├── base.py         # BaseProvider 抽象接口
│   ├── echo.py         # 离线演示（无需 Key）
│   └── openai_compat.py# OpenAI 兼容接口（DeepSeek/Kimi/通义…）
└── skills/             # 本地技能（正则命中，优先于 LLM）
    ├── base.py         # Skill 基类
    └── time_skill.py   # 示例：报时
```

## 怎么扩展

- **加一个本地技能**：继承 `Skill`，写 `patterns` 正则和 `run()`，在 `skills/__init__.py` 挂载一行。
- **加一个新大脑**：继承 `BaseProvider`，用 `@register` 装饰器（或手动注册）即可被 `/provider` 识别。

## 路线图

- [x] v0.1 框架：TUI + 插件式大脑 + 记忆 + 技能系统
- [ ] v0.2 流式输出、工具调用（让 LLM 主动调用本地技能）
- [ ] v0.3 长期记忆（本地向量库 / 文件笔记）
- [ ] v0.4 系统控制技能（日程、提醒、执行命令）
- [ ] v0.5 语音交互（STT + TTS），喊一声 "Jarvis"
