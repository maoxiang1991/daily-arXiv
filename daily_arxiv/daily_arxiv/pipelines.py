# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface


class DailyArxivPipeline:
    """补充论文 URL 字段 / Fill in pdf/abs URLs.
    元数据(标题/作者/摘要等)已由 spider 在 parse 阶段批量抓取
    Metadata is batch-fetched by the spider during parse."""

    def process_item(self, item: dict, spider):
        item["pdf"] = f"https://arxiv.org/pdf/{item['id']}"
        item["abs"] = f"https://arxiv.org/abs/{item['id']}"
        return item
