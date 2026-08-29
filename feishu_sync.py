#!/usr/bin/env python3
"""
飞书同步 / Feishu sync: 每日论文推送 + 知识库沉淀
1) 群消息: 每日汇总一条(post 富文本, 分组标签+标题链接+TL;DR)
2) 多维表格(Bitable): 每篇论文一行, 幂等去重
3) 知识库文档: 把 data/{date}.md 导入为云文档并挂载到知识库节点, 幂等(同名跳过)

配置:
- topics.yaml feishu 段: chat_id / app_token / table_id / wiki_node_token / site_url (非敏感标识)
- 环境变量(密钥): FEISHU_APP_ID / FEISHU_APP_SECRET (ai/.env 本地, GitHub Secrets 部署)
未配置密钥时所有功能静默跳过(fail-soft), 不影响爬取主流程。

用法 / Usage:
  python feishu_sync.py --date 2026-08-28               # 默认三件套
  python feishu_sync.py --date ... --skip-message / --skip-bitable / --skip-doc
  python feishu_sync.py --date ... --dry-run            # 只打印将发送/写入的内容
  python feishu_sync.py --list-chats                    # 列出机器人所在群(拿 chat_id)
  python feishu_sync.py --init-table                    # 在指定多维表格中创建字段(一次性)
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent
BASE = "https://open.feishu.cn/open-apis"
DOC_TITLE_PREFIX = "论文速递"

# 多维表格字段定义 / Bitable field definitions
FIELDS = [
    {"field_name": "标题", "type": 1, "property": {}},
    {"field_name": "日期", "type": 5, "property": {"date_formatter": "yyyy-MM-dd"}},
    {"field_name": "链接", "type": 15, "property": {"type": 1}},  # URL 字段, 失败则回退文本
    {"field_name": "分组", "type": 4, "property": None},           # 多选, 选项来自 topics.yaml
    {"field_name": "关键词", "type": 1, "property": {}},
    {"field_name": "TL;DR", "type": 1, "property": {}},
    {"field_name": "方法", "type": 1, "property": {}},
    {"field_name": "arXiv分类", "type": 1, "property": {}},
    {"field_name": "作者", "type": 1, "property": {}},
]


def load_config():
    topics_file = ROOT / "topics.yaml"
    if not topics_file.exists():
        print(f"topics.yaml 不存在 / not found: {topics_file}", file=sys.stderr)
        return {}
    return yaml.safe_load(topics_file.read_text(encoding="utf-8")) or {}


def log(msg):
    print(msg, file=sys.stderr)


def get_tenant_token(app_id, app_secret):
    """换取 tenant_access_token / Get tenant_access_token"""
    r = requests.post(
        f"{BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=15,
    )
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败 / token failed: code={d.get('code')} msg={d.get('msg')}")
    return d["tenant_access_token"]


def api_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}


def load_papers(date_str, language):
    """读取当日 AI 增强数据 / Load the day's AI-enhanced papers"""
    path = ROOT / "data" / f"{date_str}_AI_enhanced_{language}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"数据文件不存在 / data file not found: {path}")
    papers = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            papers.append(json.loads(line))
    return papers


def sort_papers(papers, group_order):
    def key(p):
        groups = p.get("AI", {}).get("groups", []) or []
        ranks = [group_order.index(g) if g in group_order else len(group_order) for g in groups]
        return (min(ranks) if ranks else len(group_order), p.get("title", ""))
    return sorted(papers, key=key)


# ---------------- 1) 群消息 / Group message ----------------

def build_post_content(papers, date_str, group_order, site_url, doc_url=""):
    """构建 post 富文本内容 / Build post (rich text) message content"""
    lines = []
    for p in papers:
        groups = p.get("AI", {}).get("groups", []) or []
        tag = "、".join(groups) if groups else "未分组"
        title = p.get("title", "")
        url = p.get("abs") or f"https://arxiv.org/abs/{p['id']}"
        tldr = (p.get("AI", {}).get("tldr") or "").strip()
        if len(tldr) > 150:
            tldr = tldr[:150] + "…"
        kws = ", ".join(p.get("matched_keywords", []) or [])
        lines.append([{"tag": "a", "text": f"【{tag}】{title}", "href": url}])
        detail = f"    TL;DR: {tldr}" if tldr else ""
        if kws:
            detail += f"  |  关键词: {kws}"
        lines.append([{"tag": "text", "text": detail}])

    footer = []
    if doc_url:
        footer.append([{"tag": "a", "text": "🗂 知识库文档", "href": doc_url}])
    if site_url:
        footer.append([{"tag": "a", "text": "🌐 网站", "href": site_url}])
    if footer:
        lines.append([{"tag": "text", "text": "—"}])
        lines.extend(footer)

    title = f"📚 论文速递 {date_str} · {len(papers)} 篇"
    return {"zh_cn": {"title": title, "content": lines}}


