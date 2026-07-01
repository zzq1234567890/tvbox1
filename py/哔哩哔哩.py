from base.spider import Spider
import requests
import re
import urllib.parse
import time
import hashlib

# B站API基础地址
API_BASE = "https://api.bilibili.com"
WEB_BASE = "https://www.bilibili.com"

# 请求头（模拟浏览器）
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
    'Origin': 'https://www.bilibili.com'
}
TIMEOUT = 10

# 分区映射（rid -> 名称）
REGION_MAP = {
    "1": "动画",
    "3": "音乐",
    "4": "游戏",
    "5": "娱乐",
    "11": "电视剧",
    "13": "番剧",
    "23": "电影",
    "36": "科技",
    "119": "鬼畜",
    "129": "舞蹈",
    "155": "生活",
    "160": "时尚",
    "181": "影视",
    "188": "纪录片",
    "217": "资讯",
    "234": "美食",
    "235": "国创"
}


class Spider(Spider):
    def getName(self):
        return "哔哩哔哩"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def homeContent(self, filter):
        """返回全部分类（分区）"""
        classes = []
        for rid, name in REGION_MAP.items():
            classes.append({
                "type_id": rid,
                "type_name": name
            })
        return {"class": classes}

    def homeVideoContent(self):
        """首页推荐（可不实现，返回空）"""
        return {'list': []}

    def categoryContent(self, cid, pg, filter, ext):
        """获取分区视频列表"""
        try:
            page = int(pg) if pg else 1
            rid = cid  # cid即分区rid
            url = f"{API_BASE}/x/web-interface/dynamic/region?rid={rid}&pn={page}&ps=20"
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code != 200:
                return {'list': []}
            data = resp.json()
            if data.get('code') != 0:
                return {'list': []}

            videos = []
            archives = data.get('data', {}).get('archives', [])
            for item in archives:
                # 构造vod_id为bvid
                bvid = item.get('bvid', '')
                title = item.get('title', '')
                pic = item.get('pic', '')
                duration = item.get('duration', 0)  # 秒
                # 格式化时长
                m, s = divmod(duration, 60)
                h, m = divmod(m, 60)
                if h > 0:
                    remarks = f"{h}:{m:02d}:{s:02d}"
                else:
                    remarks = f"{m:02d}:{s:02d}"
                # 简介取前50字
                desc = item.get('desc', '')[:50]
                videos.append({
                    "vod_id": bvid,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": remarks,
                    "vod_content": desc
                })

            return {
                'list': videos,
                'page': page,
                'pagecount': 9999,  # 简化处理，不获取总页数
                'limit': 20,
                'total': 999999
            }
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {'list': []}

    def detailContent(self, ids):
        """获取视频详情（包括分P信息和播放地址构造）"""
        bvid = ids[0]  # ids是一个列表，取第一个
        if not bvid:
            return {'list': []}

        try:
            # 1. 获取视频基本信息
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
            owner = vinfo.get('owner', {})
            author = owner.get('name', '')
            # 获取分区名称
            tid = str(vinfo.get('tid', ''))
            type_name = REGION_MAP.get(tid, '')

            # 分P列表
            pages = vinfo.get('pages', [])
            if not pages:
                # 如果没有分P，则构造一个默认的
                pages = [{'cid': vinfo.get('cid', 0), 'part': '完整视频'}]

            # 2. 构造播放源（不同清晰度）
            # 清晰度映射：qn值，常用：80=高清1080P，64=高清720P，32=清晰360P，16=流畅
            quality_map = {
                "超清": 80,
                "高清": 64,
                "标清": 32,
                "流畅": 16
            }
            play_from = []
            play_url = []

            # 获取avid
            avid = vinfo.get('aid', 0)

            for qname, qn in quality_map.items():
                urls = []
                # 每个分P构造一个播放地址请求URL（后续由playerContent解析）
                for page in pages:
                    cid = page.get('cid', 0)
                    part_name = page.get('part', f'P{len(urls)+1}')
                    # 构造播放地址请求参数（由playerContent处理）
                    play_req_url = f"{API_BASE}/x/player/playurl?avid={avid}&cid={cid}&qn={qn}&type=json"
                    urls.append(f"{part_name}${play_req_url}")
                play_from.append(qname)
                play_url.append("#".join(urls))

            # 拼接演员、类型等
            # B站没有演员，可放UP主
            actor_str = author
            # 视频总时长（秒）转为集数？这里显示分P数
            remarks = f"共{len(pages)}P"

            VOD = {
                "vod_id": bvid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_actor": actor_str,
                "type_name": type_name,
                "vod_remarks": remarks,
                "vod_content": desc,
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url)
            }

            return {'list': [VOD]}

        except Exception as e:
            print(f"detailContent error: {e}")
            return {'list': []}

    def playerContent(self, flag, id, vipFlags):
        """解析播放地址"""
        # flag是清晰度名称（如“超清”），id是上一步构造的play_req_url
        # 重试机制
        for attempt in range(3):
            try:
                resp = requests.get(id, headers=HEADERS, timeout=TIMEOUT)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if data.get('code') != 0:
                    continue
                # 获取视频URL
                durl = data.get('data', {}).get('durl', [])
                if durl and isinstance(durl, list):
                    # 取第一个片段（通常B站会合并多个片段，但这里简单处理）
                    play_url = durl[0].get('url', '')
                    if play_url:
                        return {
                            "parse": 0,
                            "playUrl": '',
                            "url": play_url,
                            "header": HEADERS
                        }
                # 若没有durl，尝试获取dash格式（HLS）
                dash = data.get('data', {}).get('dash', {})
                if dash:
                    video_list = dash.get('video', [])
                    if video_list:
                        # 取最高清晰度
                        play_url = video_list[0].get('baseUrl', '')
                        if play_url:
                            return {
                                "parse": 0,
                                "playUrl": '',
                                "url": play_url,
                                "header": HEADERS
                            }
                # 若没有找到，继续重试
            except Exception as e:
                print(f"playerContent attempt {attempt+1} error: {e}")
                time.sleep(1)
        # 失败返回空
        return {
            "parse": 0,
            "playUrl": '',
            "url": 'about:blank',
            "header": HEADERS
        }

    def searchContent(self, key, quick, pg=1):
        """搜索视频"""
        try:
            page = int(pg) if pg else 1
            keyword = urllib.parse.quote(key)
            url = f"{API_BASE}/x/web-interface/search/all/v2?keyword={keyword}&page={page}"
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code != 200:
                return {'list': []}
            data = resp.json()
            if data.get('code') != 0:
                return {'list': []}

            # 提取视频结果
            result = data.get('data', {}).get('result', [])
            videos = []
            for item in result:
                # 只取视频类型（type="video"）
                if item.get('type') != 'video':
                    continue
                bvid = item.get('bvid', '')
                title = item.get('title', '').replace('<em class="keyword">', '').replace('</em>', '')
                pic = item.get('pic', '')
                duration = item.get('duration', 0)
                m, s = divmod(duration, 60)
                h, m = divmod(m, 60)
                if h > 0:
                    remarks = f"{h}:{m:02d}:{s:02d}"
                else:
                    remarks = f"{m:02d}:{s:02d}"
                desc = item.get('description', '')[:50]
                videos.append({
                    "vod_id": bvid,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": remarks,
                    "vod_content": desc
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
