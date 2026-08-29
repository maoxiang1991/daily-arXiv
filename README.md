# 每日 arXiv 论文速递（SLAM / VIO / LVIO 方向）

每天自动爬取 arXiv 新论文 → 按关注方向的关键词过滤 → LLM 生成中文摘要并分组 → 展示在网页上，同时推送到飞书群、沉淀到飞书知识库。

```
arXiv 爬取(秒级批量) → 关键词过滤 → 去重 → DeepSeek 摘要+分组 → 网页展示
                                                        → 飞书群消息 + 多维表格 + 知识库文档
```

## 一、本地使用

### 1. 安装依赖

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # 安装 uv(一次性)
uv sync                                           # 自动装 Python 3.12 和所有依赖
```

### 2. 配置

所有配置在**一个文件**里：根目录 [topics.yaml](./topics.yaml)

```yaml
arxiv:
  categories: [cs.CV, cs.RO, eess.SY, eess.IV]   # 爬取的 arXiv 分类
llm:
  language: Chinese                               # 摘要语言
  model_name: deepseek-v4-flash                   # 模型
  base_url: https://api.deepseek.com/v1
exclude_keywords: ["anomaly detection", "segmentation"]  # 排除词(可选)
groups:                                           # 关注分组 = 名称 + 关键词
  - name: "SLAM"
    keywords: ["SLAM", "visual odometry", ...]
feishu:                                           # 飞书推送(可选, 见下文)
  chat_id: "oc_xxx"
```

密钥放在 `ai/.env`（已 gitignore，不会上传）：

```
OPENAI_API_KEY="sk-xxx"        # DeepSeek 或其他 OpenAI 兼容 API key(必需)
FEISHU_APP_ID="cli_xxx"        # 飞书(可选)
FEISHU_APP_SECRET="xxx"
```

### 3. 运行

```bash
./run.sh          # 爬取→过滤→AI摘要→Markdown→飞书同步, 全自动
```

新论文只在 arXiv 每天发布一次（UTC 0 点，北京时间早 8 点），发布后运行才能拿到当天论文；重复运行会被去重机制拦下（不重复花钱）。

### 4. 本地预览网页

```bash
python -m http.server 8000
```

把 `js/data-config.js` 里 `getDataBaseUrl` 临时改成返回 `http://localhost:8000`，浏览器打开 http://localhost:8000（预览完改回来，别提交）。

## 二、GitHub 部署（定时任务 + 网页）

1. **推送代码**：`git push origin main`
2. **开启 Actions 写权限**：Settings → Actions → General → Workflow permissions → 选 **Read and write permissions**
3. **配置 Secrets**：Settings → Secrets and variables → Actions → Secrets，添加：
   - `OPENAI_API_KEY`（必需）
   - `FEISHU_APP_ID` / `FEISHU_APP_SECRET`（飞书可选）
   - `ACCESS_PASSWORD`（可选，给网站加访问密码）
4. **Variables**（可选）：`EMAIL`、`NAME`（workflow 提交 git 用的身份，不配则用 bot 身份）
5. **开启 Pages**：仓库设为**公开** → Settings → Pages → Deploy from a branch → `main` / root
6. **手动触发**：Actions → arXiv-daily-ai-enhanced → Run workflow
7. **定时**：默认每天 **UTC 17:30**（北京时间 01:30）自动运行，改 [.github/workflows/run.yml](.github/workflows/run.yml) 里的 cron 表达式可调整时间（cron 用 UTC 时间）

## 三、飞书推送与知识库（可选）

配置后每天自动：**群消息汇总** + **多维表格**（每篇一行）+ **知识库文档**（每日一篇美排版报告）。

### 1. 创建飞书应用

1. 打开 open.feishu.cn → 开发者后台 → 创建**企业自建应用** → 「机器人」页**启用机器人能力**
2. 「权限管理」开通：`im:message`、`bitable:app`、`drive:drive`、`docx:document`、`wiki:wiki`（可选 `im:chat:readonly`）
3. 「凭证与基础信息」复制 **App ID / App Secret**
4. 「版本管理与发布」→ 创建版本 → 申请发布 → 审批通过

### 2. 准备群、表格、知识库

1. 建飞书群 → 群设置 → 群机器人 → 添加机器人 → 选你的应用
2. 新建**多维表格**（如"论文知识库"），URL 中取 `app_token`（`/base/` 后）和 `table_id`（`table=` 后）；表格右上角把应用添加为**可编辑**协作者
3. 知识库新建一个页面（如"首页"，作为每日文档挂载点），URL 中取节点 token（`/wiki/` 后）；知识库设置里把应用（或含机器人的群）添加为**管理员**

### 3. 填写配置并测试

```bash
export FEISHU_APP_ID="cli_xxx" FEISHU_APP_SECRET="xxx"
python feishu_sync.py --list-chats          # 拿 chat_id 填进 topics.yaml
python feishu_sync.py --init-table          # 一次性创建表格字段
python feishu_sync.py --date 2026-08-28 --dry-run   # 预览(不调 API)
python feishu_sync.py --date 2026-08-28     # 真实推送三件套
```

### 常见报错

| 错误 | 原因 | 解决 |
|---|---|---|
| code=230002 | 机器人不在群里 | 把机器人加入目标群 |
| code=1254043 | 应用不是表格协作者 | 表格右上角添加应用(可编辑) |
| code=1254003/1254004 | app_token/table_id 错误 | 从表格 URL 重新复制 |
| HTTP 403 (wiki) | 知识库权限不足 | 把应用/群加为知识库管理员 |
| 未配置 FEISHU_APP_ID | 密钥没设 | 检查 ai/.env 或 GitHub Secrets |

## 四、常用命令速查

| 命令 | 作用 |
|---|---|
| `./run.sh` | 完整流程：爬取→过滤→AI→Markdown→飞书 |
| `python feishu_sync.py --date YYYY-MM-DD` | 手动推送某天到飞书三件套 |
| `python feishu_sync.py --date ... --skip-message/--skip-bitable/--skip-doc` | 关掉某一项 |
| `python feishu_sync.py --init-table` | 重建多维表格字段 |
| `SKIP_KEYWORD_FILTER=1 ./run.sh` | 跳过关键词过滤(爬全量) |
