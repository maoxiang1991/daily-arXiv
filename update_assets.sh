#!/bin/bash
# 更新前端资产: 文件列表 / 每日论文数统计 / 分组配置 / Update frontend assets
# 供 run.sh(本地) 与 GitHub Actions workflow 共用 / Shared by local run.sh and the CI workflow
# 从仓库根目录运行 / Run from the repo root
set -e

# 自动激活虚拟环境(如存在, 保证 python/yaml 可用) / Auto-activate venv if present
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# 从 topics.yaml 读取语言配置 / Read language from topics.yaml
LANGUAGE=$(python -c "import yaml; print(yaml.safe_load(open('topics.yaml')).get('llm', {}).get('language', 'Chinese'))" 2>/dev/null || echo "Chinese")

# 1. 文件列表 / File list
ls data/*.jsonl | sed 's|data/||' > assets/file-list.txt
echo "✅ 文件列表更新完成 / File list updated"

# 2. 每日论文数统计 / Per-date paper counts
{
    echo "{"
    first=true
    for f in data/*_AI_enhanced_${LANGUAGE}.jsonl; do
        [ -f "$f" ] || continue
        d=$(basename "$f" | cut -d_ -f1)
        c=$(wc -l < "$f")
        if [ "$first" = "true" ]; then
            echo "  \"$d\": $c"
            first=false
        else
            echo "  ,\"$d\": $c"
        fi
    done
    echo "}"
} > assets/file-stats.json
echo "✅ 每日论文数统计更新完成 / Per-date paper counts updated"

# 3. 分组配置 / Groups config
python export_groups.py
