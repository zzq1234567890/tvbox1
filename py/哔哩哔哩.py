from base.spider import Spider
import requests
import re
import time
import hashlib
import urllib.parse
from urllib.parse import urlencode

# ================= 配置 =================
API_BASE = "https://api.bilibili.com"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
    # 如果仍无法访问，请尝试添加登录后的 Cookie（从浏览器复制）
    # 'Cookie': '你的Cookie值'
}
TIMEOUT = 10
MAX_RETRIES = 3

# 分类映射（与红果短剧风格一致：用 & 拼接）
REGION_MAP = {
    "1": "动画", "3": "音乐", "4": "游戏", "5": "娱乐",
    "11": "电视剧", "13": "番剧", "23": "电影", "36": "科技",
    "119": "鬼畜", "129": "舞蹈", "155": "生活", "160": "时尚",
    "181": "影视", "188": "纪录片", "217": "资讯", "234": "美食", "235": "国创"
}
CLASS_NAMES = "&".join(REGION_MAP.values())
# ========================================

class Spider(Spider):
    def getName(self):
        return "哔哩哔哩"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    # ---------- WBI 签名（可选，仅用于搜索） ----------
    def _get_wbi_keys(self):
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
            img_key = img_url.split('/')[-1].split('.')[0] if img_url else ''
            sub_key = sub_url.split('/')[-1].split('.')[0] if sub_url else ''
            return img_key, sub_key
        except Exception as e:
            print(f"获取WBI keys失败: {e}")
            return None, None

    def _encrypt_wbi(self, params, img_key, sub_key):
        if not img_key or not sub_key:
            return params
        mix_key = sub_key[:4] + img_key[:4]
        sorted_params = sorted(params.items())
        query = urlencode(sorted_params)
        sign = hashlib.md5((query + mix_key).encode()).hexdigest()
        params['w_rid'] = sign
        params['wts'] = int(time.time())
        return params

    def _wbi_request(self, url, params=None):
        if params is None:
            params = {}
        img_key, sub_key = self._get_wbi_keys()
        if img_key and sub_key:
            params = self._encrypt_wbi(params, img_key, sub_key)
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            return resp
        except Exception as e:
            print(f"WBI请求失败: {e}")
            return None

    # ---------- 首页分类 ----------
    def homeContent(self, filter):
        class_list = CLASS_NAMES.split('&')
        classes = []
        for idx, name in enumerate(class_list):
            rid = None
            for k, v in REGION_MAP.items():
                if v == name:
                    rid = k
                    break
            if rid is None:
                rid = str(idx + 1)
            classes.append({"type_id": rid, "type_name": name})
        return {"class": classes}

    def homeVideoContent(self):
        videos = []
        try:
            # 用热门排行补首页（rid=1 动画，通用）
            url = f"{API_BASE}/x/web-interface/ranking/v2"
            resp = requests.get(url, params={'rid': 1, 'type': 'all'},
                                headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('code') == 0:
                    for item in data.get('data', {}).get('list', [])[:6]:
                        bvid = item.get('bvid', '')
                        if not bvid:
                            continue
                        videos.append({
                            "vod_id": bvid,
                            "vod_name": item.get('title', ''),
                            "vod_pic": item.get('pic', ''),
                            "vod_remarks": self._format_duration(item.get('duration', 0)),
                        })
        except:
            pass
        return {'list': videos}

    # ---------- 分类视频列表（使用稳定接口，无需签名） ----------
    def categoryContent(self, cid, pg, filter, ext):
        videos = []
        page = int(pg) if pg else 1
        try:
            # ① 先试分区动态接口
            url = f"{API_BASE}/x/web-interface/dynamic/region"
            resp = requests.get(url, params={'rid': cid, 'pn': page, 'ps': 20},
                                headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('code') == 0:
                    archives = data.get('data', {}).get('archives', [])
                    if archives:
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
    
            # ② Fallback：分区排行榜（几乎所有 rid 都支持）
            url2 = f"{API_BASE}/x/web-interface/ranking/v2"
            resp2 = requests.get(url2, params={'rid': cid, 'type': 'all'},
                                 headers=HEADERS, timeout=TIMEOUT)
            if resp2.status_code == 200:
                data2 = resp2.json()
                if data2.get('code') == 0:
                    for item in data2.get('data', {}).get('list', []):
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
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {'list': []}
    
        return {
            'list': videos,
            'page': page,
            'pagecount': 9999,
            'limit': 20,
            'total': 999999
        }

    # ---------- 视频详情 ----------
    def detailContent(self, ids):
        bvid = ids[0]
        if not bvid:
            return {'list': []}

        try:
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

            # 多清晰度播放源（与红果短剧一致）
            quality_map = {"超清": 80, "高清": 64, "标清": 32, "流畅": 16}
            play_from = []
            play_url = []
            avid = vinfo.get('aid', 0)

            for qname, qn in quality_map.items():
                urls = []
                for page in pages:
                    cid = page.get('cid', 0)
                    part_name = page.get('part', f'P{len(urls)+1}')
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

    # ---------- 播放地址解析 ----------
    def playerContent(self, flag, id, vipFlags):
        for attempt in range(MAX_RETRIES):
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

    # ---------- 搜索（带WBI签名，失败则降级） ----------
    def searchContent(self, key, quick, pg=1):
        try:
            page = int(pg) if pg else 1
            params = {'keyword': key, 'page': page, 'search_type': 'video'}
            url = f"{API_BASE}/x/web-interface/wbi/search/type"
            resp = self._wbi_request(url, params)
            if not resp or resp.status_code != 200:
                # 降级：尝试无签名请求
                resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
                if resp.status_code != 200:
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