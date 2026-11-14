# -*- coding: utf-8 -*-
import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from base64 import b64encode, b64decode
from urllib.parse import quote

from base.spider import Spider


class Spider(Spider):

    def init(self, extend=""):
        # 抓包固定参数（com.dongyu.movies 1.0.0）
        self.device_id = "5218a2f5f561aaad"
        self.app_id = "10003"
        self.app_version = "1.0.0"
        self.app_key = "00823f50736454de37cfef8b260c9e35"
        self.app_secret = "aca767d257733a3d97fe125bb9150feb"
        # apiVersion 头 = 服务端唯一硬门禁（缺头即报"只接收POST请求"）
        self.api_version = "w2yj3m9b"
        self.headers = {
            'User-Agent': 'okhttp/4.9.0',
            'apiVersion': self.api_version,
            # 以下为贴近真机的无害静态头（实测均可删，防服务端加严）
            'appId': self.app_id,
            'version': self.app_version,
            'package': 'com.dongyu.movies',
            'deviceId': self.device_id,
            'AppKey': self.app_key,
            'AppSecret': self.app_secret,
            'appName': 'lanlan',
        }
        # 灰度下发的业务域名（抓包实测）
        self.hosts = ['http://134.175.188.60:2025', 'https://ngsp2.10000.im']
        self.host = self.hosts[0]
        self.M = 'Tcgomtsdwz'

    def getName(self):
        return "南瓜影视"

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv|mkv|ts)', url or '', re.I))

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    # ---------------- 首页 ----------------
    def homeContent(self, filter):
        hdata = self.getdata('/api.php/%s/gmsugsctlmjfdjeo' % self.M, {'tid': '0'})
        d = hdata['data'] or {}
        vlist = d.get('tj', []) or []
        sub_data = d.get('sub_data', []) or []
        classes = []
        filters = {}
        for i in sub_data:
            classes.append({'type_id': str(i.get('type_id')), 'type_name': i.get('type_name')})
            dl = i.get('data') or []
            for it in dl:
                it['type_id'] = i.get('type_id')
            vlist.extend(dl)
        if classes:
            with ThreadPoolExecutor(max_workers=min(len(classes), 8)) as executor:
                for cid, ft in executor.map(self.getf, classes):
                    if len(ft):
                        filters[cid] = ft
        return {'class': classes, 'filters': filters, 'list': vlist}

    def homeVideoContent(self):
        try:
            data = self.getdata('/api.php/%s/hntyjobzaoyrfynh' % self.M, {'tid': '0', 'pg': '1'})
            return {'list': data.get('data') or []}
        except Exception:
            return {'list': []}

    # ---------------- 分类 ----------------
    def categoryContent(self, tid, pg, filter, extend):
        body = {"tid": tid, "pg": pg}
        if extend:
            for k in ('area', 'lang', 'year', 'type', 'orderBy'):
                v = extend.get(k)
                if v:
                    body[k] = v
        data = self.getdata('/api.php/%s/gbuvymmzcnpozcnj' % self.M, body)
        dd = (data.get('data') or {})
        lst = dd.get('data') or []
        limit = len(lst) or 50
        pagecount = int(pg or 1) + 1 if lst else int(pg or 1)
        return {'list': lst, 'page': int(pg or 1), 'pagecount': pagecount,
                'limit': limit, 'total': pagecount * limit}

    def getf(self, mp):
        ft, cid = [], str(mp['type_id'])
        try:
            fdata = self.getdata('/api.php/%s/gbuvymmzcnpozcnj' % self.M, {'tid': cid, 'pg': '1'})
            dy = ['area', 'year', 'lang', 'type']
            fd = (fdata.get('data') or {}).get('type_extend', {}) or {}
            for dkey in fd:
                if dkey in dy and fd[dkey]:
                    values = [v.strip() for v in str(fd[dkey]).split(",") if v.strip()]
                    if values:
                        ft.append({"key": dkey, "name": dkey,
                                   "value": [{"n": v, "v": v} for v in values]})
            return (cid, ft)
        except Exception:
            return (cid, ft)

    # ---------------- 详情 ----------------
    def detailContent(self, ids):
        try:
            data = self.getdata('/api.php/%s/yfpnncbqeejpzcbr' % self.M, {'ids': ids[0]})
        except Exception:
            return {'list': []}
        vod = data.get('data') or {}
        if not isinstance(vod, dict) or not vod.get('vod_name'):
            return {'list': []}
        plist = []
        names = []
        play_urls = vod.get('vod_play_url') or []
        if isinstance(play_urls, dict):
            play_urls = [play_urls]
        if not isinstance(play_urls, list):
            play_urls = []
        for i in play_urls:
            if not isinstance(i, dict):
                continue
            ulist = []
            name = (i.get('name') or i.get('id') or '').split(' ')[0]
            if not name:
                name = i.get('id') or '线路'
            names.append(name)
            jdata = {'parse': ''}
            p = i.get('parse')
            if isinstance(p, list) and len(p):
                jdata['parse'] = self.e64(json.dumps(p, ensure_ascii=False))
            elif isinstance(p, str) and p:
                jdata['parse'] = self.e64(json.dumps([p], ensure_ascii=False))
            for j in (i.get('data') or []):
                u = j.get('url') or j.get('translation_url') or ''
                u = re.sub(r'^3abfc0://', '', u)
                if not u:
                    continue
                jdata['url'] = u
                ulist.append(f'{j.get("name") or ""}${self.e64(json.dumps(jdata, ensure_ascii=False))}')
            if ulist:
                plist.append('#'.join(ulist))
        vod['vod_play_from'] = '$$$'.join(names)
        vod['vod_play_url'] = '$$$'.join(plist)
        vod.pop('cover_list', None)
        return {'list': [vod]}

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick, pg="1"):
        body = {"wd": key, "tid": "0", "pg": pg}
        data = self.getdata('/api.php/%s/fbyvgecswvxykjzy' % self.M, body)
        dl = data.get('data') or []
        if isinstance(dl, dict):
            dl = dl.get('list') or dl.get('data') or []
        vlist = []
        for i in dl:
            if isinstance(i, dict):
                i.pop('vod_play_from', None)
                vlist.append(i)
        return {'list': vlist, 'page': int(pg or 1),
                'pagecount': int(pg or 1) + 1 if vlist else int(pg or 1)}

    # ---------------- 播放 ----------------
    def playerContent(self, flag, id, vipFlags):
        if id and '$' in id:
            id = id.split('$')[-1]
        try:
            data = json.loads(self.d64(id))
        except Exception:
            data = {'url': id}
        parse = data.get('parse')
        url = data.get('url', '')
        if parse:
            try:
                parse = json.loads(self.d64(parse))
            except Exception:
                parse = None
        is_direct = bool(url) and self.isVideoFormat(url)
        p, head = (0 if is_direct else 1), ''
        if url and not is_direct and parse:
            for pj in parse:
                if not pj or not pj.startswith('http'):
                    continue
                try:
                    resp = self.fetch(f'{pj}{url}&version={self.app_version}&user_name=游客_3abfc0',
                                      self.headers)
                    jd = resp.json()
                    d2 = jd.get('data') or {}
                    nu = d2.get('url') or jd.get('url')
                    if nu and 'AdvertisementVideo' in nu:
                        continue
                    if nu:
                        url = nu
                        head = d2.get('header') or jd.get('header') or {'User-Agent': 'okhttp/4.9.0'}
                        p = 0
                        break
                except Exception:
                    continue
        if url and 'AdvertisementVideo' in url:
            return {'parse': 1, 'url': '', 'header': {'User-Agent': 'okhttp/4.9.0'}}
        return {'parse': p, 'url': url, 'header': head}

    def localProxy(self, param):
        pass

    # ---------------- 网络层 ----------------
    def getdata(self, path, params=None, host=None):
        body = {'appVersion': self.app_version, 'appKey': self.app_key, 'appSecret': self.app_secret}
        if params:
            body.update({k: v for k, v in params.items() if v not in (None, '')})
        q = '&'.join(f'{k}={quote(str(v), safe="")}' for k, v in body.items())
        headers = self.headers.copy()
        headers['requestId'] = str(uuid.uuid4())
        headers['timestamp'] = str(int(time.time() * 1000))
        hosts = [host] if host else self.hosts
        last_err = None
        for h in hosts:
            try:
                response = self.get(f'{h}{path}?{q}', headers=headers)
                rdata = response.text
                if not rdata:
                    raise ValueError('empty response')
                return json.loads(rdata)
            except Exception as ex:
                last_err = ex
                continue
        raise last_err

    def get(self, url, headers=None):
        import requests
        return requests.get(url, headers=headers or self.headers, timeout=(10, 25))

    def post(self, url, headers=None, data=None):
        import requests
        return requests.post(url, headers=headers or self.headers, data=data, timeout=(10, 25))

    def fetch(self, url, headers=None):
        import requests
        return requests.get(url, headers=headers or self.headers, timeout=(10, 25))

    # ---------------- 工具 ----------------
    def e64(self, text):
        try:
            return b64encode(text.encode('utf-8')).decode('utf-8')
        except Exception:
            return ""

    def d64(self, encoded_text):
        try:
            return b64decode(encoded_text.encode('utf-8')).decode('utf-8')
        except Exception:
            return ""
