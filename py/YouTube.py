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
        # 使用会话保持 cookies
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        })
        if self.proxies:
            self.session.proxies.update(self.proxies)
        self.channel_cache = {}
        # 硬编码分类列表（略，保持原样）
        self.classes = [
            # ... 您提供的分类列表（为了节省篇幅，此处省略，请复制之前硬编码的 classes）
        ]
        # 构建别名映射
        self.alias_map = {}
        for cls in self.classes:
            if cls['type_id'].startswith("LIST:自媒體") and "@" in cls['type_id']:
                parts = cls['type_id'].replace("LIST:自媒體", "").strip()
                for part in parts.split(","):
                    part = part.strip()
                    if part and "@" in part:
                        alias, ch_id = part.split("@", 1)
                        alias = alias.strip()
                        ch_id = ch_id.strip()
                        if alias and ch_id:
                            self.alias_map[alias] = ch_id

    def _resolve_search_keyword(self, cid):
        keyword = cid
        if keyword.startswith("LIST:"):
            keyword = keyword[5:]
        if ',' in keyword:
            keyword = keyword.split(',')[0].strip()
        if keyword in self.alias_map:
            return self.alias_map[keyword]
        # 如果是频道ID格式（如 @laogao），直接返回原样，后续使用频道视频页
        if keyword.startswith('@'):
            return keyword
        return keyword

    def _fetch_channel_videos(self, channel_id):
        """直接获取某个频道的视频列表（当关键词是 @频道ID 时）"""
        # 支持 @handle 格式
        url = f"https://www.youtube.com/@{channel_id[1:]}/videos"
        try:
            resp = self.session.get(url, timeout=10, verify=False)
            if resp.status_code != 200:
                return []
            html = resp.text
            # 提取 ytInitialData
            videos = self._extract_videos(html, 40)
            if videos:
                return videos
            # 回退提取视频ID
            video_ids = re.findall(r'watch\?v=([a-zA-Z0-9_-]{11})', html)
            seen = set()
            videos = []
            for vid in video_ids:
                if vid not in seen:
                    seen.add(vid)
                    videos.append({
                        "vod_id": vid,
                        "vod_name": f"频道视频 {vid[:8]}",
                        "vod_pic": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
                    })
                    if len(videos) >= 40:
                        break
            return videos
        except Exception as e:
            print(f"[YouTube] 获取频道视频失败: {e}")
            return []

    def categoryContent(self, cid, page, filter, ext):
        search_keyword = self._resolve_search_keyword(cid)
        if not search_keyword:
            search_keyword = "video"
        print(f"[YouTube] 分类: {cid} -> 搜索词: {search_keyword}")

        # 如果关键词是频道ID，直接访问频道视频页
        if search_keyword.startswith('@'):
            videos = self._fetch_channel_videos(search_keyword)
            if videos:
                self.channel_cache["current"] = videos
                return {
                    'list': videos,
                    'page': 1,
                    'pagecount': 1,
                    'limit': len(videos),
                    'total': len(videos),
                    'parse': 0,
                    'jx': 0
                }

        # 普通搜索
        url = f"https://www.youtube.com/results?search_query={quote(search_keyword)}&sp=EgIQAQ%3D%3D"
        try:
            resp = self.session.get(url, timeout=10, verify=False)
            html_content = resp.text
            videos = self._extract_videos(html_content, 40)
            if not videos:
                # 尝试去掉搜索词中的特殊字符或使用更通用的 fallback
                fallback_keyword = re.sub(r'[^\w\u4e00-\u9fff]+', ' ', search_keyword).strip()
                if fallback_keyword and fallback_keyword != search_keyword:
                    print(f"[YouTube] 使用fallback搜索词: {fallback_keyword}")
                    fallback_url = f"https://www.youtube.com/results?search_query={quote(fallback_keyword)}&sp=EgIQAQ%3D%3D"
                    resp2 = self.session.get(fallback_url, timeout=10, verify=False)
                    videos = self._extract_videos(resp2.text, 40)
                if not videos:
                    # 最后尝试搜索 video
                    print("[YouTube] 无结果，尝试通用搜索词 'video'")
                    last_url = f"https://www.youtube.com/results?search_query={quote('video')}&sp=EgIQAQ%3D%3D"
                    resp3 = self.session.get(last_url, timeout=10, verify=False)
                    videos = self._extract_videos(resp3.text, 40)
            self.channel_cache["current"] = videos
            if not videos:
                print("[YouTube] 警告：未提取到任何视频，请检查网络或解析代码。")
            return {
                'list': videos,
                'page': 1,
                'pagecount': 1,
                'limit': len(videos),
                'total': len(videos),
                'parse': 0,
                'jx': 0
            }
        except Exception as e:
            print(f"[YouTube] categoryContent异常: {e}")
            return {'list': [], 'parse': 0, 'jx': 0}

    def _extract_videos(self, html_content, limit=30):
        videos = []
        # 方法1: 提取 ytInitialData（新版）
        m = re.search(r'var ytInitialData\s*=\s*({.*?});', html_content, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                # 尝试不同路径
                contents = data.get('contents', {})
                # 搜索页面路径
                two_col = contents.get('twoColumnSearchResultsRenderer', {})
                primary = two_col.get('primaryContents', {})
                section = primary.get('sectionListRenderer', {})
                for cont in section.get('contents', []):
                    item_section = cont.get('itemSectionRenderer', {})
                    for item in item_section.get('contents', []):
                        video = item.get('videoRenderer')
                        if video and 'videoId' in video:
                            title = video.get('title', {}).get('runs', [{}])[0].get('text', '未知')
                            videos.append({
                                'vod_id': video['videoId'],
                                'vod_name': title,
                                'vod_pic': f"https://img.youtube.com/vi/{video['videoId']}/hqdefault.jpg"
                            })
                            if len(videos) >= limit:
                                break
                    if len(videos) >= limit:
                        break
                # 如果上面没找到，尝试其他路径（比如频道页面）
                if not videos:
                    tab = contents.get('twoColumnBrowseResultsRenderer', {})
                    tabs = tab.get('tabs', [])
                    for tab_item in tabs:
                        tab_renderer = tab_item.get('tabRenderer', {})
                        content = tab_renderer.get('content', {})
                        section_renderer = content.get('sectionListRenderer', {})
                        for cont in section_renderer.get('contents', []):
                            item_section = cont.get('itemSectionRenderer', {})
                            for item in item_section.get('contents', []):
                                video = item.get('videoRenderer')
                                if video and 'videoId' in video:
                                    title = video.get('title', {}).get('runs', [{}])[0].get('text', '未知')
                                    videos.append({
                                        'vod_id': video['videoId'],
                                        'vod_name': title,
                                        'vod_pic': f"https://img.youtube.com/vi/{video['videoId']}/hqdefault.jpg"
                                    })
                                    if len(videos) >= limit:
                                        break
                            if len(videos) >= limit:
                                break
                        if len(videos) >= limit:
                            break
            except Exception as e:
                print(f"[YouTube] 解析ytInitialData失败: {e}")

        # 方法2: 直接匹配视频ID（备胎）
        if not videos:
            # 匹配 "videoId":"..." 或 watch?v=...
            video_ids = re.findall(r'"videoId":"([^"]+)"', html_content)
            if not video_ids:
                video_ids = re.findall(r'watch\?v=([a-zA-Z0-9_-]{11})', html_content)
            seen = set()
            for vid in video_ids:
                if vid not in seen:
                    seen.add(vid)
                    # 尝试从附近提取标题
                    title_pattern = r'"title":{"runs":\[{"text":"([^"]+)"}].*?"videoId":"' + re.escape(vid) + r'"'
                    title_match = re.search(title_pattern, html_content, re.S)
                    title = title_match.group(1) if title_match else f"YouTube视频 {vid[:8]}"
                    videos.append({
                        "vod_id": vid,
                        "vod_name": title,
                        "vod_pic": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
                    })
                    if len(videos) >= limit:
                        break

        # 方法3: 如果仍然没有，尝试提取所有 a 标签中的 /watch?v= 链接
        if not videos:
            links = re.findall(r'href="(/watch\?v=[a-zA-Z0-9_-]{11})"', html_content)
            for link in links:
                vid = link.split('=')[-1]
                videos.append({
                    "vod_id": vid,
                    "vod_name": f"YouTube视频 {vid[:8]}",
                    "vod_pic": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
                })
                if len(videos) >= limit:
                    break

        return videos

    # 其余方法（homeContent, detailContent, playerContent, _get_title, _safe, localProxy, liveContent, destroy）
    # 与之前相同，这里省略重复，保留原有实现即可
    # 注意：homeContent 和 homeVideoContent 等需要返回 parse/jx 字段
