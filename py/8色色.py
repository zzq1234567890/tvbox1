# -*- coding: utf-8 -*-
"""
8涩独立图片查看 - 修复版
兼容：蜂蜜 / 鱼壳 / 默影视 / OK / PeekPro

封面自适应：
  - FongMi 系（蜂蜜/鱼壳/默影视）：proxy:// + localProxy（带 Referer）
  - PeekPro 等：图片URL@Referer=...
  自动检测 getProxyUrl，无需手动切换
播放：直连 / 带头 / 代理 三线路
速度：缓存 + 分页并行
"""
import re
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, unquote
from base.spider import Spider
from urllib3 import disable_warnings

disable_warnings()


class Spider(Spider):
    host = "https://8se.me"
    ref = "https://8se.me/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
        "Referer": "https://8se.me/",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "close",
    }

    img_headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
        "Referer": "https://8se.me/",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    _cache = {}
    _CACHE_TTL = 600
    _pic_mode = None  # 'proxy' | 'ref'，首次检测后缓存

    def getName(self):
        return "8涩独立图片查看修复版"

    def init(self, extend=""):
        # 允许手动指定封面模式：extend 里写 {"pic":"proxy"} 或 {"pic":"ref"}
        self._pic_mode = None
        try:
            if isinstance(extend, str) and extend.strip().startswith("{"):
                e = json.loads(extend)
                m = str(e.get("pic", "")).lower().strip()
                if m in ("proxy", "ref", "referer", "direct"):
                    self._pic_mode = "proxy" if m == "proxy" else "ref"
        except Exception:
            pass

    def homeContent(self, filter):
        classes = [
            {"type_id": "series-66600a3a227ee", "type_name": "私购流出"},
            {"type_id": "series-64be224b662c0", "type_name": "港模套图"},
            {"type_id": "series-5f1476781eab4", "type_name": "秀人网"},
            {"type_id": "series-64be21c972ca4", "type_name": "国模套图"},
            {"type_id": "series-6660093348354", "type_name": "秀人套图"},
            {"type_id": "series-665f66f97ec4d", "type_name": "街拍AI"},
        ]
        return {"class": classes, "filters": {}, "list": []}

    def _detect_pic_mode(self):
        """FongMi 系有 getProxyUrl → 用 proxy；否则用 @Referer（PeekPro）"""
        if self._pic_mode in ("proxy", "ref"):
            return self._pic_mode
        mode = "ref"
        try:
            # 蜂蜜 / 鱼壳 / 默影视 / FongMi 会提供此方法
            fn = getattr(self, "getProxyUrl", None)
            if callable(fn):
                u = fn(True)
                if u and ("proxy" in str(u).lower() or "9978" in str(u) or "http" in str(u)):
                    mode = "proxy"
        except Exception:
            pass
        # 再试无参
        if mode == "ref":
            try:
                fn = getattr(self, "getProxyUrl", None)
                if callable(fn):
                    u = fn()
                    if u:
                        mode = "proxy"
            except Exception:
                pass
        self._pic_mode = mode
        print(f"[pic_mode] {mode}")
        return mode

    def _norm_pic(self, pic):
        if not pic:
            return ""
        pic = str(pic).split("@")[0].strip()
        if pic.startswith("//"):
            pic = "https:" + pic
        pic = re.sub(r"/(\d+)_\d+x\d+\.webp", r"/\1.jpg", pic)
        return pic

    def _pic_for_list(self, pic):
        pic = self._norm_pic(pic)
        if not pic:
            return ""
        mode = self._detect_pic_mode()
        if mode == "proxy":
            # 默影视 / 蜂蜜 / 鱼壳
            return "proxy://do=py&url=" + quote(pic, safe="")
        # PeekPro / OK 等：URL 后缀 Referer
        return f"{pic}@Referer={self.ref}"

    def categoryContent(self, tid, pg, filter, extend):
        url = f"{self.host}/photos/{tid}/{pg}.html"
        try:
            res = requests.get(url, headers=self.headers, verify=False, timeout=10)
            res.encoding = "utf-8"
            html = res.text
            vod_list = []
            items = re.findall(
                r'class="item photo".*?href="/photo/id-([^"]+)\.html".*?title="([^"]+)"',
                html,
                re.S,
            )
            for mid, name in items:
                pic = ""
                img_style = re.search(
                    rf'id-{mid}\.html".*?style="[^"]*background-image:url\([\'"]([^\'"]+)[\'"]\)',
                    html,
                    re.S,
                )
                if img_style:
                    pic = img_style.group(1)
                if not pic:
                    img_attr = re.search(
                        rf'id-{mid}\.html".*?(?:data-original|src)="([^"]+)"',
                        html,
                        re.S,
                    )
                    if img_attr:
                        pic = img_attr.group(1)
                if not pic:
                    block = re.search(
                        rf'id-{re.escape(mid)}\.html".{{0,800}}',
                        html,
                        re.S,
                    )
                    if block:
                        m2 = re.search(
                            r'(?:https?:)?//[^"\'\s>]+\.(?:jpg|webp|png)',
                            block.group(0),
                            re.I,
                        )
                        if m2:
                            pic = m2.group(0)

                vod_list.append(
                    {
                        "vod_id": mid,
                        "vod_name": name,
                        "vod_pic": self._pic_for_list(pic),
                        "vod_remarks": "高清套图",
                    }
                )
            return {
                "page": int(pg),
                "pagecount": 99,
                "limit": 20,
                "total": 999,
                "list": vod_list,
            }
        except Exception as e:
            print("categoryContent error:", e)
            return {"list": []}

    def detailContent(self, ids):
        out = []
        try:
            mid = self._parse_mid(ids)
            if not mid:
                return {"list": []}

            images = self._get_album_images(mid)
            title = mid
            try:
                detail_url = f"{self.host}/photo/id-{mid}.html"
                res = requests.get(
                    detail_url, headers=self.headers, verify=False, timeout=8
                )
                res.encoding = "utf-8"
                t = re.search(r"<title>([^<]+)</title>", res.text, re.I)
                if t:
                    title = re.sub(r"\s*[-|].*$", "", t.group(1)).strip() or mid
            except Exception:
                pass

            pic = images[0] if images else ""
            out.append(
                {
                    "vod_id": mid,
                    "vod_name": title,
                    "vod_pic": self._pic_for_list(pic),
                    "vod_content": title,
                    "vod_play_from": "直连$$$带头$$$代理",
                    "vod_play_url": f"direct${mid}$$$ref${mid}$$$proxy${mid}",
                    "vod_player": "pics",
                    "vod_remarks": (str(len(images)) + "P") if images else "",
                }
            )
        except Exception as e:
            print("detailContent error:", e)
        return {"list": out}

    def playerContent(self, flag, id, vipFlags):
        try:
            mode = "direct"
            raw = str(id).strip()
            fl = str(flag or "").strip().lower()

            if "$" in raw:
                parts = raw.split("$")
                mode = (parts[0] or "direct").lower()
                mid = parts[-1]
            else:
                mid = raw

            if fl in ("带头", "ref", "referer"):
                mode = "ref"
            elif fl in ("代理", "proxy"):
                mode = "proxy"
            elif fl in ("直连", "direct"):
                mode = "direct"

            mid = self._parse_mid(mid)
            if not mid:
                return {"parse": 0, "playUrl": "", "url": ""}

            images = self._get_album_images(mid)
            if not images:
                return {"parse": 0, "playUrl": "", "url": ""}

            ua = self.img_headers["User-Agent"]

            if mode == "ref":
                tagged = [
                    f"{u.split('@')[0].strip()}@Referer={self.ref}&User-Agent={ua}"
                    for u in images
                ]
                url = "pics://" + "&&".join(tagged)
            elif mode == "proxy":
                proxied = [
                    "proxy://do=py&url=" + quote(u.split("@")[0].strip(), safe="")
                    for u in images
                ]
                url = "pics://" + "&&".join(proxied)
            else:
                url = "pics://" + "&&".join(
                    u.split("@")[0].strip() for u in images
                )

            return {
                "parse": 0,
                "playUrl": "",
                "url": url,
                "header": json.dumps(self.img_headers),
            }
        except Exception as e:
            print("playerContent error:", e)
            return {"parse": 0, "playUrl": "", "url": ""}

    def localProxy(self, params):
        try:
            url = params.get("url") or params.get("u") or ""
            if not url:
                return [404, "text/plain", b""]
            url = unquote(str(url))
            if not url.startswith("http"):
                m = re.search(r"(https?://[^\s&]+)", url)
                if m:
                    url = m.group(1)
            url = url.split("@")[0].strip()
            r = requests.get(
                url, headers=self.img_headers, verify=False, timeout=15
            )
            ct = r.headers.get("Content-Type", "image/jpeg")
            if "image" not in (ct or "") and r.content[:3] not in (
                b"\xff\xd8\xff",
                b"\x89PN",
            ):
                ct = "image/jpeg"
            return [200, ct, r.content]
        except Exception as e:
            print("localProxy error:", e)
            return [404, "text/plain", b""]

    def searchContent(self, key, quick, pg="1"):
        return {"list": []}

    def destroy(self):
        pass

    def _parse_mid(self, ids):
        mid = ""
        if isinstance(ids, (list, tuple)) and ids:
            mid = str(ids[0]).strip()
        elif isinstance(ids, str):
            mid = ids.strip()
        if "$" in mid:
            mid = mid.split("$")[-1]
        m = re.search(r"id-([a-zA-Z0-9]+)", mid)
        if m:
            mid = m.group(1)
        for prefix in ("direct", "ref", "proxy", "直连", "带头", "代理"):
            if mid.lower().startswith(prefix):
                mid = mid[len(prefix) :].lstrip("$_-")
        return mid.strip() if mid else ""

    def _cache_get(self, mid):
        item = self._cache.get(mid)
        if not item:
            return None
        ts, imgs = item
        if time.time() - ts > self._CACHE_TTL:
            self._cache.pop(mid, None)
            return None
        return imgs

    def _cache_set(self, mid, imgs):
        self._cache[mid] = (time.time(), imgs)

    def _extract_imgs(self, html, images, seen):
        for m in re.finditer(
            r"background-image:\s*url\([\'\"]?((?:https?:)?//[^\'\")]+)[\'\"]?\)",
            html,
            re.I,
        ):
            src = m.group(1)
            if src.startswith("//"):
                src = "https:" + src
            src = re.sub(r"/(\d+)_\d+x\d+\.webp", r"/\1.jpg", src)
            if src not in seen and any(x in src for x in (".jpg", ".webp", ".png")):
                seen.add(src)
                images.append(src)
        for m in re.finditer(
            r'(?:data-src|data-original|src)="((?:https?:)?//[^"]+\.(?:jpg|webp|png)[^"]*)"',
            html,
            re.I,
        ):
            src = m.group(1)
            if src.startswith("//"):
                src = "https:" + src
            src = re.sub(r"/(\d+)_\d+x\d+\.webp", r"/\1.jpg", src)
            if src not in seen:
                seen.add(src)
                images.append(src)

    def _fetch(self, url, timeout=8):
        try:
            r = requests.get(url, headers=self.headers, verify=False, timeout=timeout)
            r.encoding = "utf-8"
            return r.text
        except Exception as e:
            print("fetch fail:", url, e)
            return ""

    def _get_album_images(self, mid):
        cached = self._cache_get(mid)
        if cached is not None:
            print(f"[cache] {mid} -> {len(cached)}")
            return cached
        try:
            images = []
            seen = set()
            detail_url = f"{self.host}/photo/id-{mid}.html"
            html = self._fetch(detail_url, timeout=10)
            if not html:
                return []
            self._extract_imgs(html, images, seen)

            pages = re.findall(
                rf'href="(/photo/id-{re.escape(mid)}/\d+\.html)"', html
            )
            page_urls = []
            for p in set(pages):
                if p.endswith("/1.html"):
                    continue
                page_urls.append(self.host + p)

            if page_urls:
                with ThreadPoolExecutor(max_workers=min(6, len(page_urls))) as ex:
                    futs = {ex.submit(self._fetch, u, 8): u for u in page_urls}
                    for fut in as_completed(futs):
                        h = fut.result()
                        if h:
                            self._extract_imgs(h, images, seen)

            if not images:
                show_id = re.search(r'photoShow\.html\?id=([^"&]+)', html)
                if show_id:
                    show_url = f"{self.host}/photoShow.html?id={show_id.group(1)}"
                    show_html = self._fetch(show_url, timeout=8)
                    total_info = re.search(r"\(1/(\d+)\)", show_html or "")
                    img_info = re.search(
                        r'src="((?:https?:)?//[^"]+/(\d+)\.jpg)"', show_html or ""
                    )
                    if total_info and img_info:
                        total = int(total_info.group(1))
                        first_url = img_info.group(1)
                        if first_url.startswith("//"):
                            first_url = "https:" + first_url
                        prefix_num = img_info.group(2)
                        base_url = first_url.replace(f"{prefix_num}.jpg", "")
                        images = [
                            f"{base_url}{str(i).zfill(len(prefix_num))}.jpg"
                            for i in range(1, total + 1)
                        ]

            print(f"解析到 {len(images)} 张")
            self._cache_set(mid, images)
            return images
        except Exception as e:
            print("解析图集失败:", e)
            return []
