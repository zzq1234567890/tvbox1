# coding=utf-8
#!/usr/bin/python
import re
import sys
import json
import time
import requests
from urllib.parse import quote

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    def getName(self):
        return "YouTube视频"

    def init(self, extend):
        try:
            self.extendDict = json.loads(extend)
        except:
            self.extendDict = {}
        self.proxies = self.extendDict.get('proxy', {})
        self.proxy_str = self.extendDict.get('proxy_str', None)
        # 使用最稳健的 UA，配合动态 Referer 处理
        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        self.channel_cache = {}
        # 分类与映射配置
        self.config_url = "https://raw.githubusercontent.com/zzq1234567890/tvbox1/refs/heads/main/lib/youtube.json"
        self.classes = []
        self.alias_map = {}   # 别名 -> 频道ID，用于自媒体分类
        self._load_config()

    # ----------------------------------------------
    # 配置加载与解析
    # ----------------------------------------------
    def _load_config(self):
        """加载远程配置，构建分类列表与别名映射"""
        try:
            r = requests.get(self.config_url, timeout=8, proxies=self.proxies)
            config = r.json()
            raw_classes = config.get("class", [])
            self.classes = []
            for item in raw_classes:
                type_id = item.get("type_id", "").strip()
                type_name = item.get("type_name", "").strip()
                if type_id and type_name:
                    self.classes.append({
                        "type_id": type_id,
                        "type_name": type_name
                    })
                    # 如果是“自媒體”分类，额外解析别名映射
                    if type_id.startswith("LIST:自媒體") and "@" in type_id:
                        parts = type_id.replace("LIST:自媒體", "").strip()
                        for seg in parts.split(","):
                            seg = seg.strip()
                            if seg and "@" in seg:
                                alias, ch_id = seg.split("@", 1)
                                alias = alias.strip()
                                ch_id = ch_id.strip()
                                if alias and ch_id:
                                    self.alias_map[alias] = ch_id
        except Exception as e:
            # 加载失败时保留一个默认项，避免首页为空
            self.classes = [{'type_id': 'YouTube视频', 'type_name': '默认搜索'}]

    def _resolve_search_keyword(self, cid):
        """
        将分类ID转换为 YouTube 实际可用的搜索词
        - 去掉 "LIST:" 前缀
        - 如果命中别名映射，直接返回频道ID（如 laogao）
        - 否则保留原样（可能是一组用逗号隔开的关键词，原样搜索 YouTube 会处理）
        """
        keyword = cid
        if keyword.startswith("LIST:"):
            keyword = keyword[5:]
        if keyword in self.alias_map:
            return self.alias_map[keyword]
        return keyword

    # ----------------------------------------------
    # 接口实现
    # ----------------------------------------------
    def homeContent(self, filter):
        """返回动态分类列表"""
        return {'class': self.classes}

    def homeVideoContent(self):
        """默认展示第一个分类的视频"""
        if self.classes:
            first_cid = self.classes[0]['type_id']
            return self.categoryContent(first_cid, 1, {}, {})
        return {'list': []}

    def categoryContent(self, cid, page, filter, ext):
        """根据分类ID获取视频列表"""
        search_keyword = self._resolve_search_keyword(cid)
        if not search_keyword:
            return {'list': []}

        # YouTube 搜索 API, sp=EgIQAQ%3D%3D 用于筛选视频
        url = f"https://www.youtube.com/results?search_query={quote(search_keyword)}&sp=EgIQAQ%3D%3D"
        try:
            r = requests.get(url, headers=self.header, timeout=8, proxies=self.proxies, stream=True)
            html_content = r.raw.read(64 * 1024).decode('utf-8', 'ignore')
            r.close()

            videos = self._extract_videos(html_content, 50)
            self.channel_cache["current"] = videos
            return {
                'list': videos,
                'page': 1,
                'pagecount': 1,
                'limit': len(videos),
                'total': len(videos)
            }
        except Exception:
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        """搜索接口直接复用分类搜索逻辑"""
        return self.categoryContent(key, pg, {}, {})

    def detailContent(self, did):
        """视频详情页，构建单集与全集列表"""
        vid = did[0]
        cache = self.channel_cache.get("current", [])
        video_item = next((v for v in cache if v['vod_id'] == vid), None)
        title = video_item['vod_name'] if video_item else self._get_title(vid)

        episode_list = [f"{self._safe(v['vod_name'])}${v['vod_id']}" for v in cache]

        vod = {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg",
            "vod_play_from": "YouTube直连",
            "vod_play_url": f"{self._safe(title)}${vid}"
        }
        if episode_list:
            vod["vod_play_url"] += "#" + "#".join(episode_list)
        return {'list': [vod]}

    def playerContent(self, flag, pid, vipFlags):
        """播放器，通过动态时间戳和Referer突破限制"""
        vid = pid.split('$')[-1]
        return {
            "parse": 1,
            "url": f"https://www.youtube.com/watch?v={vid}&t={int(time.time())}",
            "header": {
                "User-Agent": self.header["User-Agent"],
                "Referer": f"https://www.youtube.com/watch?v={vid}"
            },
            "proxy": self.proxy_str
        }

    # ----------------------------------------------
    # 辅助方法
    # ----------------------------------------------
    def _extract_videos(self, html_content, limit=30):
        """从 HTML 中提取 ytInitialData 并解析视频列表"""
        videos = []
        m = re.search(r'var ytInitialData\s*=\s*({.*?});', html_content, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(1))
            contents = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {})
            items = contents.get("primaryContents", {}).get("sectionListRenderer", {}).get("contents", [])
            for section in items:
                vids = section.get("itemSectionRenderer", {}).get("contents", [])
                for item in vids:
                    r = item.get("videoRenderer")
                    if r and "videoId" in r:
                        videos.append({
                            "vod_id": r["videoId"],
                            "vod_name": r.get("title", {}).get("runs", [{}])[0].get("text", "未知"),
                            "vod_pic": f"https://img.youtube.com/vi/{r['videoId']}/hqdefault.jpg"
                        })
                        if len(videos) >= limit:
                            break
        except:
            pass
        return videos

    def _get_title(self, vid):
        """通过 oEmbed 获取视频标题（降级方案）"""
        try:
            r = requests.get(
                f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json",
                timeout=3, proxies=self.proxies
            )
            return r.json().get("title", "YouTube视频")
        except:
            return "YouTube视频"

    def _safe(self, t):
        """过滤标题中的特殊字符，避免播放链接格式出错"""
        return "".join([c if c.isalnum() or c in "· " else "·" for c in t])[:80]

    def destroy(self):
        pass
