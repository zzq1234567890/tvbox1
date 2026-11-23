import sys
import re
import json
import time
import random
import struct
import requests
import urllib.parse
import hashlib
import hmac
import base64
import ssl
import socket
from base64 import b64encode, b64decode
from urllib.parse import quote, urljoin, urlparse, parse_qs
from urllib3 import disable_warnings
from base.spider import Spider
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import warnings

warnings.filterwarnings('ignore', message='Unverified HTTPS request')
disable_warnings()

# 检查 socks 支持
try:
    from requests.packages.urllib3.contrib.socks import SOCKSProxyManager
    SOCKS_AVAILABLE = True
except ImportError:
    SOCKS_AVAILABLE = False


class Spider(Spider):
    """
    广东荔枝网（GRTN）直播 Spider：单源双模式（参考 yangshipin.py）

    用法一：当直播源（live 里填）
    {
    "api": "./广东荔枝.py",
    "ext": {},
    "name": "广东荔枝"
    }

    用法二：当点播站（site 里填）
    {
    "key": "gdtv_vod", "name": "广东荔枝",
    "type": 3,
    "api": "./广东荔枝.py", "ext": {}
    }

    ext 可选：
      epg_xml    直播 M3U 的节目单地址，默认空（不写 tvg-url）
      live_mode  proxy(默认) 直播 M3U 嵌代理地址，每次拉流取新鲜 token；
                 redirect 则在生成 M3U 时直接取官方 hd 直链（token 易过期，仅排错用）

    点播与直播分开播放：
    - 点播（site）：分类/详情/播放走 detailContent/playerContent，每频道单集
      `直播$cid`，playerContent 返回 parse=0 的本地代理 m3u8（type=m3u8&url=..&cid=..），
      代理去 ENDLIST 保滚动，避免“这集已播放结束”。
    - 直播（live）：liveContent 返回 M3U 文本，每行播放地址是本地代理
      `type=m3u8&cid=..`（不嵌过期 token），真正拉流时 localProxy 再取新鲜 hd。
      点播、直播共用 _entries()，频道集合、顺序、分组永远一致。
    """
    
    # ==================== 频道数据 ====================
    CHANNEL_MAP = {
        43: '广东卫视',
        44: '广东珠江',
        45: '广东新闻',
        46: '大湾区卫视（海外版）',
        47: '广东体育',
        48: '广东民生',
        51: '大湾区卫视',
        53: '广东影视',
        16: '4K超高清',
        54: '广东少儿',
        66: '嘉佳卡通',
        42: '南方购物',
        15: '岭南戏曲',
        74: '广东移动',
        111: '现代教育',
        100: '广东台经典剧',
        99: 'GRTN健康频道',
        75: 'GRTN文化频道',
        102: 'GRTN生活频道',
    }
    
    # 频道图标
    LOGOS = {
        43: 'https://cdn.jsdelivr.net/gh/wanglindl/TVlogo@main/img/Guangdong.png',
        44: 'https://cdn.jsdelivr.net/gh/wanglindl/TVlogo@main/img/Guangdong.png',
        51: 'https://cdn.jsdelivr.net/gh/wanglindl/TVlogo@main/img/Guangdong.png',
    }
    
    # ==================== 分类定义 ====================
    CATS = [
        {'name': '广东卫视', 'ids': [43, 44, 45, 46, 47, 48, 51, 53]},
        {'name': '高清频道', 'ids': [16, 54, 66]},
        {'name': '特色频道', 'ids': [42, 15, 74, 111]},
        {'name': 'GRTN频道', 'ids': [100, 99, 75, 102]},
    ]
    
    # ==================== 初始化 ====================
    
    def init(self, extend=""):
        opts = {}
        if isinstance(extend, dict):
            opts = extend
        elif isinstance(extend, str) and extend.strip().startswith("{"):
            try:
                opts = json.loads(extend)
            except ValueError:
                opts = {}
        self.epg_xml = str(opts.get("epg_xml") or "").strip()
        self.live_mode = str(opts.get("live_mode") or "proxy").strip().lower()
        if self.live_mode not in ("proxy", "redirect"):
            self.live_mode = "proxy"
        self.session = self._create_session()
        self.cache_dir = self._init_cache_dir()
        self.common_headers = {
            'Accept': '*/*',
            'Connection': 'keep-alive',
            'Referer': 'https://www.gdtv.cn/',
            'Origin': 'https://www.gdtv.cn',
            'User-Agent': 'Mozilla/5.0 (Linux; U; Android 9)'
        }
        self.session.headers.update(self.common_headers)
        
    def _create_session(self) -> requests.Session:
        s = requests.Session()
        retry_strategy = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy)
        s.mount('http://', adapter)
        s.mount('https://', adapter)
        return s
    
    def _init_cache_dir(self) -> str:
        import os
        cache_dir = os.path.join(os.path.dirname(__file__), 'gdtvcache')
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, mode=0o775, exist_ok=True)
        return cache_dir
    
    def getName(self):
        return "广东荔枝网直播"

    def getDependence(self):
        return []

    def action(self, action):
        return {}

    # ==================== 点播/直播共用频道来源 ====================

    def _entries(self, tid='all'):
        """点播列表与直播 M3U 的唯一频道来源，两边都从这里取，保证一致。"""
        norm = str(tid or 'all').strip()
        if not norm:
            norm = 'all'
        out = []
        if norm in ('all', ''):
            for cid, name in self.CHANNEL_MAP.items():
                out.append({
                    'cid': cid,
                    'name': name,
                    'group': self._group_of(cid),
                    'epg': str(cid),
                })
            return out
        try:
            cat_index = int(norm)
        except (TypeError, ValueError):
            return []
        if cat_index < 0 or cat_index >= len(self.CATS):
            return []
        cat = self.CATS[cat_index]
        for cid in cat['ids']:
            name = self.CHANNEL_MAP.get(cid, f'频道{cid}')
            out.append({
                'cid': cid,
                'name': name,
                'group': cat['name'],
                'epg': str(cid),
            })
        return out

    def _group_of(self, cid):
        for cat in self.CATS:
            if cid in cat['ids']:
                return cat['name']
        return '广东荔枝'

    def _card(self, cid, name):
        return {
            'vod_id': str(cid),
            'vod_name': name,
            'vod_pic': self.LOGOS.get(cid, ''),
            'vod_remarks': '广东荔枝 | 直播',
        }

    def _logo(self, cid, name=''):
        try:
            direct = self.LOGOS.get(int(cid), '') if str(cid).strip().lstrip('-').isdigit() else ''
        except Exception:
            direct = ''
        return direct or ''

    # ==================== 直播源 M3U ====================

    def liveContent(self, url=""):
        if getattr(self, 'epg_xml', ''):
            lines = ['#EXTM3U tvg-url="%s" x-tvg-url="%s"' % (self.epg_xml, self.epg_xml)]
        else:
            lines = ['#EXTM3U']
        # 直播列表直接由点播列表生成：点播全部频道 + 各分类，共用 _entries()。
        seen = set()
        for tid in ['all'] + [str(i) for i in range(len(self.CATS))]:
            for item in self._entries('all' if tid == 'all' else tid):
                cid = item['cid']
                if cid in seen:
                    continue
                seen.add(cid)
                lines.append(self._m3u_entry(cid, item['name'], item['epg'], item['group']))
                lines.append(self._live_play_url(cid))
        return '\n'.join(lines) + '\n'

    def _live_play_url(self, cid):
        """直播 M3U 的播放行：默认只嵌代理 cid，拉流时再取新鲜 token。"""
        if getattr(self, 'live_mode', 'proxy') == 'redirect':
            try:
                hd = self._get_play_url(int(cid))
                if hd:
                    return hd
            except Exception:
                pass
        return self._lazy_proxy_url(cid)

    def _lazy_proxy_url(self, cid):
        """直播懒地址：type=m3u8&cid=..，localProxy 见 cid 无 url 时现取 hd。"""
        try:
            proxy_base = self.getProxyUrl()
        except Exception:
            return ''
        if not proxy_base:
            return ''
        separator = '&' if '?' in proxy_base else '?'
        return f'{proxy_base}{separator}type=m3u8&cid={quote(str(cid), safe="")}'

    def _m3u_entry(self, cid, name, epg='', group=''):
        def _safe(value):
            return re.sub(r'[\r\n]+', ' ', str(value or '')).replace('"', '').strip()
        logo = self._logo(cid, name)
        return '#EXTINF:-1 tvg-id="%s" tvg-name="%s" tvg-logo="%s" group-title="%s",%s' % (
            _safe(epg or cid), _safe(name), _safe(logo),
            _safe(group or self._group_of(cid)), _safe(name))
    
    # ==================== 蜘蛛壳接口 ====================
    
    def homeContent(self, filter=False):
        classes = [
            {'type_id': str(i), 'type_name': c['name']}
            for i, c in enumerate(self.CATS)
        ]
        result = {'class': classes}
        if filter:
            result['filters'] = {}
        return result
    
    def homeVideoContent(self):
        return self.categoryContent('0', '1', False, {})
    
    def categoryContent(self, tid, pg='1', filter=False, extend=None):
        # 点播分类直接走共用 _entries()，与直播 M3U 同源
        entries = self._entries(tid)
        if not entries and str(tid).strip() not in ('all', ''):
            return self._empty_page()
        vod_list = [self._card(item['cid'], item['name']) for item in entries]
        return {
            'page': 1,
            'pagecount': 1,
            'limit': len(vod_list),
            'total': len(vod_list),
            'list': vod_list,
        }
    
    def detailContent(self, ids):
        if not ids:
            return {'list': []}
        cid = int(str(ids[0]).strip())
        name = self.CHANNEL_MAP.get(cid, f'频道{cid}')
        vod = {
            'vod_id': str(cid),
            'vod_name': name,
            'vod_pic': self.LOGOS.get(cid, ''),
            'type_name': '电视直播',
            'vod_remarks': '直播',
            'vod_play_from': '广东荔枝网',
            'vod_play_url': f'直播${cid}',
            'vod_content': f'{name} 高清直播',
        }
        return {'list': [vod]}
    
    def playerContent(self, flag, id, vipFlags=None):
        raw = str(id or '')
        # detail 给的是 `直播$43`，取最后一个 $ 后面的频道 id；兼容 $$$ 分隔
        cid = raw.split('$$$')[-1].split('$')[-1].strip()
        try:
            channel_id = int(cid)
        except ValueError:
            return {'parse': 0, 'playUrl': '', 'url': '', 'header': {}}

        if channel_id not in self.CHANNEL_MAP:
            return {'parse': 0, 'playUrl': '', 'url': '', 'header': {}}

        try:
            play_url = self._get_play_url(channel_id)
            if play_url:
                # 直播当点播播：必须 parse=0 直播直出 + 走本地代理滚动 m3u8。
                # 之前 parse=1 会让壳走嗅探/解析，拿到只有 3 片约 9 秒的
                # 快照就认为“这集已播放结束”；只有开循环才继续。
                proxy_url = self._get_proxy_url(play_url, kind='m3u8', cid=str(channel_id))
                if not proxy_url:
                    proxy_url = play_url
                return {
                    'parse': 0,
                    'playUrl': '',
                    'url': proxy_url,
                    'header': {
                        'User-Agent': 'Mozilla/5.0 (Linux; U; Android 9)',
                        'Referer': 'https://www.gdtv.cn/',
                        'Origin': 'https://www.gdtv.cn',
                    },
                    'format': 'application/x-mpegURL',
                }
        except Exception as e:
            print(f"[广东荔枝网] 获取播放地址失败: {e}")

        return {'parse': 0, 'playUrl': '', 'url': '', 'header': {}}
    
    def searchContent(self, key, quick=False, pg='1'):
        keyword = str(key or '').strip().lower()
        if not keyword:
            return {'list': []}
        videos = []
        for cid, name in self.CHANNEL_MAP.items():
            if keyword in str(cid).lower() or keyword in name.lower():
                videos.append({
                    'vod_id': str(cid),
                    'vod_name': name,
                    'vod_pic': self.LOGOS.get(cid, ''),
                    'vod_remarks': '直播',
                })
        return {'list': videos}
    
    def isVideoFormat(self, url):
        try:
            low = str(url or '').lower().split('?')[0]
            return low.endswith(('.m3u8', '.m3u', '.mp4', '.ts', '.m4s', '.key')) or '.m3u8' in low
        except Exception:
            return False

    def proxy(self, param):
        return self.localProxy(param)
    
    def manualVideoCheck(self):
        return False
    
    def localProxy(self, param):
        """
        本地代理：m3u8 拉回重写为代理段地址，ts 二进制回传。
        六壳传入可能是 dict / JSON 字符串 / 原始 URL 字符串，统一归一化。
        只用 200/400/404/500 状态码，避免部分壳 Status.lookup 闪退。
        """
        try:
            if isinstance(param, dict):
                query = dict(param)
            elif isinstance(param, str):
                try:
                    parsed_param = json.loads(param)
                    query = dict(parsed_param) if isinstance(parsed_param, dict) else {'url': param}
                except Exception:
                    query = {'url': param}
            else:
                query = {}

            def _one(value):
                if isinstance(value, (list, tuple)):
                    return str(value[0]) if value else ''
                return str(value or '')

            kind = _one(query.get('type') or query.get('action') or query.get('do') or '').strip().lower()
            cid = _one(query.get('cid') or query.get('id') or '').strip()
            raw_url = _one(query.get('url') or query.get('u') or '').strip()
            referer = _one(query.get('referer') or query.get('ref') or '').strip()
            if not raw_url:
                # 兼容裸 URL 字符串直接进代理
                try:
                    raw_url = str(param).strip()
                except Exception:
                    raw_url = ''
            # 注意：上游 t_token 里 %2B 必须原样保留，多做一次 unquote 会变 + 导致 403，
            # 所以这里绝不 blanket unquote，只在下面两种情况做一次精确解码。
            # 兼容旧版/外层代理地址：...?do=py&u=<quoted> 或 ?do=py&type=..&url=..
            # 直接把外层剥掉，取内层真实上游地址，避免把代理地址当上游去 GET。
            try:
                if 'do=py' in raw_url and ('u=' in raw_url or 'url=' in raw_url):
                    qs = urlparse(raw_url).query
                    outer = {}
                    for part in qs.split('&'):
                        if not part or '=' not in part:
                            continue
                        k, v = part.split('=', 1)
                        try:
                            k = urllib.parse.unquote(k)
                            v = urllib.parse.unquote(v)
                        except Exception:
                            pass
                        if k not in outer:
                            outer[k] = v
                    inner = str(outer.get('url') or outer.get('u') or '').strip()
                    if inner:
                        raw_url = inner
                        if not kind:
                            kind = str(outer.get('type') or outer.get('action') or '').strip().lower()
                        if not cid:
                            cid = str(outer.get('cid') or outer.get('id') or '').strip()
            except Exception:
                pass
            # dict 值若被双重编码（出现 %25），只解一次回到 %2B 即停
            try:
                if '%25' in raw_url:
                    raw_url = urllib.parse.unquote(raw_url)
            except Exception:
                pass
            # 部分容器用 form 解码把 + 变成空格，这里救回来
            try:
                if ' ' in raw_url and ('t_token' in raw_url or 'txSecret' in raw_url):
                    raw_url = raw_url.replace(' ', '+')
            except Exception:
                pass
            if raw_url.startswith('//'):
                raw_url = 'https:' + raw_url
            # 直播懒地址：只有 type=m3u8&cid，无 url —— 现取新鲜 hd 再走 m3u8 分支
            if not raw_url.startswith(('http://', 'https://')):
                if cid and (not kind or kind in ('m3u8', 'py', 'proxy', 'media')):
                    try:
                        fresh = self._get_play_url(int(cid))
                    except Exception:
                        fresh = ''
                    if fresh:
                        raw_url = fresh
                        kind = 'm3u8'
                if not raw_url.startswith(('http://', 'https://')):
                    return [404, 'text/plain; charset=utf-8', 'Not Found']

            low_all = (raw_url + ' ' + kind).lower()
            if not kind or kind in ('py', 'proxy', 'media'):
                if '.m3u8' in low_all or '.m3u' in low_all:
                    kind = 'm3u8'
                else:
                    kind = 'ts'

            headers = {
                'User-Agent': 'Mozilla/5.0 (Linux; U; Android 9)',
                'Referer': 'https://www.gdtv.cn/',
                'Origin': 'https://www.gdtv.cn',
                'Accept': '*/*',
                'Connection': 'keep-alive',
            }

            if kind == 'm3u8' or '.m3u8' in raw_url.lower() or '.m3u' in raw_url.lower():
                content = ''
                base = raw_url
                try:
                    resp = self.session.get(raw_url, headers=headers, timeout=20, verify=False)
                    if resp.status_code == 200 and resp.text:
                        content = resp.text
                        base = str(getattr(resp, 'url', '') or raw_url)
                except Exception:
                    content = ''
                # t_token 过期时用 cid 重新取一次新鲜 hd 地址再拉
                if (not content or '#EXTINF' not in content) and cid:
                    try:
                        fresh = self._get_play_url(int(cid))
                        if fresh and fresh != raw_url:
                            resp = self.session.get(fresh, headers=headers, timeout=20, verify=False)
                            if resp.status_code == 200 and resp.text:
                                content = resp.text
                                base = str(getattr(resp, 'url', '') or fresh)
                                raw_url = fresh
                    except Exception:
                        pass
                if not content:
                    return [404, 'text/plain; charset=utf-8', 'Fetch Failed']
                try:
                    data = self._rewrite_m3u8(content, base, cid=cid)
                except Exception:
                    data = content
                if not data:
                    return [404, 'text/plain; charset=utf-8', 'Fetch Failed']
                return [200, 'application/vnd.apple.mpegurl', data]

            # ts / key / 其他二进制段
            try:
                resp = self.session.get(raw_url, headers=headers, timeout=20, verify=False)
                if resp.status_code != 200 or not resp.content:
                    return [404, 'text/plain; charset=utf-8', 'Fetch Failed']
                body = resp.content
            except Exception:
                return [404, 'text/plain; charset=utf-8', 'Fetch Failed']
            mime = 'video/MP2T'
            try:
                if body[:1] == b'G':
                    mime = 'video/MP2T'
                elif body[:4] == b'\x89PNG':
                    mime = 'image/png'
                elif body[:3] == b'\xff\xd8\xff':
                    mime = 'image/jpeg'
            except Exception:
                mime = 'application/octet-stream'
            if not isinstance(body, (bytes, bytearray)):
                try:
                    body = str(body).encode('utf-8')
                except Exception:
                    return [404, 'text/plain; charset=utf-8', 'Fetch Failed']
            else:
                body = bytes(body)
            return [200, mime, body]

        except Exception:
            return [500, 'text/plain; charset=utf-8', 'proxy error']
    
    def _rewrite_m3u8(self, content, base_url, cid=''):
        """重写M3U8：段/key 改写为本地代理地址，去掉 ENDLIST 保直播滚动"""
        if not content:
            return content

        parsed = urlparse(base_url)
        base_dir = base_url.rsplit('/', 1)[0] + '/'

        output = []
        uri_pattern = re.compile(r'URI=(["\'])(.*?)\1', re.I)
        lines = content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        stream_next = False

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            # 主表下一行是子 m3u8 地址
            if stream_next:
                stream_next = False
                abs_url = line if line.startswith(('http://', 'https://')) else urljoin(base_dir, line)
                output.append(self._get_proxy_url(abs_url, kind='m3u8', cid=cid))
                continue

            if line.startswith('#EXT-X-STREAM-INF'):
                output.append(raw_line)
                stream_next = True
                continue

            # 处理 EXT-X-KEY 中的 URI
            if line.startswith('#EXT-X-KEY'):
                def replace_uri(match):
                    uri = match.group(2)
                    if not uri.startswith(('http://', 'https://')):
                        if uri.startswith('/'):
                            uri = f"{parsed.scheme}://{parsed.netloc}{uri}"
                        else:
                            uri = urljoin(base_dir, uri)
                    proxy_uri = self._get_proxy_url(uri, kind='ts', cid=cid)
                    return f'URI={match.group(1)}{proxy_uri}{match.group(1)}'
                output.append(uri_pattern.sub(replace_uri, raw_line))
                continue

            # 去掉点播化标记，直播必须保持滚动
            if line.startswith('#EXT-X-ENDLIST') or line.startswith('#EXT-X-PLAYLIST-TYPE'):
                continue

            # 保留注释行
            if line.startswith('#'):
                output.append(raw_line)
                continue

            # 资源行：兼容带 ?txSecret= 等参数的分片
            low = line.split('?')[0].lower()
            if '.ts' in low or '.m3u8' in low or '.m3u' in low or '.m4s' in low or '.key' in low:
                if not line.startswith(('http://', 'https://')):
                    if line.startswith('/'):
                        line = f"{parsed.scheme}://{parsed.netloc}{line}"
                    else:
                        line = urljoin(base_dir, line)
                kind = 'm3u8' if ('.m3u8' in low or '.m3u' in low) else 'ts'
                output.append(self._get_proxy_url(line, kind=kind, cid=cid))
            else:
                output.append(raw_line)

        return '\n'.join(output) + '\n'

    def _get_proxy_url(self, upstream, kind='ts', cid=''):
        """生成代理链接：type 区分 m3u8/ts，带 cid 供 token 过期自救"""
        try:
            proxy_base = self.getProxyUrl()
        except Exception:
            return upstream
        if not proxy_base:
            return upstream
        separator = '&' if '?' in proxy_base else '?'
        url = f'{proxy_base}{separator}type={kind}&url={quote(str(upstream or ""), safe="")}'
        if str(cid or '').strip():
            url += f'&cid={quote(str(cid).strip(), safe="")}'
        return url
    
    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass
    
    def _empty_page(self):
        return {
            'page': 1,
            'pagecount': 1,
            'limit': 0,
            'total': 0,
            'list': [],
        }
    
    # ==================== 播放地址获取 ====================
    
    def _get_play_url(self, channel_id: int) -> str:
        """获取直播播放地址"""
        try:
            # 1. getParam
            resp = self.session.get(
                "https://tcdn-api.itouchtv.cn/getParam",
                timeout=10,
                verify=False
            )
            node = json.loads(resp.text)['node']
            
            # 2. wsnode
            wsnode = self._get_wsnode(node)
            
            # 3. 频道 API
            api_url = f"https://gdtv-api.gdtv.cn/api/tv/v2/tvChannel/{channel_id}?node={base64.b64encode(wsnode.encode()).decode()}"
            
            # 预检请求
            self.session.options(api_url, timeout=10, verify=False)
            
            # 签名请求
            t, sign = self._generate_signature(api_url)
            extra_headers = {
                'X-Itouchtv-Ca-Key': '89541943007407288657755311868534',
                'X-Itouchtv-Ca-Signature': sign,
                'X-Itouchtv-Ca-Timestamp': t,
                'X-Itouchtv-Client': 'WEB_M',
                'X-Itouchtv-Device-Id': 'WEBM_0',
            }
            
            resp = self.session.get(api_url, headers=extra_headers, timeout=15, verify=False)
            data = json.loads(resp.text)
            play_url_obj = json.loads(data['playUrl'])
            return play_url_obj.get('hd', '')
            
        except Exception as e:
            print(f"[广东荔枝网] 获取播放地址失败: {e}")
            return ''
    
    # ==================== WebSocket ====================
    
    def _get_wsnode(self, node: str) -> str:
        """通过WebSocket获取wsnode"""
        host, port, path = 'tcdn-ws.itouchtv.cn', 3800, '/connect'
        raw_key = bytes([random.randint(33, 126) for _ in range(16)])
        key = base64.b64encode(raw_key).decode()
        
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        sock = socket.create_connection((host, port), timeout=8)
        ssl_sock = context.wrap_socket(sock, server_hostname=host)
        
        upgrade = (f"GET {path} HTTP/1.1\r\n"
                   f"Host: {host}:{port}\r\n"
                   f"Upgrade: websocket\r\n"
                   f"Connection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\n"
                   f"Sec-WebSocket-Version: 13\r\n\r\n")
        ssl_sock.sendall(upgrade.encode())
        
        response = b''
        while b'\r\n\r\n' not in response:
            response += ssl_sock.recv(4096)
            
        if b'101' not in response.split(b'\r\n')[0]:
            raise Exception('WebSocket upgrade failed')
            
        msg = json.dumps({"route": "getwsparam", "message": node})
        ssl_sock.sendall(self._encode_ws_frame(msg))
        recv = self._recv_ws_frame(ssl_sock)
        ssl_sock.close()
        
        data = json.loads(recv.decode())
        if 'wsnode' not in data:
            raise Exception('wsnode missing in WebSocket response')
        return data['wsnode']
    
    def _encode_ws_frame(self, text: str) -> bytes:
        data = text.encode()
        length = len(data)
        mask = [random.randint(0, 255) for _ in range(4)]
        frame = bytearray()
        frame.append(0x81)
        if length < 126:
            frame.append(0x80 | length)
        elif length < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack('>H', length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack('>Q', length))
        frame.extend(mask)
        masked = bytes([data[i] ^ mask[i % 4] for i in range(length)])
        frame.extend(masked)
        return bytes(frame)
    
    def _recv_ws_frame(self, sock) -> bytes:
        header = sock.recv(2)
        if len(header) < 2:
            raise Exception('Incomplete WebSocket frame header')
        opcode = header[0] & 0x0f
        if opcode != 0x1:
            raise Exception(f'Unexpected opcode {opcode}')
        payload_len = header[1] & 0x7f
        if payload_len == 126:
            buf = sock.recv(2)
            payload_len = struct.unpack('>H', buf)[0]
        elif payload_len == 127:
            buf = sock.recv(8)
            payload_len = struct.unpack('>Q', buf)[0]
        data = b''
        while len(data) < payload_len:
            chunk = sock.recv(min(4096, payload_len - len(data)))
            if not chunk:
                break
            data += chunk
        return data
    
    # ==================== 签名 ====================
    
    def _generate_signature(self, url: str) -> tuple:
        t = str(int(time.time() * 1000))
        k = 'dfkcY1c3sfuw1Cii9DWj8UO3iQy2hqlDxyvDXd1oVMxwYVDSgeB6phO9eW1dfuwX'
        msg = f"GET\n{url}\n{t}\n"
        sign = base64.b64encode(hmac.new(k.encode(), msg.encode(), hashlib.sha256).digest()).decode()
        return t, sign