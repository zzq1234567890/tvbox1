#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
import json
import time

SITE_URL = "https://www.9g88x.com/"
DATA_API = "https://data.7wzx9.com/forward"
CDN_API = "https://data.7wzx9.com/getDataInit"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)

REQUEST_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": USER_AGENT,
    "Origin": SITE_URL,
    "Referer": SITE_URL,
}

SITE_NAME = "9g88x"
SITE_DISPLAY_NAME = "9g88x·ZakaTV"
CACHE_TTL = 3600

CATEGORY_LIST = [
    {"type_id": "6",  "type_name": "91传媒",   "type_mid": "1"},
    {"type_id": "7",  "type_name": "精东传媒",  "type_mid": "1"},
    {"type_id": "8",  "type_name": "麻豆传媒",  "type_mid": "1"},
    {"type_id": "9",  "type_name": "麻豆映画",  "type_mid": "1"},
    {"type_id": "10", "type_name": "麻豆猫爪",  "type_mid": "1"},
    {"type_id": "11", "type_name": "蜜桃传媒",  "type_mid": "1"},
    {"type_id": "12", "type_name": "天美传媒",  "type_mid": "1"},
    {"type_id": "13", "type_name": "星空传媒",  "type_mid": "1"},
    {"type_id": "14", "type_name": "偷拍自拍",  "type_mid": "1"},
    {"type_id": "15", "type_name": "日韩视频",  "type_mid": "1"},
    {"type_id": "16", "type_name": "欧美性爱",  "type_mid": "1"},
    {"type_id": "17", "type_name": "智能换脸",  "type_mid": "1"},
    {"type_id": "18", "type_name": "经典三级",  "type_mid": "1"},
    {"type_id": "19", "type_name": "网红主播",  "type_mid": "1"},
    {"type_id": "20", "type_name": "台湾辣妹",  "type_mid": "1"},
    {"type_id": "21", "type_name": "onlyfans",  "type_mid": "1"},
    {"type_id": "22", "type_name": "中文字幕",  "type_mid": "1"},
    {"type_id": "23", "type_name": "经典素人",  "type_mid": "1"},
    {"type_id": "24", "type_name": "高清无码",  "type_mid": "1"},
    {"type_id": "25", "type_name": "美颜巨乳",  "type_mid": "1"},
    {"type_id": "26", "type_name": "丝袜制服",  "type_mid": "1"},
    {"type_id": "27", "type_name": "SM系列",    "type_mid": "1"},
    {"type_id": "28", "type_name": "欧美系列",  "type_mid": "1"},
    {"type_id": "29", "type_name": "H動畫",     "type_mid": "1"},
]

def format_remarks(brand="ZakaTV", meta=""):
    clean_meta = str(meta or "").strip()
    clean_meta = re.sub(r"[\r\n\t]+", " ", clean_meta).strip()
    if clean_meta:
        return "%s | %s" % (brand, clean_meta)
    return brand

try:
    import requests as _requests

    def _post_json(url, body, timeout=15):
        rsp = _requests.post(url, json=body, headers=REQUEST_HEADERS, timeout=timeout)
        return rsp.json()

except ImportError:
    from urllib.request import Request, urlopen

    def _post_json(url, body, timeout=15):
        data = json.dumps(body).encode("utf-8")
        req = Request(url, data=data, headers=REQUEST_HEADERS, method="POST")
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

def api_get_all():
    return _post_json(DATA_API, {
        "command": "WEB_GET_ALL",
        "languageType": "CN",
        "content": "",
    })

def api_get_info(type_id, type_mid, page=1, records=30, content="", search_type=""):
    body = {
        "command": "WEB_GET_INFO",
        "pageNumber": page,
        "RecordsPage": records,
        "typeId": type_id,
        "typeMid": type_mid,
        "languageType": "CN",
        "content": content,
    }
    if search_type:
        body["type"] = search_type
    return _post_json(DATA_API, body)

def api_get_detail(item_id, type_mid="1"):
    return _post_json(DATA_API, {
        "command": "WEB_GET_INFO_DETAIL",
        "languageType": "CN",
        "content": "",
        "id": item_id,
        "type_Mid": type_mid,
    })

