#coding=utf-8
#!/usr/bin/python
"""
YouTube 插件 - 基于 yt-dlp 核心逻辑重构
支持:
- 多客户端 (WEB, ANDROID, IOS, TVHTML5 等)
- 动态签名解密 (增强 JS 解释器)
- 直播流自动续期
- 自适应格式选择
- 缓存优化
"""
import re
import os
import sys
import json
import html
import time
import hashlib
from urllib.parse import quote, unquote, parse_qs, urlparse, urlunparse
import requests
from base.spider import Spider
sys.path.append('..')

DEBUG_LOG = '/sdcard/Download/0714youtube_trace.log'

# ========== 全局辅助 ==========
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

# ========== 增强 JS 解释器 (仿 yt-dlp) ==========
class JSInterpreter:
    """模拟执行简单的 JavaScript 函数，用于解密签名和 n 参数"""
    def __init__(self, code, func_name):
        self.code = code
        self.func_name = func_name
        self.functions = {}
        self._extract_functions()

    def _extract_functions(self):
        # 提取主解密函数
        pattern = r'function\s+' + re.escape(self.func_name) + r'\s*\(([^)]*)\)\s*\{([^}]*)\}'
        match = re.search(pattern, self.code, re.S)
        if match:
            args_str, body = match.groups()
            self.functions[self.func_name] = {
                'args': [a.strip() for a in args_str.split(',') if a.strip()],
                'body': body
            }
        # 提取辅助对象 { method: function(...) { ... } }
        helper_pattern = r'var\s+([a-zA-Z0-9_$]+)\s*=\s*\{([^}]*)\};'
        for m in re.finditer(helper_pattern, self.code, re.S):
            obj_name, obj_body = m.groups()
            for method_match in re.finditer(r'([a-zA-Z0-9_$]+)\s*:\s*function\s*\(([^)]*)\)\s*\{([^}]*)\}', obj_body):
                m_name, m_args, m_body = method_match.groups()
                self.functions[m_name] = {
                    'args': [a.strip() for a in m_args.split(',') if a.strip()],
                    'body': m_body
                }

    def call(self, func_name, args):
        func = self.functions.get(func_name)
        if not func:
            raise Exception(f'Function {func_name} not found')
        # 构建变量环境
        env = {}
        # 绑定参数
        for i, arg in enumerate(func['args']):
            if i < len(args):
                env[arg] = args[i]
            else:
                env[arg] = None
        # 执行 body
        body = func['body']
        # 按语句分割（简单处理）
        statements = self._split_statements(body)
        for stmt in statements:
            stmt = stmt.strip()
            if not stmt:
                continue
            self._execute_statement(stmt, env)
        # 返回值：通常为第一个参数（如 'a'）或显式 return
        if 'a' in env:
            return env['a']
        return args[0] if args else None

    def _split_statements(self, body):
        # 简单分割，忽略字符串中的分号
        statements = []
        current = []
        in_string = False
        escape = False
        for ch in body:
            if escape:
                current.append(ch)
                escape = False
                continue
            if ch == '\\':
                current.append(ch)
                escape = True
                continue
            if ch == '"' or ch == "'":
                in_string = not in_string
                current.append(ch)
                continue
            if not in_string and ch == ';':
                statements.append(''.join(current))
                current = []
            else:
                current.append(ch)
        if current:
            statements.append(''.join(current))
        return statements

    def _execute_statement(self, stmt, env):
        # 处理 var x = ... 
        var_match = re.match(r'var\s+([a-zA-Z0-9_$]+)\s*=\s*(.+)$', stmt)
        if var_match:
            var_name, expr = var_match.groups()
            env[var_name] = self._evaluate_expression(expr.strip(), env)
            return
        # 处理赋值 a = ...
        assign_match = re.match(r'([a-zA-Z0-9_$]+)\s*=\s*(.+)$', stmt)
        if assign_match:
            var_name, expr = assign_match.groups()
            if var_name in env:
                env[var_name] = self._evaluate_expression(expr.strip(), env)
            return
        # 处理函数调用，如 helper.method(a, 5)
        call_match = re.match(r'([a-zA-Z0-9_$]+)\.([a-zA-Z0-9_$]+)\(([^)]*)\)', stmt)
        if call_match:
            obj, method, params = call_match.groups()
            if obj in env:
                # 解析参数
                param_list = [p.strip() for p in params.split(',') if p.strip()]
                resolved = []
                for p in param_list:
                    if p in env:
                        resolved.append(env[p])
                    else:
                        # 尝试数字或字符串
                        if p.startswith('"') or p.startswith("'"):
                            resolved.append(p[1:-1])
                        else:
                            try:
                                resolved.append(int(p))
                            except:
                                resolved.append(p)
                # 调用辅助函数（可能是本类中的函数）
                if method in self.functions:
                    result = self.call(method, resolved)
                    # 如果方法名为 'method' 之类的，结果可能影响 env
                    # 这里简单处理：若方法返回非空，赋给调用对象
                    if result is not None:
                        env[obj] = result
                elif method in env:
                    # 如果 method 是变量？
                    pass
            return
        # 处理简单表达式，如 a.reverse()
        method_match = re.match(r'([a-zA-Z0-9_$]+)\.([a-zA-Z0-9_$]+)\(\)', stmt)
        if method_match:
            obj, method = method_match.groups()
            if obj in env:
                if method == 'reverse':
                    if isinstance(env[obj], list):
                        env[obj].reverse()
                    elif isinstance(env[obj], str):
                        env[obj] = env[obj][::-1]
                elif method == 'pop':
                    if isinstance(env[obj], list):
                        env[obj].pop()
            return
        # 处理 slice/splice 等
        slice_match = re.match(r'([a-zA-Z0-9_$]+)\s*=\s*([a-zA-Z0-9_$]+)\.slice\((\d+)\)', stmt)
        if slice_match:
            target, source, num = slice_match.groups()
            if source in env:
                env[target] = env[source][int(num):]
            return
        splice_match = re.match(r'([a-zA-Z0-9_$]+)\s*=\s*([a-zA-Z0-9_$]+)\.splice\(0,\s*(\d+)\)', stmt)
        if splice_match:
            target, source, num = splice_match.groups()
            if source in env:
                env[target] = env[source][int(num):]
            return

    def _evaluate_expression(self, expr, env):
        # 处理 .split('') 等
        split_match = re.match(r'([a-zA-Z0-9_$]+)\.split\(([^)]*)\)', expr)
        if split_match:
            var, sep = split_match.groups()
            if var in env:
                sep = sep.strip()
                if sep.startswith('"') or sep.startswith("'"):
                    sep = sep[1:-1]
                return env[var].split(sep)
        # 处理字符串或数字
        if expr.startswith('"') or expr.startswith("'"):
            return expr[1:-1]
        try:
            return int(expr)
        except:
            pass
        if expr in env:
            return env[expr]
        return expr

