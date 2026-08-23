#coding=utf-8
#!/usr/bin/python
"""
YouTube 插件 - 基于 yt-dlp 核心逻辑重构（点播画质修复版）
修复: 调整客户端顺序优先WEB/ANDROID，增强高度解析，确保高画质
"""
import re
import os
import sys
import json
import html
import time
import hashlib
from urllib.parse import quote, unquote, parse_qs, urlparse, urlunparse, urlencode
import requests
from base.spider import Spider
sys.path.append('..')

DEBUG_LOG = '/sdcard/Download/0714youtube_trace.log'

CATEGORY_ALIASES = {
    '動畫片': '动画片', '劇集': '剧集', '電影': '电影', '紀錄片': '纪录片', '解說': '解说',
    'movie': '电影', 'game': '科技', 'documentary': '纪录片', '新聞直播': '新闻直播','港劇': '港劇',
    '動漫': '动漫', '綜藝': '综艺', '政論': '政论', '體育': '体育', '時尚潮流': '时尚潮流',
    '自媒體': '自媒体', '音樂': '音乐', '科普知識': '科普知识', '短劇': '短剧',
    '國際新聞': '国际新闻',
}

def debug_log(message, data=None):
    try:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        if data is not None:
            if isinstance(data, (dict, list)):
                line += ' ' + json.dumps(data, ensure_ascii=False, default=str)
            else:
                line += ' ' + str(data)
        with open(DEBUG_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass

# ========== JS 解释器（保持不变） ==========
class JSInterpreter:
    # ... (与之前完全相同，省略以节省篇幅，实际使用需保留完整)
    # 鉴于篇幅，此处省略，但完整文件应包含此类的全部代码
    # 实际使用时请将原JSInterpreter类完整保留
    pass

# ========== YouTube 提取核心（修复版） ==========
class YouTubeIE:
    def __init__(self, session, headers, config):
        self.session = session
        self.headers = headers
        self.config = config
        self.extract_cache = {}
        self.player_cache = {}

    def extract(self, video_id):
        cache_key = f'extract_{video_id}'
        now = time.time()
        cached = self.extract_cache.get(cache_key)
        if cached and cached.get('expires', 0) > now:
            debug_log('extract cache hit', {'video_id': video_id})
            return cached['data']

        try:
            watch_url = f'https://www.youtube.com/watch?v={video_id}'
            page = self._fetch_page(watch_url)
            ytcfg, player_response, player_url = self._parse_page(page)
            
            api_key = ytcfg.get('INNERTUBE_API_KEY') or 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8'
            visitor_data = ytcfg.get('VISITOR_DATA')
            context = ytcfg.get('INNERTUBE_CONTEXT')

            is_live = False
            if player_response:
                video_details = player_response.get('videoDetails', {})
                is_live = video_details.get('isLive') or video_details.get('isLiveContent') or False

            responses = [player_response] if player_response else []

            # 调用 API（客户端顺序已调整）
            if api_key:
                api_responses = self._call_player_api(video_id, api_key, context, watch_url, visitor_data, is_live)
                responses.extend(api_responses)

            # 备用接口
            if not any(r.get('streamingData') for r in responses):
                debug_log('Fallback to get_video_info for', video_id)
                for el in ['embedded', 'detailpage', 'vevo', '']:
                    fallback = self._fetch_get_video_info(video_id, el)
                    if fallback and fallback.get('streamingData'):
                        responses.append(fallback)
                        break

            if not any(r.get('streamingData') for r in responses):
                raise Exception('No stream found')

            live_manifest = None
            formats = []
            for resp in responses:
                streaming = resp.get('streamingData', {})
                hls = streaming.get('hlsManifestUrl')
                dash = streaming.get('dashManifestUrl')
                if hls or dash:
                    live_manifest = {'hls': hls, 'dash': dash}
                raw_formats = streaming.get('formats', []) + streaming.get('adaptiveFormats', [])
                for fmt in raw_formats:
                    norm = self._normalize_format(fmt, player_url)
                    if norm and norm.get('url'):
                        if not any(f.get('itag') == norm.get('itag') for f in formats):
                            formats.append(norm)

            if not formats and not live_manifest:
                raise Exception('No stream found')

            video_title = player_response.get('videoDetails', {}).get('title', video_id) if player_response else video_id
            duration = int(player_response.get('videoDetails', {}).get('lengthSeconds', 0)) if player_response else 0
            data = {
                'id': video_id,
                'title': video_title,
                'duration': duration,
                'formats': formats,
                'live_manifest': live_manifest,
                'is_live': is_live,
            }
            self.extract_cache[cache_key] = {'data': data, 'expires': now + 3600}
            return data
        except Exception as e:
            debug_log('extract error', repr(e))
            raise

    def _fetch_page(self, url):
        r = self.session.get(url, headers=self.headers, timeout=15)
        r.raise_for_status()
        return r.text

    def _parse_page(self, html):
        ytcfg = self._extract_ytcfg(html)
        player_response = self._extract_json_after(html, 'ytInitialPlayerResponse')
        player_url = self._extract_player_url(html)
        return ytcfg or {}, player_response or {}, player_url or ''

    def _extract_ytcfg(self, html):
        m = re.search(r'ytcfg\.set\s*\(\s*({.+?})\s*\)\s*;', html, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except:
                pass
        return {}

    def _extract_json_after(self, html, marker):
        pos = html.find(marker)
        if pos < 0: return None
        start = html.find('{', pos)
        if start < 0: return None
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(html)):
            ch = html[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if in_str:
                if ch == in_str:
                    in_str = False
                continue
            if ch in ('"', "'"):
                in_str = ch
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[start:i+1])
                    except:
                        return None
        return None

    def _extract_player_url(self, html):
        patterns = [
            r'"jsUrl":"([^"]+)"',
            r'"PLAYER_JS_URL":"([^"]+)"',
            r'(/s/player/[^"\\]+/base\.js)',
            r'(/s/player/[^"\\]+/tv\.js)',
        ]
        for p in patterns:
            m = re.search(p, html)
            if m:
                return m.group(1).replace('\\/', '/')
        return ''

    def _fetch_get_video_info(self, video_id, el='embedded'):
        if el:
            url = f'https://www.youtube.com/get_video_info?video_id={video_id}&el={el}&ps=default&eurl='
        else:
            url = f'https://www.youtube.com/get_video_info?video_id={video_id}&ps=default&eurl='
        try:
            r = self.session.get(url, headers=self.headers, timeout=10)
            r.raise_for_status()
            params = parse_qs(r.text)
            if 'player_response' in params:
                return json.loads(params['player_response'][0])
        except:
            pass
        return None

    def _call_player_api(self, video_id, api_key, context, referer, visitor_data, is_live):
        # ===== 修复点：调整客户端顺序，WEB 和 ANDROID 优先 =====
        clients = [
            # 首选 WEB 客户端（通常返回全部格式）
            {'name': 'WEB', 'version': '2.20260121.09.00', 'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
            {'name': 'ANDROID', 'version': '21.02.35', 'ua': 'com.google.android.youtube/21.02.35 (Linux; U; Android 11) gzip'},
            {'name': 'IOS', 'version': '21.02.3', 'ua': 'com.google.ios.youtube/21.02.3 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X)'},
            {'name': 'MWEB', 'version': '2.20260115.01.00', 'ua': 'Mozilla/5.0 (iPad; CPU OS 16_7_10 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1,gzip(gfe)'},
            {'name': 'ANDROID_VR', 'version': '1.65.10', 'ua': 'com.google.android.apps.youtube.vr.oculus/1.65.10 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip'},
            {'name': 'WEB_EMBEDDED_PLAYER', 'version': '1.20260120.00.00', 'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
            {'name': 'WEB_REMIX', 'version': '1.20260120.00.00', 'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
            # TV 客户端放最后（仅用于直播或备选）
            {'name': 'TVHTML5', 'version': '7.20240220.00.00', 'ua': 'Mozilla/5.0 (Chromecast)'},
            {'name': 'TV', 'version': '1.20260120.00.00', 'ua': 'Mozilla/5.0 (Chromecast)'},
        ]
        if is_live:
            # 直播时 TV 客户端放前面
            clients.insert(0, {'name': 'TV', 'version': '1.20260120.00.00', 'ua': 'Mozilla/5.0 (Chromecast)'})
            clients.insert(1, {'name': 'TVHTML5', 'version': '7.20240220.00.00', 'ua': 'Mozilla/5.0 (Chromecast)'})

        results = []
        for client in clients:
            try:
                payload = {
                    'context': {
                        'client': {
                            'clientName': client['name'],
                            'clientVersion': client['version'],
                            'hl': 'en',
                            'gl': 'US',
                            'userAgent': client['ua']
                        }
                    },
                    'videoId': video_id,
                    'playbackContext': {'contentPlaybackContext': {'html5Preference': 'HTML5_PREF_WANTS'}},
                    'contentCheckOk': True,
                    'racyCheckOk': True,
                }
                url = f'https://www.youtube.com/youtubei/v1/player?key={api_key}&prettyPrint=false'
                headers = {
                    'Referer': referer,
                    'X-YouTube-Client-Name': str(self._client_name_id(client['name'])),
                    'X-YouTube-Client-Version': client['version'],
                    'User-Agent': client['ua'],
                }
                if visitor_data:
                    headers['X-Goog-Visitor-Id'] = visitor_data
                r = self.session.post(url, json=payload, headers=headers, timeout=15)
                r.raise_for_status()
                data = r.json()
                if data.get('streamingData'):
                    data['_client_name'] = client['name']
                    results.append(data)
                    debug_log(f'API client {client["name"]} success')
            except Exception as e:
                debug_log(f'API client {client["name"]} failed', str(e))
                continue
        return results

    def _client_name_id(self, name):
        mapping = {
            'WEB': 1, 'MWEB': 2, 'ANDROID': 3, 'IOS': 5, 'TVHTML5': 7,
            'ANDROID_VR': 28, 'WEB_EMBEDDED_PLAYER': 56, 'WEB_REMIX': 67,
            'TV': 85, 'TV_DOWNGRADED': 86,
        }
        return mapping.get(name, 1)

    def _normalize_format(self, fmt, player_url):
        url = fmt.get('url')
        if not url:
            cipher = fmt.get('signatureCipher') or fmt.get('cipher')
            if cipher:
                url = self._decrypt_signature(cipher, player_url)
        if not url:
            return None
        url = self._decrypt_nsig(url, player_url)
        if not url:
            return None

        mime = fmt.get('mimeType', '')
        codecs = re.search(r'codecs="([^"]+)"', mime)
        codecs = codecs.group(1) if codecs else ''
        has_video = mime.startswith('video/') or any(x in codecs for x in ('avc', 'vp9', 'av01', 'h264'))
        has_audio = mime.startswith('audio/') or any(x in codecs for x in ('mp4a', 'opus', 'vorbis'))
        
        # 修复点：从 quality 中提取高度
        height = fmt.get('height', 0)
        if height == 0:
            quality_label = fmt.get('qualityLabel') or fmt.get('quality')
            if quality_label:
                match = re.search(r'(\d+)p', quality_label)
                if match:
                    height = int(match.group(1))
        
        return {
            'itag': fmt.get('itag'),
            'url': url,
            'mimeType': mime,
            'ext': 'mp4' if 'mp4' in mime else 'webm' if 'webm' in mime else 'unknown',
            'width': fmt.get('width', 0),
            'height': height,
            'fps': fmt.get('fps', 0),
            'bitrate': fmt.get('bitrate') or fmt.get('averageBitrate') or 0,
            'initRange': fmt.get('initRange', {}),
            'indexRange': fmt.get('indexRange', {}),
            'codecs': codecs,
            'quality': fmt.get('qualityLabel') or fmt.get('quality'),
            'vcodec': codecs if has_video else 'none',
            'acodec': codecs if has_audio else 'none',
            'headers': fmt.get('http_headers', {}),
        }

    def _decrypt_signature(self, cipher, player_url):
        params = parse_qs(cipher)
        url = unquote(params.get('url', [''])[0])
        s = unquote(params.get('s', [''])[0])
        sp = params.get('sp', ['sig'])[0]
        if not url or not s:
            return url
        if player_url:
            decoded_s = self._decrypt_sig(s, player_url)
            if decoded_s:
                sep = '&' if '?' in url else '?'
                return f'{url}{sep}{sp}={quote(decoded_s)}'
        return url

    def _decrypt_sig(self, sig, player_url):
        js_code = self._get_player_code(player_url)
        if not js_code:
            return sig
        func_name = None
        for pattern in [
            r'\.sig\|\|([a-zA-Z0-9_$]+)\(',
            r'"signature",\s*([a-zA-Z0-9_$]+)\(',
            r'([a-zA-Z0-9_$]+)=function\(a\)\{a=a\.split\(""\);',
        ]:
            m = re.search(pattern, js_code)
            if m:
                func_name = m.group(1)
                break
        if not func_name:
            return sig
        try:
            interp = JSInterpreter(js_code, func_name)
            return interp.call(func_name, [sig])
        except Exception:
            return sig

    def _decrypt_nsig(self, url, player_url):
        parsed = urlparse(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        n = query.get('n', [None])[0]
        if not n:
            return url

        js_code = self._get_player_code(player_url)
        if not js_code:
            query.pop('n', None)
            new_parsed = parsed._replace(query=urlencode(query, doseq=True))
            return urlunparse(new_parsed)

        func_name = None
        patterns = [
            r'\b([a-zA-Z0-9_$]+)\s*=\s*function\s*\(a\)\s*\{.*?\.n\s*=',
            r'"n",\s*([a-zA-Z0-9_$]+)\(',
            r'function\s+([a-zA-Z0-9_$]+)\s*\(a\)\s*\{.*?\.n\s*=',
            r'\.n\s*=\s*([a-zA-Z0-9_$]+)\(',
            r'\b([a-zA-Z0-9_$]+)\([a-zA-Z0-9_$]+\)\.n\s*=',
        ]
        for p in patterns:
            m = re.search(p, js_code, re.S)
            if m:
                func_name = m.group(1)
                break

        if not func_name:
            query.pop('n', None)
            new_parsed = parsed._replace(query=urlencode(query, doseq=True))
            return urlunparse(new_parsed)

        try:
            interp = JSInterpreter(js_code, func_name)
            decoded = interp.call(func_name, [n])
            if decoded and decoded != n:
                query['n'] = [decoded]
            else:
                query.pop('n', None)
        except Exception as e:
            debug_log('n-sig decryption failed', str(e))
            query.pop('n', None)

        new_parsed = parsed._replace(query=urlencode(query, doseq=True))
        return urlunparse(new_parsed)

    def _get_player_code(self, player_url):
        if not player_url: return ''
        if player_url in self.player_cache:
            return self.player_cache[player_url]
        if player_url.startswith('//'):
            player_url = 'https:' + player_url
        elif player_url.startswith('/'):
            player_url = 'https://www.youtube.com' + player_url
        try:
            r = self.session.get(player_url, headers=self.headers, timeout=15)
            r.raise_for_status()
            code = r.text
        except Exception:
            code = ''
        self.player_cache[player_url] = code
        return code

    def choose_video_tracks(self, formats, quality='best', codec_filter=None):
        # 修复点：如果纯视频轨道为空，则包含渐进式（音视频合流）
        videos = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') == 'none']
        if not videos:
            # 尝试包含所有视频格式（包括渐进式）
            videos = [f for f in formats if f.get('vcodec') != 'none']
        if codec_filter:
            videos = [f for f in videos if codec_filter in f.get('codecs', '').lower()]
        # 按分辨率降序，若 height 为0则尝试从 quality 提取
        videos.sort(key=lambda f: (int(f.get('height', 0)), int(f.get('bitrate', 0))), reverse=True)
        if videos:
            best = videos[0]
            hdr = self._is_hdr(best)
            tracks = []
            item = best.copy()
            item['track_name'] = 'HDR' if hdr else 'SDR'
            item['is_hdr'] = hdr
            tracks.append(item)
            if hdr:
                sdr = next((f for f in videos if not self._is_hdr(f)), None)
                if sdr:
                    sdr = sdr.copy()
                    sdr['track_name'] = 'SDR'
                    sdr['is_hdr'] = False
                    tracks.append(sdr)
            return tracks
        return []

    def choose_audio(self, formats):
        audios = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
        if not audios:
            return None
        audios.sort(key=lambda f: int(f.get('bitrate', 0)), reverse=True)
        return audios[0]

    def _is_hdr(self, fmt):
        mime = fmt.get('mimeType', '').lower()
        codecs = fmt.get('codecs', '').lower()
        return 'vp9.2' in mime or 'vp09.02' in codecs or fmt.get('colorInfo', {}).get('hdrMetadataInfo')

# ========== TVbox 适配层（保持不变） ==========
class Spider(Spider):
    def getName(self):
        return 'YouTube'

    def init(self, extend):
        try:
            self.extendDict = json.loads(extend) if extend else {}
        except:
            self.extendDict = {}
        self.session = requests.Session()
        self.proxy_str = None
        proxy_val = self.extendDict.get('proxy')
        if proxy_val:
            if isinstance(proxy_val, dict):
                self.session.proxies = proxy_val
                self.proxy_str = (proxy_val.get('http') or proxy_val.get('https') or '').replace('http://', '').replace('https://', '')
            elif isinstance(proxy_val, str):
                self.proxy_str = proxy_val.replace('http://', '').replace('https://', '')
                self.session.proxies = {'http': f'http://{self.proxy_str}', 'https': f'http://{self.proxy_str}'}

        self.header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://www.youtube.com/',
            'Cookie': 'CONSENT=YES+cb; SOCS=CAESEwgDEgk2MzgzMjY1MzkaAmVuIAEaBgiAo_CmBg',
        }
        cookie_val = self.extendDict.get('cookie')
        if cookie_val:
            self.header['Cookie'] = cookie_val
        self.session.headers.update(self.header)

        self.yt = YouTubeIE(self.session, self.header, self.extendDict)
        self._cache = {}
        self.search_cache = {}
        self.classes = []
        self.filters = {}
        self.search_map = {}
        
        config_path = os.path.join(os.path.dirname(__file__), './lib/youtube.json')
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.classes = config.get('class', [])
                self.filters = config.get('filters', {})
                for item in self.classes:
                    self.search_map[item.get('type_id')] = item.get('type_name')
            except:
                self._fallback_hardcoded()
        else:
            self._fallback_hardcoded()

        self.news_keywords = (
            'TVBS NEWS 直播 東森新聞 直播 中天新聞 直播 民視新聞 直播 三立新聞 直播 '
            '台視新聞 直播 中視新聞 直播 華視新聞 直播 公視 直播 公視台語台 直播 '
            '寰宇新聞 直播 鏡新聞 直播 大愛 直播 非凡財經 直播 東森財經 直播 '
            '三立財經iNEWS 直播 鳳凰衛視 直播 CCTV中文国际 直播 '
            '新闻直播 24小时新闻 实时新闻 突发新闻 头条新闻 即时新闻 新闻直播间'
        )
        self.intl_news_keywords = (
            'Al Jazeera English live BBC News live CNN live Sky News live '
            'France 24 live DW live ABC News live CBS News live NBC News live '
            'NHK live Arirang live CNA live Bloomberg live CNBC live Fox News live '
            'Euronews live RT live TRT World live NDTV live India Today live WION live '
            'CGTN live Al Arabiya live '
            '24/7 live news breaking news live live news channel'
        )

    def _fallback_hardcoded(self):
        self.classes = [
            {'type_id': '新闻直播', 'type_name': '新闻直播'},
            {'type_id': '国际新闻', 'type_name': '国际新闻'},
            {'type_id': '动漫', 'type_name': '动漫'},
            {'type_id': '动画片', 'type_name': '动画片'},
            {'type_id': '综艺', 'type_name': '综艺'},
            {'type_id': '电影', 'type_name': '电影'},
            {'type_id': '剧集', 'type_name': '剧集'},
            {'type_id': '体育', 'type_name': '体育'},
        ]
        self.search_map = {'新闻直播': '新闻直播'}

    def setCache(self, key, value):
        self._cache[key] = value

    def getCache(self, key):
        data = self._cache.get(key)
        if data and isinstance(data, dict) and data.get('expires', 0) > time.time():
            return data
        return None

    def homeContent(self, filter):
        result = {'class': self.classes}
        if filter and self.filters:
            result['filters'] = self.filters
        return result

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, cid, page, filter, ext):
        page = int(page)
        filters = ext if isinstance(ext, dict) else {}
        query = self._build_category_keyword(cid, filters)
        videos, has_more = self._search_youtube(query, page)
        videos.sort(key=lambda x: x.get('is_live', False), reverse=True)
        return {'list': videos, 'page': page, 'pagecount': page + 1 if has_more else page, 'limit': len(videos), 'total': len(videos)}

    def searchContent(self, key, quick, pg=1):
        page = int(pg)
        videos, has_more = self._search_youtube(key, page)
        videos.sort(key=lambda x: x.get('is_live', False), reverse=True)
        return {'list': videos, 'page': page, 'pagecount': page + 1 if has_more else page, 'limit': len(videos), 'total': len(videos)}

    def detailContent(self, did):
        video_id = did[0]
        title = self._get_video_title(video_id)
        safe_title = self._safe_title(title)
        try:
            data = self.yt.extract(video_id)
            formats = data['formats']
            codec_groups = {}
            for fmt in formats:
                if fmt.get('vcodec') == 'none':
                    continue
                codec = fmt.get('codecs', '').lower()
                if 'avc' in codec or 'h264' in codec:
                    ct = 'h264'
                elif 'vp9' in codec or 'vp09' in codec:
                    ct = 'vp9'
                elif 'av01' in codec:
                    ct = 'av1'
                else:
                    ct = 'other'
                codec_groups.setdefault(ct, []).append(fmt)
            play_sources = []
            play_urls = []
            for ct, fmts in codec_groups.items():
                fmts.sort(key=lambda f: int(f.get('height', 0)), reverse=True)
                best = fmts[0]
                h = int(best.get('height', 0))
                is_hdr = self.yt._is_hdr(best)
                label = f'{h}p {ct.upper()} {"HDR" if is_hdr else "SDR"}'
                quality = 'hdr' if is_hdr else 'best'
                play_sources.append(label)
                play_urls.append(f'{safe_title} {label}${video_id}@{quality}_{ct}')
        except Exception:
            play_sources = ['SDR', 'HDR']
            play_urls = [f'{safe_title} SDR${video_id}@best_h264', f'{safe_title} HDR${video_id}@hdr_h264']
        vod = {
            'vod_id': video_id,
            'vod_name': title,
            'vod_pic': f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg',
            'vod_play_from': '$$$'.join(play_sources),
            'vod_play_url': '$$$'.join(play_urls)
        }
        return {'list': [vod]}

    def playerContent(self, flag, pid, vipFlags):
        raw = pid.split('$')[-1]
        if '@' in raw:
            parts = raw.rsplit('@', 1)
            video_id, qc = parts[0], parts[1] if len(parts) > 1 else 'best'
            if '_' in qc:
                quality, codec_type = qc.split('_', 1)
            else:
                quality, codec_type = qc, None
        else:
            video_id, quality, codec_type = raw, 'best', None
        if quality not in ('best', 'hdr', '4k', '2k', '1080p'):
            quality = 'best'

        try:
            data = self.yt.extract(video_id)
            
            manifest = data.get('live_manifest')
            if manifest:
                url = manifest.get('hls') or manifest.get('dash')
                if url:
                    debug_log('Bypassing proxy for live stream', url)
                    return {
                        'parse': 0,
                        'jx': 0,
                        'url': url,
                        'header': self.header,
                        'format': 'application/vnd.apple.mpegurl' if url.endswith('.m3u8') else 'application/dash+xml'
                    }

            all_tracks = self.yt.choose_video_tracks(data['formats'], 'best', codec_filter=codec_type)
            wanted = 'HDR' if quality == 'hdr' else 'SDR'
            video_tracks = [t for t in all_tracks if t.get('track_name') == wanted]
            if not video_tracks and all_tracks:
                video_tracks = [all_tracks[0]]
                
            if video_tracks:
                audio = self.yt.choose_audio(data['formats'])
                if audio:
                    cache_key = f'yt_mpd_{video_id}_{quality}_{codec_type or "none"}'
                    self.setCache(cache_key, {
                        'video_tracks': video_tracks,
                        'audio_track': audio,
                        'duration': data.get('duration', 0),
                        'expires': time.time() + 300,
                    })
                    return {
                        'parse': 0,
                        'jx': 0,
                        'url': f'http://127.0.0.1:9978/proxy?do=py&type=mpd&vid={video_id}&quality={quality}_{codec_type or "none"}',
                        'format': 'application/dash+xml',
                        'header': self.header
                    }
                else:
                    playable = video_tracks[0]
                    return {
                        'parse': 0,
                        'jx': 0,
                        'url': playable['url'],
                        'header': playable.get('headers', self.header)
                    }

            progressive = [f for f in data['formats'] if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
            if progressive:
                progressive.sort(key=lambda f: (int(f.get('height', 0)), int(f.get('bitrate', 0))), reverse=True)
                playable = progressive[0]
                return {
                    'parse': 0,
                    'jx': 0,
                    'url': playable['url'],
                    'header': playable.get('headers', self.header)
                }

            raise Exception('No playable stream')
        except Exception as e:
            debug_log('playerContent error fallback to webview', repr(e))
            return {
                'parse': 1,
                'url': f'https://www.youtube.com/embed/{video_id}?autoplay=1',
                'proxy': self.proxy_str
            }

    def localProxy(self, params):
        if params.get('do') != 'py':
            return None
        typ = params.get('type')
        if typ == 'mpd':
            return self._proxy_mpd(params)
        return None

    def _proxy_mpd(self, params):
        vid = params.get('vid')
        qc = params.get('quality')
        cache_key = f'yt_mpd_{vid}_{qc}'
        data = self.getCache(cache_key)
        if not data:
            data = self._refresh_mpd(vid, qc)
        if not data:
            return [404, 'text/plain', 'MPD cache expired']
            
        video_tracks = data.get('video_tracks', [])
        audio_track = data.get('audio_track', {})
        duration = data.get('duration', 0)
        duration_pt = f"PT{int(duration)}S" if duration else "PT0S"
        
        mpd = f'''<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="{duration_pt}" minBufferTime="PT2S" profiles="urn:mpeg:dash:profile:isoff-on-demand:2011">
  <Period id="1" start="PT0S">
'''
        for item in video_tracks:
            init = item.get('initRange', {})
            idx = item.get('indexRange', {})
            base_url = item.get('url')
            mpd += f'''    <AdaptationSet mimeType="{html.escape(item.get('mimeType', 'video/mp4').split(';')[0])}" startWithSAP="1" segmentAlignment="true" scanType="progressive">
      <Representation id="v{item.get('itag', 1)}" bandwidth="{item.get('bitrate', 1000000)}" codecs="{html.escape(item.get('codecs', ''))}" height="{item.get('height', 0)}" width="{item.get('width', 0)}">
        <BaseURL>{html.escape(base_url)}</BaseURL>
        <SegmentBase indexRange="{idx.get('start', 0)}-{idx.get('end', 0)}"><Initialization range="{init.get('start', 0)}-{init.get('end', 0)}"/></SegmentBase>
      </Representation>
    </AdaptationSet>
'''
        if audio_track:
            init = audio_track.get('initRange', {})
            idx = audio_track.get('indexRange', {})
            base_url = audio_track.get('url')
            mpd += f'''    <AdaptationSet mimeType="{html.escape(audio_track.get('mimeType', 'audio/mp4').split(';')[0])}" startWithSAP="1" segmentAlignment="true" lang="und">
      <Representation id="audio" bandwidth="{audio_track.get('bitrate', 128000)}" codecs="{html.escape(audio_track.get('codecs', ''))}" audioSamplingRate="44100">
        <BaseURL>{html.escape(base_url)}</BaseURL>
        <SegmentBase indexRange="{idx.get('start', 0)}-{idx.get('end', 0)}"><Initialization range="{init.get('start', 0)}-{init.get('end', 0)}"/></SegmentBase>
      </Representation>
    </AdaptationSet>
'''
        mpd += '  </Period>\n</MPD>'
        
        headers = {
            'Content-Type': 'application/dash+xml',
            'Access-Control-Allow-Origin': '*'
        }
        return [200, headers, mpd]

    def _refresh_mpd(self, vid, qc):
        try:
            data = self.yt.extract(vid)
            quality, codec_type = qc.split('_') if '_' in qc else (qc, None)
            all_tracks = self.yt.choose_video_tracks(data['formats'], 'best', codec_filter=codec_type)
            wanted = 'HDR' if quality == 'hdr' else 'SDR'
            video_tracks = [t for t in all_tracks if t.get('track_name') == wanted]
            if not video_tracks and all_tracks:
                video_tracks = [all_tracks[0]]
            audio = self.yt.choose_audio(data['formats'])
            if not video_tracks:
                return None
            cache_data = {'video_tracks': video_tracks, 'audio_track': audio, 'duration': data.get('duration', 0), 'expires': time.time() + 300}
            self.setCache(f'yt_mpd_{vid}_{qc}', cache_data)
            return cache_data
        except Exception:
            return None

    def _build_category_keyword(self, cid, filters):
        category_id = CATEGORY_ALIASES.get(cid, cid)
        if category_id == '新闻直播':
            base = self.news_keywords
        elif category_id == '国际新闻':
            base = self.intl_news_keywords
        else:
            base = self.search_map.get(cid) or category_id
        terms = [base] if base else []
        if filters:
            for k, v in filters.items():
                if v:
                    terms.append(str(v))
        return ' '.join(terms)

    def _search_youtube(self, query, page):
        page = max(1, int(page))
        cache_key = hashlib.md5(query.encode()).hexdigest()
        session = self.search_cache.get(cache_key)
        if page == 1 or not session:
            session = self._fetch_search_first(query)
            self.search_cache[cache_key] = session
        while len(session.get('pages', [])) < page and session.get('next'):
            data = self._fetch_search_continuation(session)
            videos = self._extract_videos(data, 30)
            session.setdefault('pages', []).append(videos)
            session['next'] = self._extract_continuation(data)
        pages = session.get('pages', [])
        videos = pages[page - 1] if len(pages) >= page else []
        has_more = bool(session.get('next')) or len(pages) > page
        return videos, has_more

    def _fetch_search_first(self, query):
        url = f'https://www.youtube.com/results?search_query={quote(query)}'
        r = self.session.get(url, timeout=15)
        html = r.text
        data = self.yt._extract_json_after(html, 'ytInitialData') or {}
        ytcfg = self.yt._extract_ytcfg(html) or {}
        api_key = ytcfg.get('INNERTUBE_API_KEY')
        context = ytcfg.get('INNERTUBE_CONTEXT', {})
        videos = self._extract_videos(data, 30)
        return {'api_key': api_key, 'context': context, 'referer': url, 'pages': [videos], 'next': self._extract_continuation(data)}

    def _fetch_search_continuation(self, session):
        token = session.get('next')
        api_key = session.get('api_key')
        if not token or not api_key: return {}
        url = f'https://www.youtube.com/youtubei/v1/search?key={api_key}'
        headers = self.header.copy()
        headers.update({'Content-Type': 'application/json', 'Origin': 'https://www.youtube.com', 'Referer': session.get('referer', 'https://www.youtube.com/')})
        payload = {'context': session.get('context', {}), 'continuation': token}
        try:
            r = self.session.post(url, json=payload, headers=headers, timeout=15)
            r.raise_for_status()
            return r.json()
        except: return {}

    def _extract_continuation(self, data):
        tokens = []
        def scan(obj):
            if isinstance(obj, dict):
                for key, val in obj.items():
                    if key == 'continuationEndpoint':
                        token = val.get('continuationCommand', {}).get('token')
                        if token: tokens.append(token)
                    elif key == 'continuationItemRenderer':
                        token = val.get('continuationEndpoint', {}).get('continuationCommand', {}).get('token')
                        if token: tokens.append(token)
                    else: scan(val)
            elif isinstance(obj, list):
                for item in obj: scan(item)
        scan(data)
        return tokens[0] if tokens else None

    def _extract_videos(self, data, limit):
        videos = []
        seen = set()
        def scan(obj):
            if len(videos) >= limit: return
            if isinstance(obj, dict):
                for key in ('videoRenderer', 'compactVideoRenderer', 'gridVideoRenderer'):
                    if key in obj:
                        item = self._parse_renderer(obj[key])
                        if item and item['vod_id'] not in seen:
                            seen.add(item['vod_id'])
                            videos.append(item)
                for val in obj.values(): scan(val)
            elif isinstance(obj, list):
                for val in obj: scan(val)
        scan(data)
        return videos[:limit]

    def _parse_renderer(self, renderer):
        try:
            vid = renderer.get('videoId')
            if not vid:
                nav = renderer.get('navigationEndpoint', {})
                vid = nav.get('watchEndpoint', {}).get('videoId')
            if not vid: return None
            title_obj = renderer.get('title', {})
            title = title_obj.get('simpleText') or ' '.join([x.get('text', '') for x in title_obj.get('runs', [])]) or 'YouTube'
            dur = renderer.get('lengthText', {}).get('simpleText', '')
            is_live = False
            for badge in renderer.get('badges', []):
                if badge.get('metadataBadgeRenderer', {}).get('style') == 'BADGE_STYLE_TYPE_LIVE_NOW':
                    is_live = True
                    break
            return {'vod_id': vid, 'vod_name': html.unescape(title), 'vod_pic': f'https://img.youtube.com/vi/{vid}/hqdefault.jpg', 'vod_remarks': dur, 'is_live': is_live}
        except: return None

    def _get_video_title(self, vid):
        try:
            r = self.session.get(f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json', timeout=5)
            return r.json().get('title', vid)
        except: return vid

    def _safe_title(self, title):
        if not title: return 'video'
        return re.sub(r'[#$@%&!?*|\\/:<>]', ' ', title)[:60]

    def destroy(self):
        try:
            self.session.close()
        except:
            pass