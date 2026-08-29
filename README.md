# 🚀 daily-arXiv-ai-enhanced

> [!CAUTION]
> 若您所在法域对学术数据有审查要求，谨慎运行本代码；任何二次分发版本必须履行合规审查（包括但不限于原始论文合规性、AI合规性）义务，否则一切法律后果由下游自行承担。

> [!CAUTION]
> If your jurisdiction has censorship requirements for academic data, run this code with caution; any secondary distribution version must remove the entrance accessible to China and fulfill the content review obligations, otherwise all legal consequences will be borne by the downstream.


This innovative tool transforms how you stay updated with arXiv papers by combining automated crawling with AI-powered summarization.


## ✨ Key Features

🎯 **Zero Infrastructure Required**
- Leverages GitHub Actions and Pages - no server needed
- Completely free to deploy and use

🤖 **Smart AI Summarization**
- Daily paper crawling with DeepSeek-powered summaries
- Cost-effective: Only ~0.2 CNY per day

💫 **Smart Reading Experience**
- Personalized paper highlighting based on your interests
- Cross-device compatibility (desktop & mobile)
- Local preference storage for privacy
- Flexible date range filtering

🧩 **SKILL System**
- Plug-and-play skill modules for customizing paper filtering

⚙️ **Easy Preference Export & Integration**
- One-click copy in Settings to export your keywords and authors configuration
- Seamlessly combine exported preferences with SKILL for reproducible and shareable setups

