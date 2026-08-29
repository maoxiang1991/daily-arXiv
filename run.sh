#!/bin/bash

# 本地测试脚本 / Local testing script
# 主要工作流已迁移到 GitHub Actions (.github/workflows/run.yml)
# Main workflow has been migrated to GitHub Actions (.github/workflows/run.yml)

# 自动激活虚拟环境(如存在) / Auto-activate virtual environment if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# 自动读取 ai/.env 中的环境变量(如存在, gitignored 不会提交) / Auto-load env vars from ai/.env if present
if [ -f "ai/.env" ]; then
    set -a
    source ai/.env
    set +a
fi

# 兼容处理: httpx(LLM HTTP 客户端)不识别 socks:// 协议, 统一转为标准 socks5://
# Normalize non-standard socks:// proxy scheme (e.g. Clash) to socks5:// for httpx compatibility
for var in all_proxy ALL_PROXY; do
    val=$(printenv "$var" 2>/dev/null || true)
    if [ -n "$val" ] && [[ "$val" == socks://* ]]; then
        export "$var"="socks5://${val#socks://}"
    fi
done

# 从 topics.yaml 读取配置(唯一配置源) / Read config from topics.yaml (single source of truth)
# 此处只读取本脚本需要的字段; 各 Python 脚本各自直接从 topics.yaml 读取自己的配置
if [ -f "topics.yaml" ]; then
    LANGUAGE=$(python -c "import yaml; print(yaml.safe_load(open('topics.yaml')).get('llm', {}).get('language', 'Chinese'))" 2>/dev/null || echo "Chinese")
else
    LANGUAGE="${LANGUAGE:-Chinese}"
fi

# 环境变量检查和提示 / Environment variables check and prompt
echo "=== 本地调试环境检查 / Local Debug Environment Check ==="
if [ -z "$TOKEN_GITHUB" ]; then
    echo "⚠️  提示：未设置 TOKEN_GITHUB / Warning: TOKEN_GITHUB not set"
    echo "可能导致 GitHub 相关功能受限 / May limit GitHub related functionalities"
else
    echo "✅ TOKEN_GITHUB 已设置 / TOKEN_GITHUB is set"
fi

# 检查必需的环境变量 / Check required environment variables
if [ -z "$OPENAI_API_KEY" ]; then
    echo "⚠️  提示：未设置 OPENAI_API_KEY / Warning: OPENAI_API_KEY not set"
    echo "📝 要进行完整本地调试，请设置以下环境变量 / For complete local debugging, please set the following environment variables:"
    echo ""
    echo "🔑 必需变量 / Required variables:"
    echo "   export OPENAI_API_KEY=\"your-api-key-here\"  (或写入 ai/.env, gitignored)"
    echo ""
    echo "🔧 其他配置 / Other config:"
    echo "   分类、模型、语言、分组等全部在仓库根目录 topics.yaml 中配置"
    echo "   (categories / model / language / groups are all in topics.yaml)"
    echo ""
    echo "💡 设置后重新运行此脚本即可进行完整测试 / After setting, rerun this script for complete testing"
    echo "🚀 或者继续运行部分流程（爬取+去重检查）/ Or continue with partial workflow (crawl + dedup check)"
    echo ""
    read -p "继续部分流程？(y/N) / Continue with partial workflow? (y/N): " continue_partial
    if [[ ! $continue_partial =~ ^[Yy]$ ]]; then
        echo "退出脚本 / Exiting script"
        exit 0
    fi
    PARTIAL_MODE=true
else
    echo "✅ OPENAI_API_KEY 已设置 / OPENAI_API_KEY is set"
    PARTIAL_MODE=false

    # 所有运行配置来自 topics.yaml(唯一配置源), 此处只做展示 / All runtime config comes from topics.yaml
    echo "🔧 当前配置 / Current configuration (topics.yaml):"
    echo "   LANGUAGE: $LANGUAGE"
    if [ -f "topics.yaml" ]; then
        python - <<'EOF'
import yaml
c = yaml.safe_load(open('topics.yaml'))
print("   CATEGORIES:", ", ".join(c.get('arxiv', {}).get('categories', [])))
llm = c.get('llm', {})
print("   MODEL_NAME:", llm.get('model_name', ''))
print("   BASE_URL:", llm.get('base_url', ''))
print("   GROUPS:", ", ".join(g['name'] for g in c.get('groups', [])))
EOF
    fi
fi

echo ""
echo "=== 开始本地调试流程 / Starting Local Debug Workflow ==="

# 获取当前日期 / Get current date
today=`date -u "+%Y-%m-%d"`

echo "本地测试：爬取 $today 的arXiv论文... / Local test: Crawling $today arXiv papers..."

# 第一步：爬取数据 / Step 1: Crawl data
echo "步骤1：开始爬取... / Step 1: Starting crawl..."

# 检查今日文件是否已存在，如存在则删除 / Check if today's file exists, delete if found
if [ -f "data/${today}.jsonl" ]; then
    echo "🗑️ 发现今日文件已存在，正在删除重新生成... / Found existing today's file, deleting for fresh start..."
    rm "data/${today}.jsonl"
    echo "✅ 已删除现有文件：data/${today}.jsonl / Deleted existing file: data/${today}.jsonl"
else
    echo "📝 今日文件不存在，准备新建... / Today's file doesn't exist, ready to create new one..."
fi

cd daily_arxiv
scrapy crawl arxiv -o ../data/${today}.jsonl

if [ ! -f "../data/${today}.jsonl" ]; then
    echo "爬取失败，未生成数据文件 / Crawling failed, no data file generated"
    exit 1
fi

# 第一步半：按分组关键词过滤 / Step 1.5: Filter by group keywords (topics.yaml)
if [ "$SKIP_KEYWORD_FILTER" = "1" ]; then
    echo "⏭️  跳过关键词过滤(SKIP_KEYWORD_FILTER=1) / Skipping keyword filter"
else
    echo "步骤1.5：按分组关键词过滤... / Step 1.5: Filtering by group keywords..."
    python daily_arxiv/filter_keywords.py ../data/${today}.jsonl
    filter_exit=$?
    if [ $filter_exit -eq 1 ]; then
        echo "⚠️  没有命中分组关键词的论文，停止处理 / No papers matched group keywords, stopping"
        exit 1
    fi
fi

# 第二步：检查去重 / Step 2: Check duplicates
echo "步骤2：执行去重检查... / Step 2: Performing intelligent deduplication check..."
python daily_arxiv/check_stats.py
dedup_exit_code=$?

case $dedup_exit_code in
    0)
        # check_stats.py已输出成功信息，继续处理 / check_stats.py already output success info, continue processing
        ;;
    1)
        # check_stats.py已输出无新内容信息，停止处理 / check_stats.py already output no new content info, stop processing
        exit 1
        ;;
    2)
        # check_stats.py已输出错误信息，停止处理 / check_stats.py already output error info, stop processing
        exit 2
        ;;
    *)
        echo "❌ 未知退出码，停止处理... / Unknown exit code, stopping..."
        exit 1
        ;;
