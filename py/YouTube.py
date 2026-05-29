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
        # 如果 proxy 是 "noproxy" 或空，则不使用代理
        if self.proxy_str == "noproxy":
            self.proxy_str = None
            self.proxies = {}
        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        self.channel_cache = {}
        self.classes = []
        self.alias_map = {}
        # 开启调试日志（在 OK 影视运行目录下生成 youtube_debug.log）
        self.debug_log = open(os.path.join(os.path.dirname(__file__), 'youtube_debug.log'), 'a', encoding='utf-8')
        self._log("YouTube 插件初始化")
        self._load_config()

    def _log(self, msg):
        """写入调试日志"""
        try:
            self.debug_log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")
            self.debug_log.flush()
        except:
            pass

    def _load_config(self):
        """加载分类配置，失败时使用保底分类"""
        config_loaded = False

        # 1. 尝试从 ext 中的 json 路径加载
        json_path = self.extendDict.get('json')
        if json_path:
            if json_path.startswith('./'):
                base_dir = os.path.dirname(os.path.abspath(__file__))
                abs_path = os.path.join(base_dir, json_path[2:])
            else:
                abs_path = json_path
            self._log(f"尝试加载本地配置: {abs_path}")
            if os.path.exists(abs_path):
                try:
                    with open(abs_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    self._parse_config(config)
                    config_loaded = True
                    self._log("本地配置加载成功")
                except Exception as e:
                    self._log(f"本地配置解析失败: {e}")

        # 2. 尝试远程配置
        if not config_loaded:
            remote_url = "https://raw.githubusercontent.com/zzq1234567890/tvbox1/refs/heads/main/lib/youtube.json"
            self._log(f"尝试加载远程配置: {remote_url}")
            try:
                r = requests.get(remote_url, timeout=8, proxies=self.proxies)
                if r.status_code == 200:
                    self._parse_config(r.json())
                    config_loaded = True
                    self._log("远程配置加载成功")
            except Exception as e:
                self._log(f"远程配置加载失败: {e}")

        # 3. 保底分类（使用简单有效的搜索词）
        if not config_loaded:
            self._log("使用硬编码保底分类")
            self.classes = [
                {"type_id": "音乐", "type_name": "音乐"},
                {"type_id": "电视剧", "type_name": "剧集"},
                {"type_id": "纪录片", "type_name": "纪录片"},
                {"type_id": "动画片", "type_name": "动漫"},
                {"type_id": "电影", "type_name": "电影"},
                {"type_id": "综艺节目", "type_name": "综艺"},
                {"type_id": "video", "type_name": "🔥测试搜索(应返回结果)"}
            ]
            self.alias_map = {}

    def _parse_config(self, config):
        """解析配置 JSON"""
        self.classes = []
        self.alias_map = {}
        for item in config.get("class", []):
            type_id = item.get("type_id", "").strip()
            type_name = item.get("type_name", "").strip()
            if type_id and type_name:
                self.classes.append({"type_id": type_id, "type_name": type_name})
                # 自媒体别名映射
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
        if not self.classes:
            self.classes = [{"type_id": "video", "type_name": "默认搜索"}]

    def _resolve_search_keyword(self, cid):
        """
        将分类ID转换为有效的搜索词
        - 去掉 "LIST:" 前缀
        - 如果包含逗号，取第一个有效部分
        - 如果命中别名映射则使用映射值
        """
        keyword = cid
        if keyword.startswith("LIST:"):
            keyword = keyword[5:]
        # 取逗号前的第一个有效词（去掉首尾空格）
        if ',' in keyword:
            keyword = keyword.split(',')[0].strip()
        # 别名映射
        if keyword in self.alias_map:
            return self.alias_map[keyword]
        # 如果关键词是“热门视频”，映射为“trending”
        if keyword == "热门视频" or keyword == "默认搜索":
            return "youtube trending"
        # 如果关键词是“视频”之类，直接保留
        return keyword

    def homeContent(self, filter):
        self._log(f"返回分类列表，数量: {len(self.classes)}")
        return {'class': self.classes}

    def homeVideoContent(self):
        if self.classes:
            return self.categoryContent(self.classes[0]['type_id'], 1, {}, {})
        return {'list': []}

    def categoryContent(self, cid, page, filter, ext):
        search_keyword = self._resolve_search_keyword(cid)
        if not search_keyword:
            self._log(f"分类 {cid} 解析后关键词为空")
            return {'list': []}
        self._log(f"搜索关键词: {search_keyword} (原始分类: {cid})")
        
        # 第一次搜索
        videos = self._search_youtube(search_keyword)
        if not videos:
            # 如果搜索失败，尝试使用更通用的关键词再搜一次
            fallback_keyword = "video"
            self._log(f"首次搜索无结果，尝试通用词: {fallback_keyword}")
            videos = self._search_youtube(fallback_keyword)
        
        self._log(f"获取到 {len(videos)} 个视频")
        self.channel_cache["current"] = videos
        return {
            'list': videos,
            'page': 1,
            'pagecount': 1,
            'limit': len(videos),
            'total': len(videos)
        }

    def _search_youtube(self, keyword, retry=2):
        """执行YouTube搜索，返回视频列表"""
        url = f"https://www.youtube.com/results?search_query={quote(keyword)}&sp=EgIQAQ%3D%3D"
        for attempt in range(retry):
            try:
                self._log(f"请求URL: {url} (尝试 {attempt+1})")
                r = requests.get(url, headers=self.header, timeout=10, proxies=self.proxies, stream=True)
                # 只读取前 256KB，避免过大
                html_content = r.raw.read(256 * 1024).decode('utf-8', 'ignore')
                r.close()
                videos = self._extract_videos(html_content, 50)
                if videos:
                    return videos
                self._log(f"第{attempt+1}次请求未解析到视频，可能需更换关键词")
            except Exception as e:
                self._log(f"搜索异常: {e}")
                if attempt < retry-1:
                    time.sleep(1)
        return []

    def searchContent(self, key, quick, pg=1):
        self._log(f"用户搜索关键词: {key}")
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
        """从HTML中提取视频列表"""
        videos = []
        # 查找 ytInitialData
        m = re.search(r'var ytInitialData\s*=\s*({.*?});', html_content, re.S)
        if not m:
            self._log("未找到 ytInitialData")
            # 尝试另一种正则：ytInitialData = {...}; 可能有换行
            m = re.search(r'ytInitialData\s*=\s*({.*?});', html_content, re.S)
            if not m:
                return []
        try:
            data = json.loads(m.group(1))
            # 搜索结果路径
            items = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {}).get("primaryContents", {}).get("sectionListRenderer", {}).get("contents", [])
            if not items:
                # 可能是其他布局，尝试备用路径
                items = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
                if items:
                    items = items[0].get("tabRenderer", {}).get("content", {}).get("sectionListRenderer", {}).get("contents", [])
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
        except Exception as e:
            self._log(f"解析视频列表异常: {e}")
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
        try:
            self.debug_log.close()
        except:
            pass