def send_post_message(token, chat_id, content):
    r = requests.post(
        f"{BASE}/im/v1/messages",
        params={"receive_id_type": "chat_id"},
        headers=api_headers(token),
        json={"receive_id": chat_id, "msg_type": "post", "content": json.dumps(content)},
        timeout=15,
    )
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"发送消息失败 / send message failed: code={d.get('code')} msg={d.get('msg')}")


# ---------------- 2) 多维表格 / Bitable ----------------

def get_field_types(token, app_token, table_id):
    r = requests.get(
        f"{BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        params={"page_size": 100},
        headers=api_headers(token),
        timeout=15,
    )
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"获取字段失败 / list fields failed: code={d.get('code')} msg={d.get('msg')}")
    return {f["field_name"]: f["type"] for f in d.get("data", {}).get("items", [])}


def create_field(token, app_token, table_id, field, groups):
    property_ = field["property"]
    if field["type"] == 4:  # 多选: 选项来自分组名 / multi-select options from group names
        property_ = {"options": [{"name": g} for g in groups]}
    body = {"field_name": field["field_name"], "type": field["type"]}
    if property_:
        body["property"] = property_
    r = requests.post(
        f"{BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        headers=api_headers(token),
        json=body,
        timeout=15,
    )
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(d.get("msg"))


def search_today_record_titles(token, app_token, table_id, date_ms):
    """检索当天已有记录的标题(去重用) / Find existing titles for the day (dedup)"""
    body = {
        "filter": {
            "conjunction": "and",
            "conditions": [{"field_name": "日期", "operator": "is", "value": ["ExactDate", date_ms]}],
        },
        "page_size": 500,
    }
    r = requests.post(
        f"{BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
        headers=api_headers(token),
        json=body,
        timeout=15,
    )
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"检索记录失败 / search records failed: code={d.get('code')} msg={d.get('msg')}")
    items = d.get("data", {}).get("items", [])
    return {it["fields"].get("标题") for it in items if isinstance(it["fields"].get("标题"), str)}


def batch_create_records(token, app_token, table_id, records, field_types):
    r = requests.post(
        f"{BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create",
        headers=api_headers(token),
        json={"records": records},
        timeout=30,
    )
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"批量写入失败 / batch_create failed: code={d.get('code')} msg={d.get('msg')}")


def sync_bitable(token, cfg, papers, date_str):
    app_token = (cfg.get("app_token") or "").strip()
    table_id = (cfg.get("table_id") or "").strip()
    if not app_token or not table_id:
        log("⚠️ 未配置 app_token/table_id, 跳过多维表格同步 / skipping bitable (not configured)")
        return
    date_ms = int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    field_types = get_field_types(token, app_token, table_id)
    existing = search_today_record_titles(token, app_token, table_id, date_ms)
    log(f"表格中当日已有记录: {len(existing)} 条 / existing records for {date_str}: {len(existing)}")

    records = []
    for p in papers:
        title = p.get("title", "")
        if title in existing:
            continue
        fields = {
            "标题": title,
            "日期": date_ms,
            "链接": {"link": p.get("abs") or f"https://arxiv.org/abs/{p['id']}", "text": "arXiv"}
            if field_types.get("链接") == 15 else (p.get("abs") or ""),
            "分组": p.get("AI", {}).get("groups", []) or [],
            "关键词": ", ".join(p.get("matched_keywords", []) or []),
            "TL;DR": (p.get("AI", {}).get("tldr") or "")[:500],
            "方法": (p.get("AI", {}).get("method") or "")[:500],
            "arXiv分类": ", ".join(p.get("categories", []) or []),
            "作者": ", ".join(p.get("authors", []) or []),
        }
        records.append({"fields": fields})

    if not records:
        log("✅ 表格无新论文需要写入 / no new records to write")
        return
    batch_create_records(token, app_token, table_id, records, field_types)
    log(f"✅ 多维表格写入 {len(records)} 条记录 / wrote {len(records)} records")


# ---------------- 3) 知识库文档 / Wiki doc ----------------

def get_wiki_space_id(token, node_token):
    r = requests.get(
        f"{BASE}/wiki/v2/spaces/get_node",
        params={"token": node_token},
        headers=api_headers(token),
        timeout=15,
    )
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"获取知识库节点失败 / get_node failed: code={d.get('code')} msg={d.get('msg')}")
    return d["data"]["node"]["space_id"]


