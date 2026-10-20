# 十一、Git 管理规范（重要，最常被忽略）

**项目根目录 `/home/agent/.claude/workspace/project` 必须是一个 git 仓库**，否则面板的版本
下拉框会显示「非Git项目」（点它可让面板给你下 `git init` 指令）。

## 一次性初始化

```bash
cd /home/agent/.claude/workspace/project
git config user.name "harness-agent"        # 容器里默认没有 git 身份，不设会 commit 失败
git config user.email "agent@harness.local" # 用 --local（默认），不要 --global
git init
git add -A && git commit -m "Initial commit"
```

## 每次对话后必须提交

```bash
git add -A && git commit -m "描述本次变更"
echo "$(git rev-parse --short HEAD) 描述本次变更" >> logs/commit.txt
```

## 必须维护

- `.gitignore`（至少包含）：
  ```
  logs/
  node_modules/
  .DS_Store
  __pycache__/
  *.log
  .env
  uploads/
  dist/
  build/
  ```
- `logs/commit.txt`：每行一条 `{短commit_id} {标题}`，持续追加：
  ```
  a1b2c3d4 添加用户认证功能
  e5f6g7h8 修复登录页面样式问题
  ```

## 远程仓库命名（硬性）

GitHub 仓库名**必须以 `harness` 开头**，例如 `harness-notes`、`harness-claw`。

```bash
# 自检（不合规会打印提示）
git remote get-url origin | sed -E 's#.*/##; s#\.git$##' | grep -q '^harness' \
  || echo "远程仓库名不合规：必须以 harness 开头"

# 或者直接跑脚本（仓库里有 tools/github/scripts/check_repo_name.sh）
bash tools/github/scripts/check_repo_name.sh

# 已有仓库改名后，把本地远程指过去（GitHub 旧地址会自动重定向，但别依赖它）
git remote set-url origin https://github.com/<owner>/<harness-新名>.git
git remote -v
```

## 常见踩坑

- `fatal: not a git repository` → 还没 `git init`（或不在项目根目录执行）。
- `Please tell me who you are` → 没设身份，按上面第 2、3 行设置。
- 提交前用 `git status --short` 自检；交付里附 `git log --oneline -1` 作为证据。
