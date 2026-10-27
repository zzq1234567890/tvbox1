# -*- coding: utf-8 -*-
import base64
import html
import http.client
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from urllib.parse import quote, unquote, urljoin, urlparse

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass

HOST = "https://ryoz487.mmyy25.top"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

CATEGORIES = [
    {"type_name": "美女主播", "type_id": "6"},
    {"type_name": "精品推荐", "type_id": "7"},
    {"type_name": "自拍偷拍", "type_id": "3"},
    {"type_name": "国产乱伦", "type_id": "8"},
    {"type_name": "制服丝袜", "type_id": "9"},
    {"type_name": "传媒探花", "type_id": "10"},
    {"type_name": "清纯学生", "type_id": "11"},
    {"type_name": "淫妻作乐", "type_id": "12"},
    {"type_name": "反差母狗", "type_id": "13"},
    {"type_name": "足浴撩妹", "type_id": "17"},
    {"type_name": "制服诱惑", "type_id": "14"},
    {"type_name": "AI换脸", "type_id": "18"},
    {"type_name": "丝袜美腿", "type_id": "15"},
    {"type_name": "多人群交", "type_id": "4"},
    {"type_name": "中文字幕", "type_id": "16"},
    {"type_name": "主奴调教", "type_id": "5"},
]

FILTER_CONFIG = [
    {
        "key": "by",
        "name": "排序",
        "value": [
            {"n": "时间", "v": "time"},
            {"n": "人气", "v": "hits"},
            {"n": "评分", "v": "score"},
        ]
    }
]


