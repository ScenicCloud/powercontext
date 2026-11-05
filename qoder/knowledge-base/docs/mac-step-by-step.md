# Mac 上从零到提交：手把手大白话指南

> 这份指南假设你用的是 Mac（M 系列芯片）。每一步都写了「做什么、为什么、看到什么算成功」。
> 全程需要你本人操作的只有三类：登录 Qoder、把代码推到比赛仓库、在 Qoder Sites 点发布。

## 开始前，先备齐这几样

1. **Qoder 账号**：去 <https://qoder.com/zh/> 下载 Mac 版客户端并注册/登录（用个人账号，企业账号没法把站点设成公开）。
2. **Python 3.11 或更高版本**：终端敲 `python3 --version` 看版本；没有就去 python.org 装，或用 `brew install python@3.12`。
3. **比赛仓库地址**：报名时登记的那个团队仓库（提测表单里仓库地址是固定的）。
4. 本项目压缩包 `ob_qoder_project.zip`，解压后里面是 `knowledge-base` 整个文件夹。

---

## 第 1 步：把项目放进比赛仓库的 qoder 目录

比赛要求代码基于 `2026-competition-ecosystem` 分支，并且放进仓库的 `qoder/` 目录。

1. 终端里克隆比赛仓库（把下面地址换成你报名的仓库地址）：

```bash
git clone <报名仓库地址>
cd <仓库文件夹名>
git checkout 2026-competition-ecosystem
```

2. 把解压出来的 `knowledge-base` 文件夹，整个拷到仓库的 `qoder/` 目录下，最终长这样：

```
仓库根/
└── qoder/
    └── knowledge-base/
        ├── README.md
        ├── src/
        ├── site/
        ├── docs/
        └── ...
```

> 为什么要放 qoder 目录：赛事骨架按赛道分了 `dify/ gaode/ minimax/ qoder/ stepfun/`，评委按目录找你的作品。

## 第 2 步：在 Qoder 里打开这个项目（满足「用 Qoder 开发」）

1. 打开 Qoder 客户端，登录你的个人账号。
2. 选择打开文件夹，定位到 `qoder/knowledge-base`。
3. 把 `docs/qoder-task-prompt.md` 里**第一段（后端项目）**整段复制，粘贴到 Qoder 对话框发送。
4. Qoder 会读取现有代码、检查结构；你让它补全/修正时，**每一步改动先看一眼它改了什么，再点 Accept（接受/保存）**。
5. 让 Qoder 在终端里跑自测：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/selftest.py
```

- 看到末尾 `全部通过 ✅` 就算成功；如果有 FAIL，把报错贴回给 Qoder 让它修，直到全绿。

> 小白解释：
> - `.venv` 是这个项目专用的「小环境」，依赖只装在这里，不污染系统 Python。
> - `source .venv/bin/activate` 是进入这个小环境；命令行前面出现 `(.venv)` 就说明进对了。
> - `selftest.py` 是自动检查脚本，替你把写入、检索、删除都验一遍。

## 第 3 步：本地命令行自己再点一遍（留作演示证据）

在已激活 `.venv` 的终端里，按 `docs/validation-sample.md` 逐条跑：

```bash
python -m src.cli ingest          # 导入 7 条样例笔记
python -m src.cli count           # 应该显示 7 条
python -m src.cli search "周报" --mode fulltext          # 关键词检索
python -m src.cli search "补码 溢出 判断" --mode vector # 语义检索
python -m src.cli search "混合检索 RRF" --mode hybrid     # 混合检索
python -m src.cli list --category work                  # 只看工作类
```

每一条的终端输出，截图存好——这就是「seekdb 真的在干活」的证据。

## 第 4 步：填开发记录、截图留痕

打开 `docs/qoder-dev-log.md`，按里面的表格填：

- **Qoder 账号 UID**：Qoder → 设置（Settings）→ 个人资料（Profile）→ Edit，复制 Qoder UID 填进去。
- 六个环节各留一张截图：需求拆解、技术选型、编码、调试、自测全绿、Sites 发布。截图能看到你的提问和 Qoder 的产出即可；有姓名手机号就打码。
- 把第 3 步的终端输出贴到「技术结合证据」一节。

## 第 5 步：用 Qoder Sites 发布作品站

1. Qoder 侧栏找 **Sites → Add site**，新任务会自动带上 `@sites`。
2. 把 `docs/qoder-task-prompt.md` 里**第二段（演示站）**整段粘贴发送；它会生成一个静态网页。
3. 右侧预览里自己点一遍：输入关键词能出结果、类别能过滤、三种模式能切换、手机宽度下不乱版。
4. 没问题后点右上角 **Publish（发布）**，等状态变成 `Published`。
5. 点 **Share → Change access scope**，选 **Anyone can access（任何人都可访问）**，确认允许公开。
   - 这一步很关键：默认只有你自己能看，评委打不开。
6. 点 **Copy link** 复制站点网址，先放着，提交时填。

> 注意：发布后如果你又改了网页内容，要**再点一次 Publish** 线上才会更新；评审结束前别把站点暂停或删掉。

## 第 6 步：把代码推回比赛仓库

```bash
cd <仓库根>
git add qoder/knowledge-base
git commit -m "feat(qoder): 基于 seekdb 的个人知识检索助手"
git push origin 2026-competition-ecosystem
```

推完后在仓库网页上确认：`2026-competition-ecosystem` 分支里能看到 `qoder/knowledge-base` 这些文件。

记两个提交信息（表单可能要填）：

```bash
git branch --show-current     # 分支名：2026-competition-ecosystem
git log -1 --format=%H        # 本次提交的完整 Commit id（一长串 40 位）
```

## 第 7 步：填提交表单

到大赛测试平台 Qoder 赛题入口，按要求填：

| 字段 | 填什么 |
| --- | --- |
| 项目网站网址 | 第 5 步复制的 Qoder Sites 公开链接 |
| 代码仓库地址 | 报名登记的团队仓库（平台一般已固定） |
| Qoder 账号 UID | 第 4 步在个人资料里复制的 UID |
| Commit id / Branch | 第 6 步记下的提交哈希和分支名 |

其余材料：运行说明（README）、验证样例（validation-sample.md）、开发记录（qoder-dev-log.md + 截图）按平台要求上传或附在仓库 docs 里。

## 第 8 步：提交前最后自检

- [ ] 用**无痕窗口**打开站点链接，不登录也能正常看到页面。
- [ ] 仓库里代码完整，没有把 `.venv`、数据库文件、日志提交进去（`.gitignore` 已帮你排除）。
- [ ] `selftest.py` 全绿，验证样例能复现。
- [ ] 站点有简介、痛点、核心功能、截图位、仓库链接。
- [ ] 站点可见范围是「任何人可访问」。

## 常见报错（大白话）

- **装依赖时报 seekdb 装不上**：确认 macOS 版本 ≥ 15.6、Python ≥ 3.11；不行就换 Linux 环境，或按 `submit-guide.md` 改用 PowerContext。
- **`seekdb_open failed` / fallocate Operation not supported**：你把数据库放在了不支持的磁盘（比如某些网盘/移动盘）。把数据目录指到本机用户目录：

  ```bash
  export SEEKDB_PATH="$HOME/.knowledge/seekdb.db"
  ```

- **刚导入就搜，向量结果为空**：索引在后台慢慢建，等 1–2 秒再搜；代码里也做了兜底，不会一直空。
- **站点别人打不开**：可见范围没设成公开，回到 Sites → Share 改成 Anyone can access 并重新 Publish。
