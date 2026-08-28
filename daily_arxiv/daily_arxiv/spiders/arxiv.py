import scrapy
import os
import re
import sys
from pathlib import Path

import arxiv

try:
    import yaml
except ImportError:
    yaml = None

BATCH_SIZE = 100  # 元数据批量抓取每批论文数 / batch size for metadata fetching


def load_categories():
    """
    加载目标分类 / Load target categories
    唯一配置源: topics.yaml 的 arxiv.categories (缺失时回退默认 cs.CV)
    Single source: topics.yaml arxiv.categories (fallback: cs.CV)
    """
    topics_file = Path(__file__).resolve().parents[3] / "topics.yaml"
    if yaml is not None and topics_file.exists():
        try:
            config = yaml.safe_load(topics_file.read_text(encoding="utf-8"))
            cats = config.get("arxiv", {}).get("categories", [])
            if cats:
                return [str(c).strip() for c in cats]
        except Exception as e:
            print(f"读取 topics.yaml 失败, 使用默认分类 cs.CV / Failed to read topics.yaml, using default: {e}", file=sys.stderr)
    return ["cs.CV"]


class ArxivSpider(scrapy.Spider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categories = load_categories()
        # 保存目标分类列表，用于后续验证
        self.target_categories = set(categories)
        self.start_urls = [
            f"https://arxiv.org/list/{cat}/new" for cat in self.target_categories
        ]  # 起始URL（计算机科学领域的最新论文）
        # 显式打印配置来源, 便于确认 topics.yaml 生效 / Log config source for verification
        self.logger.info(f"目标分类 / Target categories: {sorted(self.target_categories)} (配置来源 / source: topics.yaml)")

    name = "arxiv"  # 爬虫名称
    allowed_domains = ["arxiv.org"]  # 允许爬取的域名

    def parse(self, response):
        # 第一步: 解析列表页, 收集本页全部论文的 ID 和分类 / Step 1: parse the listing page
        # 注意: 旧版 arxiv 页面用 dlpage 底部 ul 的锚点区分跨列表论文, 曾用
        #   paper_id >= anchors[-1] 跳过; 2026 年页面改版后该锚点结构已变,
        #   继续使用会导致 95% 的论文被误跳过, 因此已移除该逻辑
        #   (跨列表重复由下游按论文 ID 去重处理)
        entries = []
        for paper in response.css("dl dt"):
            paper_anchor = paper.css("a[name^='item']::attr(name)").get()
            if not paper_anchor:
                continue

            # 获取论文ID
            abstract_link = paper.css("a[title='Abstract']::attr(href)").get()
            if not abstract_link:
                continue

            arxiv_id = abstract_link.split("/")[-1]

            # 获取对应的论文描述部分 (dd元素)
            paper_dd = paper.xpath("following-sibling::dd[1]")
            if not paper_dd:
                continue

            # 提取论文分类信息 - 在subjects部分
            # 注意: 必须读取全部 subjects 文本(含跨列表的副分类), 只读 primary-subject
            #   会漏掉从其他分类跨列表到目标分类的论文
            subjects_text = " ".join(paper_dd.css(".list-subjects ::text").getall())
            if not subjects_text:
                # 如果找不到 subjects, 尝试旧版主分类方式
                subjects_text = paper_dd.css(".list-subjects .primary-subject::text").get()

            if subjects_text:
                # 解析分类信息，通常格式如 "Computer Vision and Pattern Recognition (cs.CV)"
                # 提取括号中的分类代码
                categories_in_paper = re.findall(r'\(([^)]+)\)', subjects_text)

                # 检查论文分类是否与目标分类有交集
                paper_categories = set(categories_in_paper)
                if paper_categories.intersection(self.target_categories):
                    entries.append({
                        "id": arxiv_id,
                        "categories": list(paper_categories),
                    })
                else:
                    self.logger.debug(f"Skipped paper {arxiv_id} with categories {paper_categories} (not in target {self.target_categories})")
            else:
                # 如果无法获取分类信息，记录警告但仍然保留论文（保持向后兼容）
                self.logger.warning(f"Could not extract categories for paper {arxiv_id}, including anyway")
                entries.append({
                    "id": arxiv_id,
                    "categories": [],
                })

        # 第二步: 批量抓取元数据(每批 BATCH_SIZE 篇, 一次 API 请求) / Step 2: batch-fetch metadata
        self._fetch_metadata_batch(entries)

        # 第三步: 产出完整条目 / Step 3: yield complete items
        for entry in entries:
            if entry.get("_missing"):
                continue
            yield entry

    def _fetch_metadata_batch(self, entries):
        """
        批量抓取论文元数据 / Batch-fetch paper metadata via arXiv API id_list
        每批一次请求(最多 BATCH_SIZE 篇), 相比逐篇抓取(每篇一次请求+限速)快两个数量级
        One API call per batch (up to BATCH_SIZE ids) instead of one call per paper
        """
        if not entries:
            return

        client = arxiv.Client(page_size=BATCH_SIZE)
        ids = [e["id"] for e in entries]
        by_id = {}

        for i in range(0, len(ids), BATCH_SIZE):
            chunk = ids[i:i + BATCH_SIZE]
            search = arxiv.Search(id_list=chunk, max_results=len(chunk))
            try:
                for paper in client.results(search):
                    short_id = paper.get_short_id()
                    # 去掉版本后缀(v1/v2), 与列表页的无版本 ID 对齐 / Strip version suffix to match listing ids
                    by_id[re.sub(r"v\d+$", "", short_id)] = paper
            except Exception as e:
                self.logger.warning(f"批量抓取失败, 回退逐篇 / Batch fetch failed, falling back per-id: {e}")
                for pid in chunk:
                    try:
                        paper = next(client.results(arxiv.Search(id_list=[pid], max_results=1)))
                        short_id = paper.get_short_id()
                        by_id[re.sub(r"v\d+$", "", short_id)] = paper
                    except Exception as e2:
                        self.logger.warning(f"未取到元数据 / No metadata for {pid}: {e2}")

        self.logger.info(f"批量抓取元数据完成 / Batch metadata fetched: {len(ids)} ids, {len(by_id)} resolved")

        for entry in entries:
            paper = by_id.get(entry["id"])
            if paper is None:
                self.logger.warning(f"未取到元数据, 跳过 / Missing metadata, skipping: {entry['id']}")
                entry["_missing"] = True
                continue
            entry["authors"] = [a.name for a in paper.authors]
            entry["title"] = paper.title
            entry["categories"] = paper.categories
            entry["comment"] = paper.comment
            entry["summary"] = paper.summary
