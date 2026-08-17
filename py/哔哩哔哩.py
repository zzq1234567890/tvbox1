# -*- coding: utf-8 -*-
"""
哔哩哔哩 TVBox 爬虫（支持扫码登录 + Cookie 持久化 + 有声音）
==========================================================
- 播放地址使用 fnval=1 拿 durl（MP4/FLV 格式），音视频合一，普通 TVBox 播放器
  即可正常发声；fnval=16 走 DASH 容易出现「能看不能听」问题。
- Cookie 保存在脚本所在目录，应用重启后仍有效。
- 扫码登录后自动保存 Cookie，有效期约 30 天。
"""

from base.spider import Spider
import sys
import time
import json
import hashlib
import webbrowser
import requests
import urllib.parse
import re
from urllib.parse import urlencode
import os

# ===== 获取脚本所在目录（持久化存储位置） =====
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(_SCRIPT_DIR, exist_ok=True)

# 兼容老 / 极简 Python 运行时（部分盒子可能不带 threading）
try:
    import threading as _threading
    HAS_THREADING = True
except ImportError:
    HAS_THREADING = False
    _threading = None

# 兼容老 / 极简 Python 运行时（部分盒子可能不带 http.server）
try:
    import http.server as _http_server_mod
    import socketserver as _socketserver_mod
    HAS_HTTP_SERVER = True
except ImportError:
    HAS_HTTP_SERVER = False
    _http_server_mod = None
    _socketserver_mod = None

# QR 登录场景专用的内嵌 HTTP 服
_qr_http_server = None
_qr_http_thread = None
_qr_http_port = None
_qr_http_dir  = None

# ================= 配置 =================
API_BASE = "https://api.bilibili.com"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
    'Cookie': ''
}

TIMEOUT = 10
MAX_RETRIES = 3

QUALITY_MAP = [
    ("超清4K",   120),
    ("1080P+",   116),
    ("1080P+",   112),
    ("1080P",    80),
    ("高清",     64),
    ("标清",     32),
    ("流畅",     16),
]

REGION_MAP = {
    "6": "戏曲","1": "动画", "3": "音乐", "4": "游戏", "5": "娱乐",
    "11": "电视剧", "13": "番剧", "23": "电影", "36": "科技",
    "119": "鬼畜", "129": "舞蹈", "155": "生活", "160": "时尚",
    "181": "影视", "188": "纪录片", "217": "资讯", "234": "美食", "235": "国创"
}
CLASS_NAMES = "&".join(REGION_MAP.values())
CATEGORY_SEARCH_MAP = {"6": "戲曲"}

# ========================================
# ============== 调试日志 =====================
_SPIDER_LOG_FILE = None
for _d in ("/storage/emulated/0/Download", "/sdcard/Download", "/sdcard", _SCRIPT_DIR):
    try:
        if (os.path.isdir(_d) and os.access(_d, os.W_OK)):
            _SPIDER_LOG_FILE = os.path.join(_d, "spider_bilibili_xiqu.log")
            break
    except Exception:
        pass
if _SPIDER_LOG_FILE is None:
    try:
        if os.name == "nt":
            _ud = os.path.join(os.path.expanduser("~"), "Downloads")
            os.makedirs(_ud, exist_ok=True)
            _SPIDER_LOG_FILE = os.path.join(_ud, "spider_bilibili_xiqu.log")
        else:
            _SPIDER_LOG_FILE = "/tmp/spider_bilibili_xiqu.log"
    except Exception:
        _SPIDER_LOG_FILE = None

