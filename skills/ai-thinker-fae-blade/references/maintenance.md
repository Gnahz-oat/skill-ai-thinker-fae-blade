# 使用与更新

本技能随包保存官方 Skill 原文件、脚本、参考资料和 MIT 许可；官方 Skill 位于 `upstream/snapshots/<内容哈希>/source/skills/`。`upstream/active.json` 指定本次使用的快照，快照的 `catalog.json` 给出描述、相对入口与逐文件 SHA-256。

每个对话首次使用调用 `sync --if-due`；24 小时内成功或失败的检查均限流一次，可手动运行 `sync` 立即重试。失败检查后返回 `cached_after_failed_check`，应说明正在使用旧版。同步只更新官方文件，不修改主技能、用户工程或 MCP 设置。

先获取官方安装页面的技能清单，再尝试官方 GitHub（Ai-Thinker-AIoT/skills）和 Gitee（Ai-Thinker-Open/skills）。官方 Skills 首页可能仍指向旧 GitHub 地址，以安装指南为准核对。新版本必须覆盖页面全部技能及此前已有技能，检查 YAML、名称、完整文件复制与哈希后才切换 active.json。上游脚本在同步验证中不会被执行。新增技能自动进入目录，按 description 判断任务适用性；官方删除技能会阻止自动应用，需要人工核实后调整覆盖策略。

当前快照包含 `board-pins`，后续同步仍严格要求完整目录。首次发布缺项的历史来源与状态保存在 coverage.json 和旧快照目录，不能把官方网页简介改写成“官方 Skill”补位。

更新失败不会切换 active.json；旧快照保留可回退。若发现当前文件被人工修改或损坏，完整性验证失败，停止同步，先保存用户修改。脚本同时更新采用排他锁；异常杀死进程后可确认没有同步进程，再删除空的 `upstream/.sync-lock` 目录。

GitHub 每日工作流对完整候选版本验证和执行维护脚本测试，全部通过后才提交。上游当前不完整时工作流失败并保留当前提交，Actions 记录指出缺项。GitHub 定时运行可能延迟，公开仓库长期无活动可能被暂停，必要时在 Actions 页面重新启用。网页恢复后可手动触发 Sync upstream 即时同步。

若 Python 缺失，需要安装 Python 3.11+；维护脚本依赖 PyYAML，官方子技能执行自己的脚本时可能另需对应工具链/GDB/仪器依赖，按所选技能说明安装，不能声称打包即已安装全部开发工具。
