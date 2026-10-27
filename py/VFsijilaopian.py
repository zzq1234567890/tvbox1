#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
import json
import base64
import html as html_lib
import urllib.request
import urllib.parse
from urllib.parse import urlparse, quote, unquote
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


def format_remarks(brand="ZakaTV", meta=""):
    clean_meta = str(meta or "").strip()
    clean_meta = re.sub(r"[\r\n\t]+", " ", clean_meta).strip()
    if clean_meta:
        return "%s | %s" % (brand, clean_meta)
    return brand


class Spider(SpiderBase):
    def __init__(self):
        super(Spider, self).__init__()
        self.siteUrl = "https://vintagepornfun.com"
        self.tgGroup = "https://t.me/+3t5XRPPo9mlkZDRl"
        self.brandActor = "📺TG群: https://t.me/+3t5XRPPo9mlkZDRl"
        self.brandDirector = "📺ZakaTV"
        self._ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        self.options = {}

        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        try:
            self.ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        except Exception:
            pass

        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

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
        return "Zaka·四季老片"

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".mkv", ".avi", ".ts", ".mpd", "index.png"))

    def manualVideoCheck(self):
        return False

    def _fetch(self, target_url, referer=""):
        if not target_url:
            return {"code": 0, "text": "", "bytes": b"", "err": "URL为空", "final_url": ""}
        if target_url.startswith("//"):
            target_url = "https:" + target_url
        elif target_url.startswith("/"):
            target_url = self.siteUrl + target_url

        headers = {
            "User-Agent": self._ua,
            "Referer": referer if referer else (self.siteUrl + "/"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }

        last_err = ""
        for attempt in range(2):
            try:
                req = urllib.request.Request(target_url, headers=headers)
                with self.opener.open(req, timeout=12) as resp:
                    code = resp.getcode()
                    final_url = resp.geturl()
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
                    return {"code": code, "text": text, "bytes": raw, "err": "", "final_url": final_url}
            except urllib.error.HTTPError as e:
                last_err = "HTTP %s" % e.code
                if e.code in (451, 403, 429) and attempt == 0:
                    continue
                err_raw = b""
                try:
                    err_raw = e.read()
                    if err_raw.startswith(b"\x1f\x8b"):
                        err_raw = gzip.decompress(err_raw)
                    err_text = err_raw.decode("utf-8", errors="ignore")
                except Exception:
                    err_text = ""
                return {"code": e.code, "text": err_text, "bytes": err_raw, "err": str(e), "final_url": target_url}
            except Exception as e:
                last_err = str(e)
                if attempt == 0:
                    continue
                return {"code": -1, "text": "", "bytes": b"", "err": str(e), "final_url": target_url}

        return {"code": -1, "text": "", "bytes": b"", "err": last_err, "final_url": target_url}

    def _unesc(self, s):
        try:
            return html_lib.unescape(s or "").strip()
        except Exception:
            return (s or "").strip()

    def homeContent(self, filter=False):
        classes = [
            {"type_name": "50s 经典", "type_id": "50s-porn"},
            {"type_name": "60s 经典", "type_id": "60s-porn"},
            {"type_name": "70s 经典", "type_id": "70s-porn"},
            {"type_name": "80s 经典", "type_id": "80s-porn"},
            {"type_name": "90s 经典", "type_id": "90s-porn"},
            {"type_name": "美洲经典", "type_id": "american-vintage-porn"},
            {"type_name": "亚洲复古", "type_id": "asian-vintage-porn"},
            {"type_name": "巴西经典", "type_id": "brazilian-vintage-porn"},
            {"type_name": "经典老片", "type_id": "classic-porn-movies"},
            {"type_name": "丹麦经典", "type_id": "danish-vintage-porn"},
            {"type_name": "荷兰经典", "type_id": "dutch-vintage-porn"},
            {"type_name": "法国浪漫", "type_id": "french-vintage-porn"},
            {"type_name": "德国经典", "type_id": "german-vintage-porn"},
            {"type_name": "黄金时代", "type_id": "golden-age-of-porn"},
            {"type_name": "印度复古", "type_id": "indian-vintage-porn"},
            {"type_name": "意大利经典", "type_id": "italian-vintage-porn"},
            {"type_name": "日本怀旧", "type_id": "japanese-vintage-porn"},
            {"type_name": "怀旧恶搞", "type_id": "vintage-parody-porn"},
            {"type_name": "复古电影", "type_id": "vintage-porn-movies"},
            {"type_name": "轻度柔和", "type_id": "vintage-softcore-movies"}
        ]
        res = {"class": classes}
        if filter:
            res["filters"] = {}
        return res

    def homeVideoContent(self):
        return {"list": []}

    def _parse_article_cards(self, html_text):
        vod_list = []
        seen = set()

        raw_cards = []
        if "<article" in html_text:
            splits = html_text.split("<article")[1:]
            for sp in splits:
                raw_cards.append("<article" + sp.split("</article>")[0])
        elif 'class="post' in html_text:
            splits = re.split(r'(?=<div[^>]+class=["\'][^"\']*post)', html_text)
            for sp in splits[1:]:
                raw_cards.append(sp[:4000])

        if not raw_cards:
            pattern = r'(<a[^>]+href=["\'](?:https?://vintagepornfun\.com)?/\d{4}/\d{2}/\d{2}/[^"\']+["\'][^>]*>[\s\S]*?</a>)'
            found = re.findall(pattern, html_text, re.I)
            raw_cards = found if found else [html_text]

        for block in raw_cards:
            links = re.findall(r'href=["\']((?:https?://vintagepornfun\.com)?/\d{4}/\d{2}/\d{2}/[^"\']+)["\']', block, re.I)
            if not links:
                continue

            clean_href = links[0].strip()
            if clean_href.startswith("/"):
                clean_href = self.siteUrl + clean_href

            if clean_href in seen:
                continue
            seen.add(clean_href)

            title_m = re.search(r'title=["\']([^"\']+)["\']', block)
            if not title_m:
                title_m = re.search(r'<h[234][^>]*>[\s\S]*?<a[^>]*>(.*?)</a>', block, re.I)
            if not title_m:
                title_m = re.search(r'alt=["\']([^"\']+)["\']', block)

            if title_m:
                raw_title = title_m.group(1)
                clean_title = self._unesc(re.sub(r'<[^>]+>', '', raw_title))
            else:
                clean_title = "经典影像"

            pic_m = re.search(r'(?:data-main-thumb|data-src|data-original)=["\']([^"\']+)["\']', block, re.I)
            if not pic_m:
                pic_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', block, re.I)

            raw_pic = pic_m.group(1).strip() if pic_m else ""
            if raw_pic.startswith("//"):
                raw_pic = "https:" + raw_pic
            elif raw_pic.startswith("/"):
                raw_pic = self.siteUrl + raw_pic

            pic = "%s@Referer=%s@User-Agent=%s" % (raw_pic, self.siteUrl + "/", quote(self._ua)) if raw_pic else ""

            duration_m = re.search(r'class=["\']duration["\'][^>]*>[\s\S]*?</i>\s*([^<]+)<', block, re.I)
            if not duration_m:
                duration_m = re.search(r'class=["\']duration["\'][^>]*>([^<]+)<', block, re.I)

            raw_duration = self._unesc(duration_m.group(1) if duration_m else "")
            remarks = format_remarks("ZakaTV", raw_duration)

            b64_href = base64.urlsafe_b64encode(clean_href.encode("utf-8")).decode("utf-8").rstrip("=")
            safe_id = "v_" + b64_href

            vod_list.append({
                "vod_id": safe_id,
                "vod_name": clean_title,
                "vod_pic": pic,
                "vod_remarks": remarks,
                "style": {"type": "rect", "ratio": 1.78}
            })

        return vod_list

    def categoryContent(self, tid, pg, filter=False, extend=None):
        slug = str(tid).strip("/")
        try:
            page_num = max(1, int(str(pg).strip() or 1))
        except Exception:
            page_num = 1

        if page_num == 1:
            target_url = "%s/category/%s/" % (self.siteUrl, slug)
        else:
            target_url = "%s/category/%s/page/%d/" % (self.siteUrl, slug, page_num)

        res = self._fetch(target_url)
        html_text = res.get("text", "")

        main_part = html_text
        for sep in ("<header", "<nav"):
            if sep in main_part:
                main_part = main_part.split(sep, 1)[-1]
        if "<footer" in main_part:
            main_part = main_part.split("<footer", 1)[0]

        vod_list = self._parse_article_cards(main_part)

        next_page_str = "/page/%d/" % (page_num + 1)
        has_next = False
        if next_page_str in html_text:
            has_next = True
        elif 'class="pagination"' in html_text and len(vod_list) >= 20:
            has_next = True

        return {
            "page": page_num,
            "pagecount": page_num + 1 if has_next else max(1, page_num),
            "limit": len(vod_list) if vod_list else 20,
            "total": 999 if has_next else len(vod_list),
            "list": vod_list
        }

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else str(ids)

        target_url = ""
        if str(raw_id).startswith("v_"):
            clean_b64 = raw_id[2:]
            pad_len = len(clean_b64) % 4
            if pad_len:
                clean_b64 += "=" * (4 - pad_len)
            try:
                target_url = base64.urlsafe_b64decode(clean_b64.encode("utf-8")).decode("utf-8")
            except Exception:
                target_url = ""

        if not target_url:
            target_url = raw_id if raw_id.startswith("http") else "%s/%s" % (self.siteUrl, raw_id.lstrip("/"))

        res = self._fetch(target_url)
        html_text = res.get("text", "")

        title_m = re.search(r'<h1[^>]*>(.*?)</h1>', html_text, re.S | re.I)
        vod_name = self._unesc(re.sub(r'<[^>]+>', '', title_m.group(1))) if title_m else "经典视频"

        pic_m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html_text, re.I)
        raw_pic = pic_m.group(1).strip() if pic_m else ""
        vod_pic = "%s@Referer=%s@User-Agent=%s" % (raw_pic, self.siteUrl + "/", quote(self._ua)) if raw_pic else ""

        all_iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html_text, re.I)
        valid_iframes = []
        for u in all_iframes:
            u_clean = u.strip()
            if u_clean.startswith("//"):
                u_clean = "https:" + u_clean
            if "whitetrafsa" in u_clean or not u_clean.startswith("http"):
                continue
            if u_clean not in valid_iframes:
                valid_iframes.append(u_clean)

        dood_lines = []
        other_lines = []
        for ifr in valid_iframes:
            if "d000d" in ifr or "dood" in ifr:
                dood_lines.append(ifr)
            else:
                other_lines.append(ifr)
        sorted_iframes = dood_lines + other_lines

        play_items = []
        for idx, ifr in enumerate(sorted_iframes):
            domain = urlparse(ifr).netloc or ("线路%d" % (idx + 1))
            clean_ifr = ifr.replace("$", "").replace("#", "")
            play_items.append("%s$%s" % (domain, clean_ifr))

        play_url_str = "#".join(play_items) if play_items else "线路探测$%s" % target_url.replace("$", "").replace("#", "")

        desc_content = (
            "【🔥 官方交流群: %s】\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "• 影片名称: %s\n"
            "• 播放源状态: 已解析出 %d 条真实正片播放线路\n"
            "• 默认线路: d000d / dood（置顶首选播放）\n"
            "• 品牌专区: ZakaTV致力于为您带来原生极速观影体验。"
        ) % (self.tgGroup, vod_name, len(valid_iframes))

        escaped_desc = desc_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        return {
            "list": [{
                "vod_id": raw_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_actor": self.brandActor,
                "vod_director": self.brandDirector,
                "vod_remarks": format_remarks("ZakaTV", "%d条线路" % len(valid_iframes)),
                "vod_content": escaped_desc,
                "vod_play_from": "原生专线",
                "vod_play_url": play_url_str
            }]
        }

    def playerContent(self, flag, id, vipFlags):
        url = str(id).strip()

        if any(ext in url.lower() for ext in (".mp4", ".m3u8", "index.png")):
            return {
                "parse": 0,
                "playUrl": "",
                "url": url,
                "header": {
                    "User-Agent": self._ua,
                    "Referer": self.siteUrl + "/"
                }
            }

        res = self._fetch(url, referer=self.siteUrl + "/")
        iframe_html = res.get("text", "")

        m_direct = re.search(r'(https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*)', iframe_html, re.I)
        if m_direct:
            return {
                "parse": 0,
                "playUrl": "",
                "url": m_direct.group(1),
                "header": {
                    "User-Agent": self._ua,
                    "Referer": url
                }
            }

        m_pass = re.search(r'/pass_md5/[^"\']+', iframe_html)
        if m_pass:
            domain = urlparse(url).netloc
            pass_url = "https://" + domain + m_pass.group(0)
            token_resp = self._fetch(pass_url, referer=url)
            prefix = token_resp.get("text", "").strip()
            if prefix:
                token = m_pass.group(0).split("/")[-1]
                final_stream = prefix + "1234567890?token=" + token
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": final_stream,
                    "header": {
                        "User-Agent": self._ua,
                        "Referer": url
                    }
                }

        return {
            "parse": 1,
            "playUrl": "",
            "url": url,
            "header": {
                "User-Agent": self._ua,
                "Referer": self.siteUrl + "/"
            }
        }

    def searchContent(self, key, quick, pg="1"):
        try:
            page_num = max(1, int(str(pg).strip() or 1))
        except Exception:
            page_num = 1

        encoded_key = quote(str(key))
        if page_num > 1:
            target_url = "%s/page/%d/?s=%s" % (self.siteUrl, page_num, encoded_key)
        else:
            target_url = "%s/?s=%s" % (self.siteUrl, encoded_key)

        res = self._fetch(target_url)
        html_text = res.get("text", "")

        main_part = html_text
        for sep in ("<header", "<nav"):
            if sep in main_part:
                main_part = main_part.split(sep, 1)[-1]
        if "<footer" in main_part:
            main_part = main_part.split("<footer", 1)[0]

        vod_list = self._parse_article_cards(main_part)

        next_page_str = "/page/%d/" % (page_num + 1)
        has_next = False
        if next_page_str in html_text:
            has_next = True
        elif 'class="pagination"' in html_text and len(vod_list) >= 20:
            has_next = True

        return {
            "page": page_num,
            "pagecount": page_num + 1 if has_next else max(1, page_num),
            "limit": len(vod_list) if vod_list else 20,
            "total": 999 if has_next else len(vod_list),
            "list": vod_list
        }

    def action(self, action):
        return {"msg": "ok"}

    def liveContent(self):
        return ""

    def localProxy(self, params):
        url = params.get("url", "")
        if not url:
            return [404, "text/plain; charset=utf-8", "Missing url parameter"]
        res = self._fetch(url, referer=self.siteUrl + "/")
        raw_bytes = res.get("bytes", b"")
        mime = "image/jpeg"
        if raw_bytes.startswith(b"\x89PNG"):
            mime = "image/png"
        elif raw_bytes.startswith(b"GIF8"):
            mime = "image/gif"
        elif raw_bytes.startswith(b"RIFF") and b"WEBP" in raw_bytes[:16]:
            mime = "image/webp"
        return [res.get("code", 200), mime, raw_bytes]

    def destroy(self):
        self.options = {}
