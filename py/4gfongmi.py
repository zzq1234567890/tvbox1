# -*- coding: utf-8 -*-
# 4GTV - 蜂蜜影视 5.6 优化版（带调试日志）

import sys
sys.path.append('..')

import base64
import datetime
import hashlib
import html
import json
import re
import ssl
import time
import urllib.request
from base.spider import Spider

# ---------- 调试开关 ----------
DEBUG = True   # True 输出调试信息，False 静默

def debug_log(msg):
    if DEBUG:
        print("[4GTV-DEBUG] " + str(msg))


class Spider(Spider):
    def __init__(self):
        self.api1 = 'https://api2.4gtv.tv/TV/GetChannelUrl'
        self.api2 = 'https://api2.4gtv.tv/App/GetChannelUrl2'
        self.list_api = 'https://api2.4gtv.tv/Channel/GetAllChannel2/TV'
        self.web = 'https://www.4gtv.tv'
        self.plain_key = '7F3DD6981A72707B12A8C0CC80A3C96B75B9057AD55F1AE1'
        self.ua = 'Dalvik/2.1.0 (Linux; U; Android 13; Android TV Build/TP1A.220624.014)'
        self.channels = []
        self.classes = [
            {'type_id': '綜合', 'type_name': '綜合'},
            {'type_id': '音樂綜藝', 'type_name': '音樂綜藝'},
            {'type_id': '兒童與青少年', 'type_name': '兒童與青少年'},
            {'type_id': '新聞財經', 'type_name': '新聞財經'},
            {'type_id': '運動健康生活', 'type_name': '運動健康生活'},
            {'type_id': '戲劇', 'type_name': '戲劇'},
            {'type_id': '電影', 'type_name': '電影'},
        ]
        self.cache_time = 0
        self.play_cache = {}
        debug_log("Spider 初始化完成")

    def init(self, extend=''):
        return None

    def getName(self):
        return '4GTV'

    def destroy(self):
        pass

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv)(\?|$)', str(url or ''), re.I))

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return None

    def _auth(self):
        day = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')
        raw = (day + self.plain_key).encode('utf-8')
        token = base64.b64encode(hashlib.sha512(raw).digest()).decode('ascii')
        debug_log(f"生成授权令牌: {token[:20]}...")
        return token

    def _headers(self, json_body=False):
        h = {
            'Host': 'api2.4gtv.tv',
            'User-Agent': self.ua,
            'fsDEVICE': 'TV',
            'fsVERSION': '1.5.4',
            '4GTV_AUTH': self._auth(),
        }
        if json_body:
            h['Content-Type'] = 'application/json'
        debug_log(f"请求头: {h}")
        return h

    def _request_json(self, url, payload=None):
        debug_log(f"JSON请求: {url}, payload: {payload}")
        headers = self._headers(payload is not None)
        try:
            if payload is None:
                resp = self.fetch(url, headers=headers, timeout=12)
            elif hasattr(self, 'post'):
                resp = self.post(url, json=payload, headers=headers, timeout=12)
            else:
                resp = self.fetch(url, data=json.dumps(payload), headers=headers, timeout=12)
            text = getattr(resp, 'text', '') or getattr(resp, 'content', b'')
            if isinstance(text, bytes):
                text = text.decode('utf-8', errors='ignore')
            if text:
                data = json.loads(text)
                debug_log(f"JSON响应成功: {str(data)[:200]}...")
                return data
        except Exception as e:
            debug_log(f"壳内请求失败: {e}")

        # 兜底 urllib
        try:
            data = None
            if payload is not None:
                data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers=headers,
                                         method='POST' if data is not None else 'GET')
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                raw = resp.read().decode('utf-8', errors='ignore')
            result = json.loads(raw) if raw else {}
            debug_log(f"urllib 请求成功: {str(result)[:200]}...")
            return result
        except Exception as e:
            debug_log(f"urllib 请求失败: {e}")
            return {}

    def _request_text(self, url, referer=None):
        debug_log(f"网页请求: {url}, referer: {referer}")
        headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/150.0.0.0 Safari/537.36'),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        if referer:
            headers['Referer'] = referer
        else:
            headers['Referer'] = self.web + '/channel'
        try:
            resp = self.fetch(url, headers=headers, timeout=12)
            text = getattr(resp, 'text', '') or getattr(resp, 'content', b'')
            if isinstance(text, bytes):
                text = text.decode('utf-8', errors='ignore')
            if text:
                debug_log(f"网页响应长度: {len(text)} 字符")
                return text
        except Exception as e:
            debug_log(f"壳内网页请求失败: {e}")

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ssl._create_unverified_context(), timeout=12) as resp:
                text = resp.read().decode('utf-8', errors='ignore')
                debug_log(f"urllib 网页响应长度: {len(text)}")
                return text
        except Exception as e:
            debug_log(f"urllib 网页请求失败: {e}")
            return ''

    def _group_name(self, raw):
        parts = re.split(r'[^\u4e00-\u9fa5a-zA-Z0-9]+', str(raw or ''))
        name = next((x.strip() for x in parts if x.strip()), '未分类')
        if name in ('現場直擊', '國會頻道'):
            return '新聞財經'
        return name

    def _priority(self, asset):
        asset = str(asset or '')
        if asset.lower().startswith('litv-'):
            return 0
        if asset.lower().startswith('4gtv-4gtv'):
            return 1
        return 2

    def _load_channels(self, force=False):
        debug_log(f"加载频道列表, force={force}, 缓存时间={self.cache_time}")
        if self.channels and not force and time.time() - self.cache_time < 6 * 3600:
            debug_log("使用缓存的频道列表")
            return True
        j = self._request_json(self.list_api)
        rows = j.get('Data') if isinstance(j, dict) else None
        if not isinstance(rows, list):
            debug_log("频道列表数据无效")
            return bool(self.channels)

        groups = {}
        for ch in rows:
            name = str(ch.get('fsNAME') or '未知频道')
            cid = ch.get('fnID')
            asset = ch.get('fs4GTV_ID')
            if cid is not None and asset and '東森購物' not in name:
                groups.setdefault(name, []).append(ch)

        kept = []
        for name, items in groups.items():
            if name in ('TVBS', 'TVBS新聞'):
                media = next((x for x in items if 'media' in str(x.get('fs4GTV_ID', '')).lower()), None)
                if media:
                    kept.append(media)
                    continue
            kept.append(min(items, key=lambda x: self._priority(x.get('fs4GTV_ID'))))

        category_order = []
        clean = []
        for ch in kept:
            group = self._group_name(ch.get('fsTYPE_NAME'))
            if group not in category_order:
                category_order.append(group)
            clean.append({
                'id': str(ch.get('fnID')),
                'asset': str(ch.get('fs4GTV_ID')),
                'name': str(ch.get('fsNAME') or '未知频道'),
                'group': group,
                'pic': str(ch.get('fsHEAD_FRAME') or ch.get('fsLOGO_MOBILE') or
                           ch.get('fsLOGO_PC') or ''),
                'set': str((ch.get('lstSETs') or ['1'])[0]),
                'free': bool(ch.get('fcFREE')),
                'overseas': bool(ch.get('fcOVERSEAS')),
            })
        self.channels = clean
        if category_order:
            self.classes = [{'type_id': x, 'type_name': x} for x in category_order]
        self.cache_time = time.time()
        debug_log(f"加载了 {len(self.channels)} 个频道，分类: {category_order}")
        return True

    def _vod(self, ch):
        play_id = ch['id'] + '|' + ch['asset'] + '|' + ch.get('set', '1')
        if not ch.get('free', True):
            remarks = '付费频道'
        elif ch.get('overseas'):
            remarks = '海外可播'
        else:
            remarks = '限台湾'
        return {
            'vod_id': play_id,
            'vod_name': ch['name'],
            'vod_pic': ch.get('pic', ''),
            'vod_remarks': remarks,
        }

    def homeContent(self, filter):
        self._load_channels()
        return {'class': self.classes}

    def homeVideoContent(self):
        self._load_channels()
        return {'list': [self._vod(x) for x in self.channels[:30]]}

    def categoryContent(self, tid, pg, filter, extend):
        self._load_channels()
        page = max(1, int(pg or 1))
        size = 60
        rows = [x for x in self.channels if x['group'] == str(tid)]
        start = (page - 1) * size
        videos = [self._vod(x) for x in rows[start:start + size]]
        pagecount = max(1, (len(rows) + size - 1) // size)
        return {
            'list': videos,
            'page': page,
            'pagecount': pagecount,
            'limit': size,
            'total': len(rows),
        }

    def searchContent(self, key, quick, pg='1'):
        self._load_channels()
        wd = str(key or '').strip().lower()
        rows = [x for x in self.channels if wd in x['name'].lower()] if wd else []
        return {'list': [self._vod(x) for x in rows], 'page': 1, 'pagecount': 1,
                'limit': len(rows), 'total': len(rows)}

    # ---------- 播放地址获取核心（优先网页） ----------
    def _play_urls(self, api, cid, asset, device='tv'):
        debug_log(f"调用API: {api}, cid={cid}, asset={asset}, device={device}")
        payload = {
            'fnCHANNEL_ID': int(cid),
            'fsASSET_ID': asset,
            'fsDEVICE_TYPE': device,
            'clsAPP_IDENTITY_VALIDATE_ARUS': {'fsVALUE': ''},
        }
        j = self._request_json(api, payload)
        data = j.get('Data') if isinstance(j, dict) else None
        urls = data.get('flstURLs') if isinstance(data, dict) else None
        if urls:
            debug_log(f"API返回URLs: {urls}")
        else:
            debug_log("API未返回有效URLs")
        return urls if isinstance(urls, list) else []

    def _select_url(self, urls, asset):
        if not urls:
            debug_log("URL列表为空")
            return ''
        debug_log(f"从 {len(urls)} 个URL中选择")
        # 优先选择 1080p 或 high，其次 mozai 域名
        preferred = []
        for u in urls:
            if isinstance(u, str) and u.startswith('http'):
                if '1080' in u or 'high' in u.lower():
                    preferred.append(u)
                elif '-mozai.4gtv.tv' in u:
                    preferred.append(u)
        if preferred:
            url = preferred[0]
            debug_log(f"首选URL: {url}")
        else:
            url = urls[0] if isinstance(urls[0], str) else ''
            debug_log(f"fallback URL: {url}")
        # 某些频道强制高码率
        if 'live' in asset and 'index.m3u8' in url:
            url = url.replace('index.m3u8', '1080.m3u8')
            debug_log(f"强制替换为1080: {url}")
        return url

    def _decode_js_string(self, value):
        value = html.unescape(str(value or ''))
        try:
            decoded = json.loads('"' + value.replace('"', '\\"') + '"')
            debug_log(f"JS字符串解码成功: {decoded}")
            return decoded
        except Exception as e:
            debug_log(f"JS字符串解码失败，使用替换: {e}")
            return value.replace('\\/', '/').replace('\\u0026', '&')

    def _web_play_url(self, cid, asset, set_id='1'):
        """从官网页面抓取播放地址"""
        page_url = '%s/channel/%s?set=%s&ch=%s' % (self.web, asset, set_id or '1', cid)
        debug_log(f"抓取网页: {page_url}")
        text = self._request_text(page_url, referer='https://www.4gtv.tv/')
        if not text:
            debug_log("网页内容为空")
            return ''

        # 检查是否成功
        success = re.search(r'resultsSuccess\s*=\s*true', text, re.I)
        if not success:
            err = re.search(r'resultsErrMessage\s*=\s*[\'\"]([^\'\"]+)', text, re.I)
            if err:
                debug_log(f"网页返回错误: {err.group(1)}")
            else:
                debug_log("网页未成功 (resultsSuccess != true)")
            return ''

        # 多种方式提取 flstURLs
        patterns = [
            r'flstURLs\s*=\s*[\'\"](.*?)[\'\"]\s*;',
            r'[\'\"]flstURLs[\'\"]\s*:\s*[\'\"](.*?)[\'\"]',
            r'flstURLs\s*=\s*([^;]+);',
        ]
        raw = ''
        for pattern in patterns:
            m = re.search(pattern, text, re.I | re.S)
            if m:
                raw = self._decode_js_string(m.group(1).strip())
                debug_log(f"通过正则 {pattern} 提取到: {raw}")
                break
        if not raw:
            # 尝试从 video 标签直接提取
            vid_src = re.search(r'<video[^>]+src=[\'\"]([^\'\"]+\.m3u8[^\'\"]*)[\'\"]', text, re.I)
            if vid_src:
                raw = vid_src.group(1)
                debug_log(f"从video标签提取到: {raw}")
        if not raw:
            debug_log("未能提取到播放地址")
            return ''

        # 解析多个 url
        urls = [x.strip() for x in re.split(r'[\s,]+', raw) if x.strip().startswith('http')]
        debug_log(f"解析出URLs: {urls}")
        return self._select_url(urls, asset)

    def _get_play_url(self, cid, asset, set_id='1'):
        """获取播放地址，带缓存，优先网页抓取"""
        cache_key = cid + '|' + asset + '|' + set_id
        debug_log(f"尝试获取播放地址: {cache_key}")
        cache = self.play_cache.get(cache_key)
        if cache and time.time() < cache[1]:
            debug_log(f"缓存命中: {cache[0]}")
            return cache[0]

        target = ''
        # 1. 优先使用网页抓取
        debug_log("尝试网页抓取...")
        target = self._web_play_url(cid, asset, set_id)
        if target:
            self.play_cache[cache_key] = (target, time.time() + 1800)
            debug_log(f"网页抓取成功: {target}")
            return target

        # 2. 尝试 API（app 接口）
        for device in ('android', 'tv', 'phone'):
            debug_log(f"尝试API设备: {device}")
            urls = self._play_urls(self.api2, cid, asset, device=device)
            target = self._select_url(urls, asset)
            if target:
                debug_log(f"API({device})成功: {target}")
                break
        if target:
            self.play_cache[cache_key] = (target, time.time() + 1800)
            return target

        # 3. 最后尝试 TV 接口
        debug_log("尝试TV接口...")
        urls = self._play_urls(self.api1, cid, asset, device='tv')
        target = self._select_url(urls, asset)
        if target:
            self.play_cache[cache_key] = (target, time.time() + 1800)
            debug_log(f"TV接口成功: {target}")
            return target

        debug_log("所有方式均未能获取播放地址")
        return ''

    # ---------- 详情与播放 ----------
    def detailContent(self, ids):
        play_id = str(ids[0] if isinstance(ids, list) else ids)
        debug_log(f"detailContent 请求: {play_id}")
        self._load_channels()
        parts = play_id.split('|')
        ch = None
        if len(parts) >= 2:
            ch = next((x for x in self.channels if x['id'] == parts[0] and x['asset'] == parts[1]), None)
        name = ch['name'] if ch else '4GTV直播'
        pic = ch.get('pic', '') if ch else ''

        # 尝试获取直接播放地址
        if ch and len(parts) >= 2:
            cid = parts[0]
            asset = parts[1]
            set_id = parts[2] if len(parts) > 2 else '1'
            url = self._get_play_url(cid, asset, set_id)
            if url:
                debug_log(f"detailContent 返回直接播放地址: {url}")
                vod = {
                    'vod_id': play_id,
                    'vod_name': name,
                    'vod_pic': pic,
                    'vod_remarks': '直播',
                    'vod_content': '4GTV直播频道',
                    'vod_play_from': '4GTV',
                    'vod_play_url': url,   # 直接返回地址
                }
                return {'list': [vod]}

        # 若获取失败，回退为标识形式
        debug_log("detailContent 回退为标识形式")
        vod = {
            'vod_id': play_id,
            'vod_name': name,
            'vod_pic': pic,
            'vod_remarks': '直播',
            'vod_content': '4GTV直播频道',
            'vod_play_from': '4GTV',
            'vod_play_url': '直播$' + play_id,
        }
        return {'list': [vod]}

    def playerContent(self, flag, id, vipFlags):
        play_id = str(id or '')
        debug_log(f"playerContent 请求: {play_id}")
        if '|' not in play_id:
            debug_log("play_id 格式不正确，返回空")
            return {'parse': 0, 'jx': 0, 'url': ''}
        parts = play_id.split('|')
        cid = parts[0]
        asset = parts[1] if len(parts) > 1 else ''
        set_id = parts[2] if len(parts) > 2 else '1'
        target = self._get_play_url(cid, asset, set_id)
        debug_log(f"playerContent 返回: {target}")
        return {
            'parse': 0,
            'jx': 0,
            'url': target or '',
            'header': {
                'User-Agent': self.ua,
                'Referer': 'https://www.4gtv.tv/'
            }
        }
