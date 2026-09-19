# Git 协作与环境重建

## 仓库范围

frontend 与 backend 在同一 Git 仓库内管理，不分别初始化嵌套仓库。原 iCan 目录作为历史备份；后续改动集中在 InsightCheck。

提交源码、迁移、测试、依赖声明和技术文档。不要提交虚拟环境、node_modules、缓存、账号密钥、体检原始数据和本地数据库。首次环境建立按根目录 README 执行；Python 虚拟环境必须重新创建，不能复制旧电脑的 .venv。

## 日常流程

采用短期任务分支：一个分支承载一项可验收功能，负责人在 PR 中标明。不要固定复用个人 dev-* 分支，也不要将整个阶段放入一个 feat/v2-* 分支。完整分工见 [2.0 任务书](TEAM_TASKS_V2.md)。

首次克隆后进入仓库：

```powershell
git clone https://github.com/MrJerry-git/InsightCheck.git
cd InsightCheck
```

每次开始新任务，先确认当前未提交工作已提交或妥善保存，再从最新主分支创建任务分支（以下名称是示例）：

```powershell
git status
git fetch origin
git switch --no-track -c feat/report-import origin/main
```

新功能用 feat/，修复用 fix/，文档用 docs/。不同任务使用不同名称；不要删除已有同名分支来强行执行示例。

完成一个范围明确的改动后，执行相关测试，检查差异，再提交：

```powershell
git status
git diff
git add <本次修改的文件>
git diff --cached
git commit -m "Implement report import"
git push -u origin feat/report-import
```

在 GitHub 创建 Pull Request，写明解决的问题、验证结果及仍未完成的部分。主分支保留经过检查的版本。数据与实验指标必须标明来源和验证状态，不能把演示输出作为实际研究结论。

PR 中注明负责人、任务编号、接口依赖和复现步骤。在审分支只追加该任务的修改；独立任务另建分支。依赖接口未完成时使用 Draft PR，不能以开发假数据当作功能完成。不得提交秘密、病例或数据库。

开发中需要同步已合并的更新时，先保存当前工作，在自己的任务分支执行：

```powershell
git fetch origin
git merge origin/main
```

理解并解决冲突后，重新验证受影响功能；不强制推送共享分支。默认用 Create a merge commit 合并 PR。自己的 PR 不能自我批准；管理员例外须在实际审查完成后明确使用。

## 合并后的分支清理

先在 GitHub 确认 PR 已合并，确认任务分支没有新增未合并提交、未提交文件或被其他任务依赖，再删除任务分支。以下命令中的分支名必须替换为刚合并的那条任务分支：

```powershell
git fetch origin
git switch main
git merge --ff-only origin/main
git log origin/main..feat/report-import --oneline
```

最后一条输出应为空，且工作目录应干净。如果主分支不能快进或仍有独有提交，先检查原因，不强制重置或删除。确认后执行：

```powershell
git push origin --delete feat/report-import
git branch -d feat/report-import
git fetch --prune origin
```

如果已在 GitHub 点击 Delete branch，无需再次执行远程删除。下一任务从最新 origin/main 建立新分支。上述祖先检查按默认 merge commit 流程编写；如果采用 squash/rebase，出现独有提交时需核对内容，不能直接强制删除。

现有 dev-* 等历史分支逐一核对后清理，不批量删除。保留未合并工作和原 PR，必要时迁移到任务分支，验证后关闭被替代 PR；不能因新规划丢弃代码。
