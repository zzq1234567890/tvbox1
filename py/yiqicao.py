#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
import json
import base64
import urllib.request
import urllib.parse
from urllib.parse import urlencode, quote, unquote, urlsplit, parse_qs
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

BASE_URL = "https://www.kfzedwc.com:2087"
API_BASE = BASE_URL + "/v1"
BRANCH = "t1"
PLAY_FROM = "Zaka专线"
PAGE_SIZE = 20
XOR_COVER = True

PUBKEY = (
    "MIIBVAIBADANBgkqhkiG9w0BAQEFAASCAT4wggE6AgEAAkEA0E9Nsuz6jYF+JeLqKaL1LkZyg0Wl4xP"
    "IwEzlDrO4UOMYGX1WG+nqf9ovpplgThgLcyoRM1YFshGFOrkAiHEZqwIDAQABAkABvEdncDX+K9ADPMq6ohLs2cV"
    "mdpQVOjr37ywRXUnx0o6skjM3Yg45uw3lpobrkckep0NxqrINeSsrY29hA3ZBAiEA8rnQiqs6hXw8tLIBk0i2i7"
    "tqai9xew/lD/wDGQdtvdECIQDbs6kkuEs9us9avgF/JO7F13OmlDzR0lzrIzujxvLSuwIgW+BX/tVXnoVrWR50GD"
    "MS3gt/+VeiBen7U7SZ25SDRrECIBhIx41zgX2VRI43KlsvbeUYZ4QmJoLaycKD5ne36ec5AiEA44AwFDoD1qf1wI"
    "Z152QxrkZgGMyKG6c836lRB5VdiME="
)

def format_remarks(brand="ZakaTV", meta=""):
    clean_meta = str(meta or "").strip()
    clean_meta = re.sub(r"[\r\n\t]+", " ", clean_meta).strip()
    if clean_meta:
        return "%s | %s" % (brand, clean_meta)
    return brand

