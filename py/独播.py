# 独播库.py
from base.spider import Spider
import requests
import re
import urllib.parse
import html

host = "https://www.duboku.mov"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    'Referer': host
}
timeout = 10

class Spider(Spider):
    def getName(self):
        return "独播库"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def homeContent(self, filter):
        # 根据"新文字文件.txt"整理分类
        class_list = [
            ("type:1", "电影"),
            ("show:6", "动作片"),
            ("show:7", "爱情片"),
            ("show:8", "恐怖片"),
            ("show:9", "剧情片"),
            ("show:10", "科幻片"),
            ("show:11", "喜剧片"),
            ("show:23", "战争片"),
            ("show:28", "纪录片"),
            ("show:35", "动画片"),
            ("type:2", "连续剧"),
            ("show:13", "国产剧"),
            ("show:25", "欧美剧"),
            ("show:14", "香港剧"),
            ("show:15", "韩国剧"),
            ("show:16", "日本剧"),
            ("show:24", "台湾剧"),
            ("show:26", "海外剧"),
            ("type:3", "动漫"),
            ("show:area:大陆:id:3", "大陆动漫"),
            ("show:area:日本:id:3", "日本动漫"),
            ("show:area:美国:id:3", "美国动漫"),
            ("show:area:台湾:id:3", "台湾动漫"),
            ("type:4", "综艺"),
            ("show:area:中国大陆:id:4", "大陆综艺"),
            ("show:area:日本:id:4", "日本综艺"),
            ("show:area:香港:id:4", "香港综艺"),
            ("show:area:韩国:id:4", "韩国综艺"),
            ("show:area:英国:id:4", "英国综艺"),
            ("show:area:美国:id:4", "美国综艺"),
        ]
        classes = [{"type_id": cid, "type_name": name} for cid, name in class_list]
        return {"class": classes}

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, cid, pg, filter, ext):
        page = int(pg) if pg else 1
        # 解析分类ID，构造URL路径
        parts = cid.split(':')
        if parts[0] == 'type':
            path = f"type/id/{parts[1]}"
        elif parts[0] == 'show':
            if len(parts) == 2:  # show:6
                path = f"show/id/{parts[1]}"
            elif len(parts) == 5 and parts[1] == 'area':  # show:area:大陆:id:3
                area = urllib.parse.quote(parts[2])
                path = f"show/area/{area}/id/{parts[4]}"
            else:
                return {'list': []}
        else:
            return {'list': []}

        # 拼接URL，处理分页
        url = f"{host}/index.php/vod/{path}"
        if page > 1:
            url += f"/page/{page}"
        url += ".html"

        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                return {'list': []}
            html_content = resp.text
            # 解析视频列表
            videos = self._parse_vod_list(html_content)
            return {
                'list': videos,
                'page': str(page),
                'pagecount': 9999,
                'limit': 20,
                'total': 999999
            }
        except Exception as e:
            print(f"categoryContent error: {e}")
            return {'list': []}

    def _parse_vod_list(self, html_content):
        """从HTML中提取视频列表项"""
        videos = []
        # 匹配每个视频项（使用常见的苹果CMS结构）
        # 先尝试匹配 <div class="module-item"> ... </div> 模式
        item_pattern = r'<div[^>]*class="[^"]*module-item[^"]*"[^>]*>(.*?)</div>\s*(?=<div|$)'
        items = re.findall(item_pattern, html_content, re.S)
        if not items:
            # 如果未匹配，尝试使用更通用的 <li> 或 <a> 组合
            # 这里简化：直接找详情链接和图片
            pattern = r'<a[^>]+href="(/index\.php/vod/detail/id/([^"]+)\.html)"[^>]*>.*?<img[^>]+src="([^"]+)"[^>]+alt="([^"]*)"[^>]*>.*?</a>'
            matches = re.findall(pattern, html_content, re.S)
            for link, vid, pic, title in matches:
                # 提取备注（可能位于附近的span）
                remark = ""
                # 尝试查找该链接附近的<span class="...remark...">
                # 简单起见，我们可从整个页面中查找，但容易错位，这里留空
                videos.append({
                    "vod_id": f"id={vid}",
                    "vod_name": title.strip() if title else "未知",
                    "vod_pic": pic if pic.startswith('http') else host + pic,
                    "vod_remarks": remark,
                    "vod_content": ""
                })
        else:
            # 解析每个item
            for item in items:
                # 提取详情链接和ID
                link_match = re.search(r'<a[^>]+href="(/index\.php/vod/detail/id/([^"]+)\.html)"', item)
                if not link_match:
                    continue
                link, vid = link_match.groups()
                # 提取封面
                img_match = re.search(r'<img[^>]+src="([^"]+)"', item)
                pic = img_match.group(1) if img_match else ""
                # 提取标题
                title_match = re.search(r'<a[^>]+title="([^"]*)"', item)
                title = title_match.group(1) if title_match else ""
                if not title:
                    # 尝试从img的alt或文本获取
                    alt_match = re.search(r'<img[^>]+alt="([^"]*)"', item)
                    title = alt_match.group(1) if alt_match else ""
                # 提取备注（集数或类型）
                remark_match = re.search(r'<span[^>]*class="[^"]*remark[^"]*"[^>]*>([^<]*)</span>', item)
                remark = remark_match.group(1) if remark_match else ""
                # 处理图片相对路径
                if pic and not pic.startswith('http'):
                    pic = host + pic if pic.startswith('/') else host + '/' + pic
                videos.append({
                    "vod_id": f"id={vid}",
                    "vod_name": title.strip() or "未知",
                    "vod_pic": pic,
                    "vod_remarks": remark,
                    "vod_content": ""
                })
        return videos

    def detailContent(self, ids):
        did = ids[0]
        # 解析视频ID
        if '=' in did:
            vid = did.split('=')[1]
        else:
            vid = did
        if not vid:
            return {'list': []}

        detail_url = f"{host}/index.php/vod/detail/id/{vid}.html"
        try:
            resp = requests.get(detail_url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                return {'list': []}
            html_content = resp.text
            # 提取基本信息
            # 标题
            title_match = re.search(r'<h1[^>]*>([^<]*)</h1>', html_content)
            vod_name = title_match.group(1).strip() if title_match else ""
            # 封面
            pic_match = re.search(r'<img[^>]+src="([^"]+)"[^>]+class="[^"]*vod-img[^"]*"', html_content)
            if not pic_match:
                pic_match = re.search(r'<img[^>]+src="([^"]+)"[^>]+alt="[^"]*"', html_content)
            vod_pic = pic_match.group(1) if pic_match else ""
            if vod_pic and not vod_pic.startswith('http'):
                vod_pic = host + vod_pic if vod_pic.startswith('/') else host + '/' + vod_pic
            # 演员
            actor_match = re.search(r'<span>主演：</span>\s*<a[^>]*>([^<]*)</a>', html_content)
            if not actor_match:
                actor_match = re.search(r'主演：</span>\s*<a[^>]*>([^<]*)</a>', html_content)
            vod_actor = actor_match.group(1).strip() if actor_match else ""
            # 类型
            type_match = re.search(r'<span>类型：</span>\s*<a[^>]*>([^<]*)</a>', html_content)
            if not type_match:
                type_match = re.search(r'类型：</span>\s*<a[^>]*>([^<]*)</a>', html_content)
            type_name = type_match.group(1).strip() if type_match else ""
            # 简介
            desc_match = re.search(r'<div[^>]*class="[^"]*vod-content[^"]*"[^>]*>(.*?)</div>', html_content, re.S)
            if not desc_match:
                desc_match = re.search(r'<div[^>]*class="[^"]*detail-content[^"]*"[^>]*>(.*?)</div>', html_content, re.S)
            vod_content = desc_match.group(1).strip() if desc_match else ""
            if vod_content:
                # 清理HTML标签
                vod_content = re.sub(r'<[^>]+>', '', vod_content).strip()

            # 提取剧集列表
            # 常见播放列表结构：<ul class="playlist"> <li><a href="...">第1集</a></li> ... </ul>
            playlist_match = re.search(r'<ul[^>]*class="[^"]*playlist[^"]*"[^>]*>(.*?)</ul>', html_content, re.S)
            if not playlist_match:
                playlist_match = re.search(r'<div[^>]*class="[^"]*playlist[^"]*"[^>]*>(.*?)</div>', html_content, re.S)
            episodes = []
            if playlist_match:
                ul_content = playlist_match.group(1)
                # 提取每个a标签
                ep_links = re.findall(r'<a[^>]+href="(/index\.php/vod/play/[^"]+\.html)"[^>]*>([^<]*)</a>', ul_content, re.S)
                for ep_url, ep_title in ep_links:
                    episodes.append({
                        "title": ep_title.strip() or "第{}集".format(len(episodes)+1),
                        "url": host + ep_url if ep_url.startswith('/') else ep_url
                    })

            # 如果没有找到剧集，尝试从其他结构中提取
            if not episodes:
                # 查找所有带有播放链接的a
                all_links = re.findall(r'<a[^>]+href="(/index\.php/vod/play/[^"]+\.html)"[^>]*>([^<]*)</a>', html_content, re.S)
                for url, title in all_links:
                    episodes.append({
                        "title": title.strip() or "第{}集".format(len(episodes)+1),
                        "url": host + url if url.startswith('/') else url
                    })

            # 构造播放数据（类似红果短剧，按清晰度分组）
            play_from = []
            play_url = []
            if episodes:
                # 只提供一个播放源（比如"高清"），也可以多个
                play_from.append("高清")
                play_url.append("#".join([f"{ep['title']}${ep['url']}" for ep in episodes]))

            # 构建返回数据
            vod = {
                "vod_id": f"id={vid}",
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_actor": vod_actor,
                "type_name": type_name,
                "vod_remarks": f"共{len(episodes)}集" if episodes else "",
                "vod_content": vod_content,
                "vod_play_from": "$$$".join(play_from) if play_from else "",
                "vod_play_url": "$$$".join(play_url) if play_url else ""
            }
            return {'list': [vod]}
        except Exception as e:
            print(f"detailContent error: {e}")
            return {'list': []}

    def playerContent(self, flag, id, vipFlags):
        # id 是播放页完整URL
        try:
            resp = requests.get(id, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                return {"parse": 0, "playUrl": '', "url": 'about:blank', "header": headers}
            html_content = resp.text

            # 尝试提取视频地址
            # 1. 查找 <video> 标签的 src
            video_src = re.search(r'<video[^>]+src="([^"]+)"', html_content)
            if video_src:
                video_url = video_src.group(1)
                if not video_url.startswith('http'):
                    video_url = host + video_url if video_url.startswith('/') else host + '/' + video_url
                return {"parse": 0, "playUrl": '', "url": video_url, "header": headers}

            # 2. 查找 <iframe> 的 src
            iframe_src = re.search(r'<iframe[^>]+src="([^"]+)"', html_content)
            if iframe_src:
                iframe_url = iframe_src.group(1)
                if not iframe_url.startswith('http'):
                    iframe_url = host + iframe_url if iframe_url.startswith('/') else host + '/' + iframe_url
                # 有些iframe可能包含最终视频，但直接返回该iframe地址让播放器加载
                return {"parse": 0, "playUrl": '', "url": iframe_url, "header": headers}

            # 3. 查找 <source> 标签
            source_src = re.search(r'<source[^>]+src="([^"]+)"', html_content)
            if source_src:
                src = source_src.group(1)
                if not src.startswith('http'):
                    src = host + src if src.startswith('/') else host + '/' + src
                return {"parse": 0, "playUrl": '', "url": src, "header": headers}

            # 4. 尝试查找JS中的播放地址（简单匹配）
            js_src = re.search(r'file:\s*["\']([^"\']+)["\']', html_content)
            if js_src:
                js_url = js_src.group(1)
                if not js_url.startswith('http'):
                    js_url = host + js_url if js_url.startswith('/') else host + '/' + js_url
                return {"parse": 0, "playUrl": '', "url": js_url, "header": headers}

            # 如果都找不到，返回空
            return {"parse": 0, "playUrl": '', "url": 'about:blank', "header": headers}
        except Exception as e:
            print(f"playerContent error: {e}")
            return {"parse": 0, "playUrl": '', "url": 'about:blank', "header": headers}

    def searchContent(self, key, quick, pg=1):
        try:
            page = int(pg) if pg else 1
        except:
            page = 1
        # 搜索URL（通常为 /index.php/vod/search.html?wd=关键词）
        search_url = f"{host}/index.php/vod/search.html?wd={urllib.parse.quote(key)}"
        if page > 1:
            search_url += f"&page={page}"
        try:
            resp = requests.get(search_url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                return {'list': []}
            html_content = resp.text
            videos = self._parse_vod_list(html_content)
            # 搜索结果页可能结构相同
            return {
                'list': videos,
                'page': str(page),
                'pagecount': 9999,
                'limit': len(videos),
                'total': 999999
            }
        except Exception as e:
            print(f"searchContent error: {e}")
            return {'list': []}
