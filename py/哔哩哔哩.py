from base.spider import Spider
import requests
import re
import json
import time
import hashlib
import urllib.parse
from urllib.parse import urlencode

# ================= 配置 =================
API_BASE = "https://api.bilibili.com"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
    # 如果仍无法访问，请尝试添加登录后的 Cookie（从浏览器复制）
    # 'Cookie': '你的Cookie值'
}
TIMEOUT = 10
MAX_RETRIES = 3

# 分类映射（与红果短剧风格一致：用 & 拼接）
REGION_MAP = {
    "6": "戏曲","1": "动画", "3": "音乐", "4": "游戏", "5": "娱乐",
    "11": "电视剧", "13": "番剧", "23": "电影", "36": "科技",
    "119": "鬼畜", "129": "舞蹈", "155": "生活", "160": "时尚",
    "181": "影视", "188": "纪录片", "217": "资讯", "234": "美食", "235": "国创"
}
CLASS_NAMES = "&".join(REGION_MAP.values())

# 部分分类不走分区动态，而是用搜索结果填充
# 对应页面：https://search.bilibili.com/all?keyword=...&search_source=3
CATEGORY_SEARCH_MAP = {
    "6": "戲曲",  # rid=6 (戏曲) → 繁体"戲曲"搜索，避免与简体"戏曲"混淆
}

# ========================================
# ============== 调试日志 =====================
# TVBox 内嵌 Python 的 print 默认进 logcat，UI 里看不到。
# 同时把所有调试点写到 _SPIDER_LOG_FILE，在电视端用文件管理器打开即可。
# 路径寻找顺序：/storage/emulated/0/Download > /sdcard/Download > /sdcard
# 找不到可写目录时降级到 ~/Downloads 或 /tmp，再不行就只用 stdout。
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