class Spider(SpiderBase):
    def __init__(self):
        super(Spider, self).__init__()
        self.base = BASE_URL
        self.api_base = API_BASE
        self.branch = BRANCH
        self.ua = (
            "Mozilla/5.0 (Linux; Android 13; SM-G9810 Build/TP1A.220624.014; wv) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0.6478.134 Mobile Safari/537.36"
        )
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

        self._cates_cache = None
        self._subs_cache = None
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
        return "一起草"

    def isVideoFormat(self, url):
        if not url:
            return False
        low = url.lower()
        if any(bad in low for bad in ("preview.mp4", "sample.mp4", "trailer.mp4", "top_banner", "native-ad")):
            return False
        return any(ext in low for ext in (".m3u8", ".mp4", ".flv", ".webm", ".ts", "index.png"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self.options = {}

    def _fetch_raw(self, target_url, params=None, headers_custom=None):
        if not target_url:
            return {"code": 0, "text": "", "bytes": b"", "err": ""}
        if target_url.startswith("//"):
            target_url = "https:" + target_url
        elif target_url.startswith("/") and not target_url.startswith(self.base):
            target_url = self.base + target_url

        if params:
            qs = urllib.parse.urlencode(params)
            target_url = "%s%s%s" % (target_url, "&" if "?" in target_url else "?", qs)

        headers = {
            "User-Agent": self.ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self.base + "/",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }
        if headers_custom:
            headers.update(headers_custom)

        for attempt in range(2):
            try:
                req = urllib.request.Request(target_url, headers=headers)
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
                        text = raw.decode("utf-8")
                    except Exception:
                        text = raw.decode("latin1", errors="ignore")
                    return {"code": resp.getcode(), "text": text, "bytes": raw, "err": ""}
            except urllib.error.HTTPError as e:
                err_text = ""
                try:
                    err_text = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                if attempt == 0 and e.code in (429, 451):
                    continue
                return {"code": e.code, "text": err_text, "bytes": b"", "err": str(e)}
            except Exception as e:
                if attempt == 0:
                    continue
                return {"code": -1, "text": "", "bytes": b"", "err": str(e)}

        return {"code": -1, "text": "", "bytes": b"", "err": "timeout"}

    def _rsa_decrypt(self, key_b64):
        try:
            from cryptography.hazmat.primitives.serialization import load_der_public_key
            from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
            pub = load_der_public_key(base64.b64decode(PUBKEY))
            return pub.decrypt(base64.b64decode(key_b64), rsa_padding.PKCS1v15())
        except Exception:
            pass
        try:
            from Crypto.PublicKey import RSA
            from Crypto.Cipher import PKCS1_v1_5
            pub = RSA.import_key(base64.b64decode(PUBKEY))
            return PKCS1_v1_5.new(pub).decrypt(base64.b64decode(key_b64), b"")
        except Exception:
            return b""

    def _aes_decrypt(self, data_b64, aes_key):
        key = aes_key.encode("utf-8")
        iv = aes_key[::-1][:16].encode("utf-8")
        ct = base64.b64decode(data_b64)
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
            plain = dec.update(ct) + dec.finalize()
        except Exception:
            try:
                from Crypto.Cipher import AES
                plain = AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
            except Exception:
                return b""
        if plain:
            pad = plain[-1]
            if 1 <= pad <= 16:
                plain = plain[:-pad]
        return plain

    def _decrypt_payload(self, body):
        if not isinstance(body, dict):
            return body
        data_field = body.get("data")
        key_field = body.get("key")
        if isinstance(data_field, str) and isinstance(key_field, str):
            try:
                raw_key = self._rsa_decrypt(key_field)
                if not raw_key:
                    return None
                aes_key = raw_key.decode("utf-8")
                plain = self._aes_decrypt(data_field, aes_key)
                if not plain:
                    return None
                obj = json.loads(plain.decode("utf-8"))
                return obj.get("data", obj)
            except Exception:
                return None
        return data_field if data_field is not None else body

    def _api_get(self, path, params=None):
        req_params = dict(params or {})
        req_params.setdefault("c", self.branch)
        target = self.api_base + "/" + path.lstrip("/")
        res = self._fetch_raw(target, params=req_params)
        if res.get("code") != 200 or not res.get("text"):
            return None
        try:
            body = json.loads(res["text"])
            return self._decrypt_payload(body)
        except Exception:
            return None

    def _fix_url(self, url):
        if not url:
            return ""
        if url.startswith("http"):
            return url
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self.base + url
        return self.base + "/" + url

    def fixCover(self, url):
        if not url:
            return ""
        if not url.startswith("http"):
            return url
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

    def _load_categories_and_subs(self):
        if self._cates_cache is not None and self._subs_cache is not None:
            return

        cates = []
        subs_map = {}
        seen_ids = set()

        init_data = self._api_get("/blist")
        raw_menu = []
        if isinstance(init_data, dict):
            raw_menu = init_data.get("menu_cates") or []

        if raw_menu:
            for item in raw_menu:
                if not isinstance(item, dict):
                    continue
                cid = item.get("id")
                name = item.get("name")
                if cid is None or not name:
                    continue
                cid_str = str(cid).strip()
                if cid_str in ("None", "", "0"):
                    continue
                if cid_str not in seen_ids:
                    seen_ids.add(cid_str)
                    cates.append({"type_id": cid_str, "type_name": str(name).strip()})

                sub_list = item.get("sub_cates") or item.get("sub_menu") or []
                subs = []
                for s in sub_list:
                    if isinstance(s, dict) and s.get("name"):
                        sid = s.get("id") if s.get("id") is not None else s.get("t")
                        if sid is not None and str(sid).strip() not in ("None", ""):
                            subs.append({"n": str(s["name"]).strip(), "v": str(sid).strip()})
                if subs:
                    subs_map[cid_str] = subs

        fallback_cates = self._api_get("/vod/category")
        fb_list = []
        if isinstance(fallback_cates, dict):
            fb_list = fallback_cates.get("cates") or fallback_cates.get("list") or []
        elif isinstance(fallback_cates, list):
            fb_list = fallback_cates

        for item in fb_list:
            if not isinstance(item, dict):
                continue
            cid = item.get("id")
            name = item.get("name")
            if cid is None or not name:
                continue
            cid_str = str(cid).strip()
            if cid_str not in seen_ids:
                seen_ids.add(cid_str)
                cates.append({"type_id": cid_str, "type_name": str(name).strip()})

            if cid_str not in subs_map:
                sub_list = item.get("sub_cates") or item.get("sub_menu") or []
                subs = []
                for s in sub_list:
                    if isinstance(s, dict) and s.get("name"):
                        sid = s.get("id") if s.get("id") is not None else s.get("t")
                        if sid is not None and str(sid).strip() not in ("None", ""):
                            subs.append({"n": str(s["name"]).strip(), "v": str(sid).strip()})
                if subs:
                    subs_map[cid_str] = subs

        if not cates:
            cates = [
                {"type_id": "1", "type_name": "国产"},
                {"type_id": "3", "type_name": "日韩"},
                {"type_id": "40", "type_name": "原创"},
                {"type_id": "2", "type_name": "传媒"},
                {"type_id": "4", "type_name": "欧美"},
                {"type_id": "5", "type_name": "动漫"},
                {"type_id": "6", "type_name": "AI换脸"},
                {"type_id": "7", "type_name": "主播"},
                {"type_id": "8", "type_name": "AV解说"},
                {"type_id": "10", "type_name": "同性"}
            ]

        self._cates_cache = cates
        self._subs_cache = subs_map

    def _build_filter_config(self):
        self._load_categories_and_subs()
        sort_filter = {
            "key": "sort",
            "name": "排序",
            "value": [
                {"n": "默认", "v": ""},
                {"n": "最新", "v": "time"},
                {"n": "最热", "v": "hits"},
                {"n": "评分", "v": "score"}
            ]
        }
        filters = {}
        for c in self._cates_cache:
            cid = str(c["type_id"])
            f_list = [sort_filter]
            subs = self._subs_cache.get(cid) or []
            if subs:
                sub_filter = {
                    "key": "sub",
                    "name": "子分类",
                    "value": [{"n": "全部", "v": ""}] + subs
                }
                f_list.insert(0, sub_filter)
            filters[cid] = f_list
        return filters

    def homeContent(self, filter):
        self._load_categories_and_subs()
        res = {"class": self._cates_cache}
        if filter:
            res["filters"] = self._build_filter_config()
        return res

    def homeVideoContent(self):
        data = self._api_get("/relist")
        items = self._parse_videos(data)
        return {"list": items}

    def _looks_video(self, d):
        if not isinstance(d, dict):
            return False
        if d.get("href") or d.get("is_yp") or d.get("is_ad") or d.get("ad") is not None or d.get("ad_type"):
            return False
        if str(d.get("type", "")).lower() == "ad":
            return False
        has_id = any(d.get(k) is not None for k in ("id", "vod_id", "video_id"))
        has_name = any(d.get(k) for k in ("name", "title", "vod_name", "video_name"))
        return bool(has_id and has_name)

    def _to_item(self, v):
        if not isinstance(v, dict) or not self._looks_video(v):
            return None
        vid = v.get("id") or v.get("vod_id") or v.get("video_id")
        name = v.get("name") or v.get("title") or v.get("vod_name") or v.get("video_name")
        if vid is None or not name:
            return None

        vod_id = "%s/%s.html" % (self.base, vid)
        pic = v.get("enc_img") or v.get("pic") or v.get("cover") or v.get("img") or v.get("vod_pic") or ""
        pic = self._fix_url(pic)

        raw_meta = v.get("time") or v.get("duration") or v.get("vod_remarks") or ""
        remarks = format_remarks("ZakaTV", raw_meta)

        return {
            "vod_id": vod_id,
            "vod_name": str(name).strip()[:200],
            "vod_pic": self.fixCover(pic),
            "vod_remarks": remarks,
            "style": {"type": "rect", "ratio": 1.78}
        }

    def _parse_videos(self, data):
        items = []
        seen = set()
        candidates = []

        if isinstance(data, dict):
            for k in ("recommend_videos", "rank_videos", "list", "videos", "data", "rows"):
                blk = data.get(k)
                if isinstance(blk, list):
                    for x in blk:
                        if isinstance(x, dict) and self._looks_video(x):
                            candidates.append(x)
                elif isinstance(blk, dict) and isinstance(blk.get("videos"), list):
                    for x in blk["videos"]:
                        if isinstance(x, dict) and self._looks_video(x):
                            candidates.append(x)

        if not candidates and isinstance(data, list):
            for x in data:
                if isinstance(x, dict) and self._looks_video(x):
                    candidates.append(x)

        if not candidates:
            def walk(obj, depth=0):
                if depth > 8 or obj is None:
                    return
                if isinstance(obj, list):
                    for x in obj:
                        walk(x, depth + 1)
                elif isinstance(obj, dict):
                    if self._looks_video(obj):
                        candidates.append(obj)
                    for val in obj.values():
                        walk(val, depth + 1)
            walk(data)

        for it in candidates:
            item = self._to_item(it)
            if item and item["vod_id"] not in seen:
                seen.add(item["vod_id"])
                items.append(item)

        return items

    def _extract_pagination(self, data):
        total = 0
        pagecount = 0

        def walk(obj, depth=0):
            nonlocal total, pagecount
            if depth > 6 or obj is None:
                return
            if isinstance(obj, dict):
                for k, v in obj.items():
                    kl = str(k).lower().strip()
                    if isinstance(v, (int, float, str)):
                        sv = str(v).strip()
                        if sv.lstrip("-").isdigit():
                            nv = int(float(sv))
                            if kl in ("total", "total_count", "totalcount", "count", "record_count") and not total:
                                total = nv
                            elif kl in ("pagecount", "page_count", "pages", "total_page") and not pagecount:
                                pagecount = nv
                for val in obj.values():
                    if isinstance(val, (dict, list)):
                        walk(val, depth + 1)
            elif isinstance(obj, list):
                for x in obj:
                    if isinstance(x, (dict, list)):
                        walk(x, depth + 1)

        walk(data)
        return total, pagecount

    def _list_result(self, data, pg):
        items = self._parse_videos(data)
        total, pagecount = self._extract_pagination(data)
        current_pg = int(pg) if pg else 1
        if not pagecount:
            if total:
                pagecount = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            else:
                pagecount = current_pg + 1 if len(items) >= PAGE_SIZE else current_pg
        return {
            "list": items,
            "page": current_pg,
            "pagecount": pagecount,
            "limit": PAGE_SIZE,
            "total": total or len(items)
        }

    def categoryContent(self, tid, pg, filter, extend):
        pg_str = str(pg or "1")
        extend = extend or {}
        params = {"page": pg_str, "limit": PAGE_SIZE}

        sub_id = str(extend.get("sub", "")).strip()
        main_tid = str(tid or "").strip()

        if sub_id:
            params["cate_id"] = sub_id
            params["cate_pid"] = main_tid
        elif main_tid:
            params["cate_id"] = main_tid

        if extend.get("sort"):
            params["sort"] = str(extend["sort"])

        data = self._api_get("/vod", params)
        if not data and sub_id:
            params_retry = {"page": pg_str, "limit": PAGE_SIZE, "cate_id": main_tid, "cate_pid": sub_id}
            if extend.get("sort"):
                params_retry["sort"] = str(extend["sort"])
            data = self._api_get("/vod", params_retry)

        return self._list_result(data, pg_str)

    def searchContent(self, key, quick, pg="1"):
        pg_str = str(pg or "1")
        params = {"name": key, "page": pg_str, "limit": PAGE_SIZE}
        data = self._api_get("/vod", params)
        return self._list_result(data, pg_str)

    def _deep_field(self, obj, *keys, depth=0):
        if depth > 8 or obj is None:
            return ""
        if isinstance(obj, dict):
            for k in keys:
                v = obj.get(k)
                if v is not None and str(v).strip():
                    return str(v).strip()
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    r = self._deep_field(v, *keys, depth=depth + 1)
                    if r:
                        return r
        elif isinstance(obj, list):
            for x in obj:
                if isinstance(x, (dict, list)):
                    r = self._deep_field(x, *keys, depth=depth + 1)
                    if r:
                        return r
        return ""

    def _collect_play(self, obj, out, depth=0):
        if depth > 8 or obj is None:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and re.search(r"\.(m3u8|mp4|flv|webm|ts)(\?[^\"']*)?$", v, re.I):
                    clean_u = v.replace("\\/", "/")
                    if clean_u not in out:
                        out.append(clean_u)
                elif isinstance(v, (dict, list)):
                    self._collect_play(v, out, depth + 1)
        elif isinstance(obj, list):
            for x in obj:
                self._collect_play(x, out, depth + 1)

    def detailContent(self, array):
        vid = array[0] if isinstance(array, (list, tuple)) else str(array)
        m = re.search(r"/(\d+)(?:\.html)?(?:[?&]|$)", vid)
        id_ = m.group(1) if m else re.sub(r"\D", "", vid)
        data = self._api_get("vod/" + str(id_))
        obj = data if isinstance(data, dict) else {}

        name = self._deep_field(obj, "name", "title", "vod_name", "video_name")
        cover = self._deep_field(obj, "enc_img", "pic", "cover", "img", "vod_pic")
        cover = self._fix_url(cover)
        desc = self._deep_field(obj, "desc", "description", "content", "intro", "vod_content")
        raw_meta = self._deep_field(obj, "time", "duration", "vod_remarks")
        year = self._deep_field(obj, "year", "vod_year")
        area = self._deep_field(obj, "area", "region", "vod_area")

        play_urls = []
        self._collect_play(obj, play_urls)

        eps = []
        for idx, u in enumerate(play_urls):
            clean_u = u.replace("\\/", "/").strip()
            eps.append("线路%d$%s" % (idx + 1, clean_u))

        play_from = PLAY_FROM
        play_url = "#".join(eps) if eps else ("播放$%s/%s.html" % (self.base, id_))

        full_desc = (
            "【🔥 官方交流群: %s】\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "%s"
        ) % (self.tgGroup, desc or "极速高清资源已就绪")

        detail = {
            "vod_id": vid,
            "vod_name": name or str(id_),
            "vod_pic": self.fixCover(cover),
            "vod_year": year,
            "vod_area": area,
            "vod_actor": self.brandActor,
            "vod_director": self.brandDirector,
            "vod_remarks": format_remarks("ZakaTV", raw_meta),
            "vod_content": full_desc.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
            "vod_play_from": play_from,
            "vod_play_url": play_url
        }
        return {"list": [detail]}

    def playerContent(self, flag, id, vipFlags):
        url = str(id).strip()
        if not url.startswith("http"):
            url = self._fix_url(url)
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": {
                "User-Agent": self.ua,
                "Referer": self.base + "/",
                "Origin": self.base
            }
        }

    def action(self, action):
        return {"msg": "ok"}

    def liveContent(self):
        return ""

    @staticmethod
    def _looks_image(b):
        return (
            b[:3] == b"\xff\xd8\xff" or
            b[:4] == b"\x89PNG" or
            b[:3] == b"GIF" or
            b[:2] == b"BM" or
            b[:4] == b"RIFF" or
            b[:3] == b"WEB"
        )

    def _extract_proxy_url(self, param):
        if not param:
            return ""
        url = ""
        if isinstance(param, str):
            url = param
            if url.startswith("http") and "/proxy?" in url:
                try:
                    qs = parse_qs(urlsplit(url).query)
                    if qs.get("url"):
                        url = qs["url"][0]
                except Exception:
                    pass
        elif isinstance(param, dict):
            for k in ("url", "pic", "img", "target", "src", "image", "raw", "u"):
                v = param.get(k)
                if v:
                    url = v[0] if isinstance(v, list) and v else str(v)
                    break
        elif isinstance(param, (list, tuple)) and param:
            return self._extract_proxy_url(param[0])

        url = url.strip().strip("\"'").strip()
        try:
            while "%" in url:
                decoded = unquote(url)
                if decoded == url:
                    break
                url = decoded
        except Exception:
            pass
        return url

    def localProxy(self, param):
        try:
            url = self._extract_proxy_url(param)
            if not url or not url.startswith("http"):
                return [404, "text/plain", b"", "invalid url"]

            headers = {
                "User-Agent": self.ua,
                "Referer": self.base + "/",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"
            }
            res = self._fetch_raw(url, headers_custom=headers)
            if res.get("code") != 200 or not res.get("bytes"):
                return [404, "text/plain", b"", "fetch fail"]

            body = res["bytes"]
            if XOR_COVER and body and not self._looks_image(body[:16]):
                xored = bytes([x ^ 0x88 for x in body])
                if self._looks_image(xored[:16]):
                    body = xored

            ctype = "image/jpeg"
            if body[:3] == b"\xff\xd8\xff":
                ctype = "image/jpeg"
            elif body[:4] == b"\x89PNG":
                ctype = "image/png"
            elif body[:3] == b"GIF":
                ctype = "image/gif"

            extra_headers = (
                "Content-Type: %s\r\n"
                "Cache-Control: public, max-age=86400\r\n"
                "Content-Length: %d\r\n"
            ) % (ctype, len(body))

            return [200, ctype, body, extra_headers]
        except Exception as e:
            return [500, "text/plain", b"", str(e)]
