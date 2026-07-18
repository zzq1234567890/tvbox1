#coding=utf-8
#!/usr/bin/python
import re
import os
import sys
import json
import html
import time
from urllib.parse import quote, unquote, parse_qs, urlencode, urlparse, urlunparse
import requests
from base.spider import Spider
sys.path.append('..')

DEBUG_LOG = '/sdcard/Download/0714youtube_trace.log'

# 分类别名
CATEGORY_ALIASES = {
    '動畫片': '动画片', '劇集': '剧集', '電影': '电影', '紀錄片': '纪录片', '解說': '解说',
    'movie': '电影', 'game': '科技', 'documentary': '纪录片', '新聞直播': '新闻直播','港劇': '港劇',

    '動漫': '动漫', '綜藝': '综艺', '政論': '政论', '體育': '体育', '時尚潮流': '时尚潮流',
    '自媒體': '自媒体', '音樂': '音乐', '科普知識': '科普知识', '短劇': '短剧',
    '國際新聞': '国际新闻',
}

def _filter_group(key, name, pairs):
    return {'key': key, 'name': name, 'value': [{'n': '全部', 'v': ''}] + [{'n': n, 'v': v} for n, v in pairs]}

def _with_year(*groups):
    years = [{'n': '全部', 'v': ''}] + [{'n': str(year), 'v': str(year)} for year in range(2026, 1957, -1)]
    return [{'key': 'year', 'name': '年份', 'value': years}] + list(groups)

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