def api_get_cdn_map():
    result = _post_json(CDN_API, {
        "name": "John", "age": 31, "city": "New York",
    })
    return (result.get("data") or {}).get("macVodLinkMap") or {}

_cdn_map = None
_cdn_map_ts = 0

def get_cdn_map():
    global _cdn_map, _cdn_map_ts
    if _cdn_map is None or (time.time() - _cdn_map_ts > CACHE_TTL):
        _cdn_map = api_get_cdn_map()
        _cdn_map_ts = time.time()
    return _cdn_map

def get_categories():
    return CATEGORY_LIST

def build_pic_url(vod_pic, vod_server_id):
    if not vod_pic:
        return ""
    if vod_pic.startswith("http"):
        return vod_pic
    cdn = get_cdn_map()
    server = cdn.get(str(vod_server_id), {})
    prefix = server.get("PIC_LINK_1", "")
    return prefix + vod_pic if prefix else vod_pic

def build_play_url(vod_url, vod_server_id):
    if not vod_url:
        return ""
    if vod_url.startswith("http"):
        return vod_url
    cdn = get_cdn_map()
    server = cdn.get(str(vod_server_id), {})
    prefix = server.get("LINK_1", "")
    return prefix + vod_url if prefix else vod_url

def format_video_item(item):
    vod_server_id = item.get("vod_server_id", "")
    vod_pic = item.get("vod_pic") or item.get("art_pic") or ""
    vod_name = item.get("vod_name") or item.get("art_name") or ""
    raw_meta = item.get("vod_class") or item.get("art_class") or item.get("vod_remarks") or "高清"

    if vod_server_id:
        vod_pic = build_pic_url(vod_pic, vod_server_id)

    remarks = format_remarks("ZakaTV", raw_meta)

    return {
        "vod_id": str(item.get("id", "")),
        "vod_name": vod_name,
        "vod_pic": vod_pic,
        "vod_remarks": remarks,
        "style": {"type": "rect", "ratio": 1.78}
    }

def get_type_mid_for_id(item_id):
    result = api_get_detail(item_id=item_id, type_mid="1")
    data = result.get("data") or {}
    detail = data.get("result")
    if detail and (detail.get("vod_name") or detail.get("vod_url")):
        return "1", detail
    result = api_get_detail(item_id=item_id, type_mid="2")
    data = result.get("data") or {}
    detail = data.get("result")
    if detail:
        return "2", detail
    return "1", {}

