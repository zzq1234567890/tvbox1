# -*- coding: utf-8 -*-
"""
哔哩哔哩 TVBox 爬虫（支持扫码登录 + 自动关闭窗口）
======================================================
- 首页增加「📱 扫码登录」分类，点击进入显示二维码。
- 点击「播放」会优先打开一个含轮询的 HTML 页面，登录成功后自动关闭。
- 若 HTML 无法打开，可切换至备用的「图片」源（手动关闭）。
- 登录后自动保存 Cookie，后续视频使用高画质。
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

# QR 登录场景专用的内嵌 HTTP 服（让 TVBox 拿到 http:// URL 必然走 webview）
_qr_http_server = None     # HTTPServer 实例
_qr_http_thread = None     # serve_forever 守护线程
_qr_http_port = None       # 监听端口
_qr_http_dir  = None       # 服务根目录

# ================= 配置 =================
API_BASE = "https://api.bilibili.com"

# 默认请求头（init 时如加载到本地 cookie 文件，会覆盖 Cookie）
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
    'Cookie': ''
}

TIMEOUT = 10
MAX_RETRIES = 3

# --------------- 高清清晰度映射 ---------------
# qn 编号说明（B站官方定义）：
#   16   = 360P 流畅
#   32   = 480P 标清
#   64   = 720P 高清
#   80   = 1080P（需登录）
#   112  = 1080P+ 高码率（需大会员）
#   116  = 1080P+ HDR（需大会员）
#   120  = 4K 超清（需大会员）
# 大会员可拿到 120，普通登录最高 80，未登录最高 32。
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

CATEGORY_SEARCH_MAP = {
    "6": "戲曲",  # rid=6 (戏曲) → 繁体"戲曲"搜索
}

# ========================================
# ============== 调试日志 =====================
import os as _ospider_log
_SPIDER_LOG_FILE = None
for _d in ("/storage/emulated/0/Download", "/sdcard/Download", "/sdcard"):
    try:
        if (_ospider_log.path.isdir(_d)
                and _ospider_log.access(_d, _ospider_log.W_OK)):
            _SPIDER_LOG_FILE = _ospider_log.path.join(_d, "spider_bilibili_xiqu.log")
            break
    except Exception:
        pass
if _SPIDER_LOG_FILE is None:
    try:
        if _ospider_log.name == "nt":
            _ud = _ospider_log.path.join(_ospider_log.path.expanduser("~"), "Downloads")
            _ospider_log.makedirs(_ud, exist_ok=True)
            _SPIDER_LOG_FILE = _ospider_log.path.join(_ud, "spider_bilibili_xiqu.log")
        else:
            _SPIDER_LOG_FILE = "/tmp/spider_bilibili_xiqu.log"
    except Exception:
        _SPIDER_LOG_FILE = None


def _log(msg):
    """双通道：stdout + 文件。TVBox 端以文件为准，桌面跑以终端为准。"""
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

# ========================================
# ============== 本地 Cookie 加载 =====================
# 登录后由 bile_login.py 写到下面任一路径，启动时自动加载。
# 路径顺序：盒子内置 -> sdcard -> 用户家目录下载 -> 当前目录。
COOKIE_FILE_CANDIDATES = [
    "/storage/emulated/0/Download/bili_cookie.json",
    "/sdcard/Download/bili_cookie.json",
    "/sdcard/bili_cookie.json",
]
if _ospider_log.name == "nt":
    _uk = _ospider_log.path.join(_ospider_log.path.expanduser("~"),
                                 "Downloads", "bili_cookie.json")
    if _uk not in COOKIE_FILE_CANDIDATES:
        COOKIE_FILE_CANDIDATES.insert(0, _uk)


def _load_cookie_file():
    """从硬盘加载已扫码登录保存的 Cookie（如果存在）"""
    for path in COOKIE_FILE_CANDIDATES:
        try:
            if _ospider_log.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                ck = data.get("cookies", {})
                if ck.get("SESSDATA"):
                    _log(f"[cookie] loaded {path}, fields={list(ck.keys())}")
                    return ck
        except Exception as e:
            _log(f"[cookie] {path} read error: {e}")
    _log("[cookie] no valid cookie file found, using default header Cookie")
    return None


def _apply_cookies_to_headers(base_headers, cookies):
    if not cookies:
        return base_headers
    h = dict(base_headers)
    h["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return h
# ========================================


class Spider(Spider):
    # 特殊 type_id：当 user 进入对应分类时触发
    QR_LOGIN_TID    = "__qr_login__"    # 进入 → 生成新 QR 并显示
    QR_RELOGIN_TID  = "__qr_relogin__"  # 进入 → 清掉本地 cookie 立刻重新登

    def getName(self):
        return "哔哩哔哩"

    def init(self, extend):
        """TVBox 启动爬虫时调用：加载本地扫码 cookie"""
        global HEADERS
        saved = _load_cookie_file()
        if saved:
            HEADERS = _apply_cookies_to_headers(HEADERS, saved)
            _log(f"[init] cookie loaded, user_id={saved.get('DedeUserID', '?')}")
        else:
            _log("[init] no cookie, using built-in empty header")
        _log(f"[init] 哔哩哔哩 spider 启动, log_file={_SPIDER_LOG_FILE}")

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    # ---------- 通用：把封面缩略图 URL 升级为原图 ----------
    @staticmethod
    def _upscale_cover(url):
        """
        B 站 pic 字段通常附带 @672w_378h_1c.webp 这种尺寸后缀，
        截到第一个 @ 之前就是原图（一般 1920x1080 或更高）。
        """
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        at = url.find("@")
        if at != -1:
            url = url[:at]
        return url

    # ---------- WBI 签名（可选，仅用于搜索） ----------
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
        # 把登录相关的入口放在最前面，开机即看见
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
        # 特殊：清除 Cookie 重新登（一键到底：清完直接给二维码）
        if str(cid) == self.QR_RELOGIN_TID:
            return self._qr_relogin_category(int(pg) if pg else 1)
        # 特殊：进入「扫码登录」分类
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
        # ★ 扫码登录条目：壳子点进分类条目后会调 detailContent 拉详情，
        # 如果这里不认 QR_LOGIN_TID，详情弹窗就是空白的，用户看不到二维码。
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

            # 该视频对当前账号实际可用的清晰度（登录后才返回完整列表）
            accept_q = set(vinfo.get('accept_quality') or [])
            if accept_q:
                available_q = [(n, q) for n, q in QUALITY_MAP if q in accept_q]
                if not available_q:
                    available_q = list(QUALITY_MAP)
            else:
                available_q = list(QUALITY_MAP)

            # 多清晰度播放源（高清参数加齐）
            #   fnval=4048      → DASH 优先（4K 一般只有 dash 流）
            #   fnver=0         → 协议版本
            #   fourk=1         → 允许 4K
            #   high_quality=1  → 高码率
            play_from = []
            play_url = []
            avid = vinfo.get('aid', 0)

            for qname, qn in available_q:
                urls = []
                for page in pages:
                    cid = page.get('cid', 0)
                    part_name = page.get('part', f'P{len(urls)+1}')
                    play_req_url = (
                        f"{API_BASE}/x/player/playurl"
                        f"?avid={avid}&cid={cid}&qn={qn}"
                        f"&type=json&fnval=4048&fnver=0"
                        f"&fourk=1&high_quality=1"
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
        # ===== 新增：如果传入的是二维码图片 URL，直接返回图片 =====
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

        # 原有的 QR 登录分支（保留兼容，但主要用于 HTML）
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

            # 优先级：data URL（内嵌HTML） > HTTP HTML > file:// HTML > 图片
            # 首选：内嵌 data:text/html;base64 URL（最稳，不依赖任何外部服务）
            if html_path and png_path and _ospider_log.path.isfile(html_path) \
                    and _ospider_log.path.isfile(png_path):
                inline_url = self._qr_build_inline_data_url(html_path, png_path, qr_url)
                if inline_url:
                    _log("[qr] playerContent 返回 data:text/html 内嵌 URL")
                    return {
                        "parse": 0, "playUrl": '', "url": inline_url,
                        "header": text_html_header,
                    }

            # 兜底 1：HTTP 服务 HTML
            base_url = self._qr_start_http_server(save_dir)
            if base_url and html_path and _ospider_log.path.isfile(html_path):
                rel = _ospider_log.path.basename(html_path)
                url = base_url + rel
                _log(f"[qr] playerContent 返回 HTTP HTML {url}")
                return {
                    "parse": 0, "playUrl": '', "url": url,
                    "header": text_html_header,
                }

            # 兜底 2：file:// HTML
            if html_path and _ospider_log.path.isfile(html_path):
                _log(f"[qr] playerContent 返回 file:// HTML {html_path}")
                return {
                    "parse": 0, "playUrl": '', "url": "file://" + html_path,
                    "header": text_html_header,
                }

            # 兜底 3：图片（PNG）
            if png_path and _ospider_log.path.isfile(png_path):
                img_url = ""
                if base_url:
                    # 优先使用 HTTP 服务的图片
                    card_name = "bili_qrcode_card.png"
                    raw_name = "bili_qrcode.png"
                    card_full = _ospider_log.path.join(save_dir, card_name)
                    raw_full = _ospider_log.path.join(save_dir, raw_name)
                    if _ospider_log.path.isfile(card_full):
                        img_url = base_url + card_name
                    elif _ospider_log.path.isfile(raw_full):
                        img_url = base_url + raw_name
                if not img_url:
                    # 使用 data URL 或 file://
                    img_url = state.get("preview_card_url") or state.get("data_url") or "file://" + png_path
                _log(f"[qr] playerContent 返回图片 {img_url[:80]}")
                return {
                    "parse": 0, "playUrl": '', "url": img_url,
                    "header": {**HEADERS, "Content-Type": "image/png"},
                }

            # 终极兜底：B 站 URL
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
                # 优先 dash（4K 一般只有 dash 才有，码率也是最高）
                dash = data.get('data', {}).get('dash', {})
                if dash:
                    video_list = dash.get('video', [])
                    audio_list = dash.get('audio', [])
                    if video_list:
                        play_url = video_list[0].get('baseUrl', '')
                        if play_url:
                            result = {
                                "parse": 0, "playUrl": '',
                                "url": play_url, "header": HEADERS,
                            }
                            if audio_list and audio_list[0].get('baseUrl'):
                                result["audioUrl"] = audio_list[0]['baseUrl']
                            return result
                # 退化到 durl
                durl = data.get('data', {}).get('durl', [])
                if durl:
                    play_url = durl[0].get('url', '')
                    if play_url:
                        return {"parse": 0, "playUrl": '', "url": play_url, "header": HEADERS}
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

    # ---------- 搜索结果作为分类列表（戏曲等） ----------
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
    # 用户在盒子首页第一项看到「📱 扫码登录」分类，点进来后：
    #   1) 生成 QR 并落到 /sdcard/Download/bili_qrcode.png
    #   2) 作为视频海报显示在电视上（手机扫描能扫到的尺寸）
    #   3) 后台守护线程每 2 秒轮询，登录成功即写 cookie 文件 + 更新全局 HEADERS
    #   4) 用户重新点进任意视频时即可看到 1080P / 4K
    # ========================================

    def _qr_save_dir(self):
        """找一个可写目录放二维码 png：盒子内置 → sdcard → 用户家目录"""
        for d in ("/storage/emulated/0/Download",
                  "/sdcard/Download",
                  "/sdcard",
                  _ospider_log.path.expanduser("~")):
            try:
                if _ospider_log.path.isdir(d) and _ospider_log.access(d, _ospider_log.W_OK):
                    return d
            except Exception:
                continue
        return _ospider_log.getcwd()

    def _qr_build_inline_data_url(self, html_path, png_path, qr_url):
        """终极兜底：把 HTML 包装页读出来，把 QR PNG 转成 data URL 内嵌进去，
        整个 base64 编码成 data:text/html URL。
        TVBox 拿到这种 URL 不可能当视频流，必然走 webview → 直接显示 QR。
        不依赖 HTTP 服务 / file:// / sdcard 权限，全平台通用。"""
        try:
            import base64 as _b64
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            # 把 HTML 里指向 file:// 的 img 替换成内联 PNG
            if png_path and _ospider_log.path.isfile(png_path):
                with open(png_path, "rb") as f:
                    png_b64 = _b64.b64encode(f.read()).decode()
                png_data_url = "data:image/png;base64," + png_b64
                # 替换 HTML 里 <img src="file://..."> 为 data URL
                import re
                html = re.sub(
                    r'<img\s+src="[^"]*qr\.png[^"]*"\s+alt="QR"\s*/?>',
                    f'<img src="{png_data_url}" alt="QR"/>',
                    html, flags=re.IGNORECASE
                )
            b64 = _b64.b64encode(html.encode("utf-8")).decode()
            url = "data:text/html;base64," + b64
            _log(f"[qr] 内联 data URL 长度 {len(url)}，必然 webview 打开")
            return url
        except Exception as e:
            _log(f"[qr] 内联 data URL 失败: {e}")
            return ""

    def _qr_start_http_server(self, directory):
        """为 QR 资源（HTML / PNG）起一个临时 HTTP 服务，返回 base URL。
        目的：让 playerContent 返回的 URL 是 http://127.0.0.1:PORT/xxx.html，
        任何 TVBox 壳子看到 http + .html 都 100% 走自带的 webview，
        避免 file:// 被盒子的安全策略拦截导致「点了没反应」。
        实现要点：**不切换进程 cwd**，translate_path 手动映射到目标目录，
        同时内置 /qr_status 状态接口供页面 JS 轮询扫码进度。
        """
        global _qr_http_server, _qr_http_thread, _qr_http_port, _qr_http_dir
        if not HAS_HTTP_SERVER or not HAS_THREADING:
            return ""
        # 已起过且目录不变 → 复用
        if (_qr_http_server is not None and _qr_http_dir == directory
                and _qr_http_port is not None):
            return f"http://127.0.0.1:{_qr_http_port}/"
        try:
            import socket as _sock
            _s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            _s.bind(('127.0.0.1', 0))
            port = _s.getsockname()[1]
            _s.close()

            _serve_dir = _ospider_log.path.abspath(directory)
            _spider_ref = self

            class _QHandler(_http_server_mod.SimpleHTTPRequestHandler):
                # 状态接口：页面 JS 每 2 秒 GET 一次，实时显示扫码进度
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

                # 手动把请求路径映射到 _serve_dir，完全不依赖进程 cwd
                def translate_path(self, path):
                    path = path.split('?', 1)[0].split('#', 1)[0]
                    try:
                        path = urllib.parse.unquote(path)
                    except Exception:
                        pass
                    parts = [p for p in path.split('/') if p and p != '..']
                    target = _serve_dir
                    for p in parts:
                        target = _ospider_log.path.join(target, p)
                    return target

                def log_message(self, fmt, *args):  # noqa
                    pass  # 安静

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
        """渲染 QR → PNG，优先本地 qrcode 库，失败走 api.qrserver.com。
        返回 (rendered:bool, data_url:str)。
        关键参数：box_size=24（电视距离能扫），border=10（标准安静区），
        ERROR_CORRECT_H（容忍 30% 遮挡 / 电视反光）。
        **强制输出正方形**：哪怕 qrcode 库出 bug，给一张矩形图我们也补成正方形。"""
        # 方式 1：本地 qrcode（同时拿到 data URL 兜底）
        try:
            import qrcode  # noqa
            from io import BytesIO
            import base64 as _b64

            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=24,           # 单模块 24px → 整体 1200~1400 px
                border=4,              # spec 最小安静区 (原本 10 缩到 TVBox 缩略图后被压扁)
            )
            qr.add_data(qr_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            # 防御：把任何模式的图转成 RGB，且**强制正方形**（白底居中）
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

            # 1a) 落盘到文件系统
            img.save(png_path, format='PNG')
            # 1b) 内存里同时编码出 data URL（file:// 兼容性差时用它）
            buf = BytesIO()
            img.save(buf, format='PNG')
            data_url = "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()
            return True, data_url
        except Exception as e:
            _log(f"[qr] 本地 qrcode 渲染失败: {e}")

        # 方式 2：在线生成（同样要大尺寸 + 高纠错 + 黑白）
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
                # 在线返回的 PNG 9 成 9 是 1200x1200，但保险起见也校验一下
                try:
                    from PIL import Image as _PILImage  # noqa
                    from io import BytesIO as _Bio
                    _im = _PILImage.open(_Bio(resp.content))
                    if _im.size[0] != _im.size[1]:
                        _log(f"[qr] 在线 PNG 也是非正方形 {_im.size}")
                except Exception:
                    pass
                return True, data_url
            _log(f"[qr] 外网 QR 生成失败 http={resp.status_code}")
        except Exception as e:
            _log(f"[qr] 外网 QR 生成异常: {e}")
        return False, ""

    def _qr_render_preview_card(self, qr_png_path, status_text, qr_url):
        """合成"成品宣传卡"用作 TVBox 的 vod_pic。

        关键修复：**PIL-free 也能跑**！
        盒子环境（OK 影视等）通常不带 Pillow，原来一旦 PIL 缺失就直接
        返回空串 → TVBox 拿到一个无效 vod_pic，缩略图就显示得很小或
        是个占位图。现在 PIL 缺失时，会把原始 QR PNG 直接复制成
        "card" 文件（HTTP 服务能挂出去当真实图片），并把它的 data URL
        当作 vod_pic 兜底，**绝对不会让 vod_pic 落到 B 站登录 URL 字符串
        这种"非图片"的状态**。
        """
        # PIL 路径：有 Pillow 才拼 1920x1080 的大卡片（含状态文字、URL）
        try:
            from PIL import Image, ImageDraw, ImageFont  # noqa
            from io import BytesIO
            import base64 as _b64

            qr = Image.open(qr_png_path).convert("RGB")
            # 防御：补成正方形
            w, h = qr.size
            if w != h:
                side = max(w, h)
                canvas = Image.new("RGB", (side, side), "white")
                canvas.paste(qr, ((side - w) // 2, (side - h) // 2))
                qr = canvas
                w = h = side

            # 合成画布：1920x1080 (16:9)
            CW, CH = 1920, 1080
            card = Image.new("RGB", (CW, CH), (244, 245, 247))
            draw = ImageDraw.Draw(card)

            # 选字体（系统没有就用默认；都不行也不会崩）
            def _font(sz, bold=False):
                paths = []
                try:
                    if _ospider_log.name == "nt":
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
                        if _ospider_log.path.isfile(p):
                            return ImageFont.truetype(p, sz)
                    except Exception:
                        pass
                try:
                    return ImageFont.load_default()
                except Exception:
                    return None

            f_status = _font(40)
            # ① 顶部状态
            try:
                if f_status:
                    draw.text((60, 50), status_text, fill=(120, 120, 120), font=f_status)
                else:
                    draw.text((60, 50), status_text, fill=(120, 120, 120))
            except Exception:
                pass

            # ② 中间白底卡片
            QR_SIDE = 880
            qr_resized = qr.resize((QR_SIDE, QR_SIDE), Image.NEAREST)
            card_x = (CW - QR_SIDE) // 2
            card_y = (CH - QR_SIDE) // 2 + 20
            draw.rectangle([card_x - 8, card_y - 8,
                            card_x + QR_SIDE + 7, card_y + QR_SIDE + 7],
                           fill=(255, 255, 255))
            card.paste(qr_resized, (card_x, card_y))

            # ③ 底部 caption
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

            # 落盘到磁盘（让 HTTP 服务能挂出去当真实图片）
            try:
                card.save(qr_png_path.replace("bili_qrcode.png",
                                              "bili_qrcode_card.png"),
                          format="PNG")
            except Exception as e:
                _log(f"[qr] preview card 落盘失败: {e}")

            # 同时编码成 data URL
            buf = BytesIO()
            card.save(buf, format="PNG")
            return "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()
        except ImportError:
            _log("[qr] PIL/Pillow 未安装，走 PIL-free 路径：直接把原始 QR 复制为 card")
        except Exception as e:
            _log(f"[qr] preview card 合成失败: {e}")

        # ===== PIL-free 兜底：把原始 QR PNG 当作 "card" 用 =====
        try:
            import base64 as _b64
            if not _ospider_log.path.isfile(qr_png_path):
                return ""
            # 1) 复制到 card 文件名，让 HTTP 服务能挂出去
            try:
                with open(qr_png_path, "rb") as _src:
                    _raw = _src.read()
                card_path = qr_png_path.replace("bili_qrcode.png",
                                                 "bili_qrcode_card.png")
                with open(card_path, "wb") as _dst:
                    _dst.write(_raw)
            except Exception as e:
                _log(f"[qr] card 复制落盘失败: {e}")
            # 2) 编码成 data URL
            return "data:image/png;base64," + _b64.b64encode(_raw).decode()
        except Exception as e:
            _log(f"[qr] PIL-free 兜底也失败: {e}")
            return ""

    def _qr_make_html_wrapper(self, png_path, qr_url, data_url="", base_url=""):
        """生成全屏扫码页（点「播放」后壳子会弹出新窗口加载本页）。
        关键点：
        1) QR 图用内嵌 base64 data URL，页面自包含，不依赖 webview 能否读本地文件；
        2) 通过本地 HTTP 服务提供时，JS 每 2 秒轮询 /qr_status，
           扫码进度（等待扫码 → 已扫码 → 登录成功）实时显示在窗口里；
        3) 布局只用 flex + vmin，旧内核 webview 也兼容。"""
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
        """新一次扫码流程：生成 QR + 落盘 PNG + 写 HTML 包装页 + 后台轮询线程。"""
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": HEADERS["User-Agent"],
            "Referer":    "https://www.bilibili.com/",
            "Origin":     "https://www.bilibili.com",
        })

        # 1) 调用 B 站接口申请 QR
        try:
            resp = sess.get(CLI_QR_GEN_URL, timeout=TIMEOUT)
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"无法连接 B 站: {e}")
        if data.get("code") != 0:
            raise RuntimeError(f"生成二维码失败: {data}")
        qr = data["data"]
        qr_url, qr_key = qr["url"], qr["qrcode_key"]
        # ★ 显式打印 QR URL 到日志，扫码没反应时可手动复制到手机浏览器尝试
        _log(f"[qr] QR 生成成功 url={qr_url} key={qr_key}")

        # 2) 渲染 PNG（同时拿到 data URL）
        save_dir = self._qr_save_dir()
        png_path = _ospider_log.path.join(save_dir, "bili_qrcode.png")
        rendered, data_url = self._qr_render_png(qr_url, png_path)
        image_url = "file://" + png_path if rendered else qr_url

        # 2.2) 先起本地 HTTP 服务：弹窗页需要它的 /qr_status 轮询接口，
        # 海报也需要 http:// 的图片地址（OK影视等壳子不加载 data: 大图）
        base_url = self._qr_start_http_server(save_dir)

        # 2.5) 合成"成品宣传卡" → 让 HTTP 服务 / 兜底 vod_pic 都能拿到真图
        #      即便 PIL 缺失，新代码也会把原始 QR 复制成 card 文件，
        #      **保证 http://127.0.0.1:PORT/bili_qrcode_card.png 一定能用**。
        preview_card_url = ""
        if rendered:
            preview_card_url = self._qr_render_preview_card(
                png_path, "⏳ 等待扫码…", qr_url
            )
            card_disk = _ospider_log.path.join(save_dir, "bili_qrcode_card.png")
            _log(
                "[qr] 预览卡合成 {0} size={1} card_disk={2} exists={3}"
                .format(
                    "成功" if preview_card_url else "失败",
                    len(preview_card_url or ""),
                    card_disk,
                    _ospider_log.path.isfile(card_disk),
                )
            )

        # 3) 生成 HTML 全屏扫码页（点"播放"后壳子弹出新窗口加载此页）
        html_path = None
        if rendered:
            html_path = self._qr_make_html_wrapper(png_path, qr_url, data_url,
                                                   base_url=base_url)

        # 4) 状态对象
        state = {
            "sess":       sess,
            "qr_key":     qr_key,
            "qr_url":     qr_url,
            "image_url":  image_url,
            "data_url":   data_url,    # HTML wrapper 兜底
            "png_path":   png_path,
            "html_path":  html_path,   # vod_play_url 主推（自带 webview 的影视壳）
            "preview_card_url": preview_card_url,  # ★ vod_pic（TVBox 主显示）
            "save_dir":   save_dir,    # ★ HTTP 服务根目录
            "rendered":   rendered,
            "started_at": time.time(),
            "status":     "等待扫码…",
            "logged_in":  False,
            "alive":      True,
        }
        self._qr_state = state

        # 5) 后台守护线程：盒子端 Python 大多支持 threading
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
                _log(f"[qr] 后台线程启动失败: {e}；将改为每次进入分类时同步补轮询")

        _log(f"[qr] QR 已生成 png={png_path} rendered={rendered} "
             f"html={html_path} key={qr_key}")

    def _qr_poll_thread(self, sess, qr_key, state):
        """后台守护线程：每 2 秒轮询，不阻塞 TVBox 主线程。
        退出条件：登录成功 / 二维码失效 (86038) / 5 分钟超时。
        同时定期重渲染预览卡，让 TVBox 缩略图实时反映状态变化。"""
        deadline = time.time() + 300   # B站默认 180s，给宽裕点 300s
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
            # 状态变了就重画预览卡（让 TVBox 缩略图实时反映）
            if state["status"] != last_preview_status:
                last_preview_status = state["status"]
                self._refresh_preview_card(state)
            time.sleep(2)
        if state.get("alive", False):
            state["status"] = "登录超时（5 分钟）"
            state["alive"]  = False
            self._refresh_preview_card(state)

    def _refresh_preview_card(self, state):
        """用最新 status 重画预览卡（PIL 可用时），更新 preview_card_url。
        让 TVBox 缩略图能跟着轮询状态实时变化。"""
        if not state.get("rendered") or not state.get("png_path"):
            return
        if not _ospider_log.path.isfile(state["png_path"]):
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
        """在主线程里同步轮询一小段（≤ max_seconds）。
        用在没有 threading 支持的盒子环境；TVBox 进入分类时总会调到，
        时间窗口很短、不卡 UI。"""
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
        """登录成功的统一收尾：写 cookie 文件 + 立即生效 HEADERS。"""
        cookies = sess.cookies.get_dict()
        if not cookies.get("SESSDATA"):
            _log("[qr] 未拿到 SESSDATA，跳过落盘")
            return False
        save_dir = _cli_find_save_dir()
        cookie_path = _ospider_log.path.join(save_dir, "bili_cookie.json")
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
        """TVBox 进入「📱 扫码登录」分类时被调用的入口。"""
        try:
            state = getattr(self, '_qr_state', None)
            need_new = (
                state is None
                or not state.get("alive", False)
                or state.get("logged_in", False)
                or not state.get("image_url")
                or (state.get("png_path")
                    and not _ospider_log.path.isfile(state["png_path"]))
                or (pg and int(pg) > 1 and not state.get("logged_in"))
            )
            if need_new:
                self._qr_start_new_login()
                state = self._qr_state

            # 没线程/线程意外退出 → 这里补 3 秒
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

            # ★ vod_remarks 留极简短标签，避免压住 QR 缩略图
            if state.get("logged_in"):
                remark = "✓ 已登录"
            else:
                remark = "扫码登录"

            # ===== 确保 HTTP 服务起着：让 vod_pic 一定是真图片 URL =====
            _sd = state.get("save_dir") or self._qr_save_dir()
            base_url = self._qr_start_http_server(_sd)

            # ===== 海报优先级（必须是真图片 URL，TVBox 才肯显示）：
            #   1) HTTP 服务的"成品卡" PNG（强烈推荐，海报里就是 QR）
            #   2) HTTP 服务的"原始 QR" PNG（盒子缩略图够大就能扫）
            #   3) 合成预览卡 data URL
            #   4) 原始 QR data URL
            #   5) file:// 原始 QR（仅当 HTTP 起不来）
            #  ★ 注意：B 站登录 URL（qr_url）**绝不能**当 vod_pic，
            #    那种字符串会让 TVBox 显示一个占位方框/小图标。
            thumb = ""
            if base_url:
                card_name = "bili_qrcode_card.png"
                raw_name  = "bili_qrcode.png"
                card_full = _ospider_log.path.join(_sd, card_name)
                raw_full  = _ospider_log.path.join(_sd, raw_name)
                if _ospider_log.path.isfile(card_full):
                    thumb = base_url + card_name
                elif _ospider_log.path.isfile(raw_full):
                    thumb = base_url + raw_name
            if not thumb:
                thumb = preview_card or data_url or image_url or ""
            # 万一还没拿到（不太可能）：把 QR 落盘到当前目录硬保一个 file://
            if not thumb and png_path and _ospider_log.path.isfile(png_path):
                thumb = "file://" + png_path

            # ===== 播放源：优先 HTML（带自动关闭），备选图片 =====
            play_sources = []
            # 首选：HTML 页面（如果存在且可用）
            if rendered and html_path and _ospider_log.path.isfile(html_path):
                # 尝试内联 data URL（最稳）
                inline_url = self._qr_build_inline_data_url(html_path, png_path, qr_url)
                if inline_url:
                    play_sources.append(("扫码登录(HTML,自动关闭)", "默认$" + inline_url))
                elif base_url:
                    rel = _ospider_log.path.basename(html_path)
                    play_sources.append(("扫码登录(HTML,自动关闭)", "默认$" + base_url + rel))
                else:
                    play_sources.append(("扫码登录(HTML,自动关闭)", "默认$" + "file://" + html_path))

            # 备选：图片（如果 HTML 无法打开，用户可手动切换）
            if rendered and png_path and _ospider_log.path.isfile(png_path):
                img_url = ""
                if base_url:
                    card_name = "bili_qrcode_card.png"
                    raw_name = "bili_qrcode.png"
                    card_full = _ospider_log.path.join(_sd, card_name)
                    raw_full = _ospider_log.path.join(_sd, raw_name)
                    if _ospider_log.path.isfile(card_full):
                        img_url = base_url + card_name
                    elif _ospider_log.path.isfile(raw_full):
                        img_url = base_url + raw_name
                if not img_url:
                    img_url = preview_card or data_url or image_url or ""
                if img_url:
                    play_sources.append(("扫码登录(图片)", "默认$" + img_url))

            # 如果都没有，兜底 B 站链接
            if not play_sources and qr_url:
                play_sources.append(("扫码登录(浏览器)", "默认$" + qr_url))

            # 最终兜底
            if not play_sources:
                play_sources.append(("⚠️ 生成失败", "默认$about:blank"))

            # ★★★ 关键诊断日志 ★★★
            _log(
                "[qr-cat] 返回 vod_pic=\n     {0}\n"
                "[qr-cat] 返回播放源数={1}\n"
                "[qr-cat] 状态: rendered={2} http_up={3} status={4}"
                .format(
                    (thumb[:200] + "...") if len(thumb) > 200 else thumb,
                    len(play_sources),
                    rendered, bool(base_url), status,
                )
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
        """清理所有候选路径下的 cookie 文件 + 之前生成的 QR png。
        返回 (cleared:[paths], failed:[(path, err_str)])。"""
        cleared, failed = [], []
        for path in COOKIE_FILE_CANDIDATES:
            try:
                if _ospider_log.path.isfile(path):
                    _ospider_log.remove(path)
                    cleared.append(path)
            except Exception as e:
                failed.append((path, str(e)))
                _log(f"[qr-relogin] 删除 {path} 失败: {e}")
        # 顺手把残留的二维码 png 也清掉（盒子内/sdcard 各放一份都试）
        for qr_dir in ("/storage/emulated/0/Download",
                       "/sdcard/Download", "/sdcard"):
            qr_path = _ospider_log.path.join(qr_dir, "bili_qrcode.png")
            try:
                if _ospider_log.path.isfile(qr_path):
                    _ospider_log.remove(qr_path)
                    cleared.append(qr_path)
            except Exception as e:
                _log(f"[qr-relogin] 删除 {qr_path} 失败: {e}")
        return cleared, failed

    def _qr_relogin_category(self, pg):
        """清掉本地 cookie + 立刻进入扫码登录分类（一键到底）。"""
        # 1) 清 cookie
        cleared, failed = self._qr_clear_local_cookies()

        # 2) 清 HEADERS 里的 Cookie；下次搜索/播放就走未登录身份
        try:
            global HEADERS
            HEADERS = dict(HEADERS)
            HEADERS['Cookie'] = ''
        except Exception as e:
            _log(f"[qr-relogin] reset HEADERS Cookie 失败: {e}")

        # 3) 强制下次 _qr_login_category 生成全新 QR（不复用旧的）
        try:
            self._qr_state = None
        except Exception:
            pass

        _log(f"[qr-relogin] cleared={len(cleared)} failed={len(failed)} -> "
             f"pipes into QR login")

        # 4) 直接走扫码登录流程，给用户"点一下就扫"的体验
        result = self._qr_login_category(pg)

        # 6) 在结果上盖一层 "Cookie 已清掉" 的提示
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
# ============== 命令行模式：扫码登录 =====================
# 用法（仅在 PC 上执行，TVBox 通过 import 加载本文件不会触发）：
#     pip install qrcode[pil]      # 可选：终端打印二维码；没装会自动用浏览器打开
#     python 哔哩哔哩.py
# ========================================

CLI_QR_GEN_URL  = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
CLI_QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"


def _cli_find_save_dir():
    """找一个可写目录，用于放 bili_cookie.json"""
    candidates = [
        _ospider_log.path.join(_ospider_log.path.expanduser("~"), "Downloads"),
        _ospider_log.path.expanduser("~"),
        "/storage/emulated/0/Download",
        "/sdcard/Download",
        _ospider_log.getcwd(),
    ]
    for d in candidates:
        try:
            _ospider_log.makedirs(d, exist_ok=True)
            test = _ospider_log.path.join(d, ".bili_write_test")
            with open(test, "w") as f:
                f.write("ok")
            _ospider_log.remove(test)
            return d
        except Exception:
            continue
    return _ospider_log.getcwd()


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
    """优先在终端打印二维码；没有库就让浏览器打开"""
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
    """CLI 入口：执行扫码登录并落盘 Cookie"""
    print("=" * 60)
    print(" 哔哩哔哩扫码登录工具（CLI 模式）")
    print(" 直接 `python 哔哩哔哩.py` 即可启动此模式；")
    print(" TVBox 端通过 import 加载，__main__ 不会触发。")
    print("=" * 60)

    save_dir = _cli_find_save_dir()
    cookie_path = _ospider_log.path.join(save_dir, "bili_cookie.json")
    print(f"Cookie 将保存到:\n  {cookie_path}\n")

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": HEADERS["User-Agent"],
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    })

    # Step 1: 生成
    print("[1/4] 生成二维码...")
    try:
        qr = _cli_gen_qr(sess)
    except Exception as e:
        print(f"  ✗ {e}")
        sys.exit(1)
    qr_url = qr["url"]
    qr_key = qr["qrcode_key"]
    print(f"  qrcode_key = {qr_key}")

    # Step 2: 显示
    print("\n[2/4] 请用哔哩哔哩 APP 扫一扫 ↓")
    _cli_show_qr(qr_url)

    # Step 3: 轮询
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
        # 0=成功  86038=已失效  86090=已扫码待确认  86101=未扫码
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

    # Step 4: 保存
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
    print(" 下一步：把这个文件复制到电视盒子的任一下列路径：")
    for p in ("/storage/emulated/0/Download/bili_cookie.json",
              "/sdcard/Download/bili_cookie.json"):
        print(f"   {p}")
    print(" 然后重启电视端爬虫，init 时会打印「[cookie] loaded ...」即生效。")
    print("=" * 60)


if __name__ == "__main__":
    try:
        _cli_login_main()
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(1)
