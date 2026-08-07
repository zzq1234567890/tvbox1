from base.spider import Spider
import requests
import re
from urllib.parse import quote, urlencode
import json
import time

class Spider(Spider):
    site = "https://hongguoduanju.com"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36'
    }
    timeout = 8  # 缩短超时
    category_map = {
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

    def __init__(self):
        self.bridge = ""  # 默认不使用代理
        self.session = requests.Session()  # 复用连接
        self.session.headers.update(self.headers)
        self._cache = {}

    def getName(self):
        return "小心儿悠悠"

    def init(self, extend=""):
        if isinstance(extend, dict):
            self.bridge = str(extend.get("bridge") or "").rstrip("/")
            # 允许传入自定义解析地址
            self.parse_api = extend.get("parse_api", "")
        elif extend:
            text = str(extend).strip()
            try:
                data = json.loads(text)
                self.bridge = str(data.get("bridge") or "").rstrip("/")
                self.parse_api = data.get("parse_api", "")
            except Exception:
                if text.startswith("http"):
                    self.bridge = text.rstrip("/")
        if not hasattr(self, 'parse_api'):
            self.parse_api = ""

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self.session.close()
        return

    def _get(self, url):
        # 使用 session 复用连接
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    def _router_data(self, url):
        cached = self._cache.get(url)
        if cached and time.time() - cached[0] < 60:  # 缩短缓存到60秒
            return cached[1]
        html = self._get(url)
        # 匹配 _ROUTER_DATA 或 __NEXT_DATA__
        match = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>", html, re.S)
        if not match:
            match = re.search(r"<script id=\"__NEXT_DATA__\"[^>]*>(\{.*?\})</script>", html, re.S)
        if not match:
            raise RuntimeError("未找到页面数据")
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

    def _search_items(self, keyword, page=1):
        url = self.site + "/search?keyword=" + quote(keyword) + "&page=" + str(page)
        data = self._router_data(url)
        search_page = data.get("loaderData", {}).get("search_page", {})
        items = search_page.get("searchResult") or []
        if not items:
            items = search_page.get("list") or search_page.get("data") or []
        return items

    def searchContent(self, key, quick, pg=1):
        page = max(1, int(pg or 1))
        per_page = 30
        try:
            items = self._search_items(key, page)
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

    def playerContent(self, flag, pid, vipFlags):
        """
        获取播放地址，按优先级尝试：
        1. 自定义解析接口（通过 init 传入 parse_api）
        2. 官方 /api/play 接口
        3. 直接构造 m3u8 链接（需 Referer）
        """
        vid = str(pid)
        # 1. 如果配置了自定义解析 API
        if hasattr(self, 'parse_api') and self.parse_api:
            try:
                resp = self.session.get(self.parse_api + "?vid=" + quote(vid), timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    play_url = data.get('url') or data.get('play_url') or data.get('data', {}).get('url')
                    if play_url:
                        return self._build_play_result(play_url)
            except Exception as e:
                print("自定义解析失败:", e)

        # 2. 尝试官方播放接口
        try:
            api_url = self.site + "/api/play?vid=" + quote(vid)
            resp = self.session.get(api_url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                play_url = data.get('url') or data.get('play_url') or data.get('data', {}).get('url')
                if play_url:
                    return self._build_play_result(play_url)
        except Exception as e:
            print("官方API获取播放地址失败:", e)

        # 3. 备选：构造 m3u8 链接（需带上 Referer）
        fallback_url = self.site + "/video/" + vid + ".m3u8"
        return self._build_play_result(fallback_url, need_referer=True)

    def _build_play_result(self, url, need_referer=False):
        header = {
            "User-Agent": self.headers["User-Agent"]
        }
        if need_referer:
            header["Referer"] = self.site + "/"
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": header
        }

    def localProxy(self, params):
        # 如果保留了 bridge 代理，可在此实现，但默认不使用
        return None