class Spider(object):
    def __init__(self):
        self.extend = ""
        self.brandActor = "📺TG群: https://t.me/+3t5XRPPo9mlkZDRl"
        self.brandDirector = "📺ZakaTV"
        self.tgGroup = "https://t.me/+3t5XRPPo9mlkZDRl"

    def getName(self):
        return SITE_DISPLAY_NAME

    def getDependence(self):
        return []

    def init(self, extend=""):
        self.extend = extend or ""
        try:
            get_cdn_map()
        except Exception:
            pass

    def destroy(self):
        pass

    def homeContent(self, filter):
        classes = []
        for cat in CATEGORY_LIST:
            classes.append({
                "type_id": cat["type_id"],
                "type_name": cat["type_name"],
            })

        all_videos = []
        for cat in CATEGORY_LIST[:6]:
            try:
                result = api_get_info(
                    type_id=cat["type_id"],
                    type_mid=cat["type_mid"],
                    page=1, records=5,
                )
                data = result.get("data") or {}
                raw_list = data.get("resultList") or []
                for v in raw_list:
                    all_videos.append(format_video_item(v))
            except Exception:
                continue

        return {
            "class": classes,
            "filters": {},
            "list": all_videos[:30],
            "style": {"type": "rect", "ratio": 1.78}
        }

    def homeVideoContent(self):
        all_videos = []
        for cat in CATEGORY_LIST[:6]:
            try:
                result = api_get_info(
                    type_id=cat["type_id"],
                    type_mid=cat["type_mid"],
                    page=1, records=5,
                )
                data = result.get("data") or {}
                raw_list = data.get("resultList") or []
                for v in raw_list:
                    all_videos.append(format_video_item(v))
            except Exception:
                continue

        return {
            "list": all_videos[:30],
            "style": {"type": "rect", "ratio": 1.78}
        }

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg) if pg else 1
        except (ValueError, TypeError):
            pg = 1

        tid = str(tid)
        type_mid = "1"

        result = api_get_info(type_id=tid, type_mid=type_mid, page=pg)
        data = result.get("data") or {}
        raw_list = data.get("resultList") or []
        video_list = [format_video_item(v) for v in raw_list]

        return {
            "list": video_list,
            "page": pg,
            "pagecount": data.get("pageAllNumber", 1),
            "limit": "30",
            "total": data.get("count", 0),
            "style": {"type": "rect", "ratio": 1.78}
        }

    def detailContent(self, ids):
        item_id = str(ids[0]) if ids else ""
        type_mid, detail = get_type_mid_for_id(item_id)

        full_desc = (
            "【🔥 官方交流群: %s】\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Zaka专线 极速硬解"
        ) % self.tgGroup

        if type_mid == "1":
            vod_server_id = detail.get("vod_server_id", "")
            play_url = build_play_url(detail.get("vod_url", ""), vod_server_id)
            vod_pic = build_pic_url(detail.get("vod_pic", ""), vod_server_id)
            play_url_str = "正片$" + play_url if play_url else ""
            raw_meta = detail.get("vod_remarks") or detail.get("vod_class") or "正片"
            remarks = format_remarks("ZakaTV", raw_meta)

            item = {
                "vod_id": item_id,
                "vod_name": detail.get("vod_name", ""),
                "vod_pic": vod_pic,
                "type_name": detail.get("typeName", ""),
                "vod_year": detail.get("vod_year", ""),
                "vod_area": detail.get("vod_area", ""),
                "vod_remarks": remarks,
                "vod_actor": self.brandActor,
                "vod_director": self.brandDirector,
                "vod_content": full_desc,
                "vod_play_from": "Zaka专线",
                "vod_play_url": play_url_str,
            }
        else:
            art_pic = detail.get("art_pic", "")
            art_url = detail.get("art_url", "")
            play_urls = []
            if art_url:
                imgs = re.findall(r'<img[^>]+src="([^"]+)"', art_url)
                for i, img_url in enumerate(imgs):
                    play_urls.append("图片%d$%s" % (i + 1, img_url))
            play_url_str = "#".join(play_urls) if play_urls else ""
            remarks = format_remarks("ZakaTV", "图片写真")

            item = {
                "vod_id": item_id,
                "vod_name": detail.get("art_name", ""),
                "vod_pic": art_pic,
                "type_name": "图片/小说",
                "vod_remarks": remarks,
                "vod_actor": self.brandActor,
                "vod_director": self.brandDirector,
                "vod_content": full_desc,
                "vod_play_from": "Zaka专线" if play_url_str else "",
                "vod_play_url": play_url_str,
            }

        return {"list": [item]}

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg) if pg else 1
        except (ValueError, TypeError):
            pg = 1

        result = api_get_info(
            type_id="0", type_mid="1", page=pg,
            content=key, search_type="1",
        )
        data = result.get("data") or {}
        raw_list = data.get("resultList") or []
        video_list = [format_video_item(v) for v in raw_list]

        return {
            "list": video_list,
            "style": {"type": "rect", "ratio": 1.78}
        }

    def playerContent(self, flag, id, vipFlags):
        url = str(id)

        if not url.startswith("http"):
            type_mid, detail = get_type_mid_for_id(url)
            if type_mid == "1":
                vod_server_id = detail.get("vod_server_id", "")
                url = build_play_url(detail.get("vod_url", ""), vod_server_id)
            else:
                url = detail.get("art_pic", "")

        header = json.dumps({
            "Referer": SITE_URL,
            "User-Agent": USER_AGENT,
        })

        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": header,
        }

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def liveContent(self, url):
        return ""

    def localProxy(self, param):
        return [200, "text/plain; charset=utf-8", "", None, 0]

    def action(self, action):
        return {}
