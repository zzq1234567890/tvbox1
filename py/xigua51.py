# -*- coding: utf-8 -*-
# 51吃瓜(cg51) TVBox Python 爬虫
# 六壳契约: TVBox / fongmi / 默影视 / 影视仓 / OK影视 / PickTV
import json
import re
import sys
import time
from base64 import b64decode, b64encode
from urllib.parse import quote, unquote, urlparse

import requests
from lxml import html as lxml_html

try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
except Exception:
    AES = None
    unpad = None

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    """数据链路: 发布站 appConfig 取线路 -> 首页/分类/搜索 -> 详情 data-config -> 直链 m3u8"""

    SITE = 'https://cg51.com'
    # 兜底线路: 允许 301 跳转, 探测时取最终可达域名
    STATIC_HOSTS = [
        'https://nutkvpuvh.oozzvqhzt.cc',
        'https://emxhyyqylw.rigxwsgw.com',
        'https://ktotmwbfwp.oozzvqhzt.cc',
    ]
    CONF_KEY = '0726001'
    IMG_KEY = b'f5d965df75336270'
    IMG_IV = b'97b60394abc2fbe1'
    UA = ('Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36')
    MEDIA_RE = re.compile(r'\.(m3u8|mp4|flv|ts|mkv|mov|m4v|webm)(\?|$)', re.I)

    # ---------------- 生命周期 ----------------
    def init(self, extend=""):
        self.extend = extend or ''
        self.host = ''
        self.timeout = 12
        self._live_cache = []
        self._live_cache_at = 0.0
        # H265 线路是 fMP4(EXT-X-MAP + .m4s)/HEVC, 部分壳与解码器不支持,
        # 默认不输出; 需要时在配置 extend 里写 {"h265": true} 显式启用。
        self.enable_h265 = self._read_flag(self.extend, 'h265', False)
        self.session = requests.Session()
        self.session.verify = False
        self.headers = {
            'User-Agent': self.UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        self.session.headers.update(self.headers)
        self.host = self._pick_host()
        self._sync_headers()

    def _read_flag(self, extend, name, default=False):
        """从 extend 读取布尔开关: 支持 dict 或 JSON 字符串, 也支持 "h265=1" 形式"""
        try:
            if isinstance(extend, dict):
                cfg = extend
            else:
                text = str(extend or '').strip()
                if text.startswith('{'):
                    cfg = json.loads(text)
                else:
                    cfg = {}
                    for part in text.replace('&', ',').split(','):
                        if '=' in part:
                            k, v = part.split('=', 1)
                            cfg[k.strip()] = v.strip()
            if name not in cfg:
                return default
            val = cfg.get(name)
            if isinstance(val, bool):
                return val
            return str(val).strip().lower() in ('1', 'true', 'yes', 'on')
        except Exception:
            return default

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass

    def getName(self):
        return '51吸瓜'

    def getDependence(self):
        return []

    def manualVideoCheck(self):
        return False

    def isVideoFormat(self, url):
        return bool(url and self.MEDIA_RE.search(str(url)))

    def action(self, action):
        return {}

    def proxy(self, param):
        return self.localProxy(param)

    def _log(self, msg):
        try:
            self.log(msg)
        except Exception:
            try:
                print(msg)
            except Exception:
                pass

    # ---------------- 线路 ----------------
    def _pick_host(self):
        """优先 extend 覆盖 / 宿主缓存, 其次发布站动态线路, 最后静态兜底"""
        candidates = []
        override = self._ext_host()
        cached = self._cache_get('host_51ok')
        for u in [override, cached] + self._live_hosts() + self.STATIC_HOSTS:
            u = (u or '').strip().rstrip('/')
            if u.startswith('http') and u not in candidates:
                candidates.append(u)
        for u in candidates:
            final = self._probe(u)
            if final:
                self._cache_set('host_51ok', final)
                return final
        self._log('线路探测全部失败, 退回静态首条')
        return candidates[0] if candidates else self.SITE

    def _ext_host(self):
        """ext 支持 {"host": "..."} / {"domain": "..."}"""
        try:
            cfg = self.extend
            if isinstance(cfg, str) and cfg.strip().startswith('{'):
                cfg = json.loads(cfg)
            if isinstance(cfg, dict):
                for k in ('host', 'domain', 'url'):
                    v = str(cfg.get(k) or '').strip()
                    if v.startswith('http'):
                        return v.rstrip('/')
        except Exception:
            pass
        return ''

    def _live_hosts(self):
        """解密发布站 appConfig: AES-CBC(sha256(key), iv=前16字节)

        结果在内存缓存 5 分钟: 换线时 _candidates() 会重复调用, 避免每次都打发布站。
        """
        now = time.time()
        if self._live_cache and now - self._live_cache_at < 300:
            return list(self._live_cache)
        hosts = self._fetch_live_hosts()
        if hosts:
            self._live_cache = list(hosts)
            self._live_cache_at = now
        return hosts

    def _fetch_live_hosts(self):
        try:
            page = self.session.get(self.SITE, headers=self.headers,
                                    timeout=8, allow_redirects=True).text
            m = re.search(r'(?m)^\s*window\.appConfig\s*=\s*\{', page)
            if not m:
                return []
            seg = page[m.start():]
            datas = re.findall(r'(?m)^\s*data:\s*"([^"]+)"', seg)
            keys = re.findall(r'(?m)^\s*key:\s*"([^"]+)"', seg)
            if not datas or AES is None:
                return []
            raw = b64decode(datas[-1])
            key_str = keys[-1] if keys else self.CONF_KEY
            key = self._sha256(key_str)
            plain = unpad(AES.new(key, AES.MODE_CBC, raw[:16]).decrypt(raw[16:]), 16)
            cfg = json.loads(plain.decode('utf-8'))
            hosts = []
            for field in ('domain', 'backup_domain'):
                for item in cfg.get(field) or []:
                    v = str(item.get('value') or '').strip().rstrip('/')
                    if v.startswith('http') and v not in hosts:
                        hosts.append(v)
            self._log('发布站线路: %s' % hosts)
            return hosts
        except Exception as e:
            self._log('发布站线路获取失败: %s' % e)
            return []

    def _sha256(self, text):
        try:
            from Crypto.Hash import SHA256
            return SHA256.new(text.encode()).digest()
        except Exception:
            import hashlib
            return hashlib.sha256(text.encode()).digest()

    def _probe(self, host):
        """探测线路: 必须返回内容页特征, 只认最终可达域名"""
        try:
            r = self.session.get(host + '/', headers=self.headers,
                                 timeout=6, allow_redirects=True)
            if r.status_code != 200:
                return ''
            text = r.content.decode('utf-8', 'replace')
            if 'navbar-nav' not in text and 'post-card' not in text:
                return ''
            parsed = urlparse(r.url)
            return '%s://%s' % (parsed.scheme, parsed.netloc)
        except Exception:
            return ''

    def _candidates(self):
        out = []
        for u in self._live_hosts() + self.STATIC_HOSTS:
            u = (u or '').strip().rstrip('/')
            if u.startswith('http') and u != self.host and u not in out:
                out.append(u)
        return out

    def _sync_headers(self):
        self.headers.update({'Referer': self.host + '/', 'Origin': self.host})
        self.session.headers.update(self.headers)

    def _sync_host(self, final_url):
        """跟随 301 后同步 host, 保证 Referer 与后续相对路径一致"""
        try:
            parsed = urlparse(final_url)
            origin = '%s://%s' % (parsed.scheme, parsed.netloc)
            if origin and origin != self.host:
                self.host = origin
                self._sync_headers()
                self._cache_set('host_51ok', origin)
        except Exception:
            pass

    def _cache_get(self, key):
        try:
            return self.getCache(key) or ''
        except Exception:
            return ''

    def _cache_set(self, key, value):
        try:
            self.setCache(key, value)
        except Exception:
            pass

    # ---------------- 请求 ----------------
    def _get(self, path, timeout=None):
        """当前线路取页面, 失败逐条换线; 全部失败抛异常(不伪装成功空列表)"""
        is_abs = str(path).startswith('http')
        try:
            return self._request(path if is_abs else self.host + path, timeout)
        except Exception as e:
            last = e
        for h in self._candidates():
            try:
                # 绝对 URL 换线时必须替换 origin, 否则仍在打原域
                text = self._request(self._swap_origin(path, h) if is_abs else h + path, timeout)
                self.host = h
                self._sync_headers()
                self._cache_set('host_51ok', h)
                self._log('换线成功: %s' % h)
                return text
            except Exception as e:
                last = e
                continue
        raise Exception('所有线路不可达: %s (%s)' % (path, last))

    def _swap_origin(self, url, host):
        """把绝对 URL 的 scheme://netloc 换成指定线路"""
        try:
            tail = urlparse(url)
            return '%s%s%s' % (host, tail.path or '/',
                               ('?' + tail.query) if tail.query else '')
        except Exception:
            return url

    def _request(self, url, timeout=None):
        r = self.session.get(url, headers=self.headers,
                             timeout=timeout or self.timeout, allow_redirects=True)
        if r.status_code != 200:
            raise Exception('HTTP %s' % r.status_code)
        ctype = (r.headers.get('Content-Type') or '').lower()
        if ctype and 'html' not in ctype and 'xml' not in ctype and 'text' not in ctype:
            raise Exception('非 HTML 响应: %s' % ctype)
        self._sync_host(r.url)
        return self._decode(r)

    def _decode(self, r):
        """按 BOM / meta charset / 强制 utf-8 逐级解码, 剔除 NUL。

        部分线路会返回 UTF-16/32 或夹带 NUL 的响应; 直接 utf-8 解码后
        字符串以 '<\\x00\\x00\\x00' 开头, libxml2 会判成 UCS4LE 并抛
        XMLSyntaxError: encoding not supported USC4 little endian。
        """
        body = r.content or b''
        if not body:
            return ''
        return self._decode_bytes(body, r).replace('\x00', '')

    def _decode_bytes(self, body, r):
        """BOM > 无 BOM 宽字符 > 严格 UTF-8 > 声明 charset > 容错 UTF-8"""
        for bom, enc in ((b'\xff\xfe\x00\x00', 'utf-32-le'),
                         (b'\x00\x00\xfe\xff', 'utf-32-be'),
                         (b'\xff\xfe', 'utf-16-le'),
                         (b'\xfe\xff', 'utf-16-be')):
            if body[:len(bom)] == bom:
                try:
                    return body[len(bom):].decode(enc)
                except Exception:
                    break
        if b'\x00' in body[:4096]:
            enc = self._wide_kind(body[:4096])
            if enc:
                try:
                    text = body.decode(enc)
                    if chr(0xFFFD) not in text[:2000]:
                        return text
                except Exception:
                    pass
        # 站点实际为 UTF-8: 严格解码成功即采信, 避免被错误的 charset 声明带偏
        try:
            return body.decode('utf-8')
        except Exception:
            pass
        for enc in self._encoding_chain(body, r):
            try:
                text = body.decode(enc)
            except Exception:
                continue
            if chr(0xFFFD) not in text[:2000]:
                return text
        return body.decode('utf-8', 'replace')

    def _wide_kind(self, head):
        """无 BOM 时按 NUL 分布判断宽字符字节序, 只认 '<' 开头的页面"""
        if len(head) < 8:
            return ''
        if head[:1] == b'<' and head[1:4] == b'\x00\x00\x00':
            return 'utf-32-le'
        if head[:3] == b'\x00\x00\x00' and head[3:4] == b'<':
            return 'utf-32-be'
        if head[:1] == b'<' and head[1:2] == b'\x00':
            return 'utf-16-le'
        if head[:1] == b'\x00' and head[1:2] == b'<':
            return 'utf-16-be'
        return ''

    def _encoding_chain(self, body, r):
        """候选解码顺序: HTTP charset > meta charset > utf-8"""
        chain = []
        header = ''
        try:
            header = (r.headers.get('Content-Type') or '').lower()
        except Exception:
            pass
        m = re.search(r'charset=([\w-]+)', header)
        if m:
            chain.append(m.group(1))
        head = body[:4096].decode('ascii', 'ignore')
        m = re.search(r'charset=["\']?([\w-]+)', head, re.I)
        if m:
            chain.append(m.group(1).lower())
        chain.append('utf-8')
        out = []
        for enc in chain:
            enc = (enc or '').strip().lower()
            if enc and enc not in out and enc not in ('gb2312',):
                out.append(enc)
        return out

    def _doc(self, text):
        """HTML 解析: 一律转 bytes 并显式指定 utf-8, 不走 lxml 的 Unicode 路径。

        Chaquopy 内置的旧版 lxml 在 fromstring(str) 时走 _parseUnicodeDoc,
        会把非 ASCII 文本误判成 UCS4LE 并抛
        XMLSyntaxError: encoding not supported USC4 little endian。
        新版 lxml 的该路径已修好, 所以主机侧无法复现, 只能在调用方式上规避:
        先把 str 编码成 utf-8 bytes, 再交给 parser(encoding='utf-8')。
        """
        if not text:
            raise Exception('空页面')
        text = str(text).replace('\x00', '')
        if not text.strip():
            raise Exception('空页面')
        problem = None
        for candidate in (text, re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f]', ' ', text)):
            try:
                body = candidate.encode('utf-8', 'replace')
            except Exception:
                body = candidate.encode('utf-8', 'ignore')
            # 无标签的纯文本/JSON 体: 包一层空文档, 避免 ParserError: Document is empty
            if b'<' not in body:
                body = b'<html><body></body></html>'
            try:
                return lxml_html.fromstring(body, parser=self._html_parser())
            except Exception as e:
                problem = e
        raise Exception('HTML 解析失败: %s' % problem)

    def _html_parser(self):
        """宽松 HTML 解析器: 显式 utf-8, 允许错误恢复。

        必须用 lxml.html.HTMLParser 而非 etree.HTMLParser:
        前者产出的元素带 text_content(), 后者只是裸 _Element。
        每次新建, 避免解析器内部状态跨请求残留。
        """
        try:
            return lxml_html.HTMLParser(encoding='utf-8', recover=True, huge_tree=True)
        except TypeError:
            return lxml_html.HTMLParser(encoding='utf-8')

    def _abs(self, url):
        url = str(url or '').strip()
        if not url:
            return ''
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return self.host + url
        return url

    # ---------------- 解析工具 ----------------
    def _text(self, nodes):
        if not nodes:
            return ''
        return ' '.join((nodes[0].text_content() or '').split())

    def _meta(self, doc, name):
        nodes = doc.xpath('//meta[@property=$n or @name=$n]/@content', n=name)
        return ' '.join((nodes[0] or '').split()) if nodes else ''

    def _desc(self, doc):
        """简介: 正文段落拼接(站点 og:description 只截 150 字), 过滤推广段"""
        parts = []
        for p in doc.xpath('//*[@itemprop="articleBody"]//p'):
            text = ' '.join((p.text_content() or '').split())
            if len(text) < 40:
                continue
            # 官方地址/邮箱/APP 推广段不是剧情简介
            if ('http' in text and len(text) < 200) or '邮箱' in text:
                continue
            if text in parts:
                continue
            parts.append(text)
            if len(' '.join(parts)) >= 600:
                break
        text = ' '.join(parts).strip()
        if text:
            return text[:800]
        return self._meta(doc, 'og:description') or self._meta(doc, 'description')

    def _card_pic(self, node):
        for xp in ('.//*[@z-bg-loader-url]/@z-bg-loader-url',
                   './/img[@z-image-loader-url]/@z-image-loader-url',
                   './/img[@data-original]/@data-original'):
            v = node.xpath(xp)
            if v and v[0].strip():
                return v[0].strip()
        v = node.xpath('.//img/@src')
        if v and v[0].startswith('http'):
            return v[0].strip()
        for script in node.xpath('.//script/text()'):
            m = re.search(r"loadBannerDirect\(\s*'([^']+)'", script or '')
            if m:
                return m.group(1)
        return ''

    def _parse_nav(self, doc):
        """导航: 直链 li 与 button+下拉 ul 两种形态, 仅收站内 /category/ 项"""
        out, seen = [], set()
        lis = doc.xpath('//ul[contains(@class,"navbar-nav") and contains(@class,"mr-auto")]/li')
        for li in lis:
            links = li.xpath('.//ul//a[@href]') or li.xpath('./a[@href]')
            for a in links:
                href = (a.get('href') or '').strip()
                m = re.match(r'^/category/([A-Za-z0-9_-]+)/?$', href)
                if not m:
                    continue
                name = ' '.join((a.text_content() or '').split())
                if not name or name == '首页':
                    continue
                tid = m.group(1)
                if tid in seen:
                    continue
                seen.add(tid)
                out.append({'type_id': tid, 'type_name': name})
        return out

    def _parse_cards(self, doc, xpath):
        """列表卡片: 仅收 /archives/ 详情链接, 排除外链广告卡"""
        videos = []
        seen = set()
        for a in doc.xpath(xpath):
            href = (a.get('href') or '').strip()
            if not href.startswith('/archives/') or href in seen:
                continue
            name = self._text(a.xpath('.//h2[contains(@class,"post-card-title")]'))
            if not name:
                name = ' '.join((a.get('title') or '').split())
            if not name:
                continue
            remark = self._text(a.xpath('.//*[@itemprop="datePublished"]')).rstrip('•· ')
            if not remark:
                remark = self._text(a.xpath('.//*[contains(@class,"wraps")]'))
            seen.add(href)
            pic = self._card_pic(a)
            videos.append({
                'vod_id': href,
                'vod_name': name,
                'vod_pic': self._img_proxy(pic) if pic else '',
                'vod_remarks': remark,
                'style': {'type': 'rect', 'ratio': 1.33},
            })
        return videos

    def _pagecount(self, doc, pg):
        """分页: 取 page-navigator 中最大数字页; 无分页视为单页"""
        nums = []
        for href in doc.xpath('//*[contains(@class,"page-navigator")]//a/@href'):
            for n in re.findall(r'/(\d+)/?(?:\?|$)', href or ''):
                try:
                    nums.append(int(n))
                except Exception:
                    continue
        nums.append(pg)
        return max(nums)

    # ---------------- 首页 ----------------
    def homeContent(self, filter):
        try:
            doc = self._doc(self._get('/'))
            classes = self._parse_nav(doc)
            lst = self._parse_cards(doc, '//*[@id="index"]//article/a[@href]')
            if not lst:
                raise Exception('首页无卡片')
            return {'class': classes, 'list': lst[:30], 'filters': {}}
        except Exception as e:
            self._log('homeContent: %s' % e)
            raise

    def homeVideoContent(self):
        try:
            doc = self._doc(self._get('/'))
            return {'list': self._parse_cards(doc, '//*[@id="index"]//article/a[@href]')[:30]}
        except Exception as e:
            self._log('homeVideoContent: %s' % e)
            raise

    # ---------------- 分类 ----------------
    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(str(pg or '1').strip() or 1)
        except Exception:
            page = 1
        tid = str(tid or '').strip()
        if not tid:
            return {'list': [], 'page': page, 'pagecount': 1, 'limit': 0}
        if tid.startswith('/'):
            path = tid.rstrip('/')
        elif tid.startswith('tag/'):
            path = '/' + tid.rstrip('/')
        else:
            path = '/category/%s' % tid.strip('/')
        path = path if page <= 1 else '%s/%d' % (path, page)
        path += '/'
        try:
            doc = self._doc(self._get(path))
            videos = self._parse_cards(doc, '//*[@id="archive"]//article/a[@href]')
            return {
                'list': videos,
                'page': page,
                'pagecount': self._pagecount(doc, page),
                'limit': len(videos),
            }
        except Exception as e:
            self._log('categoryContent: %s' % e)
            raise

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(str(pg or '1').strip() or 1)
        except Exception:
            page = 1
        word = str(key or '').strip()
        if not word:
            return {'list': [], 'page': page, 'pagecount': 1, 'limit': 0}
        kw = quote(word)
        path = '/search/%s/' % kw if page <= 1 else '/search/%s/%d/' % (kw, page)
        doc = self._doc(self._get(path))
        videos = self._parse_cards(doc, '//*[@id="archive"]//article/a[@href]')
        return {
            'list': videos,
            'page': page,
            'pagecount': self._pagecount(doc, page),
            'limit': len(videos),
        }

    # ---------------- 详情 ----------------
    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = str(vid or '').strip()
        url = self._abs(vid)
        doc = self._doc(self._get(url))
        title = self._text(doc.xpath('//h1[contains(@class,"post-title")]')) or self._meta(doc, 'og:title')
        pic = ''
        imgs = doc.xpath('//*[@itemprop="articleBody"]//img[@z-image-loader-url]/@z-image-loader-url')
        if not imgs:
            imgs = doc.xpath('//*[@itemprop="articleBody"]//img/@src')
        for cand in imgs:
            cand = (cand or '').strip()
            if cand.startswith('http'):
                pic = cand
                break
        desc = self._desc(doc)
        play_from, play_url = self._play_lines(doc)
        if not play_url:
            play_from, play_url = self._child_episodes(doc)
        vod = {
            'vod_id': vid,
            'vod_name': title or vid,
            'vod_pic': self._img_proxy(pic) if pic else '',
            'vod_content': desc,
            'vod_play_from': play_from,
            'vod_play_url': play_url,
        }
        return {'list': [vod]}

    def _play_lines(self, doc):
        """详情页 dplayer data-config -> 直链。

        H265 是 fMP4(EXT-X-MAP + .m4s)/HEVC, 部分壳的播放器与解码器不支持,
        出现时表现为点击无声黑屏。默认只输出 H264 的 TS 线路;
        需要 H265 时在源配置 extend 里写 {"h265": true}。
        """
        mains, h265s = [], []
        for node in doc.xpath('//*[contains(@class,"dplayer")][@data-config]'):
            try:
                cfg = json.loads(node.get('data-config') or '{}')
            except Exception:
                continue
            url = str(((cfg.get('video') or {}).get('url')) or '').strip()
            if url.startswith('http') and url not in mains:
                mains.append(url)
            h = str(((cfg.get('video_h265') or {}).get('url')) or '').strip()
            if h.startswith('http') and h not in h265s:
                h265s.append(h)
        froms, urls = [], []
        if mains:
            froms.append('51吸瓜')
            urls.append('#'.join('视频%d$%s' % (i, u) for i, u in enumerate(mains, 1)))
        if h265s and getattr(self, 'enable_h265', False):
            froms.append('51吸瓜H265')
            urls.append('#'.join('视频%d$%s' % (i, u) for i, u in enumerate(h265s, 1)))
        return '$$$'.join(froms), '$$$'.join(urls)

    def _child_episodes(self, doc):
        """榜单/合集页: 正文内子文章按图片链接顺序拆成集数"""
        eps, seen = [], set()
        for img in doc.xpath('//*[@itemprop="articleBody"]//img[@z-image-loader-url]'):
            anc = img.xpath('ancestor::a[@href][1]')
            if not anc:
                continue
            href = (anc[0].get('href') or '').strip()
            if not href.startswith('/archives/') or href in seen:
                continue
            name = ' '.join((img.get('alt') or img.get('title') or '').split())
            name = name[:60] if name else '第%d集' % (len(eps) + 1)
            seen.add(href)
            eps.append('%s$%s' % (name.replace('$', ' ').replace('#', ' '), self._abs(href)))
        if not eps:
            return '', ''
        return '51吸瓜', '#'.join(eps)

    # ---------------- 播放 ----------------
    def _play_header(self):
        return {'User-Agent': self.UA, 'Referer': self.host + '/'}

    def playerContent(self, flag, id, vipFlags=None):
        raw = str(id or '').strip()
        if not raw:
            return {'parse': 0, 'url': '', 'header': {}}
        if self.MEDIA_RE.search(raw):
            return {'parse': 0, 'url': raw, 'header': self._play_header()}
        url = self._abs(raw)
        try:
            doc = self._doc(self._get(url))
            _, play_url = self._play_lines(doc)
            if play_url:
                first = play_url.split('$$$')[0].split('#')[0].split('$')[-1]
                if first.startswith('http'):
                    return {'parse': 0, 'url': first, 'header': self._play_header()}
        except Exception as e:
            self._log('playerContent: %s' % e)
        return {'parse': 1, 'url': url, 'header': self._play_header()}

    # ---------------- 图片代理 ----------------
    def _img_proxy(self, url):
        """封面为 AES 加密流, 走本机代理解密; 无 proxy 能力时退回原图"""
        url = (url or '').strip()
        if not url:
            return ''
        try:
            base = self.getProxyUrl()
        except Exception:
            return url
        return '%s&url=%s&type=img' % (base, self.e64(url))

    def e64(self, text):
        """URL-safe base64: '+' '/' '=' 在 proxy query 中会被拆散, 统一替换"""
        try:
            raw = b64encode(str(text).encode('utf-8')).decode('utf-8')
            return raw.replace('+', '-').replace('/', '_').rstrip('=')
        except Exception:
            return ''

    def d64(self, text):
        """兼容 URL-safe 与标准 base64"""
        try:
            s = unquote(str(text)).strip()
            s = s.replace('-', '+').replace('_', '/')
            s += '=' * (-len(s) % 4)
            return b64decode(s).decode('utf-8', 'replace')
        except Exception:
            return ''

    def localProxy(self, param):
        try:
            p = param or {}
            raw = str(p.get('url') or p.get('pdid') or '').strip()
            if not raw:
                return [404, 'text/plain', '']
            url = raw if raw.startswith('http') else self.d64(raw)
            if not url.startswith('http'):
                return [404, 'text/plain', '']
            r = self.session.get(url, headers={'User-Agent': self.UA,
                                               'Referer': self.host + '/'},
                                 timeout=self.timeout, allow_redirects=True)
            if r.status_code != 200 or not r.content:
                return [r.status_code or 502, 'text/plain', '']
            data = r.content
            if data[:3] == b'\xff\xd8\xff' or data[:8] == b'\x89PNG\r\n\x1a\n' \
                    or data[:6] in (b'GIF87a', b'GIF89a') or data[:4] == b'RIFF':
                return [200, self._mime(data), data]
            plain = self._aes_img(data)
            if plain:
                return [200, self._mime(plain), plain]
            return [200, self._mime(data), data]
        except Exception as e:
            self._log('localProxy: %s' % e)
            return [500, 'text/plain', '']

    def _aes_img(self, data):
        if AES is None:
            return b''
        try:
            return unpad(AES.new(self.IMG_KEY, AES.MODE_CBC, self.IMG_IV).decrypt(data), 16)
        except Exception:
            return b''

    def _mime(self, data):
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return 'image/png'
        if data[:6] in (b'GIF87a', b'GIF89a'):
            return 'image/gif'
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return 'image/webp'
        if data[:2] == b'BM':
            return 'image/bmp'
        return 'image/jpeg'