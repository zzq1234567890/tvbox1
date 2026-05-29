# coding=utf-8
#!/usr/bin/python
import re
import sys
import json
import time
import requests
import os
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
        
        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        
        self.channel_cache = {}
        self.config = self._load_config()

    def _load_config(self):
        try:
            config_path = os.path.join(os.path.dirname(__file__), "youtube.json")
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {"class": []}
        except:
            return {"class": []}

    def homeContent(self, filter):
        return {
            'class': self.config.get('class', []),
            'filters': self.config.get('filters', {})
        }

    def homeVideoContent(self):
        return self.categoryContent("華語音樂", 1, {}, {})

    def categoryContent(self, cid, page, filter, ext):
        if cid.startswith("LIST:"):
            cid = cid.split(":", 1)[1].split(",")[0]

        query = cid
        is_live = any(kw in cid for kw in ["直播", "Live", "新聞直播", "體育直播", "赛事直播"])

        # 直播專用參數
        sp_param = "EgJAAQ%3D%3D" if is_live else "EgIQAQ%3D%3D"
        
        if ext and isinstance(ext, dict):
            for k, v in ext.items():
                if v and v != "":
                    query += f" {v}"

        url = f"https://www.youtube.com/results?search_query={quote(query)}&sp={sp_param}"
        
        try:
            r = requests.get(url, headers=self.header, timeout=12, proxies=self.proxies, stream=True)
            html_content = r.raw.read(160 * 1024).decode('utf-8', 'ignore')
            r.close()

            videos = self._extract_videos(html_content, 40, is_live)
            self.channel_cache["current"] = videos

            return {
                'list': videos,
                'page': int(page),
                'pagecount': 1,
                'limit': len(videos),
                'total': len(videos)
            }
        except Exception as e:
            print(f"[YouTube] Error: {e}")
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        return self.categoryContent(key, pg, {}, {})

    def detailContent(self, did):
        vid = did[0]
        cache = self.channel_cache.get("current", [])
        video_item = next((v for v in cache if v.get('vod_id') == vid), None)
        
        title = video_item.get('vod_name', '') if video_item else self._get_title(vid)
        remarks = video_item.get('vod_remarks', 'YouTube') if video_item else 'YouTube'

        episode_list = [f"{self._safe(v.get('vod_name',''))}${v.get('vod_id','')}" for v in cache]

        vod = {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg",
            "vod_remarks": remarks,
            "vod_play_from": "YouTube",
            "vod_play_url": f"{self._safe(title)}${vid}"
        }
        
        if episode_list:
            vod["vod_play_url"] += "#" + "#".join(episode_list)
            
        return {'list': [vod]}

    def playerContent(self, flag, pid, vipFlags):
        vid = pid.split('$')[-1]
        t = int(time.time())
        return {
            "parse": 1,
            "url": f"https://www.youtube.com/watch?v={vid}&t={t}",
            "header": {
                "User-Agent": self.header["User-Agent"],
                "Referer": f"https://www.youtube.com/watch?v={vid}",
            },
            "proxy": self.proxy_str
        }

    def _extract_videos(self, html_content, limit=40, is_live=False):
        videos = []
        m = re.search(r'var ytInitialData\s*=\s*({.+?});', html_content, re.S | re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                contents = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {}) \
                            .get("primaryContents", {}).get("sectionListRenderer", {}).get("contents", [])
                
                for section in contents:
                    for item in section.get("itemSectionRenderer", {}).get("contents", []):
                        r = item.get("videoRenderer") or item.get("compactVideoRenderer")
                        if r and r.get("videoId"):
                            title = r.get("title", {}).get("runs", [{}])[0].get("text", "未知")
                            live_badge = ""
                            
                            # 檢測直播標記
                            if is_live or any(b in str(r) for b in ["LIVE", "直播", "正在直播"]):
                                live_badge = "🔴 直播中 "
                            
                            videos.append({
                                "vod_id": r["videoId"],
                                "vod_name": live_badge + title,
                                "vod_pic": f"https://img.youtube.com/vi/{r['videoId']}/hqdefault.jpg",
                                "vod_remarks": "LIVE" if live_badge else ""
                            })
                            if len(videos) >= limit:
                                return videos
            except:
                pass

        # 備用提取
        if len(videos) < 10:
            pattern = r'"videoId":"([^"]+)"[^}]*?"title"[^}]*?"text":"([^"]+)"'
            for match in re.finditer(pattern, html_content, re.DOTALL):
                vid, name = match.group(1), match.group(2)
                if vid:
                    live_badge = "🔴 直播中 " if is_live else ""
                    videos.append({
                        "vod_id": vid,
                        "vod_name": live_badge + html.unescape(name),
                        "vod_pic": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
                    })
                    if len(videos) >= limit:
                        break
        return videos

    def _get_title(self, vid):
        try:
            r = requests.get(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json",
                           timeout=5, proxies=self.proxies)
            return r.json().get("title", "YouTube視頻")
        except:
            return "YouTube視頻"

    def _safe(self, t):
        if not t:
            return "未知"
        t = re.sub(r'[\\/:*?"<>|&#$\[\]]', '·', str(t))
        return t.strip()[:80]

    def destroy(self):
        pass
