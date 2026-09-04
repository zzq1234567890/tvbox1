#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 山有木兮影视 TVBox spider (film.symx.club)
# 依赖: 158 验证码解锁微服务 http://192.168.0.158:7799/solve
# 链路: 签名HMAC → detail/search/parse → 401时自动过滑块(服务端) → m3u8直链

try:
    from base.spider import Spider
except Exception:
    class Spider:
        def __init__(self):
            pass

import json
import re
import time
import hmac
import hashlib
import urllib.request
import urllib.parse

BASE = 'https://film.symx.club'
UA = ('Mozilla/5.0 (Linux; Android 11; Pixel 5) '
      'AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/120.0.0.0 Mobile Safari/537.36')
GWKEY = '0x1A2B3C4D5E6F7A8B9C'
SALT_ENC = '5c0b5d396d3158'
SOLVERS = ['http://192.168.0.158:7799/solve', 'http://127.0.0.1:7799/solve']

CATS = [(1, '电视剧'), (2, '电影'), (3, '综艺'), (4, '动漫'), (5, '短剧'),
        ('r_quality', '高分榜'), ('r_new', '最新'), ('r_list', '热播榜')]


def gw(e):
    o = ''
    for i in range(0, len(e), 2):
        o += chr(int(e[i:i + 2], 16) ^ ord(GWKEY[(i // 2) % len(GWKEY)]))
    return o


def hwe():
    raw = str(int(time.time() * 1000))
    return raw[:-1] + str(sum(int(c) for c in raw[:-1]) % 10)


def http_get(url, headers, timeout=15):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), r.read()
    except Exception as e:
        code = getattr(e, 'code', 0)
        body = b''
        try:
            body = e.read()
        except Exception:
            pass
        return code, body


def http_post_json(url, headers, obj, timeout=15):
    data = json.dumps(obj).encode('utf-8')
    h = dict(headers)
    h['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), r.read()
    except Exception as e:
        code = getattr(e, 'code', 0)
        body = b''
        try:
            body = e.read()
        except Exception:
            pass
        return code, body


class Spider(Spider):

    def __init__(self):
        self.salt = gw(SALT_ENC)
        self.cid = ''
        self.token = ''
        self.token_ts = 0
        self.cookie = ''
        self.name = '山有木兮'

    def getName(self):
        return self.name

    def init(self, extend=''):
        try:
            if extend:
                cfg = json.loads(extend)
                if cfg.get('solver'):
                    SOLVERS.insert(0, cfg['solver'])
        except Exception:
            pass

    def homeContent(self, filter):
        cates = [{'type_id': str(cid), 'type_name': name} for cid, name in CATS]
        result = {'class': cates}
        if filter:
            result['filters'] = self._filters()
        return result

    def homeVideoContent(self):
        j = self.api('film/category')
        vids = []
        if j and j.get('data'):
            for cat in j['data'][:2]:
                for f in cat.get('filmList', [])[:5]:
                    vids.append(self._fmt(f))
        return {'list': vids}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        ext = extend or {}
        # 榜单类走 rank 接口(无分页)
        if tid in ('r_quality', 'r_new', 'r_list'):
            api = {'r_quality': 'film/rank/quality',
                   'r_new': 'film/rank/new',
                   'r_list': 'film/rank/list'}[tid]
            j = self.api(api)
            raw = ((j or {}).get('data')) or []
            if isinstance(raw, dict):
                raw = raw.get('list') or []
            films = []
            for it in raw:
                if isinstance(it, dict) and it.get('filmRankList'):
                    # rank/list: 按分类分组, 展平
                    films.extend(it.get('filmRankList') or [])
                elif isinstance(it, dict):
                    films.append(it)
            per = 20
            return {'list': [self._fmt(f) for f in films[(pg - 1) * per:
                                                         pg * per]],
                    'page': pg,
                    'pagecount': max(1, (len(films) + per - 1) // per),
                    'limit': per, 'total': len(films)}
        q = ('film/category/list?area=%s&categoryId=%s&language=%s'
             '&pageNum=%d&pageSize=20&sort=%s&year=%s'
             % (urllib.parse.quote(ext.get('area', '') or ''), tid,
                urllib.parse.quote(ext.get('language', '') or ''), pg,
                ext.get('sort') or 'updateTime',
                urllib.parse.quote(str(ext.get('year', '') or ''))))
        j = self.api(q)
        data = (j or {}).get('data') or {}
        films = data.get('list') if isinstance(data, dict) else (data or [])
        films = films or []
        total = data.get('total') if isinstance(data, dict) else len(films)
        try:
            total = int(total)
        except Exception:
            total = len(films) * pg
        return {'list': [self._fmt(f) for f in films], 'page': pg,
                'pagecount': max(1, (total + 19) // 20),
                'limit': 20, 'total': total}

    def _filters(self):
        """按分类拉 filter 选项(area/year/language/sort)"""
        out = {}
        for cid, _name in CATS:
            if not str(cid).isdigit():
                continue
            j = self.api('film/category/filter?categoryId=%s' % cid)
            d = (j or {}).get('data') or {}
            groups = []
            for key, okey, label in (('sort', 'sortOptions', '排序'),
                                     ('area', 'areaOptions', '地区'),
                                     ('year', 'yearOptions', '年份'),
                                     ('language', 'languageOptions', '语言')):
                opts = d.get(okey) or []
                if not opts:
                    continue
                vals = [{'n': '全部', 'v': ''}]
                for o in opts:
                    if isinstance(o, dict):
                        vals.append({'n': o.get('label') or o.get('value'),
                                     'v': o.get('value')})
                    else:
                        vals.append({'n': str(o), 'v': str(o)})
                groups.append({'key': key, 'name': label, 'value': vals})
            if groups:
                out[str(cid)] = groups
        return out

    def detailContent(self, ids):
        fid = ids[0]
        j = self.api('film/detail?id=%s' % fid)
        d = (j or {}).get('data') or {}
        play_from = []
        play_url = []
        for pl in d.get('playLineList') or []:
            pn = pl.get('playerName') or ('线路%s' % pl.get('playerId'))
            play_from.append(pn)
            eps = ['%s$%s' % (ln.get('name'), ln.get('id'))
                   for ln in pl.get('lines') or []]
            play_url.append('#'.join(eps))
        vod = self._fmt(d)
        vod.update({
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url),
            'vod_director': d.get('director') or '',
            'vod_actor': d.get('actor') or '',
            'vod_content': d.get('blurb') or '',
            'vod_year': str(d.get('year') or ''),
        })
        return {'list': [vod]}

    def searchContent(self, key, quick, pg='1'):
        pg = int(pg or 1)
        j = self.api('film/search?keyword=%s&pageNum=%d&pageSize=20'
                     % (urllib.parse.quote(key), pg))
        data = (j or {}).get('data') or {}
        films = data.get('list') if isinstance(data, dict) else (data or [])
        films = films or []
        total = data.get('total') if isinstance(data, dict) else len(films)
        try:
            total = int(total)
        except Exception:
            total = len(films)
        pc = max(1, (total + 19) // 20)
        return {'list': [self._fmt(f) for f in films],
                'page': pg, 'pagecount': pc, 'limit': 20, 'total': total}

    def playerContent(self, flag, id, vipFlags):
        m3u8 = self.parse_line(id)
        if not m3u8:
            return {'parse': 0, 'playUrl': '', 'url': '',
                    'header': {'User-Agent': UA}}
        return {'parse': 0, 'playUrl': '', 'url': m3u8,
                'header': {'User-Agent': UA, 'Referer': BASE + '/'}}

    def isVideoFormat(self, url):
        return True

    def manualVideoCheck(self):
        return False

    # ---------- 内部 ----------
    def _fmt(self, f):
        return {'vod_id': str(f.get('id')),
                'vod_name': f.get('name') or '',
                'vod_pic': f.get('cover') or '',
                'vod_remarks': str(f.get('updateStatus') or ''),
                'vod_score': str(f.get('doubanScore') or '')}

    def _headers(self, api_path, with_token=True):
        # 签名路径规则: 前导斜杠 + 去掉 query
        p = api_path.split('?')[0]
        if not p.startswith('/'):
            p = '/' + p
        ts = hwe()
        u = ts + 'symx_' + self.salt + p
        u = u.replace('1', 'i').replace('0', 'o').replace('5', 's')
        sign = hmac.new(self.salt.encode(), u.encode(),
                        hashlib.sha256).hexdigest()
        h = {'User-Agent': UA, 'X-Platform': 'web', 'Origin': BASE,
             'Referer': BASE + '/', 'Accept': 'application/json, text/plain, */*',
             'X-Client-Id': self.cid or '00000000000000000000000000000000',
             'X-Timestamp': ts, 'X-Sign-X': sign}
        if with_token and self.token:
            h['X-Verify-Token'] = self.token
        if self.cookie:
            h['Cookie'] = self.cookie
        return h

    def api(self, api_path, retried=False):
        code, body = http_get(BASE + '/api/' + api_path,
                              self._headers(api_path))
        # 403=种cookie / 502=服务端瞬时超时 → 退避重打(该站 502 较频繁)
        for i in range(4):
            if code in (403, 502, 504, 500, 0):
                time.sleep(0.5 + i * 0.8)
                code, body = http_get(BASE + '/api/' + api_path,
                                      self._headers(api_path))
            else:
                break
        if code == 200:
            try:
                j = json.loads(body.decode('utf-8'))
                if j.get('code') == 200:
                    return j
                if j.get('code') == 1004 and not retried:
                    self.ensure_token(force=True)
                    return self.api(api_path, retried=True)
            except Exception:
                pass
        if code in (401, 403) and not retried:
            self.ensure_token(force=True)
            return self.api(api_path, retried=True)
        return None

    def ensure_token(self, force=False):
        # token 有效期内复用; force=True 时强制换新(401/1004 场景)
        if (not force) and self.token and time.time() - self.token_ts < 200:
            return True
        for u in SOLVERS:
            try:
                code, body = http_get(u, {'User-Agent': UA}, timeout=240)
                if code == 200:
                    j = json.loads(body.decode('utf-8'))
                    if j.get('ok') and j.get('token'):
                        self.token = j['token']
                        self.cid = j.get('cid') or ''
                        self.cookie = j.get('cookie') or ''
                        self.token_ts = time.time()
                        return True
            except Exception:
                continue
        # solver 拿不到(冷却中): 清掉旧 token 避免带着废票反复被拒
        if force:
            self.token = ''
            self.token_ts = 0
        return False

    def parse_line(self, line_id):
        """取真实播放地址。
        本站行为: 首次请求常回 403(带自跳转HTML, 用于种 cookie) → 重打即 200;
        401/1004 = verify token 失效 → 强制换新 token 再打;
        502 = 服务端瞬时故障 → 退避重试。
        """
        api_path = 'line/play/parse?lineId=%s' % line_id
        for attempt in range(6):
            code, body = http_get(BASE + '/api/' + api_path,
                                  self._headers(api_path))
            if code == 200:
                try:
                    j = json.loads(body.decode('utf-8'))
                    if j.get('code') == 200 and j.get('data'):
                        return j.get('data')
                    if j.get('code') in (1004, 401):
                        self.ensure_token(force=True)
                        continue
                except Exception:
                    pass
                # code!=200 的业务错误: 稍等重试
                time.sleep(0.8)
                continue
            if code == 403:
                # 种 cookie 后立即重打(不计入换 token)
                time.sleep(0.4)
                continue
            if code == 401:
                self.ensure_token(force=True)
                continue
            if code in (500, 502, 504, 0):
                time.sleep(0.6 + attempt * 0.8)
                continue
            break
        return ''
