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

DEBUG_LOG = '/sdcard/Download/0712youtube_trace.log'


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
    # 此处为完整的 YouTubeLite 类，与 0712 版完全一致（为避免重复，省略，实际使用需包含全部方法）
    # 请确保包含以下所有方法：
    # __init__, extract, extract_video_id, _client_name_id, _extract_visitor_data,
    # _extract_signature_timestamp, _get_po_token, choose_playable, _video_codec_priority,
    # _is_risky_best_video, choose_video_tracks, _is_hdr_video, choose_audio, _probe_format,
    # choose_best_video_audio, _url_summary, _get, _post_json, _call_player_api, _normalize_format,
    # _decrypt_signature_cipher, _decrypt_sig, _decrypt_nsig, _get_player_code, _extract_sig_plan,
    # _extract_helper_object, _extract_n_function, _extract_js_function_body, _extract_ytcfg,
    # _extract_initial_player_response, _extract_json_after, _extract_player_url, _search
    # 由于篇幅，此处仅作示意，实际使用时需补全。
    # 建议直接从 0712 版复制 YouTubeLite 类完整代码，或从之前我的回答中复制完整类。
    pass


class Spider(Spider):
    def getName(self):
        return 'YouTube视频'

    def init(self, extend):
        self.extendDict = {}
        if extend:
            if isinstance(extend, dict):
                self.extendDict = extend
            elif isinstance(extend, str):
                try:
                    self.extendDict = json.loads(extend)
                except Exception as e:
                    debug_log('extend JSON parse error', repr(e))
                    if '=' in extend:
                        parts = extend.split('=', 1)
                        if len(parts) == 2:
                            self.extendDict = {parts[0].strip(): parts[1].strip()}
                    else:
                        self.extendDict = {}
            else:
                self.extendDict = {}
        debug_log('init extendDict', self.extendDict)

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
            'Referer': 'https://www.youtube.com/'
        }
        self.session.headers.update(self.header)
        self.yt = YouTubeLite(self.session, self.header, self.extendDict)
        self.config = {}
        self.search_page_cache = {}

        try:
            self.youtube_config = self._load_youtube_config()
            debug_log('youtube_config loaded', {'keys': list(self.youtube_config.keys())})
        except Exception as e:
            debug_log('Failed to load youtube_config, using empty dict', repr(e))
            self.youtube_config = {}
        self.type_name_map = {
            item.get('type_id'): item.get('type_name', '')
            for item in self.youtube_config.get('class', [])
            if item.get('type_id')
        }

    def _load_youtube_config(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        default_path = os.path.join(os.path.dirname(script_dir), 'lib', 'youtube.json')

        custom_path = self.extendDict.get('json')
        if custom_path:
            if custom_path.startswith('http://') or custom_path.startswith('https://'):
                json_path = custom_path
                try:
                    debug_log('Loading youtube.json from remote URL', {'url': json_path})
                    resp = requests.get(json_path, timeout=10)
                    resp.raise_for_status()
                    config = resp.json()
                    debug_log('Loaded youtube.json from remote', {'keys': list(config.keys())})
                    return config
                except Exception as e:
                    debug_log('Failed to load youtube.json from remote', {'url': json_path, 'error': repr(e)})
                    raise RuntimeError(f'无法从远程 {json_path} 加载 youtube.json: {e}')
            elif custom_path.startswith('./') or custom_path.startswith('.\\'):
                json_path = os.path.join(script_dir, custom_path[2:])
            elif not os.path.isabs(custom_path):
                json_path = os.path.join(script_dir, custom_path)
            else:
                json_path = custom_path
        else:
            json_path = default_path

        debug_log('Attempting to load youtube.json from local', {'path': json_path, 'exists': os.path.exists(json_path)})
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            debug_log('Loaded youtube.json from local', {'path': json_path, 'keys': list(config.keys())})
            return config
        except Exception as e:
            debug_log('Failed to load youtube.json from local', {'path': json_path, 'error': repr(e)})
            raise RuntimeError(f'无法从 {json_path} 加载 youtube.json: {e}')

    def homeContent(self, filter):
        result = {'class': self.youtube_config.get('class', [])}
        if filter:
            result['filters'] = self.youtube_config.get('filters', {})
        return result

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, cid, page, filter, ext):
        page = int(page)
        filters = ext if isinstance(ext, dict) else {}
        query = self._build_category_keyword(cid, filters)
        debug_log('categoryContent query', {'cid': cid, 'query': query})
        videos, has_more = self._search_youtube_page(query, page)
        return {'list': videos, 'page': page, 'pagecount': page + 1 if has_more else page, 'limit': len(videos), 'total': len(videos)}

    def searchContent(self, key, quick, pg=1):
        page = int(pg)
        videos, has_more = self._search_youtube_page(key, page)
        return {'list': videos, 'page': page, 'pagecount': page + 1 if has_more else page, 'limit': len(videos), 'total': len(videos)}

    def detailContent(self, did):
        video_id = did[0]
        title = self._get_video_title(video_id)
        safe_title = self._safe_title(title)
        play_sources = []
        play_urls = []
        try:
            data = self.yt.extract(video_id)
            tracks = self.yt.choose_video_tracks(data.get('formats') or [], 'best')
            for track in tracks:
                height = int(track.get('height') or 0)
                kind = track.get('track_name') or ('HDR' if track.get('is_hdr') else 'SDR')
                name = f'{height}p {kind}' if height else kind
                quality = 'hdr' if kind == 'HDR' else 'best'
                play_sources.append(name)
                play_urls.append(f'{safe_title} {name}${video_id}@{quality}')
            debug_log('detail dynamic sources', {'video_id': video_id, 'sources': play_sources})
        except Exception as e:
            debug_log('detail dynamic sources error', {'video_id': video_id, 'error': repr(e)})
        if not play_sources:
            play_sources = ['SDR', 'HDR']
            play_urls = [
                f'{safe_title} SDR${video_id}@best',
                f'{safe_title} HDR${video_id}@hdr',
            ]
        vod = {
            'vod_id': video_id,
            'vod_name': title,
            'vod_pic': f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg',
            'vod_play_from': '$$$'.join(play_sources),
            'vod_play_url': '$$$'.join(play_urls)
        }
        return {'list': [vod]}

    def _build_direct_play_url(self, media_url, headers, ext):
        header_query = urlencode({k: v for k, v in (headers or {}).items() if v})
        return f'{media_url}|{header_query}' if header_query else media_url

    def playerContent(self, flag, pid, vipFlags):
        raw_pid = pid.split('$')[-1]
        if '@' in raw_pid:
            video_id, quality = raw_pid.rsplit('@', 1)
        else:
            video_id, quality = raw_pid, '1080p'
        if quality not in ('best', 'hdr', '4k', '2k', '1080p'):
            quality = 'best'
        debug_log('playerContent', {'flag': flag, 'pid': pid, 'video_id': video_id, 'quality': quality})
        try:
            data = self.yt.extract(video_id)
            all_tracks = self.yt.choose_video_tracks(data['formats'], 'best')
            wanted_name = 'HDR' if quality == 'hdr' else 'SDR'
            video_tracks = [x for x in all_tracks if x.get('track_name') == wanted_name]
            if not video_tracks and all_tracks:
                video_tracks = [all_tracks[0]]
            if video_tracks:
                audio = self.yt.choose_audio(data['formats'])
                debug_log('selected track', {'requested': wanted_name, 'track': {'name': video_tracks[0].get('track_name'), 'itag': video_tracks[0].get('itag'), 'height': video_tracks[0].get('height'), 'mime': video_tracks[0].get('mimeType')}, 'audio': audio.get('itag') if audio else None})
                if audio:
                    cache_key = f'yt_{video_id}_{quality}'
                    self.setCache(cache_key, {
                        'video_tracks': video_tracks,
                        'video_url': video_tracks[0]['url'],
                        'audio_url': audio['url'],
                        'video_item': video_tracks[0],
                        'audio_item': audio,
                        'duration': data.get('duration') or 0,
                        'expires': time.time() + 300,
                    })
                    return {'parse': 0, 'jx': 0, 'url': f'http://127.0.0.1:9978/proxy?do=py&type=mpd&vid={video_id}&quality={quality}', 'format': 'application/dash+xml'}
                playable = video_tracks[0]
                headers = self.header.copy()
                headers.update(playable.get('headers') or {})
                return {'parse': 0, 'jx': 0, 'url': playable['url'], 'header': headers}
            raise Exception(f'没有可直接播放的 {quality} 视频流格式')
        except Exception as e:
            debug_log('playerContent error', repr(e))
            print(f'[YouTubeLite] 解析失败: {e}')
            res = {'parse': 1, 'url': f'https://www.youtube.com/embed/{video_id}?autoplay=1', 'header': json.dumps(self.header)}
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

    def _proxy_single(self, params):
        vid = params.get('vid')
        debug_log('proxy single request', {'vid': vid, 'range': params.get('range'), 'keys': sorted(list(params.keys()))[:20]})
        data = self.getCache(f'yt_single_{vid}') if vid else None
        if not data:
            return [404, 'text/plain', '播放缓存已过期或不存在']
        target_url = data.get('url')
        if not target_url:
            return [404, 'text/plain', '播放地址不存在']
        headers = (data.get('headers') or self.header).copy()
        range_header = params.get('range') or params.get('Range')
        if range_header:
            headers['Range'] = range_header
        try:
            r = self.session.get(target_url, headers=headers, stream=True, timeout=30)
            debug_log('proxy single response', {'status': r.status_code, 'content_type': r.headers.get('content-type'), 'content_length': r.headers.get('content-length'), 'content_range': r.headers.get('content-range')})
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
            debug_log('proxy single error', repr(e))
            return [500, 'text/plain', f'代理播放失败: {str(e)}']

    def _proxy_mpd(self, params):
        vid = params.get('vid')
        quality = params.get('quality') or '1080p'
        data = self.getCache(f'yt_{vid}_{quality}') if vid else None
        if not data:
            return [404, 'text/plain', '视频缓存已过期或不存在']
        audio_url = data.get('audio_url')
        duration = data.get('duration') or 0
        video_tracks = data.get('video_tracks') or [data.get('video_item') or {}]
        audio_item = data.get('audio_item') or {}
        media_base = f'http://127.0.0.1:9978/proxy?do=py&type=media&vid={vid}&quality={quality}'
        direct_segments = str(self.extendDict.get('seg') or 'proxy').lower() == 'direct'
        duration_pt = f"PT{int(duration or 0)}S"
        mpd = f'''<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="{duration_pt}" minBufferTime="PT1.5S" profiles="urn:mpeg:dash:profile:isoff-on-demand:2011">
  <Period id="1" start="PT0S">
'''
        for item in video_tracks:
            init_range = item.get('initRange') or {}
            index_range = item.get('indexRange') or {}
            name = item.get('track_name') or ('HDR' if item.get('is_hdr') else 'SDR')
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
        debug_log('proxy mpd tracks', {'vid': vid, 'quality': quality, 'tracks': [{'name': x.get('track_name'), 'itag': x.get('itag')} for x in video_tracks], 'audio': audio_item.get('itag'), 'direct': direct_segments, 'duration': duration_pt})
        return [200, 'application/dash+xml', mpd]

    def _proxy_media(self, params):
        vid = params.get('vid')
        quality = params.get('quality') or '1080p'
        track = params.get('track')
        data = self.getCache(f'yt_{vid}_{quality}') if vid else None
        if not data or track not in ('video', 'audio'):
            return [404, 'text/plain', '媒体不存在']
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
        headers.update((media_item or {}).get('headers') or {})
        range_header = params.get('range') or params.get('Range')
        if range_header:
            headers['Range'] = range_header
        try:
            r = self.session.get(target_url, headers=headers, stream=True, timeout=30)
            content_type = r.headers.get('content-type', 'application/octet-stream')
            debug_log('proxy media response', {'track': track, 'itag': media_item.get('itag'), 'track_name': media_item.get('track_name'), 'status': r.status_code, 'range': range_header, 'content_type': content_type, 'content_length': r.headers.get('content-length'), 'content_range': r.headers.get('content-range')})
            resp_headers = {'Content-Type': content_type, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-cache'}
            if r.headers.get('content-range'):
                resp_headers['Content-Range'] = r.headers.get('content-range')
            if r.headers.get('content-length'):
                resp_headers['Content-Length'] = r.headers.get('content-length')
            return [r.status_code, content_type, r.content, resp_headers]
        except Exception as e:
            return [500, 'text/plain', f'代理媒体失败: {str(e)}']

    def _normalize_filter_term(self, value):
        if isinstance(value, (list, tuple)):
            return ' '.join([self._normalize_filter_term(item) for item in value if item])
        if isinstance(value, dict):
            return ' '.join([self._normalize_filter_term(item) for item in value.values() if item])
        return re.sub(r'\s+', ' ', str(value or '')).strip()[:180]

    def _build_category_keyword(self, cid, filters=None):
        # 直接使用整个 cid 作为基础搜索词（与 0712 版完全一致）
        base_keywords = cid
        # 补充 type_name（如果有且不重复）
        type_name = self.type_name_map.get(cid, '')
        if type_name and type_name not in base_keywords:
            base_keywords = base_keywords + ' ' + type_name
        terms = [base_keywords] if base_keywords else []
        # 添加过滤条件
        if isinstance(filters, dict):
            for value in filters.values():
                term = self._normalize_filter_term(value)
                if term:
                    terms.append(term)
        # 去重
        seen = set()
        output = []
        for term in terms:
            term = term.strip()
            if term and term not in seen:
                seen.add(term)
                output.append(term)
        final_query = ' '.join(output)
        debug_log('Built search query', {'cid': cid, 'filters': filters, 'query': final_query})
        return final_query

    # 以下方法均为搜索和解析辅助，与 0712 版一致（此处省略详细实现，实际使用时需完整包含）
    # 包括 _search_cache_key, _search_youtube, _search_youtube_page, _fetch_search_first_page,
    # _fetch_search_continuation, _extract_continuation_token, _extract_videos_fixed,
    # _extract_videos_from_api, _parse_renderer, _get_video_title, _safe_title, _seconds_to_iso_duration, destroy

    # 由于篇幅，此处仅提供骨架，实际使用请确保所有方法完整。
    # 强烈建议直接从 0712 版复制整个 Spider 类（除 homeContent 和 _load_youtube_config 外），
    # 然后替换 homeContent 和 _load_youtube_config 即可。
