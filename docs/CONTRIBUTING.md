# Git 协作与环境重建

## 仓库范围

frontend 与 backend 在同一 Git 仓库内管理，不分别初始化嵌套仓库。原 iCan 目录作为历史备份；后续改动集中在 InsightCheck。

提交源码、迁移、测试、依赖声明和技术文档。不要提交虚拟环境、node_modules、缓存、账号密钥、体检原始数据和本地数据库。首次环境建立按根目录 README 执行；Python 虚拟环境必须重新创建，不能复制旧电脑的 .venv。

## 日常流程

首次克隆后进入仓库，建立独立工作分支：

```powershell
git clone https://github.com/MrJerry-git/InsightCheck.git
cd InsightCheck
git switch -c feat/risk-baseline
```

完成一个范围明确的改动后，执行相关测试，检查差异，再提交：

```powershell
git status
git diff
git add <本次修改的文件>
git diff --cached
git commit -m "Implement risk baseline"
git push -u origin feat/risk-baseline
```

在 GitHub 创建 Pull Request，写明解决的问题、验证结果及仍未完成的部分。主分支保留经过检查的版本。数据与实验指标必须标明来源和验证状态，不能把演示输出作为实际研究结论。
