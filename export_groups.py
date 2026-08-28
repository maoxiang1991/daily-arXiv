#!/usr/bin/env python3
"""
把 topics.yaml 导出为 assets/groups.json 供前端使用 / Export topics.yaml to assets/groups.json for the frontend
前端通过相对路径 assets/groups.json 读取分组定义(分组名、关键词) / The frontend reads group definitions via assets/groups.json
"""
import json
import sys
from pathlib import Path

import yaml


def main():
    root = Path(__file__).resolve().parent
    topics_file = root / "topics.yaml"
    out_file = root / "assets" / "groups.json"

    try:
        config = yaml.safe_load(topics_file.read_text(encoding="utf-8"))
        groups = config.get("groups", [])
        if not groups:
            raise ValueError("topics.yaml 中没有定义任何分组 / No groups defined")
        payload = {
            "version": config.get("version", 1),
            "search_days": config.get("search_days", 7),
            "groups": [{"name": g["name"], "keywords": g.get("keywords", [])} for g in groups],
        }
    except Exception as e:
        print(f"❌ 读取 topics.yaml 失败 / Failed to read topics.yaml: {e}", file=sys.stderr)
        sys.exit(1)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 已导出分组配置 / Groups exported: {out_file} ({len(groups)} groups)", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
