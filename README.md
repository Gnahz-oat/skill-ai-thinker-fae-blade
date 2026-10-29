# 安信可FAE之刃

面向新人 FAE 的安信可全产品线助手：根据任务组合官方 Skill、检索官方知识库、补问关键条件，交付排查步骤、示例代码和可转发客户的回复。以 Windows Codex 为主，兼容 Claude Code、Cursor。

**当前覆盖：15 个完整官方 Skill，包含 `board-pins`。** 官方安装页列出的技能及此前已有技能均已包含在同步快照中；开发板引脚仍须核对对应官方规格书。

## 安装

需要 Node.js（用于 npx 安装）、Git、Python 3.11+。只需安装主 Skill，其目录已附带官方文件与资源：

```sh
npx skills add Gnahz-oat/ai-thinker-fae-blade --skill ai-thinker-fae-blade
```

在安装器中选择 Codex、Claude Code 或 Cursor，以及项目级/用户级安装。仅选择主 Skill，避免重复安装嵌套快照中的同名官方技能。安装后在新对话中输入：

```text
使用“安信可FAE之刃”帮我排查：Ai-WB2-12F 的 MQTT 连接失败。
固件版本……，串口日志……，目标是给客户一套排查步骤和回复。
```

Codex 可显式输入 `$ai-thinker-fae-blade`。自动匹配也已启用。首次使用时助手会安装维护脚本依赖 PyYAML（如缺少），检查官方更新，并在需要知识库且缺少连接时为**当前工具**配置 MCP。宿主若要求授权或重新加载，按提示完成；技能不会绕过宿主权限。

手动安装：复制整个 `skills/ai-thinker-fae-blade` 文件夹到客户端技能目录。Codex 当前支持用户级 `~/.agents/skills/`、项目级 `.agents/skills/`；Claude Code 使用 `~/.claude/skills/`；Cursor 使用 `~/.cursor/skills/`。按客户端版本的当前文档确认目录。维护依赖可手动安装：

```sh
python -m pip install -r <已安装技能目录>/scripts/requirements.txt
```

## 工作能力

- 模组选型、型号对比、规格书与开发资源查找。
- AT/SDK 开发、嵌入式 C 编码与代码审查、SCBB 驱动开发、OTA 文件生成。
- 供电/接线/外设问题、串口日志与 BL coredump 分析。
- 全产品线官方资料查询；不在官方 Skill 覆盖内的产品通过知识库支持。
- 针对新人解释必要术语，给可执行步骤与可转发客户的中文回复。

主技能按官方描述选取相关技能，读取完整入口与所需资源，支持组合调用；新增技能不依赖手写白名单。打包资源不会自动安装全部 SDK、GDB、仪器驱动，执行具体任务时按相应官方 Skill 检查依赖。

## MCP：首次使用时自动接入

连接的是安信可官方托管的只读知识库，不在本地部署后端。已有可用连接直接复用；没有连接时从[官方 MCP 页面](https://docs.ai-thinker.com/mcp/)读取当前公开凭据，先验证连接，再备份并写入当前工具的用户级配置。凭据只在用户本机配置中保存，公开仓库没有真实 Token。

若宿主需要重新加载，助手会区分“配置完成”和“当前会话已能调用”。重新加载前可以通过脚本的 `wiki-tools` / `wiki-call` 完成当前只读查询。已禁用的连接、损坏的配置、同名但不同地址的服务不会被自动覆盖。

## 自动更新

本机每个对话首次调用主 Skill 时检查更新，同一天最多联网检查一次。`sync` 可手动立即重试；失败保留旧快照，报告更新失败。成功后生成全技能目录与逐文件 SHA-256，再原子切换当前快照；任务固定使用一个快照。

仓库的 **Sync upstream** 工作流每天运行（北京时间约 09:17，GitHub 可能延迟），也可在 Actions 中手动触发。完整候选版本通过验证和测试后直接提交；来源缺项时工作流失败并保留已发布的快照。公开仓库长期无活动时 GitHub 可能暂停定时任务，需要在 Actions 页面重新启用。

```sh
python skills/ai-thinker-fae-blade/scripts/blade.py sync
python skills/ai-thinker-fae-blade/scripts/blade.py validate
python -m unittest discover -s tests -v
```

同步优先尝试官方 GitHub，再尝试官方 Gitee。必须匹配官方网页目录与已有技能，才能应用；不完整下载、无效 YAML、哈希损坏或上游删除技能都会阻止自动覆盖。原快照保留用于回退。主 Skill 自身的更新通过重新安装本仓库完成。

## 官方来源与许可

- [官方 Skill 安装指南](https://docs.ai-thinker.com/skills/install.html)
- [官方 GitHub 仓库](https://github.com/Ai-Thinker-AIoT/skills)
- [官方 Gitee 镜像](https://gitee.com/Ai-Thinker-Open/skills)
- [官方 MCP 说明](https://docs.ai-thinker.com/mcp/)

本项目由用户个人维护，名称为“安信可FAE之刃”，不代表安信可官方出品。主 Skill 与维护代码采用 MIT；上游原文件及其许可保存在快照 source/ 内，提交 SHA 和来源记录于 catalog.json。
