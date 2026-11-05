# 提测手册与满分核对清单

> 目标：同时满足基础验收（网站可访问、项目能运行、Qoder 开发可核对、技术结合有效），并在实用价值、完成度、工程质量上拿分。

## 一、提交材料对照（题目要求）

| 提交材料 | 本项目对应位置 | 状态 |
| --- | --- | --- |
| 项目网站网址 | Qoder Sites 发布后的公开链接（见第四节） | 待发布 |
| 代码仓库 | 完整源码，位于赛事仓库 `qoder/knowledge-base/` | 待推送 |
| 运行说明 | `README.md`（环境、依赖版本、接入方式、安装到启动步骤） | 已备 |
| 验证样例 | `docs/validation-sample.md`（初始数据、输入、步骤、预期结果、技术作用记录） | 已备 |
| Qoder 开发记录 | `docs/qoder-dev-log.md`（分环节截图/录屏清单 + 账号 UID） | 待补截图与 UID |
| 使用效果材料（鼓励） | 站点访问统计、使用日志、反馈截图（隐去隐私） | 选做 |

## 二、仓库与分支规范

- 基于官方赛事分支 `2026-competition-ecosystem` 开发；完成私有仓库导入后，你会获得同名分支。
- 项目资产放入仓库的 `qoder/` 目录（本项目放在 `qoder/knowledge-base/`）。
- 参考骨架：<https://github.com/oceanbase/powercontext/tree/2026-competition-ecosystem>

```bash
# 1. 克隆报名登记的团队仓库（地址以报名信息为准），切到赛事分支
git clone <报名仓库地址>
cd <仓库名>
git checkout 2026-competition-ecosystem

# 2. 把本项目整体拷到 qoder/ 目录
mkdir -p qoder
cp -r <本项目目录>/knowledge-base qoder/

# 3. 提交并推送
git add qoder/knowledge-base
git commit -m "feat(qoder): 基于 seekdb 的个人知识检索助手"
git push origin 2026-competition-ecosystem

# 4. 记录提交信息（平台表单需要时填写）
git branch --show-current      # 分支名
git log -1 --format=%H          # 完整 Commit id（40 位）
```

> 仓库如需向评审开放权限：公开仓库直接可访问；私有仓库按平台要求开放只读权限，不要提交真实 API Key、密码等凭据（配置示例用占位值）。

## 三、在 Qoder 中完成开发（满足「使用 Qoder 开发」）

1. 从 [qoder.com](https://qoder.com/zh/) 下载 Qoder 桌面端 / IDE / JetBrains 插件 / CLI 任一，登录参赛**个人账号**。
2. 打开 `qoder/knowledge-base` 目录，把 `docs/qoder-task-prompt.md` 第一段贴进任务框，让 Agent 理解并按需迭代。
3. 过程中审查文件改动与终端命令，确认后 **Accept / 保存**；让 Agent 运行 `python scripts/selftest.py` 并按反馈修到全绿。
4. 按 `docs/qoder-dev-log.md` 分环节留痕：需求拆解、技术选型、编码、调试、自测、站点发布，每步保留对话截图或录屏。
5. 填写 **Qoder 账号 UID**（Qoder → 设置 Settings → 个人资料 Profile → Edit 里复制），用于核对站点归属与使用记录。

> 仅用 Qoder 发布网站、代码却在其他工具编写，不符合本赛道要求；主要功能须由 Qoder 参与完成并留有记录。

## 四、在 Qoder Sites 发布作品站

1. 侧栏 **Sites → Add site**，新任务带 `@sites`；粘贴 `docs/qoder-task-prompt.md` 第二段提示词生成静态站。
2. 预览中验证：搜索可输入、类别过滤生效、三种模式可切换、结果卡片正常；页面包含项目简介、解决的问题、核心功能、演示截图/录屏、代码仓库链接与体验入口。
3. 点 **Publish** 等待 `Published`。
4. **Share → Change access scope → Anyone can access（任何人都可访问）** 并确认公开。
   - 必须用**个人账号**发布；企业版账号无法设置公开访问。
   - 默认「仅自己可见」评委打不开。
5. **Copy link** 复制站点地址。

> 注意：
> - 发布后再改内容，需要**再次点击 Publish** 才会更新线上版本。
> - 评审结束前不要暂停或删除已提交的站点。
> - 免费版 Sites 仅静态站、不提供数据库/存储；真实 seekdb 检索由仓库内 Python 应用完成，站点为内置样例的静态演示。

## 五、提交前满分核对清单

**基础验收（必须全过）**
- [ ] 用无痕浏览器打开站点链接，未登录状态下可正常访问。
- [ ] 按 `README.md` 配置后项目可启动，按 `docs/validation-sample.md` 可体验主要功能。
- [ ] 开发记录能体现主要功能由 Qoder 参与完成，附账号 UID。
- [ ] seekdb 在功能中实际发挥作用：有可核对的检索结果 / 写入记录（见验证样例与开发记录文档）。

**评价维度自查**
- [ ] 实用价值：针对真实痛点，解决方式明确。
- [ ] 完成度与体验：主要流程完整顺畅，功能与描述一致。
- [ ] 技术结合：seekdb 使用合理，对功能有实际帮助。
- [ ] Qoder 开发实践：记录清楚展示 Qoder 在各环节的作用。
- [ ] 工程质量：代码结构清晰、依赖配置齐全、评审可顺利复现。
- [ ] 仓库不含 `.venv`、数据库运行时产物、日志（`.gitignore` 已排除）。

## 六、常见问题排查

### 1. `seekdb_open failed: code=-1` / `OB_IO_ERROR -4009`（fallocate Operation not supported）
当前文件系统不支持 `fallocate`（常见于网络盘、受限目录）。把数据库目录指到本地常规卷：

```bash
export SEEKDB_PATH="$HOME/.knowledge/seekdb.db"
python -m src.cli ingest
```

### 2. 刚写入后向量检索召回为空
seekdb 向量索引异步构建，写入后等待 1–2 秒再检索；代码已内置全量向量余弦精排兜底，空索引期也有结果。

### 3. macOS 安装 seekdb 失败
嵌入式 wheel 要求 **macOS arm64 ≥ 15.6**；系统过低请先升级，或改用 Linux x86_64 环境。

### 4. Windows 环境
嵌入式 seekdb 在 Windows 暂不可用。可用 WSL2 / Linux / macOS 开发；或按题目允许改用 **PowerContext**（见下）。

### 5. 备选：改用 PowerContext（题目允许二选一）
若 seekdb 环境无法就绪，可把核心「记忆/上下文」能力改为接入 OceanBase PowerContext：通过本地 Server、Python Client 或 HTTP/MCP 接口保存并复用用户偏好、任务进展、历史互动。官方文档：<https://powercontext.oceanbase.io/>。仓库结构与 CLI/演示站可复用，仅替换 `src/repository.py` 的存储与检索实现，并在 README 注明使用的是 PowerContext。同时使用两者时，需在文档说明各自分工。

## 七、参考链接

- seekdb 仓库：<https://github.com/oceanbase/seekdb>
- seekdb 文档：<https://docs.seekdb.ai/>
- pyseekdb API：<https://oceanbase.github.io/pyseekdb/api/>
- PowerContext 仓库：<https://github.com/oceanbase/powercontext>
- PowerContext 文档：<https://powercontext.oceanbase.io/>
- Qoder Sites 文档：<https://docs.qoder.com/qoder/sites>