def _log(msg):
    try:
        line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + str(msg)
    except Exception:
        line = str(msg)
    try:
        print(line)
    except Exception:
        pass
    if _SPIDER_LOG_FILE:
        try:
            with open(_SPIDER_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

# ========================================
# ============== 本地 Cookie 加载 =====================
COOKIE_FILE_CANDIDATES = [
    os.path.join(_SCRIPT_DIR, "bili_cookie.json"),   # 首选
    "/storage/emulated/0/Download/bili_cookie.json",
    "/sdcard/Download/bili_cookie.json",
    "/sdcard/bili_cookie.json",
]
if os.name == "nt":
    _uk = os.path.join(os.path.expanduser("~"), "Downloads", "bili_cookie.json")
    if _uk not in COOKIE_FILE_CANDIDATES:
        COOKIE_FILE_CANDIDATES.insert(1, _uk)

def _load_cookie_file():
    for path in COOKIE_FILE_CANDIDATES:
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                ck = data.get("cookies", {})
                if ck.get("SESSDATA"):
                    _log(f"[cookie] loaded {path}, fields={list(ck.keys())}")
                    return ck
        except Exception as e:
            _log(f"[cookie] {path} read error: {e}")
    _log("[cookie] no valid cookie file found")
    return None

def _apply_cookies_to_headers(base_headers, cookies):
    if not cookies:
        return base_headers
    h = dict(base_headers)
    h["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return h

# ========================================
# ======  Cookie 有效性检测 =====================
def _check_cookie_valid(headers):
    try:
        url = f"{API_BASE}/x/web-interface/nav"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('code') == 0:
                return True
    except Exception as e:
        _log(f"[check] error: {e}")
    return False

# ========================================

class Spider(Spider):
    QR_LOGIN_TID    = "__qr_login__"
    QR_RELOGIN_TID  = "__qr_relogin__"

    def getName(self):
        return "哔哩哔哩"

    def init(self, extend):
        global HEADERS
        saved = _load_cookie_file()
        if saved:
            HEADERS = _apply_cookies_to_headers(HEADERS, saved)
            _log(f"[init] cookie loaded, user_id={saved.get('DedeUserID', '?')}")
            if not _check_cookie_valid(HEADERS):
                _log("[init] ⚠️ Cookie 已过期，请进入「📱 扫码登录」重新扫码")
            else:
                _log("[init] ✅ Cookie 有效，无需扫码")
        else:
            _log("[init] no cookie, using built-in empty header")
        _log(f"[init] 哔哩哔哩 spider 启动, log_file={_SPIDER_LOG_FILE}")

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    @staticmethod
    def _upscale_cover(url):
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        at = url.find("@")
        if at != -1:
            url = url[:at]
        return url

    # ---------- WBI 签名 ----------
    def _get_wbi_keys(self):
        try:
            url = f"{API_BASE}/x/web-interface/nav"
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code != 200:
                return None, None
            data = resp.json()
            if data.get('code') != 0:
                return None, None
            wbi_img = data.get('data', {}).get('wbi_img', {})
            img_url = wbi_img.get('img_url', '')
            sub_url = wbi_img.get('sub_url', '')
            img_key = img_url.split('/')[-1].split('.')[0] if img_url else ''
            sub_key = sub_url.split('/')[-1].split('.')[0] if sub_url else ''
            return img_key, sub_key
        except Exception as e:
            _log(f"获取WBI keys失败: {e}")
            return None, None

    def _encrypt_wbi(self, params, img_key, sub_key):
        if not img_key or not sub_key:
            return params
        mix_key = sub_key[:4] + img_key[:4]
        sorted_params = sorted(params.items())
        query = urlencode(sorted_params)
        sign = hashlib.md5((query + mix_key).encode()).hexdigest()
        params['w_rid'] = sign
        params['wts'] = int(time.time())
        return params

    def _wbi_request(self, url, params=None):
        if params is None:
            params = {}
        img_key, sub_key = self._get_wbi_keys()
        if img_key and sub_key:
            params = self._encrypt_wbi(params, img_key, sub_key)
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            return resp
        except Exception as e:
            _log(f"WBI请求失败: {e}")
            return None

    # ---------- 首页分类 ----------
    def homeContent(self, filter):
        class_list = CLASS_NAMES.split('&')
        classes = []
        for idx, name in enumerate(class_list):
            rid = None
            for k, v in REGION_MAP.items():
                if v == name:
                    rid = k
                    break
            if rid is None:
                rid = str(idx + 1)
            classes.append({"type_id": rid, "type_name": name})
        classes.insert(0, {
            "type_id": self.QR_RELOGIN_TID,
            "type_name": "🔄 清除 Cookie 重新登录",
        })
        classes.insert(0, {
            "type_id": self.QR_LOGIN_TID,
            "type_name": "📱 扫码登录",
        })
        return {"class": classes}

    def homeVideoContent(self):
        videos = []
        try:
            url = f"{API_BASE}/x/web-interface/ranking/v2"
            resp = requests.get(url, params={'rid': 1, 'type': 'all'},
                                headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('code') == 0:
                    for item in data.get('data', {}).get('list', [])[:6]:
                        bvid = item.get('bvid', '')
                        if not bvid:
                            continue
                        videos.append({
                            "vod_id": bvid,
                            "vod_name": item.get('title', ''),
                            "vod_pic": self._upscale_cover(item.get('pic', '')),
                            "vod_remarks": self._format_duration(item.get('duration', 0)),
                        })
        except:
            pass
        return {'list': videos}

    # ---------- 分类视频列表 ----------
    def categoryContent(self, cid, pg, filter, ext):
        if str(cid) == self.QR_RELOGIN_TID:
            return self._qr_relogin_category(int(pg) if pg else 1)
        if str(cid) == self.QR_LOGIN_TID:
            return self._qr_login_category(int(pg) if pg else 1)

        page = int(pg) if pg else 1
        search_keyword = CATEGORY_SEARCH_MAP.get(str(cid))
        if search_keyword:
            return self._search_as_category(search_keyword, page)

        videos = []
        try:
            url = f"{API_BASE}/x/web-interface/dynamic/region"
            resp = requests.get(url, params={'rid': cid, 'pn': page, 'ps': 20},
                                headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('code') == 0:
                    archives = data.get('data', {}).get('archives', [])
                    if archives:
                        for item in archives:
                            bvid = item.get('bvid', '')
                            if not bvid:
                                continue
                            videos.append({
                                "vod_id": bvid,
                                "vod_name": item.get('title', '无标题'),
                                "vod_pic": self._upscale_cover(item.get('pic', '')),
                                "vod_remarks": self._format_duration(item.get('duration', 0)),
                                "vod_content": item.get('desc', '')[:50]
                            })
                        return {
                            'list': videos,
                            'page': page,
                            'pagecount': 9999,
                            'limit': 20,
                            'total': 999999
                        }

            url2 = f"{API_BASE}/x/web-interface/ranking/v2"
            resp2 = requests.get(url2, params={'rid': cid, 'type': 'all'},
                                 headers=HEADERS, timeout=TIMEOUT)
            if resp2.status_code == 200:
                data2 = resp2.json()
                if data2.get('code') == 0:
                    for item in data2.get('data', {}).get('list', []):
                        bvid = item.get('bvid', '')
                        if not bvid:
                            continue
                        videos.append({
                            "vod_id": bvid,
                            "vod_name": item.get('title', '无标题'),
                            "vod_pic": self._upscale_cover(item.get('pic', '')),
                            "vod_remarks": self._format_duration(item.get('duration', 0)),
                            "vod_content": item.get('desc', '')[:50]
                        })
        except Exception as e:
            _log(f"categoryContent error: {e}")
            return {'list': []}

        return {
            'list': videos,
            'page': page,
            'pagecount': 9999,
            'limit': 20,
            'total': 999999
        }

    # ---------- 视频详情 ----------
    def detailContent(self, ids):
        bvid = ids[0]
        if str(bvid) == self.QR_LOGIN_TID:
            return self._qr_login_category(1)
        if not bvid:
            return {'list': []}

        try:
            view_url = f"{API_BASE}/x/web-interface/view?bvid={bvid}"
            resp = requests.get(view_url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code != 200:
                return {'list': []}
            view_data = resp.json()
            if view_data.get('code') != 0:
                return {'list': []}
            vinfo = view_data.get('data', {})

            title = vinfo.get('title', '')
            pic = self._upscale_cover(vinfo.get('pic', ''))
            desc = vinfo.get('desc', '')
            author = vinfo.get('owner', {}).get('name', '')
            tid = str(vinfo.get('tid', ''))
            type_name = REGION_MAP.get(tid, '')

            pages = vinfo.get('pages', [])
            if not pages:
                pages = [{'cid': vinfo.get('cid', 0), 'part': '完整视频'}]

            accept_q = set(vinfo.get('accept_quality') or [])
            if accept_q:
                available_q = [(n, q) for n, q in QUALITY_MAP if q in accept_q]
                if not available_q:
                    available_q = list(QUALITY_MAP)
            else:
                available_q = list(QUALITY_MAP)

            play_from = []
            play_url = []
            avid = vinfo.get('aid', 0)

            for qname, qn in available_q:
                urls = []
                for page in pages:
                    cid = page.get('cid', 0)
                    part_name = page.get('part', f'P{len(urls)+1}')
                    # ★ 关键修复：fnval=1 → 强制 B 站返回 durl（MP4 格式），
                    #   音视频合一，普通 TVBox 播放器（OK 影视等）能直接播。
                    #   fnval=16 走 DASH（视频/音频分两条流），多数 TVBox 播放器
                    #   不会同步混流 → 1080P 看着正常但**没有声音**。
                    # ★ 1080P 大会员/HEVC-only 视频可能仍然只返 DASH，
                    #   playerContent 里会再退化兜底。
                    play_req_url = (
                        f"{API_BASE}/x/player/playurl"
                        f"?avid={avid}&cid={cid}&qn={qn}"
                        f"&type=json&fnval=1&fnver=0"
                        f"&fourk=1&high_quality=1"
                        f"&platform=html5"
                    )
                    urls.append(f"{part_name}${play_req_url}")
                play_from.append(qname)
                play_url.append("#".join(urls))

            VOD = {
                "vod_id": bvid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_actor": author,
                "type_name": type_name,
                "vod_remarks": f"共{len(pages)}P",
                "vod_content": desc,
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url)
            }
            return {'list': [VOD]}
        except Exception as e:
            _log(f"detailContent error: {e}")
            return {'list': []}

    # ---------- 播放地址解析 ----------
    def playerContent(self, flag, id, vipFlags):
        if (isinstance(id, str) and (
            id.startswith("data:image") or
            "bili_qrcode" in id or
            id.endswith(".png")
        )):
            _log(f"[playerContent] 识别为二维码图片，直接返回: {id[:80]}")
            return {
                "parse": 0,
                "playUrl": '',
                "url": id,
                "header": {
                    **HEADERS,
                    "Content-Type": "image/png",
                    "Cache-Control": "no-cache",
                }
            }

        if str(flag) == self.QR_LOGIN_TID or str(id) == self.QR_LOGIN_TID:
            state = getattr(self, '_qr_state', None) or {}
            html_path = state.get("html_path", "")
            png_path  = state.get("png_path", "")
            qr_url    = state.get("qr_url", "")
            save_dir  = state.get("save_dir", "") or self._qr_save_dir()
            text_html_header = {
                **HEADERS,
                "Content-Type": "text/html; charset=utf-8",
                "Accept": "text/html,application/xhtml+xml,*/*",
            }

            if html_path and png_path and os.path.isfile(html_path) \
                    and os.path.isfile(png_path):
                inline_url = self._qr_build_inline_data_url(html_path, png_path, qr_url)
                if inline_url:
                    _log("[qr] playerContent 返回 data:text/html 内嵌 URL")
                    return {
                        "parse": 0, "playUrl": '', "url": inline_url,
                        "header": text_html_header,
                    }

            base_url = self._qr_start_http_server(save_dir)
            if base_url and html_path and os.path.isfile(html_path):
                rel = os.path.basename(html_path)
                url = base_url + rel
                _log(f"[qr] playerContent 返回 HTTP HTML {url}")
                return {
                    "parse": 0, "playUrl": '', "url": url,
                    "header": text_html_header,
                }

            if html_path and os.path.isfile(html_path):
                _log(f"[qr] playerContent 返回 file:// HTML {html_path}")
                return {
                    "parse": 0, "playUrl": '', "url": "file://" + html_path,
                    "header": text_html_header,
                }

            if png_path and os.path.isfile(png_path):
                img_url = ""
                if base_url:
                    card_name = "bili_qrcode_card.png"
                    raw_name = "bili_qrcode.png"
                    card_full = os.path.join(save_dir, card_name)
                    raw_full = os.path.join(save_dir, raw_name)
                    if os.path.isfile(card_full):
                        img_url = base_url + card_name
                    elif os.path.isfile(raw_full):
                        img_url = base_url + raw_name
                if not img_url:
                    img_url = state.get("preview_card_url") or state.get("data_url") or "file://" + png_path
                _log(f"[qr] playerContent 返回图片 {img_url[:80]}")
                return {
                    "parse": 0, "playUrl": '', "url": img_url,
                    "header": {**HEADERS, "Content-Type": "image/png"},
                }

            if qr_url:
                _log(f"[qr] playerContent 返回 URL {qr_url}")
                return {"parse": 0, "playUrl": '', "url": qr_url, "header": HEADERS}

            return {"parse": 0, "playUrl": '', "url": "about:blank", "header": HEADERS}

        # 正常视频播放解析
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(id, headers=HEADERS, timeout=TIMEOUT)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if data.get('code') != 0:
                    continue
                # === 路径 1：durl（MP4/FLV 格式，**音视频合一**）===
                durl = data.get('data', {}).get('durl', [])
                if durl:
                    play_url = durl[0].get('url', '')
                    if play_url:
                        # 同步从 durl 拿一下 audio 信息（用于诊断）
                        _log(f"[player] durl OK qn={data.get('data',{}).get('quality')} "
                             f"len={len(play_url)}")
                        return {"parse": 0, "playUrl": '', "url": play_url, "header": HEADERS}

                # === 路径 2：durl 为空 → 当前请求是 DASH（fnval=1 仍可能不返 durl，
                # 常见于 HEVC-only / 4K / 大会员限定）→ 再试一次强制 fnval=1
                dash = data.get('data', {}).get('dash', {})
                if dash:
                    _log(f"[player] 当前返 DASH（durl 为空），重试一次 fnval=1")
                    try:
                        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
                        u = urlparse(id)
                        qs = parse_qs(u.query)
                        qs['fnval'] = ['1']
                        # 强制 web 平台，避免 tv/ott 强制 dash
                        if 'platform' not in qs:
                            qs['platform'] = ['html5']
                        new_q = urlencode({k: v[0] for k, v in qs.items()})
                        retry_url = urlunparse((u.scheme, u.netloc, u.path,
                                                u.params, new_q, u.fragment))
                        r2 = requests.get(retry_url, headers=HEADERS, timeout=TIMEOUT)
                        if r2.status_code == 200:
                            d2 = r2.json()
                            durl2 = d2.get('data', {}).get('durl', [])
                            if durl2 and durl2[0].get('url'):
                                _log(f"[player] 二次请求拿到 durl（带音频）！")
                                return {"parse": 0, "playUrl": '',
                                        "url": durl2[0]['url'], "header": HEADERS}
                    except Exception as e_retry:
                        _log(f"[player] 二次请求异常: {e_retry}")

                    # === 路径 3：彻底没有 durl 只能用 DASH 时，把 audio 也带出来
                    video_list = dash.get('video', [])
                    audio_list = dash.get('audio', [])
                    if video_list:
                        play_url = video_list[0].get('baseUrl', '')
                        audio_url = (audio_list[0].get('baseUrl', '')
                                     if audio_list else '')
                        if play_url:
                            result = {
                                "parse": 0, "playUrl": '',
                                "url": play_url, "header": HEADERS,
                            }
                            if audio_url:
                                result["audioUrl"]  = audio_url
                                result["audio_url"] = audio_url
                            _log(f"[player] DASH fallback: video+audio "
                                 f"video_len={len(play_url)} audio={'yes' if audio_url else 'no'}")
                            return result
            except Exception as e:
                _log(f"playerContent attempt {attempt+1} error: {e}")
                time.sleep(1)
        return {"parse": 0, "playUrl": '', "url": 'about:blank', "header": HEADERS}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg=1):
        try:
            page = int(pg) if pg else 1
            params = {'keyword': key, 'page': page, 'search_type': 'video'}
            url = f"{API_BASE}/x/web-interface/wbi/search/type"
            resp = self._wbi_request(url, params)
            if not resp or resp.status_code != 200:
                resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
                if resp.status_code != 200:
                    return {'list': []}
            data = resp.json()
            if data.get('code') != 0:
                _log(f"searchContent API错误: {data.get('message')}")
                return {'list': []}

            videos = []
            result = data.get('data', {}).get('result', [])
            for item in result:
                bvid = item.get('bvid', '')
                if not bvid:
                    continue
                title = re.sub(r'<em[^>]*>|</em>', '', item.get('title', '无标题'))
                videos.append({
                    "vod_id": bvid,
                    "vod_name": title,
                    "vod_pic": self._upscale_cover(item.get('pic', '')),
                    "vod_remarks": self._format_duration(item.get('duration', 0)),
                    "vod_content": item.get('description', '')[:50]
                })
            return {
                'list': videos,
                'page': page,
                'pagecount': 9999,
                'limit': len(videos),
                'total': 999999
            }
        except Exception as e:
            _log(f"searchContent error: {e}")
            return {'list': []}

    # ---------- 辅助 ----------
    def _format_duration(self, seconds):
        if not seconds:
            return "00:00"
        if isinstance(seconds, str):
            s = seconds.strip()
            if re.match(r'^\d{1,3}:\d{2}(:\d{2})?$', s):
                return s
            digits = re.sub(r'\D', '', s)
            if not digits:
                return "00:00"
            try:
                seconds = int(digits)
            except Exception:
                return "00:00"
        try:
            total = int(seconds)
        except (ValueError, TypeError):
            return "00:00"
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    # ---------- 搜索结果作为分类列表 ----------
    def _search_as_category(self, keyword, page=1):
        res = self._search_tier_wbi(keyword, page)
        if res['list']:
            return res
        res = self._search_tier_legacy(keyword, page)
        if res['list']:
            return res
        res = self._search_tier_html(keyword, page)
        if res['list']:
            return res
        _log(f"[search-fail] keyword={keyword!r} page={page}, all tiers empty")
        return {'list': [], 'page': page, 'pagecount': 0, 'limit': 20, 'total': 0}

    def _search_tier_wbi(self, keyword, page):
        try:
            params = {'keyword': keyword, 'page': page, 'search_type': 'video'}
            url = f"{API_BASE}/x/web-interface/wbi/search/type"
            resp = self._wbi_request(url, params)
            if not resp or resp.status_code != 200:
                _log(f"[tier1] http={resp.status_code if resp else 'None'}")
                return {'list': []}
            data = resp.json()
            if data.get('code') != 0:
                _log(f"[tier1] api code={data.get('code')} msg={data.get('message')}")
                return {'list': []}
            return self._build_search_response(data.get('data', {}) or {}, page)
        except Exception as e:
            _log(f"[tier1] error: {e}")
            return {'list': []}

    def _search_tier_legacy(self, keyword, page):
        try:
            params = {'keyword': keyword, 'page': page}
            url = f"{API_BASE}/x/web-interface/search/all/v2"
            headers = dict(HEADERS)
            headers['Referer'] = 'https://search.bilibili.com/'
            resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
            if resp.status_code != 200:
                _log(f"[tier2] http={resp.status_code}")
                return {'list': []}
            data = resp.json()
            if data.get('code') != 0:
                _log(f"[tier2] api code={data.get('code')} msg={data.get('message')}")
                return {'list': []}
            payload = data.get('data')
            if isinstance(payload, list):
                items = payload
            elif isinstance(payload, dict):
                items = (payload.get('result') or payload.get('video')
                         or payload.get('items') or [])
            else:
                items = []
            videos = [v for v in (self._build_vod_from_search_item(it)
                                  for it in items) if v]
            _log(f"[tier2] http=200 code=0 items={len(items)} valid_bvid={len(videos)}")
            return {
                'list': videos,
                'page': page,
                'pagecount': 9999,
                'limit': 20,
                'total': 999999
            }
        except Exception as e:
            _log(f"[tier2] error: {e}")
            return {'list': []}

    def _search_tier_html(self, keyword, page):
        try:
            url = "https://search.bilibili.com/all"
            params = {'keyword': keyword, 'page': page, 'search_source': '3'}
            headers = dict(HEADERS)
            headers['Referer'] = 'https://search.bilibili.com/'
            resp = requests.get(url, params=params, headers=headers,
                                timeout=TIMEOUT, allow_redirects=True)
            if resp.status_code != 200:
                _log(f"[tier3] http={resp.status_code}")
                return {'list': []}
            html = resp.text
            _log(f"[tier3] http=200 bytes={len(html)}")

            if _SPIDER_LOG_FILE:
                try:
                    dump_path = _SPIDER_LOG_FILE + ".html"
                    with open(dump_path, "w", encoding="utf-8") as f:
                        f.write(html)
                    _log(f"[tier3] html dumped -> {dump_path}")
                except Exception as e:
                    _log(f"[tier3] html dump failed: {e}")

            if '风控' in html and len(html) < 5_000:
                _log("[tier3] returned 风控 challenge page")
                return {'list': []}

            candidates = (
                "window.__INITIAL_STATE__",
                "window.__INITIAL_DATA__",
                "window.__INITIAL_SSR_STATE__",
                "__NEXT_DATA__",
            )
            js_text = None
            used_name = None
            for nm in candidates:
                pos = html.find(nm)
                if pos == -1:
                    continue
                start = pos + len(nm)
                while start < len(html) and html[start] in ' \t\n\r=;:,':
                    start += 1
                end = html.find('</script>', start)
                if end == -1:
                    continue
                candidate = html[start:end]
                candidate = candidate.rstrip().rstrip(';').strip()
                if candidate and (candidate.startswith('{') or candidate.startswith('[')):
                    js_text = candidate
                    used_name = nm
                    break

            if not js_text:
                _log("[tier3] 4 个常见 JSON 容器都没找到")
                for kw in ("BV1", "result", "video", "戏曲", "戏曲折子", "戏曲视频"):
                    if kw in html:
                        _log(f"[tier3] hint: HTML 里出现 '{kw}'")
                return {'list': []}

            _log(f"[tier3] 用容器 {used_name}, js_text len={len(js_text)}")
            state = self._safe_load_json_like(js_text)
            if not state:
                _log("[tier3] JSON 解析失败")
                return {'list': []}

            videos = self._walk_extract_videos(state)
            _log(f"[tier3] DFS 找到 {len(videos)} 个视频对象")
            if not videos:
                return {'list': []}
            return {
                'list': videos,
                'page': page,
                'pagecount': 9999,
                'limit': 20,
                'total': 999999
            }
        except Exception as e:
            _log(f"[tier3] error: {e}")
            return {'list': []}

    def _build_vod_from_search_item(self, item):
        if not isinstance(item, dict):
            return None
        bvid = item.get('bvid', '')
        if not (isinstance(bvid, str) and bvid.startswith('BV') and len(bvid) >= 10):
            return None
        title = re.sub(r'<em[^>]*>|</em>', '', str(item.get('title', '无标题')))
        return {
            "vod_id": bvid,
            "vod_name": title,
            "vod_pic": self._upscale_cover(item.get('pic', '') or ''),
            "vod_remarks": self._format_duration(item.get('duration', 0)),
            "vod_content": (item.get('description') or
                            item.get('desc') or '')[:50]
        }

    def _build_search_response(self, payload, page):
        videos = [v for v in (self._build_vod_from_search_item(it)
                              for it in (payload.get('result') or []))
                  if v]
        num_pages = payload.get('numPages') or payload.get('pages') or 1
        num_results = payload.get('numResults') or payload.get('total') or 0
        return {
            'list': videos,
            'page': page,
            'pagecount': int(num_pages),
            'limit': 20,
            'total': int(num_results)
        }

    def _safe_load_json_like(self, js_text):
        try:
            return json.loads(js_text)
        except Exception:
            pass
        fixed = re.sub(r'\bundefined\b', 'null', js_text)
        fixed = re.sub(r'\bNaN\b', 'null', fixed)
        try:
            return json.loads(fixed)
        except Exception:
            return None

    def _walk_extract_videos(self, obj, depth=0, out=None):
        if out is None:
            out = []
        if depth > 25 or len(out) >= 50:
            return out
        if isinstance(obj, dict):
            bvid = obj.get('bvid')
            if (isinstance(bvid, str)
                    and bvid.startswith('BV') and len(bvid) >= 10):
                v = self._build_vod_from_search_item(obj)
                if v:
                    out.append(v)
            for v in obj.values():
                if len(out) >= 50:
                    break
                self._walk_extract_videos(v, depth + 1, out)
        elif isinstance(obj, list):
            for item in obj:
                if len(out) >= 50:
                    break
                self._walk_extract_videos(item, depth + 1, out)
        return out

    # ========================================
    # ====== TVBox 端的扫码登录入口 ======================
    # ========================================

    def _qr_save_dir(self):
        """优先使用脚本所在目录（持久化）"""
        if os.access(_SCRIPT_DIR, os.W_OK):
            return _SCRIPT_DIR
        for d in ("/storage/emulated/0/Download", "/sdcard/Download", "/sdcard", os.path.expanduser("~")):
            try:
                if os.path.isdir(d) and os.access(d, os.W_OK):
                    return d
            except Exception:
                continue
        return os.getcwd()

    def _qr_build_inline_data_url(self, html_path, png_path, qr_url):
        try:
            import base64 as _b64
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            if png_path and os.path.isfile(png_path):
                with open(png_path, "rb") as f:
                    png_b64 = _b64.b64encode(f.read()).decode()
                png_data_url = "data:image/png;base64," + png_b64
                html = re.sub(
                    r'<img\s+src="[^"]*qr\.png[^"]*"\s+alt="QR"\s*/?>',
                    f'<img src="{png_data_url}" alt="QR"/>',
                    html, flags=re.IGNORECASE
                )
            b64 = _b64.b64encode(html.encode("utf-8")).decode()
            url = "data:text/html;base64," + b64
            _log(f"[qr] 内联 data URL 长度 {len(url)}")
            return url
        except Exception as e:
            _log(f"[qr] 内联 data URL 失败: {e}")
            return ""

    def _qr_start_http_server(self, directory):
        global _qr_http_server, _qr_http_thread, _qr_http_port, _qr_http_dir
        if not HAS_HTTP_SERVER or not HAS_THREADING:
            return ""
        if (_qr_http_server is not None and _qr_http_dir == directory
                and _qr_http_port is not None):
            return f"http://127.0.0.1:{_qr_http_port}/"
        try:
            import socket as _sock
            _s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            _s.bind(('127.0.0.1', 0))
            port = _s.getsockname()[1]
            _s.close()

            _serve_dir = os.path.abspath(directory)
            _spider_ref = self

            class _QHandler(_http_server_mod.SimpleHTTPRequestHandler):
                def do_GET(self):
                    if self.path.split('?')[0] == '/qr_status':
                        try:
                            st = getattr(_spider_ref, '_qr_state', None) or {}
                            payload = json.dumps({
                                'status': st.get('status', ''),
                                'logged_in': bool(st.get('logged_in')),
                                'alive': bool(st.get('alive')),
                            }).encode('utf-8')
                        except Exception:
                            payload = b'{}'
                        self.send_response(200)
                        self.send_header('Content-Type',
                                         'application/json; charset=utf-8')
                        self.send_header('Content-Length', str(len(payload)))
                        self.send_header('Cache-Control', 'no-store')
                        self.end_headers()
                        self.wfile.write(payload)
                        return
                    return _http_server_mod.SimpleHTTPRequestHandler.do_GET(self)

                def translate_path(self, path):
                    path = path.split('?', 1)[0].split('#', 1)[0]
                    try:
                        path = urllib.parse.unquote(path)
                    except Exception:
                        pass
                    parts = [p for p in path.split('/') if p and p != '..']
                    target = _serve_dir
                    for p in parts:
                        target = os.path.join(target, p)
                    return target

                def log_message(self, fmt, *args):  # noqa
                    pass

            class _TServer(_socketserver_mod.ThreadingTCPServer):
                allow_reuse_address = True
                daemon_threads = True

            server = _TServer(('127.0.0.1', port), _QHandler)
            t = _threading.Thread(
                target=server.serve_forever, daemon=True, name="qr-http"
            )
            t.start()

            _qr_http_server = server
            _qr_http_thread = t
            _qr_http_port = port
            _qr_http_dir = directory
            _log(f"[qr] 临时 HTTP 服务已起 http://127.0.0.1:{port}/ dir={directory}")
            return f"http://127.0.0.1:{port}/"
        except Exception as e:
            _log(f"[qr] 起 HTTP 服务失败 {e}，回退到 file://")
            return ""

    def _qr_render_png(self, qr_url, png_path):
        try:
            import qrcode  # noqa
            from io import BytesIO
            import base64 as _b64

            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=24,
                border=4,
            )
            qr.add_data(qr_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            try:
                if hasattr(img, "convert") and getattr(img, "mode", "RGB") != "RGB":
                    img = img.convert("RGB")
                if hasattr(img, "size"):
                    w, h = img.size
                    if w != h:
                        from PIL import Image as _PILImage  # noqa
                        side = max(w, h)
                        canvas = _PILImage.new("RGB", (side, side), "white")
                        canvas.paste(img, ((side - w) // 2, (side - h) // 2))
                        img = canvas
                        _log(f"[qr] 检测到非正方形，已补成 {side}x{side}")
            except Exception as e_fix:
                _log(f"[qr] 正方形修正失败: {e_fix}")

            img.save(png_path, format='PNG')
            buf = BytesIO()
            img.save(buf, format='PNG')
            data_url = "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()
            return True, data_url
        except Exception as e:
            _log(f"[qr] 本地 qrcode 渲染失败: {e}")

        try:
            from urllib.parse import quote_plus
            api = ("https://api.qrserver.com/v1/create-qr-code/"
                   "?data=" + quote_plus(qr_url)
                   + "&size=1200x1200&margin=10"
                   + "&bgcolor=ffffff&color=000000&ecc=H")
            resp = requests.get(api, headers={"User-Agent": HEADERS["User-Agent"]},
                                timeout=15)
            if resp.status_code == 200 and len(resp.content) > 200:
                with open(png_path, "wb") as f:
                    f.write(resp.content)
                import base64 as _b64
                data_url = ("data:image/png;base64,"
                            + _b64.b64encode(resp.content).decode())
                return True, data_url
            _log(f"[qr] 外网 QR 生成失败 http={resp.status_code}")
        except Exception as e:
            _log(f"[qr] 外网 QR 生成异常: {e}")
        return False, ""

    def _qr_render_preview_card(self, qr_png_path, status_text, qr_url):
        try:
            from PIL import Image, ImageDraw, ImageFont  # noqa
            from io import BytesIO
            import base64 as _b64

            qr = Image.open(qr_png_path).convert("RGB")
            w, h = qr.size
            if w != h:
                side = max(w, h)
                canvas = Image.new("RGB", (side, side), "white")
                canvas.paste(qr, ((side - w) // 2, (side - h) // 2))
                qr = canvas
                w = h = side

            CW, CH = 1920, 1080
            card = Image.new("RGB", (CW, CH), (244, 245, 247))
            draw = ImageDraw.Draw(card)

            def _font(sz, bold=False):
                paths = []
                try:
                    if os.name == "nt":
                        paths += [r"C:\Windows\Fonts\msyh.ttc",
                                  r"C:\Windows\Fonts\msyh.ttf",
                                  r"C:\Windows\Fonts\simhei.ttf",
                                  r"C:\Windows\Fonts\arial.ttf"]
                    else:
                        paths += ["/System/Library/Fonts/PingFang.ttc",
                                  "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
                except Exception:
                    pass
                for p in paths:
                    try:
                        if os.path.isfile(p):
                            return ImageFont.truetype(p, sz)
                    except Exception:
                        pass
                try:
                    return ImageFont.load_default()
                except Exception:
                    return None

            f_status = _font(40)
            try:
                if f_status:
                    draw.text((60, 50), status_text, fill=(120, 120, 120), font=f_status)
                else:
                    draw.text((60, 50), status_text, fill=(120, 120, 120))
            except Exception:
                pass

            QR_SIDE = 880
            qr_resized = qr.resize((QR_SIDE, QR_SIDE), Image.NEAREST)
            card_x = (CW - QR_SIDE) // 2
            card_y = (CH - QR_SIDE) // 2 + 20
            draw.rectangle([card_x - 8, card_y - 8,
                            card_x + QR_SIDE + 7, card_y + QR_SIDE + 7],
                           fill=(255, 255, 255))
            card.paste(qr_resized, (card_x, card_y))

            f_title = _font(56)
            f_sub   = _font(34)
            f_url   = _font(28)
            base_y = card_y + QR_SIDE + 30
            try:
                if f_title:
                    draw.text((60, base_y),
                              "请用哔哩哔哩 APP 扫描此二维码登录",
                              fill=(40, 40, 40), font=f_title)
                else:
                    draw.text((60, base_y),
                              "请用哔哩哔哩 APP 扫描此二维码登录",
                              fill=(40, 40, 40))
                if f_sub:
                    draw.text((60, base_y + 80),
                              "手机哔哩哔哩 → 我的 → 扫一扫 → 对准屏幕",
                              fill=(110, 110, 110), font=f_sub)
                else:
                    draw.text((60, base_y + 80),
                              "手机哔哩哔哩 → 我的 → 扫一扫 → 对准屏幕",
                              fill=(110, 110, 110))
                if f_url:
                    draw.text((60, base_y + 145),
                              "如果扫不上，请复制下方链接到手机浏览器打开：",
                              fill=(160, 80, 80), font=f_url)
                else:
                    draw.text((60, base_y + 145),
                              "如果扫不上，请复制下方链接到手机浏览器打开：",
                              fill=(160, 80, 80))
                f_url_full = _font(26)
                if f_url_full:
                    draw.text((60, base_y + 195), qr_url,
                              fill=(120, 120, 120), font=f_url_full)
                else:
                    draw.text((60, base_y + 195), qr_url,
                              fill=(120, 120, 120))
            except Exception as e:
                _log(f"[qr] preview card 文字绘制失败（无伤大雅）: {e}")

            try:
                card.save(qr_png_path.replace("bili_qrcode.png",
                                              "bili_qrcode_card.png"),
                          format="PNG")
            except Exception as e:
                _log(f"[qr] preview card 落盘失败: {e}")

            buf = BytesIO()
            card.save(buf, format="PNG")
            return "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()
        except ImportError:
            _log("[qr] PIL/Pillow 未安装，走 PIL-free 路径")
        except Exception as e:
            _log(f"[qr] preview card 合成失败: {e}")

        try:
            import base64 as _b64
            if not os.path.isfile(qr_png_path):
                return ""
            try:
                with open(qr_png_path, "rb") as _src:
                    _raw = _src.read()
                card_path = qr_png_path.replace("bili_qrcode.png",
                                                 "bili_qrcode_card.png")
                with open(card_path, "wb") as _dst:
                    _dst.write(_raw)
            except Exception as e:
                _log(f"[qr] card 复制落盘失败: {e}")
            return "data:image/png;base64," + _b64.b64encode(_raw).decode()
        except Exception as e:
            _log(f"[qr] PIL-free 兜底也失败: {e}")
            return ""

    def _qr_make_html_wrapper(self, png_path, qr_url, data_url="", base_url=""):
        html_path = png_path.rsplit('.', 1)[0] + '.html'
        img_src = data_url if data_url else ("file://" + png_path)
        poll_js = ""
        if base_url:
            poll_js = (
                "<script>"
                "var st=document.getElementById('st');"
                "function tick(){"
                "  try{"
                "    var x=new XMLHttpRequest();"
                "    x.open('GET','" + base_url + "qr_status',true);"
                "    x.timeout=3000;"
                "    x.onreadystatechange=function(){"
                "      if(x.readyState===4&&x.status===200){"
                "        try{"
                "          var d=JSON.parse(x.responseText||'{}');"
                "          if(d.status){st.textContent=d.status;}"
                "          if(d.logged_in){"
                "            st.textContent='✓ 登录成功！窗口 5 秒后自动关闭';"
                "            st.style.color='#1a7f37';"
                "            setTimeout(function(){window.close();},5000);"
                "          }else if(!d.alive){"
                "            st.style.color='#c0392b';"
                "          }"
                "        }catch(e){}"
                "      }"
                "    };"
                "    x.send();"
                "  }catch(e){}"
                "}"
                "setInterval(tick,2000);tick();"
                "</script>"
            )
        content = (
            "<!DOCTYPE html>\n"
            "<html><head><meta charset=\"UTF-8\">"
            "<meta name=\"viewport\""
            " content=\"width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no\">"
            "<title>哔哩哔哩扫码登录</title>"
            "<style>"
            "* { box-sizing: border-box; margin: 0; padding: 0; }"
            "html, body { width: 100%; height: 100%; }"
            "body {"
            "  background: #f4f5f7;"
            "  font-family: -apple-system, BlinkMacSystemFont,"
            "    'PingFang SC', 'Microsoft YaHei', sans-serif;"
            "  display: flex; flex-direction: column;"
            "  overflow: hidden;"
            "}"
            ".main {"
            "  flex: 1 1 auto; min-height: 0;"
            "  display: flex; align-items: center; justify-content: center;"
            "  padding: 16px;"
            "}"
            ".qr {"
            "  background: #fff; border-radius: 16px;"
            "  padding: 14px;"
            "  box-shadow: 0 6px 28px rgba(0, 0, 0, .12);"
            "  width: min(78vmin, calc(100vh - 240px), calc(100vw - 32px), 640px);"
            "  height: min(78vmin, calc(100vh - 240px), calc(100vw - 32px), 640px);"
            "  display: flex; align-items: center; justify-content: center;"
            "}"
            ".qr img {"
            "  max-width: 100%; max-height: 100%;"
            "  display: block;"
            "  image-rendering: pixelated;"
            "  image-rendering: -moz-crisp-edges;"
            "  image-rendering: crisp-edges;"
            "}"
            ".info {"
            "  flex: 0 0 auto;"
            "  background: #fff;"
            "  border-top: 1px solid #eee;"
            "  padding: 14px 20px 22px;"
            "  text-align: center;"
            "}"
            ".info .title {"
            "  font-size: clamp(14px, 2.6vmin, 18px);"
            "  color: #333; font-weight: 600;"
            "}"
            ".info .status {"
            "  font-size: clamp(12px, 2.2vmin, 16px);"
            "  color: #e67e22; font-weight: 600; margin-top: 6px;"
            "}"
            ".info .sub {"
            "  font-size: clamp(11px, 1.9vmin, 13px);"
            "  color: #888; margin-top: 4px;"
            "}"
            ".info .url {"
            "  font-family: Menlo, Consolas, monospace;"
            "  font-size: clamp(9px, 1.5vmin, 11px);"
            "  color: #b0b0b0; word-break: break-all;"
            "  margin-top: 6px;"
            "}"
            "</style></head><body>"
            "<div class=\"main\">"
              "<div class=\"qr\">"
              f"<img src=\"{img_src}\" alt=\"QR\"/>"
              "</div>"
            "</div>"
            "<div class=\"info\">"
              "<div class=\"title\">请用哔哩哔哩 APP 扫描此二维码登录</div>"
              "<div class=\"status\" id=\"st\">等待扫码…</div>"
              "<div class=\"sub\">手机哔哩哔哩 → 我的 → 扫一扫 → 对准屏幕</div>"
              f"<div class=\"url\">扫码 URL：{qr_url}</div>"
            "</div>"
            + poll_js +
            "</body></html>"
        )
        try:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(content)
            return html_path
        except Exception as e:
            _log(f"[qr] HTML wrapper write failed: {e}")
            return None

    def _qr_start_new_login(self):
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": HEADERS["User-Agent"],
            "Referer":    "https://www.bilibili.com/",
            "Origin":     "https://www.bilibili.com",
        })

        try:
            resp = sess.get(CLI_QR_GEN_URL, timeout=TIMEOUT)
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"无法连接 B 站: {e}")
        if data.get("code") != 0:
            raise RuntimeError(f"生成二维码失败: {data}")
        qr = data["data"]
        qr_url, qr_key = qr["url"], qr["qrcode_key"]
        _log(f"[qr] QR 生成成功 url={qr_url} key={qr_key}")

        save_dir = self._qr_save_dir()
        png_path = os.path.join(save_dir, "bili_qrcode.png")
        rendered, data_url = self._qr_render_png(qr_url, png_path)
        image_url = "file://" + png_path if rendered else qr_url

        base_url = self._qr_start_http_server(save_dir)

        preview_card_url = ""
        if rendered:
            preview_card_url = self._qr_render_preview_card(
                png_path, "⏳ 等待扫码…", qr_url
            )
            card_disk = os.path.join(save_dir, "bili_qrcode_card.png")
            _log(
                "[qr] 预览卡合成 {0} size={1} card_disk={2} exists={3}"
                .format(
                    "成功" if preview_card_url else "失败",
                    len(preview_card_url or ""),
                    card_disk,
                    os.path.isfile(card_disk),
                )
            )

        html_path = None
        if rendered:
            html_path = self._qr_make_html_wrapper(png_path, qr_url, data_url,
                                                   base_url=base_url)

        state = {
            "sess":       sess,
            "qr_key":     qr_key,
            "qr_url":     qr_url,
            "image_url":  image_url,
            "data_url":   data_url,
            "png_path":   png_path,
            "html_path":  html_path,
            "preview_card_url": preview_card_url,
            "save_dir":   save_dir,
            "rendered":   rendered,
            "started_at": time.time(),
            "status":     "等待扫码…",
            "logged_in":  False,
            "alive":      True,
        }
        self._qr_state = state

        if HAS_THREADING and _threading is not None:
            try:
                t = _threading.Thread(
                    target=self._qr_poll_thread,
                    args=(sess, qr_key, state),
                    daemon=True,
                )
                t.start()
                self._qr_thread = t
                _log(f"[qr] 后台轮询线程已启动 key={qr_key}")
            except Exception as e:
                _log(f"[qr] 后台线程启动失败: {e}")

        _log(f"[qr] QR 已生成 png={png_path} rendered={rendered} "
             f"html={html_path} key={qr_key}")

    def _qr_poll_thread(self, sess, qr_key, state):
        deadline = time.time() + 300
        last_preview_status = None
        while time.time() < deadline and state.get("alive", False):
            try:
                resp = sess.get(CLI_QR_POLL_URL,
                                params={"qrcode_key": qr_key},
                                timeout=TIMEOUT)
                data = resp.json()
                code = data.get("data", {}).get("code", -1)
                if code == 0:
                    self._qr_save_cookies(sess)
                    state["logged_in"] = True
                    state["status"]  = "登录成功，Cookie 已自动更新，可关闭此页面"
                    state["alive"]   = False
                    self._refresh_preview_card(state)
                    _log("[qr] 后台轮询检测到登录成功")
                    return
                elif code == 86038:
                    state["status"] = "二维码已失效，请重新进入此分类"
                    state["alive"]  = False
                    self._refresh_preview_card(state)
                    return
                elif code == 86090:
                    state["status"] = "已扫码，请在手机上点击「确认登录」"
                elif code == 86101:
                    state["status"] = "等待扫码…"
                else:
                    state["status"] = "[{0}] {1}".format(
                        code, data.get("data", {}).get("message", ""))
            except Exception as e:
                _log(f"[qr] 后台 poll 异常: {e}")
            if state["status"] != last_preview_status:
                last_preview_status = state["status"]
                self._refresh_preview_card(state)
            time.sleep(2)
        if state.get("alive", False):
            state["status"] = "登录超时（5 分钟）"
            state["alive"]  = False
            self._refresh_preview_card(state)

    def _refresh_preview_card(self, state):
        if not state.get("rendered") or not state.get("png_path"):
            return
        if not os.path.isfile(state["png_path"]):
            return
        try:
            new_url = self._qr_render_preview_card(
                state["png_path"], state.get("status", "等待扫码…"),
                state.get("qr_url", "")
            )
            if new_url:
                state["preview_card_url"] = new_url
        except Exception as e:
            _log(f"[qr] 刷新预览卡失败: {e}")

    def _qr_poll_step(self, max_seconds=3):
        state = getattr(self, '_qr_state', None)
        if not state or not state.get("alive") or state.get("logged_in"):
            return
        sess, qr_key = state["sess"], state["qr_key"]
        deadline = time.time() + max_seconds
        while time.time() < deadline:
            try:
                data = sess.get(CLI_QR_POLL_URL,
                                params={"qrcode_key": qr_key},
                                timeout=TIMEOUT).json()
                code = data.get("data", {}).get("code", -1)
                if code == 0:
                    self._qr_save_cookies(sess)
                    state["logged_in"] = True
                    state["status"]    = "✓ 登录成功，Cookie 已自动更新"
                    state["alive"]     = False
                    return
                elif code == 86038:
                    state["status"] = "二维码已失效"
                    state["alive"]  = False
                    return
                elif code == 86090:
                    state["status"] = "已扫码，请在手机上点击「确认登录」"
                elif code == 86101:
                    state["status"] = "等待扫码…"
            except Exception as e:
                _log(f"[qr] step poll 异常: {e}")
            time.sleep(1)
            if state.get("logged_in") or not state.get("alive"):
                return

    def _qr_save_cookies(self, sess):
        cookies = sess.cookies.get_dict()
        if not cookies.get("SESSDATA"):
            _log("[qr] 未拿到 SESSDATA，跳过落盘")
            return False
        cookie_path = os.path.join(_SCRIPT_DIR, "bili_cookie.json")
        payload = {
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "user_id":  cookies.get("DedeUserID", ""),
            "buvid":    cookies.get("buvid3", ""),
            "cookies":  cookies,
        }
        try:
            with open(cookie_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            global HEADERS
            HEADERS = _apply_cookies_to_headers(HEADERS, cookies)
            _log(f"[qr] cookie 已落盘 {cookie_path} user_id={payload['user_id']}")
            return True
        except Exception as e:
            _log(f"[qr] cookie 写盘失败: {e}")
            return False

    def _qr_login_category(self, pg):
        try:
            state = getattr(self, '_qr_state', None)
            need_new = (
                state is None
                or not state.get("alive", False)
                or state.get("logged_in", False)
                or not state.get("image_url")
                or (state.get("png_path")
                    and not os.path.isfile(state["png_path"]))
                or (pg and int(pg) > 1 and not state.get("logged_in"))
            )
            if need_new:
                self._qr_start_new_login()
                state = self._qr_state

            self._qr_poll_step(max_seconds=3)
            state = getattr(self, '_qr_state', {}) or {}

            png_path   = state.get("png_path", "")
            html_path  = state.get("html_path", "")
            data_url   = state.get("data_url", "")
            image_url  = state.get("image_url", "")
            preview_card = state.get("preview_card_url", "")
            rendered   = state.get("rendered", False)
            status     = state.get("status", "等待扫码…")
            qr_url     = state.get("qr_url", "")

            if state.get("logged_in"):
                remark = "✓ 已登录"
            else:
                remark = "扫码登录"

            _sd = state.get("save_dir") or self._qr_save_dir()
            base_url = self._qr_start_http_server(_sd)

            thumb = ""
            if base_url:
                card_name = "bili_qrcode_card.png"
                raw_name  = "bili_qrcode.png"
                card_full = os.path.join(_sd, card_name)
                raw_full  = os.path.join(_sd, raw_name)
                if os.path.isfile(card_full):
                    thumb = base_url + card_name
                elif os.path.isfile(raw_full):
                    thumb = base_url + raw_name
            if not thumb:
                thumb = preview_card or data_url or image_url or ""
            if not thumb and png_path and os.path.isfile(png_path):
                thumb = "file://" + png_path

            play_sources = []
            if rendered and html_path and os.path.isfile(html_path):
                inline_url = self._qr_build_inline_data_url(html_path, png_path, qr_url)
                if inline_url:
                    play_sources.append(("扫码登录(HTML,自动关闭)", "默认$" + inline_url))
                elif base_url:
                    rel = os.path.basename(html_path)
                    play_sources.append(("扫码登录(HTML,自动关闭)", "默认$" + base_url + rel))
                else:
                    play_sources.append(("扫码登录(HTML,自动关闭)", "默认$" + "file://" + html_path))

            if rendered and png_path and os.path.isfile(png_path):
                img_url = ""
                if base_url:
                    card_name = "bili_qrcode_card.png"
                    raw_name = "bili_qrcode.png"
                    card_full = os.path.join(_sd, card_name)
                    raw_full = os.path.join(_sd, raw_name)
                    if os.path.isfile(card_full):
                        img_url = base_url + card_name
                    elif os.path.isfile(raw_full):
                        img_url = base_url + raw_name
                if not img_url:
                    img_url = preview_card or data_url or image_url or ""
                if img_url:
                    play_sources.append(("扫码登录(图片)", "默认$" + img_url))

            if not play_sources and qr_url:
                play_sources.append(("扫码登录(浏览器)", "默认$" + qr_url))

            if not play_sources:
                play_sources.append(("⚠️ 生成失败", "默认$about:blank"))

            _log(
                "[qr-cat] vod_pic={0}, 源数={1}, 状态={2}"
                .format(thumb[:100] + "..." if len(thumb)>100 else thumb,
                        len(play_sources), status)
            )

            vod_name = "📱 扫码登录（点击播放查看二维码）"
            vod_content = (
                "【扫码状态】 {0}\n\n"
                "【扫码 URL】 {1}\n"
                "（扫不上时，把这行链接复制到手机浏览器打开也可登录）\n\n"
                "【文件位置】\n"
                "  QR PNG : {2}\n"
                "  HTML   : {3}\n\n"
                "【使用说明】\n"
                "• 默认使用「HTML」源，登录后窗口会自动关闭。\n"
                "• 若无法弹出窗口，请手动切换至「图片」源（需手动关闭）。\n\n"
                "【操作步骤】\n"
                "1. 手机哔哩哔哩 → 我的 → 扫一扫\n"
                "2. 对准电视上的二维码（保持 20cm 距离）\n"
                "3. 手机弹「确认登录」时点确认\n"
                "4. 提示「登录成功」即可关闭窗口"
            ).format(status, qr_url, png_path, html_path)

            return {
                "list": [{
                    "vod_id":       self.QR_LOGIN_TID,
                    "vod_name":     vod_name,
                    "vod_pic":      thumb,
                    "vod_remarks":  remark,
                    "vod_content":  vod_content,
                    "vod_play_from": "$$$".join(s[0] for s in play_sources),
                    "vod_play_url":  "$$$".join(s[1] for s in play_sources),
                }],
                "page":       1,
                "pagecount":  1,
                "limit":       1,
                "total":       1,
            }
        except Exception as e:
            _log(f"[qr] _qr_login_category 失败: {e}")
            return {
                "list": [{
                    "vod_id":       self.QR_LOGIN_TID,
                    "vod_name":     f"扫码登录失败：{e}",
                    "vod_pic":      "",
                    "vod_remarks":  str(e),
                    "vod_play_from": "📱 扫码登录",
                    "vod_play_url":  "错误$about:blank",
                }],
                "page":       1,
                "pagecount":  1,
                "limit":      1,
                "total":      1,
            }

    # ========================================
    # ====== TVBox 端：一键清掉 Cookie 重新登录 ==========
    # ========================================

    def _qr_clear_local_cookies(self):
        cleared, failed = [], []
        for path in COOKIE_FILE_CANDIDATES:
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    cleared.append(path)
            except Exception as e:
                failed.append((path, str(e)))
                _log(f"[qr-relogin] 删除 {path} 失败: {e}")
        for qr_dir in ("/storage/emulated/0/Download",
                       "/sdcard/Download", "/sdcard"):
            qr_path = os.path.join(qr_dir, "bili_qrcode.png")
            try:
                if os.path.isfile(qr_path):
                    os.remove(qr_path)
                    cleared.append(qr_path)
            except Exception as e:
                _log(f"[qr-relogin] 删除 {qr_path} 失败: {e}")
        return cleared, failed

    def _qr_relogin_category(self, pg):
        cleared, failed = self._qr_clear_local_cookies()
        try:
            global HEADERS
            HEADERS = dict(HEADERS)
            HEADERS['Cookie'] = ''
        except Exception as e:
            _log(f"[qr-relogin] reset HEADERS Cookie 失败: {e}")
        try:
            self._qr_state = None
        except Exception:
            pass
        _log(f"[qr-relogin] cleared={len(cleared)} failed={len(failed)}")
        result = self._qr_login_category(pg)
        if isinstance(result, dict) and result.get("list"):
            head_vod = result["list"][0]
            head_vod["vod_content"] = (
                f"✓ 已清掉本地 cookie：{len(cleared)} 个文件\n"
                f"{'失败：' + str([(p, e) for p, e in failed]) if failed else '全部成功清掉'}\n"
                f"{head_vod.get('vod_content', '')}"
            )
            head_vod["vod_name"] = (
                f"✓ Cookie 已清除，待扫码登录 - {head_vod.get('vod_name', '')}"
            )
        return result


# ========================================
# ============== 命令行模式 =====================
CLI_QR_GEN_URL  = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
CLI_QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"

def _cli_find_save_dir():
    candidates = [
        _SCRIPT_DIR,
        os.path.join(os.path.expanduser("~"), "Downloads"),
        os.path.expanduser("~"),
        "/storage/emulated/0/Download",
        "/sdcard/Download",
        os.getcwd(),
    ]
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            test = os.path.join(d, ".bili_write_test")
            with open(test, "w") as f:
                f.write("ok")
            os.remove(test)
            return d
        except Exception:
            continue
    return os.getcwd()

def _cli_gen_qr(sess):
    resp = sess.get(CLI_QR_GEN_URL)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"生成二维码失败: {data}")
    return data["data"]

def _cli_poll_qr(sess, qrcode_key):
    resp = sess.get(CLI_QR_POLL_URL, params={"qrcode_key": qrcode_key})
    return resp.json()

def _cli_show_qr(qr_url):
    try:
        import qrcode
        qr = qrcode.QRCode(border=2, box_size=1)
        qr.add_data(qr_url)
        qr.make(fit=True)
        qr.print_ascii(tty=True)
        return True
    except ImportError:
        pass
    print("  (终端二维码不可用，可执行 `pip install qrcode[pil]` 启用)")
    try:
        webbrowser.open(qr_url)
        return True
    except Exception as e:
        print(f"  浏览器打开失败: {e}")
        print(f"  请手动复制此链接到浏览器：\n  {qr_url}")
        return False

def _cli_login_main():
    print("=" * 60)
    print(" 哔哩哔哩扫码登录工具（CLI 模式）")
    print("=" * 60)
    save_dir = _cli_find_save_dir()
    cookie_path = os.path.join(save_dir, "bili_cookie.json")
    print(f"Cookie 将保存到:\n  {cookie_path}\n")
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": HEADERS["User-Agent"],
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    })
    print("[1/4] 生成二维码...")
    try:
        qr = _cli_gen_qr(sess)
    except Exception as e:
        print(f"  ✗ {e}")
        sys.exit(1)
    qr_url = qr["url"]
    qr_key = qr["qrcode_key"]
    print(f"  qrcode_key = {qr_key}")
    print("\n[2/4] 请用哔哩哔哩 APP 扫一扫 ↓")
    _cli_show_qr(qr_url)
    print("\n[3/4] 等待手机确认登录（最长 3 分钟）...")
    deadline = time.time() + 180
    login_ok = False
    while time.time() < deadline:
        try:
            data = _cli_poll_qr(sess, qr_key)
        except Exception as e:
            print(f"  轮询异常: {e}")
            time.sleep(2)
            continue
        code = data.get("data", {}).get("code", -1)
        if code == 0:
            print("  ✓ 登录成功！")
            login_ok = True
            break
        elif code == 86038:
            print("  ✗ 二维码已失效，请重新运行")
            return
        elif code == 86090:
            print("  [已扫码] 请在手机上点击「确认登录」...")
        elif code == 86101:
            print("  [等待扫码] ...")
        else:
            print(f"  [{code}] {data.get('data', {}).get('message')}")
        time.sleep(2)

    if not login_ok:
        print("  ✗ 登录超时（3 分钟无操作）")
        sys.exit(1)

    cookies = sess.cookies.get_dict()
    if not cookies.get("SESSDATA"):
        print("  ✗ 响应里没有 SESSDATA，请重试")
        sys.exit(1)

    payload = {
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "user_id":  cookies.get("DedeUserID", ""),
        "buvid":    cookies.get("buvid3", ""),
        "cookies":  cookies,
    }
    with open(cookie_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n[4/4] Cookie 已保存\n  -> {cookie_path}")
    print(f"  user_id  = {payload['user_id']}")
    print(f"  saved_at = {payload['saved_at']}")
    print(f"  fields   = {', '.join(cookies.keys())}")
    print("\n" + "=" * 60)
    print(" 下一步：重启 TVBox，爬虫会自动加载此 Cookie，无需再次扫码。")
    print("=" * 60)


if __name__ == "__main__":
    try:
        _cli_login_main()
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(1)