#!/usr/bin/python
# coding=utf-8
import base64
import hashlib
import json
import re
import time
import urllib.parse

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass

try:
    import requests
except Exception:
    requests = None

_easyocr_reader = None

import urllib.request


class Spider(BaseSpider):
    HOST = "https://wbbb1.com"
    PHOST = "xn--qvr2v.850088.xyz"
    PROXY = "https://py.fzcrym.link:1314"
    IMG_P = PROXY + "/wbb_img?u="
    PH_P = PROXY + "/wbb_ph?t="
    # 这些图床带 Referer 会 403，必须走代理剥离 Referer
    REF_BLOCK = ("iqiyipic.com", "hdslb.com", "bwcgee.cn", "imgurl.ggvip.click",
                 "meilinvps.com")
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    CATES = [("1", "电影"), ("2", "剧集"), ("3", "动漫"), ("4", "综艺")]
    SEGS = 12
    IDX = {"area": 1, "class": 3, "lang": 4, "letter": 5, "page": 8, "year": 11}

    def init(self, extend=""):
        self.filters_cache = {}
        self.last_req = 0.0
        self.gap = 0.6
        self.sess = requests.Session() if requests else None
        if self.sess:
            self.sess.headers.update({
                "User-Agent": self.UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
        self.fetch(self.HOST + "/")
        return self

    def getName(self):
        return "歪比巴卜"

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return any(x in u for x in (".m3u8", ".mp4", ".flv", ".mkv", ".ts"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        return

    def _throttle(self):
        d = time.time() - getattr(self, "last_req", 0)
        if d < self.gap:
            time.sleep(self.gap - d)
        self.last_req = time.time()

    def fetch(self, url, ref=None, tries=5, need=None):
        h = {"Referer": ref or (self.HOST + "/")}
        last = ""
        for i in range(tries):
            self._throttle()
            code = 0
            try:
                if self.sess:
                    r = self.sess.get(url, headers=h, timeout=25)
                    code, last = r.status_code, r.text
                else:
                    hh = dict(h)
                    hh["User-Agent"] = self.UA
                    rq = urllib.request.Request(url, headers=hh)
                    rs = urllib.request.urlopen(rq, timeout=25)
                    code, last = rs.getcode(), rs.read().decode("utf-8", "ignore")
                if code == 200 and (need is None or need in last or len(last) > 20000):
                    return last
            except Exception:
                pass
            # 429/403 是频率限制，退避后重放（同一 URL 二次请求即通）
            time.sleep(1.2 * (i + 1) if code in (403, 429) else 0.4)
        return last

    def post(self, url, data, ref=None):
        h = {"User-Agent": self.UA, "Referer": ref or (self.HOST + "/"),
             "X-Requested-With": "XMLHttpRequest",
             "Accept": "application/json, text/javascript, */*; q=0.01"}
        try:
            if self.sess:
                return self.sess.post(url, data=data, headers=h, timeout=25).text
            body = urllib.parse.urlencode(data).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
            return urllib.request.urlopen(urllib.request.Request(url, data=body, headers=h), timeout=25).read().decode("utf-8", "ignore")
        except Exception:
            return ""

    def fix_url(self, u):
        u = str(u or "").strip()
        if not u:
            return ""
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("/"):
            return self.HOST + u
        return u

    def clean(self, t):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t or "")).strip()

    def pic(self, raw, title=""):
        """封面归一：空/占位 → 生成海报；防盗链或死链图床 → 走代理（内部再回落占位）。"""
        u = str(raw or "").strip()
        t = urllib.parse.quote(title or "影片", safe="")
        if u in ("", "/", "#", "about:blank") or "load.gif" in u or "errorpic" in u:
            return self.PH_P + t
        u = self.fix_url(u)
        low = u.lower()
        if low.rstrip("/") in (self.HOST, self.HOST + "/") or low.endswith("wbbb1.com/"):
            return self.PH_P + t
        if low.startswith("http://") or any(h in low for h in self.REF_BLOCK):
            return self.IMG_P + urllib.parse.quote(u, safe="") + "&t=" + t
        return u

    def show_url(self, tid, ext, pg):
        seg = [""] * self.SEGS
        seg[0] = str(tid)
        for k, i in self.IDX.items():
            if k == "page":
                continue
            v = str((ext or {}).get(k) or "").strip()
            if v:
                seg[i] = urllib.parse.quote(v, safe="")
        seg[self.IDX["page"]] = str(pg)
        return "%s/show/%s.html" % (self.HOST, "-".join(seg))

    def parse_cards(self, html):
        out, seen = [], set()
        blocks = re.findall(r'<a[^>]+href="/detail/(\d+)\.html"[^>]*?title="([^"]*)"[\s\S]{0,900}?</a>', html)
        for vid, title in blocks:
            if vid in seen:
                continue
            seen.add(vid)
            out.append({"vod_id": vid, "vod_name": title, "vod_pic": "", "vod_remarks": ""})
        # 榜单/热搜页无 title 属性，标题在 infotitle 里
        for m in re.finditer(r'<a[^>]+href="/detail/(\d+)\.html"[^>]*>([\s\S]{0,500}?)</a>', html):
            vid, blk = m.group(1), m.group(2)
            if vid in seen:
                continue
            t = re.search(r'infotitle"?>([^<]{1,60})<', blk) or re.search(r'item-title"?>([^<]{1,60})<', blk)
            nm = self.clean(t.group(1)) if t else self.clean(blk)[:40]
            if not nm:
                continue
            seen.add(vid)
            note = re.search(r'<p>([^<]{0,20})</p>', blk)
            out.append({"vod_id": vid, "vod_name": nm, "vod_pic": "",
                        "vod_remarks": self.clean(note.group(1)) if note else ""})
        pics, notes = {}, {}
        for m in re.finditer(r'href="/detail/(\d+)\.html"[\s\S]{0,900}?</a>', html):
            blk = m.group(0)
            vid = m.group(1)
            p = re.search(r'data-original="([^"]+)"', blk) or re.search(r'<img[^>]+src="(https?[^"]+)"', blk)
            if p and vid not in pics:
                pics[vid] = p.group(1)
            n = re.search(r'class="module-item-note">([^<]{0,24})<', blk) or re.search(r'class="module-item-text">([^<]{0,24})<', blk)
            if n and vid not in notes:
                notes[vid] = self.clean(n.group(1))
        for v in out:
            if not v["vod_pic"]:
                v["vod_pic"] = pics.get(v["vod_id"], "")
            v["vod_pic"] = self.pic(v["vod_pic"], v["vod_name"])
            if not v["vod_remarks"]:
                v["vod_remarks"] = notes.get(v["vod_id"], "")
        return [v for v in out if v["vod_name"]]

    def get_filters(self, tid):
        if tid in self.filters_cache:
            return self.filters_cache[tid]
        html = self.fetch(self.show_url(tid, {}, 1), self.HOST + "/type/%s.html" % tid)
        groups = {"area": [], "class": [], "lang": [], "letter": [], "year": []}
        for m in re.finditer(r'href="/show/([^"]+)\.html"[^>]*>([^<]{1,12})</a>', html):
            raw, name = m.group(1), self.clean(m.group(2))
            if not name or name in ("全部",):
                continue
            parts = urllib.parse.unquote(raw).split("-")
            if len(parts) < self.SEGS:
                continue
            for key, idx in (("area", 1), ("class", 3), ("lang", 4), ("letter", 5), ("year", 11)):
                v = parts[idx] if idx < len(parts) else ""
                if v and v == name and all(
                        (parts[j] == "" or j == 0) for j in range(1, min(len(parts), self.SEGS)) if j != idx):
                    if not any(x["v"] == v for x in groups[key]):
                        groups[key].append({"n": name, "v": v})
        label = {"area": "地区", "class": "剧情", "lang": "语言", "letter": "字母", "year": "年份"}
        flt = []
        for key in ("class", "area", "year", "lang", "letter"):
            if not groups[key]:
                continue
            flt.append({"key": key, "name": label[key],
                        "value": [{"n": "全部", "v": ""}] + groups[key]})
        self.filters_cache[tid] = flt
        return flt

    def total_pages(self, html, pg):
        nums = [int(x) for x in re.findall(r'/show/[^"]*?-{8}(\d+)-{3}\.html', html)]
        return max(nums) if nums else pg + 1

    def homeContent(self, filter):
        cls = [{"type_id": t, "type_name": n} for t, n in self.CATES]
        flt = {}
        if filter:
            for t, _ in self.CATES:
                f = self.get_filters(t)
                if f:
                    flt[t] = f
        html = self.fetch(self.HOST + "/", need="module-item")
        return {"class": cls, "filters": flt, "list": self.parse_cards(html)}

    def homeVideoContent(self):
        return {"list": self.parse_cards(self.fetch(self.HOST + "/", need="module-item"))}

    def categoryContent(self, tid, pg, filter, extend):
        pg = max(int(pg or 1), 1)
        url = self.show_url(tid, extend or {}, pg)
        html = self.fetch(url, self.HOST + "/type/%s.html" % tid, need="module-item")
        vl = self.parse_cards(html)
        pc = self.total_pages(html, pg) if vl else pg
        return {"list": vl, "page": pg, "pagecount": pc, "limit": 72, "total": pc * 72}

    def _ocr_verify(self):
        """自动识别并提交搜索验证码(easyocr), 成功返回True。"""
        if self.sess is None:
            return False
        try:
            global _easyocr_reader
        except Exception:
            return False
        try:
            if _easyocr_reader is None:
                import easyocr
                _easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        except Exception:
            return False
        from PIL import Image
        for attempt in range(12):
            try:
                img = self.sess.get(self.HOST + "/index.php/verify/index.html",
                                    headers={"Referer": self.HOST + "/"}, timeout=20).content
                p = "/tmp/.wbb_v.png"
                open(p, "wb").write(img)
                code = "".join(_easyocr_reader.readtext(
                    p, allowlist="0123456789abcdefghijklmnopqrstuvwxyz",
                    detail=0)).strip()
                if not (3 <= len(code) <= 8):
                    continue
                r = self.sess.post(
                    self.HOST + "/index.php/ajax/verify_check?type=search&verify="
                    + urllib.parse.quote(code),
                    headers={"Referer": self.HOST + "/",
                             "X-Requested-With": "XMLHttpRequest"}, timeout=20)
                if r.text.startswith('{"code":1'):
                    return True
            except Exception:
                pass
            time.sleep(1.2)
        return False

    def searchContent(self, key, quick, pg="1"):
        pg = int(pg or 1)
        k = str(key or "").strip()
        # 路径式搜索URL(MACCMS标准), UTF-8关键词由requests自动编码:
        u = "%s/search/%s-------------.html" % (self.HOST, k)
        html = self.fetch(u, self.HOST + "/", tries=2, need=None)
        if "系统安全验证" in html or "需要输入验证码" in html or "访问此数据需要输入验证码" in html:
            if self._ocr_verify():
                time.sleep(4.5)
                html = self.fetch(u, self.HOST + "/", tries=2, need=None)
        if "请不要频繁操作" in html:
            time.sleep(4.5)
            html = self.fetch(u, self.HOST + "/", tries=2, need=None)
        vl = self.parse_cards(html)
        if vl:
            return {"list": vl, "page": pg, "pagecount": pg + 1 if len(vl) >= 20 else pg,
                    "limit": len(vl), "total": len(vl)}
        # 旧URL形式兜底:
        for u2 in ("%s/search/-------------.html?wd=%s&page=%d" % (self.HOST, urllib.parse.quote(k), pg),
                   "%s/index.php/vod/search/page/%d/wd/%s.html" % (self.HOST, pg, urllib.parse.quote(k))):
            html = self.fetch(u2, self.HOST + "/", tries=2, need=None)
            if "验证码" in html:
                if self._ocr_verify():
                    time.sleep(4.5)
                    html = self.fetch(u2, self.HOST + "/", tries=2, need=None)
            vl = self.parse_cards(html)
            if vl:
                return {"list": vl, "page": pg, "pagecount": pg + 1 if len(vl) >= 20 else pg,
                        "limit": len(vl), "total": len(vl)}
        return self.search_fallback(key, pg)

    def search_fallback(self, key, pg):
        """站点搜索有图形验证码，改用「分类+首字母」扫描 + 本地标题匹配。"""
        k = str(key or "").strip()
        if not k:
            return {"list": [], "page": pg, "pagecount": pg, "limit": 0, "total": 0}
        hits, seen = [], set()
        for tid, _ in self.CATES:
            for p in (pg,):
                r = self.categoryContent(tid, p, True, {})
                for v in r["list"]:
                    if k in v["vod_name"] and v["vod_id"] not in seen:
                        seen.add(v["vod_id"])
                        hits.append(v)
            if len(hits) >= 20:
                break
        if not hits:
            html = self.fetch(self.HOST + "/index.php/label/hot.html", self.HOST + "/", tries=3, need="detail/")
            for v in self.parse_cards(html):
                if k in v["vod_name"] and v["vod_id"] not in seen:
                    seen.add(v["vod_id"])
                    hits.append(v)
        return {"list": hits, "page": pg, "pagecount": pg + 1 if hits else pg,
                "limit": len(hits), "total": len(hits)}

    def detailContent(self, ids):
        vid = str(ids[0]) if ids else ""
        html = self.fetch("%s/detail/%s.html" % (self.HOST, vid), self.HOST + "/", need="module-info")
        if not html:
            return {"list": []}
        name = ""
        m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if m:
            name = self.clean(m.group(1))
        pic = ""
        for pat in (r'module-info-poster[\s\S]{0,300}?data-original="([^"]+)"',
                    r'module-item-pic[\s\S]{0,240}?data-original="([^"]+)"',
                    r'property="og:image"\s+content="([^"]+)"',
                    r'data-original="([^"]+)"'):
            mm = re.search(pat, html)
            if mm and mm.group(1).strip() not in ("", "/"):
                pic = mm.group(1)
                break
        pic = self.pic(pic, name)
        head = html[html.find("module-info-heading"):][:1400]
        year = area = ""
        types = []
        for a in re.finditer(r'<a[^>]+href="/show/([^"]+)\.html"[^>]*>([^<]{1,12})</a>', head):
            raw, txt = urllib.parse.unquote(a.group(1)), self.clean(a.group(2))
            parts = raw.split("-")
            if len(parts) > 11 and parts[11] == txt:
                year = txt
            elif len(parts) > 1 and parts[1] == txt:
                area = txt
            elif len(parts) > 3 and parts[3] == txt:
                types.append(txt)
        actor = director = remarks = ""
        for m in re.finditer(r'module-info-item[^>]*>([\s\S]{0,420}?)</div>\s*</div>', html):
            t = self.clean(m.group(1))
            if t.startswith("导演"):
                director = t.replace("导演：", "").strip(" /")
            elif t.startswith("主演") or t.startswith("演员"):
                actor = re.sub(r'^(主演|演员)：', "", t).strip(" /")
            if "备注：" in t:
                remarks = t.split("备注：")[-1].strip()
        desc = ""
        m = re.search(r'module-info-introduction[^>]*>([\s\S]{0,3000}?)</div>', html)
        if m:
            desc = self.clean(m.group(1))[:900]
        names = re.findall(r'data-dropdown-value="([^"]+)"', html)
        panels = re.findall(r'<div class="module-list[^"]*"[^>]*>([\s\S]{0,60000}?)(?=<div class="module-list|<script)', html)
        froms, urls = [], []
        for i, blk in enumerate(panels):
            eps = re.findall(r'href="(/vplay/[^"]+)"[^>]*>\s*<span>([^<]{0,40})</span>', blk)
            if not eps:
                eps = [(a, self.clean(b)) for a, b in re.findall(r'href="(/vplay/[^"]+)"[^>]*title="([^"]*)"', blk)]
            if not eps:
                continue
            froms.append(names[i] if i < len(names) else ("线路%d" % (i + 1)))
            seen, items = set(), []
            for href, label in eps:
                if href in seen:
                    continue
                seen.add(href)
                nm = self.clean(label) or ("第%d集" % (len(items) + 1))
                items.append("%s$%s" % (nm, href))
            urls.append("#".join(items))
        vod = {
            "vod_id": vid, "vod_name": name, "vod_pic": pic,
            "type_name": "/".join(types), "vod_year": year, "vod_area": area,
            "vod_remarks": remarks, "vod_actor": actor, "vod_director": director,
            "vod_content": desc,
            "vod_play_from": "$$$".join(froms) or "线路1",
            "vod_play_url": "$$$".join(urls),
        }
        return {"list": [vod]}

    def md5hex(self, s):
        return hashlib.md5(s.encode("utf-8")).hexdigest()

    def calc(self, x):
        return (self.md5hex(x) + " P")[-22:]

    def rc4(self, key, data):
        s = list(range(256))
        j = 0
        kl = len(key)
        for i in range(256):
            j = (j + s[i] + ord(key[i % kl])) % 256
            s[i], s[j] = s[j], s[i]
        out = bytearray()
        i = j = 0
        for ch in data:
            i = (i + 1) % 256
            j = (j + s[i]) % 256
            s[i], s[j] = s[j], s[i]
            out.append(ch ^ s[(s[i] + s[j]) % 256])
        return bytes(out)

    def b64d(self, s):
        s = str(s or "").replace("-", "+").replace("_", "/")
        return base64.b64decode(s + "=" * ((4 - len(s) % 4) % 4))

    def enplay(self, seed, x):
        return base64.b64encode(self.rc4(self.calc(seed), x.encode("latin-1", "ignore"))).decode()

    def deplay(self, seed, x):
        return self.rc4(self.calc(seed), self.b64d(x)).decode("latin-1")

    def aes_dec(self, b64, key, iv):
        raw = self.b64d(b64)
        k, v = key.encode()[:16], iv.encode()[:16]
        d = b""
        try:
            from Crypto.Cipher import AES
            d = AES.new(k, AES.MODE_CBC, v).decrypt(raw)
        except Exception:
            pass
        if not d:
            try:
                from Cryptodome.Cipher import AES
                d = AES.new(k, AES.MODE_CBC, v).decrypt(raw)
            except Exception:
                pass
        if not d:
            try:
                from cryptography.hazmat.backends import default_backend
                from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
                dec = Cipher(algorithms.AES(k), modes.CBC(v), backend=default_backend()).decryptor()
                d = dec.update(raw) + dec.finalize()
            except Exception:
                pass
        if not d:
            return ""
        n = d[-1] if d else 0
        if 1 <= n <= 16:
            d = d[:-n]
        return d.decode("utf-8", "ignore")

    def resolve(self, purl):
        u = str(purl or "").replace("http://", "https://")
        if not u:
            return "", ""
        t = int(time.time())
        pbase = "https://%s/player/" % self.PHOST
        body = self.post(pbase + "api.php", {
            "url": u,
            "key": self.enplay(u, self.md5hex(u + "stray")),
            "vkey": self.enplay(u, str(t) + self.md5hex(self.calc(u) + "stray")),
            "ckey": self.enplay(u, self.md5hex(self.PHOST + "stray")),
        }, pbase + "?url=" + u)
        try:
            j = json.loads(body)
        except Exception:
            return "", ""
        if str(j.get("code")) != "200" or not j.get("url"):
            return "", ""
        try:
            k = self.deplay(u, j["aes_key"])
            iv = self.deplay(u, j["aes_iv"])
        except Exception:
            return "", ""
        return self.aes_dec(j["url"], k, iv), str(j.get("type") or "")

    def playerContent(self, flag, id, vipFlags):
        pid = str(id or "")
        hdr = {"User-Agent": self.UA, "Referer": self.HOST + "/"}
        if self.isVideoFormat(pid) and pid.startswith("http"):
            return {"parse": 0, "playUrl": "", "url": pid, "header": json.dumps(hdr)}
        page = pid if pid.startswith("http") else self.fix_url(pid)
        ref = re.sub(r"/vplay/(\d+)-.*", r"/detail/\1.html", page)
        pj = None
        for rnd in range(3):
            html = self.fetch(page, ref, tries=6, need="player_aaaa")
            m = re.search(r'var player_aaaa\s*=\s*(\{.*?\})\s*</script>', html, re.S)
            if m:
                try:
                    pj = json.loads(m.group(1))
                    break
                except Exception:
                    pj = None
            self.fetch(ref, self.HOST + "/", tries=2)
            time.sleep(1.0 + rnd)
        if not pj:
            return {"parse": 1, "playUrl": "", "url": page, "header": json.dumps(hdr)}
        raw = pj.get("url") or ""
        enc = str(pj.get("encrypt") or "0")
        if enc == "1":
            raw = urllib.parse.unquote(raw)
        elif enc == "2":
            try:
                raw = urllib.parse.unquote(self.b64d(raw).decode("utf-8", "ignore"))
            except Exception:
                pass
        if raw.startswith("http") and self.isVideoFormat(raw):
            return {"parse": 0, "playUrl": "", "url": raw, "header": json.dumps(hdr)}
        real, _ = self.resolve(raw)
        if real and real.startswith("http"):
            return {"parse": 0, "playUrl": "", "url": real,
                    "header": json.dumps({"User-Agent": self.UA, "Referer": "https://%s/" % self.PHOST})}
        return {"parse": 1, "playUrl": "", "url": page, "header": json.dumps(hdr)}

    def localProxy(self, param):
        return [200, "text/plain", ""]