class Spider(BaseSpider):

    def getName(self):
        return "momoyiyeqing"

    def init(self, extend=""):
        pass

    def _req(self, url, retry=3, timeout=12, referer=None):
        headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": referer if referer else (HOST + "/"),
        }
        for i in range(retry):
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

                req_obj = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req_obj, timeout=timeout, context=ctx) as resp:
                    data = resp.read()
                    real_url = resp.geturl()
                    for enc in ["utf-8", "gbk", "gb2312", "latin-1"]:
                        try:
                            return resp.getcode(), real_url, data.decode(enc)
                        except Exception:
                            continue
                    return resp.getcode(), real_url, data.decode("utf-8", errors="ignore")
            except urllib.error.HTTPError as he:
                return he.code, url, ""
            except Exception:
                if i < retry - 1:
                    time.sleep(0.3)
                else:
                    return 0, url, ""
        return 0, url, ""

    def _fix_url(self, url):
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return urljoin(HOST, url)
        if url.startswith("http"):
            return url
        return urljoin(HOST, "/" + url)

    def _clean_text(self, text):
        if not text:
            return ""
        return html.unescape(re.sub(r'<[^>]+>', '', str(text))).strip()

    def _parse_items(self, html_text):
        items = []
        if not html_text:
            return items

        raw_blocks = re.findall(r'<dl[^>]*>.*?</dl>', html_text, re.DOTALL | re.IGNORECASE)
        seen = set()

        for block in raw_blocks:
            href_m = re.search(r'href="([^"]*(?:/vod/play/id/|/id/)(\d+)[^"]*)"', block, re.IGNORECASE)
            if not href_m:
                continue

            vid = href_m.group(2)
            if vid in seen:
                continue

            pic = ""
            for p_attr in ["data-original", "data-src", "src"]:
                pm = re.search(r'%s="([^"]+)"' % p_attr, block, re.IGNORECASE)
                if pm:
                    val = pm.group(1).strip()
                    if val and "base64" not in val and not val.endswith(".gif"):
                        pic = self._fix_url(val)
                        break

            if not pic:
                continue

            title = ""
            for pat in [
                r'<h3[^>]*>(.*?)</h3>',
                r'alt="([^"]+)"',
                r'title="([^"]+)"'
            ]:
                tm = re.search(pat, block, re.IGNORECASE)
                if tm:
                    t_val = self._clean_text(tm.group(1))
                    if t_val and "友情链接" not in t_val:
                        title = t_val
                        break

            if not title:
                continue

            seen.add(vid)

            dur = ""
            dur_m = re.search(r'(\d+:\d+(?::\d+)?)', block)
            if dur_m:
                dur = dur_m.group(1)

            remarks = ("ZakaTV | %s" % dur) if dur else "ZakaTV"

            items.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks,
                "vod_pic_style": "1.78",
                "vod_card_style": "rect",
                "style": {"type": "rect", "ratio": 1.78}
            })

        return items

    def homeContent(self, filter):
        filters_map = {}
        for c in CATEGORIES:
            filters_map[c["type_id"]] = FILTER_CONFIG

        return {
            "class": CATEGORIES,
            "filters": filters_map,
            "list": [],
            "class_flag": 0,
            "style": {"type": "rect", "ratio": 1.78}
        }

    def homeVideoContent(self):
        url = "%s/index.php/vod/type/id/6.html" % HOST
        code, real_url, html_text = self._req(url)
        return {
            "list": self._parse_items(html_text),
            "style": {"type": "rect", "ratio": 1.78}
        }

    def categoryContent(self, tid, pg="1", filter=False, extend=None):
        p = int(pg) if str(pg).isdigit() else 1
        clean_tid = tid.strip("/")
        ext = extend if isinstance(extend, dict) else {}
        by = ext.get("by", "time") if ext else "time"

        if p > 1:
            url = "%s/index.php/vod/type/id/%s/page/%s.html" % (HOST, clean_tid, p)
        else:
            url = "%s/index.php/vod/type/id/%s.html" % (HOST, clean_tid)

        if by and by != "time":
            url = "%s?by=%s" % (url, quote(by))

        code, real_url, html_text = self._req(url)
        items = self._parse_items(html_text)

        pagecount = p
        pc_match = re.search(r'page/(\d+)\.html', html_text)
        if pc_match:
            try:
                pagecount = int(pc_match.group(1))
            except Exception:
                pagecount = p
        else:
            pc_match2 = re.search(r'共\s*(\d+)\s*页', html_text)
            if pc_match2:
                try:
                    pagecount = int(pc_match2.group(1))
                except Exception:
                    pagecount = p

        return {
            "list": items,
            "page": p,
            "pagecount": max(pagecount, p),
            "limit": 24,
            "total": 9999,
            "class_flag": 0,
            "style": {"type": "rect", "ratio": 1.78}
        }

    def detailContent(self, ids):
        if not ids:
            return {"list": []}

        vid = str(ids[0]).strip()
        play_url = "%s/index.php/vod/play/id/%s/sid/1/nid/1.html" % (HOST, vid)
        detail_url = "%s/index.php/vod/detail/id/%s.html" % (HOST, vid)

        code, real_url, html_text = self._req(play_url)
        if not html_text:
            code, real_url, html_text = self._req(detail_url)

        if not html_text:
            return {"list": []}

        title = ""
        meta_m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html_text, re.IGNORECASE)
        if meta_m:
            title = self._clean_text(meta_m.group(1))

        if not title:
            title_tag_m = re.search(r'<title>(.*?)</title>', html_text, re.DOTALL | re.IGNORECASE)
            if title_tag_m:
                raw_t = title_tag_m.group(1).split(" - ")[0].split("_")[0]
                t_clean = self._clean_text(raw_t)
                if t_clean and "友情链接" not in t_clean:
                    title = t_clean

        if not title:
            for pat in [
                r'<div[^>]*class="[^"]*(?:title|info|detail|player)[^"]*"[^>]*>\s*<h[1-3][^>]*>(.*?)</h[1-3]>',
                r'<h1[^>]*>(.*?)</h1>',
                r'<h2[^>]*>(.*?)</h2>',
            ]:
                tm = re.search(pat, html_text, re.DOTALL | re.IGNORECASE)
                if tm:
                    t_cand = self._clean_text(tm.group(1))
                    if t_cand and "友情链接" not in t_cand and not t_cand.startswith("精选视频"):
                        title = t_cand
                        break

        if not title:
            title = "精选视频 " + vid

        pic = ""
        og_pic_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html_text, re.IGNORECASE)
        if og_pic_m:
            pic = self._fix_url(og_pic_m.group(1))

        if not pic:
            pic_m = re.search(r'<img[^>]+(?:class="[^"]*(?:poster|cover|pic|nature)[^"]*"[^>]+)?src="([^"]+)"', html_text, re.IGNORECASE)
            if pic_m:
                pic = self._fix_url(pic_m.group(1))

        play_link = ""
        m_json = re.search(r'player_data\s*=\s*(\{.*?\})', html_text, re.DOTALL)
        if m_json:
            try:
                pdata = json.loads(m_json.group(1))
                play_link = pdata.get("url", "")
            except Exception:
                pass

        if not play_link:
            m_now = re.search(r'var\s+now\s*=\s*["\']([^"\']+)["\']', html_text)
            if m_now:
                play_link = m_now.group(1)

        if not play_link:
            m_m3u8 = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', html_text)
            if m_m3u8:
                play_link = m_m3u8.group(1)

        if not play_link:
            m_mp4 = re.search(r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)', html_text)
            if m_mp4:
                play_link = m_mp4.group(1)

        if not play_link:
            m_iframe = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html_text)
            if m_iframe:
                iframe_src = self._fix_url(m_iframe.group(1))
                _, _, iframe_html = self._req(iframe_src, referer=play_url)
                if iframe_html:
                    m2 = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', iframe_html)
                    if m2:
                        play_link = m2.group(1)

        final_play_url = ("正片$%s" % play_link) if play_link else ("正片$%s" % play_url)
        notice_desc = "📺ZakaTV 独家呈现\n官方交流群: https://t.me/+3t5XRPPo9mlkZDRl"

        vod = {
            "vod_id": vid,
            "vod_name": html.unescape(title),
            "vod_pic": pic,
            "vod_year": "",
            "vod_area": "",
            "vod_actor": "📺TG群: https://t.me/+3t5XRPPo9mlkZDRl",
            "vod_director": "📺ZakaTV",
            "vod_content": notice_desc,
            "vod_remarks": "ZakaTV",
            "vod_play_from": "ZakaTV",
            "vod_play_url": final_play_url,
        }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        headers = {
            "User-Agent": UA,
            "Referer": HOST + "/"
        }
        return {
            "parse": 0,
            "playUrl": "",
            "url": id,
            "header": json.dumps(headers)
        }

    def searchContent(self, key, quick=False, pg="1"):
        p = int(pg) if str(pg).isdigit() else 1
        url = "%s/index.php/vod/search.html?wd=%s&page=%s" % (HOST, quote(key), p)
        code, real_url, html_text = self._req(url)
        items = self._parse_items(html_text)

        return {
            "list": items,
            "page": p,
            "pagecount": 999,
            "limit": 24,
            "total": 9999,
            "class_flag": 0,
            "style": {"type": "rect", "ratio": 1.78}
        }

    def localProxy(self, params):
        return [200, "text/plain; charset=utf-8", b"", None]

    def action(self, action):
        return {}

    def liveContent(self):
        return {}

    def manualVideoCheck(self):
        return False

    def isVideoFormat(self, url):
        return False

    def destroy(self):
        pass
