#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
import json
import base64
import urllib.request
import urllib.parse
from urllib.parse import unquote, quote, urljoin, urlsplit, parse_qs
import http.cookiejar
import gzip
import zlib
import ssl

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"

BASE_URL = "https://www.dadiao.cc"
PLAY_HOST = "https://m.892539.xyz"
PAGE_SIZE = 24

def format_remarks(brand="ZakaTV", meta=""):
    clean_meta = str(meta or "").strip()
    clean_meta = re.sub(r"[\r\n\t]+", " ", clean_meta).strip()
    if clean_meta:
        return "%s | %s" % (brand, clean_meta)
    return brand

class Spider(SpiderBase):
    def __init__(self):
        super(Spider, self).__init__()
        self.host = BASE_URL
        self.play_host = PLAY_HOST
        self.ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        self.brandActor = "📺TG群: https://t.me/+3t5XRPPo9mlkZDRl"
        self.brandDirector = "📺ZakaTV"
        self.tgGroup = "https://t.me/+3t5XRPPo9mlkZDRl"

        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

        self._zone_map = {}
        self._sub_cat_names = {}
        self.options = {}

    def init(self, extend=""):
        if isinstance(extend, dict):
            self.options = extend
        elif extend:
            try:
                self.options = json.loads(extend)
            except Exception:
                self.options = {}
        return True

    def getName(self):
        return "大屌视频·ZakaTV"

    def isVideoFormat(self, url):
        if not url:
            return False
        low = url.lower()
        return any(ext in low for ext in (".m3u8", ".mp4", ".flv", ".webm", ".ts", "magnet:"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self.options = {}

    def _fetch(self, url, referer=None):
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = urljoin(self.host, url)

        headers = {
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": referer or (self.host + "/"),
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }

        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers=headers)
                with self.opener.open(req, timeout=15) as resp:
                    raw = resp.read()
                    enc = getattr(resp, "headers", {}).get("Content-Encoding", "")
                    if raw.startswith(b"\x1f\x8b") or enc == "gzip":
                        raw = gzip.decompress(raw)
                    elif enc == "deflate":
                        try:
                            raw = zlib.decompress(raw)
                        except Exception:
                            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                    try:
                        return raw.decode("utf-8")
                    except Exception:
                        return raw.decode("latin1", errors="ignore")
            except Exception:
                if attempt == 0:
                    continue
        return ""

    def fixCover(self, url):
        if not url:
            return ""
        if not url.startswith("http"):
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = urljoin(self.host, url)
        qs = urllib.parse.urlencode({"do": "py", "name": self.getName(), "url": url})
        proxy_base = ""
        if hasattr(self, "getProxyUrl"):
            try:
                proxy_base = self.getProxyUrl()
            except Exception:
                pass
        if proxy_base:
            try:
                p = urlsplit(proxy_base)
                base = "%s://%s/proxy" % (p.scheme or "http", p.netloc or "127.0.0.1:9978")
                return "%s?%s" % (base, qs)
            except Exception:
                pass
        return "http://127.0.0.1:9978/proxy?%s" % qs

    def _load_categories(self, text):
        if not text:
            return

        self._zone_map = {}
        self._sub_cat_names = {}

        rows = re.findall(r'<div class="cate-row">([\s\S]*?)</div>\s*</div>', text)
        if rows:
            for row in rows:
                zm = re.search(r'<div class="zone-tag">\s*(.*?)\s*</div>', row)
                if not zm:
                    continue
                zone_name = zm.group(1).strip()
                if "磁力" in zone_name:
                    continue
                tids = []
                for tid, name in re.findall(r'<a href="/list/(\d+)-1\.html"[^>]*>([^<]+)</a>', row):
                    cname = name.strip()
                    if not cname:
                        continue
                    tids.append(tid)
                    self._sub_cat_names[tid] = cname
                if tids:
                    self._zone_map[zone_name] = tids

        if not self._zone_map:
            zone_names = re.findall(r'<div class="zone-tag">\s*(.*?)\s*</div>', text)
            items_blocks = re.findall(r'<div class="cate-items">([\s\S]*?)</div>', text)
            if len(zone_names) == len(items_blocks) and len(zone_names) > 0:
                for i, zn in enumerate(zone_names):
                    zone_name = zn.strip()
                    if "磁力" in zone_name:
                        continue
                    tids = []
                    for tid, name in re.findall(r'<a href="/list/(\d+)-1\.html"[^>]*>([^<]+)</a>', items_blocks[i]):
                        cname = name.strip()
                        if not cname:
                            continue
                        tids.append(tid)
                        self._sub_cat_names[tid] = cname
                    if tids:
                        self._zone_map[zone_name] = tids

        if not self._zone_map:
            seen_tid = set()
            for tid, name in re.findall(r'<a href="/list/(\d+)-1\.html"[^>]*>([^<]+)</a>', text):
                cname = name.strip()
                if not cname or tid in seen_tid:
                    continue
                seen_tid.add(tid)
                self._sub_cat_names[tid] = cname
            if self._sub_cat_names:
                self._zone_map["全部视频"] = list(self._sub_cat_names.keys())

    def homeContent(self, filter):
        text = self._fetch(self.host)
        if text:
            self._load_categories(text)

        classes = []
        filters = {}

        for zone_name, tids in self._zone_map.items():
            if not tids or "磁力" in zone_name:
                continue
            zone_tid = "zone:" + ",".join(tids)
            classes.append({"type_id": zone_tid, "type_name": zone_name})

            sub_values = []
            for tid in tids:
                sub_name = self._sub_cat_names.get(tid, tid)
                sub_values.append({"n": sub_name, "v": tid})

            if sub_values:
                filters[zone_tid] = [{
                    "key": "sub",
                    "name": "分类",
                    "value": sub_values
                }]
            else:
                filters[zone_tid] = []

        return {
            "class": classes,
            "filters": filters,
            "style": {"type": "rect", "ratio": 1.78}
        }

    def homeVideoContent(self):
        return {"list": []}

    def _parse_list(self, html):
        items = []
        li_blocks = re.findall(
            r'<li>\s*<a class="thumb-card" href="(/(?:video|torrent)/([^"]+)\.html)"[^>]*>([\s\S]*?)</li>',
            html
        )
        for href, vid, body in li_blocks:
            title = vid
            h5_match = re.search(r'<h5><a[^>]*>(.*?)</a></h5>', body, re.S)
            if h5_match:
                title = re.sub(r'<[^>]+>', '', h5_match.group(1)).strip()

            pic = ""
            pic_match = re.search(r'<img[^>]+data-original="([^"]+)"', body)
            if pic_match:
                pic = pic_match.group(1).strip()
            else:
                pic_match = re.search(r'<img[^>]+src="([^"]+)"', body)
                if pic_match:
                    pic = pic_match.group(1).strip()

            if pic and (pic.endswith("loading.svg") or pic.endswith("loading.gif")):
                pic = ""

            if pic:
                if pic.startswith("//"):
                    pic = "https:" + pic
                elif pic.startswith("/"):
                    pic = urljoin(self.host, pic)

            is_torrent = href.startswith("/torrent/")
            meta_tag = "磁力" if is_torrent else "高清"
            remarks = format_remarks("ZakaTV", meta_tag)

            items.append({
                "vod_id": ("torrent_" + vid) if is_torrent else vid,
                "vod_name": title,
                "vod_pic": self.fixCover(pic),
                "vod_remarks": remarks,
                "style": {"type": "rect", "ratio": 1.78}
            })
        return items

    def _get_list(self, tid, page):
        url = "%s/list/%s-%d.html" % (self.host, tid, page)
        html = self._fetch(url, referer=("%s/list/%s-1.html" % (self.host, tid)))
        if not html:
            return []
        return self._parse_list(html)

    def _do_category(self, tid, pg):
        page = int(pg) if pg else 1
        items = self._get_list(tid, page)
        total_page = page + 1
        if page == 1:
            html = self._fetch("%s/list/%s-1.html" % (self.host, tid))
            if html:
                pages = re.findall(r'/list/\d+-(\d+)\.html', html)
                if pages:
                    total_page = max(int(p) for p in pages)
        return {
            "list": items,
            "page": page,
            "pagecount": total_page,
            "limit": len(items) if items else PAGE_SIZE,
            "total": total_page * (len(items) if items else PAGE_SIZE),
            "style": {"type": "rect", "ratio": 1.78}
        }

    def categoryContent(self, tid, pg, filter, extend):
        if isinstance(extend, str):
            try:
                extend = json.loads(extend)
            except Exception:
                extend = {}

        if tid and str(tid).startswith("zone:"):
            tids = str(tid).replace("zone:", "").split(",")
            tids = [t.strip() for t in tids if t.strip()]
            if extend and isinstance(extend, dict) and extend.get("sub"):
                target_tid = str(extend["sub"]).strip()
                return self._do_category(target_tid, pg)
            else:
                if tids:
                    return self._do_category(tids[0], pg)
                return {"list": [], "page": 1, "pagecount": 1, "limit": 0, "total": 0, "style": {"type": "rect", "ratio": 1.78}}
        else:
            return self._do_category(str(tid or "").strip(), pg)

    def _parse_detail(self, html, vid, base_url, is_torrent=False):
        title = ""
        m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
        if m:
            title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if not title:
            m = re.search(r'<title>([^<]+)</title>', html)
            if m:
                title = m.group(1).strip()

        cover = ""
        m = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', html)
        if m:
            cover = m.group(1).strip()
        if not cover:
            m = re.search(r'<img[^>]+class="[^"]*cover[^"]*"[^>]+src="([^"]+)"', html, re.S)
            if m:
                cover = m.group(1).strip()
        if not cover:
            m = re.search(r'<img[^>]+data-original="([^"]+)"', html)
            if m:
                cover = m.group(1).strip()
        if not cover:
            m = re.search(r'<video[^>]+poster="([^"]+)"', html)
            if m:
                cover = m.group(1).strip()

        if cover:
            if cover.startswith("//"):
                cover = "https:" + cover
            elif cover.startswith("/"):
                cover = urljoin(self.host, cover)

        play_urls = []
        seen = set()

        def add(label, url):
            if not url or url in seen:
                return
            seen.add(url)
            play_urls.append("%s$%s" % (label, url))

        if not is_torrent:
            site_id = ""
            source_id = ""

            comment_match = re.search(r'<!--\s*source_id:(\d+),\s*site_id:(\d+)', html)
            if comment_match:
                source_id = comment_match.group(1)
                site_id = comment_match.group(2)

            if not site_id or not source_id:
                hls_match = re.search(r'hls\.loadSource\([\'"](https?://[^\'"]+)[\'"]\)', html)
                if hls_match:
                    hls_url = hls_match.group(1)
                    sid_match = re.search(r'site_id=(\d+)', hls_url)
                    src_match = re.search(r'source_id=(\d+)', hls_url)
                    if sid_match and src_match:
                        site_id = sid_match.group(1)
                        source_id = src_match.group(1)

            if not site_id:
                m_sid = re.search(r'site_id[=:]\s*(\d+)', html)
                if m_sid:
                    site_id = m_sid.group(1)
            if not source_id:
                m_src = re.search(r'source_id[=:]\s*(\d+)', html)
                if m_src:
                    source_id = m_src.group(1)

            if site_id and source_id:
                play_url = "%s/play.php?site_id=%s&source_id=%s" % (self.play_host, site_id, source_id)
                add("Zaka专线", play_url)

            for media in set(re.findall(r'https?://[^\s"\'<>]+\.(?:m3u8|mp4|flv|mkv|ts)(?:\?[^\s"\'<>]*)?', html)):
                add("直链备用", media)

            for src in set(re.findall(r'<iframe[^>]+(?:src|data-src)=["\']([^"\']+)["\']', html)):
                if any(k in src for k in ("play.php", "m3u8", "mp4", "embed", "player")):
                    full_src = src if src.startswith("http") else urljoin(base_url, src)
                    add("解析播放", full_src)

            scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
            for script in scripts:
                for b64 in re.findall(r'["\']([A-Za-z0-9+/]{20,}={0,2})["\']', script):
                    try:
                        dec = base64.b64decode(b64).decode("utf-8")
                        if dec.startswith("http") and any(x in dec for x in (".m3u8", ".mp4", "play.php")):
                            add("加密线路", dec)
                    except Exception:
                        pass

            if not play_urls:
                add("默认播放", base_url)
        else:
            b64_match = re.search(r"var j_b64\s*=\s*['\"]([A-Za-z0-9+/=]+)['\"]", html)
            if b64_match:
                try:
                    decoded = base64.b64decode(b64_match.group(1)).decode("utf-8")
                    j_data = json.loads(decoded)
                    if j_data.get("tm"):
                        add("磁力原链", j_data["tm"])
                    if j_data.get("tt"):
                        add("种子下载", j_data["tt"])
                except Exception:
                    pass

            if not play_urls:
                for hm in re.findall(r'href=["\'](magnet:\?xt=urn:btih:[^"\']+)["\']', html):
                    decoded = unquote(hm)
                    if decoded.startswith("magnet:"):
                        add("磁力原链", decoded)

            if not play_urls:
                for mag in set(re.findall(r'magnet:\?xt=urn:btih:[A-Za-z0-9]+[^\s"\'<>]*', html)):
                    add("磁力原链", mag)

            if not play_urls:
                hash_match = re.search(r'[A-Fa-f0-9]{40}', html)
                if hash_match:
                    add("磁力哈希", "magnet:?xt=urn:btih:" + hash_match.group(0))

        sources = []
        urls = []
        for pu in play_urls:
            parts = pu.split("$", 1)
            if len(parts) == 2:
                sources.append(parts[0])
                urls.append(pu)

        full_desc = (
            "【🔥 官方交流群: %s】\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "大屌视频 极速硬解"
        ) % self.tgGroup

        remarks = format_remarks("ZakaTV", "磁力" if is_torrent else "正片")

        return {
            "vod_id": vid,
            "vod_name": title or vid,
            "vod_pic": self.fixCover(cover),
            "vod_actor": self.brandActor,
            "vod_director": self.brandDirector,
            "vod_remarks": remarks,
            "vod_content": full_desc,
            "vod_play_from": "$$$".join(sources) if sources else "Zaka专线",
            "vod_play_url": "#".join(urls) if urls else ("播放$%s" % base_url)
        }

    def detailContent(self, ids):
        vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        if vid.startswith("magnet:"):
            return {
                "list": [{
                    "vod_id": vid,
                    "vod_name": "磁力直链",
                    "vod_pic": "",
                    "vod_actor": self.brandActor,
                    "vod_director": self.brandDirector,
                    "vod_remarks": format_remarks("ZakaTV", "磁力"),
                    "vod_content": "磁力下载资源",
                    "vod_play_from": "磁力专线",
                    "vod_play_url": "磁力$%s" % vid
                }]
            }

        if vid.startswith("torrent_"):
            real_id = vid.replace("torrent_", "")
            url = "%s/torrent/%s.html" % (self.host, real_id)
            html = self._fetch(url, referer=self.host)
            if html:
                detail = self._parse_detail(html, vid, url, is_torrent=True)
                if detail:
                    return {"list": [detail]}
            return {"list": []}

        url = "%s/video/%s.html" % (self.host, vid)
        html = self._fetch(url, referer=self.host)
        if html:
            detail = self._parse_detail(html, vid, url, is_torrent=False)
            if detail:
                return {"list": [detail]}
        return {"list": []}

    def playerContent(self, flag, id, vipFlags=None):
        raw_id = str(id or "").strip()
        if raw_id.startswith("magnet:"):
            return {
                "parse": 0,
                "url": raw_id,
                "header": {
                    "User-Agent": self.ua
                }
            }

        if raw_id and not raw_id.startswith("http") and not raw_id.startswith("magnet:"):
            det = self.detailContent([raw_id])
            if det and det.get("list"):
                p_url = det["list"][0].get("vod_play_url", "")
                if p_url:
                    first = p_url.split("#")[0]
                    raw_id = first.split("$", 1)[1] if "$" in first else first

        referer = self.host
        if raw_id and raw_id.startswith("http"):
            try:
                p = urlsplit(raw_id)
                if p.netloc:
                    referer = "%s://%s/" % (p.scheme or "https", p.netloc)
            except Exception:
                pass

        return {
            "parse": 0,
            "playUrl": "",
            "url": raw_id,
            "header": {
                "User-Agent": self.ua,
                "Referer": referer,
                "Origin": referer.rstrip("/")
            }
        }

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        all_items = []

        url = "%s/search.php?content=%s&type=1&page=%d" % (self.host, quote(key), page)
        html = self._fetch(url, referer=self.host)
        if html:
            items = self._parse_list(html)
            all_items.extend(items)

        if not all_items:
            url_torrent = "%s/search.php?content=%s&type=2&page=%d" % (self.host, quote(key), page)
            html_t = self._fetch(url_torrent, referer=self.host)
            if html_t:
                items_t = self._parse_list(html_t)
                all_items.extend(items_t)

        return {
            "list": all_items,
            "page": page,
            "pagecount": page + 1,
            "limit": len(all_items),
            "total": page * len(all_items),
            "style": {"type": "rect", "ratio": 1.78}
        }

    def localProxy(self, param):
        url = ""
        if isinstance(param, dict):
            url = param.get("url", "")
        elif isinstance(param, str):
            if "/proxy?" in param:
                try:
                    qs = parse_qs(urlsplit(param).query)
                    if qs.get("url"):
                        url = qs["url"][0]
                except Exception:
                    pass
            else:
                url = param

        if not url or not url.startswith("http"):
            return [404, "text/plain", b""]

        try:
            parsed = urlsplit(url)
            referer = ("%s://%s/" % (parsed.scheme or "https", parsed.netloc)) if parsed.netloc else (self.host + "/")
            headers = {
                "User-Agent": self.ua,
                "Referer": referer,
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"
            }
            req = urllib.request.Request(url, headers=headers)
            with self.opener.open(req, timeout=15) as resp:
                body = resp.read()
                ctype = getattr(resp, "headers", {}).get("Content-Type", "image/jpeg")
                return [200, ctype, body]
        except Exception:
            return [404, "text/plain", b""]