class Spider(Spider):
    def getName(self):
        return "哔哩哔哩"

    def init(self, extend):
        _log(f"[init] 哔哩哔哩 spider 启动, log_file={_SPIDER_LOG_FILE}")

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

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
        return {"class": classes}

    def homeVideoContent(self):
        videos = []
        try:
            # 用热门排行补首页（rid=1 动画，通用）
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
                            "vod_pic": item.get('pic', ''),
                            "vod_remarks": self._format_duration(item.get('duration', 0)),
                        })
        except:
            pass
        return {'list': videos}

    # ---------- 分类视频列表（使用稳定接口，无需签名） ----------
    def categoryContent(self, cid, pg, filter, ext):
        page = int(pg) if pg else 1

        # 戏曲（rid=6）等指定分类：用搜索结果代替分区动态/排行
        # 走 https://search.bilibili.com/all?keyword=...
        search_keyword = CATEGORY_SEARCH_MAP.get(str(cid))
        if search_keyword:
            return self._search_as_category(search_keyword, page)

        videos = []
        try:
            # ① 先试分区动态接口
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
                                "vod_pic": item.get('pic', ''),
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

            # ② Fallback：分区排行榜（几乎所有 rid 都支持）
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
                            "vod_pic": item.get('pic', ''),
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
            pic = vinfo.get('pic', '')
            desc = vinfo.get('desc', '')
            author = vinfo.get('owner', {}).get('name', '')
            tid = str(vinfo.get('tid', ''))
            type_name = REGION_MAP.get(tid, '')

            pages = vinfo.get('pages', [])
            if not pages:
                pages = [{'cid': vinfo.get('cid', 0), 'part': '完整视频'}]

            # 多清晰度播放源（与红果短剧一致）
            quality_map = {"超清": 80, "高清": 64, "标清": 32, "流畅": 16}
            play_from = []
            play_url = []
            avid = vinfo.get('aid', 0)

            for qname, qn in quality_map.items():
                urls = []
                for page in pages:
                    cid = page.get('cid', 0)
                    part_name = page.get('part', f'P{len(urls)+1}')
                    play_req_url = f"{API_BASE}/x/player/playurl?avid={avid}&cid={cid}&qn={qn}&type=json"
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
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(id, headers=HEADERS, timeout=TIMEOUT)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if data.get('code') != 0:
                    continue
                dash = data.get('data', {}).get('dash', {})
                if dash:
                    video_list = dash.get('video', [])
                    if video_list:
                        play_url = video_list[0].get('baseUrl', '')
                        if play_url:
                            return {"parse": 0, "playUrl": '', "url": play_url, "header": HEADERS}
                durl = data.get('data', {}).get('durl', [])
                if durl:
                    play_url = durl[0].get('url', '')
                    if play_url:
                        return {"parse": 0, "playUrl": '', "url": play_url, "header": HEADERS}
            except Exception as e:
                _log(f"playerContent attempt {attempt+1} error: {e}")
                time.sleep(1)
        return {"parse": 0, "playUrl": '', "url": 'about:blank', "header": HEADERS}

    # ---------- 搜索（带WBI签名，失败则降级） ----------
    def searchContent(self, key, quick, pg=1):
        try:
            page = int(pg) if pg else 1
            params = {'keyword': key, 'page': page, 'search_type': 'video'}
            url = f"{API_BASE}/x/web-interface/wbi/search/type"
            resp = self._wbi_request(url, params)
            if not resp or resp.status_code != 200:
                # 降级：尝试无签名请求
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
                    "vod_pic": item.get('pic', ''),
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
        """
        接受 秒（int/float）或 B 站已经格式化好的字符串（"mm:ss" / "h:mm:ss"）。
        B 站 WBI 搜索结果里 duration 字段有时是 int，有时是字符串，统统容错。
        """
        if not seconds:
            return "00:00"
        if isinstance(seconds, str):
            s = seconds.strip()
            # 已经是 mm:ss 或 h:mm:ss 形式直接透传
            if re.match(r'^\d{1,3}:\d{2}(:\d{2})?$', s):
                return s
            # 否则把里面所有数字挤出来当秒数处理
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
        """
        多级 fallback（按可靠性从高到低逐级尝试）：
        Tier 1: /x/web-interface/wbi/search/type     (新版，需要 WBI 签名 + 风控)
        Tier 2: /x/web-interface/search/all/v2        (旧版，不强制 WBI)
        Tier 3: 抓 https://search.bilibili.com/all   (你提供的 URL 的真实 HTML 页面)
        """
        # Tier 1
        res = self._search_tier_wbi(keyword, page)
        if res['list']:
            return res

        # Tier 2
        res = self._search_tier_legacy(keyword, page)
        if res['list']:
            return res

        # Tier 3
        res = self._search_tier_html(keyword, page)
        if res['list']:
            return res

        _log(f"[search-fail] keyword={keyword!r} page={page}, all tiers empty")
        return {'list': [], 'page': page, 'pagecount': 0, 'limit': 20, 'total': 0}

    def _search_tier_wbi(self, keyword, page):
        """Tier 1: 新版 WBI 接口 /x/web-interface/wbi/search/type"""
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
        """Tier 2: 旧版搜索接口 /x/web-interface/search/all/v2（不需 WBI 签名）"""
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
        """Tier 3: 抓 https://search.bilibili.com/all 的 HTML，从 JSON 容器里抽视频。
        支持的容器（按优先级）：
            window.__INITIAL_STATE__
            window.__INITIAL_DATA__
            window.__INITIAL_SSR_STATE__
            __NEXT_DATA__
        容错：
            - 容器的 JSON 内部可能含被 \\/ 转义的 </script>，所以用 indexOf 定位而非正则。
            - JSON 字面量里可能有 undefined / NaN，统一替换为 null。
            - 整页 HTML 落到 spider_bilibili_xiqu.log.html 便于人工查看。
        """
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

            # 把整页 HTML 写到日志旁文件供人工查看
            if _SPIDER_LOG_FILE:
                try:
                    dump_path = _SPIDER_LOG_FILE + ".html"
                    with open(dump_path, "w", encoding="utf-8") as f:
                        f.write(html)
                    _log(f"[tier3] html dumped -> {dump_path}")
                except Exception as e:
                    _log(f"[tier3] html dump failed: {e}")

            # 风控 challenge 短页面
            if '风控' in html and len(html) < 5_000:
                _log("[tier3] returned 风控 challenge page")
                return {'list': []}

            # 尝试 4 个常见 JSON 容器；用 indexOf 而非正则，避免 JSON 内嵌入的
            # </script>（被转义为 <\/script>）影响匹配。
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
                # 跳过空白和 '=', ']; 等过渡
                while start < len(html) and html[start] in ' \t\n\r=;:,':
                    start += 1
                end = html.find('</script>', start)
                if end == -1:
                    continue
                candidate = html[start:end]
                # 去掉尾部可能的 ';' 和空格
                candidate = candidate.rstrip().rstrip(';').strip()
                if candidate and (candidate.startswith('{') or candidate.startswith('[')):
                    js_text = candidate
                    used_name = nm
                    break

            if not js_text:
                _log("[tier3] 4 个常见 JSON 容器都没找到：INITIAL_STATE / INITIAL_DATA / INITIAL_SSR_STATE / __NEXT_DATA__")
                for kw in ("BV1", "result", "video", "戏曲", "戏曲折子", "戏曲视频"):
                    if kw in html:
                        _log(f"[tier3] hint: HTML 里出现 '{kw}'")
                return {'list': []}

            _log(f"[tier3] 用容器 {used_name}, js_text len={len(js_text)}")
            state = self._safe_load_json_like(js_text)
            if not state:
                _log("[tier3] JSON 解析失败（已尝试替换 undefined/NaN）")
                # 输出首尾各 200 字符方便人眼对照
                try:
                    _log(f"[tier3] 前 200 字符: {js_text[:200]!r}")
                    _log(f"[tier3] 末 200 字符: {js_text[-200:]!r}")
                except Exception:
                    pass
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
        """把一个搜索结果 dict 转成 vod 格式（无效则返回 None）"""
        if not isinstance(item, dict):
            return None
        bvid = item.get('bvid', '')
        if not (isinstance(bvid, str) and bvid.startswith('BV') and len(bvid) >= 10):
            return None
        title = re.sub(r'<em[^>]*>|</em>', '', str(item.get('title', '无标题')))
        return {
            "vod_id": bvid,
            "vod_name": title,
            "vod_pic": item.get('pic', '') or '',
            "vod_remarks": self._format_duration(item.get('duration', 0)),
            "vod_content": (item.get('description') or
                            item.get('desc') or '')[:50]
        }

    def _build_search_response(self, payload, page):
        """把新版 WBI 返回 data 包成统一格式"""
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
        """尝试把 JS 风格 JSON 解析出来；处理 undefined/NaN 字面量"""
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
        """深度遍历 __INITIAL_STATE__，挑出含合法 bvid 的对象"""
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
