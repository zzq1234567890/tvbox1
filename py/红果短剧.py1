from base.spider import Spider
import requests
import re
import urllib.parse
import json
import time

SITE = "https://hongguoduanju.com"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36'
}
timeout = 15
CATEGORY_MAP = {
    "热门": "sort_type=1",
    "最新": "sort_type=2",
    "都市": "background=cate_1",
    "现代": "background=cate_757",
    "古代": "background=cate_758",
    "乡村": "background=cate_11",
    "职场": "background=cate_127",
    "校园": "background=cate_4",
    "悬疑": "topic=cate_165",
    "喜剧": "topic=cate_303",
    "重生": "setting=cate_36",
    "穿越": "setting=cate_37",
}
_cache = {}

class Spider(Spider):
    def getName(self):
        return "小心儿悠悠"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def _get(self, url):
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    def _router_data(self, url):
        cached = _cache.get(url)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        html = self._get(url)
        match = re.search(
            r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>",
            html,
            re.S,
        )
        if not match:
            raise RuntimeError("未找到 _ROUTER_DATA")
        data = json.loads(match.group(1))
        _cache[url] = (time.time(), data)
        return data

    @staticmethod
    def _vod(item):
        tags = item.get("tags") or []
        if isinstance(tags, list):
            tags = " · ".join(str(x) for x in tags[:3])
        count = item.get("episode_cnt") or len(item.get("vid_list") or [])
        remark = ("全%s集" % count) if count else str(tags or "")
        return {
            "vod_id": f"series_id={item.get('series_id', '')}",
            "vod_name": str(item.get("series_name") or ""),
            "vod_pic": str(item.get("series_cover") or ""),
            "vod_remarks": remark,
        }

    def _category_items(self, query):
        url = SITE + "/category?" + query
        data = self._router_data(url)
        page = data.get("loaderData", {}).get("category_page", {})
        items = page.get("recommendList") or []
        if not items:
            items = page.get("categoryData", {}).get("recommendList") or []
        seen = set()
        result = []
        for item in items:
            sid = str(item.get("series_id") or "")
            if sid and sid not in seen:
                seen.add(sid)
                result.append(item)
        return result

    def _search_items(self, keyword, page=1):
        url = SITE + "/search?keyword=" + urllib.parse.quote(keyword) + "&page=" + str(page)
        data = self._router_data(url)
        search_page = data.get("loaderData", {}).get("search_page", {})
        return search_page.get("searchResult") or []

    def homeContent(self, filter):
        classes = [{"type_id": query, "type_name": name} for name, query in CATEGORY_MAP.items()]
        home_list = []
        try:
            items = self._category_items("sort_type=1")[:30]
            home_list = [self._vod(x) for x in items]
        except Exception as e:
            print("首页推荐加载失败:", e)
        return {"class": classes, "list": home_list}

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, cid, pg, filter, ext):
        page = int(pg) if pg else 1
        per_page = 30
        try:
            items = self._category_items(str(cid))
            start = (page - 1) * per_page
            chunk = items[start:start + per_page]
            total = len(items)
            page_count = max(1, (total + per_page - 1) // per_page) if total else 1
            videos = [self._vod(x) for x in chunk]
            return {
                'list': videos,
                'page': page,
                'pagecount': page_count,
                'limit': per_page,
                'total': total
            }
        except Exception as e:
            print(f"分类加载失败: {e}")
            return {'list': [], 'page': page, 'pagecount': 1}

    def detailContent(self, ids):
        series_id = ids[0].split('=')[1] if '=' in ids[0] else ids[0]
        url = SITE + "/detail?series_id=" + urllib.parse.quote(series_id)
        try:
            data = self._router_data(url)
            detail = data.get("loaderData", {}).get("detail_page", {})
            series = detail.get("seriesDetail") or {}
            vids = series.get("vid_list") or []
            episodes = []
            for idx, vid in enumerate(vids):
                episodes.append(f"第{idx+1}集${vid}")
            tags = series.get("tags") or []
            if isinstance(tags, list):
                tags = ",".join(str(x) for x in tags)
            vod = {
                "vod_id": series_id,
                "vod_name": str(series.get("series_name") or ""),
                "vod_pic": str(series.get("series_cover") or ""),
                "type_name": str(tags),
                "vod_remarks": f"全{len(vids)}集",
                "vod_content": str(series.get("series_intro") or ""),
                "vod_play_from": "红果",
                "vod_play_url": "#".join(episodes)
            }
            return {"list": [vod]}
        except Exception as e:
            print("详情获取失败:", e)
            return {"list": []}

    def playerContent(self, flag, pid, vipFlags):
        # 尝试官方播放接口（需抓包确认，此处为常见猜测）
        play_api = SITE + "/api/play?vid=" + urllib.parse.quote(str(pid))
        try:
            resp = requests.get(play_api, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                play_url = data.get('url') or data.get('play_url') or data.get('data', {}).get('url')
                if play_url:
                    return {
                        "parse": 0,
                        "playUrl": "",
                        "url": play_url,
                        "header": headers
                    }
        except Exception as e:
            print("获取播放地址失败:", e)
        # 备用（仅示例，不一定有效）
        fallback_url = SITE + "/video/" + str(pid) + ".m3u8"
        return {
            "parse": 0,
            "playUrl": "",
            "url": fallback_url,
            "header": headers
        }

    def searchContent(self, key, quick, pg=1):
        page = int(pg) if pg else 1
        per_page = 30
        try:
            items = self._search_items(key, page)
            start = (page - 1) * per_page
            chunk = items[start:start + per_page]
            total = len(items)
            page_count = max(1, (total + per_page - 1) // per_page) if total else 1
            videos = [self._vod(x) for x in chunk]
            return {
                'list': videos,
                'page': page,
                'pagecount': page_count,
                'limit': per_page,
                'total': total
            }
        except Exception as e:
            print("搜索失败:", e)
            return {'list': [], 'page': page, 'pagecount': 1}        return "小心儿悠悠"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    # ---------- 辅助函数：从官方页面提取数据 ----------
    def _get(self, url):
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    def _router_data(self, url):
        cached = _cache.get(url)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        html = self._get(url)
        match = re.search(
            r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>",
            html,
            re.S,
        )
        if not match:
            raise RuntimeError("页面数据格式已变化")
        data = json.loads(match.group(1))
        _cache[url] = (time.time(), data)
        return data

    @staticmethod
    def _vod(item):
        """将官方数据项转换为统一的vod格式"""
        tags = item.get("tags") or []
        if isinstance(tags, list):
            tags = " · ".join(str(x) for x in tags[:3])
        count = item.get("episode_cnt") or len(item.get("vid_list") or [])
        remark = ("全%s集" % count) if count else str(tags or "")
        return {
            "vod_id": f"series_id={item.get('series_id', '')}",   # 使用 series_id
            "vod_name": str(item.get("series_name") or ""),
            "vod_pic": str(item.get("series_cover") or ""),
            "vod_remarks": remark,
        }

    def _category_items(self, query):
        """获取分类下的剧集列表"""
        url = SITE + "/category?" + query
        data = self._router_data(url)
        page = data.get("loaderData", {}).get("category_page", {})
        items = page.get("recommendList") or []
        if not items:
            items = page.get("categoryData", {}).get("recommendList") or []
        seen = set()
        result = []
        for item in items:
            sid = str(item.get("series_id") or "")
            if sid and sid not in seen:
                seen.add(sid)
                result.append(item)
        return result

    def _search_items(self, keyword, page=1):
        """从官方搜索页面获取结果"""
        url = SITE + "/search?keyword=" + urllib.parse.quote(keyword) + "&page=" + str(page)
        data = self._router_data(url)
        search_page = data.get("loaderData", {}).get("search_page", {})
        items = search_page.get("searchResult") or []
        return items

    # ---------- 主页分类 ----------
    def homeContent(self, filter):
        classes = []
        for name, query in CATEGORY_MAP.items():
            classes.append({"type_id": query, "type_name": name})
        # 首页推荐（可选）
        try:
            items = self._category_items("sort_type=1")[:30]
            home_list = [self._vod(x) for x in items]
        except:
            home_list = []
        return {
            "class": classes,
            "list": home_list
        }

    def homeVideoContent(self):
        # 已在 homeContent 中返回 list，此处保留空实现
        return {'list': []}

    # ---------- 分类内容 ----------
    def categoryContent(self, cid, pg, filter, ext):
        page = int(pg) if pg else 1
        per_page = 30
        try:
            items = self._category_items(str(cid))
            start = (page - 1) * per_page
            chunk = items[start:start + per_page]
            total = len(items)
            page_count = max(1, (total + per_page - 1) // per_page)
            videos = [self._vod(x) for x in chunk]
            return {
                'list': videos,
                'page': page,
                'pagecount': page_count,
                'limit': per_page,
                'total': total
            }
        except Exception as e:
            print("分类加载失败:", e)
            return {'list': [], 'page': page, 'pagecount': 1}

    # ---------- 详情（适配 series_id） ----------
    def detailContent(self, ids):
        did = ids[0]
        
        # 解析参数
        params = {}
        if '?' in did:
            queryString = did.split('?')[1]
        else:
            queryString = did
        pairs = queryString.split('&')
        for pair in pairs:
            if '=' in pair:
                k, v = pair.split('=', 1)
                params[k] = v
        
        # 优先使用 series_id
        series_id = params.get('series_id', '')
        book_id = params.get('book_id', '')
        actor = params.get('actor', '')
        fullType = params.get('type', '')
        
        # 如果没有 series_id 但有 book_id，则原样处理
        if not series_id and not book_id:
            # 尝试从 did 中提取 book_id（兼容旧格式）
            match = re.search(r'book_id=([^&]*)', did)
            if match:
                book_id = match.group(1)
        
        # 调用代理 API（优先使用 series_id，否则用 book_id）
        api_params = ""
        if series_id:
            api_params = f"series_id={series_id}"
        elif book_id:
            api_params = f"book_id={book_id}"
        else:
            return {'list': []}
        
        apiUrl = f"{base_url}?{api_params}"
        try:
            response = requests.get(url=apiUrl, headers=headers, timeout=timeout)
            if response.status_code != 200:
                return {'list': []}
            
            data = response.json()
            if data.get('code') != 200 or not data.get('data'):
                return {'list': []}
            
            vod_list = data['data']
            
            # 构建播放源（按清晰度）
            play_from = []
            play_url = []
            quality_options = [
                ("超清", "2160p"),
                ("高清", "1080p"), 
                ("标清", "720p"),
                ("低清", "480p"),
                ("流畅", "360p")
            ]
            for quality_name, quality_value in quality_options:
                urls = []
                for item in vod_list:
                    chapterName = item.get('title', '')
                    videoId = item.get('video_id', '')
                    playUrl = f"{quality_host}/duanju/api.php?video_id={videoId}&type=json&level={quality_value}"
                    urls.append(f"{chapterName}${playUrl}")
                play_from.append(quality_name)
                play_url.append("#".join(urls))
            
            # 演员信息（复用原逻辑）
            actors = []
            try:
                actor_api_url = f"{base_url}?series_id={series_id or book_id}&showRawParams=false"
                actor_response = requests.get(url=actor_api_url, headers=headers, timeout=timeout)
                if actor_response.status_code == 200:
                    actor_data = actor_response.json()
                    if actor_data.get('code') == 200 and 'celebrities' in actor_data:
                        celebrities = actor_data['celebrities']
                        if isinstance(celebrities, list):
                            for celeb in celebrities:
                                actor_name = celeb.get('user_name') or celeb.get('name') or celeb.get('actor_name') or ''
                                if actor_name and actor_name.strip() and actor_name not in actors:
                                    actors.append(actor_name)
            except Exception as e:
                print(f"获取演员信息失败: {e}")
                if actor:
                    actors = [actor]
            actor_str = ", ".join(actors) if actors else (actor or "")
            
            # 分类
            categories = []
            if 'category_names' in data and isinstance(data['category_names'], list):
                categories = data['category_names'][:3]
            elif 'category' in data:
                categories = [data['category']]
            type_str = ", ".join(categories) if categories else fullType
            
            VOD = {
                "vod_id": did,
                "vod_name": data.get('book_name', ''),
                "vod_pic": data.get('book_pic', ''),
                "vod_actor": actor_str,
                "type_name": type_str,
                "vod_remarks": f"共{len(vod_list)}集",
                "vod_content": data.get('desc', ''),
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url)
            }
            return {'list': [VOD]}
        except Exception as e:
            print(f"获取详情失败: {e}")
            return {'list': []}

    # ---------- 播放（保持不变） ----------
    def playerContent(self, flag, id, vipFlags):
        max_retries = 3
        for i in range(max_retries):
            try:
                response = requests.get(url=id, headers=headers, timeout=timeout)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('code') == 200 and data.get('data'):
                        play_url = data['data'].get('url', '')
                        if play_url:
                            return {
                                "parse": 0,
                                "playUrl": '',
                                "url": play_url,
                                "header": headers
                            }
                    break
            except:
                if i < max_retries - 1:
                    continue
                else:
                    break
        return {
            "parse": 0,
            "playUrl": '',
            "url": 'about:blank',
            "header": headers
        }

    # ---------- 搜索（使用官方页面） ----------
    def searchContent(self, key, quick, pg=1):
        page = int(pg) if pg else 1
        per_page = 30
        try:
            items = self._search_items(key, page)
            start = (page - 1) * per_page
            chunk = items[start:start + per_page]
            total = len(items)
            page_count = max(1, (total + per_page - 1) // per_page) if total else 1
            videos = [self._vod(x) for x in chunk]
            return {
                'list': videos,
                'page': page,
                'pagecount': page_count,
                'limit': per_page,
                'total': total
            }
        except Exception as e:
            print("搜索失败:", e)
            return {'list': [], 'page': page, 'pagecount': 1}        "现代": "background=cate_757",
        "古代": "background=cate_758",
        "乡村": "background=cate_11",
        "职场": "background=cate_127",
        "校园": "background=cate_4",
        "悬疑": "topic=cate_165",
        "喜剧": "topic=cate_303",
        "重生": "setting=cate_36",
        "穿越": "setting=cate_37",
    }

    def __init__(self):
        self.bridge = "http://192.168.1.4:9979"
        self._cache = {}

    def getName(self):
        return "小心儿悠悠"   # 保持原名

    def init(self, extend=""):
        if isinstance(extend, dict):
            self.bridge = str(extend.get("bridge") or self.bridge).rstrip("/")
        elif extend:
            text = str(extend).strip()
            try:
                data = json.loads(text)
                self.bridge = str(data.get("bridge") or self.bridge).rstrip("/")
            except Exception:
                if text.startswith("http"):
                    self.bridge = text.rstrip("/")

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        return

    def _get(self, url):
        response = requests.get(url, headers=self.headers, timeout=25)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    def _router_data(self, url):
        cached = self._cache.get(url)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        html = self._get(url)
        match = re.search(
            r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>",
            html,
            re.S,
        )
        if not match:
            raise RuntimeError("页面数据格式已变化")
        data = json.loads(match.group(1))
        self._cache[url] = (time.time(), data)
        return data

    @staticmethod
    def _vod(item):
        tags = item.get("tags") or []
        if isinstance(tags, list):
            tags = " · ".join(str(x) for x in tags[:3])
        count = item.get("episode_cnt") or len(item.get("vid_list") or [])
        remark = ("全%s集" % count) if count else str(tags or "")
        return {
            "vod_id": str(item.get("series_id") or ""),
            "vod_name": str(item.get("series_name") or ""),
            "vod_pic": str(item.get("series_cover") or ""),
            "vod_remarks": remark,
        }

    def _category_items(self, query):
        url = self.site + "/category?" + query
        data = self._router_data(url)
        page = data.get("loaderData", {}).get("category_page", {})
        items = page.get("recommendList") or []
        if not items:
            items = page.get("categoryData", {}).get("recommendList") or []
        seen = set()
        result = []
        for item in items:
            sid = str(item.get("series_id") or "")
            if sid and sid not in seen:
                seen.add(sid)
                result.append(item)
        return result

    def homeContent(self, filter):
        return {
            "class": [
                {"type_name": name, "type_id": query}
                for name, query in self.category_map.items()
            ],
            "list": self.homeVideoContent().get("list", []),
        }

    def homeVideoContent(self):
        try:
            items = self._category_items("sort_type=1")[:30]
            return {"list": [self._vod(x) for x in items]}
        except Exception as exc:
            print("红果首页读取失败:", exc)
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        page = max(1, int(pg or 1))
        per_page = 30
        try:
            items = self._category_items(str(tid))
            start = (page - 1) * per_page
            chunk = items[start:start + per_page]
            page_count = max(1, (len(items) + per_page - 1) // per_page)
            return {
                "list": [self._vod(x) for x in chunk],
                "page": page,
                "pagecount": page_count,
                "limit": per_page,
                "total": len(items),
            }
        except Exception as exc:
            print("红果分类读取失败:", exc)
            return {"list": [], "page": page, "pagecount": page}

    def detailContent(self, ids):
        series_id = str(ids[0])
        url = self.site + "/detail?series_id=" + quote(series_id)
        try:
            data = self._router_data(url)
            detail = data.get("loaderData", {}).get("detail_page", {})
            series = detail.get("seriesDetail") or {}
            vids = series.get("vid_list") or []
            episodes = [
                "第%d集$%s" % (index + 1, vid)
                for index, vid in enumerate(vids)
                if str(vid)
            ]
            tags = series.get("tags") or []
            if isinstance(tags, list):
                tags = ",".join(str(x) for x in tags)
            vod = {
                "vod_id": series_id,
                "vod_name": str(series.get("series_name") or "红果短剧"),
                "vod_pic": str(series.get("series_cover") or ""),
                "type_name": str(tags),
                "vod_remarks": "全%s集" % (series.get("episode_cnt") or len(vids)),
                "vod_content": str(series.get("series_intro") or ""),
                "vod_play_from": "红果",
                "vod_play_url": "#".join(episodes),
            }
            return {"list": [vod]}
        except Exception as exc:
            print("红果详情读取失败:", exc)
            return {"list": []}

    # -------------------- 搜索（修复版）--------------------
    def _search_items(self, keyword, page=1):
        """请求搜索页面并返回结果列表"""
        url = self.site + "/search?keyword=" + quote(keyword) + "&page=" + str(page)
        data = self._router_data(url)
        search_page = data.get("loaderData", {}).get("search_page", {})
        items = search_page.get("searchResult") or []
        return items

    def searchContent(self, key, quick, pg=1):
        page = max(1, int(pg or 1))
        per_page = 30
        try:
            items = self._search_items(key, page)
            # 分页处理
            start = (page - 1) * per_page
            chunk = items[start:start + per_page]
            total = len(items)
            page_count = max(1, (total + per_page - 1) // per_page) if total else 1
            return {
                "list": [self._vod(x) for x in chunk],
                "page": page,
                "pagecount": page_count,
                "limit": per_page,
                "total": total,
            }
        except Exception as exc:
            print("红果搜索失败:", exc)
            return {"list": [], "page": page, "pagecount": page}

    def searchContentPage(self, key, quick, pg=1):
        return self.searchContent(key, quick, pg)

    # -------------------- 播放 --------------------
    def playerContent(self, flag, pid, vipFlags):
        url = self.bridge + "/play?" + urlencode({"vid": str(pid)})
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": {
                "User-Agent": self.headers["User-Agent"],
                "Referer": self.site + "/",
            },
        }

    def localProxy(self, params):
        return None        "现代": "background=cate_757",
        "古代": "background=cate_758",
        "乡村": "background=cate_11",
        "职场": "background=cate_127",
        "校园": "background=cate_4",
        "悬疑": "topic=cate_165",
        "喜剧": "topic=cate_303",
        "重生": "setting=cate_36",
        "穿越": "setting=cate_37",
    }

    def __init__(self):
        self.bridge = "http://192.168.1.4:9979"
        self._cache = {}

    def getName(self):
        return "小心儿悠悠"   # 保留原名，避免影响已有配置

    def init(self, extend=""):
        if isinstance(extend, dict):
            self.bridge = str(extend.get("bridge") or self.bridge).rstrip("/")
        elif extend:
            text = str(extend).strip()
            try:
                data = json.loads(text)
                self.bridge = str(data.get("bridge") or self.bridge).rstrip("/")
            except Exception:
                if text.startswith("http"):
                    self.bridge = text.rstrip("/")

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        return

    def _get(self, url):
        response = requests.get(url, headers=self.headers, timeout=25)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    def _router_data(self, url):
        cached = self._cache.get(url)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        html = self._get(url)
        match = re.search(
            r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>",
            html,
            re.S,
        )
        if not match:
            raise RuntimeError("页面数据格式已变化")
        data = json.loads(match.group(1))
        self._cache[url] = (time.time(), data)
        return data

    @staticmethod
    def _vod(item):
        tags = item.get("tags") or []
        if isinstance(tags, list):
            tags = " · ".join(str(x) for x in tags[:3])
        count = item.get("episode_cnt") or len(item.get("vid_list") or [])
        remark = ("全%s集" % count) if count else str(tags or "")
        return {
            "vod_id": str(item.get("series_id") or ""),
            "vod_name": str(item.get("series_name") or ""),
            "vod_pic": str(item.get("series_cover") or ""),
            "vod_remarks": remark,
        }

    def _category_items(self, query):
        url = self.site + "/category?" + query
        data = self._router_data(url)
        page = data.get("loaderData", {}).get("category_page", {})
        items = page.get("recommendList") or []
        if not items:
            items = page.get("categoryData", {}).get("recommendList") or []
        seen = set()
        result = []
        for item in items:
            sid = str(item.get("series_id") or "")
            if sid and sid not in seen:
                seen.add(sid)
                result.append(item)
        return result

    def homeContent(self, filter):
        return {
            "class": [
                {"type_name": name, "type_id": query}
                for name, query in self.category_map.items()
            ],
            "list": self.homeVideoContent().get("list", []),
        }

    def homeVideoContent(self):
        try:
            items = self._category_items("sort_type=1")[:30]
            return {"list": [self._vod(x) for x in items]}
        except Exception as exc:
            print("红果首页读取失败:", exc)
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        page = max(1, int(pg or 1))
        per_page = 30
        try:
            items = self._category_items(str(tid))
            start = (page - 1) * per_page
            chunk = items[start:start + per_page]
            page_count = max(1, (len(items) + per_page - 1) // per_page)
            return {
                "list": [self._vod(x) for x in chunk],
                "page": page,
                "pagecount": page_count,
                "limit": per_page,
                "total": len(items),
            }
        except Exception as exc:
            print("红果分类读取失败:", exc)
            return {"list": [], "page": page, "pagecount": page}

    def detailContent(self, ids):
        series_id = str(ids[0])
        url = self.site + "/detail?series_id=" + quote(series_id)
        try:
            data = self._router_data(url)
            detail = data.get("loaderData", {}).get("detail_page", {})
            series = detail.get("seriesDetail") or {}
            vids = series.get("vid_list") or []
            episodes = [
                "第%d集$%s" % (index + 1, vid)
                for index, vid in enumerate(vids)
                if str(vid)
            ]
            tags = series.get("tags") or []
            if isinstance(tags, list):
                tags = ",".join(str(x) for x in tags)
            vod = {
                "vod_id": series_id,
                "vod_name": str(series.get("series_name") or "红果短剧"),
                "vod_pic": str(series.get("series_cover") or ""),
                "type_name": str(tags),
                "vod_remarks": "全%s集" % (series.get("episode_cnt") or len(vids)),
                "vod_content": str(series.get("series_intro") or ""),
                "vod_play_from": "红果",
                "vod_play_url": "#".join(episodes),
            }
            return {"list": [vod]}
        except Exception as exc:
            print("红果详情读取失败:", exc)
            return {"list": []}

    # ----- 重构搜索：直接调用官方搜索页面 -----
    def _search_items(self, keyword, page=1):
        """从搜索页面获取结果列表"""
        url = self.site + "/search?keyword=" + quote(keyword) + "&page=" + str(page)
        data = self._router_data(url)
        search_page = data.get("loaderData", {}).get("search_page", {})
        items = search_page.get("searchResult") or []
        return items

    def searchContent(self, key, quick, pg=1):
        page = max(1, int(pg or 1))
        per_page = 30
        try:
            items = self._search_items(key, page)
            # 分页（如果搜索接口已经分页，这里只是二次保险）
            start = (page - 1) * per_page
            chunk = items[start:start + per_page]
            # 计算总页数（搜索结果可能不全，但我们可以用返回列表长度估算）
            total = len(items)
            page_count = max(1, (total + per_page - 1) // per_page) if total else 1
            return {
                "list": [self._vod(x) for x in chunk],
                "page": page,
                "pagecount": page_count,
                "limit": per_page,
                "total": total,
            }
        except Exception as exc:
            print("红果搜索失败:", exc)
            return {"list": [], "page": page, "pagecount": page}

    def searchContentPage(self, key, quick, pg=1):
        return self.searchContent(key, quick, pg)

    def playerContent(self, flag, pid, vipFlags):
        url = self.bridge + "/play?" + urlencode({"vid": str(pid)})
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": {
                "User-Agent": self.headers["User-Agent"],
                "Referer": self.site + "/",
            },
        }

    def localProxy(self, params):
        return None