esac

cd ..

# 第三步：AI处理 / Step 3: AI processing
if [ "$PARTIAL_MODE" = "false" ]; then
    echo "步骤3：AI增强处理... / Step 3: AI enhancement processing..."
    cd ai
    python enhance.py --data ../data/${today}.jsonl --max_workers 4
    
    if [ $? -ne 0 ]; then
        echo "❌ AI处理失败 / AI processing failed"
        exit 1
    fi
    echo "✅ AI增强处理完成 / AI enhancement processing completed"
    cd ..
else
    echo "⏭️  跳过AI处理（部分模式）/ Skipping AI processing (partial mode)"
fi

# 第四步：转换为Markdown / Step 4: Convert to Markdown
echo "步骤4：转换为Markdown... / Step 4: Converting to Markdown..."
cd to_md

if [ "$PARTIAL_MODE" = "false" ] && [ -f "../data/${today}_AI_enhanced_${LANGUAGE}.jsonl" ]; then
    echo "📄 使用AI增强后的数据进行转换... / Using AI enhanced data for conversion..."
    python convert.py --data ../data/${today}_AI_enhanced_${LANGUAGE}.jsonl
    
    if [ $? -ne 0 ]; then
        echo "❌ Markdown转换失败 / Markdown conversion failed"
        exit 1
    fi
    echo "✅ AI增强版Markdown转换完成 / AI enhanced Markdown conversion completed"
    
else
    if [ "$PARTIAL_MODE" = "true" ]; then
        echo "⏭️  跳过Markdown转换（部分模式，需要AI增强数据）/ Skipping Markdown conversion (partial mode, requires AI enhanced data)"
    else
        echo "❌ 错误：未找到AI增强文件 / Error: AI enhanced file not found"
        echo "AI文件: ../data/${today}_AI_enhanced_${LANGUAGE}.jsonl"
        exit 1
    fi
fi

cd ..

# 第五步：更新前端资产(文件列表/每日统计/分组配置) / Step 5: Update frontend assets
echo "步骤5：更新文件列表/每日统计/分组配置... / Step 5: Updating file list, stats and groups..."
bash update_assets.sh

# 第六步：飞书推送与知识库同步(未配置密钥时自动跳过) / Step 6: Feishu push & knowledge base sync
echo "步骤6：飞书推送与知识库同步... / Step 6: Feishu push & knowledge base sync..."
python feishu_sync.py --date ${today} || echo "⚠️ 飞书同步失败或未配置(不影响主流程) / Feishu sync failed or not configured (non-blocking)"

# 完成总结 / Completion summary
echo ""
echo "=== 本地调试完成 / Local Debug Completed ==="
if [ "$PARTIAL_MODE" = "false" ]; then
    echo "🎉 完整流程已完成 / Complete workflow finished:"
    echo "   ✅ 数据爬取 / Data crawling"
    echo "   ✅ 去重检查 / Smart duplicate check"
    echo "   ✅ AI增强处理 / AI enhancement"
    echo "   ✅ Markdown转换 / Markdown conversion"
    echo "   ✅ 文件列表更新 / File list update"
else
    echo "🔄 部分流程已完成 / Partial workflow finished:"
    echo "   ✅ 数据爬取 / Data crawling"
    echo "   ✅ 去重检查 / Smart duplicate check"
    echo "   ⏭️  跳过AI增强和Markdown转换 / Skipped AI enhancement and Markdown conversion"
    echo "   ✅ 文件列表更新 / File list update"
    echo ""
    echo "💡 提示：设置OPENAI_API_KEY可启用完整功能 / Tip: Set OPENAI_API_KEY to enable full functionality"
fi