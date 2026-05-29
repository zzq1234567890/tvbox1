# coding=utf-8
#!/usr/bin/python
import re
import sys
import json
import time
import os
import requests
from urllib.parse import quote
sys.path.append('..')
from base.spider import Spider

class Spider(Spider):
    def getName(self):
        return "YouTube视频"

    def init(self, extend):
        try:
            self.extendDict = json.loads(extend) if isinstance(extend, str) else extend
        except:
            self.extendDict = {}
        self.proxies = self.extendDict.get('proxy', {})
        self.proxy_str = self.extendDict.get('proxy_str', None)
        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        self.channel_cache = {}
        self.classes = []
        self.alias_map = {}
        # 加载分类配置：优先使用 ext 中的 json 路径，其次使用远程 URL
        self._load_config_from_ext()

    def _load_config_from_ext(self):
        """从扩展配置中加载分类 JSON（支持本地文件或远程 URL）"""
        config_path = self.extendDict.get('json')
        if not config_path:
            # 没有配置 json 路径，使用默认远程地址
            self._load_remote_config("https://raw.githubusercontent.com/zzq1234567890/tvbox1/refs/heads/main/lib/youtube.json")
            return

        # 处理本地相对路径
        if config_path.startswith('./'):
            # 获取当前脚本所在目录，拼接相对路径
            base_dir = os.path.dirname(os.path.abspath(__file__))
            abs_path = os.path.join(base_dir, config_path[2:])
        else:
            abs_path = config_path

        # 尝试读取本地文件
        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self._parse_config(config)
            return
        except Exception as e:
            print(f"读取本地配置文件失败: {e}, 尝试远程地址")

        # 如果本地读取失败且路径看起来像 URL，尝试直接请求
        if config_path.startswith('http://') or config_path.startswith('https://'):
            self._load_remote_config(config_path)
        else:
            # 最后 fallback 到默认远程地址
            self._load_remote_config("https://raw.githubusercontent.com/zzq1234567890/tvbox1/refs/heads/main/lib/youtube.json")

    def _load_remote_config(self, url):
        """从远程 URL 加载配置"""
        try:
            r = requests.get(url, timeout=8, proxies=self.proxies)
            config = r.json()
            self._parse_config(config)
        except Exception as e:
            print(f"远程配置加载失败: {e}")
            # 保底默认分类
            self.classes = [{'type_id': 'YouTube视频', 'type_name': '默认搜索'}]

    def _parse_config(self, config):
        """解析配置，构建分类列表和别名映射"""
        self.classes = []
        self.alias_map = {}
        for item in config.get("class", []):
            type_id = item.get("type_id", "").strip()
            type_name = item.get("type_name", "").strip()
            if type_id and type_name:
                self.classes.append({
                    "type_id": type_id,
                    "type_name": type_name
                })
                # 处理自媒体分类中的别名映射（例如：老高與小茉 @laogao）
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

    def _resolve_search_keyword(self, cid):
        """将分类ID转换为实际搜索关键词"""
        keyword = cid
        if keyword.startswith("LIST:"):
            keyword = keyword[5:]
        if keyword in self.alias_map:
            return self.alias_map[keyword]
        return keyword

    def homeContent(self, filter):
        return {'class': self.classes}

    def homeVideoContent(self):
        if self.classes:
            return self.categoryContent(self.classes[0]['type_id'], 1, {}, {})
        return {'list': []}

    def categoryContent(self, cid, page, filter, ext):
        search_keyword = self._resolve_search_keyword(cid)
        if not search_keyword:
            return {'list': []}
        # 针对多关键词的情况（如 "剧集,腾讯剧集,..."），YouTube 搜索会自行处理逗号分隔
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
        # 直接使用用户输入的关键词搜索
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
