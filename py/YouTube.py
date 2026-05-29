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
        self.classes = []          # 分类列表
        self.alias_map = {}        # 别名映射
        # 加载配置
        self._load_config()

    def _load_config(self):
        """加载分类配置（优先本地json，失败则使用硬编码默认分类）"""
        config_loaded = False

        # 1. 尝试从 ext 中的 json 路径加载
        json_path = self.extendDict.get('json')
        if json_path:
            # 处理相对路径
            if json_path.startswith('./'):
                base_dir = os.path.dirname(os.path.abspath(__file__))
                abs_path = os.path.join(base_dir, json_path[2:])
            else:
                abs_path = json_path
            print(f"[YouTube] 尝试加载本地配置: {abs_path}")
            if os.path.exists(abs_path):
                try:
                    with open(abs_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    self._parse_config(config)
                    config_loaded = True
                    print("[YouTube] 本地配置加载成功")
                except Exception as e:
                    print(f"[YouTube] 本地配置解析失败: {e}")

        # 2. 尝试远程默认地址
        if not config_loaded:
            remote_url = "https://raw.githubusercontent.com/zzq1234567890/tvbox1/refs/heads/main/lib/youtube.json"
            print(f"[YouTube] 尝试加载远程配置: {remote_url}")
            try:
                r = requests.get(remote_url, timeout=8, proxies=self.proxies)
                if r.status_code == 200:
                    self._parse_config(r.json())
                    config_loaded = True
                    print("[YouTube] 远程配置加载成功")
            except Exception as e:
                print(f"[YouTube] 远程配置加载失败: {e}")

        # 3. 保底：使用硬编码的常用分类（从你提供的 youtube.json 中提取）
        if not config_loaded:
            print("[YouTube] 使用硬编码默认分类")
            self.classes = [
                {"type_id": "LIST:华语音乐,华语MV,点击率最高", "type_name": "音乐"},
                {"type_id": "LIST:剧集,腾讯剧集,爱奇艺剧集,优酷剧集", "type_name": "剧集"},
                {"type_id": "LIST:紀錄片,国家地理,BBC Earth", "type_name": "纪录片"},
                {"type_id": "LIST:動漫,腾讯动漫,爱奇艺动漫", "type_name": "动漫"},
                {"type_id": "电影", "type_name": "电影"},
                {"type_id": "LIST:综艺,芒果综艺,腾讯综艺", "type_name": "综艺"},
                {"type_id": "热门视频", "type_name": "热门推荐"}   # 最后的保底分类
            ]
            # 简单别名映射示例（如果需要可自行添加）
            self.alias_map = {}

    def _parse_config(self, config):
        """解析配置 JSON，构建分类列表和别名映射"""
        self.classes = []
        self.alias_map = {}
        for item in config.get("class", []):
            type_id = item.get("type_id", "").strip()
            type_name = item.get("type_name", "").strip()
            if type_id and type_name:
                self.classes.append({"type_id": type_id, "type_name": type_name})
                # 处理自媒体别名映射
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
        # 如果解析后没有分类，添加一个保底
        if not self.classes:
            self.classes = [{"type_id": "热门视频", "type_name": "热门推荐"}]

    def _resolve_search_keyword(self, cid):
        """将分类ID转换为实际搜索关键词，优化多关键词情况"""
        keyword = cid
        if keyword.startswith("LIST:"):
            keyword = keyword[5:]
        # 如果包含逗号，只取第一个关键词（YouTube 搜索多个关键词效果差）
        if ',' in keyword:
            keyword = keyword.split(',')[0].strip()
        # 别名映射
        if keyword in self.alias_map:
            return self.alias_map[keyword]
        # 特殊处理：如果 keyword 是 "热门视频"，改为通用关键词
        if keyword == "热门视频":
            return "youtube trending"
        return keyword

    def homeContent(self, filter):
        print(f"[YouTube] 返回分类数量: {len(self.classes)}")
        return {'class': self.classes}

    def homeVideoContent(self):
        if self.classes:
            return self.categoryContent(self.classes[0]['type_id'], 1, {}, {})
        return {'list': []}

    def categoryContent(self, cid, page, filter, ext):
        search_keyword = self._resolve_search_keyword(cid)
        if not search_keyword:
            print(f"[YouTube] 分类 {cid} 解析后关键词为空")
            return {'list': []}
        print(f"[YouTube] 搜索关键词: {search_keyword} (原始分类: {cid})")
        url = f"https://www.youtube.com/results?search_query={quote(search_keyword)}&sp=EgIQAQ%3D%3D"
        try:
            r = requests.get(url, headers=self.header, timeout=10, proxies=self.proxies, stream=True)
            # 只读取前 128KB，避免过大
            html_content = r.raw.read(128 * 1024).decode('utf-8', 'ignore')
            r.close()
            videos = self._extract_videos(html_content, 50)
            print(f"[YouTube] 获取到 {len(videos)} 个视频")
            self.channel_cache["current"] = videos
            return {
                'list': videos,
                'page': 1,
                'pagecount': 1,
                'limit': len(videos),
                'total': len(videos)
            }
        except Exception as e:
            print(f"[YouTube] 搜索异常: {e}")
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        print(f"[YouTube] 搜索关键词: {key}")
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
            print("[YouTube] 未找到 ytInitialData")
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
        except Exception as e:
            print(f"[YouTube] 解析视频列表异常: {e}")
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
