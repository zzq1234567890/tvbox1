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
        # 远程配置 URL
        self.config_url = "https://raw.githubusercontent.com/zzq1234567890/tvbox1/refs/heads/main/lib/youtube.json"
        self.classes = []          # 分类列表
        self.alias_map = {}        # 别名映射（用于自媒体等）
        self._load_config()

    def _load_config(self):
        """从远程URL加载分类配置"""
        try:
            r = requests.get(self.config_url, timeout=8, proxies=self.proxies)
            config = r.json()
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
                    # 处理自媒体别名映射（格式：别名 @频道ID）
                    if type_id.startswith("LIST:自媒體") and "@" in type_id:
                        parts = type_id.replace("LIST:自媒體", "").strip()
                        for part in parts.split(","):
                            part = part.strip()
                            if part and "@" in part:
                                alias, ch_id = part.split("@", 1)
                                alias = alias.strip()
                                ch_id = ch_id.strip()
                                if alias and ch_id:
                                    self.alias_map[alias] = ch_id
            print(f"[YouTube] 加载到 {len(self.classes)} 个分类")
        except Exception as e:
            print(f"[YouTube] 加载配置失败: {e}")
            # 保底分类
            self.classes = [
                {"type_id": "音乐", "type_name": "音乐"},
                {"type_id": "电影", "type_name": "电影"},
                {"type_id": "电视剧", "type_name": "剧集"},
                {"type_id": "video", "type_name": "热门视频"}
            ]

    def _resolve_search_keyword(self, cid):
        """将分类ID转换为有效的YouTube搜索关键词"""
        keyword = cid
        # 去掉 LIST: 前缀
        if keyword.startswith("LIST:"):
            keyword = keyword[5:]
        # 如果包含逗号，取第一个有效关键词（去除空格）
        if ',' in keyword:
            keyword = keyword.split(',')[0].strip()
        # 别名映射
        if keyword in self.alias_map:
            return self.alias_map[keyword]
        # 针对一些特殊分类做映射
        if keyword in ["短劇", "电影", "體育", "科技", "解說", "神秘", "动画片", "時尚潮流", "放松", "4K", "宇宙", "GETTRENDS"]:
            # 这些分类直接使用原词作为搜索词
            return keyword
        # 对于其他情况，直接返回关键词（可能为空）
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
            # 保底关键词
            search_keyword = "video"
        print(f"[YouTube] 分类: {cid} -> 搜索词: {search_keyword}")
        url = f"https://www.youtube.com/results?search_query={quote(search_keyword)}&sp=EgIQAQ%3D%3D"
        try:
            r = requests.get(url, headers=self.header, timeout=10, proxies=self.proxies, stream=True)
            # 读取前256KB
            html_content = r.raw.read(256 * 1024).decode('utf-8', 'ignore')
            r.close()
            videos = self._extract_videos(html_content, 40)
            # 如果没有视频，尝试使用更通用的关键词再搜一次
            if not videos and search_keyword not in ["video", "youtube trending"]:
                fallback_url = f"https://www.youtube.com/results?search_query={quote('video')}&sp=EgIQAQ%3D%3D"
                r2 = requests.get(fallback_url, headers=self.header, timeout=10, proxies=self.proxies, stream=True)
                html2 = r2.raw.read(256 * 1024).decode('utf-8', 'ignore')
                r2.close()
                videos = self._extract_videos(html2, 40)
                if videos:
                    print(f"[YouTube] 使用fallback搜索词'video'获取到{len(videos)}个视频")
            self.channel_cache["current"] = videos
            return {
                'list': videos,
                'page': 1,
                'pagecount': 1,
                'limit': len(videos),
                'total': len(videos)
            }
        except Exception as e:
            print(f"[YouTube] categoryContent异常: {e}")
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
        # 方法1: 提取 ytInitialData
        m = re.search(r'var ytInitialData\s*=\s*({.*?});', html_content, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                items = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {})
                items = items.get("primaryContents", {}).get("sectionListRenderer", {}).get("contents", [])
                for section in items:
                    vids = section.get("itemSectionRenderer", {}).get("contents", [])
                    for item in vids:
                        r = item.get("videoRenderer")
                        if r and "videoId" in r:
                            title = r.get("title", {}).get("runs", [{}])[0].get("text", "未知")
                            videos.append({
                                "vod_id": r["videoId"],
                                "vod_name": title,
                                "vod_pic": f"https://img.youtube.com/vi/{r['videoId']}/hqdefault.jpg"
                            })
                            if len(videos) >= limit:
                                break
            except:
                pass
        # 如果方法1没有结果，使用正则直接提取videoId
        if not videos:
            video_ids = re.findall(r'"videoId":"([^"]+)"', html_content)
            if not video_ids:
                video_ids = re.findall(r'watch\?v=([a-zA-Z0-9_-]{11})', html_content)
            seen = set()
            for vid in video_ids:
                if vid not in seen:
                    seen.add(vid)
                    videos.append({
                        "vod_id": vid,
                        "vod_name": f"YouTube视频 {vid[:8]}",
                        "vod_pic": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
                    })
                    if len(videos) >= limit:
                        break
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
