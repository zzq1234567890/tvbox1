#!/usr/bin/python
# -*- coding: utf-8 -*-
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, unquote, urlencode, urlparse
import requests
from base.spider import Spider

class Spider(Spider):
    def getName(self):
        return "洛雪TV"

    def init(self, extend=""):
        self.name = "洛雪TV"
        self.host = "https://tv.lxyy.club"
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Referer": self.host + "/", "Accept": "application/json, text/plain, */*"}
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.img = "https://image.tmdb.org/t/p/w400"
        self.parser = "https://svip.qlplayer.cyou/?url="
        self.line_api = {}
        mb = {"sort_by": "popularity.desc", "primary_release_date_lte": "today", "include_adult": "false", "include_video": "false"}
        sb = {"sort_by": "popularity.desc", "first_air_date_lte": "today", "include_null_first_air_dates": "false", "include_adult": "false"}
        ab = dict(sb, with_genres="16")
        self.cm = {
            "movie-all": ("movie", {}), "movie-popular": ("movie", {}), "movie-latest": ("movie", {"sort_by": "primary_release_date.desc"}), "movie-rated": ("movie", {"sort_by": "vote_average.desc", "vote_count_gte": "200"}), "cn-movie": ("movie", {"with_original_language": "zh", "with_origin_country": "CN"}), "movie-action": ("movie", {"with_genres": "28"}), "movie-comedy": ("movie", {"with_genres": "35"}), "movie-romance": ("movie", {"with_genres": "10749"}), "movie-mystery": ("movie", {"with_genres": "9648"}), "movie-scifi": ("movie", {"with_genres": "878"}),
            "series-all": ("tv", {}), "series-hot": ("tv", {}), "series-latest": ("tv", {"sort_by": "first_air_date.desc"}), "series-rated": ("tv", {"sort_by": "vote_average.desc", "vote_count_gte": "200"}), "cn-tv": ("tv", {"with_original_language": "zh", "with_origin_country": "CN", "without_genres": "16"}), "series-korea": ("tv", {"with_origin_country": "KR"}), "series-japan": ("tv", {"with_origin_country": "JP"}), "series-western": ("tv", {"with_original_language": "en"}),
            "anime-all": ("tv", {"with_genres": "16"}), "anime-cn": ("tv", {"with_genres": "16", "with_original_language": "zh", "with_origin_country": "CN"}), "anime-japan": ("tv", {"with_genres": "16", "with_origin_country": "JP"}), "anime-western": ("tv", {"with_genres": "16", "with_original_language": "en"}), "anime-latest": ("tv", {"with_genres": "16", "sort_by": "first_air_date.desc"})
        }
        self.cats = [
            ("movie", mb), ("series", sb), ("anime", ab)
        ]
        self.classes = []
        for g, base in self.cats:
            for tid, lbl in {
                "movie": [("movie-all", "全部"), ("movie-popular", "热门"), ("movie-latest", "最新"), ("movie-rated", "高分"), ("cn-movie", "国产"), ("movie-action", "动作"), ("movie-comedy", "喜剧"), ("movie-romance", "爱情"), ("movie-mystery", "悬疑"), ("movie-scifi", "科幻")],
                "series": [("series-all", "全部"), ("series-hot", "热播"), ("series-latest", "最新"), ("series-rated", "高分"), ("cn-tv", "国产"), ("series-korea", "韩剧"), ("series-japan", "日剧"), ("series-western", "欧美")],
                "anime": [("anime-all", "全部"), ("anime-cn", "国漫"), ("anime-japan", "日漫"), ("anime-western", "欧美"), ("anime-latest", "最新")]
            }.get(g, []):
                self.classes.append({"type_id": tid, "type_name": lbl})
        if extend:
            try:
                p = json.loads(extend).get("proxy") if isinstance(extend, str) else extend.get("proxy")
                if p:
                    self.session.proxies = {k: v for k, v in p.items()} if isinstance(p, dict) else {"http": p, "https": p}
            except Exception:
                pass

    def _get(self, url):
        try:
            r = self.session.get(url, headers=self.headers, timeout=20, verify=False, proxies=self.session.proxies or None)
            return r.json() if r.status_code == 200 else {}
        except Exception:
            return {}

    def _tmdb(self, media, params, page):
        q = dict(params)
        q.update({"page": page, "language": "zh-CN"})
        return self._get(self.host + "/api/tmdb.php?path=discover/" + media + "&" + urlencode(q))

    def _item(self, v):
        name = v.get("title") or v.get("name") or ""
        return {"vod_id": quote(name), "vod_name": name, "vod_pic": (self.img + v["poster_path"]) if v.get("poster_path") else "", "vod_remarks": (v.get("release_date") or v.get("first_air_date") or "")[:4]}

    def _rank(self):
        d = self._get(self.host + "/api/ranking.php")
        return [{"vod_id": quote(v.get("title") or ""), "vod_name": v.get("title") or "", "vod_pic": (self.img + v["posterPath"]) if v.get("posterPath") else "", "vod_remarks": v.get("mediaType") or ""} for v in (d.get("items") or []) if v.get("title")]

    def homeContent(self, filter):
        return {"class": self.classes, "list": self._rank()[:30], "filters": {}}

    def homeVideoContent(self):
        return {"list": self._rank()[:40]}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        media, params = self.cm.get(tid, ("movie", {}))
        d = self._tmdb(media, params, pg)
        items = [self._item(v) for v in (d.get("results") or [])]
        return {"page": pg, "pagecount": int(d.get("total_pages") or 1), "limit": len(items) or 20, "total": int(d.get("total_results") or 0), "list": items}

    def _join(self, eps):
        return "#".join(f"{self._clean(e.get('name') or str(i + 1))}${e.get('url')}" for i, e in enumerate(eps) if e.get("url"))

    @staticmethod
    def _clean(name):
        """去掉线路名/集名中可能导致播放器解析失败的 emoji 与特殊字符"""
        return re.sub(r"[^\w\u4e00-\u9fff .\-()+——]", "", str(name)).strip() or "线路"

    def _extend_vod(self, vod, dl, r):
        if not vod.get("vod_pic"):
            vod["vod_pic"] = dl.get("pic") or r.get("pic") or ""
        for k, f in (("vod_content", "content"), ("vod_director", "director"), ("vod_actor", "actor"), ("vod_area", "area"), ("vod_year", "year"), ("vod_remarks", "remarks")):
            if not vod.get(k) and dl.get(f):
                vod[k] = dl.get(f)
        if not vod.get("vod_remarks"):
            vod["vod_remarks"] = " / ".join(x for x in (r.get("remarks"), r.get("type"), str(r.get("year") or "")) if x)

    @staticmethod
    def _to_direct(url):
        """将自营 jlplayer 页面(/s/<hash>)转换为同源的 smart.m3u8 直链，绕开 shield 解析器"""
        m = re.search(r"jimaoys95\.com/s/([0-9a-f]+)", url)
        if m:
            return "https://jimaoys94.com/public/playback/%s/smart.m3u8" % m.group(1)
        return url

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        raw = ids[0]
        name = unquote(raw.split(":", 3)[-1] if raw.startswith("tmdb:") else raw)
        d = self._get(self.host + "/api/proxy.php?action=search&wd=" + quote(name))
        rs = (d.get("results") or [])[:8]
        if not rs:
            return {"list": []}
        vod = {"vod_id": raw, "vod_name": name, "vod_pic": "", "vod_play_from": "", "vod_play_url": ""}
        fs, us = [], []

        def fetch(r):
            return r, self._get(self.host + "/api/proxy.php?action=detail&source=" + quote(str(r.get("source") or "")) + "&id=" + quote(str(r.get("id") or "")))

        done = {}
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(fetch, r): (r.get("source"), r.get("id")) for r in rs}
            for fut in as_completed(futs):
                r, dd = fut.result()
                done[(r.get("source"), r.get("id"))] = dd
        for r in rs:
            dd = done.get((r.get("source"), r.get("id"))) or {}
            dls = dd.get("details") or [] if isinstance(dd, dict) else []
            if not dls:
                continue
            dl = dls[0]
            self._extend_vod(vod, dl, r)
            api = dl.get("player_api") or ""
            src_name = self._clean(dl.get("source_name") or r.get("source_name") or str(r.get("source") or "线路"))
            groups = dl.get("episodes") or []
            if len(groups) <= 1:
                eps = groups[0].get("episodes") or [] if groups else []
                if not eps:
                    pu = dl.get("play_url") or ""
                    eps = [{"name": x.split("$")[0], "url": self._to_direct(x.split("$", 1)[1])} for x in pu.split("#") if "$" in x]
                else:
                    eps = [dict(e, url=self._to_direct(e.get("url") or "")) for e in eps]
                u = self._join(eps)
                if u:
                    fs.append(src_name)
                    us.append(u)
                    self.line_api[src_name] = api
            else:
                for g in groups:
                    eps = g.get("episodes") or []
                    eps = [dict(e, url=self._to_direct(e.get("url") or "")) for e in eps]
                    u = self._join(eps)
                    if u:
                        ln = self._clean(f"{src_name}-{g.get('group') or '线路'}")
                        fs.append(ln)
                        us.append(u)
                        self.line_api[ln] = api
        if not fs:
            return {"list": []}
        vod["vod_play_from"] = "$$$".join(fs)
        vod["vod_play_url"] = "$$$".join(us)
        return {"list": [vod]}

    def searchContent(self, key, quick, pg="1"):
        d = self._get(self.host + "/api/proxy.php?action=search&wd=" + quote(key) + "&page=" + str(pg))
        items = []
        for r in (d.get("results") or []):
            nm = r.get("name") or ""
            if not nm:
                continue
            rm = " / ".join(x for x in (r.get("remarks"), r.get("type"), str(r.get("year") or "")) if x)
            items.append({"vod_id": quote(nm), "vod_name": nm, "vod_pic": r.get("pic") or "", "vod_remarks": rm})
        return {"list": items, "page": int(pg) if str(pg).isdigit() else 1}

    def playerContent(self, flag, id, vipFlags):
        api = self.line_api.get(flag) or ""
        if re.search(r"\.(?:m3u8|mp4)(?:$|[?#])", urlparse(id).path, re.I):
            return {"parse": 0, "url": id, "header": json.dumps({})}
        if not api:
            api = self.parser
        return {"parse": 1, "url": api + quote(id, safe=""), "header": json.dumps({})}