import os
import json
import sys
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict
from queue import Queue
from threading import Lock
# INSERT_YOUR_CODE
import requests

import dotenv
import argparse
import yaml
from pathlib import Path
from tqdm import tqdm

import langchain_core.exceptions
from langchain_openai import ChatOpenAI
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from structure import Structure

if os.path.exists('.env'):
    dotenv.load_dotenv()
template = open("template.txt", "r").read()
system = open("system.txt", "r").read()


def load_config():
    """
    从 topics.yaml 加载项目配置(唯一配置源) / Load project config from topics.yaml (single source)
    """
    topics_file = Path(__file__).resolve().parent.parent / "topics.yaml"
    if not topics_file.exists():
        raise FileNotFoundError(
            f"topics.yaml 不存在: {topics_file}。请先创建配置文件 / topics.yaml not found, please create it first"
        )
    return yaml.safe_load(topics_file.read_text(encoding="utf-8"))


def load_topic_groups(config):
    """
    从配置中提取关注分组 / Extract topic groups from config
    返回 (分组名列表, 注入 prompt 的分组文本) / Returns (group names, prompt text)
    """
    groups = config.get("groups", [])
    if not groups:
        raise ValueError("topics.yaml 中没有定义任何分组 / No groups defined in topics.yaml")
    names = [g["name"] for g in groups]
    groups_text = "\n".join(
        f"- {g['name']}: {', '.join(g.get('keywords', []))}" for g in groups
    )
    return names, groups_text

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, required=True, help="jsonline data file")
    parser.add_argument("--max_workers", type=int, default=1, help="Maximum number of parallel workers")
    return parser.parse_args()

