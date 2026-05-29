# coding=utf-8
#!/usr/bin/python
import re
import sys
import os
import json
import time
import requests
from urllib.parse import quote

sys.path.append('..')
from base.spider import Spider

class Spider(Spider):
    def getName(self):
        return "YouTube视频"

    def init(self, extend=""):
        try:
            self.extendDict = json.loads(extend) if isinstance(extend, str) else extend
        except:
            self.extendDict = {}
            
        # 代理设置
        self.proxies = self.extendDict.get('proxy', {})
        self.proxy_str = self.extendDict.get('proxy_str', None)
        
        # 请求头
        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        
        # 缓存与配置
        self.channel_cache = {}
        self.config = {}
        
        # 读取 youtube.json 配置 (默认与py同目录，即lib目录下)
        try:
            base_path = os.path.dirname(os.path.abspath(__file__))
            json_path = os.path.join(base_path, '/lib/youtube.json')
            if os.path.exists(json_path):
                with open(json_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
        except Exception as e:
            print(f"[YouTube] Load config error: {e}")

    def homeContent(self, filter):
        result = {'class': [], 'filters': {}}
        if self.config:            result['class'] = self.config.get('class', [])
            if filter:
                result['filters'] = self.config.get('filters', {})
        else:
            # 兜底：如果json读取失败，使用简单默认值
            result['class'] = [{'type_id': '华语音乐', 'type_name': '华语音乐'}]
        return result

    def homeVideoContent(self):
        # 尝试获取推荐内容，如果没有则用第一个分类
        recommend = self.config.get('recommend', '')
        cid = recommend.split('|')[0].replace('LIST:', '') if recommend else '华语音乐'
        return self.categoryContent(cid, 1, {}, {})

    def categoryContent(self, cid, page, filter, ext):
        # 构建搜索词
        search_key = cid
        
        # 处理 LIST: 开头的复合分类，取第一个有效词或组合
        if search_key.startswith('LIST:'):
            parts = [p.strip() for p in search_key.replace('LIST:', '').split(',') if p.strip()]
            search_key = parts[0] if parts else ''
            
        # 合并筛选器参数 (ext 包含用户选择的 tid, time 等)
        if ext:
            # 优先使用 tid (频道/细分类型)，其次追加 time
            tid_val = ext.get('tid', '')
            time_val = ext.get('time', '')
            
            if tid_val:
                # 如果选择了具体频道或细分标签，替换或追加到搜索词
                # 对于 @ 开头的频道ID，直接作为核心搜索词效果更好
                if tid_val.startswith('@'):
                    search_key = tid_val
                else:
                    search_key = f"{tid_val} {search_key}"
                    
            if time_val and time_val.strip():
                search_key = f"{search_key} {time_val}"

        url = f"https://www.youtube.com/results?search_query={quote(search_key)}&sp=EgIQAQ%3D%3D"
        
        try:
            # 响应截断：只获取前 64KB，防止阻塞
            r = requests.get(url, headers=self.header, timeout=8, proxies=self.proxies, stream=True)
            html_content = r.raw.read(64 * 1024).decode('utf-8', 'ignore')
            r.close()
            
            videos = self._extract_videos(html_content, 50)
            self.channel_cache["current"] = videos            return {
                'list': videos, 
                'page': 1, 
                'pagecount': 1, 
                'limit': len(videos), 
                'total': len(videos)
            }
        except Exception as e:
            print(f"[YouTube] Category Error: {e}")
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
        m = re.search(r'var ytInitialData\s*=\s*({.*?});', html_content, re.S)
        if not m:             return []
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
                if len(videos) >= limit:
                    break
        except Exception as e:
            print(f"[YouTube] Extract Error: {e}")
        return videos

    def _get_title(self, vid):
        try:
            r = requests.get(
                f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json", 
                timeout=3, 
                proxies=self.proxies
            )
            return r.json().get("title", "YouTube视频")
        except:
            return "YouTube视频"

    def _safe(self, t):
        return "".join([c if c.isalnum() or c in "· " else "·" for c in t])[:80]

    def destroy(self):
        pass
