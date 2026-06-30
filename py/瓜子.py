# coding=utf-8
# !/usr/bin/python
import base64
import binascii
import sys
from pprint import pprint
from urllib.parse import parse_qsl
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.Hash import MD5
from Crypto.PublicKey import RSA
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.append("..")
from base.spider import Spider
import time
import json

class Spider(Spider):

    def init(self, extend=""):
        # self.host=self.host_late(self.hosts)
        self.host = self.hosts[2]
        self.headers = {
            'User-Agent': 'okhttp/3.12.0',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'code': 'GZ0060',
            'cache-control': 'no-cache',
            'Accept-Charset': 'UTF-8',
            'version': '2412021',
            'packagename': 'com.m8bd1b6239.vafd7ee90c.a24a6a07ad20241228',
            'ver': '1.9.3.11',
            'referer': self.host,
        }
        pass

    def getName(self):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    hosts=['https://api.fknjq37.com', 'https://api.2xvd33x.com', 'https://api.n7xpy5f.com', 'https://api.rmedphk.com', 'https://api.umygrx3.com', 'https://api.6a7nnf7.com']

    # host = 'https://api.6a7nnf7.com'

    token = '581f2d0fa7b547b858e8691864db84c4.001133adbbda7fb1d3d66f8fe369116428cac9d706d2d5a9ef2d4db160ed7e3fdcdfd27ebfc4172d4530ac40ae2b4ac0044c505687eef07c5beb3d2e572717069ff0e4370303f607cffacc7ad1de21498571c2f431d08206f9ebba633435c8549f538412c57319165fe254e0b06b4db2e25d262682a201673654e0a571ffc19d163f1c0e6d8c7e069e88ec46266a22ae.fbc027024601a4c99ca28ecc1b70c614ccf3676f7b9a644ac54607cbb62f627c'
    def homeContent(self, filter):
        data = self.getdata('/App/IndexList/indexScreen', {'t_id': '0'})
        print(data)
        result = {}
        filters = {}
        dy = {"class": "类型", "area": "地区", "lang": "语言", "year": "年份", "sort": "排序"}
        classes = []
        for item in data['column']:
            classes.append({
                'type_name': item['name'],
                'type_id': str(item['value'])
            })
        common_filters = []
        for key in dy:
            if key in data:
                value_array = []
                for filter_item in data[key][1:]:
                    value_array.append({
                        "n": filter_item["name"],
                        "v": filter_item["value"]
                    })
                if value_array:
                    common_filters.append({
                        "key": key,
                        "name": dy[key],
                        "value": value_array
                    })
        for item in classes:
            tid = str(item['type_id'])
            filters[tid] = common_filters.copy()

        result["class"] = classes
        result["filters"] = filters
        return result

    def homeVideoContent(self):
        data = self.getdata('/App/IndexList/index', {'pid': '1'})
        result = {}
        vlist = [it for item in data['list'][1:] for it in self.getlist(item)['list']]
        result["list"] = vlist
        return result

    def categoryContent(self, tid, pg, filter, extend):
        body = {"area": extend.get("area", "0"), "year": extend.get("year", "0"), "pageSize": "30",
                "sort": extend.get("sort", "d_id"), "page": pg, "tid": tid}
        data = self.getdata('/App/IndexList/indexList', body)
        return self.getlist(data)

    def detailContent(self, ids):
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_qdata = executor.submit(
                self.getdata,
                '/App/IndexPlay/playInfo',
                {"token_id": "1649412", "vod_id": ids[0], "mobile_time": str(int(time.time())), "token": self.token}
            )
            future_jdata = executor.submit(
                self.getdata,
                '/App/Resource/Vurl/show',
                {"vurl_cloud_id": "2", "vod_d_id": ids[0]}
            )
            qdata = future_qdata.result()
            jdata = future_jdata.result()
        vod = qdata['vodInfo']
        vod['type_name'] = ','.join(map(str, vod.get('videoTag', [])))
        vod.pop('videoTag', None)
        vod['vod_content'] = vod.get('vod_use_content', '').replace('\u3000', '\n').strip()
        r = []
        for index, i in enumerate(jdata['list']):
            n = []
            p = []
            for key, value in i['play'].items():
                if value['param']:
                    n.append(key)
                    p.append(value['param'])
            cm=str(index + 1)
            if len(jdata['list'])==1:
                cm=vod['vod_name']
            r.append(cm + '$' + p[-1] + '||' + '@'.join(n))
        vod['vod_play_from'] = '嗷呜要吃瓜'
        vod['vod_play_url'] = '#'.join(r)
        return {'list': [vod]}

    def searchContent(self, key, quick, pg="1"):
        data = self.getdata('/App/Index/findMoreVod', {"keywords": key, "page": pg, "order_val": "1"})
        vlist = self.getlist(data)['list']
        result = {'list': vlist,'page':pg}
        return result

    def playerContent(self, flag, id, vipFlags):
        # vod_d_id=87946&vurl_id=1615530&domain_type=8&resolution=1080&type=play||720@1080
        qst = id.split('||')
        json = dict(parse_qsl(qst[0]))
        json['vod_id'] = json.pop('vod_d_id')
        resolutions = list(reversed(qst[-1].split('@')))
        url = []
        result_dict = {}
        with ThreadPoolExecutor(max_workers=len(resolutions)) as executor:
            future_to_resolution = {}
            for resolution in resolutions:
                json_copy = json.copy()
                json_copy['resolution'] = resolution
                future = executor.submit(
                    self.getdata,
                    '/App/Resource/VurlDetail/showOne',
                    json_copy
                )
                future_to_resolution[future] = resolution
            for future in as_completed(future_to_resolution):
                resolution = future_to_resolution[future]
                try:
                    data = future.result()
                    result_dict[int(resolution)] = data['url']
                except Exception as e:
                    print(f'Resolution {resolution} generated an exception: {str(e)}')
            for resolution in sorted(result_dict.keys(), reverse=True):
                url.extend([str(resolution), result_dict[resolution]])

        result = {
            "parse": 0,
            "url": url,
            "header": {
                'User-Agent': 'AppleCoreMedia/1.0.0.23F77 (iPhone; U; CPU OS 26_5 like Mac OS X; zh_cn)',
                'Sec-Ch-Ua-Platform': 'iphone',
                'Sec-Ch-Ua': 'RemoveSecChUa',
                'Sec-Ch-Ua-Mobile': 'Remove-Sec-Ch-Ua-Mobile',
            }
        }
        return result

    def localProxy(self, param):
        pass

    def getdata(self, url: str, request_key: dict) -> dict:
        try:
            key = self.encrypt(json.dumps(request_key))
            def build_request_body(token):
                keys = "Qmxi5ciWXbQzkr7o+SUNiUuQxQEf8/AVyUWY4T/BGhcXBIUz4nOyHBGf9A4KbM0iKF3yp9M7WAY0rrs5PzdTAOB45plcS2zZ0wUibcXuGJ29VVGRWKGwE9zu2vLwhfgjTaaDpXo4rby+7GxXTktzJmxvneOUdYeHi+PZsThlvPI="
                signature = f'token_id=,token={token},phone_type=1,request_key={key},app_id=1,time={str(int(time.time()))},keys={keys}*&zvdvdvddbfikkkumtmdwqppp?|4Y!s!2br'
                md5_hash = MD5.new()
                md5_hash.update(signature.encode('utf-8'))
                signature_md5 = md5_hash.hexdigest()
                return {
                    'token': token,
                    'token_id': '',
                    'phone_type': '1',
                    'time': str(int(time.time())),
                    'phone_model': 'xiaomi-22021211rc',
                    'keys': keys,
                    'request_key': key,
                    'signature': signature_md5,
                    'app_id': '1',
                    'ad_version': '1'
                }
            body = build_request_body(self.token)
            response = self.post(self.host + url, data=body, headers=self.headers)
            if response.json()['code'] != 200:
                if url == '/App/Authentication/Authenticator/refresh':
                    raise Exception("Token refresh failed")
                tdata = self.getdata('/App/Authentication/Authenticator/refresh', {})
                print(tdata.text)
                self.token = tdata.get('data')
                if not self.token:
                    raise Exception("Failed to get new token")
                body = build_request_body(self.token)
                response = self.post(self.host + url, data=body, headers=self.headers)
            banner = response.json()['data']
            response_key = banner['response_key']
            keys = banner['keys']
            body_key = """MIICdgIBADANBgkqhkiG9w0BAQEFAASCAmAwggJcAgEAAoGAe6hKrWLi1zQmjTT1ozbE4QdFeJGNxubxld6GrFGximxfMsMB6BpJhpcTouAqywAFppiKetUBBbXwYsYU1wNr648XVmPmCMCy4rY8vdliFnbMUj086DU6Z+/oXBdWU3/b1G0DN3E9wULRSwcKZT3wj/cCI1vsCm3gj2R5SqkA9Y0CAwEAAQKBgAJH+4CxV0/zBVcLiBCHvSANm0l7HetybTh/j2p0Y1sTXro4ALwAaCTUeqdBjWiLSo9lNwDHFyq8zX90+gNxa7c5EqcWV9FmlVXr8VhfBzcZo1nXeNdXFT7tQ2yah/odtdcx+vRMSGJd1t/5k5bDd9wAvYdIDblMAg+wiKKZ5KcdAkEA1cCakEN4NexkF5tHPRrR6XOY/XHfkqXxEhMqmNbB9U34saTJnLWIHC8IXys6Qmzz30TtzCjuOqKRRy+FMM4TdwJBAJQZFPjsGC+RqcG5UvVMiMPhnwe/bXEehShK86yJK/g/UiKrO87h3aEu5gcJqBygTq3BBBoH2md3pr/W+hUMWBsCQQChfhTIrdDinKi6lRxrdBnn0Ohjg2cwuqK5zzU9p/N+S9x7Ck8wUI53DKm8jUJE8WAG7WLj/oCOWEh+ic6NIwTdAkEAj0X8nhx6AXsgCYRql1klbqtVmL8+95KZK7PnLWG/IfjQUy3pPGoSaZ7fdquG8bq8oyf5+dzjE/oTXcByS+6XRQJAP/5ciy1bL3NhUhsaOVy55MHXnPjdcTX0FaLi+ybXZIfIQ2P4rb19mVq1feMbCXhz+L1rG8oat5lYKfpe8k83ZA=="""
            body_key = "-----BEGIN RSA PRIVATE KEY-----\n" + \
                       body_key + \
                       "\n-----END RSA PRIVATE KEY-----"

            rsa_key = RSA.importKey(body_key)
            cipher = PKCS1_v1_5.new(rsa_key)
            decoded_keys = base64.b64decode(keys)
            decrypted_data = cipher.decrypt(decoded_keys, None)
            body_key_iv = json.loads(decrypted_data.decode('utf-8'))
            key = body_key_iv['key'].encode('utf-8')
            iv = body_key_iv['iv'].encode('utf-8')
            html = self.decrypt(response_key, key, iv)
            return json.loads(html)

        except Exception as e:
            print(f"处理请求失败: {str(e)}")
            return {'error': str(e)}

    def encrypt(self, plain_text: str) -> str:
        key = b"mvXBSW7ekreItNsT"
        iv = b"2U3IrJL8szAKp0Fj"
        pad = lambda s: s + (AES.block_size - len(s) % AES.block_size) * chr(AES.block_size - len(s) % AES.block_size)
        plain_text = pad(plain_text).encode('utf-8')
        cipher = AES.new(key, AES.MODE_CBC, iv)
        encrypted = cipher.encrypt(plain_text)
        return binascii.hexlify(encrypted).decode('utf-8').upper()

    def decrypt(self, encrypted_text: str, key: bytes, iv: bytes) -> str:
        encrypted_bytes = binascii.unhexlify(encrypted_text)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted_bytes)
        unpad = lambda s: s[:-s[-1]]
        return unpad(decrypted).decode('utf-8')

    def getlist(self,data):
        for it in data['list']:
            it['vod_remarks']=f'更新至{it.get("vod_continu","")}集'
            if 'd_total' not in it or it.get('vod_continu','')==it.get('d_total',''):
                it['vod_remarks']=f'全{it.get("d_total","") or it.get("vod_continu","")}集'
            if it.get('d_total','')=='0' or it.get('vod_continu','')=='0':
                it['vod_remarks']=it.get('vod_year','')
            it['vod_year']=it.get('vod_scroe','')
            it['vod_pic']=it.get('vod_pic','')+'@User-Agent=Dalvik/2.1.0 (Linux; U; Android 11; M2012K10C Build/RP1A.200720.011)'
        return data


if __name__ == "__main__":
    sp = Spider()
    formatJo = sp.init([])
    formatJo = sp.homeContent(False)  # 主页，等于真表示启用筛选
    # formatJo = sp.homeVideoContent()  # 主页视频
    # formatJo = sp.searchContent("蜡笔小新",False) # 搜索{"area":"大陆","by":"hits","class":"国产","lg":"国语"}
    # formatJo = sp.categoryContent('73', '1', False, {})  # 分类
    # formatJo = sp.detailContent(['87946'])  # 详情
    # formatJo = sp.playerContent("", "vod_d_id=87946&vurl_id=1615530&domain_type=8&resolution=1080&type=play||720@1080",{})  # 播放
    # formatJo = sp.localProxy({"":"https://www.yingmeng.net/vodplay/140148-2-1.html"}) # 播放
    pprint(formatJo)

