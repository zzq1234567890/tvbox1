# -*- coding: utf-8 -*-
import json
import re
import ssl
import urllib.parse
import urllib.request
import html

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass

class Spider(BaseSpider):

    HOST = "https://bad.news"

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def action(self, action):
        pass

    def destroy(self):
        pass

    def liveContent(self):
        return {}

    def localProxy(self, params):
        return [200, "text/plain", ""]

    def _fetch(self, url, headers=None, timeout=15):
        if headers is None:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
            }
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers=headers)
        try:
            resp = urllib.request.urlopen(req, context=ctx, timeout=timeout)
            code = resp.getcode()
            real_url = resp.geturl()
            body_bytes = resp.read()
            try:
                body_text = body_bytes.decode("utf-8")
            except Exception:
                try:
                    body_text = body_bytes.decode("gbk", errors="ignore")
                except Exception:
                    body_text = str(body_bytes)
            return {
                "ok": True,
                "status_code": code,
                "real_url": real_url,
                "body": body_text
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e)
            }

    def homeContent(self, filter):
        classes = [
            {"type_id": "porn_hot", "type_name": "热门视频"},
            {"type_id": "porn_new", "type_name": "最新发布"},
            {"type_id": "porn_score", "type_name": "高分精选"},
            {"type_id": "porn_better", "type_name": "特别推荐"},
            {"type_id": "long_porn", "type_name": "长篇巨作"},
            {"type_id": "dm_all", "type_name": "动漫全集"},
            {"type_id": "dm_3d", "type_name": "三维动画"},
            {"type_id": "dm_tongren", "type_name": "同人原创"},
            {"type_id": "dm_cosplay", "type_name": "角色扮演"}
        ]
        return {
            "class": classes,
            "filters": {}
        }

    def homeVideoContent(self):
        return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if str(pg).isdigit() else 1

        is_dm = False

        if tid == "porn_hot":
            path = "/tag/porn/sort-hot" if page == 1 else "/tag/porn/sort-hot/page-%d" % page
        elif tid == "porn_new":
            path = "/tag/porn/sort-new" if page == 1 else "/tag/porn/sort-new/page-%d" % page
        elif tid == "porn_score":
            path = "/tag/porn/sort-score" if page == 1 else "/tag/porn/sort-score/page-%d" % page
        elif tid == "porn_better":
            path = "/tag/porn/sort-better" if page == 1 else "/tag/porn/sort-better/page-%d" % page
        elif tid == "long_porn":
            path = "/tag/long-porn" if page == 1 else "/tag/long-porn/page-%d" % page
        elif tid == "dm_all":
            is_dm = True
            path = "/dm" if page == 1 else "/dm/page-%d" % page
        elif tid == "dm_3d":
            is_dm = True
            path = "/dm/type/q-3D" if page == 1 else "/dm/type/q-3D/page-%d" % page
        elif tid == "dm_tongren":
            is_dm = True
            q_val = urllib.parse.quote("同人")
            path = "/dm/type/q-%s" % q_val if page == 1 else "/dm/type/q-%s/page-%d" % (q_val, page)
        elif tid == "dm_cosplay":
            is_dm = True
            path = "/dm/type/q-Cosplay" if page == 1 else "/dm/type/q-Cosplay/page-%d" % page
        else:
            path = "/" if page == 1 else "/page-%d" % page

        target_url = self.HOST + path
        res = self._fetch(target_url)

        vod_list = []
        if res.get("ok"):
            raw_html = res.get("body", "")

            if is_dm:
                articles = re.findall(r'<article[^>]*>([\s\S]*?)</article>', raw_html, re.I)
                for art in articles:
                    id_match = re.search(r'href=[\'"][^"\']*/dm/play/id-(\d+)[\'"]', art)
                    if not id_match:
                        continue
                    v_id = "dm_%s" % id_match.group(1)

                    title_match = re.search(r'<a class="title"[^>]*title=[\'"]([^\'"]+)[\'"]', art)
                    title = ""
                    if title_match:
                        title = title_match.group(1).strip()
                    else:
                        title_text_match = re.search(r'<a class="title"[^>]*>([\s\S]*?)</a>', art)
                        if title_text_match:
                            title = re.sub(r'<[^>]+>', '', title_text_match.group(1)).strip()
                    if not title:
                        title = "动漫 %s" % id_match.group(1)
                    title = html.unescape(title)

                    pic = ""
                    echo_match = re.search(r'data-echo=[\'"]([^\'"]+)[\'"]', art)
                    if echo_match:
                        pic = echo_match.group(1).strip()
                    else:
                        src_match = re.search(r'<img[^>]+src=[\'"]([^\'"]+)[\'"]', art)
                        if src_match:
                            c_pic = src_match.group(1).strip()
                            if "lightbox-blank" not in c_pic and "default" not in c_pic:
                                pic = c_pic
                    if pic.startswith("/"):
                        pic = self.HOST + pic

                    vod_list.append({
                        "vod_id": v_id,
                        "vod_name": title,
                        "vod_pic": pic,
                        "vod_remarks": "ZakaTV",
                        "style": {"type": "rect", "ratio": 1.78}
                    })
            else:
                blocks = re.split(r'<div class=[\'"](?:link|topic)\s+', raw_html)
                if len(blocks) <= 1:
                    blocks = re.split(r'<div class=[\'"][^\'"]*link[^\'"]*[\'"]', raw_html)

                for b in blocks[1:]:
                    if "【热点】" in b or "招聘" in b or "/tag/灌水" in b:
                        continue

                    tid_match = re.search(r'data-tid=[\'"](\d+)[\'"]', b)
                    v_id = ""
                    if tid_match:
                        v_id = tid_match.group(1)
                    else:
                        id_match = re.search(r'href=[\'"][^"\']*/t/(\d+)[\'"]', b)
                        if id_match:
                            v_id = id_match.group(1)

                    if not v_id:
                        continue

                    title = ""
                    title_match = re.search(r'<h3 class="title">[\s\S]*?<a class="title"[^>]*>([\s\S]*?)</a>', b)
                    if title_match:
                        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
                        title = html.unescape(title)
                    if not title:
                        alt_title_match = re.search(r'<a[^>]+href="[^"]*/t/' + v_id + r'"[^>]*>([\s\S]*?)</a>', b)
                        if alt_title_match:
                            title = re.sub(r'<[^>]+>', '', alt_title_match.group(1)).strip()
                            title = html.unescape(title)
                    if not title:
                        title = "视频 %s" % v_id

                    pic = ""
                    poster_match = re.search(r'poster=[\'"]([^\'"]+)[\'"]', b)
                    if poster_match:
                        pic = poster_match.group(1).strip()
                    if not pic:
                        echo_match = re.search(r'data-echo=[\'"]([^\'"]+)[\'"]', b)
                        if echo_match:
                            pic = echo_match.group(1).strip()
                    if not pic:
                        src_match = re.search(r'<img[^>]+src=[\'"]([^\'"]+)[\'"]', b)
                        if src_match:
                            candidate = src_match.group(1).strip()
                            if "blank.gif" not in candidate and "default_avatar" not in candidate:
                                pic = candidate
                    if pic.startswith("/"):
                        pic = self.HOST + pic

                    time_match = re.search(r'<div class="ct-time">\s*<span>([^<]+)</span>', b)
                    remarks = "ZakaTV"
                    if time_match:
                        dur = time_match.group(1).strip()
                        if dur:
                            remarks = "ZakaTV | %s" % dur

                    vod_list.append({
                        "vod_id": v_id,
                        "vod_name": title,
                        "vod_pic": pic,
                        "vod_remarks": remarks,
                        "style": {"type": "rect", "ratio": 1.78}
                    })

        return {
            "page": page,
            "pagecount": page + 1 if len(vod_list) >= 10 else page,
            "limit": 20,
            "total": 9999,
            "list": vod_list
        }

    def detailContent(self, ids):
        vod_id = ids[0] if ids else "1"

        if str(vod_id).startswith("dm_"):
            real_id = str(vod_id).replace("dm_", "")
            target_url = "%s/dm/play/id-%s" % (self.HOST, real_id)
        else:
            target_url = "%s/t/%s" % (self.HOST, vod_id)

        res = self._fetch(target_url)
        body = res.get("body", "") if res.get("ok") else ""

        title = "视频 %s" % vod_id
        t_match = re.search(r'<title>([\s\S]*?)</title>', body, re.I)
        if t_match:
            title = re.sub(r'[\r\n\t]+', ' ', t_match.group(1)).strip()
            title = html.unescape(title)

        pic = ""
        poster_match = re.search(r'poster=[\'"]([^\'"]+)[\'"]', body)
        if poster_match:
            pic = poster_match.group(1).strip()
        if not pic:
            echo_match = re.search(r'data-echo=[\'"]([^\'"]+)[\'"]', body)
            if echo_match:
                pic = echo_match.group(1).strip()
        if pic.startswith("/"):
            pic = self.HOST + pic

        play_url = ""
        source_match = re.search(r'data-source=[\'"]([^\'"]+)[\'"]', body)
        if source_match:
            play_url = source_match.group(1).strip()
        else:
            v_src_match = re.search(r'<video[^>]+src=[\'"]([^\'"]+)[\'"]', body)
            if v_src_match:
                play_url = v_src_match.group(1).strip()
            else:
                m3u8_match = re.search(r'[\'"](https?://[^\'"]+\.m3u8[^\'"]*)[\'"]', body)
                if m3u8_match:
                    play_url = m3u8_match.group(1).strip()

        if not play_url:
            play_url = "正片$%s" % target_url
        else:
            play_url = "正片$%s" % play_url

        vod = {
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": pic,
            "vod_remarks": "ZakaTV",
            "vod_actor": "📺TG群: https://t.me/+3t5XRPPo9mlkZDRl",
            "vod_director": "📺ZakaTV",
            "vod_content": "📺官方交流群: https://t.me/+3t5XRPPo9mlkZDRl\n本资源来自网络聚合，仅供交流学习使用。",
            "vod_play_from": "BadNews",
            "vod_play_url": play_url
        }

        return {"list": [vod]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if str(pg).isdigit() else 1
        q_enc = urllib.parse.quote(key)
        target_url = "%s/search/q-%s/type-porn" % (self.HOST, q_enc)
        if page > 1:
            target_url = "%s/search/q-%s/type-porn/page-%d" % (self.HOST, q_enc, page)

        res = self._fetch(target_url)
        vod_list = []
        if res.get("ok"):
            raw_html = res.get("body", "")
            blocks = re.split(r'<div class=[\'"](?:link|topic)\s+', raw_html)
            for b in blocks[1:]:
                if "【热点】" in b or "招聘" in b or "/tag/灌水" in b:
                    continue

                tid_match = re.search(r'data-tid=[\'"](\d+)[\'"]', b)
                v_id = ""
                if tid_match:
                    v_id = tid_match.group(1)
                else:
                    id_match = re.search(r'href=[\'"][^"\']*/t/(\d+)[\'"]', b)
                    if id_match:
                        v_id = id_match.group(1)

                if not v_id:
                    continue

                title = ""
                title_match = re.search(r'<h3 class="title">[\s\S]*?<a class="title"[^>]*>([\s\S]*?)</a>', b)
                if title_match:
                    title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
                    title = html.unescape(title)
                if not title:
                    title = "视频 %s" % v_id

                pic = ""
                poster_match = re.search(r'poster=[\'"]([^\'"]+)[\'"]', b)
                if poster_match:
                    pic = poster_match.group(1).strip()
                if not pic:
                    echo_match = re.search(r'data-echo=[\'"]([^\'"]+)[\'"]', b)
                    if echo_match:
                        pic = echo_match.group(1).strip()
                if pic.startswith("/"):
                    pic = self.HOST + pic

                vod_list.append({
                    "vod_id": v_id,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": "ZakaTV",
                    "style": {"type": "rect", "ratio": 1.78}
                })

        return {
            "page": page,
            "pagecount": page + 1 if len(vod_list) >= 10 else page,
            "limit": 20,
            "total": 9999,
            "list": vod_list
        }

    def playerContent(self, flag, id, vipFlags):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }
        if "twimg.com" not in id:
            headers["Referer"] = self.HOST + "/"

        return {
            "parse": 0,
            "playUrl": "",
            "url": id,
            "header": headers
        }