class YouTubeLite:
    def __init__(self, session, headers=None, config=None):
        self.session = session
        self.headers = headers or {}
        self.config = config or {}
        self.player_cache = {}
        self.extract_cache = {}
        self.sig_plan_cache = {}
        # 默认缓存 TTL 3600 秒，配合刷新机制更稳定
        self.extract_cache_ttl = int(self.config.get('extract_cache_ttl') or 3600)

    def extract(self, url_or_id):
        video_id = self.extract_video_id(url_or_id)
        cached = self.extract_cache.get(video_id)
        now = time.time()
        if cached and cached.get('expires', 0) > now:
            debug_log('extract cache hit', {'video_id': video_id, 'ttl': int(cached.get('expires', 0) - now)})
            return cached.get('data')
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        extract_started = time.time()
        debug_log('extract start', {'input': url_or_id, 'video_id': video_id})
        watch_started = time.time()
        page_resp = self._get(watch_url)
        page = page_resp.text
        debug_log('watch page', {'status': page_resp.status_code, 'length': len(page), 'cost_ms': int((time.time() - watch_started) * 1000)})
        ytcfg = self._extract_ytcfg(page) or {}
        player_response = self._extract_initial_player_response(page) or {}
        player_url = self._extract_player_url(page)
        api_key = ytcfg.get('INNERTUBE_API_KEY') or self._search(r'"INNERTUBE_API_KEY":"([^"]+)"', page)
        visitor_data = self._extract_visitor_data(ytcfg, player_response)
        sts = None

        # ---- 判断是否直播 ----
        is_live = False
        duration = 0
        if player_response:
            details = player_response.get('videoDetails') or {}
            is_live = details.get('isLive') or details.get('isLiveContent') or False
            duration = int(details.get('lengthSeconds') or 0)
        debug_log('live detection', {'video_id': video_id, 'is_live': is_live, 'duration': duration})

        debug_log('page parsed', {'has_ytcfg': bool(ytcfg), 'has_initial_pr': bool(player_response),
                                  'initial_status': (player_response.get('playabilityStatus') or {}).get('status'),
                                  'initial_has_streaming': bool(player_response.get('streamingData')),
                                  'has_api_key': bool(api_key), 'has_visitor': bool(visitor_data),
                                  'sts': sts, 'player_url': player_url})
        context = ytcfg.get('INNERTUBE_CONTEXT') or {
            'client': {'clientName': 'WEB', 'clientVersion': '2.20240310.01.00', 'hl': 'en', 'gl': 'US'}
        }
        responses = [player_response] if player_response else []
        if api_key:
            api_responses = self._call_player_api(video_id, api_key, context, watch_url, visitor_data, sts, is_live)
            if not isinstance(api_responses, list):
                api_responses = [api_responses] if api_responses else []
            responses.extend([x for x in api_responses if x])

        # 合并响应后，检查直播 manifest（仅当有实际 hls 或 dash 时才视为直播）
        live_manifest = None
        for resp in responses:
            streaming = resp.get('streamingData') or {}
            hls = streaming.get('hlsManifestUrl')
            dash = streaming.get('dashManifestUrl')
            if hls or dash:
                live_manifest = {'hls': hls, 'dash': dash}
                debug_log('found live manifest', {'client': resp.get('_client_name'), 'hls': hls, 'dash': dash})
                break
        # 没有 manifest 就算 isLive 为 True 也视为点播
        if not live_manifest:
            debug_log('无有效 manifest，视为点播', {'video_id': video_id})

        player_response = next((x for x in responses if (x.get('playabilityStatus') or {}).get('status') == 'OK'), player_response)
        status = (player_response.get('playabilityStatus') or {}).get('status')
        streaming = player_response.get('streamingData') or {}
        if status and status not in ('OK', 'LIVE_STREAM_OFFLINE') and not streaming:
            reason = (player_response.get('playabilityStatus') or {}).get('reason') or status
            raise Exception(f'YouTube 不可播放: {reason}')
        details = player_response.get('videoDetails') or {}
        raw_formats = []
        seen_raw = set()
        source_counts = []
        for response in responses:
            response_streaming = (response or {}).get('streamingData') or {}
            source_raw = (response_streaming.get('formats') or []) + (response_streaming.get('adaptiveFormats') or [])
            source_counts.append({'formats': len(response_streaming.get('formats') or []),
                                  'adaptive': len(response_streaming.get('adaptiveFormats') or [])})
            for raw in source_raw:
                key = (raw.get('itag'), raw.get('url') or raw.get('signatureCipher') or raw.get('cipher') or raw.get('mimeType'))
                if key not in seen_raw:
                    seen_raw.add(key)
                    raw = raw.copy()
                    raw['_client_name'] = (response or {}).get('_client_name')
                    raw['_client_ua'] = (response or {}).get('_client_ua')
                    raw_formats.append(raw)
        debug_log('raw formats', {'sources': source_counts, 'total': len(raw_formats),
                                  'sample_keys': sorted(list(raw_formats[0].keys())) if raw_formats else []})
        formats = []
        cipher_count = 0
        for raw in raw_formats:
            if raw.get('signatureCipher') or raw.get('cipher'):
                cipher_count += 1
            item = self._normalize_format(raw, player_url)
            if item and item.get('url'):
                formats.append(item)
        debug_log('normalized formats', {'count': len(formats), 'cipher_count': cipher_count,
                                         'progressive': len([x for x in formats if x.get('vcodec') != 'none' and x.get('acodec') != 'none'])})

        if not formats and not live_manifest:
            raise Exception('未获取到可用播放地址')

        data = {
            'id': video_id,
            'title': details.get('title') or video_id,
            'duration': int(details.get('lengthSeconds') or 0),
            'formats': formats,
            'live_manifest': live_manifest,
        }
        self.extract_cache[video_id] = {'data': data, 'expires': time.time() + self.extract_cache_ttl}
        debug_log('extract complete', {'video_id': video_id, 'cost_ms': int((time.time() - extract_started) * 1000),
                                       'formats': len(formats), 'is_live': bool(live_manifest)})
        return data

    @staticmethod
    def extract_video_id(text):
        text = str(text or '').strip()
        for pattern in [
            r'(?:v=|/v/|/embed/|/shorts/|youtu\.be/)([0-9A-Za-z_-]{11})',
            r'^([0-9A-Za-z_-]{11})$',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        raise Exception('无法识别 YouTube 视频 ID')

    def _client_name_id(self, client_name):
        return {
            'WEB': 1, 'MWEB': 2, 'ANDROID': 3, 'IOS': 5, 'TVHTML5': 7,
            'ANDROID_VR': 28, 'WEB_EMBEDDED_PLAYER': 56, 'WEB_REMIX': 67,
        }.get(client_name, 1)

    def _extract_visitor_data(self, ytcfg, player_response):
        return (
            self.config.get('visitor_data')
            or ytcfg.get('VISITOR_DATA')
            or (((ytcfg.get('INNERTUBE_CONTEXT') or {}).get('client') or {}).get('visitorData'))
            or ((player_response.get('responseContext') or {}).get('visitorData'))
        )

    def choose_playable(self, formats, quality=None):
        all_videos = [x for x in formats if x.get('vcodec') != 'none' and x.get('acodec') == 'none']
        candidates = all_videos[:]
        if quality == '4k':
            candidates = [x for x in candidates if int(x.get('height') or 0) >= 2160]
        elif quality == '2k':
            candidates = [x for x in candidates if 1440 <= int(x.get('height') or 0) < 2160]
        elif quality == '1080p':
            candidates = [x for x in candidates if 1000 <= int(x.get('height') or 0) < 1440]
        elif quality == 'best':
            safe_candidates = [x for x in candidates if not self._is_risky_best_video(x)]
            if safe_candidates:
                candidates = safe_candidates
        else:
            candidates = [x for x in candidates if int(x.get('height') or 0) >= 1080]
        if not candidates and quality == 'best':
            candidates = all_videos
        if not candidates:
            return None
        candidates.sort(key=lambda x: (
            self._video_codec_priority(x),
            int(x.get('height') or 0),
            int(x.get('bitrate') or 0)
        ), reverse=True)
        return candidates[0]

    def _video_codec_priority(self, item):
        mime = (item.get('mimeType') or '').lower()
        codecs = (item.get('codecs') or '').lower()
        if 'vp9.2' in mime or 'vp09.02' in codecs:
            return 4
        if 'vp9' in mime or 'vp09' in codecs:
            return 3
        if 'avc' in codecs or 'h264' in codecs:
            return 2
        if 'av01' in codecs:
            return 1
        return 0

    def _is_risky_best_video(self, item):
        codecs = (item.get('codecs') or '').lower()
        return 'av01' in codecs

    def choose_video_tracks(self, formats, quality=None, codec_filter=None):
        videos = [x for x in formats if x.get('vcodec') != 'none' and x.get('acodec') == 'none']
        if codec_filter:
            videos = [x for x in videos if codec_filter in (x.get('codecs') or '').lower()]
        cap = 2160 if quality in ('best', '4k') else 1440 if quality == '2k' else 1080
        videos = [x for x in videos if int(x.get('height') or 0) <= cap] or videos
        vp9 = [x for x in videos if self._video_codec_priority(x) >= 3]
        if vp9:
            videos = vp9
        sdr = [x for x in videos if not self._is_hdr_video(x)]
        hdr = [x for x in videos if self._is_hdr_video(x)]
        sort_key = lambda x: (int(x.get('height') or 0), int(x.get('bitrate') or 0))
        sdr.sort(key=sort_key, reverse=True)
        hdr.sort(key=sort_key, reverse=True)
        tracks = []
        if sdr:
            item = sdr[0].copy()
            item['track_name'] = 'SDR'
            item['is_hdr'] = False
            tracks.append(item)
        if hdr:
            item = hdr[0].copy()
            item['track_name'] = 'HDR'
            item['is_hdr'] = True
            tracks.append(item)
        if not tracks:
            item = self.choose_playable(formats, quality)
            if item:
                item = item.copy()
                item['track_name'] = 'HDR' if self._is_hdr_video(item) else 'SDR'
                item['is_hdr'] = self._is_hdr_video(item)
                tracks.append(item)
        return tracks

    def _is_hdr_video(self, item):
        mime = (item.get('mimeType') or '').lower()
        codecs = (item.get('codecs') or '').lower()
        color = item.get('colorInfo') or {}
        return 'vp9.2' in mime or 'vp09.02' in codecs or bool(color.get('hdrMetadataInfo'))

    def choose_audio(self, formats):
        candidates = [x for x in formats if x.get('acodec') != 'none' and x.get('vcodec') == 'none']
        if not candidates:
            return None
        candidates.sort(key=lambda x: (1 if x.get('ext') == 'mp4' else 0, int(x.get('bitrate') or 0)), reverse=True)
        return candidates[0]

    def _get(self, url, **kwargs):
        headers = self.headers.copy()
        headers.update(kwargs.pop('headers', {}) or {})
        r = self.session.get(url, headers=headers, timeout=kwargs.pop('timeout', 15), **kwargs)
        r.raise_for_status()
        return r

    def _post_json(self, url, payload, headers=None):
        h = self.headers.copy()
        h.update({'Content-Type': 'application/json', 'Origin': 'https://www.youtube.com'})
        if headers:
            h.update({k: v for k, v in headers.items() if v})
        r = self.session.post(url, json=payload, headers=h, timeout=15)
        r.raise_for_status()
        return r.json()

    def _call_player_api(self, video_id, api_key, context, referer, visitor_data=None, sts=None, is_live=False):
        base_clients = [
            {'client': {'clientName': 'ANDROID_VR', 'clientVersion': '1.65.10', 'deviceMake': 'Oculus', 'deviceModel': 'Quest 3', 'androidSdkVersion': 32, 'userAgent': 'com.google.android.apps.youtube.vr.oculus/1.65.10 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip', 'osName': 'Android', 'osVersion': '12L', 'hl': 'en', 'gl': 'US'}},
            {'client': {'clientName': 'ANDROID', 'clientVersion': '21.02.35', 'androidSdkVersion': 30, 'userAgent': 'com.google.android.youtube/21.02.35 (Linux; U; Android 11) gzip', 'osName': 'Android', 'osVersion': '11', 'hl': 'en', 'gl': 'US'}},
            {'client': {'clientName': 'IOS', 'clientVersion': '21.02.3', 'deviceMake': 'Apple', 'deviceModel': 'iPhone16,2', 'userAgent': 'com.google.ios.youtube/21.02.3 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)', 'osName': 'iPhone', 'osVersion': '18.3.2.22D82', 'hl': 'en', 'gl': 'US'}},
            context,
            {'client': {'clientName': 'MWEB', 'clientVersion': '2.20260115.01.00', 'userAgent': 'Mozilla/5.0 (iPad; CPU OS 16_7_10 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1,gzip(gfe)', 'hl': 'en', 'gl': 'US'}},
        ]
        if is_live:
            clients = base_clients + [
                {'client': {'clientName': 'TVHTML5', 'clientVersion': '7.20240220.00.00', 'platform': 'TV', 'deviceMake': 'Google', 'deviceModel': 'Chromecast', 'hl': 'en', 'gl': 'US'}}
            ]
        else:
            clients = base_clients

        results = []
        fallback = None
        for ctx in clients:
            client_name = (ctx.get('client') or {}).get('clientName')
            try:
                url = f'https://www.youtube.com/youtubei/v1/player?key={api_key}&prettyPrint=false'
                payload = {
                    'context': ctx,
                    'videoId': video_id,
                    'playbackContext': {'contentPlaybackContext': {'html5Preference': 'HTML5_PREF_WANTS', **({'signatureTimestamp': sts} if sts else {})}},
                    'contentCheckOk': True,
                    'racyCheckOk': True,
                }
                client = ctx.get('client') or {}
                headers = {
                    'Referer': referer,
                    'X-YouTube-Client-Name': str(self._client_name_id(client.get('clientName'))),
                    'X-YouTube-Client-Version': client.get('clientVersion') or '',
                }
                if visitor_data:
                    headers['X-Goog-Visitor-Id'] = visitor_data
                client_ua = client.get('userAgent')
                if client_ua:
                    headers['User-Agent'] = client_ua
                data = self._post_json(url, payload, headers=headers)
                streaming = data.get('streamingData') or {}
                has_streaming = bool(streaming)
                if has_streaming:
                    data['_client_name'] = client_name
                    data['_client_ua'] = client_ua
                    results.append(data)
                if has_streaming and fallback is None:
                    fallback = data
                elif fallback is None:
                    fallback = data

                if not is_live and client_name == 'ANDROID_VR' and has_streaming:
                    formats = streaming.get('formats') or []
                    adaptive = streaming.get('adaptiveFormats') or []
                    direct_video = [x for x in adaptive if (x.get('url') or x.get('signatureCipher') or x.get('cipher')) and str(x.get('mimeType') or '').startswith('video/')]
                    if direct_video:
                        debug_log('player API fast return (vod)', {'client': client_name, 'direct_video': len(direct_video)})
                        return results
            except Exception as e:
                debug_log('API call error', {'client': client_name, 'error': repr(e)})
                continue
        return results or ([fallback] if fallback else [])

    def _normalize_format(self, fmt, player_url):
        media_url = fmt.get('url')
        if not media_url:
            cipher = fmt.get('signatureCipher') or fmt.get('cipher')
            if cipher:
                media_url = self._decrypt_signature_cipher(cipher, player_url)
        if not media_url:
            return None
        media_url = self._decrypt_nsig(media_url, player_url)
        mime = fmt.get('mimeType') or ''
        ext = 'mp4' if 'mp4' in mime else 'webm' if 'webm' in mime else 'unknown'
        codecs = self._search(r'codecs="([^"]+)"', mime) or ''
        has_audio = mime.startswith('audio/') or any(x in codecs for x in ('mp4a', 'opus', 'vorbis'))
        has_video = mime.startswith('video/') or any(x in codecs for x in ('avc', 'vp9', 'av01', 'h264'))
        headers = (fmt.get('http_headers') or {}).copy()
        if fmt.get('_client_ua'):
            headers['User-Agent'] = fmt.get('_client_ua')
        return {
            'itag': fmt.get('itag'),
            'url': media_url,
            'mimeType': mime,
            'client': fmt.get('_client_name'),
            'ext': ext,
            'width': fmt.get('width') or 0,
            'height': fmt.get('height') or 0,
            'fps': fmt.get('fps') or 0,
            'bitrate': fmt.get('bitrate') or fmt.get('averageBitrate') or 0,
            'contentLength': fmt.get('contentLength'),
            'initRange': fmt.get('initRange') or {},
            'indexRange': fmt.get('indexRange') or {},
            'codecs': codecs,
            'quality': fmt.get('qualityLabel') or fmt.get('quality'),
            'colorInfo': fmt.get('colorInfo') or {},
            'vcodec': codecs if has_video else 'none',
            'acodec': codecs if has_audio else 'none',
            'headers': headers,
        }

    def _decrypt_signature_cipher(self, cipher, player_url):
        data = parse_qs(cipher)
        media_url = unquote(data.get('url', [''])[0])
        sig = unquote(data.get('s', [''])[0])
        sp = data.get('sp', ['sig'])[0]
        if not media_url:
            return ''
        if sig:
            decoded = self._decrypt_sig(sig, player_url)
            sep = '&' if '?' in media_url else '?'
            media_url = f'{media_url}{sep}{sp}={quote(decoded)}'
        return media_url

    def _decrypt_sig(self, sig, player_url):
        cache_key = player_url or ''
        if cache_key in self.sig_plan_cache:
            plan = self.sig_plan_cache.get(cache_key)
        else:
            code = self._get_player_code(player_url)
            plan = self._extract_sig_plan(code)
            self.sig_plan_cache[cache_key] = plan
        if not plan:
            return sig
        arr = list(sig)
        for op, arg in plan:
            if op == 'reverse':
                arr.reverse()
            elif op in ('slice', 'splice'):
                arr = arr[int(arg):]
            elif op == 'swap' and arr:
                j = int(arg) % len(arr)
                arr[0], arr[j] = arr[j], arr[0]
        return ''.join(arr)

    def _decrypt_nsig(self, media_url, player_url):
        try:
            parsed = urlparse(media_url)
            query = parse_qs(parsed.query)
            n_value = query.get('n', [None])[0]
            if not n_value:
                return media_url
            path_match = re.search(r'/n/([^/]+)', parsed.path)
            if path_match and path_match.group(1) != n_value:
                new_path = parsed.path.replace(f"/n/{path_match.group(1)}", f"/n/{n_value}", 1)
                return urlunparse(parsed._replace(path=new_path))
            return media_url
        except Exception:
            return media_url

    def _get_player_code(self, player_url):
        if not player_url:
            return ''
        if player_url in self.player_cache:
            return self.player_cache[player_url]
        if player_url.startswith('//'):
            player_url = 'https:' + player_url
        elif player_url.startswith('/'):
            player_url = 'https://www.youtube.com' + player_url
        try:
            code = self._get(player_url).text
        except Exception:
            code = ''
        self.player_cache[player_url] = code
        return code

    def _extract_sig_plan(self, code):
        if not code:
            return None
        name = None
        for pattern in [
            r'\.sig\|\|([a-zA-Z0-9_$]+)\(',
            r'"signature",\s*([a-zA-Z0-9_$]+)\(',
            r'([a-zA-Z0-9_$]+)=function\(a\)\{a=a\.split\(""\);',
        ]:
            m = re.search(pattern, code)
            if m:
                name = m.group(1)
                break
        if not name:
            return None
        body = self._extract_js_function_body(code, name)
        if not body:
            return None
        helper = self._search(r'([a-zA-Z0-9_$]+)\.[a-zA-Z0-9_$]+\(a,\d+\)', body)
        helper_map = self._extract_helper_object(code, helper) if helper else {}
        plan = []
        for part in body.split(';'):
            if 'reverse()' in part:
                plan.append(('reverse', 0))
                continue
            m = re.search(r'\.slice\((\d+)\)', part)
            if m:
                plan.append(('slice', int(m.group(1))))
                continue
            m = re.search(r'\.splice\(0,(\d+)\)', part)
            if m:
                plan.append(('splice', int(m.group(1))))
                continue
            m = re.search(r'([a-zA-Z0-9_$]+)\.([a-zA-Z0-9_$]+)\(a,(\d+)\)', part)
            if m and m.group(1) == helper:
                op = helper_map.get(m.group(2))
                if op:
                    plan.append((op, int(m.group(3))))
        return plan or None

    def _extract_helper_object(self, code, name):
        if not name:
            return {}
        m = re.search(r'var\s+' + re.escape(name) + r'=\{(.+?)\};', code, re.S) or re.search(re.escape(name) + r'=\{(.+?)\};', code, re.S)
        if not m:
            return {}
        result = {}
        for method, body in re.findall(r'([a-zA-Z0-9_$]+):function\([a-z,]+\)\{(.*?)\}', m.group(1)):
            if '.reverse(' in body:
                result[method] = 'reverse'
            elif '.splice(' in body:
                result[method] = 'splice'
            elif '.slice(' in body:
                result[method] = 'slice'
            elif 'a[0]' in body and 'length' in body:
                result[method] = 'swap'
        return result

    def _extract_js_function_body(self, code, name):
        starts = []
        for pattern in [
            r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{',
            re.escape(name) + r'\s*=\s*function\s*\([^)]*\)\s*\{',
            r'var\s+' + re.escape(name) + r'\s*=\s*function\s*\([^)]*\)\s*\{',
        ]:
            m = re.search(pattern, code)
            if m:
                starts.append(m.end() - 1)
        if not starts:
            return ''
        start = starts[0]
        depth = 0
        in_str = None
        escape = False
        for i in range(start, len(code)):
            ch = code[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if in_str:
                if ch == in_str:
                    in_str = None
                continue
            if ch in ('"', "'", '`'):
                in_str = ch
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return code[start + 1:i]
        return ''

    def _extract_ytcfg(self, text):
        m = re.search(r'ytcfg\.set\s*\(\s*({.+?})\s*\)\s*;', text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except Exception:
            return None

    def _extract_initial_player_response(self, text):
        return self._extract_json_after(text, 'ytInitialPlayerResponse')

    def _extract_json_after(self, text, marker):
        pos = text.find(marker)
        if pos < 0:
            return None
        start = text.find('{', pos)
        if start < 0:
            return None
        depth = 0
        in_str = None
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if in_str:
                if ch == in_str:
                    in_str = None
                continue
            if ch == '"':
                in_str = ch
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:
                        return None
        return None

    def _extract_player_url(self, text):
        for pattern in [
            r'"jsUrl":"([^"]+)"',
            r'"PLAYER_JS_URL":"([^"]+)"',
            r'(/s/player/[^"\\]+/base\.js)',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1).replace('\\/', '/')
        return ''

    @staticmethod
    def _search(pattern, text, default=None):
        m = re.search(pattern, text or '', re.S)
        return m.group(1) if m else default

class Spider(Spider):
    def getName(self):
        return 'YouTube'

    def init(self, extend):
        try:
            self.extendDict = json.loads(extend) if extend else {}
        except Exception:
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
                proxy_url = f'http://{self.proxy_str}'
                self.session.proxies = {'http': proxy_url, 'https': proxy_url}

        self.header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://www.youtube.com/',
            'Cookie': 'CONSENT=YES+cb; SOCS=CAESEwgDEgk2MzgzMjY1MzkaAmVuIAEaBgiAo_CmBg',
        }
        # 支持用户自定义 Cookie
        cookie_val = self.extendDict.get('cookie')
        if cookie_val:
            self.header['Cookie'] = cookie_val
            debug_log('使用自定义 Cookie')

        self.session.headers.update(self.header)
        self.yt = YouTubeLite(self.session, self.header, self.extendDict)
        self.config = {}
        self.search_page_cache = {}
        self._cache = {}

        # ---- 加载 youtube.json 动态配置 ----
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
                    tid = item.get('type_id')
                    name = item.get('type_name')
                    if tid and name:
                        self.search_map[tid] = name
                debug_log('加载 youtube.json 成功', {'class_count': len(self.classes), 'filter_count': len(self.filters)})
            except Exception as e:
                debug_log('加载 youtube.json 失败', repr(e))
                self._fallback_hardcoded()
        else:
            debug_log('youtube.json 不存在，使用硬编码配置')
            self._fallback_hardcoded()

        # ---------- 强制增加直播相关关键词，提高命中率 ----------
        self.search_map['新闻直播'] = 'CCTV-4 直播 凤凰卫视 直播 中文台 直播 东方卫视 直播 深圳卫视 直播 新闻直播 直播'
        self.search_map['国际新闻'] = 'BBC News live CNN live Fox News live Al Jazeera live Sky News live France 24 live DW live 国际新闻 live'

    def _fallback_hardcoded(self):
        self.classes = [
            {'type_id': '新闻直播', 'type_name': '新闻直播'},
            {'type_id': '国际新闻', 'type_name': '国际新闻'},
            {'type_id': '动漫', 'type_name': '动漫'},
            {'type_id': '动画片', 'type_name': '动画片'},
            {'type_id': '综艺', 'type_name': '综艺'},
            {'type_id': '政论', 'type_name': '政论'},
            {'type_id': '港剧', 'type_name': '港剧'},
            {'type_id': '纪录片', 'type_name': '纪录片'},
            {'type_id': '短剧', 'type_name': '短剧'},
            {'type_id': '剧集', 'type_name': '剧集'},
            {'type_id': '4K', 'type_name': '4K'},
            {'type_id': 'HDR', 'type_name': 'HDR'},
            {'type_id': '自然', 'type_name': '自然'},
            {'type_id': '电影', 'type_name': '电影'},
            {'type_id': '放松', 'type_name': '放松'},
            {'type_id': '16K HDR', 'type_name': '16K HDR'},
            {'type_id': '科技', 'type_name': '科技'},
            {'type_id': '解说', 'type_name': '解说'},
            {'type_id': '体育', 'type_name': '体育'},
            {'type_id': '时尚潮流', 'type_name': '时尚潮流'},
            {'type_id': '科普知识', 'type_name': '科普知识'},
            {'type_id': '自媒体', 'type_name': '自媒体'},
            {'type_id': '音乐', 'type_name': '音乐'},
            {'type_id': '神秘', 'type_name': '神秘'},
        ]
        self.search_map = {
           '新闻直播': '新闻直播,新闻直播，新聞直播',
            '国际新闻': 'engkish news living,BBC News, Fox News ,Fox Business ,Bloomberg ,CNBC ,Sky News, CNN,france24 ,DW, Aljazeera,Asia news',
            '动漫': '一号动漫社 Animation Club,蒼穹動漫社Animation Club,斗破动漫社 Animation,腾讯动漫,爱奇艺动漫,优酷动漫,芒果动漫,Ani-Mi動漫迷動畫頻道,3D国漫工厂,阅文动漫,卡通狂欢嘉会',
            '综艺': '台視時光機,芒果综艺,腾讯综艺,爱奇艺综艺,优酷综艺,卫视综艺,超級夜總會',
            '政论': '觀點,豐富,Yahoo風向,全球大視野,環球大戰線,郭正亮頻道,論政天下,岑永康',
            '短剧': '短剧',
            '剧集': '腾讯剧集,爱奇艺剧集,优酷剧集,芒果剧集,八大劇樂部,民視戲劇,三立台劇,三立華劇,龍華戲劇,華視懷舊頻道,華視戲劇,中視經典戲劇',
             '纪录片': '亞洲旅遊台,CCTV纪录,CCTV科教,公視+,National Geographic,Kevin_YOLO,Nat Geo Animals,BBC Earth,Top Travel,National Geographic India,BBC Earth Science,历史纪录片,自然纪录片,宇宙纪录片',
            '港剧': 'TVB,亞視精選,ATV 亞洲電視',
            '4K': '4K',
             '动画片': '动画片',
           
             '4K': '4K',
            '动画片': '动画片',
            '港剧': '港剧',
            'HDR': 'HDR',
            '自然': '自然',
            '电影': '电影',
            '放松': '放松',
            '16K HDR': '16K HDR',
            '科技': '科技',
            '解说': '解说',
            '体育': '体育',
            '时尚潮流': '时尚潮流',
            '科普知识': '科普知识',
            '自媒体': '自媒体',
            '音乐': '音乐',
            '神秘': '神秘',
        }

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
        debug_log('categoryContent', {'cid': cid, 'query': query, 'page': page})
        videos, has_more = self._search_youtube_page(query, page)

        # 若为新闻直播或国际新闻，则只保留直播视频
        if cid in ('新闻直播', '国际新闻'):
            videos = [v for v in videos if v.get('is_live', False)]
            # 若过滤后为空，则没有更多页
            if not videos:
                has_more = False

        return {'list': videos, 'page': page, 'pagecount': page + 1 if has_more else page, 'limit': len(videos), 'total': len(videos)}

    def searchContent(self, key, quick, pg=1):
        page = int(pg)
        videos, has_more = self._search_youtube_page(key, page)
        return {'list': videos, 'page': page, 'pagecount': page + 1 if has_more else page, 'limit': len(videos), 'total': len(videos)}

    def detailContent(self, did):
        video_id = did[0]
        title = self._get_video_title(video_id)
        safe_title = self._safe_title(title)
        try:
            data = self.yt.extract(video_id)
            formats = data.get('formats', [])
            codec_groups = {}
            for fmt in formats:
                if fmt.get('vcodec') == 'none':
                    continue
                codec = fmt.get('codecs', '').lower()
                if 'avc' in codec or 'h264' in codec:
                    codec_type = 'h264'
                elif 'vp9' in codec or 'vp09' in codec:
                    codec_type = 'vp9'
                elif 'av01' in codec:
                    codec_type = 'av1'
                else:
                    codec_type = 'other'
                if codec_type not in codec_groups:
                    codec_groups[codec_type] = []
                codec_groups[codec_type].append(fmt)
            
            play_sources = []
            play_urls = []
            for codec_type, fmt_list in codec_groups.items():
                fmt_list.sort(key=lambda x: int(x.get('height') or 0), reverse=True)
                best = fmt_list[0]
                height = int(best.get('height') or 0)
                is_hdr = self.yt._is_hdr_video(best)
                kind = 'HDR' if is_hdr else 'SDR'
                codec_name = codec_type.upper()
                name = f'{height}p {codec_name} {kind}' if height else f'{codec_name} {kind}'
                quality = 'hdr' if is_hdr else 'best'
                play_sources.append(name)
                play_urls.append(f'{safe_title} {name}${video_id}@{quality}_{codec_type}')
        except Exception as e:
            debug_log('detail error', repr(e))
            play_sources = ['SDR', 'HDR']
            play_urls = [
                f'{safe_title} SDR${video_id}@best_h264',
                f'{safe_title} HDR${video_id}@hdr_h264',
            ]
        vod = {
            'vod_id': video_id,
            'vod_name': title,
            'vod_pic': f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg',
            'vod_play_from': '$$$'.join(play_sources),
            'vod_play_url': '$$$'.join(play_urls)
        }
        return {'list': [vod]}

    def playerContent(self, flag, pid, vipFlags):
        raw_pid = pid.split('$')[-1]
        if '@' in raw_pid:
            parts = raw_pid.rsplit('@', 1)
            video_id, quality_codec = parts[0], parts[1]
            if '_' in quality_codec:
                quality, codec_type = quality_codec.split('_', 1)
            else:
                quality = quality_codec
                codec_type = None
        else:
            video_id, quality = raw_pid, 'best'
            codec_type = None
        if quality not in ('best', 'hdr', '4k', '2k', '1080p'):
            quality = 'best'
        try:
            data = self.yt.extract(video_id)

            manifest = data.get('live_manifest')
            if manifest and (manifest.get('hls') or manifest.get('dash')):
                url = manifest.get('hls') or manifest.get('dash')
                if url:
                    debug_log('直播 manifest 返回', {'url': url, 'protocol': 'HLS' if url.endswith('.m3u8') else 'DASH'})
                    # 直播也通过代理，避免前端处理 cookie
                    cache_key = f'yt_live_{video_id}'
                    self.setCache(cache_key, {
                        'url': url,
                        'headers': self.header.copy(),
                        'expires': time.time() + 300,
                    })
                    return {
                        'parse': 0, 'jx': 0,
                        'url': f'http://127.0.0.1:9978/proxy?do=py&type=single&vid={video_id}&quality=live',
                        'format': 'application/vnd.apple.mpegurl' if url.endswith('.m3u8') else 'application/dash+xml'
                    }

            debug_log('点播处理', {'video_id': video_id, 'quality': quality, 'codec': codec_type})
            all_tracks = self.yt.choose_video_tracks(data['formats'], 'best', codec_filter=codec_type)
            wanted_name = 'HDR' if quality == 'hdr' else 'SDR'
            video_tracks = [x for x in all_tracks if x.get('track_name') == wanted_name]
            if not video_tracks and all_tracks:
                video_tracks = [all_tracks[0]]
            if video_tracks:
                audio = self.yt.choose_audio(data['formats'])
                if audio:
                    cache_key = f'yt_{video_id}_{quality}_{codec_type}'
                    self.setCache(cache_key, {
                        'video_tracks': video_tracks,
                        'video_url': video_tracks[0]['url'],
                        'audio_url': audio['url'],
                        'video_item': video_tracks[0],
                        'audio_item': audio,
                        'duration': data.get('duration') or 0,
                        'expires': time.time() + 300,
                    })
                    debug_log('点播使用 MPD 代理（分离音视频）', {
                        'video_itag': video_tracks[0].get('itag'),
                        'video_height': video_tracks[0].get('height'),
                        'codec': codec_type,
                        'audio_itag': audio.get('itag')
                    })
                    return {
                        'parse': 0, 'jx': 0,
                        'url': f'http://127.0.0.1:9978/proxy?do=py&type=mpd&vid={video_id}&quality={quality}_{codec_type}',
                        'format': 'application/dash+xml'
                    }
                else:
                    # 只有视频无音频 → 单文件代理
                    playable = video_tracks[0]
                    cache_key = f'yt_single_{video_id}_{quality}_{codec_type}'
                    self.setCache(cache_key, {
                        'url': playable['url'],
                        'headers': playable.get('headers', {}),
                        'expires': time.time() + 300,
                    })
                    return {
                        'parse': 0, 'jx': 0,
                        'url': f'http://127.0.0.1:9978/proxy?do=py&type=single&vid={video_id}&quality={quality}_{codec_type}',
                    }
            # 若没有 video_tracks，则取渐进式
            progressives = [x for x in data['formats'] if x.get('vcodec') != 'none' and x.get('acodec') != 'none']
            if progressives:
                progressives.sort(key=lambda x: (int(x.get('height') or 0), int(x.get('bitrate') or 0)), reverse=True)
                playable = progressives[0]
                cache_key = f'yt_single_{video_id}_{quality}_{codec_type}'
                self.setCache(cache_key, {
                    'url': playable['url'],
                    'headers': playable.get('headers', {}),
                    'expires': time.time() + 300,
                })
                return {
                    'parse': 0, 'jx': 0,
                    'url': f'http://127.0.0.1:9978/proxy?do=py&type=single&vid={video_id}&quality={quality}_{codec_type}',
                }
            raise Exception('没有可播放的流')
        except Exception as e:
            debug_log('playerContent error', repr(e))
            # 降级为嵌入页面，不再传递 header 以避免百度 Cookie 格式错误
            res = {'parse': 1, 'url': f'https://www.youtube.com/embed/{video_id}?autoplay=1'}
            if self.proxy_str:
                res['proxy'] = self.proxy_str
            return res

    def localProxy(self, params):
        if params.get('do') != 'py':
            return None
        if params.get('type') == 'mpd':
            return self._proxy_mpd(params)
        if params.get('type') == 'media':
            return self._proxy_media(params)
        if params.get('type') == 'single':
            return self._proxy_single(params)
        return None

    # ---------- 缓存刷新方法 ----------
    def _refresh_cache(self, vid, quality_codec):
        """重新提取视频信息并更新缓存（MPD 用）"""
        try:
            data = self.yt.extract(vid)
            if '_' in quality_codec:
                quality, codec_type = quality_codec.split('_', 1)
            else:
                quality = quality_codec
                codec_type = None
            all_tracks = self.yt.choose_video_tracks(data['formats'], 'best', codec_filter=codec_type)
            wanted_name = 'HDR' if quality == 'hdr' else 'SDR'
            video_tracks = [x for x in all_tracks if x.get('track_name') == wanted_name]
            if not video_tracks and all_tracks:
                video_tracks = [all_tracks[0]]
            audio = self.yt.choose_audio(data['formats'])
            if not video_tracks:
                return None
            cache_data = {
                'video_tracks': video_tracks,
                'video_url': video_tracks[0]['url'],
                'audio_url': audio['url'] if audio else None,
                'video_item': video_tracks[0],
                'audio_item': audio or {},
                'duration': data.get('duration') or 0,
                'expires': time.time() + 300,
            }
            cache_key = f'yt_{vid}_{quality}_{codec_type}'
            self.setCache(cache_key, cache_data)
            debug_log('MPD缓存刷新成功', {'vid': vid, 'quality': quality_codec})
            return cache_data
        except Exception as e:
            debug_log('刷新MPD缓存失败', repr(e))
            return None

    def _refresh_single_cache(self, vid, quality_codec):
        """重新提取视频信息并更新单文件缓存"""
        try:
            data = self.yt.extract(vid)
            # 优先取渐进式
            progressives = [x for x in data['formats'] if x.get('vcodec') != 'none' and x.get('acodec') != 'none']
            if progressives:
                progressives.sort(key=lambda x: (int(x.get('height') or 0), int(x.get('bitrate') or 0)), reverse=True)
                playable = progressives[0]
            else:
                # 无渐进式，取视频 track 中第一个
                tracks = self.yt.choose_video_tracks(data['formats'], 'best')
                if not tracks:
                    return None
                playable = tracks[0]
            cache_data = {
                'url': playable['url'],
                'headers': playable.get('headers', {}),
                'expires': time.time() + 300,
            }
            cache_key = f'yt_single_{vid}_{quality_codec}'
            self.setCache(cache_key, cache_data)
            debug_log('单文件缓存刷新成功', {'vid': vid, 'quality': quality_codec})
            return cache_data
        except Exception as e:
            debug_log('刷新单文件缓存失败', repr(e))
            return None

    # ---------- 代理实现 ----------
    def _proxy_single(self, params):
        vid = params.get('vid')
        quality_codec = params.get('quality') or 'best_h264'
        # 如果是直播，尝试从缓存获取
        if quality_codec == 'live':
            cache_key = f'yt_live_{vid}'
            data = self.getCache(cache_key)
            if not data:
                return [404, 'text/plain', '直播缓存不存在']
            target_url = data.get('url')
            headers = self.header.copy()
            headers.pop('Cookie', None)  # 由 session 携带
            range_header = params.get('range') or params.get('Range')
            if range_header:
                headers['Range'] = range_header
            try:
                r = self.session.get(target_url, headers=headers, stream=True, timeout=30)
                content_type = r.headers.get('content-type', 'application/vnd.apple.mpegurl')
                resp_headers = {
                    'Content-Type': content_type,
                    'Accept-Ranges': 'bytes',
                    'Cache-Control': 'no-cache',
                }
                if r.headers.get('content-range'):
                    resp_headers['Content-Range'] = r.headers.get('content-range')
                if r.headers.get('content-length'):
                    resp_headers['Content-Length'] = r.headers.get('content-length')
                return [r.status_code, content_type, r.content, resp_headers]
            except Exception as e:
                return [500, 'text/plain', f'直播代理失败: {str(e)}']

        # 普通点播单文件
        cache_key = f'yt_single_{vid}_{quality_codec}'
        data = self.getCache(cache_key)
        if not data:
            data = self._refresh_single_cache(vid, quality_codec)
        if not data:
            return [404, 'text/plain', '播放缓存已过期且刷新失败']
        target_url = data.get('url')
        if not target_url:
            return [404, 'text/plain', '播放地址不存在']
        headers = self.header.copy()
        headers.pop('Cookie', None)  # session 自带
        if data.get('headers'):
            headers.update(data['headers'])
        range_header = params.get('range') or params.get('Range')
        if range_header:
            headers['Range'] = range_header
        try:
            r = self.session.get(target_url, headers=headers, stream=True, timeout=30)
            content_type = r.headers.get('content-type', 'video/mp4')
            resp_headers = {
                'Content-Type': content_type,
                'Accept-Ranges': 'bytes',
                'Cache-Control': 'no-cache',
            }
            if r.headers.get('content-range'):
                resp_headers['Content-Range'] = r.headers.get('content-range')
            if r.headers.get('content-length'):
                resp_headers['Content-Length'] = r.headers.get('content-length')
            return [r.status_code, content_type, r.content, resp_headers]
        except Exception as e:
            return [500, 'text/plain', f'代理播放失败: {str(e)}']

    def _proxy_mpd(self, params):
        vid = params.get('vid')
        quality_codec = params.get('quality') or '1080p_h264'
        if '_' in quality_codec:
            quality, codec_type = quality_codec.split('_', 1)
        else:
            quality = quality_codec
            codec_type = None
        data = self.getCache(f'yt_{vid}_{quality}_{codec_type}') if vid else None
        if not data:
            data = self._refresh_cache(vid, quality_codec)
        if not data:
            return [404, 'text/plain', '视频缓存已过期且刷新失败']
        audio_url = data.get('audio_url')
        duration = data.get('duration') or 0
        video_tracks = data.get('video_tracks') or [data.get('video_item') or {}]
        audio_item = data.get('audio_item') or {}
        media_base = f'http://127.0.0.1:9978/proxy?do=py&type=media&vid={vid}&quality={quality}_{codec_type}'
        direct_segments = str(self.extendDict.get('seg') or 'proxy').lower() == 'direct'
        duration_pt = f"PT{int(duration or 0)}S"
        mpd = f'''<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="{duration_pt}" minBufferTime="PT90S" profiles="urn:mpeg:dash:profile:isoff-on-demand:2011">
  <Period id="1" start="PT0S">
'''
        for item in video_tracks:
            init_range = item.get('initRange') or {}
            index_range = item.get('indexRange') or {}
            base_url = item.get('url') if direct_segments else media_base + f"&track=video&itag={item.get('itag')}"
            mpd += f'''    <AdaptationSet mimeType="{html.escape((item.get('mimeType') or 'video/webm').split(';')[0])}" startWithSAP="1" segmentAlignment="true" scanType="progressive">
      <Representation id="v{item.get('itag', 1)}" bandwidth="{item.get('bitrate', 1000000)}" codecs="{html.escape(item.get('codecs') or '')}" height="{item.get('height', 0)}" width="{item.get('width', 0)}">
        <BaseURL>{html.escape(base_url)}</BaseURL>
        <SegmentBase indexRange="{index_range.get('start', '0')}-{index_range.get('end', '0')}"><Initialization range="{init_range.get('start', '0')}-{init_range.get('end', '0')}"/></SegmentBase>
      </Representation>
    </AdaptationSet>
'''
        if audio_url:
            audio_init = audio_item.get('initRange') or {}
            audio_index = audio_item.get('indexRange') or {}
            audio_base = audio_url if direct_segments else media_base + '&track=audio'
            mpd += f'''    <AdaptationSet mimeType="{html.escape((audio_item.get('mimeType') or 'audio/mp4').split(';')[0])}" startWithSAP="1" segmentAlignment="true" lang="und">
      <Representation id="audio" bandwidth="{audio_item.get('bitrate', 128000)}" codecs="{html.escape(audio_item.get('codecs') or '')}" audioSamplingRate="44100">
        <BaseURL>{html.escape(audio_base)}</BaseURL>
        <SegmentBase indexRange="{audio_index.get('start', '0')}-{audio_index.get('end', '0')}"><Initialization range="{audio_init.get('start', '0')}-{audio_init.get('end', '0')}"/></SegmentBase>
      </Representation>
    </AdaptationSet>
'''
        mpd += '  </Period>\n</MPD>'
        return [200, 'application/dash+xml', mpd]

    def _proxy_media(self, params):
        vid = params.get('vid')
        quality_codec = params.get('quality') or '1080p_h264'
        if '_' in quality_codec:
            quality, codec_type = quality_codec.split('_', 1)
        else:
            quality = quality_codec
            codec_type = None
        track = params.get('track')
        data = self.getCache(f'yt_{vid}_{quality}_{codec_type}') if vid else None
        if not data:
            data = self._refresh_cache(vid, quality_codec)
        if not data or track not in ('video', 'audio'):
            return [404, 'text/plain', '媒体不存在或刷新失败']
        if track == 'video':
            wanted_itag = str(params.get('itag') or '')
            tracks = data.get('video_tracks') or [data.get('video_item') or {}]
            media_item = next((x for x in tracks if str(x.get('itag')) == wanted_itag), tracks[0] if tracks else {})
            target_url = media_item.get('url')
        else:
            media_item = data.get('audio_item') or {}
            target_url = data.get('audio_url') or media_item.get('url')
        if not target_url:
            return [404, 'text/plain', f'{track} 流不存在']
        headers = self.header.copy()
        headers.pop('Cookie', None)
        headers.update(media_item.get('headers') or {})
        range_header = params.get('range') or params.get('Range')
        if range_header:
            headers['Range'] = range_header
        try:
            r = self.session.get(target_url, headers=headers, stream=True, timeout=30)
            content_type = r.headers.get('content-type', 'application/octet-stream')
            resp_headers = {'Content-Type': content_type, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-cache'}
            if r.headers.get('content-range'):
                resp_headers['Content-Range'] = r.headers.get('content-range')
            if r.headers.get('content-length'):
                resp_headers['Content-Length'] = r.headers.get('content-length')
            return [r.status_code, content_type, r.content, resp_headers]
        except Exception as e:
            return [500, 'text/plain', f'代理媒体失败: {str(e)}']

    # ---------- 搜索相关 ----------
    def _normalize_category_id(self, cid):
        raw = str(cid or '').strip()
        return CATEGORY_ALIASES.get(raw, raw)

    def _normalize_filter_term(self, value):
        if isinstance(value, (list, tuple)):
            return ' '.join([self._normalize_filter_term(item) for item in value if item])
        if isinstance(value, dict):
            return ' '.join([self._normalize_filter_term(item) for item in value.values() if item])
        return re.sub(r'\s+', ' ', str(value or '')).strip()[:180]

    def _build_category_keyword(self, cid, filters=None):
        category_id = self._normalize_category_id(cid)
        terms = []
        base = self.search_map.get(cid) or self.search_map.get(category_id) or category_id or str(cid or '').strip()
        if base:
            terms.append(base)
        if isinstance(filters, dict):
            for fkey, value in filters.items():
                if fkey == 'year':
                    yr = str(value or '').strip()
                    if yr:
                        terms.append(yr)
                else:
                    term = self._normalize_filter_term(value)
                    if term:
                        terms.append(term)
        seen = set()
        output = []
        for term in terms:
            term = term.strip()
            if term and term not in seen:
                seen.add(term)
                output.append(term)
        return ' '.join(output)

    def _search_cache_key(self, key):
        return re.sub(r'\s+', ' ', str(key or '')).strip().lower()

    def _search_youtube_page(self, key, page=1):
        page = max(1, int(page or 1))
        cache_key = self._search_cache_key(key)
        session = self.search_page_cache.get(cache_key)
        if page == 1 or not session:
            session = self._fetch_search_first_page(key)
            self.search_page_cache[cache_key] = session
        while len(session.get('pages', [])) < page and session.get('next'):
            data = self._fetch_search_continuation(session)
            videos = self._extract_videos_from_api(data, 30)
            session.setdefault('pages', []).append(videos)
            session['next'] = self._extract_continuation_token(data)
        pages = session.get('pages', [])
        videos = pages[page - 1] if len(pages) >= page else []
        has_more = bool(session.get('next')) or len(pages) > page
        return videos, has_more

    def _fetch_search_first_page(self, key):
        search_url = f'https://www.youtube.com/results?search_query={quote(str(key or ""))}'
        debug_log('fetch search page', {'url': search_url, 'key': key})
        r = self.session.get(search_url, timeout=15)
        html_str = r.text
        debug_log('search page response', {'status': r.status_code, 'length': len(html_str), 'has_ytInitialData': 'ytInitialData' in html_str})
        data = self.yt._extract_json_after(html_str, 'ytInitialData') or {}
        ytcfg = self.yt._extract_ytcfg(html_str) or {}
        api_key = ytcfg.get('INNERTUBE_API_KEY') or self.yt._search(r'"INNERTUBE_API_KEY":"([^"]+)"', html_str)
        context = ytcfg.get('INNERTUBE_CONTEXT') or {'client': {'clientName': 'WEB', 'clientVersion': '2.20240310.01.00', 'hl': 'zh-CN', 'gl': 'US'}}
        client = context.get('client') or {}
        videos = self._extract_videos_from_api(data, 30)
        debug_log('search page parsed', {'api_key': bool(api_key), 'videos': len(videos)})
        return {
            'key': key,
            'api_key': api_key,
            'context': context,
            'client_name': client.get('clientName') or 'WEB',
            'client_version': client.get('clientVersion') or '2.20240310.01.00',
            'referer': search_url,
            'pages': [videos],
            'next': self._extract_continuation_token(data),
        }

    def _fetch_search_continuation(self, session):
        token = session.get('next')
        api_key = session.get('api_key')
        if not token or not api_key:
            return {}
        url = f'https://www.youtube.com/youtubei/v1/search?key={quote(api_key)}'
        headers = self.header.copy()
        headers.update({
            'Content-Type': 'application/json',
            'Origin': 'https://www.youtube.com',
            'Referer': session.get('referer') or 'https://www.youtube.com/',
            'X-YouTube-Client-Name': str(self.yt._client_name_id(session.get('client_name'))),
            'X-YouTube-Client-Version': session.get('client_version') or '2.20240310.01.00',
        })
        payload = {'context': session.get('context') or {}, 'continuation': token}
        r = self.session.post(url, json=payload, headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()

    def _extract_continuation_token(self, data):
        tokens = []
        def scan(obj):
            if isinstance(obj, dict):
                endpoint = obj.get('continuationEndpoint') or {}
                token = endpoint.get('continuationCommand', {}).get('token')
                if token:
                    tokens.append(token)
                renderer = obj.get('continuationItemRenderer') or {}
                token = renderer.get('continuationEndpoint', {}).get('continuationCommand', {}).get('token')
                if token:
                    tokens.append(token)
                for value in obj.values():
                    scan(value)
            elif isinstance(obj, list):
                for value in obj:
                    scan(value)
        scan(data)
        return tokens[0] if tokens else ''

    def _extract_videos_from_api(self, data, limit=30):
        videos = []
        seen = set()
        def scan(obj):
            if len(videos) >= limit:
                return
            if isinstance(obj, dict):
                for key in ('videoRenderer', 'compactVideoRenderer', 'gridVideoRenderer', 'reelItemRenderer'):
                    if key in obj:
                        item = self._parse_renderer(obj[key])
                        if item and item['vod_id'] not in seen:
                            seen.add(item['vod_id'])
                            videos.append(item)
                for value in obj.values():
                    scan(value)
            elif isinstance(obj, list):
                for value in obj:
                    scan(value)
        scan(data)
        return videos[:limit]

    def _parse_renderer(self, renderer):
        try:
            vid = renderer.get('videoId')
            if not vid:
                nav = renderer.get('navigationEndpoint') or {}
                vid = (nav.get('watchEndpoint') or {}).get('videoId')
            if not vid:
                return None
            title_obj = renderer.get('title') or renderer.get('headline') or {}
            title = title_obj.get('simpleText') or ''.join([x.get('text', '') for x in title_obj.get('runs', [])]) or 'YouTube Video'
            dur = (renderer.get('lengthText') or {}).get('simpleText') or 'YouTube'

            # 检测是否为直播
            is_live = False
            badges = renderer.get('badges') or []
            for badge in badges:
                badge_renderer = badge.get('metadataBadgeRenderer') or {}
                style = badge_renderer.get('style', '')
                label = badge_renderer.get('label', '')
                if 'LIVE' in style or 'LIVE' in label.upper():
                    is_live = True
                    break

            return {
                'vod_id': vid,
                'vod_name': html.unescape(title),
                'vod_pic': f'https://img.youtube.com/vi/{vid}/hqdefault.jpg',
                'vod_remarks': dur,
                'is_live': is_live   # 新增直播标记
            }
        except Exception:
            return None

    def _get_video_title(self, vid):
        try:
            r = self.session.get(f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json', timeout=5)
            return r.json().get('title') or vid
        except Exception:
            return vid

    def _safe_title(self, title):
        if not title:
            return 'video'
        return re.sub(r'[#$@%&!?*|\\/:<>]', ' ', title)[:60]

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass