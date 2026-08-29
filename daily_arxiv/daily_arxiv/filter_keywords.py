#!/usr/bin/env python3
"""
按关键词过滤论文 / Filter papers by keywords
- 在 标题+摘要 中命中任一关键词的论文被保留 / Papers hitting any keyword in title+summary are kept
- 全大写关键词(如 SLAM、VIO)按大小写敏感匹配,避免误匹配(如 previous/obvious 中的 vio) / Uppercase keywords match case-sensitively
- 其余关键词不区分大小写 / Other keywords are case-insensitive
- 关键词来源(唯一配置源): 仓库根目录 topics.yaml 的全部分组关键词并集, 缺失时回退内置默认列表
  Keyword source (single source): union of topics.yaml group keywords; built-in defaults as fallback
- 每篇保留的论文会写入 matched_keywords 字段, 记录命中的关键词 / Kept papers get a matched_keywords field
- 退出码: 0=过滤成功 1=无论文命中(文件不变) 2=参数错误 / Exit codes: 0=success 1=no match(file unchanged) 2=bad args
"""
import json
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

DEFAULT_KEYWORDS = [
    "SLAM", "VIO", "LVIO", "IMU",
    "odometry",
    "simultaneous localization and mapping",
    "visual-inertial",
    "lidar-inertial",
    "inertial odometry",
    "multi-sensor fusion",
    "sensor fusion",
    "loop closure",
    "bundle adjustment",
    "pose graph",
    "factor graph",
    "point cloud registration",
    "visual localization",
    "relocalization",
    "place recognition",
]


def load_keywords():
    # 从 topics.yaml 取所有分组关键词的并集 / Union of all group keywords from topics.yaml
    config = load_config()
    keywords = []
    for g in config.get("groups", []):
        keywords.extend(g.get("keywords", []))
    if keywords:
        return keywords
    return DEFAULT_KEYWORDS


def load_exclude_keywords():
    """从 topics.yaml 读取排除关键词 / Load exclude keywords from topics.yaml"""
    config = load_config()
    return [str(k).strip() for k in config.get("exclude_keywords", []) if str(k).strip()]


def load_config():
    """读取 topics.yaml 配置 / Load topics.yaml config"""
    topics_file = Path(__file__).resolve().parents[2] / "topics.yaml"
    if yaml is not None and topics_file.exists():
        try:
            return yaml.safe_load(topics_file.read_text(encoding="utf-8")) or {}
        except Exception as e:
            print(f"读取 topics.yaml 失败 / Failed to read topics.yaml: {e}", file=sys.stderr)
    return {}


def matched_keywords(text, keywords):
    """返回命中的所有关键词 / Return all keywords that match the text"""
    hits = []
    for kw in keywords:
        if kw.isupper():
            # 全大写缩写: 大小写敏感, 避免 previous/obvious 误命中 vio
            if kw in text:
                hits.append(kw)
        elif kw.lower() in text.lower():
            hits.append(kw)
    return hits


def main():
    if len(sys.argv) < 2:
        print("用法 / Usage: python filter_keywords.py <jsonl文件路径>", file=sys.stderr)
        sys.exit(2)

    file_path = sys.argv[1]
    keywords = load_keywords()
    exclude_keywords = load_exclude_keywords()
    print(f"过滤关键词 / Filter keywords: {keywords}", file=sys.stderr)
    print(f"排除关键词 / Exclude keywords: {exclude_keywords}", file=sys.stderr)

    papers = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                papers.append(json.loads(line))

    kept = []
    excluded = []
    seen_ids = set()  # 同日内跨列表重复去重 / dedup cross-listed papers within the same day
    for p in papers:
        pid = p.get('id', '')
        if pid and pid in seen_ids:
            continue
        text = f"{p.get('title', '')} {p.get('summary', '')}"
        hits = matched_keywords(text, keywords)
        if not hits:
            continue
        # 排除关键词优先 / Exclude keywords take priority
        exclude_hits = matched_keywords(text, exclude_keywords)
        if exclude_hits:
            excluded.append((p.get('id'), exclude_hits))
            continue
        p['matched_keywords'] = hits
        kept.append(p)
        seen_ids.add(pid)

    print(f"总数 / Total: {len(papers)}, 保留 / Kept: {len(kept)}, 剔除 / Dropped: {len(papers) - len(kept)}", file=sys.stderr)
    if excluded:
        print(f"排除(黑名单命中) / Excluded by blacklist: {len(excluded)} 篇", file=sys.stderr)
        for pid, ehs in excluded[:10]:
            print(f"  ✗ {pid} | 排除词: {ehs}", file=sys.stderr)
    for p in kept[:10]:
        print(f"  ✓ {p.get('id')} {p.get('title', '')[:60]} | 关键词: {p['matched_keywords']}", file=sys.stderr)

    if not kept:
        print("没有命中关键词的论文, 文件保持不变 / No paper matched, file unchanged", file=sys.stderr)
        sys.exit(1)

    with open(file_path, 'w', encoding='utf-8') as f:
        for p in kept:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')
    print(f"已过滤写回 / Filtered file written: {file_path}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
