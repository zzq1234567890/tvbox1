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
        # 硬编码分类列表（完全按照您提供的 JSON）
        self.classes = [
            {"type_id": "LIST:新闻 Live,体育直播,赛事直播", "type_name": "新聞直播"},
            {"type_id": "LIST:剧集,腾讯剧集,爱奇艺剧集,优酷剧集,芒果剧集,TVB,亞視精選,ATV 亞洲電視,八大劇樂部,民視戲劇,三立台劇,三立華劇,龍華戲劇,華視懷舊頻道,華視戲劇,中視經典戲劇", "type_name": "劇集"},
            {"type_id": "LIST:紀錄片,亞洲旅遊台,CCTV纪录,CCTV科教,公視+,National Geographic,Kevin_YOLO,Nat Geo Animals,BBC Earth,Top Travel,National Geographic India,BBC Earth Science,历史纪录片,自然纪录片,宇宙纪录片", "type_name": "紀錄片"},
            {"type_id": "LIST:動漫,腾讯视频 - 动漫,一号动漫社 Animation Club,蒼穹動漫社Animation Club,斗破动漫社 Animation,腾讯动漫,爱奇艺动漫,优酷动漫,芒果动漫,Ani-Mi動漫迷動畫頻道,3D国漫工厂,阅文动漫,卡通狂欢嘉会", "type_name": "動漫"},
            {"type_id": "短劇", "type_name": "短劇"},
            {"type_id": "LIST:综艺,台視時光機,芒果综艺,腾讯综艺,爱奇艺综艺,优酷综艺,卫视综艺,超級夜總會", "type_name": "綜藝"},
            {"type_id": "電影", "type_name": "電影"},
            {"type_id": "LIST:政論,觀點,豐富,Yahoo風向,全球大視野,環球大戰線,郭正亮頻道,論政天下,岑永康", "type_name": "政論"},
            {"type_id": "體育", "type_name": "體育"},
            {"type_id": "時尚潮流", "type_name": "時尚潮流"},
            {"type_id": "放松", "type_name": "放松"},
            {"type_id": "4K", "type_name": "4K"},
            {"type_id": "宇宙", "type_name": "科普知識"},
            {"type_id": "GETTRENDS", "type_name": "Youtube Trends"},
            {"type_id": "LIST:自媒體 We Media,老高與小茉 @laogao,脑洞乌托邦 @NDWTB,自说自话的总裁 @STBoss,纪实说 @C-Documentary,老肉雜談 @老肉雜談,李永樂老師 @TchLiyongle,滇西小哥 @dianxixiaoge,李子柒 Liziqi @cnliziqi,老饭骨 @LaoFanGu,小高姐的 Magic Ingredients @MagicIngredients,小穎美食 @XiaoYingFood,primitivetechnology9550 @primitivetechnology9550,Mr Beast@MrBeast,Airforceproud95 @Airforceproud95,TheGreatWar @TheGreatWar,Mark Rober @MarkRober,不良林,涌哥侃侃 @ygkkk,悟空的日常", "type_name": "自媒體"},
            {"type_id": "LIST:HDR,Girls HDR,Landscape HDR,Walk HDR", "type_name": "HDR"},
            {"type_id": "LIST:华语音乐,华语MV,点击率最高", "type_name": "音樂"},
            {"type_id": "科技", "type_name": "科技"},
            {"type_id": "解說", "type_name": "解說"},
            {"type_id": "神秘", "type_name": "神秘"},
            {"type_id": "动画片", "type_name": "动画片"}
        ]
        # 构建别名映射（用于自媒体频道，格式：别名@频道ID）
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
        """将分类ID转换为有效的YouTube搜索关键词"""
        keyword = cid
        # 去掉 LIST: 前缀
        if keyword.startswith("LIST:"):
            keyword = keyword[5:]
        # 如果包含逗号，取第一个有效关键词（去除空格）
        if ',' in keyword:
            keyword = keyword.split(',')[0].strip()
        # 别名映射（主要针对自媒体频道名直接映射为频道ID）
        if keyword in self.alias_map:
            return self.alias_map[keyword]
        # 对于普通中文分类，直接返回原词
        return keyword

    def homeContent(self, filter):
        return {'class': self.classes, 'parse': 0, 'jx': 0}

    def homeVideoContent(self):
        if self.classes:
            return self.categoryContent(self.classes[0]['type_id'], 1, {}, {})
        return {'list': [], 'parse': 0, 'jx': 0}

    def categoryContent(self, cid, page, filter, ext):
        search_keyword = self._resolve_search_keyword(cid)
        if not search_keyword:
            search_keyword = "video"
        print(f"[YouTube] 分类: {cid} -> 搜索词: {search_keyword}")
        url = f"https://www.youtube.com/results?search_query={quote(search_keyword)}&sp=EgIQAQ%3D%3D"
        try:
            r = requests.get(url, headers=self.header, timeout=10, proxies=self.proxies, stream=True, verify=False)
            html_content = r.raw.read(256 * 1024).decode('utf-8', 'ignore')
            r.close()
            videos = self._extract_videos(html_content, 40)
            if not videos and search_keyword not in ["video", "youtube trending"]:
                fallback_url = f"https://www.youtube.com/results?search_query={quote('video')}&sp=EgIQAQ%3D%3D"
                r2 = requests.get(fallback_url, headers=self.header, timeout=10, proxies=self.proxies, stream=True, verify=False)
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
                'total': len(videos),
                'parse': 0,
                'jx': 0
            }
        except Exception as e:
            print(f"[YouTube] categoryContent异常: {e}")
            return {'list': [], 'parse': 0, 'jx': 0}

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
        return {'list': [vod], 'parse': 0, 'jx': 0}

    def playerContent(self, flag, id, vipFlags):
        # 兼容旧调用方式：id 可能是 "标题$vid" 格式，取最后一部分作为视频ID
        vid = id.split('$')[-1]
        return {
            "parse": 1,           # 让外部解析器解析 YouTube 页面
            "jx": 0,
            "playUrl": "",
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
            r = requests.get(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json", timeout=3, proxies=self.proxies, verify=False)
            return r.json().get("title", "YouTube视频")
        except:
            return "YouTube视频"

    def _safe(self, t):
        return "".join([c if c.isalnum() or c in "· " else "·" for c in t])[:80]

    def localProxy(self, param):
        return [200, "text/plain", "YouTube Spider Local Proxy"]

    def liveContent(self, url):
        pass

    def destroy(self):
        pass