def wiki_has_doc(token, space_id, parent_token, title):
    r = requests.get(
        f"{BASE}/wiki/v2/spaces/{space_id}/nodes",
        params={"page_size": 100, "parent_node_token": parent_token},
        headers=api_headers(token),
        timeout=15,
    )
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"列出知识库节点失败 / list nodes failed: code={d.get('code')} msg={d.get('msg')}")
    for item in d.get("data", {}).get("items", []):
        if item.get("title") == title:
            return True
    return False


def import_markdown_doc(token, md_path, title, wiki_node_token):
    """上传 .md → 导入为 docx 云文档 → 挂载到知识库节点 / upload → import as docx → mount to wiki"""
    file_name = md_path.name  # 如 2026-08-28.md, 扩展名须与 file_extension 严格一致
    with open(md_path, "rb") as f:
        r = requests.post(
            f"{BASE}/drive/v1/files/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            data={"file_name": file_name, "parent_type": "explorer", "parent_node": "", "size": str(md_path.stat().st_size)},
            files={"file": (file_name, f, "text/markdown")},
            timeout=60,
        )
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"上传文件失败 / upload failed: code={d.get('code')} msg={d.get('msg')}")
    file_token = d["data"]["file_token"]

    ext = file_name.rsplit(".", 1)[-1]  # md
    r = requests.post(
        f"{BASE}/drive/v1/import_tasks",
        headers=api_headers(token),
        json={"file_extension": ext, "file_token": file_token, "type": "docx", "file_name": title},
        timeout=15,
    )
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"创建导入任务失败 / import_task failed: code={d.get('code')} msg={d.get('msg')}")
    ticket = d["data"]["ticket"]

    doc_token = None
    for _ in range(30):  # 轮询导入结果, 最长约 60 秒 / poll up to ~60s
        time.sleep(2)
        r = requests.get(f"{BASE}/drive/v1/import_tasks/{ticket}", headers=api_headers(token), timeout=15)
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"查询导入任务失败 / poll import failed: {d.get('msg')}")
        result = d.get("data", {}).get("result", {})
        if result:
            doc_token = result.get("token")
            break
    if not doc_token:
        raise RuntimeError(f"导入超时 / import timeout for ticket {ticket}")
    log(f"文档导入完成 / doc imported: {doc_token}")

    if wiki_node_token:
        space_id = get_wiki_space_id(token, wiki_node_token)
        r = requests.post(
            f"{BASE}/wiki/v2/spaces/{space_id}/nodes/move_docs_to_wiki",
            headers=api_headers(token),
            json={"parent_wiki_token": wiki_node_token, "obj_type": "docx", "obj_token": doc_token},
            timeout=15,
        )
        d = r.json()
        if d.get("code") != 0:
            log(f"⚠️ 挂载到知识库失败(文档留在云空间) / mount to wiki failed: code={d.get('code')} msg={d.get('msg')}")
            return None
        log("✅ 文档已挂载到知识库 / doc mounted to wiki")
    return doc_token


def sync_doc(token, cfg, date_str, md_path):
    wiki_node_token = (cfg.get("wiki_node_token") or "").strip()
    title = f"{DOC_TITLE_PREFIX} {date_str}"
    if not md_path.exists():
        log(f"⚠️ Markdown 文件不存在, 跳过文档导入 / md not found, skipping: {md_path}")
        return None
    if wiki_node_token:
        space_id = get_wiki_space_id(token, wiki_node_token)
        if wiki_has_doc(token, space_id, wiki_node_token, title):
            log(f"✅ 知识库已存在「{title}」, 跳过 / doc already exists, skipping")
            return None
    return import_markdown_doc(token, md_path, title, wiki_node_token)


# ---------------- 工具模式 / Utility modes ----------------

def list_chats(token):
    r = requests.get(f"{BASE}/im/v1/chats", params={"page_size": 100}, headers=api_headers(token), timeout=15)
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"列出群聊失败 / list chats failed: code={d.get('code')} msg={d.get('msg')}")
    for item in d.get("data", {}).get("items", []):
        print(f"{item.get('chat_id')}  {item.get('name', '')}")


def init_table(token, cfg, groups):
    app_token = (cfg.get("app_token") or "").strip()
    table_id = (cfg.get("table_id") or "").strip()
    if not app_token or not table_id:
        raise RuntimeError("请先在 topics.yaml 配置 feishu.app_token 与 feishu.table_id")
    existing_types = get_field_types(token, app_token, table_id)
    for field in FIELDS:
        if field["field_name"] in existing_types:
            log(f"字段已存在, 跳过 / field exists, skip: {field['field_name']}")
            continue
        try:
            create_field(token, app_token, table_id, field, groups)
            log(f"✅ 创建字段 / created field: {field['field_name']} (type={field['type']})")
        except Exception as e:
            if field["type"] == 15:  # URL 字段失败 → 回退为文本 / fallback to text
                try:
                    create_field(token, app_token, table_id, {"field_name": field["field_name"], "type": 1, "property": {}}, groups)
                    log(f"✅ 创建字段(回退文本) / created as text: {field['field_name']}")
                    continue
                except Exception as e2:
                    log(f"⚠️ 字段创建失败 / field failed: {field['field_name']}: {e2}")
            else:
                log(f"⚠️ 字段创建失败 / field failed: {field['field_name']}: {e}")


