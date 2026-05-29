# coding=utf-8
#!/usr/bin/python
import re
import sys
import json
import html
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
        # 稳健的 UA，配合动态 Referer 处理
        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        self.channel_cache = {}
        # 远程配置 URL
        self.config_url = "https://raw.githubusercontent.com/zzq1234567890/tvbox1/refs/heads/main/lib/youtube.json"
        self.classes = []          # 分类列表 [{type_id, type_name}]
        self.alias_map = {}        # 别名 → 实际频道ID（用于自媒体等）
        self._load_config()

    def _load_config(self):
        """加载远程配置，解析分类和别名映射"""
        try:
            r = requests.get(self.config_url, timeout=8, proxies=self.proxies)
            config = r.json()
            # 解析 class 分类
            self.classes = []
            for item in config.get("class", []):
                type_id = item.get("type_id", "").strip()
                type_name = item.get("type_name", "").strip()
                if type_id and type_name:
                    self.classes.append({
                        "type_id": type_id,
                        "type_name": type_name
                    })
                    # 针对自媒体分类（type_id 包含 "LIST:自媒體"）提取别名映射
                    if type_id.startswith("LIST:自媒體") and "@" in type_id:
                        # 格式示例：LIST:自媒體 老高與小茉 @laogao,脑洞乌托邦 @NDWTB,...
                        # 提取 @ 后面的频道标识作为实际搜索关键词
                        parts = type_id.replace("LIST:自媒體", "").strip()
                        for p in parts.split(","):
                            p = p.strip()
                            if p and "@" in p:
                                alias, channel = p.split("@", 1)
                                alias = alias.strip()
                                channel = channel.strip()
                                if alias and channel:
                                    self.alias_map[alias] = channel
        except Exception as e:
            # 加载失败时使用默认分类（确保基本可用）
            self.classes = [
                {'type_id': '虎妞小叨叨', 'type_name': '虎妞小叨叨'},
                {'type_id': '温城鲤', 'type_name': '温城鲤'},
                {'type_id': '阿奇讲电影', 'type_name': '阿奇讲电影'},
                {'type_id': '哇萨比抓马', 'type_name': '哇萨比抓马'}
            ]

    def _resolve_search_keyword(self, cid):
        """
        将分类ID转换为实际的 YouTube 搜索关键词
        处理格式：
        - 普通字符串 -> 原样返回
        - LIST:xxx -> 去掉前缀，并尝试别名映射
        """
        keyword = cid
        # 去掉 LIST: 前缀
        if keyword.startswith("LIST:"):
            keyword = keyword[5:]  # 去掉 "LIST:"
        # 如果 keyword 命中别名映射（例如 "老高與小茉" -> "laogao"），则使用映射值
        if keyword in self.alias_map:
            return self.alias_map[keyword]
        # 未命中则直接返回 keyword（可能是多个关键词组合，如 "新闻 Live,体育直播" 原样搜索）
        return keyword

    def homeContent(self, filter):
        # 返回动态加载的分类列表
        return {'class': self.classes}

    def homeVideoContent(self):
        # 默认返回第一个分类的视频列表
        if self.classes:
            first_cid = self.classes[0]['type_id']
            return self.categoryContent(first_cid, 1, {}, {})
        return {'list': []}

    def categoryContent(self, cid, page, filter, ext):
        # 解析实际搜索关键词
        search_keyword = self._resolve_search_keyword(cid)
        # 如果搜索关键词为空，返回空列表
        if not search_keyword:
            return {'list': []}
        # 构建 YouTube 搜索 URL，增加视频过滤（sp=EgIQAQ%3D%3D 表示视频）
        url = f"https://www.youtube.com/results?search_query={quote(search_keyword)}&sp=EgIQAQ%3D%3D"
        try:
            r = requests.get(url, headers=self.header, timeout=8, proxies=self.proxies, stream=True)
            html_content = r.raw.read(64 * 1024).decode('utf-8', 'ignore')
            r.close()
            videos = self._extract_videos(html_content, 50)
            self.channel_cache["current"] = videos
            return {'list': videos, 'page': 1, 'pagecount': 1, 'limit': len(videos), 'total': len(videos)}
        except Exception:
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        # 搜索直接使用关键词，无需解析 LIST 前缀
        return self.categoryContent(key, pg, {}, {})

    def detailContent(self, did):
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
        vid = pid.split('$')[-1]
        # 动态时间戳 + 动态 Referer，击穿缓存与鉴权
        return {
            "parse": 1,
            "url": f"https://www.youtube.com/watch?v={vid}&t={int(time.time())}",
            "header": {
                "User-Agent": self.header["User-Agent"],
                "Referer": f"https://www.youtube.com/watch?v={vid}"
            },
            "proxy": self.proxy_str
        }

    def _extract_videos(self, html_content, limit=30):
        videos = []
        m = re.search(r'var ytInitialData\s*=\s*({.*?});', html_content, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(1))
            items = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {}).get("primaryContents", {}).get("sectionListRenderer", {}).get("contents", [])
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
        try:
            r = requests.get(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json", timeout=3, proxies=self.proxies)
            return r.json().get("title", "YouTube视频")
        except:
            return "YouTube视频"

    def _safe(self, t):
        return "".join([c if c.isalnum() or c in "· " else "·" for c in t])[:80]

    def destroy(self):
        pass# coding=utf-8
#!/usr/bin/python
import re
import sys
import json
import html
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
        # 稳健的 UA，配合动态 Referer 处理
        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        self.channel_cache = {}
        # 远程配置 URL
        self.config_url = "https://raw.githubusercontent.com/zzq1234567890/tvbox1/refs/heads/main/lib/youtube.json"
        self.classes = []
        self.alias_map = {}  # 别名到实际搜索关键词的映射
        self._load_config()

    def _load_config(self):
        """加载远程配置，解析分类和别名映射"""
        try:
            r = requests.get(self.config_url, timeout=8, proxies=self.proxies)
            config = r.json()
            # 解析 class 分类
            self.classes = []
            for item in config.get("class", []):
                type_id = item.get("type_id", "")
                type_name = item.get("type_name", "")
                # 处理 LIST: 前缀，保留原始 type_id 用于后续搜索
                self.classes.append({
                    "type_id": type_id,
                    "type_name": type_name
                })
            # 构建别名映射：从自媒體分类中提取频道别名
            # 例如：老高與小茉 @laogao -> 搜索关键词为 laogao
            for item in config.get("class", []):
                type_id = item.get("type_id", "")
                if type_id.startswith("LIST:自媒體"):
                    # 解析别名列表：老高與小茉 @laogao,脑洞乌托邦 @NDWTB,...
                    parts = type_id.replace("LIST:自媒體", "").strip()
                    for p in parts.split(","):
                        p = p.strip()
                        if not p:
                            continue
                        # 提取 @ 后面的频道标识作为搜索关键词
                        if "@" in p:
                            alias, channel_id = p.split("@", 1)
                            alias = alias.strip()
                            channel_id = channel_id.strip()
                            self.alias_map[alias] = channel_id
        except Exception as e:
            # 加载失败时使用默认分类
            self.classes = [
                {'type_id': '虎妞小叨叨', 'type_name': '虎妞小叨叨'},
                {'type_id': '温城鲤', 'type_name': '温城鲤'},
                {'type_id': '阿奇讲电影', 'type_name': '阿奇讲电影'},
                {'type_id': '哇萨比抓马', 'type_name': '哇萨比抓马'}
            ]

    def _resolve_search_keyword(self, cid):
        """解析分类ID，返回实际搜索关键词"""
        # 处理 LIST: 前缀格式
        if cid.startswith("LIST:"):
            keyword = cid[5:]  # 去掉 "LIST:" 前缀
            # 如果包含别名映射，尝试映射到实际频道ID
            if keyword in self.alias_map:
                return self.alias_map[keyword]
            return keyword
        # 直接返回原值（兼容旧格式）
        return cid

    def homeContent(self, filter):
        # 返回动态加载的分类列表
        return {'class': self.classes}

    def homeVideoContent(self):
        # 默认返回第一个分类的视频列表
        if self.classes:
            first_cid = self.classes[0]['type_id']
            return self.categoryContent(first_cid, 1, {}, {})
        return {'list': []}

    def categoryContent(self, cid, page, filter, ext):
        # 解析分类ID，获取实际搜索关键词
        search_keyword = self._resolve_search_keyword(cid)
        # 构建 YouTube 搜索 URL
        url = f"https://www.youtube.com/results?search_query={quote(search_keyword)}&sp=EgIQAQ%3D%3D"
        try:
            r = requests.get(url, headers=self.header, timeout=8, proxies=self.proxies, stream=True)
            html_content = r.raw.read(64 * 1024).decode('utf-8', 'ignore')
            r.close()
            
            videos = self._extract_videos(html_content, 50)
            self.channel_cache["current"] = videos
            return {'list': videos, 'page': 1, 'pagecount': 1, 'limit': len(videos), 'total': len(videos)}
        except:
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        return self.categoryContent(key, pg, {}, {})

    def detailContent(self, did):
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
        vid = pid.split('$')[-1]
        # 动态时间戳 + 动态 Referer，击穿缓存与 YouTube 鉴权校验
        return {
            "parse": 1,
            "url": f"https://www.youtube.com/watch?v={vid}&t={int(time.time())}",
            "header": {
                "User-Agent": self.header["User-Agent"],
                "Referer": f"https://www.youtube.com/watch?v={vid}"
            },
            "proxy": self.proxy_str
        }

    def _extract_videos(self, html_content, limit=30):
        videos = []
        m = re.search(r'var ytInitialData\s*=\s*({.*?});', html_content, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(1))
            items = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {}).get("primaryContents", {}).get("sectionListRenderer", {}).get("contents", [])
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
        try:
            r = requests.get(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json", timeout=3, proxies=self.proxies)
            return r.json().get("title", "YouTube视频")
        except:
            return "YouTube视频"

    def _safe(self, t):
        return "".join([c if c.isalnum() or c in "· " else "·" for c in t])[:80]

    def destroy(self):
        pass
