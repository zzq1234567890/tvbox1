# -*- coding: utf-8 -*-
# 汤头条 TVBox爬虫（全分类+封面）
# 依赖：requests

import re
import time
import html as htmllib
import urllib.parse

try:
    from base.spider import Spider
except ImportError:
    class Spider:
        pass

try:
    import requests as rq
    rq.packages.urllib3.disable_warnings()
except:
    pass

HOST = "https://m.tangttiao.cc"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
TIMEOUT = 15

CATS = [
    ("home", "精选"),
    ("cate3", "顶级网黄"), ("cate4", "福利姬"), ("cate5", "主播勾引"),
    ("cate6", "传媒精选"), ("cate7", "JVID"), ("cate8", "锅锅酱"),
    ("cate9", "巨乳大奶"), ("cate10", "抖音风"), ("cate11", "制服诱惑"),
    ("cate12", "樱花小猫"), ("cate13", "反差女友"), ("cate14", "探花约炮"),
    ("cate15", "调教性奴"), ("cate16", "ASMR"), ("cate17", "颜值网红"),
    ("cate18", "高潮自慰"), ("cate19", "欧美洋马"), ("cate20", "露出野战"),
    ("cate21", "SWAG"), ("cate22", "热门吃瓜"), ("cate23", "绿帽淫妻"),
    ("cate24", "群交滥交"), ("cate25", "风骚少妇"), ("cate26", "逆天乱伦"),
    ("cate27", "AI女神"), ("cate28", "风骚母狗"), ("cate29", "断袖男同"),
    ("cate30", "原创短剧"), ("cate31", "足交口爆"), ("cate32", "炮桶小屋"),
    ("cate33", "无套内射"), ("cate34", "黑鬼长屌"), ("cate35", "女同百合"),
    ("cate36", "伪娘人妖"), ("cate37", "吴梦梦"), ("cate39", "umate原创"),
    ("cate40", "Naomii"), ("cate41", "YuiPeach"), ("cate42", "唐伯虎"),
    ("cate43", "饼干姐姐"), ("cate44", "台北娜娜"), ("cate45", "MASKU"),
    ("cate46", "Xreind"), ("cate47", "小桃酱"), ("cate48", "安安小晗"),
    ("cate49", "柚子猫"), ("cate50", "王梨奈"), ("cate51", "辛尤里"),
    ("cate52", "粉色情人"), ("cate53", "阿朱"), ("cate54", "奶咪"),
    ("cate55", "有根棒棒"), ("cate56", "不见星空"), ("cate57", "Kitty"),
    ("cate58", "妮可"), ("cate59", "Cos女神"), ("cate60", "玩偶姊姊"),
    ("cate61", "司雨"), ("cate62", "谭晓彤"), ("cate63", "刘玥"),
    ("cate64", "Vivian"), ("cate65", "多乙"), ("cate66", "朱可儿"),
    ("cate67", "周大萌"), ("cate69", "麻豆传媒"), ("cate70", "蜜桃传媒"),
    ("cate71", "葫芦影业"), ("cate72", "香蕉视频"), ("cate73", "兔子先生"),
    ("cate74", "OnlyFans"), ("cate75", "91制片厂"), ("cate76", "ED Mosaic"),
    ("cate77", "IBiZa Media"), ("cate78", "SA国际传媒"), ("cate79", "乌托邦"),
    ("cate80", "大象传媒"), ("cate81", "天美传媒"), ("cate82", "扣扣传媒"),
    ("cate83", "性视界"), ("cate84", "星空传媒"), ("cate85", "映秀传媒"),
    ("cate86", "杏吧原版"), ("cate87", "果冻传媒"), ("cate88", "爱神传媒"),
    ("cate89", "爱豆传媒"), ("cate90", "精东影业"), ("cate91", "糖心Vlog"),
    ("cate92", "萝莉社"), ("cate94", "桥本香菜"), ("cate95", "米菲兔"),
    ("cate96", "捅主任"), ("cate97", "npxvip"), ("cate98", "Andm"),
    ("cate99", "liburin"), ("cate100", "谭晓彤"), ("cate101", "小水水"),
    ("cate102", "小鸟酱"), ("cate103", "HAMAR"), ("cate104", "铃木美子"),
    ("cate105", "占星猫"), ("cate106", "芋圆呀"), ("cate107", "小丁妹妹"),
    ("cate108", "米娜学姐"), ("cate109", "米胡桃"), ("cate110", "萌白酱"),
    ("cate111", "麻酥酥"), ("cate112", "白桃少女"), ("cate113", "八月未央"),
    ("cate115", "网红大瓜"), ("cate116", "校园猛料"), ("cate117", "大奶孕妇"),
    ("cate118", "独家泄密"), ("cate119", "热门吃瓜"), ("cate120", "潜规则"),
    ("cate121", "反差泄露"), ("cate122", "裸贷风波"), ("cate123", "轮奸呀"),
    ("cate124", "饥渴新娘"), ("cate125", "强奸醉奸"), ("cate126", "迷奸"),
    ("cate128", "AnnyWalker"), ("cate129", "MilaAzul"), ("cate130", "Comatozze"),
    ("cate131", "Honey"), ("cate132", "Luxury"), ("cate133", "kittyxk"),
    ("cate134", "JennyKitty"), ("cate135", "LeoLulu"), ("cate136", "PurpleB"),
    ("cate137", "MilaLioness"), ("cate138", "Pinklov"), ("cate139", "PornForce"),
    ("cate140", "Shinaryen"), ("cate141", "EvaElfie"), ("cate142", "Candy"),
    ("cate143", "Kenzie"), ("cate144", "CarlaCu"), ("cate145", "webto"),
    ("cate146", "SiaSib"), ("cate148", "沈先生"), ("cate149", "赵总寻花"),
    ("cate150", "小天探花"), ("cate151", "换妻探花"), ("cate152", "七天探花"),
    ("cate153", "千人斩"), ("cate154", "午夜尋花"), ("cate155", "91大神"),
    ("cate156", "按摩会所"), ("cate157", "韩国嫖妓"), ("cate158", "陈先生"),
    ("cate159", "太子寻花"), ("cate160", "翼屌寻花"), ("cate161", "小宝寻花"),
    ("cate162", "文轩探花"), ("cate164", "兄妹情深"), ("cate165", "最爱岳母"),
    ("cate166", "淫荡儿媳"), ("cate167", "淫乱父女"), ("cate168", "照顾小侄女"),
    ("cate169", "师生恋情"), ("cate170", "母子情深"), ("cate171", "姐弟爱恋"),
    ("cate172", "调教嫂子"), ("cate173", "照顾小姨子"), ("cate175", "韩国三级"),
    ("cate176", "香港三级"), ("cate177", "台湾三级"), ("cate178", "欧洲情色"),
    ("cate179", "俄乌色情"), ("cate180", "越南菲律宾"), ("cate181", "印度情色"),
    ("cate182", "日本三级"), ("cate183", "美国色情"), ("cate184", "东南亚情色"),
    ("cate186", "多人淫交"), ("cate187", "车震直播"), ("cate188", "日韩主播"),
    ("cate189", "户外直播"), ("cate190", "抖音网红"), ("cate191", "主播勾引"),
    ("cate192", "快手网红"), ("cate193", "对着你"), ("cate194", "AVOVE"),
    ("cate195", "MISSWAEM"), ("cate196", "妖骚蛇姬"), ("cate197", "大啵啵"),
    ("cate198", "虎牙辣妹"), ("cate200", "古装诱惑"), ("cate201", "萝莉塔"),
    ("cate202", "空姐诱惑"), ("cate203", "丝袜诱惑"), ("cate204", "职场OL"),
    ("cate205", "清涩校服"), ("cate206", "三点泳装"), ("cate207", "JK短裙"),
    ("cate208", "女仆装"), ("cate209", "护士打针"), ("cate210", "国风旗袍"),
    ("cate211", "体操运动"), ("cate212", "其他制服"), ("cate214", "骑兵精选"),
    ("cate215", "高清优质"), ("cate216", "FC2高清"), ("cate217", "VR视觉"),
    ("cate218", "人妻巨乳"), ("cate219", "少女制服"), ("cate220", "药物迷奸"),
    ("cate221", "强暴系列"), ("cate222", "轮奸系列"), ("cate223", "筱田佑"),
    ("cate224", "森澤佳奈"), ("cate225", "三上悠亜"), ("cate226", "AkihoYoshizawa"),
    ("cate227", "神宮寺奈緒"), ("cate228", "藤森里穗"), ("cate229", "松本一香"),
    ("cate230", "乙爱丽丝"), ("cate231", "沙月芽衣"), ("cate232", "姬咲華"),
    ("cate233", "AliceOtsu"), ("cate234", "佐山愛"), ("cate235", "水果解說"),
    ("cate237", "推荐观看"), ("cate238", "颜值少女"), ("cate239", "网红洋马"),
    ("cate240", "CandyLove"), ("cate241", "丝袜制服"), ("cate242", "欧美剧情"),
    ("cate243", "AngelX"), ("cate244", "商场性交"), ("cate245", "情色按摩"),
    ("cate246", "捷克搭讪"), ("cate247", "肤若凝脂"), ("cate248", "SweetieFox"),
    ("cate249", "Morgpie"), ("cate250", "DianRider"), ("cate251", "BadCuteGirl"),
    ("cate252", "Ailish"), ("cate253", "SamanthaFlair"), ("cate254", "滥交群交"),
    ("cate255", "巨乳少女"), ("cate256", "黑人大屌"), ("cate258", "深夜保健室"),
    ("cate259", "王竹子教学"), ("cate260", "中指通一下"), ("cate261", "Misa米砂"),
    ("cate262", "小哥哥艾理"), ("cate263", "Dr.She"), ("cate264", "1G老湿"),
    ("cate265", "两性知识"), ("cate266", "麻豆综艺"), ("cate267", "户外搭讪"),
    ("cate268", "性爱大秀"), ("cate269", "女优训练营"), ("cate270", "情趣k歌房"),
    ("cate271", "小鹏奇啪行"), ("cate272", "性爱自修室"), ("cate273", "女神体育祭"),
    ("cate274", "屁孩日记"), ("cate275", "薇傲的性趣"), ("cate276", "一三蜜桃说"),
    ("cate277", "Carrie雨千"), ("cate279", "喜剧片"), ("cate280", "古装片"),
    ("cate281", "武侠片"), ("cate282", "枪战片"), ("cate283", "灾难片"),
    ("cate284", "冒险片"), ("cate285", "犯罪片"), ("cate286", "科幻片"),
    ("cate287", "动作片"), ("cate288", "恐怖片"),
]