# ---------------- 主流程 / Main ----------------

def main():
    parser = argparse.ArgumentParser(description="飞书同步 / Feishu sync")
    parser.add_argument("--date", type=str, help="日期 YYYY-MM-DD / date (default: today UTC)")
    parser.add_argument("--skip-message", action="store_true", help="不发群消息 / skip group message")
    parser.add_argument("--skip-bitable", action="store_true", help="不同步多维表格 / skip bitable")
    parser.add_argument("--skip-doc", action="store_true", help="不导入知识库文档 / skip wiki doc")
    parser.add_argument("--dry-run", action="store_true", help="只打印将发送/写入的内容, 不调 API / print only, no API calls")
    parser.add_argument("--list-chats", action="store_true", help="列出机器人所在群 / list chats the bot is in")
    parser.add_argument("--init-table", action="store_true", help="创建多维表格字段(一次性) / create bitable fields (once)")
    args = parser.parse_args()

    config = load_config()

    # 自动读取 ai/.env 中的密钥(gitignored) / Auto-load secrets from ai/.env
    env_file = ROOT / "ai" / ".env"
    if env_file.exists():
        try:
            import dotenv
            dotenv.load_dotenv(env_file)
        except ImportError:
            pass

    feishu_cfg = config.get("feishu", {}) or {}
    language = config.get("llm", {}).get("language", "Chinese")
    site_url = (feishu_cfg.get("site_url") or "").strip()
    groups_order = [g["name"] for g in config.get("groups", [])]
    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")

    if args.init_table or args.list_chats or not args.dry_run:
        if not app_id or not app_secret:
            log("⚠️ 未配置 FEISHU_APP_ID/FEISHU_APP_SECRET, 跳过飞书同步 / Feishu not configured, skipping")
            return 0

    token = None
    if app_id and app_secret and not args.dry_run:
        token = get_tenant_token(app_id, app_secret)

    if args.list_chats:
        list_chats(token)
        return 0

    if args.init_table:
        init_table(token, feishu_cfg, groups_order)
        return 0

    # 读取当日论文 / Load papers
    try:
        papers = load_papers(date_str, language)
    except FileNotFoundError as e:
        log(f"⚠️ {e}")
        return 0
    if not papers:
        log(f"⚠️ {date_str} 无论文数据, 跳过 / no papers for {date_str}")
        return 0
    papers = sort_papers(papers, groups_order)
    log(f"论文数 / papers: {len(papers)}")

    # 1) 群消息 / Group message
    if not args.skip_message:
        content = build_post_content(papers, date_str, groups_order, site_url)
        if args.dry_run:
            print("=== 将发送的群消息 / Message to send ===")
            print(content["zh_cn"]["title"])
            for line in content["zh_cn"]["content"]:
                print("  " + " ".join(e.get("text") or e.get("href") for e in line))
        else:
            chat_id = (feishu_cfg.get("chat_id") or "").strip()
            if not chat_id:
                log("⚠️ 未配置 chat_id, 跳过群消息 / skipping message (chat_id not set)")
            else:
                try:
                    send_post_message(token, chat_id, content)
                    log("✅ 群消息已发送 / message sent")
                except Exception as e:
                    log(f"⚠️ 群消息发送失败 / message failed: {e}")

    # 2) 多维表格 / Bitable
    if not args.skip_bitable:
        if args.dry_run:
            print(f"=== 将写入多维表格 {len(papers)} 条(已存在的自动跳过) ===")
            for p in papers:
                print(f"  {p.get('title', '')[:60]} | {p.get('AI', {}).get('groups', [])}")
        else:
            try:
                sync_bitable(token, feishu_cfg, papers, date_str)
            except Exception as e:
                log(f"⚠️ 多维表格同步失败 / bitable sync failed: {e}")

    # 3) 知识库文档 / Wiki doc
    if not args.skip_doc:
        md_path = ROOT / "data" / f"{date_str}.md"
        if args.dry_run:
            print(f"=== 将导入知识库文档: {md_path} (存在: {md_path.exists()}) ===")
        else:
            try:
                sync_doc(token, feishu_cfg, date_str, md_path)
            except Exception as e:
                log(f"⚠️ 知识库文档导入失败 / doc sync failed: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
