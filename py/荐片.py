# -*- coding: utf-8 -*-
import json
import sys
sys.path.append('..')
from base.spider import Spider
import requests


class Spider(Spider):
    def init(self, extend=""):
        self.host = 'https://api.ztcgi.com'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 9; V2196A Build/PQ3A.190705.08211809; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/91.0.4472.114 Mobile Safari/537.36;webank/h5face;webank/1.0;netType:NETWORK_WIFI;appVersion:416;packageName:com.jp3.xg3',
            'Referer': self.host
        }
        self.ihost = self.imgsite().rstrip('/')
        self.skey = ''
        self.stype = '3'

    def getName(self):
        return "JianPian"

    def imgsite(self):
        try:
            data = requests.get(f"{self.host}/api/appAuthConfig", headers=self.headers, timeout=10).json()
            host = data.get('data', {}).get('imgDomain', '')
            return "https://img.zgbkz.com" if not str(host).startswith('http') else str(host).rstrip('/')
        except:
            return "https://img.zgbkz.com"

    def fix_img(self, path):
        if not path:
            return ""
        path = str(path).strip()
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if path.startswith("/"):
            return f"{self.ihost}{path}"
        return f"{self.ihost}/{path}"

    def homeContent(self, filter):
        classes = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "67", "type_name": "短剧"},
            {"type_id": "3", "type_name": "动漫"},
            {"type_id": "4", "type_name": "综艺"},{'type_id': '50', 'type_name': '纪录片'}
            
        ]
        filterObj = {
            "1": [
                {"value": [{"n": "全部", "v": ""}, {"n": "剧情", "v": "1"}, {"n": "爱情", "v": "2"}, {"n": "动画", "v": "3"}, {"n": "喜剧", "v": "4"}, {"n": "战争", "v": "5"}, {"n": "歌舞", "v": "6"}, {"n": "古装", "v": "7"}, {"n": "奇幻", "v": "8"}, {"n": "冒险", "v": "9"}, {"n": "动作", "v": "10"}, {"n": "科幻", "v": "11"}, {"n": "悬疑", "v": "12"}, {"n": "犯罪", "v": "13"}, {"n": "家庭", "v": "14"}, {"n": "传记", "v": "15"}, {"n": "运动", "v": "16"}, {"n": "同性", "v": "17"}, {"n": "惊悚", "v": "18"}, {"n": "情色", "v": "19"}, {"n": "短片", "v": "20"}, {"n": "历史", "v": "21"}, {"n": "音乐", "v": "22"}, {"n": "西部", "v": "23"}, {"n": "武侠", "v": "24"}, {"n": "恐怖", "v": "25"}], "key": "type", "name": "type"},
                {"value": [{"n": "全部", "v": ""}, {"n": "国产", "v": "1"}, {"n": "中国香港", "v": "3"}, {"n": "中国台湾", "v": "6"}, {"n": "美国", "v": "5"}, {"n": "韩国", "v": "18"}, {"n": "日本", "v": "2"}], "key": "area", "name": "area"},
                {"value": [{"n": "全部", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "107"}, {"n": "2024", "v": "119"}, {"n": "2023", "v": "153"}, {"n": "2022", "v": "101"}, {"n": "2021", "v": "118"}, {"n": "2020", "v": "16"}, {"n": "2019", "v": "7"}, {"n": "2018", "v": "2"}, {"n": "2017", "v": "3"}, {"n": "2016", "v": "22"}, {"n": "2015以前", "v": "2015"}], "key": "year", "name": "year"},
                {"value": [{"n": "全部", "v": ""}, {"n": "最新", "v": "update"}, {"n": "最热", "v": "hot"}, {"n": "评分", "v": "rating"}], "key": "sort", "name": "sort"}
            ],
            "2": [
                {"value": [{"n": "全部", "v": ""}, {"n": "剧情", "v": "1"}, {"n": "爱情", "v": "2"}, {"n": "动画", "v": "3"}, {"n": "喜剧", "v": "4"}, {"n": "战争", "v": "5"}, {"n": "歌舞", "v": "6"}, {"n": "古装", "v": "7"}, {"n": "奇幻", "v": "8"}, {"n": "冒险", "v": "9"}, {"n": "动作", "v": "10"}, {"n": "科幻", "v": "11"}, {"n": "悬疑", "v": "12"}, {"n": "犯罪", "v": "13"}, {"n": "家庭", "v": "14"}, {"n": "传记", "v": "15"}, {"n": "运动", "v": "16"}, {"n": "同性", "v": "17"}, {"n": "惊悚", "v": "18"}, {"n": "情色", "v": "19"}, {"n": "短片", "v": "20"}, {"n": "历史", "v": "21"}, {"n": "音乐", "v": "22"}, {"n": "西部", "v": "23"}, {"n": "武侠", "v": "24"}, {"n": "恐怖", "v": "25"}], "key": "type", "name": "type"},
                {"value": [{"n": "全部", "v": ""}, {"n": "国产", "v": "1"}, {"n": "中国香港", "v": "3"}, {"n": "中国台湾", "v": "6"}, {"n": "美国", "v": "5"}, {"n": "韩国", "v": "18"}, {"n": "日本", "v": "2"}], "key": "area", "name": "area"},
                {"value": [{"n": "全部", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "107"}, {"n": "2024", "v": "119"}, {"n": "2023", "v": "153"}, {"n": "2022", "v": "101"}, {"n": "2021", "v": "118"}, {"n": "2020", "v": "16"}, {"n": "2019", "v": "7"}, {"n": "2018", "v": "2"}, {"n": "2017", "v": "3"}, {"n": "2016", "v": "22"}, {"n": "2015以前", "v": "2015"}], "key": "year", "name": "year"},
                {"value": [{"n": "全部", "v": ""}, {"n": "最新", "v": "update"}, {"n": "最热", "v": "hot"}, {"n": "评分", "v": "rating"}], "key": "sort", "name": "sort"}
            ],
            "3": [
                {"value": [{"n": "全部", "v": ""}, {"n": "剧情", "v": "1"}, {"n": "爱情", "v": "2"}, {"n": "动画", "v": "3"}, {"n": "喜剧", "v": "4"}, {"n": "战争", "v": "5"}, {"n": "歌舞", "v": "6"}, {"n": "古装", "v": "7"}, {"n": "奇幻", "v": "8"}, {"n": "冒险", "v": "9"}, {"n": "动作", "v": "10"}, {"n": "科幻", "v": "11"}, {"n": "悬疑", "v": "12"}, {"n": "犯罪", "v": "13"}, {"n": "家庭", "v": "14"}, {"n": "传记", "v": "15"}, {"n": "运动", "v": "16"}, {"n": "同性", "v": "17"}, {"n": "惊悚", "v": "18"}, {"n": "情色", "v": "19"}, {"n": "短片", "v": "20"}, {"n": "历史", "v": "21"}, {"n": "音乐", "v": "22"}, {"n": "西部", "v": "23"}, {"n": "武侠", "v": "24"}, {"n": "恐怖", "v": "25"}], "key": "type", "name": "type"},
                {"value": [{"n": "全部", "v": ""}, {"n": "国产", "v": "1"}, {"n": "中国香港", "v": "3"}, {"n": "中国台湾", "v": "6"}, {"n": "美国", "v": "5"}, {"n": "韩国", "v": "18"}, {"n": "日本", "v": "2"}], "key": "area", "name": "area"},
                {"value": [{"n": "全部", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "107"}, {"n": "2024", "v": "119"}, {"n": "2023", "v": "153"}, {"n": "2022", "v": "101"}, {"n": "2021", "v": "118"}, {"n": "2020", "v": "16"}, {"n": "2019", "v": "7"}, {"n": "2018", "v": "2"}, {"n": "2017", "v": "3"}, {"n": "2016", "v": "22"}, {"n": "2015以前", "v": "2015"}], "key": "year", "name": "year"},
                {"value": [{"n": "全部", "v": ""}, {"n": "最新", "v": "update"}, {"n": "最热", "v": "hot"}, {"n": "评分", "v": "rating"}], "key": "sort", "name": "sort"}
            ],
            "67": [
                {"value": [{"n": "全部", "v": ""}, {"n": "言情", "v": "70"}, {"n": "爱情", "v": "71"}, {"n": "战神", "v": "72"}, {"n": "古代", "v": "73"}, {"n": "萌娃", "v": "74"}, {"n": "神医", "v": "75"}, {"n": "玄幻", "v": "76"}, {"n": "重生", "v": "77"}, {"n": "激情", "v": "79"}, {"n": "时尚", "v": "82"}, {"n": "剧情演绎", "v": "83"}, {"n": "影视", "v": "84"}, {"n": "人文社科", "v": "85"}, {"n": "二次元", "v": "86"}, {"n": "明星八卦", "v": "87"}, {"n": "随拍", "v": "88"}, {"n": "个人管理", "v": "89"}, {"n": "音乐", "v": "90"}, {"n": "汽车", "v": "91"}, {"n": "休闲", "v": "92"}, {"n": "校园教育", "v": "93"}, {"n": "游戏", "v": "94"}, {"n": "科普", "v": "95"}, {"n": "科技", "v": "96"}, {"n": "时政社会", "v": "97"}, {"n": "萌宠", "v": "98"}, {"n": "体育", "v": "99"}, {"n": "穿越", "v": "80"}, {"n": "", "v": "81"}, {"n": "闪婚", "v": "112"}], "key": "category_id", "name": "category_id"},
                {"value": [{"n": "全部", "v": ""}, {"n": "最新", "v": "update"}, {"n": "最热", "v": "hot"}], "key": "sort", "name": "sort"}
            ],
            "4": [
                {"value": [{"n": "全部", "v": ""}, {"n": "剧情", "v": "1"}, {"n": "爱情", "v": "2"}, {"n": "动画", "v": "3"}, {"n": "喜剧", "v": "4"}, {"n": "战争", "v": "5"}, {"n": "歌舞", "v": "6"}, {"n": "古装", "v": "7"}, {"n": "奇幻", "v": "8"}, {"n": "冒险", "v": "9"}, {"n": "动作", "v": "10"}, {"n": "科幻", "v": "11"}, {"n": "悬疑", "v": "12"}, {"n": "犯罪", "v": "13"}, {"n": "家庭", "v": "14"}, {"n": "传记", "v": "15"}, {"n": "运动", "v": "16"}, {"n": "同性", "v": "17"}, {"n": "惊悚", "v": "18"}, {"n": "情色", "v": "19"}, {"n": "短片", "v": "20"}, {"n": "历史", "v": "21"}, {"n": "音乐", "v": "22"}, {"n": "西部", "v": "23"}, {"n": "武侠", "v": "24"}, {"n": "恐怖", "v": "25"}], "key": "type", "name": "type"},
                {"value": [{"n": "全部", "v": ""}, {"n": "国产", "v": "1"}, {"n": "中国香港", "v": "3"}, {"n": "中国台湾", "v": "6"}, {"n": "美国", "v": "5"}, {"n": "韩国", "v": "18"}, {"n": "日本", "v": "2"}], "key": "area", "name": "area"},
                {"value": [{"n": "全部", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "107"}, {"n": "2024", "v": "119"}, {"n": "2023", "v": "153"}, {"n": "2022", "v": "101"}, {"n": "2021", "v": "118"}, {"n": "2020", "v": "16"}, {"n": "2019", "v": "7"}, {"n": "2018", "v": "2"}, {"n": "2017", "v": "3"}, {"n": "2016", "v": "22"}, {"n": "2015以前", "v": "2015"}], "key": "year", "name": "year"},
                {"value": [{"n": "全部", "v": ""}, {"n": "最新", "v": "update"}, {"n": "最热", "v": "hot"}, {"n": "评分", "v": "rating"}], "key": "sort", "name": "sort"}
            ]
        }
        return {'class': classes, 'filters': filterObj if filter else {}}

    def homeVideoContent(self):
        try:
            url = f"{self.host}/api/slide/list?pos_id=88"
            data = requests.get(url, headers=self.headers, timeout=10).json()
            videos = []
            for item in data.get('data', []):
                pic = self.fix_img(item.get('thumbnail', ''))
                title = item.get('title', '')
                jump_id = item.get('jump_id', '')
                videos.append({
                    'vod_id': f"{jump_id}$$${title}$$${pic}$$$1",
                    'vod_name': title,
                    'vod_pic': pic,
                    'vod_remarks': "",
                    'style': json.dumps({"type": "rect", "ratio": 1.33})
                })
            return {'list': videos}
        except:
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        extend = extend or {}
        try:
            if str(tid) == '67':
                url = f"{self.host}/api/crumb/shortList"
                params = {
                    'fcate_pid': tid,
                    'page': pg,
                    'category_id': extend.get('category_id', ''),
                    'sort': extend.get('sort', 'update') or 'update'
                }
            else:
                url = f"{self.host}/api/crumb/list"
                params = {
                    'fcate_pid': tid,
                    'page': pg,
                    'category_id': extend.get('category_id', ''),
                    'area': extend.get('area', ''),
                    'year': extend.get('year', ''),
                    'type': extend.get('type', ''),
                    'sort': extend.get('sort', '')
                }

            data = requests.get(url, params=params, headers=self.headers, timeout=10).json()
            videos = []
            for item in data.get('data', []):
                title = item.get('title', '')
                pic_field = 'cover_image' if str(tid) == '67' else 'path'
                pic = self.fix_img(item.get(pic_field, ''))
                remarks = item.get('mask', '') or item.get('score', '')
                vod_id = f"{item.get('id', '')}$$${title}$$${pic}$$${tid}"

                videos.append({
                    'vod_id': vod_id,
                    'vod_name': title,
                    'vod_pic': pic,
                    'vod_remarks': remarks,
                    'vod_year': ""
                })

            return {
                'list': videos,
                'page': pg,
                'pagecount': 99999,
                'limit': len(videos),
                'total': 99999
            }
        except:
            return {'list': []}

    def detailContent(self, ids):
        try:
            raw = ids[0]
            arr = raw.split('$$$')
            _id = arr[0]
            vod_name = arr[1] if len(arr) > 1 else ''
            vod_pic = arr[2] if len(arr) > 2 else ''
            tid = arr[3] if len(arr) > 3 else ''

            if tid == '67':
                url = f"{self.host}/api/detail?vid={_id}"
            else:
                url = f"{self.host}/api/video/detailv2?id={_id}"

            data = requests.get(url, headers=self.headers, timeout=10).json()
            res = data.get('data', {})

            play_from = []
            play_url = []

            if tid == '67':
                parts = []
                for part in res.get('playlist', []):
                    name = part.get('title', '')
                    purl = part.get('url', '')
                    if purl:
                        parts.append(f"{name}${purl}")
                if parts:
                    play_from.append('常规线路')
                    play_url.append('#'.join(parts))
            else:
                for source in res.get('source_list_source', []):
                    line_name = source.get('name', '未知线路')
                    parts = []
                    for part in source.get('source_list', []):
                        name = part.get('source_name') or str(part.get('weight', ''))
                        purl = part.get('url', '')
                        if not purl:
                            continue
                        if purl.startswith('ftp'):
                            purl = f"tvbox-xg:{purl}"
                        parts.append(f"{name}${purl}")
                    if parts:
                        play_from.append(line_name)
                        play_url.append('#'.join(parts))

            vod = {
                'vod_id': raw,
                'vod_name': vod_name,
                'vod_pic': self.fix_img(vod_pic),
                'type_name': '/'.join([t.get('name', '') for t in res.get('types', []) if t.get('name')]),
                'vod_year': res.get('year', ''),
                'vod_area': res.get('area', ''),
                'vod_actor': str([a.get('name') for a in res.get('actors', []) if a.get('name')]),
                'vod_remarks': res.get('mask', ''),
                'vod_content': res.get('description', ''),
                'vod_play_from': '$$$'.join(play_from),
                'vod_play_url': '$$$'.join(play_url)
            }
            return {'list': [vod]}
        except:
            return {'list': []}

    def playerContent(self, flag, id, vipFlags):
        if id.startswith('http'):
            return {'parse': 1, 'jx': '1', 'url': id}
        return {'parse': 0, 'url': id, 'playUrl': ''}

    def searchContent(self, key, quick, pg="1"):
        try:
            url = f"{self.host}/api/v2/search/videoV2"
            params = {'key': key, 'category_id': 88, 'page': pg, 'pageSize': 20}
            data = requests.get(url, params=params, headers=self.headers, timeout=10).json()
            key_lower = key.lower()
            filtered_items = [item for item in data.get('data', []) if key_lower in item.get('title', '').lower()]

            videos = []
            for item in filtered_items:
                title = item.get('title', '')
                pic = self.fix_img(item.get('thumbnail', ''))
                top_category = item.get('top_category', {}) or {}
                tid = str(top_category.get('id', ''))
                vod_id = f"{item.get('id', '')}$$${title}$$${pic}$$${tid}"

                videos.append({
                    'vod_id': vod_id,
                    'vod_name': title,
                    'vod_pic': pic,
                    'vod_remarks': item.get('mask', ''),
                    'vod_year': ""
                })

            return {
                'list': videos,
                'limit': 20
            }
        except:
            return {'list': []}

    def isVideoFormat(self, url): pass
    def manualVideoCheck(self): pass
    def destroy(self): pass
    def localProxy(self, param): pass
    def liveContent(self, url): pass