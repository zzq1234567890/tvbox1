# coding=utf-8
import re
import sys
import json
import requests
from urllib.parse import quote
from lxml import etree
sys.path.append('..')
from base.spider import Spider

class Spider(Spider):
    def getName(self):
        return "YouTube影视"

    def init(self, extend=""):
        self.extend = extend
        self.classes = []
        self.filters = {}
        self._load_config()

    def _load_config(self):
        """
        从 lib/youtube.json 加载配置
        """
        try:
            # 假设 lib 目录在当前目录下，或者根据你的实际路径调整
            with open('lib/youtube.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 加载分类
            self.classes = config.get("class", [])
            
            # 加载筛选器
            self.filters = config.get("filters", {})
            
            print(f"[YouTube] 成功加载 {len(self.classes)} 个分类")
        except Exception as e:
            print(f"[YouTube] 加载配置失败: {e}")
            # 保底配置
            self.classes = [
                {"type_id": "video", "type_name": "热门视频"},
                {"type_id": "music", "type_name": "音乐"}
            ]
            self.filters = {}

    def homeContent(self, filter):
        """
        首页数据，返回分类和筛选器
        """
        result = {
            "class": self.classes
        }
        if filter:
            result["filters"] = self.filters
        return result

    def categoryContent(self, tid, pg, filter, extend):
        """
        分类列表页逻辑
        """
        # 1. 获取搜索关键词
        search_keyword = self._get_search_keyword(tid, filter)
        if not search_keyword:
            search_keyword = tid

        # 2. 构造 URL
        # YouTube 分页参数是 &sp=...
        # 这里简化处理，使用基本搜索
        url = f"https://www.youtube.com/results?search_query={quote(search_keyword)}"
        
        # 如果是分页，通常需要处理 continuation token，这里简化为只取第一页
        # 如果有筛选条件，可以在这里拼接
        
        try:
            resp = requests.get(url, headers=self.get_headers(), timeout=30)
            if resp.status_code != 200:
                return {"list": [], "parse": 0, "jx": 0}
                
            html_text = resp.text
            doc = etree.HTML(html_text)
            
            # 3. 使用 XPath 提取视频列表
            # YouTube 的视频容器通常是 ytd-video-renderer
            items = doc.xpath('//ytd-video-renderer')
            
            videos = []
            for item in items:
                # 标题
                title_nodes = item.xpath('.//*[@id="video-title"]')
                title = title_nodes[0].get('title') if title_nodes and title_nodes[0].get('title') else "未知标题"
                
                # 视频ID
                href_nodes = item.xpath('.//*[@id="video-title"]')
                href = href_nodes[0].get('href') if href_nodes else ""
                vid = ""
                if href:
                    match = re.search(r'/watch\?v=([^&]+)', href)
                    if match:
                        vid = match.group(1)
                
                # 图片
                img_nodes = item.xpath('.//img[@src]')
                img_src = ""
                for img in img_nodes:
                    src = img.get('src')
                    if src and 'https' in src:
                        img_src = src
                        break
                # 如果没有找到 https 的 src，尝试 data-src 懒加载
                if not img_src:
                    img_nodes = item.xpath('.//img[@data-src]')
                    if img_nodes:
                        img_src = img_nodes[0].get('data-src')
                
                # 简介
                desc_nodes = item.xpath('.//*[@id="description-text"]//text()')
                desc = "".join(desc_nodes).strip() if desc_nodes else ""
                
                # 时长
                time_nodes = item.xpath('.//span[@class="style-scope ytd-thumbnail-overlay-time-status-renderer"]//text()')
                duration = "".join(time_nodes).strip() if time_nodes else ""
                
                if vid and title:
                    videos.append({
                        "vod_id": vid,
                        "vod_name": title,
                        "vod_pic": img_src,
                        "vod_remarks": duration or desc[:10],
                        "vod_content": desc
                    })
                    
            return {
                "list": videos,
                "parse": 0,
                "jx": 0
            }
            
        except Exception as e:
            print(f"抓取分类 {tid} 失败: {e}")
            return {"list": [], "parse": 0, "jx": 0}

    def _get_search_keyword(self, tid, filter):
        """
        根据 type_id 和筛选器获取最终的搜索关键词
        """
        keyword = tid
        
        # 处理 LIST: 前缀
        if tid.startswith("LIST:"):
            # 提取列表中的第一个有效关键词
            parts = tid[5:].split(',')
            if parts:
                keyword = parts[0].strip()
        
        # 处理筛选器
        if filter:
            # 这里可以根据 filter 中的 key 来拼接关键词
            # 例如：年份、地区等
            # 简单示例：如果有 'area' 筛选
            area = filter.get('area')
            if area:
                keyword += f" {area}"
                
            # 更复杂的逻辑可以在这里添加，根据 youtube.json 的 filters 结构
            
        return keyword

    def detailContent(self, ids):
        """
        视频详情页逻辑
        """
        vid = ids[0]
        url = f"https://www.youtube.com/watch?v={vid}"
        
        try:
            resp = requests.get(url, headers=self.get_headers(), timeout=30)
            if resp.status_code != 200:
                return {"list": []}
                
            html_text = resp.text
            doc = etree.HTML(html_text)
            
            # 提取标题
            title = doc.xpath('//meta[@name="title"]/@content')
            title = title[0].strip() if title else f"YouTube视频 {vid}"
            
            # 提取描述
            desc = doc.xpath('//meta[@name="description"]/@content')
            description = desc[0].strip() if desc else "暂无简介"
            
            # 提取作者
            owner = doc.xpath('//yt-formatted-string[@class="ytd-channel-name"]//text()')
            author = owner[0].strip() if owner else "未知作者"
            
            # 提取发布日期
            date = doc.xpath('//meta[@itemprop="datePublished"]/@content')
            pub_date = date[0].strip() if date else ""
            
            # 构建播放信息
            # 这里只有一集
            play_url = f"{title}${vid}"
            
            vod_data = {
                "vod_id": vid,
                "vod_name": title,
                "vod_actor": author,
                "vod_director": "", # YouTube 通常没有导演
                "vod_year": pub_date.split('-')[0] if pub_date else "未知",
                "vod_area": "全球",
                "vod_content": description,
                "vod_play_from": "YouTube",
                "vod_play_url": play_url
            }
            
            return {"list": [vod_data]}
            
        except Exception as e:
            print(f"获取详情失败: {e}")
            return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        """
        播放器逻辑
        """
        # 直接返回 YouTube 链接，由播放器处理
        vid = id.split('$')[-1]
        play_url = f"https://www.youtube.com/watch?v={vid}"
        
        return {
            "parse": 0, # 0 表示直接播放
            "jx": 0,
            "url": play_url,
            "header": self.get_headers()
        }

    def searchContent(self, key, quick, pg=1):
        # 搜索逻辑
        return self.categoryContent(key, pg, {}, {})

    def get_headers(self):
        """
        返回通用的请求头
        """
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.youtube.com/"
        }

    def localProxy(self, param):
        return [200, "text/plain", "Hello from YouTube Modified!"]

    def destroy(self):
        pass