# ========== YouTube 提取核心 (基于 yt-dlp) ==========
class YouTubeIE:
    def __init__(self, session, headers, config):
        self.session = session
        self.headers = headers
        self.config = config
        self.extract_cache = {}
        self.sig_cache = {}
        self.player_cache = {}
        self.expire_threshold = 60

    def extract(self, video_id):
        cache_key = f'extract_{video_id}'
        now = time.time()
        cached = self.extract_cache.get(cache_key)
        if cached and cached.get('expires', 0) > now:
            debug_log('extract cache hit', {'video_id': video_id})
            return cached['data']

        watch_url = f'https://www.youtube.com/watch?v={video_id}'
        page = self._fetch_page(watch_url)
        ytcfg, player_response, player_url = self._parse_page(page)
        api_key = ytcfg.get('INNERTUBE_API_KEY')
        visitor_data = ytcfg.get('VISITOR_DATA')

        is_live = False
        if player_response:
            video_details = player_response.get('videoDetails', {})
            is_live = video_details.get('isLive') or video_details.get('isLiveContent') or False

        responses = [player_response] if player_response else []
        if api_key:
            api_responses = self._call_player_api(video_id, api_key, ytcfg.get('INNERTUBE_CONTEXT'), watch_url, visitor_data, is_live)
            responses.extend(api_responses)

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
                    # 去重
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
        if pos < 0:
            return None
        start = html.find('{', pos)
        if start < 0:
            return None
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
        ]
        for p in patterns:
            m = re.search(p, html)
            if m:
                return m.group(1).replace('\\/', '/')
        return ''

    def _call_player_api(self, video_id, api_key, context, referer, visitor_data, is_live):
        clients = [
            {'name': 'ANDROID_VR', 'version': '1.65.10', 'ua': 'com.google.android.apps.youtube.vr.oculus/1.65.10 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip'},
            {'name': 'ANDROID', 'version': '21.02.35', 'ua': 'com.google.android.youtube/21.02.35 (Linux; U; Android 11) gzip'},
            {'name': 'IOS', 'version': '21.02.3', 'ua': 'com.google.ios.youtube/21.02.3 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X)'},
            {'name': 'MWEB', 'version': '2.20260115.01.00', 'ua': 'Mozilla/5.0 (iPad; CPU OS 16_7_10 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1,gzip(gfe)'},
        ]
        if is_live:
            clients.append({'name': 'TVHTML5', 'version': '7.20240220.00.00', 'ua': 'Mozilla/5.0 (Chromecast)'})

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
            except Exception as e:
                debug_log(f'API call error for {client["name"]}', repr(e))
                continue
        return results

    def _client_name_id(self, name):
        mapping = {
            'WEB': 1, 'MWEB': 2, 'ANDROID': 3, 'IOS': 5, 'TVHTML5': 7,
            'ANDROID_VR': 28, 'WEB_EMBEDDED_PLAYER': 56, 'WEB_REMIX': 67,
        }
        return mapping.get(name, 1)

    # ---------- 核心解密方法 ----------
    def _normalize_format(self, fmt, player_url):
        url = fmt.get('url')
        if not url:
            cipher = fmt.get('signatureCipher') or fmt.get('cipher')
            if cipher:
                url = self._decrypt_signature(cipher, player_url)
        if not url:
            return None
        # 解密 n 参数
        url = self._decrypt_nsig(url, player_url)
        if not url:
            return None

        mime = fmt.get('mimeType', '')
        codecs = re.search(r'codecs="([^"]+)"', mime)
        codecs = codecs.group(1) if codecs else ''
        has_video = mime.startswith('video/') or any(x in codecs for x in ('avc', 'vp9', 'av01', 'h264'))
        has_audio = mime.startswith('audio/') or any(x in codecs for x in ('mp4a', 'opus', 'vorbis'))
        return {
            'itag': fmt.get('itag'),
            'url': url,
            'mimeType': mime,
            'ext': 'mp4' if 'mp4' in mime else 'webm' if 'webm' in mime else 'unknown',
            'width': fmt.get('width', 0),
            'height': fmt.get('height', 0),
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
        # 解密 s
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
        # 提取解密函数名
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
        except Exception as e:
            debug_log('sig decrypt failed', repr(e))
            return sig

    def _decrypt_nsig(self, url, player_url):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        n = query.get('n', [None])[0]
        if not n:
            return url
        # 获取 player JS
        js_code = self._get_player_code(player_url)
        if not js_code:
            return url
        # 提取 n 解密函数名
        func_name = None
        # yt-dlp 常见模式
        patterns = [
            r'\b([a-zA-Z0-9_$]+)\s*=\s*function\s*\(a\)\s*\{.*?\.n\s*=',
            r'"n",\s*([a-zA-Z0-9_$]+)\(',
        ]
        for p in patterns:
            m = re.search(p, js_code)
            if m:
                func_name = m.group(1)
                break
        if not func_name:
            # 尝试直接查找 n 函数
            m = re.search(r'function\s+([a-zA-Z0-9_$]+)\s*\(a\)\s*\{.*?\.n\s*=', js_code, re.S)
            if m:
                func_name = m.group(1)
        if not func_name:
            return url
        try:
            interp = JSInterpreter(js_code, func_name)
            decoded = interp.call(func_name, [n])
            if decoded and decoded != n:
                # 替换 n 参数
                new_query = query.copy()
                new_query['n'] = [decoded]
                new_parsed = parsed._replace(query=urlencode(new_query, doseq=True))
                return urlunparse(new_parsed)
        except Exception as e:
            debug_log('nsig decrypt failed', repr(e))
        return url

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
            r = self.session.get(player_url, headers=self.headers, timeout=15)
            r.raise_for_status()
            code = r.text
        except Exception as e:
            debug_log('Failed to fetch player JS', repr(e))
            code = ''
        self.player_cache[player_url] = code
        return code

    # ===== 格式选择辅助 =====
    def choose_video_tracks(self, formats, quality='best', codec_filter=None):
        videos = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') == 'none']
        if codec_filter:
            videos = [f for f in videos if codec_filter in f.get('codecs', '').lower()]
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

# ========== TVbox 适配层 ==========
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

        # 加载分类配置
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

        # 新闻关键词
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
            # ... 其他省略
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
        videos, has_more = self._search_youtube(query, page)
        videos.sort(key=lambda x: x.get('is_live', False), reverse=True)
        return {
            'list': videos,
            'page': page,
            'pagecount': page + 1 if has_more else page,
            'limit': len(videos),
            'total': len(videos)
        }

    def searchContent(self, key, quick, pg=1):
        page = int(pg)
        videos, has_more = self._search_youtube(key, page)
        videos.sort(key=lambda x: x.get('is_live', False), reverse=True)
        return {
            'list': videos,
            'page': page,
            'pagecount': page + 1 if has_more else page,
            'limit': len(videos),
            'total': len(videos)
        }

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
            # 直播处理
            manifest = data.get('live_manifest')
            if manifest:
                url = manifest.get('hls') or manifest.get('dash')
                if url:
                    debug_log('直播 manifest', {'url': url})
                    # 缓存 manifest URL
                    cache_key = f'yt_live_{video_id}'
                    self.setCache(cache_key, {
                        'url': url,
                        'expires': time.time() + 300,
                    })
                    return {
                        'parse': 0,
                        'jx': 0,
                        'url': f'http://127.0.0.1:9978/proxy?do=py&type=single&vid={video_id}&quality=live',
                        'format': 'application/vnd.apple.mpegurl' if url.endswith('.m3u8') else 'application/dash+xml'
                    }

            # 点播
            all_tracks = self.yt.choose_video_tracks(data['formats'], 'best', codec_filter=codec_type)
            wanted = 'HDR' if quality == 'hdr' else 'SDR'
            video_tracks = [t for t in all_tracks if t.get('track_name') == wanted]
            if not video_tracks and all_tracks:
                video_tracks = [all_tracks[0]]
            if video_tracks:
                audio = self.yt.choose_audio(data['formats'])
                if audio:
                    # MPD 模式
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
                        'format': 'application/dash+xml'
                    }
                else:
                    # 单文件
                    playable = video_tracks[0]
                    cache_key = f'yt_single_{video_id}_{quality}_{codec_type or "none"}'
                    self.setCache(cache_key, {
                        'url': playable['url'],
                        'headers': playable.get('headers', {}),
                        'expires': time.time() + 300,
                    })
                    return {
                        'parse': 0,
                        'jx': 0,
                        'url': f'http://127.0.0.1:9978/proxy?do=py&type=single&vid={video_id}&quality={quality}_{codec_type or "none"}',
                    }
            # fallback: progressive
            progressive = [f for f in data['formats'] if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
            if progressive:
                progressive.sort(key=lambda f: (int(f.get('height', 0)), int(f.get('bitrate', 0))), reverse=True)
                playable = progressive[0]
                cache_key = f'yt_single_{video_id}_{quality}_{codec_type or "none"}'
                self.setCache(cache_key, {
                    'url': playable['url'],
                    'headers': playable.get('headers', {}),
                    'expires': time.time() + 300,
                })
                return {
                    'parse': 0,
                    'jx': 0,
                    'url': f'http://127.0.0.1:9978/proxy?do=py&type=single&vid={video_id}&quality={quality}_{codec_type or "none"}',
                }
            raise Exception('No playable stream')
        except Exception as e:
            debug_log('playerContent error', repr(e))
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
        elif typ == 'media':
            return self._proxy_media(params)
        elif typ == 'single':
            return self._proxy_single(params)
        return None

    # ========== 代理实现 ==========
    def _proxy_single(self, params):
        vid = params.get('vid')
        qc = params.get('quality')
        if qc == 'live':
            # 直播流代理，检查过期并刷新
            cache_key = f'yt_live_{vid}'
            cached = self.getCache(cache_key)
            need_refresh = True
            if cached:
                url = cached.get('url')
                if url:
                    expire_match = re.search(r'expire/(\d+)', url)
                    if expire_match:
                        expire = int(expire_match.group(1))
                        if time.time() + 60 < expire:
                            need_refresh = False
            if need_refresh:
                # 强制重新提取
                if f'extract_{vid}' in self.yt.extract_cache:
                    del self.yt.extract_cache[f'extract_{vid}']
                try:
                    data = self.yt.extract(vid)
                    manifest = data.get('live_manifest')
                    if manifest:
                        url = manifest.get('hls') or manifest.get('dash')
                        if url:
                            self.setCache(cache_key, {'url': url, 'expires': time.time() + 300})
                            cached = {'url': url}
                except Exception as e:
                    debug_log('直播刷新失败', repr(e))
                    if not cached:
                        return [500, 'text/plain', f'Live refresh error: {str(e)}']
            data = self.getCache(cache_key) or cached
            if not data:
                return [404, 'text/plain', 'Live stream not found']
            target_url = data.get('url')
            headers = self.header.copy()
            headers.pop('Cookie', None)
            try:
                r = self.session.get(target_url, headers=headers, stream=True, timeout=30)
                content_type = r.headers.get('content-type', 'application/vnd.apple.mpegurl')
                resp_headers = {'Content-Type': content_type, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-cache'}
                if r.headers.get('content-range'):
                    resp_headers['Content-Range'] = r.headers.get('content-range')
                if r.headers.get('content-length'):
                    resp_headers['Content-Length'] = r.headers.get('content-length')
                return [r.status_code, content_type, r.content, resp_headers]
            except Exception as e:
                return [500, 'text/plain', f'Live proxy error: {str(e)}']

        # 点播单文件
        cache_key = f'yt_single_{vid}_{qc}'
        data = self.getCache(cache_key)
        if not data:
            # 尝试刷新
            data = self._refresh_single(vid, qc)
        if not data:
            return [404, 'text/plain', 'Cache expired']
        target_url = data.get('url')
        headers = self.header.copy()
        headers.pop('Cookie', None)
        if data.get('headers'):
            headers.update(data['headers'])
        range_header = params.get('range') or params.get('Range')
        if range_header:
            headers['Range'] = range_header
        try:
            r = self.session.get(target_url, headers=headers, stream=True, timeout=30)
            content_type = r.headers.get('content-type', 'video/mp4')
            resp_headers = {'Content-Type': content_type, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-cache'}
            if r.headers.get('content-range'):
                resp_headers['Content-Range'] = r.headers.get('content-range')
            if r.headers.get('content-length'):
                resp_headers['Content-Length'] = r.headers.get('content-length')
            return [r.status_code, content_type, r.content, resp_headers]
        except Exception as e:
            return [500, 'text/plain', f'Proxy error: {str(e)}']

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
        media_base = f'http://127.0.0.1:9978/proxy?do=py&type=media&vid={vid}&quality={qc}'
        direct_segments = str(self.extendDict.get('seg', 'proxy')).lower() == 'direct'
        duration_pt = f"PT{int(duration)}S"
        mpd = f'''<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="{duration_pt}" minBufferTime="PT90S" profiles="urn:mpeg:dash:profile:isoff-on-demand:2011">
  <Period id="1" start="PT0S">
'''
        for item in video_tracks:
            init = item.get('initRange', {})
            idx = item.get('indexRange', {})
            base_url = item.get('url') if direct_segments else media_base + f"&track=video&itag={item.get('itag')}"
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
            base_url = audio_track.get('url') if direct_segments else media_base + '&track=audio'
            mpd += f'''    <AdaptationSet mimeType="{html.escape(audio_track.get('mimeType', 'audio/mp4').split(';')[0])}" startWithSAP="1" segmentAlignment="true" lang="und">
      <Representation id="audio" bandwidth="{audio_track.get('bitrate', 128000)}" codecs="{html.escape(audio_track.get('codecs', ''))}" audioSamplingRate="44100">
        <BaseURL>{html.escape(base_url)}</BaseURL>
        <SegmentBase indexRange="{idx.get('start', 0)}-{idx.get('end', 0)}"><Initialization range="{init.get('start', 0)}-{init.get('end', 0)}"/></SegmentBase>
      </Representation>
    </AdaptationSet>
'''
        mpd += '  </Period>\n</MPD>'
        return [200, 'application/dash+xml', mpd]

    def _proxy_media(self, params):
        vid = params.get('vid')
        qc = params.get('quality')
        track = params.get('track')
        cache_key = f'yt_mpd_{vid}_{qc}'
        data = self.getCache(cache_key)
        if not data:
            data = self._refresh_mpd(vid, qc)
        if not data or track not in ('video', 'audio'):
            return [404, 'text/plain', 'Media not found']
        if track == 'video':
            itag = params.get('itag')
            tracks = data.get('video_tracks', [])
            item = next((t for t in tracks if str(t.get('itag')) == itag), tracks[0] if tracks else {})
            target_url = item.get('url')
        else:
            item = data.get('audio_track', {})
            target_url = item.get('url')
        if not target_url:
            return [404, 'text/plain', 'Stream not found']
        headers = self.header.copy()
        headers.pop('Cookie', None)
        headers.update(item.get('headers', {}))
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
            return [500, 'text/plain', f'Media proxy error: {str(e)}']

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
            cache_data = {
                'video_tracks': video_tracks,
                'audio_track': audio,
                'duration': data.get('duration', 0),
                'expires': time.time() + 300,
            }
            cache_key = f'yt_mpd_{vid}_{qc}'
            self.setCache(cache_key, cache_data)
            return cache_data
        except Exception as e:
            debug_log('MPD refresh error', repr(e))
            return None

    def _refresh_single(self, vid, qc):
        try:
            data = self.yt.extract(vid)
            progressive = [f for f in data['formats'] if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
            if progressive:
                progressive.sort(key=lambda f: (int(f.get('height', 0)), int(f.get('bitrate', 0))), reverse=True)
                playable = progressive[0]
            else:
                tracks = self.yt.choose_video_tracks(data['formats'], 'best')
                if not tracks:
                    return None
                playable = tracks[0]
            cache_data = {
                'url': playable['url'],
                'headers': playable.get('headers', {}),
                'expires': time.time() + 300,
            }
            cache_key = f'yt_single_{vid}_{qc}'
            self.setCache(cache_key, cache_data)
            return cache_data
        except Exception as e:
            debug_log('Single refresh error', repr(e))
            return None

    # ========== 搜索相关 ==========
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
                if k == 'year':
                    if v:
                        terms.append(str(v))
                else:
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
        # 翻页
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
        return {
            'api_key': api_key,
            'context': context,
            'referer': url,
            'pages': [videos],
            'next': self._extract_continuation(data),
        }

    def _fetch_search_continuation(self, session):
        token = session.get('next')
        api_key = session.get('api_key')
        if not token or not api_key:
            return {}
        url = f'https://www.youtube.com/youtubei/v1/search?key={api_key}'
        headers = self.header.copy()
        headers.update({
            'Content-Type': 'application/json',
            'Origin': 'https://www.youtube.com',
            'Referer': session.get('referer', 'https://www.youtube.com/'),
        })
        payload = {'context': session.get('context', {}), 'continuation': token}
        try:
            r = self.session.post(url, json=payload, headers=headers, timeout=15)
            r.raise_for_status()
            return r.json()
        except:
            return {}

    def _extract_continuation(self, data):
        tokens = []
        def scan(obj):
            if isinstance(obj, dict):
                for key, val in obj.items():
                    if key == 'continuationEndpoint':
                        token = val.get('continuationCommand', {}).get('token')
                        if token:
                            tokens.append(token)
                    elif key == 'continuationItemRenderer':
                        token = val.get('continuationEndpoint', {}).get('continuationCommand', {}).get('token')
                        if token:
                            tokens.append(token)
                    else:
                        scan(val)
            elif isinstance(obj, list):
                for item in obj:
                    scan(item)
        scan(data)
        return tokens[0] if tokens else None

    def _extract_videos(self, data, limit):
        videos = []
        seen = set()
        def scan(obj):
            if len(videos) >= limit:
                return
            if isinstance(obj, dict):
                for key in ('videoRenderer', 'compactVideoRenderer', 'gridVideoRenderer'):
                    if key in obj:
                        item = self._parse_renderer(obj[key])
                        if item and item['vod_id'] not in seen:
                            seen.add(item['vod_id'])
                            videos.append(item)
                for val in obj.values():
                    scan(val)
            elif isinstance(obj, list):
                for val in obj:
                    scan(val)
        scan(data)
        return videos[:limit]

    def _parse_renderer(self, renderer):
        try:
            vid = renderer.get('videoId')
            if not vid:
                nav = renderer.get('navigationEndpoint', {})
                vid = nav.get('watchEndpoint', {}).get('videoId')
            if not vid:
                return None
            title_obj = renderer.get('title', {})
            title = title_obj.get('simpleText') or ' '.join([x.get('text', '') for x in title_obj.get('runs', [])]) or 'YouTube'
            dur = renderer.get('lengthText', {}).get('simpleText', '')
            is_live = False
            for badge in renderer.get('badges', []):
                if badge.get('metadataBadgeRenderer', {}).get('style') == 'BADGE_STYLE_TYPE_LIVE_NOW':
                    is_live = True
                    break
            return {
                'vod_id': vid,
                'vod_name': html.unescape(title),
                'vod_pic': f'https://img.youtube.com/vi/{vid}/hqdefault.jpg',
                'vod_remarks': dur,
                'is_live': is_live,
            }
        except:
            return None

    def _get_video_title(self, vid):
        try:
            r = self.session.get(f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json', timeout=5)
            return r.json().get('title', vid)
        except:
            return vid

    def _safe_title(self, title):
        if not title:
            return 'video'
        return re.sub(r'[#$@%&!?*|\\/:<>]', ' ', title)[:60]

    def destroy(self):
        try:
            self.session.close()
        except:
            pass