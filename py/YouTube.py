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
        if self.proxy_str == "noproxy":
            self.proxy_str = None
            self.proxies = {}
        
        # 使用更真实的浏览器 Headers + 常见 Cookie（避免无 cookie 被拦截）
        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "Cookie": "CONSENT=YES+; VISITOR_INFO1_LIVE=xyz; PREF=tz=Asia.Shanghai;"  # 基本 cookie
        }
        self.session = requests.Session()
        self.session.headers.update(self.header)
        self.channel_cache = {}
        self.classes = []
        self.alias_map = {}
        self.debug_dir = os.path.dirname(os.path.abspath(__file__))
        self._log("YouTube 插件初始化")
        self._load_config()

    def _log(self, msg):
        try:
            with open(os.path.join(self.debug_dir, 'youtube_debug.log'), 'a', encoding='utf-8') as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")
        except:
            pass

    def _load_config(self):
        config_loaded = False
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
        if not config_loaded:
            self._log("使用硬编码保底分类")
            self.classes = [
                {"type_id": "音乐", "type_name": "音乐"},
                {"type_id": "电视剧", "type_name": "剧集"},
                {"type_id": "纪录片", "type_name": "纪录片"},
                {"type_id": "动画片", "type_name": "动漫"},
                {"type_id": "电影", "type_name": "电影"},
                {"type_id": "综艺节目", "type_name": "综艺"},
                {"type_id": "video", "type_name": "测试搜索"}
            ]
            self.alias_map = {}

    def _parse_config(self, config):
        self.classes = []
        self.alias_map = {}
        for item in config.get("class", []):
            type_id = item.get("type_id", "").strip()
            type_name = item.get("type_name", "").strip()
            if type_id and type_name:
                self.classes.append({"type_id": type_id, "type_name": type_name})
        if not self.classes:
            self.classes = [{"type_id": "video", "type_name": "默认搜索"}]

    def _resolve_search_keyword(self, cid):
        keyword = cid
        if keyword.startswith("LIST:"):
            keyword = keyword[5:]
        if ',' in keyword:
            keyword = keyword.split(',')[0].strip()
        if keyword in self.alias_map:
            return self.alias_map[keyword]
        if keyword in ["热门视频", "默认搜索"]:
            return "youtube trending"
        return keyword

    def homeContent(self, filter):
        self._log(f"返回分类数量: {len(self.classes)}")
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
        self._log(f"搜索关键词: {search_keyword}")
        videos = self._search_youtube(search_keyword)
        self._log(f"获取到 {len(videos)} 个视频")
        self.channel_cache["current"] = videos
        return {
            'list': videos,
            'page': 1,
            'pagecount': 1,
            'limit': len(videos),
            'total': len(videos)
        }

    def _search_youtube(self, keyword):
        url = f"https://www.youtube.com/results?search_query={quote(keyword)}&sp=EgIQAQ%3D%3D"
        self._log(f"请求URL: {url}")
        try:
            response = self.session.get(url, timeout=15, proxies=self.proxies)
            self._log(f"HTTP状态码: {response.status_code}")
            self._log(f"最终URL: {response.url}")
            if response.status_code != 200:
                self._log(f"请求失败，状态码: {response.status_code}")
                return []
            
            html = response.text
            self._log(f"响应长度: {len(html)} 字符")
            # 保存 HTML 用于调试
            with open(os.path.join(self.debug_dir, 'youtube_debug.html'), 'w', encoding='utf-8') as f:
                f.write(html)
            
            # 方法1: 解析 ytInitialData
            videos = self._extract_videos(html)
            if videos:
                return videos
            
            # 方法2: 直接提取所有 videoId
            video_ids = re.findall(r'"videoId":"([^"]+)"', html)
            if not video_ids:
                # 尝试另一种 pattern
                video_ids = re.findall(r'watch\?v=([a-zA-Z0-9_-]{11})', html)
            unique_ids = list(dict.fromkeys(video_ids))[:30]
            self._log(f"通过正则找到 {len(unique_ids)} 个 videoId")
            for vid in unique_ids:
                videos.append({
                    "vod_id": vid,
                    "vod_name": f"YouTube视频 {vid[:8]}",
                    "vod_pic": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
                })
            return videos
        except Exception as e:
            self._log(f"搜索异常: {e}")
            import traceback
            self._log(traceback.format_exc())
            return []

    def searchContent(self, key, quick, pg=1):
        self._log(f"用户搜索: {key}")
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

    def _extract_videos(self, html, limit=30):
        videos = []
        # 提取 ytInitialData
        m = re.search(r'var ytInitialData\s*=\s*({.*?});', html, re.S)
        if not m:
            self._log("未找到 ytInitialData")
            return []
        try:
            data = json.loads(m.group(1))
            # 搜索结果路径
            two_column = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {})
            if not two_column:
                two_column = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {})
            primary = two_column.get("primaryContents", {})
            section_list = primary.get("sectionListRenderer", {})
            contents = section_list.get("contents", [])
            for section in contents:
                item_section = section.get("itemSectionRenderer", {})
                for item in item_section.get("contents", []):
                    v = item.get("videoRenderer")
                    if v and "videoId" in v:
                        title = v.get("title", {}).get("runs", [{}])[0].get("text", "未知")
                        videos.append({
                            "vod_id": v["videoId"],
                            "vod_name": title,
                            "vod_pic": f"https://img.youtube.com/vi/{v['videoId']}/hqdefault.jpg"
                        })
                        if len(videos) >= limit:
                            break
        except Exception as e:
            self._log(f"解析 ytInitialData 异常: {e}")
        return videos

    def _get_title(self, vid):
        try:
            r = self.session.get(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json", timeout=3)
            return r.json().get("title", "YouTube视频")
        except:
            return "YouTube视频"

    def _safe(self, t):
        return "".join([c if c.isalnum() or c in "· " else "·" for c in t])[:80]

    def destroy(self):
        pass