def _clean(s):
    if not s:
        return ""
    s = htmllib.unescape(str(s))
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

class Spider(Spider):
    def getName(self):
        return "汤头条"

    def init(self, extend=""):
        self.host = HOST
        self.s = None
        try:
            self.s = rq.Session()
            self.s.verify = False
            self.s.headers.update({
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": self.host + "/",
            })
        except:
            pass
        self._cache = {}

    def _get(self, path):
        url = path if path.startswith("http") else self.host.rstrip("/") + path
        try:
            r = (self.s or rq).get(
                url, timeout=TIMEOUT, verify=False,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Referer": self.host + "/",
                },
            )
            if r.status_code == 200 and r.text:
                r.encoding = "utf-8"
                return r.text
        except:
            pass
        return ""

    def _get_cached(self, path, ttl=40):
        now = time.time()
        if path in self._cache and now - self._cache[path][1] < ttl:
            return self._cache[path][0]
        t = self._get(path)
        if t:
            self._cache[path] = (t, now)
        return t

    def isVideoFormat(self, url):
        return bool(url and (".m3u8" in url or ".mp4" in url))

    def manualVideoCheck(self):
        return False

    def homeContent(self, filter=False):
        return {
            "class": [{"type_id": c[0], "type_name": c[1]} for c in CATS],
            "list": self._parse_list(self._get_cached("/")),
            "filters": {},
        }

    def homeVideoContent(self):
        return {"list": self._parse_list(self._get_cached("/"))}

    def categoryContent(self, tid, pg=1, filter=False, extend=""):
        try:
            pg = int(pg or 1)
        except:
            pg = 1
        if pg < 1:
            pg = 1
        tid = str(tid or "home").strip()

        if tid in ("home", "0", ""):
            path = "/" if pg <= 1 else f"/{pg}/"
        else:
            path = f"/category/{tid}/" if pg <= 1 else f"/category/{tid}/{pg}/"

        html = self._get_cached(path)
        videos = self._parse_list(html)
        if not videos:
            html = self._get(path)
            videos = self._parse_list(html)

        pages = 50
        if html and tid not in ("home", "0", ""):
            ns = [int(x) for x in re.findall(
                r'/category/' + re.escape(tid) + r'/(\d+)/', html)]
            if ns:
                pages = max(ns)

        return {
            "list": videos,
            "page": pg,
            "pagecount": pages,
            "limit": 20,
            "total": pages * 20,
        }

    def searchContent(self, key, quick=False, pg="1"):
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick, page):
        kw = urllib.parse.quote(str(key or "").strip())
        try:
            pg = int(page or 1)
        except:
            pg = 1
        path = f"/search/{kw}/" if pg <= 1 else f"/search/{kw}/{pg}/"
        html = self._get(path)
        videos = self._parse_list(html)
        pages = pg
        if html:
            ns = [int(x) for x in re.findall(r'/search/[^/]+/(\d+)/', html)]
            if ns:
                pages = max(ns)
        return {
            "list": videos,
            "page": pg,
            "pagecount": max(pages, pg),
            "limit": 20,
            "total": 0,
        }

    def detailContent(self, ids):
        try:
            did = str(ids[0] if isinstance(ids, (list, tuple)) else ids).strip()
        except:
            return {"list": []}
        if not did:
            return {"list": []}
        if not did.startswith("http"):
            did = self.host + (did if did.startswith("/") else "/" + did)

        html = self._get(did)
        if not html:
            return {"list": []}

        title = ""
        m = re.search(r'<h1[^>]*>([^<]+)</h1>', html) or re.search(r'<title>(.*?)</title>', html)
        if m:
            title = _clean(m.group(1).split("|")[0].split("_")[0])

        pic = ""
        pm = re.search(r'data-cover="(https?://[^"]+)"', html)
        if pm:
            pic = pm.group(1)

        play_url = self._extract_play(html) or f"正片${did}"
        return {"list": [{
            "vod_id": did,
            "vod_name": title or "未知",
            "vod_pic": pic,
            "type_name": "汤头条",
            "vod_remarks": "在线",
            "vod_content": title,
            "vod_play_from": "线路1",
            "vod_play_url": play_url,
            "vod_year": "", "vod_area": "", "vod_actor": "", "vod_director": "",
        }]}

    def playerContent(self, flag, id, vipFlags=None, vipIds=None):
        key = str(id or "").strip()
        header = {"User-Agent": UA, "Referer": self.host + "/"}
        if key.startswith("http") and self.isVideoFormat(key):
            return {"parse": 0, "url": key, "header": header}
        html = self._get(key)
        play = self._extract_play(html)
        if play and "$" in play:
            url = play.split("$")[-1]
            if url.startswith("http"):
                return {"parse": 0, "url": url, "header": header}
        return {
            "parse": 1,
            "url": key if key.startswith("http") else self.host + key,
            "header": header,
        }

    def _extract_play(self, html):
        if not html:
            return ""
        m_url = re.search(r'data-url="([^"]+)"', html)
        m_cdn = re.search(r'data-cdnline="([^"]+)"', html)
        if m_url and m_cdn:
            path = m_url.group(1).strip()
            cdn = m_cdn.group(1).rstrip("/")
            if path.startswith("http"):
                return f"正片${path}"
            return f"正片${cdn}{path}"
        for u in re.findall(r'["\']([^"\']+\.m3u8[^"\']*)["\']', html):
            u = htmllib.unescape(u)
            if u.startswith("http"):
                return f"正片${u}"
            if u.startswith("/") and m_cdn:
                return f"正片${m_cdn.group(1).rstrip('/')}{u}"
        return ""

    def _parse_list(self, html):
        if not html or len(html) < 200:
            return []
        # 封面：data-cover + 视频id（class 里 img{id}0）
        covers = {}
        for m in re.finditer(r'<img([^>]+)>', html):
            tag = m.group(1)
            cm = re.search(r'data-cover="(https?://[^"]+)"', tag)
            vm = re.search(r'img(\d{15,})', tag)
            if cm and vm:
                vid = vm.group(1)
                # 去掉末尾序号 0/1
                if vid[-1] in "0123456789" and len(vid) > 15:
                    # class 形如 img2042...280 / img2042...281
                    for v in covers:
                        pass
                    # 用最长公共：去掉最后1位
                    base = vid[:-1]
                    if base not in covers:
                        covers[base] = cm.group(1)
                if vid not in covers:
                    covers[vid] = cm.group(1)

        videos, seen = [], set()
        for m in re.finditer(r'href="(/video/(\d+)/)"[^>]*title="([^"]+)"', html):
            href, vid, title = m.group(1), m.group(2), _clean(m.group(3))
            if vid in seen or not title or title in ("HD", "畅看"):
                continue
            seen.add(vid)
            pic = covers.get(vid) or covers.get(vid + "0") or ""
            if not pic:
                # 邻近片段再找
                chunk = html[max(0, m.start() - 500):m.end() + 200]
                cm = re.search(r'data-cover="(https?://[^"]+)"', chunk)
                if cm:
                    pic = cm.group(1)
            videos.append({
                "vod_id": self.host + href,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": "在线",
            })
        if videos:
            return videos

        for m in re.finditer(r'href="(/video/(\d+)/)"[^>]*>([^<]{4,})', html):
            href, vid, title = m.group(1), m.group(2), _clean(m.group(3))
            if vid in seen or not title or title in ("HD", "畅看"):
                continue
            seen.add(vid)
            pic = covers.get(vid) or ""
            videos.append({
                "vod_id": self.host + href,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": "在线",
            })
        return videos