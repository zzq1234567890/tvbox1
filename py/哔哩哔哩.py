from base.spider import Spider
import requests
import urllib.parse
import json
import re
import time
import hashlib
import base64
from urllib.parse import urlencode

# ================= 配置区域 =================
API_BASE = "https://api.bilibili.com"
WEB_BASE = "https://www.bilibili.com"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
}
TIMEOUT = 10

# 分区映射 (rid -> 名称)
REGION_MAP = {
    "1": "动画", "3": "音乐", "4": "游戏", "5": "娱乐",
    "11": "电视剧", "13": "番剧", "23": "电影", "36": "科技",
    "119": "鬼畜", "129": "舞蹈", "155": "生活", "160": "时尚",
    "181": "影视", "188": "纪录片", "217": "资讯", "234": "美食", "235": "国创"
}
# ==========================================

class Spider(Spider):
    def getName(self):
        return "哔哩哔哩"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    # ---------- WBI 签名 ----------
    def _get_wbi_keys(self):
        """获取用于签名的 img_key 和 sub_key"""
        try:
            url = f"{API_BASE}/x/web-interface/nav"
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code != 200:
                return None, None
            data = resp.json()
            if data.get('code') != 0:
                return None, None
            wbi_img = data.get('data', {}).get('wbi_img', {})
            img_url = wbi_img.get('img_url', '')
            sub_url = wbi_img.get('sub_url', '')
            # 从URL中提取文件名（去掉扩展名）
            img_key = img_url.split('/')[-1].split('.')[0] if img_url else ''
            sub_key = sub_url.split('/')[-1].split('.')[0] if sub_url else ''
            return img_key, sub_key
        except Exception as e:
            print(f"获取WBI keys失败: {e}")
            return None, None

    def _encrypt_wbi(self, params, img_key, sub_key):
        """对参数进行WBI签名，返回加签后的参数字典"""
        if not img_key or not sub_key:
            return params
        mix_key = sub_key[:4] + img_key[:4]
        # 对参数按key排序
        sorted_params = sorted(params.items())
        # 拼接成字符串
        query = urlencode(sorted_params)
        sign = hashlib.md5((query + mix_key).encode()).hexdigest()
        params['w_rid'] = sign
        params['wts'] = int(time.time())
        return params

    def _wbi_request(self, url, params=None):
        """带WBI签名的GET请求"""
        if params is None:
            params = {}
        img_key, sub_key = self._get_wbi_keys()
        if img_key and sub_key:
            params = self._encrypt_wbi(params, img_key, sub_key)
        else:
            # 若获取失败，则不加签名（降级）
            pass
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            return resp
        except Exception as e:
            print(f"WBI请求失败: {e}")
            return None

    # ---------- 首页/分类 ----------
    def homeContent(self, filter):
        classes = [{"type_id": rid, "type_name": name} for rid, name in REGION_MAP.items()]
        return {"class": classes}

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, cid, pg, filter, ext):
        """获取分区视频列表（使用WBI签名）"""
        try:
            page = int(pg) if pg else 1
            params = {
                'rid': cid,
                'pn': page,
                'ps': 20
            }
            url = f"{API_BASE}/x/web-interface/wbi/index/icon"
            resp = self._wbi_request(url, params)
            if not resp or resp.status_code != 200:
                return {'list': []}
            data = resp.json()
            if data.get('code') != 0:
                print(f"categoryContent API错误: {data.get('message')}")
                return {'list': []}

            videos = []
            # 注意：返回的数据结构可能为 data.list 或 data.archives，根据实测调整
            archives = data.get('data', {}).get('list', [])
            if not archives:
                archives = data.get('data', {}).get('archives', [])
            for item in archives:
                bvid = item.get('bvid', '')
                if not bvid:
                    continue
                videos.append({
                    "vod_id": bvid,
                    "vod_name": item.get('title', '无标题'),
                    "vod_pic": item.get('pic', ''),
                    "vod_remarks": self._format_duration(item.get('duration', 0)),
                    "vod_content": item.get('desc', '')[:50]
                })
            return {
                'list': videos,
                'page': page,
                'pagecount': 9999,
                'limit': 20,
                'total': 999999
            }
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {'list': []}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        bvid = ids[0]
        if not bvid:
            return {'list': []}
        try:
            # 获取视频信息（view接口目前不需要WBI签名，但可保留）
            view_url = f"{API_BASE}/x/web-interface/view?bvid={bvid}"
            resp = requests.get(view_url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code != 200:
                return {'list': []}
            view_data = resp.json()
            if view_data.get('code') != 0:
                return {'list': []}
            vinfo = view_data.get('data', {})

            title = vinfo.get('title', '')
            pic = vinfo.get('pic', '')
            desc = vinfo.get('desc', '')
            author = vinfo.get('owner', {}).get('name', '')
            tid = str(vinfo.get('tid', ''))
            type_name = REGION_MAP.get(tid, '')

            pages = vinfo.get('pages', [])
            if not pages:
                pages = [{'cid': vinfo.get('cid', 0), 'part': '完整视频'}]

            # 构造播放源（清晰度）
            quality_map = {"超清": 80, "高清": 64, "标清": 32, "流畅": 16}
            play_from = []
            play_url = []
            avid = vinfo.get('aid', 0)

            for qname, qn in quality_map.items():
                urls = []
                for page in pages:
                    cid = page.get('cid', 0)
                    part_name = page.get('part', f'P{len(urls)+1}')
                    # 播放地址请求交给 playerContent 处理
                    play_req_url = f"{API_BASE}/x/player/playurl?avid={avid}&cid={cid}&qn={qn}&type=json"
                    urls.append(f"{part_name}${play_req_url}")
                play_from.append(qname)
                play_url.append("#".join(urls))

            VOD = {
                "vod_id": bvid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_actor": author,
                "type_name": type_name,
                "vod_remarks": f"共{len(pages)}P",
                "vod_content": desc,
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url)
            }
            return {'list': [VOD]}
        except Exception as e:
            print(f"detailContent error: {e}")
            return {'list': []}

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags):
        """解析播放地址（playurl接口无需签名，但返回的baseUrl可直接播放）"""
        for attempt in range(3):
            try:
                resp = requests.get(id, headers=HEADERS, timeout=TIMEOUT)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if data.get('code') != 0:
                    continue
                dash = data.get('data', {}).get('dash', {})
                if dash:
                    video_list = dash.get('video', [])
                    if video_list:
                        play_url = video_list[0].get('baseUrl', '')
                        if play_url:
                            return {"parse": 0, "playUrl": '', "url": play_url, "header": HEADERS}
                durl = data.get('data', {}).get('durl', [])
                if durl:
                    play_url = durl[0].get('url', '')
                    if play_url:
                        return {"parse": 0, "playUrl": '', "url": play_url, "header": HEADERS}
            except Exception as e:
                print(f"playerContent attempt {attempt+1} error: {e}")
                time.sleep(1)
        return {"parse": 0, "playUrl": '', "url": 'about:blank', "header": HEADERS}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg=1):
        try:
            page = int(pg) if pg else 1
            params = {
                'keyword': key,
                'page': page,
                'search_type': 'video'
            }
            url = f"{API_BASE}/x/web-interface/wbi/search/type"
            resp = self._wbi_request(url, params)
            if not resp or resp.status_code != 200:
                return {'list': []}
            data = resp.json()
            if data.get('code') != 0:
                print(f"searchContent API错误: {data.get('message')}")
                return {'list': []}

            videos = []
            result = data.get('data', {}).get('result', [])
            for item in result:
                bvid = item.get('bvid', '')
                if not bvid:
                    continue
                title = re.sub(r'<em[^>]*>|</em>', '', item.get('title', '无标题'))
                videos.append({
                    "vod_id": bvid,
                    "vod_name": title,
                    "vod_pic": item.get('pic', ''),
                    "vod_remarks": self._format_duration(item.get('duration', 0)),
                    "vod_content": item.get('description', '')[:50]
                })
            return {
                'list': videos,
                'page': page,
                'pagecount': 9999,
                'limit': len(videos),
                'total': 999999
            }
        except Exception as e:
            print(f"searchContent error: {e}")
            return {'list': []}

    # ---------- 辅助 ----------
    def _format_duration(self, seconds):
        if not seconds:
            return "00:00"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