def process_single_item(chain, item: Dict, language: str, groups_text: str, known_group_names: List[str]) -> Dict:
    def is_sensitive(content: str) -> bool:
        """
        调用敏感词检测接口检测内容是否包含敏感词。
        返回 True 表示触发敏感词，False 表示未触发。
        接口地址可用环境变量 SPAM_CHECK_URL 覆盖; 设为空则跳过检测。
        接口异常时放行(不判定为敏感), 避免第三方服务故障导致论文被误丢弃。
        """
        spam_url = os.environ.get("SPAM_CHECK_URL", "https://spam.dw-dengwei.workers.dev")
        if not spam_url:
            return False
        try:
            resp = requests.post(
                spam_url,
                json={"text": content},
                timeout=5
            )
            if resp.status_code == 200:
                result = resp.json()
                # 约定接口返回 {"sensitive": true/false, ...}
                return result.get("sensitive", True)
            else:
                # 接口异常时放行 / Fail-open when the service errors
                print(f"Sensitive check failed with status {resp.status_code}, skipping (fail-open)", file=sys.stderr)
                return False
        except Exception as e:
            print(f"Sensitive check error: {e}, skipping (fail-open)", file=sys.stderr)
            return False

    def check_github_code(content: str) -> Dict:
        """提取并验证 GitHub 链接"""
        code_info = {}

        # 1. 优先匹配 github.com/owner/repo 格式
        github_pattern = r"https?://github\.com/([a-zA-Z0-9-_]+)/([a-zA-Z0-9-_\.]+)"
        match = re.search(github_pattern, content)
        
        if match:
            owner, repo = match.groups()
            # 清理 repo 名称，去掉可能的 .git 后缀或末尾的标点
            repo = repo.rstrip(".git").rstrip(".,)")
            
            full_url = f"https://github.com/{owner}/{repo}"
            code_info["code_url"] = full_url
            
            # 尝试调用 GitHub API 获取信息
            github_token = os.environ.get("TOKEN_GITHUB")
            headers = {"Accept": "application/vnd.github.v3+json"}
            if github_token:
                headers["Authorization"] = f"token {github_token}"
            
            try:
                api_url = f"https://api.github.com/repos/{owner}/{repo}"
                resp = requests.get(api_url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    code_info["code_stars"] = data.get("stargazers_count", 0)
                    code_info["code_last_update"] = data.get("pushed_at", "")[:10]
            except Exception:
                # API 调用失败不影响主流程
                pass
            return code_info

        # 2. 如果没有 github.com，尝试匹配 github.io
        github_io_pattern = r"https?://[a-zA-Z0-9-_]+\.github\.io(?:/[a-zA-Z0-9-_\.]+)*"
        match_io = re.search(github_io_pattern, content)
        
        if match_io:
            url = match_io.group(0)
            # 清理末尾标点
            url = url.rstrip(".,)")
            code_info["code_url"] = url
            # github.io 不进行 star 和 update 判断
                
        return code_info

    # 检查 summary 字段
    if is_sensitive(item.get("summary", "")):
        return None

    # 检测代码可用性
    code_info = check_github_code(item.get("summary", ""))
    if code_info:
        item.update(code_info)

    """处理单个数据项"""
    # Default structure with meaningful fallback values
    default_ai_fields = {
        "tldr": "Summary generation failed",
        "motivation": "Motivation analysis unavailable",
        "method": "Method extraction failed",
        "result": "Result analysis unavailable",
        "conclusion": "Conclusion extraction failed",
        "abstract_zh": "",
        "groups": []
    }

    try:
        response: Structure = chain.invoke({
            "language": language,
            "content": item['summary'],
            "groups": groups_text
        })
        item['AI'] = response.model_dump()
        # 清洗分组: 丢弃模型编造的组名, 只保留 topics.yaml 中定义的
        raw_groups = item['AI'].get('groups', []) or []
        item['AI']['groups'] = [g for g in raw_groups if g in known_group_names]
    except langchain_core.exceptions.OutputParserException as e:
        # 尝试从错误信息中提取 JSON 字符串并修复
        error_msg = str(e)
        partial_data = {}
        
        if "Function Structure arguments:" in error_msg:
            try:
                # 提取 JSON 字符串
                json_str = error_msg.split("Function Structure arguments:", 1)[1].strip().split('are not valid JSON')[0].strip()
                # 预处理 LaTeX 数学符号 - 使用四个反斜杠来确保正确转义
                json_str = json_str.replace('\\', '\\\\')
                # 尝试解析修复后的 JSON
                partial_data = json.loads(json_str)
            except Exception as json_e:
                print(f"Failed to parse JSON for {item.get('id', 'unknown')}: {json_e}", file=sys.stderr)
        
        # Merge partial data with defaults to ensure all fields exist
        item['AI'] = {**default_ai_fields, **partial_data}
        print(f"Using partial AI data for {item.get('id', 'unknown')}: {list(partial_data.keys())}", file=sys.stderr)
    except Exception as e:
        # Catch any other exceptions and provide default values
        print(f"Unexpected error for {item.get('id', 'unknown')}: {e}", file=sys.stderr)
        item['AI'] = default_ai_fields
    
    # Final validation to ensure all required fields exist
    for field in default_ai_fields.keys():
        if field not in item['AI']:
            item['AI'][field] = default_ai_fields[field]

    # 检查 AI 生成的所有字段
    for v in item.get("AI", {}).values():
        if is_sensitive(str(v)):
            return None
    return item

def process_all_items(data: List[Dict], model_name: str, base_url: str, language: str, max_workers: int,
                      groups_text: str, known_group_names: List[str]) -> List[Dict]:
    """并行处理所有数据项"""
    llm = ChatOpenAI(
            model=model_name,
            base_url=base_url or None,
            api_key=os.environ.get("OPENAI_API_KEY") or None,
            extra_body={"thinking": {"type": "disabled"}}
        ).with_structured_output(Structure, method="function_calling")

    print('Connect to:', model_name, file=sys.stderr)
    
    prompt_template = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(system),
        HumanMessagePromptTemplate.from_template(template=template)
    ])

    chain = prompt_template | llm
    
    # 使用线程池并行处理
    processed_data = [None] * len(data)  # 预分配结果列表
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_idx = {
            executor.submit(process_single_item, chain, item, language, groups_text, known_group_names): idx
            for idx, item in enumerate(data)
        }
        
        # 使用tqdm显示进度
        for future in tqdm(
            as_completed(future_to_idx),
            total=len(data),
            desc="Processing items"
        ):
            idx = future_to_idx[future]
            try:
                result = future.result()
                processed_data[idx] = result
            except Exception as e:
                print(f"Item at index {idx} generated an exception: {e}", file=sys.stderr)
                # Add default AI fields to ensure consistency
                processed_data[idx] = data[idx]
                processed_data[idx]['AI'] = {
                    "tldr": "Processing failed",
                    "motivation": "Processing failed",
                    "method": "Processing failed",
                    "result": "Processing failed",
                    "conclusion": "Processing failed",
                    "abstract_zh": "",
                    "groups": []
                }
    
    return processed_data

def main():
    args = parse_args()

    # 从 topics.yaml 加载配置(唯一配置源) / Load config from topics.yaml (single source)
    config = load_config()
    llm_cfg = config.get("llm", {})
    model_name = llm_cfg.get("model_name", "deepseek-v4-flash")
    language = llm_cfg.get("language", "Chinese")
    base_url = llm_cfg.get("base_url", "")
    known_group_names, groups_text = load_topic_groups(config)
    print(f'配置来源 topics.yaml / Config from topics.yaml: model={model_name}, language={language}, groups={known_group_names}', file=sys.stderr)

    # 检查并删除目标文件
    target_file = args.data.replace('.jsonl', f'_AI_enhanced_{language}.jsonl')
    if os.path.exists(target_file):
        os.remove(target_file)
        print(f'Removed existing file: {target_file}', file=sys.stderr)

    # 读取数据
    data = []
    with open(args.data, "r") as f:
        for line in f:
            data.append(json.loads(line))

    # 去重
    seen_ids = set()
    unique_data = []
    for item in data:
        if item['id'] not in seen_ids:
            seen_ids.add(item['id'])
            unique_data.append(item)

    data = unique_data
    print('Open:', args.data, file=sys.stderr)
    
    # 并行处理所有数据
    processed_data = process_all_items(
        data,
        model_name,
        base_url,
        language,
        args.max_workers,
        groups_text,
        known_group_names
    )
    
    # 保存结果
    with open(target_file, "w") as f:
        for item in processed_data:
            if item is not None:
                f.write(json.dumps(item) + "\n")

if __name__ == "__main__":
    main()