👉 **[Try it now!](https://dw-dengwei.github.io/daily-arXiv-ai-enhanced/)** - No installation required



https://github.com/user-attachments/assets/b25712a4-fb8d-484f-863d-e8da6922f9d7




# How to use
This repo will daily crawl arXiv papers about **cs.CV, cs.GR, cs.CL, cs.AI, cs.CE, cs.GT, cs.IT, cs.LG**, and use **DeepSeek** to summarize the papers in **Chinese**.
If you wish to crawl other arXiv categories, use other LLMs, or other languages, please follow the instructions.
Otherwise, you can watch the video above first and directly use this repo in https://dw-dengwei.github.io/daily-arXiv-ai-enhanced/. Please star it if you like :)

<details>
   <summary> If you want to customize categories, LLMs, or languages, click here.  </summary>

## Instructions

所有运行配置（爬取分类/模型/语言/分组关键词/排除词/飞书标识）都在仓库根目录 **[topics.yaml](./topics.yaml)**，密钥只放 Secrets / ai/.env。

1. Fork this repo to your own account and delete my own information in [buy-me-a-coffee](./buy-me-a-coffee/README.md).
2. Go to: your-own-repo -> Settings -> Secrets and variables -> Actions
3. Go to Secrets. Secrets are encrypted and used for sensitive data
4. Create repository secrets:
   - `OPENAI_API_KEY` (required): your DeepSeek (or other OpenAI-compatible) API key
   - `FEISHU_APP_ID` / `FEISHU_APP_SECRET` (optional): Feishu push credentials, see [飞书推送与知识库](#飞书推送与知识库) below
   - [Optional] `ACCESS_PASSWORD` if you do not wish others to access your page
5. Go to Variables. Create:
   - `EMAIL`: your email for push to GitHub
   - `NAME`: your name for push to GitHub
   - (未设置时 workflow 用 github-actions[bot] 身份提交)
6. Customize [topics.yaml](./topics.yaml): 爬取分类 (arxiv.categories)、模型/语言 (llm)、关注分组与关键词 (groups)、排除词 (exclude_keywords)、飞书配置 (feishu)
7. Go to your-own-repo -> Actions -> arXiv-daily-ai-enhanced, click **Run workflow** to test (约几分钟)
8. Set up GitHub pages: Settings -> Pages. In `Build and deployment`, set `Source="Deploy from a branch"`, `Branch="main", "/(root)"`. Wait for a few minutes, go to https://\<username\>.github.io/\<repo\>/.
   - Pages 需要公开仓库; 仓库设为公开前请确认 ai/.env 未被提交(已在 .gitignore)
9. 定时: 每天 UTC 17:30 自动运行, 修改 `.github/workflows/run.yml` 的 cron 表达式可调整时间

## 飞书推送与知识库

每日结果自动推送飞书群消息, 并沉淀为多维表格(知识库)与知识库文档。需要先创建飞书开放平台自建应用:

1. open.feishu.cn -> 开发者后台 -> 创建**企业自建应用**(如"论文速递"), 在「机器人」页启用机器人能力
2. 「权限管理」申请: `im:message`(发消息)、`bitable:app`(多维表格读写)、`drive:drive`(上传+导入文档)、`docx:document`(创建/编辑文档, 导入任务服务端必需)、`wiki:wiki`(知识库); 可选 `im:chat:readonly`(用于 --list-chats)
3. 「凭证与基础信息」复制 **App ID / App Secret**
4. 「版本管理与发布」-> 创建版本 -> 申请发布(自建应用, 管理员即本人可直接通过)
5. 建飞书群 -> 群设置 -> 群机器人 -> 添加机器人 -> 选择该应用
6. 本地拿 chat_id: `python feishu_sync.py --list-chats`
7. 新建多维表格(命名"论文知识库"), 从 URL 取 `app_token`(feishu.cn/base/xxx) 与 `table_id`(tblxxx); 本地建字段: `python feishu_sync.py --init-table`
8. 知识库中新建目标页面(如"每日速递"), 取其节点 token 填入 topics.yaml 的 `feishu.wiki_node_token`; 如遇权限问题, 用"群组授权法": 建一个含机器人的群并设为知识库管理员
9. 配置:
   - topics.yaml `feishu:` 段: chat_id / app_token / table_id / wiki_node_token / site_url
   - 密钥: 本地写入 ai/.env (gitignored), 部署在 GitHub Secrets 配置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
10. 测试: `python feishu_sync.py --date 2026-08-28 --dry-run`(不调 API 预览) -> `python feishu_sync.py --date 2026-08-28`(真实推送)

脚本用法: `--skip-message` / `--skip-bitable` / `--skip-doc` 分别关闭群消息/表格/文档。

### 常见报错

| 错误 | 原因 | 解决 |
|---|---|---|
| code=230002 | 机器人不在群里 | 把应用机器人加入目标群 |
| code=1254043 | 应用未加入多维表格 | 多维表格右上角把应用添加为协作者 |
| code=1254003/1254004 | app_token/table_id 错误 | 从表格 URL 重新复制 |
| HTTP 403 (wiki) | 知识库权限不足 | 群组授权法或把应用添加为节点协作者 |
| code=1069910 | 导入扩展名不一致 | 确认上传文件名后缀与 file_extension 一致(.md) |
| 未配置提示 | 密钥未设置 | 检查 FEISHU_APP_ID/SECRET, 未配置时自动跳过属正常 |

</details>

# Contributors
Thanks to the following special contributors for contributing code, discovering bugs, and sharing useful ideas for this project!!!
<table>
  <tbody>
    <tr>
      <td align="center" valign="top">
        <a href="https://github.com/JianGuanTHU"><img src="https://avatars.githubusercontent.com/u/44895708?v=4" width="100px;" alt="JianGuanTHU"/><br /><sub><b>JianGuanTHU</b></sub></a><br />
      </td>
      <td align="center" valign="top">
        <a href="https://github.com/Chi-hong22"><img src="https://avatars.githubusercontent.com/u/75403952?v=4" width="100px;" alt="Chi-hong22"/><br /><sub><b>Chi-hong22</b></sub></a><br />
      </td>
      <td align="center" valign="top">
        <a href="https://github.com/chaozg"><img src="https://avatars.githubusercontent.com/u/69794131?v=4" width="100px;" alt="chaozg"/><br /><sub><b>chaozg</b></sub></a><br />
      </td>
      <td align="center" valign="top">
        <a href="https://github.com/quantum-ctrl"><img src="https://avatars.githubusercontent.com/u/16505311?v=4" width="100px;" alt="quantum-ctrl"/><br /><sub><b>quantum-ctrl</b></sub></a><br />
      </td>
      <td align="center" valign="top">
        <a href="https://github.com/Zhao2z"><img src="https://avatars.githubusercontent.com/u/141019403?v=4" width="100px;" alt="Zhao2z"/><br /><sub><b>Zhao2z</b></sub></a><br />
      </td>
      <td align="center" valign="top">
        <a href="https://github.com/eclipse0922"><img src="https://avatars.githubusercontent.com/u/6214316?v=4" width="100px;" alt="eclipse0922"/><br /><sub><b>eclipse0922</b></sub></a><br />
      </td>
    </tr>


  </tbody>
  <tbody>
   <tr>
      <td align="center" valign="top">
        <a href="https://github.com/xuemian168"><img src="https://avatars.githubusercontent.com/u/38741078?v=4" width="100px;" alt="xuemian168"/><br /><sub><b>xuemian168</b></sub></a><br />
      </td>
      <td align="center" valign="top">
        <a href="https://github.com/Lrrrr549"><img src="https://avatars.githubusercontent.com/u/71866027?v=4" width="100px;" alt="Lrrrr549"/><br /><sub><b>Lrrrr549</b></sub></a><br />
      </td>
      <td align="center" valign="top">
        <a href="https://github.com/AinzRimuru"><img src="https://avatars.githubusercontent.com/u/59441476?v=4" width="100px;" alt="AinzRimuru"/><br /><sub><b>AinzRimuru</b></sub></a><br />
      </td>
      <td align="center" valign="top">
        <a href="https://github.com/fengxueguiren"><img src="https://avatars.githubusercontent.com/u/153522370?v=4" width="100px;" alt="fengxueguiren"/><br /><sub><b>fengxueguiren</b></sub></a><br />
      </td>
      <td align="center" valign="top">
        <a href="https://github.com/zerocpp"><img src="https://avatars.githubusercontent.com/u/2630297?v=4" width="100px;" alt="fengxueguiren"/><br /><sub><b>zerocpp</b></sub></a><br />
      </td>
   </tr>
  </tbody>
</table>

# Acknowledgement
We sincerely thank the following individuals and organizations for their promotion and support!!!
<table>
  <tbody>
    <tr>
      <td align="center" valign="top">
        <a href="https://x.com/GitHub_Daily/status/1930610556731318781"><img src="https://pbs.twimg.com/profile_images/1660876795347111937/EIo6fIr4_400x400.jpg" width="100px;" alt="Github_Daily"/><br /><sub><b>Github_Daily</b></sub></a><br />
      </td>
      <td align="center" valign="top">
        <a href="https://x.com/aigclink/status/1930897858963853746"><img src="https://pbs.twimg.com/profile_images/1729450995850027008/gllXr6bh_400x400.jpg" width="100px;" alt="AIGCLINK"/><br /><sub><b>AIGCLINK</b></sub></a><br />
      </td>
      <td align="center" valign="top">
        <a href="https://www.ruanyifeng.com/blog/2025/06/weekly-issue-353.html"><img src="https://avatars.githubusercontent.com/u/905434" width="100px;" alt="阮一峰的网络日志"/><br /><sub><b>阮一峰的网络日志 <br> 科技爱好者周刊 <br> （第 353 期）</b></sub></a><br />
      </td>
      <td align="center" valign="top">
        <a href="https://hellogithub.com/periodical/volume/111"><img src="https://github.com/user-attachments/assets/eff6b6dd-0323-40c4-9db6-444a51bbc80a" width="100px;" alt="《HelloGitHub》第 111 期"/><br /><sub><b>《HelloGitHub》<br> 月刊第 111 期</b></sub></a><br />
      </td>
    </tr>
  </tbody>
</table>


# Star history

[![Stargazers over time](https://starchart.cc/dw-dengwei/daily-arXiv-ai-enhanced.svg?variant=adaptive)](https://starchart.cc/dw-dengwei/daily-arXiv-ai-enhanced)

# Buy me a coffee
[here](./buy-me-a-coffee/README.md)
