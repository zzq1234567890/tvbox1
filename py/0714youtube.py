#coding=utf-8
#!/usr/bin/python
import re
import os
import sys
import json
import html
import time
from urllib.parse import quote, unquote, parse_qs, urlencode, urlparse, urlunparse
import requests
from base.spider import Spider
sys.path.append('..')

DEBUG_LOG = '/sdcard/Download/0712youtube_trace.log'

YOUTUBE_CLASSES = [
    # 原有分类保留
    {'type_id': '4K', 'type_name': '4K'},
    {'type_id': 'HDR', 'type_name': 'HDR'},
    {'type_id': '自然', 'type_name': '自然'},
    {'type_id': '动画片', 'type_name': '动画片'},
    {'type_id': '短剧', 'type_name': '短剧'},
    {'type_id': '剧集', 'type_name': '剧集'},
    {'type_id': '电影', 'type_name': '电影'},
    {'type_id': '纪录片', 'type_name': '纪录片'},
    {'type_id': '放松', 'type_name': '放松'},
    {'type_id': '16K HDR', 'type_name': '16K HDR'},
    {'type_id': '科技', 'type_name': '科技'},
    {'type_id': '解说', 'type_name': '解说'},
    # 从 JSON 新增的分类
    {'type_id': '新闻直播', 'type_name': '新闻直播'},
    {'type_id': '动漫', 'type_name': '动漫'},
    {'type_id': '综艺', 'type_name': '综艺'},
    {'type_id': '政论', 'type_name': '政论'},
    {'type_id': '体育', 'type_name': '体育'},
    {'type_id': '时尚潮流', 'type_name': '时尚潮流'},
    {'type_id': '科普知识', 'type_name': '科普知识'},
    {'type_id': '自媒体', 'type_name': '自媒体'},
    {'type_id': '音乐', 'type_name': '音乐'},
    {'type_id': '神秘', 'type_name': '神秘'},
]

CATEGORY_QUERY = {
    '动画片': '动画 国漫 anime cartoon',
    '短剧': '短剧',
    '剧集': '电视剧 剧集 drama',
    '电影': '电影 movie',
    '纪录片': '纪录片 documentary',
    '放松': '放松 冥想 自然 音乐 relax meditation nature',
    '4K': '4K video',
    'HDR': 'HDR video',
    '自然': '大自然 风景 动物 世界 nature wildlife scenery',
    '16K HDR': '16K HDR video',
    '科技': '科技 technology',
    '解说': '电影解说 故事解说',
    # 新增分类的基础搜索词
    '新闻直播': '新闻 Live 直播',
    '动漫': '动漫 国漫 anime',
    '综艺': '综艺 variety show',
    '政论': '政论 观点',
    '体育': '体育 赛事 sports',
    '时尚潮流': '时尚 走秀 潮流',
    '科普知识': '宇宙 科普 历史',
    '自媒体': '自媒体 We Media',
    '音乐': '华语音乐 MV 音乐',
    '神秘': '神秘 未解之谜',
}

CATEGORY_ALIASES = {
    # 原有别名
    '動畫片': '动画片',
    '劇集': '剧集',
    '電影': '电影',
    '紀錄片': '纪录片',
    '解說': '解说',
    'movie': '电影',
    'game': '科技',
    'documentary': '纪录片',
    # 新增繁体/别名映射
    '新聞直播': '新闻直播',
    '動漫': '动漫',
    '綜藝': '综艺',
    '政論': '政论',
    '體育': '体育',
    '時尚潮流': '时尚潮流',
    '自媒體': '自媒体',
    '音樂': '音乐',
    '科普知識': '科普知识',
    # 处理 JSON 中复杂的 LIST type_id 映射
    'LIST:新闻 Live,体育直播,赛事直播': '新闻直播',
    'LIST:剧集,腾讯剧集,爱奇艺剧集,优酷剧集,芒果剧集,TVB,亞視精選,ATV 亞洲電視,八大劇樂部,民視戲劇,三立台劇,三立華劇,龍華戲劇,華視懷舊頻道,華視戲劇,中視經典戲劇': '剧集',
    'LIST:紀錄片,亞洲旅遊台,CCTV纪录,CCTV科教,公視+,National Geographic,Kevin_YOLO,Nat Geo Animals,BBC Earth,Top Travel,National Geographic India,BBC Earth Science,历史纪录片,自然纪录片,宇宙纪录片': '纪录片',
    'LIST:動漫,腾讯视频 - 动漫,一号动漫社 Animation Club,蒼穹動漫社Animation Club,斗破动漫社 Animation,腾讯动漫,爱奇艺动漫,优酷动漫,芒果动漫,Ani-Mi動漫迷動畫頻道,3D国漫工厂,阅文动漫,卡通狂欢嘉会': '动漫',
    '短劇': '短剧',
    'LIST:综艺,台視時光機,芒果综艺,腾讯综艺,爱奇艺综艺,优酷综艺,卫视综艺,超級夜總會': '综艺',
    'LIST:政論,觀點,豐富,Yahoo風向,全球大視野,環球大戰線,郭正亮頻道,論政天下,岑永康': '政论',
    '體育': '体育',
    '宇宙': '科普知识',
    'LIST:自媒體 We Media,老高與小茉 @laogao,脑洞乌托邦 @NDWTB,自说自话的总裁 @STBoss,纪实说 @C-Documentary,老肉雜談 @老肉雜談,李永樂老師 @TchLiyongle,滇西小哥 @dianxixiaoge,李子柒 Liziqi @cnliziqi,老饭骨 @LaoFanGu,小高姐的 Magic Ingredients @MagicIngredients,小穎美食 @XiaoYingFood,primitivetechnology9550 @primitivetechnology9550,Mr Beast@MrBeast,Airforceproud95 @Airforceproud95,TheGreatWar @TheGreatWar,Mark Rober @MarkRober,不良林,涌哥侃侃 @ygkkk,悟空的日常': '自媒体',
    'LIST:HDR,Girls HDR,Landscape HDR,Walk HDR': 'HDR',
    'LIST:华语音乐,华语MV,点击率最高': '音乐',
}

def _filter_group(key, name, pairs):
    return {
        'key': key,
        'name': name,
        'value': [{'n': '全部', 'v': ''}] + [{'n': n, 'v': v} for n, v in pairs]
    }

def _with_year(*groups):
    years = [{'n': '全部', 'v': ''}] + [{'n': str(year), 'v': str(year)} for year in range(2026, 1957, -1)]
    return [{'key': 'year', 'name': '年份', 'value': years}] + list(groups)

CATEGORY_FILTERS = {
    '动画片': _with_year(
        _filter_group('topic', '中文', [
            ('国漫', '国漫 3D 动画'), ('儿童早教', '儿童早教'), ('儿童歌曲', '儿童歌曲'),
            ('儿童音乐', '儿童音乐'), ('儿童绘画', '儿童绘画'), ('宝宝巴士', '宝宝巴士'),
            ('儿歌多多', '儿歌多多'), ('英语启蒙', '儿童英语启蒙'), ('安全教育', '儿童安全教育'),
            ('默认中文国漫', '國漫 劇集 3D'), ('儿童启蒙故事', '儿童启蒙故事'),
        ]),
        _filter_group('channel', '频道', [
            ('小猪佩奇', '@PeppaPigChineseOfficial 小猪佩奇 中文'), ('CoComelon', '@CoComelon'),
            ('国漫合集', 'Anime ENG SUB 合集 国漫'), ('阅文动漫', '@yuewenanimation'),
            ('哔哩动漫', '@madebybilibili 哔哩动漫'), ('腾讯动漫', '@TencentVideoAnimation'),
            ('优酷动漫', '@youkuanimation 优酷动漫'), ('爱奇艺动漫', '@iQIYIAnime 爱奇艺动漫'),
            ('默认英文国漫', '3D Chinese cartoon'),
        ])
    ),
    '短剧': _with_year(
        _filter_group('region', '地区/平台', [
            ('抖音', '抖音 短剧'), ('快手', '快手 短剧'), ('大陆', '大陆 短剧'),
            ('香港', '香港 短剧'), ('澳门', '澳门 短剧'), ('台湾', '台湾 短剧'),
            ('新加坡', '新加坡 短剧'), ('马来西亚', '马来西亚 短剧'), ('泰国', '泰国 短剧'),
            ('越南', '越南 短剧'), ('印度', '印度 短剧'), ('韩国', '韩国 短剧'),
            ('日本', '日本 短剧'), ('欧美', '欧美 短剧'), ('腾讯', '腾讯 短剧'),
            ('爱奇艺', '爱奇艺 短剧'), ('优酷', '优酷 短剧'), ('芒果', '芒果TV 短剧'), ('搜狐', '搜狐 短剧'),
        ]),
        _filter_group('topic', '题材/频道', [
            ('都市', '@Urbanshort-TV 都市 短剧'), ('爱情', '爱情 短剧'), ('复仇', '复仇 短剧'),
            ('穿越', '穿越 短剧'), ('喜剧', '喜剧 短剧'), ('奇幻', '奇幻 短剧'),
            ('九酱爱追剧', '@NineSauceDramaTV'), ('百万好剧场', '@1-pw5ox'),
            ('咖啡追剧', '@coffeedrama605'), ('斗罗短剧', '@DouluoDrama123 斗罗短剧'),
            ('嘟嘟剧场', '@DUDUJUCHANG'), ('牛牛短剧', '@niuniuduanju'),
        ])
    ),
    '剧集': _with_year(
        _filter_group('region', '中文', [
            ('华语热播电视剧官方频道', '華語熱播電視劇官方頻道'), ('粤剧', '粵劇 劇集'), ('TVB', '@TVB'),
            ('亚视精选', '@drama_asia'), ('ATV 亚洲电视', '@atvhongkong'), ('民视剧集', '@FTVDRAMA'),
            ('八大剧乐部', '@gtv-drama'), ('三立华剧', '@SETdrama'), ('华视怀旧频道', '@cts_arch'),
            ('三立台剧', '@setdramatw'), ('华视戏剧', '@cts_drama'), ('龙华电视', '@ltv_tw'),
            ('中视经典戏剧', '@ctvdrama_classic'), ('国剧放映社', '国剧放映社'), ('大陆', '大陆 剧集'),
            ('腾讯', '腾讯 剧集'), ('爱奇艺', '爱奇艺 剧集'), ('优酷', '优酷 剧集'),
            ('芒果', '芒果TV 剧集'), ('搜狐', '搜狐 剧集'), ('华数', '华数 剧集'), ('港台', '港台 剧集'),
            ('美国', '美国 Full Episode 完整剧集'), ('Netflix', 'Netflix Full Episode 完整剧集'),
            ('Disney', 'disney Full Episode 完整剧集'), ('Apple', 'apple Full Episode 完整剧集'),
            ('Amazon', 'amazon Full Episode 完整剧集'), ('HBO', 'hbo Full Episode 完整剧集'),
            ('韩国', '韩国 剧集'), ('日本', '日本 剧集'), ('英国', '英国 Full Episode 完整剧集'),
        ]),
        _filter_group('platform', 'English', [
            ('Drama', 'Full Episode drama'), ('US', 'drama Full Episode US'),
            ('Netflix', 'netflix Full Episode drama'), ('Disney', 'disney Full Episode drama'),
            ('Apple', 'apple Full Episode drama'), ('Amazon', 'amazon Full Episode drama'),
            ('HBO', 'hbo Full Episode drama'), ('Korea', 'korea Full Episode drama'),
            ('Japan', 'japan Full Episode drama'), ('UK', 'uk Full Episode drama'),
        ])
    ),
    '电影': _with_year(
        _filter_group('region', '中文', [
            ('大陆', '大陆 电影'), ('腾讯', '腾讯 电影'), ('爱奇艺', '爱奇艺 电影'),
            ('优酷', '优酷 电影'), ('芒果', '芒果TV 电影'), ('搜狐', '搜狐 电影'),
            ('港台', '港台 电影'), ('美国', '美国 电影'), ('Netflix', 'netflix Full movie 电影'),
            ('Disney', 'disney Full movie 电影'), ('Apple', 'apple Full movie 电影'),
            ('Amazon', 'amazon Full movie 电影'), ('HBO', 'hbo Full movie 电影'),
            ('韩国', '韩国 Full movie 电影'), ('日本', '日本 Full movie 电影'), ('英国', '英国 Full movie 电影'),
        ]),
        _filter_group('platform', 'English', [
            ('movie', 'youtube movies Full movie'), ('US', 'us Full movie movie'),
            ('Netflix movie', 'netflix Full movie movie'), ('Disney', 'disney Full movie movie'),
            ('Apple', 'apple Full movie movie'), ('Amazon', 'amazon Full movie movie'),
            ('HBO', 'hbo Full movie movie'), ('Koera', 'korea Full movie movie'),
            ('Japan', 'japan Full movie movie'), ('UK', 'uk Full movie movie'),
        ])
    ),
    '纪录片': _with_year(
        _filter_group('topic', '中文', [
            ('亚洲旅游台', '@asiatravel-tv'), ('CCTV纪录', '@CCTVDocumentary'), ('CCTV科教', '@cctvscienceandeducation'),
            ('Top Travel', '@toptravel_yt'), ('公视+', '@ptsplus'), ('National Geographic', '@natgeo'),
            ('Kevin_YOLO', '@kevin_YOLO'), ('Nat Geo Animals', '@natgeoanimals'), ('BBC Earth', '@bbcearth'),
            ('National Geographic India', '@natgeoindia'), ('BBC Earth Science', '@bbcearthscience'),
            ('BBC纪录片', 'BBC 纪录片'), ('国家地理', '国家地理 纪录片'), ('Netflix纪录片', 'netflix 纪录片'),
            ('历史', '历史 纪录片'), ('野性', '野性 纪录片 wild documentary'),
            ('地球', '地球 纪录片 earth documentary'), ('宇宙', '宇宙 纪录片 universe documentary'),
            ('海洋', '海洋 纪录片 oceans documentary'), ('人文', '人文 纪录片'), ('战争', '战争 纪录片 war documentary'),
        ]),
        _filter_group('platform', 'English', [
            ('默认', 'documentary'), ('National Geographic', '@natgeo'),
            ('History', 'Full history documentary'), ('WILD', 'Full wild documentary'),
            ('Earch', 'Full earth documentary'), ('Universe', 'Full universe documentary'),
            ('Oceans', 'Full oceans documentary'), ('Humanism', 'Full humanism documentary'),
            ('Wars', 'Full war documentary'),
        ])
    ),
    '放松': [
        _filter_group('topic', '主题', [
            ('冥想', '冥想 放松 meditation relax'), ('睡眠', '睡眠 放松 sleep relax'),
            ('白噪音', '白噪音 放松 white noise'), ('自然声音', '自然 声音 放松 nature sounds'),
            ('雨声', '雨声 放松 rain sounds'), ('海浪', '海浪 放松 ocean waves'),
        ])
    ],
    '4K': [
        _filter_group('topic', '主题', [
            ('风景', '4K 风景 scenery'), ('城市', '4K 城市 city walk'), ('旅行', '4K travel'),
            ('动物', '4K wildlife animals'), ('航拍', '4K drone aerial'), ('演示片', '4K demo video'),
        ])
    ],
    'HDR': [
        _filter_group('topic', '风景', [
            ('运动', 'GoPro 女翼裝飛行 極限自行車運動'), ('风景', 'hdr 大自然'),
            ('Links TV频道主', '@linksphotograph Links TV hdr'), ('放松', 'hdr 放鬆'),
            ('动物世界', 'hdr Carnivorous Animals 動物世界'), ('深海世界', 'hdr Invertebrate Fish 深海世界'),
            ('飞禽走兽', 'hdr Birds of Prey Columbiform Birds Passerine Birds'), ('生物世界', 'hdr Amphibians Reptiles 生物世界'),
        ])
    ],
    '自然': [
        _filter_group('topic', '主题', [
            ('风景', '大自然 风景 nature scenery'), ('动物世界', '动物世界 wildlife documentary'),
            ('海洋', '海洋 自然 ocean nature'), ('森林', '森林 自然 forest nature'),
            ('鸟类', '鸟类 自然 birds nature'), ('地球', '地球 自然 earth nature'),
            ('国家地理', 'National Geographic nature wildlife'), ('BBC Earth', 'BBC Earth nature'),
        ])
    ],
    '16K HDR': [
        _filter_group('topic', '风景', [
            ('运动', 'GoPro 极限自行车 翼装飞行'), ('风景', 'hdr 大自然 风景'),
            ('Links TV', '@linksphotograph Links TV hdr'), ('放松', 'hdr 放松'),
            ('动物世界', 'hdr Carnivorous Animals 动物世界'), ('深海世界', 'hdr Invertebrate Fish 深海世界'),
            ('飞禽走兽', 'hdr Birds of Prey Birds'), ('生物世界', 'hdr Amphibians Reptiles 生物世界'),
        ])
    ],
    '科技': [
        _filter_group('topic', '主题', [
            ('AI', '人工智能 AI technology'), ('数码', '数码 科技 technology'),
            ('手机', '手机 评测 technology'), ('电脑', '电脑 科技 technology'),
            ('汽车科技', '汽车 科技 technology'), ('太空', '航天 太空 technology'),
        ])
    ],
    '解说': [
        _filter_group('channel', '频道主', [('宇哥侃故事', '@yuge'), ('零度解说', '@lingdujieshuo')])
    ],
    # --- 以下为从 JSON 新增的筛选规则 ---
    '新闻直播': [
        _filter_group('live', '中文直播', [
            ('赛事', '直播 赛事'), ('CCTV', '直播 CCTV'), ('港台', '直播 港台'),
        ]),
        _filter_group('live_eng', 'English Live', [
            ('Live', 'live'), ('CNN', 'live CNN'), ('BBC', 'live BBC'),
            ('games', 'live games'), ('印度电视台', '@SETIndia'),
        ]),
        _filter_group('news', '中文新闻', [
            ('时政', '时政 新闻'), ('体育', '体育 新闻'), ('娱乐', '娱乐 新闻'),
            ('大陆', '大陆 新闻'), ('港台', '港台 新闻'),
        ]),
        _filter_group('news_eng', 'English News', [
            ('科技与发展', '閱兵 奧運會 航母 航空母艦 潛水艇 核武器 坦克 武器 卫星 火箭 輪船 飛機 飛碟'),
            ('法治与社会', '法治 法制 社会 卖淫 淫秽 污蔑 赌博 毒品 裸聊 诈骗 拐卖 强奸 勒索'),
            ('News', 'News'), ('CNN', 'CNN news'), ('BBC', 'BBC news'),
        ])
    ],
    '政论': _with_year(
        _filter_group('topic', '中文', [
            ('观点', '@觀點'), ('丰富', '@豐富'), ('论政天下', '@論政天下2024'),
            ('Yahoo风向', '@YahooTWlisten'), ('全球大视野', '@全球大視野Global_Vision'),
            ('环球大战线', '@Global-vision-talk'), ('郭正亮频道', '@Guovision-TV'), ('岑永康', '@cyk33'),
        ])
    ),
    '综艺': _with_year(
        _filter_group('region', '中文', [
            ('台视时光机', '@ttvclassic'), ('超级夜总会', '@SuperNightClubCH2'),
            ('大陆', '大陆 综艺'), ('芒果', '芒果 综艺'), ('腾讯', '腾讯 综艺'),
            ('爱奇艺', '爱奇艺 综艺'), ('优酷', '优酷 综艺'), ('港台', '港台 综艺'),
            ('美国', '美国 综艺'), ('Netflix', 'Netflix 综艺'), ('韩国', 'CRAVITY on Variety Shows 韩国 综艺'),
            ('日本', '日本 综艺'), ('英国', '英国 综艺'),
        ]),
        _filter_group('platform', 'English', [
            ('Variety', 'variety'), ('Netflix variety', 'netflix variety'),
            ('Korea', 'korea variety'), ('Japan', 'japan variety'), ('UK', 'uk variety'),
        ]),
        _filter_group('comedy', '小品', [
            ('春晚小品', '春晚小品'), ('开心麻花', '开心麻花'), ('屌丝男士', '屌丝男士'),
            ('喜剧综艺', '喜剧综艺'), ('单口', '单口 相声'), ('群口', '群口 相声'),
            ('德云社', '德云社'), ('青曲社', '青曲社'), ('郭德纲', '郭德纲'),
            ('岳云鹏', '岳云鹏'), ('曹云金', '曹云金'), ('评书', '评书'),
            ('小曲', '小曲'), ('赵本山', '赵本山'), ('陈佩斯', '陈佩斯'),
            ('冯巩', '冯巩'), ('宋小宝', '宋小宝'), ('赵丽蓉', '赵丽蓉'),
            ('潘长江', '潘长江'), ('郭冬临', '郭冬临'), ('严顺开', '严顺开'), ('文松', '文松'),
        ])
    ),
    '体育': _with_year(
        _filter_group('topic', '中文', [
            ('体育直播', '体育直播'), ('体育赛事', '体育赛事'), ('足球比赛', '足球賽事'),
            ('篮球比赛', '篮球賽事'), ('极限运动', '极限運動'), ('室内运动', '室内运动'),
            ('户外运动', '户外运动'), ('健身运动', '健身運動'),
        ]),
        _filter_group('topic_eng', 'English', [
            ('Live', 'live sports'), ('Games', 'live games'), ('Soccer', 'live soccer'),
            ('NBA', 'NBA'), ('Extreme', 'extreme sports'), ('InDoor', 'indoor sports'),
            ('OutDoor', 'outdoor sports'), ('Workout', 'workout'),
        ]),
        _filter_group('channel', '体育频道', [
            ('女足港场', '女足港場 @Hong KongWomensStadium'),
            ('全国校运动会', '全國大專 校院運動會 全中運 女子組賽事 全國中等 學校運動會'),
            ('女中仪队', '北一女中樂儀旗隊永續發展協會 北一女中家長會樂儀旗家長後援會 北一女中儀隊校友隊 台灣 学校运动会 景美女中儀隊 北一女樂儀旗隊 full樂儀隊'),
            ('校园热舞', 'full 校園熱舞 開南熱無 開南大學課外活動組 女生熱舞社 南寶熱舞社 寶踐熱舞社 NTDC 熱舞社 STUST'),
            ('红星体育官方频道', '红星体育官方频道【高清直播】'), ('中国体育比赛传奇', '中國體育比賽傳奇'),
            ('爱尔达体育家族', '愛爾達體育家族 ELTA Sports'), ('公视体育', '公視體育'),
            ('体育之光', '體育之光'), ('偶然体育赛事', '偶然體育賽事'),
        ])
    ),
    '音乐': _with_year(
        _filter_group('region', '地区', [
            ('华语音乐', '華語音樂'), ('华语MV', '華語MV'), ('环球视听', '环球视听1980 @RippleOfficialEvent'),
            ('YouTube 点阅率最高', 'YouTube 點閱率最高觀看次數最多華語歌曲'), ('海外抖音', 'TikTok 翻唱 抖音 音樂'),
            ('粤语', '粵語 音樂'), ('国语', '國語 音樂'), ('大陆', '大陆 音乐'),
            ('香港', '香港 音乐'), ('台湾', '台湾 音乐'), ('新加坡', '新加坡 音乐'),
            ('马来西亚', '馬來西亞 音乐'), ('泰国', '泰國 音乐'), ('越南', '越南 音乐'),
            ('印度', '印度 音乐'), ('韩国', '韩国 音乐'), ('日本', '日本 音乐'), ('欧美', '欧美 音乐'),
        ]),
        _filter_group('hobby', '爱好', [
            ('舞曲', '慢搖 夜店 低音 女聲'), ('80-90', '80 90 音樂'), ('人声', '人聲 音樂'),
            ('A8制造', 'A8製造 工體音樂'), ('硬歌', '深水炸彈 音樂'), ('失传已久', '嗨音雷虎 失傳 嗨音會所 音樂'),
            ('重低音DJ', '3D 8D 慢搖 重低音 音樂'), ('车载舞曲', '車載慢搖DJ歌曲串燒 深水炸彈DJ歌曲串燒 越南鼓DJ歌曲串燒 音樂'),
            ('超级女声', '超級女聲'), ('tseries', '@tseries'),
        ]),
        _filter_group('singer', '歌手', [
            ('迈克尔杰克逊', '邁克爾傑克遜 演唱會，巡演 音樂'), ('张玮伽', '張瑋伽 演唱會 巡演 音樂'),
            ('孙露', '孫露 演唱會 巡演 音樂'), ('凤凰传奇', '鳳凰傳奇 演 巡演 音樂'),
            ('龙梅子', '龍梅子 演唱會 巡演 音樂'), ('刀郎', '刀郎 演唱會 巡演 音樂'),
            ('S.H.E', 'S.H.E 演唱會 巡演 音樂'), ('慕容晓晓', '慕容曉曉 演唱會 巡演 音樂'),
            ('东方红艳', '東方紅豔 演唱會 巡演 音樂'), ('孟庭苇', '孟庭葦 演唱會 巡演 音樂'),
            ('斯琴高丽', '斯琴高麗 演唱會 巡演 音樂'), ('程响', '程響 演唱會 巡演 音樂'),
            ('蒋雪儿', '蔣雪兒 演唱會 巡演 音樂'),
        ])
    ),
    '时尚潮流': [
        _filter_group('show', '时装秀', [
            ('街舞', '脫衣舞 丁字褲 街舞 太空步 機械舞 舞 裸體舞蹈 霹靂舞 魔性舞蹈 鬼步舞 木偶舞 女性藝術舞蹈'),
            ('时尚走秀', 'T台走秀 lingerie show'), ('时装秀', 'hdr ASM lingerieTV 東京ファッションショー 下着ショー'),
            ('潮流秀', 'FASHION IN UHD'), ('时装模特', 'FASHION Runway'),
            ('模特', '比基尼 泳裝 頂級車模 空姐 寫真 Car model Stewardess Portrait'),
            ('裸体秀', 'hdr 人體藝術 裸体秀 Nude show'),
            ('无限乱斗', 'hdr 廟會秀 無限HD 公廟 鋼管舞 脫衣舞 舞女 清純 寫真'),
        ]),
        _filter_group('girl', '小姐姐', [
            ('小姐姐超清', '小姐姐超清'), ('国内小姐姐', '快手模特 抖音模特 国内小姐姐'),
            ('韩国小姐姐', '韩国小姐姐'), ('日本小姐姐', '日本小姐姐'), ('俄罗斯小姐姐', '俄罗斯小姐姐'),
            ('混血小姐姐', '混血小姐姐'), ('越南小姐姐', '越南小姐姐'), ('Al小姐姐', 'Al美女超清'),
            ('抖音热门小姐姐', '抖音热门小姐姐'), ('快手热门美女', '快手热门美女'), ('打碟小姐姐', '打碟小姐姐'),
            ('冲浪小姐姐', '冲浪小姐姐'), ('蹦迪小姐姐', '蹦迪小姐姐'), ('艺校小姐姐', '艺校小姐姐'),
            ('环球小姐', '环球小姐'), ('泰国人妖', '泰国人妖'), ('人间胸器', '人间胸器'),
        ]),
        _filter_group('girl_eng', 'English', [
            ('sexy Miss', 'sexy Miss'), ('Hot sexy Girl', 'Hot sexy Girl'), ('Korean Girl', 'Korean sexy Girl'),
            ('Japanese Girl', 'Japanese sexy Girl'), ('Russian Girl', 'Russian sexy Girl'),
            ('Vietnamese Girl', 'Vietnamese sexy Girl'), ('AI Girl', 'AI Girl'),
            ('TikTok Hot Siste', 'TikTok Hot sexy Girl'), ('Cute Girl', 'sexy Cute Girl'),
            ('Girl Dj', 'sexy Girl Dj'), ('Girl Surfer', 'sexy Girl Surfer'), ('Dance Girl', 'Dance sexy Girl'),
            ('Miss Universe', 'Miss Universe'), ('Thai Shemale', 'Thai Shemale'),
        ])
    ],
    '科普知识': [
        _filter_group('science', '科普知识', [
            ('宇宙', '光年 黑洞 銀河系 空間站 太空技術'),
            ('粒子', '空間粒子 宇宙磁場 四維空間 元素 量子 光波 光源 靈魂'),
            ('靠蒙', 'microorganism'),
        ]),
        _filter_group('history', '历史科普', [
            ('世界大战', '世界大戰 二戰 日侵 八國聯軍'),
            ('人物', '古代名人 歷史名人 歷代祖先'),
            ('生物进化史', '人類進化 微生物進化 動物進化 地球進化'),
            ('靠蒙', '歷史 History'),
        ])
    ],
    '自媒体': [
        _filter_group('creator', '频道主', [
            ('李子柒', '李子柒 Liziqi @cnliziqi'), ('滇西小哥', '滇西小哥 @dianxixiaoge'),
            ('老高与小茉', '老高與小茉 @laogao'), ('李永乐老师', '李永樂老師 @TchLiyongle'),
        ]),
        _filter_group('food', '美食频道主', [
            ('美食作家王刚', '美食作家王刚 @chefwang'),
            ('小高姐的 Magic Ingredients', '小高姐的 Magic Ingredients @MagicIngredients'),
            ('小颖美食', '小穎美食 @XiaoYingFood'),
        ]),
        _filter_group('wild', '野外频道主', [
            ('野外求生', 'primitivetechnology9550 @primitivetechnology9550'),
        ]),
        _filter_group('science', '科普频道主', [
            ('科普', 'Mr Beast@MrBeast'), ('航天大学', 'Airforceproud95 @Airforceproud95'),
            ('世界大战', 'TheGreatWar @TheGreatWar'), ('MarkRober', 'Mark Rober @MarkRober'),
        ]),
        _filter_group('edu', '教材', [
            ('不良林', '不良林'), ('涌哥侃侃', '涌哥侃侃 @ygkkk'), ('悟空的日常', '悟空的日常'),
        ])
    ],
}

def debug_log(message, data=None):
    try:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        if data is not None:
            if isinstance(data, (dict, list)):
                line += ' ' + json.dumps(data, ensure_ascii=False, default=str)
            else:
                line += ' ' + str(data)
        with open(DEBUG_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass

class YouTubeLite:
    def __init__(self, session, headers=None, config=None):
        self.session = session
        self.headers = headers or {}
        self.config = config or {}
        self.player_cache = {}
        self.extract_cache = {}
        self.sig_plan_cache = {}
        self.extract_cache_ttl = int(self.config.get('extract_cache_ttl') or 300)

    def extract(self, url_or_id):
        video_id = self.extract_video_id(url_or_id)
        cached = self.extract_cache.get(video_id)
        now = time.time()
        if cached and cached.get('expires', 0) > now:
            debug_log('extract cache hit', {'video_id': video_id, 'ttl': int(cached.get('expires', 0) - now)})
            return cached.get('data')
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        extract_started = time.time()
        debug_log('extract start', {'input': url_or_id, 'video_id': video_id})
        watch_started = time.time()
        page_resp = self._get(watch_url)
        page = page_resp.text
        debug_log('watch page', {'status': page_resp.status_code, 'length': len(page), 'cost_ms': int((time.time() - watch_started) * 1000)})
        ytcfg = self._extract_ytcfg(page) or {}
        player_response = self._extract_initial_player_response(page) or {}
        player_url = self._extract_player_url(page)
        api_key = ytcfg.get('INNERTUBE_API_KEY') or self._search(r'"INNERTUBE_API_KEY":"([^"]+)"', page)
        visitor_data = self._extract_visitor_data(ytcfg, player_response)
        # ANDROID_VR 返回明文 URL，不需要下载 base.js 提取 signatureTimestamp。
        sts = None
        debug_log('page parsed', {'has_ytcfg': bool(ytcfg), 'has_initial_pr': bool(player_response), 'initial_status': (player_response.get('playabilityStatus') or {}).get('status'), 'initial_has_streaming': bool(player_response.get('streamingData')), 'has_api_key': bool(api_key), 'has_visitor': bool(visitor_data), 'sts': sts, 'player_url': player_url})
        context = ytcfg.get('INNERTUBE_CONTEXT') or {
            'client': {'clientName': 'WEB', 'clientVersion': '2.20240310.01.00', 'hl': 'en', 'gl': 'US'}
        }
        responses = [player_response] if player_response else []
        if api_key:
            api_responses = self._call_player_api(video_id, api_key, context, watch_url, visitor_data, sts)
            if not isinstance(api_responses, list):
                api_responses = [api_responses] if api_responses else []
            responses.extend([x for x in api_responses if x])
            debug_log('player api result', {'responses': len(api_responses), 'has_streaming': [bool((x or {}).get('streamingData')) for x in api_responses]})
        player_response = next((x for x in responses if (x.get('playabilityStatus') or {}).get('status') == 'OK'), player_response)
        status = (player_response.get('playabilityStatus') or {}).get('status')
        streaming = player_response.get('streamingData') or {}
        if status and status not in ('OK', 'LIVE_STREAM_OFFLINE') and not streaming:
            reason = (player_response.get('playabilityStatus') or {}).get('reason') or status
            raise Exception(f'YouTube 不可播放: {reason}')
        details = player_response.get('videoDetails') or {}
        raw_formats = []
        seen_raw = set()
        source_counts = []
        for response in responses:
            response_streaming = (response or {}).get('streamingData') or {}
            source_raw = (response_streaming.get('formats') or []) + (response_streaming.get('adaptiveFormats') or [])
            source_counts.append({'formats': len(response_streaming.get('formats') or []), 'adaptive': len(response_streaming.get('adaptiveFormats') or [])})
            for raw in source_raw:
                key = (raw.get('itag'), raw.get('url') or raw.get('signatureCipher') or raw.get('cipher') or raw.get('mimeType'))
                if key not in seen_raw:
                    seen_raw.add(key)
                    raw = raw.copy()
                    raw['_client_name'] = (response or {}).get('_client_name')
                    raw['_client_ua'] = (response or {}).get('_client_ua')
                    raw_formats.append(raw)
        debug_log('raw formats', {'sources': source_counts, 'total': len(raw_formats), 'sample_keys': sorted(list(raw_formats[0].keys())) if raw_formats else []})
        formats = []
        cipher_count = 0
        for raw in raw_formats:
            if raw.get('signatureCipher') or raw.get('cipher'):
                cipher_count += 1
            item = self._normalize_format(raw, player_url)
            if item and item.get('url'):
                formats.append(item)
        debug_log('normalized formats', {'count': len(formats), 'cipher_count': cipher_count, 'progressive': len([x for x in formats if x.get('vcodec') != 'none' and x.get('acodec') != 'none'])})
        if not formats:
            raise Exception('未获取到可用播放地址')
        data = {
            'id': video_id,
            'title': details.get('title') or video_id,
            'duration': int(details.get('lengthSeconds') or 0),
            'formats': formats,
        }
        self.extract_cache[video_id] = {'data': data, 'expires': time.time() + self.extract_cache_ttl}
        debug_log('extract complete', {'video_id': video_id, 'cost_ms': int((time.time() - extract_started) * 1000), 'formats': len(formats)})
        return data

    @staticmethod
    def extract_video_id(text):
        text = str(text or '').strip()
        for pattern in [
            r'(?:v=|/v/|/embed/|/shorts/|youtu\.be/)([0-9A-Za-z_-]{11})',
            r'^([0-9A-Za-z_-]{11})$',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        raise Exception('无法识别 YouTube 视频 ID')

    def _client_name_id(self, client_name):
        return {
            'WEB': 1,
            'MWEB': 2,
            'ANDROID': 3,
            'IOS': 5,
            'TVHTML5': 7,
            'ANDROID_VR': 28,
            'WEB_EMBEDDED_PLAYER': 56,
            'WEB_REMIX': 67,
        }.get(client_name, 1)

    def _extract_visitor_data(self, ytcfg, player_response):
        return (
            self.config.get('visitor_data')
            or ytcfg.get('VISITOR_DATA')
            or (((ytcfg.get('INNERTUBE_CONTEXT') or {}).get('client') or {}).get('visitorData'))
            or ((player_response.get('responseContext') or {}).get('visitorData'))
        )

    def _extract_signature_timestamp(self, video_id, player_url, ytcfg=None):
        try:
            code = self._get_player_code(player_url)
            sts = self._search(r'(?:signatureTimestamp|sts)\s*:\s*(\d{5})', code)
            return int(sts) if sts else None
        except Exception as e:
            debug_log('sts extract error', repr(e))
            return None

    def _get_po_token(self, client_name, context='gvs'):
        tokens = self.config.get('po_token') or self.config.get('po_tokens') or {}
        if isinstance(tokens, str):
            return tokens
        if isinstance(tokens, dict):
            return tokens.get(f'{client_name}.{context}') or tokens.get(client_name) or tokens.get(context)
        return None

    def choose_playable(self, formats, quality=None):
        all_videos = [x for x in formats if x.get('vcodec') != 'none' and x.get('acodec') == 'none']
        candidates = all_videos[:]
        if quality == '4k':
            candidates = [x for x in candidates if int(x.get('height') or 0) >= 2160]
        elif quality == '2k':
            candidates = [x for x in candidates if 1440 <= int(x.get('height') or 0) < 2160]
        elif quality == '1080p':
            candidates = [x for x in candidates if 1000 <= int(x.get('height') or 0) < 1440]
        elif quality == 'best':
            safe_candidates = [x for x in candidates if not self._is_risky_best_video(x)]
            if safe_candidates:
                candidates = safe_candidates
        else:
            candidates = [x for x in candidates if int(x.get('height') or 0) >= 1080]
        if not candidates and quality == 'best':
            candidates = all_videos
        if not candidates:
            return None
        # 画质优先，编码顺序 VP9/HDR > H264 > AV1。保留 VP9 Profile 2 HDR，
        # 只把 AV1 放到最后，避免默认选到 itag 701/702 的超大 AV1 分段。
        candidates.sort(key=lambda x: (
            self._video_codec_priority(x),
            int(x.get('height') or 0),
            int(x.get('bitrate') or 0)
        ), reverse=True)
        selected = candidates[0]
        debug_log('video selected fast', {
            'quality': quality,
            'itag': selected.get('itag'),
            'height': selected.get('height'),
            'mime': selected.get('mimeType'),
            'codec_priority': self._video_codec_priority(selected),
            'candidates': len(candidates),
            'probe_skipped': True,
        })
        return selected

    def _video_codec_priority(self, item):
        mime = (item.get('mimeType') or '').lower()
        codecs = (item.get('codecs') or '').lower()
        if 'vp9.2' in mime or 'vp09.02' in codecs:
            return 4
        if 'vp9' in mime or 'vp09' in codecs:
            return 3
        if 'avc' in codecs or 'h264' in codecs:
            return 2
        if 'av01' in codecs:
            return 1
        return 0

    def _is_risky_best_video(self, item):
        codecs = (item.get('codecs') or '').lower()
        return 'av01' in codecs

    def choose_video_tracks(self, formats, quality=None):
        videos = [x for x in formats if x.get('vcodec') != 'none' and x.get('acodec') == 'none']
        cap = 2160 if quality in ('best', '4k') else 1440 if quality == '2k' else 1080
        videos = [x for x in videos if int(x.get('height') or 0) <= cap] or videos
        vp9 = [x for x in videos if self._video_codec_priority(x) >= 3]
        if vp9:
            videos = vp9
        sdr = [x for x in videos if not self._is_hdr_video(x)]
        hdr = [x for x in videos if self._is_hdr_video(x)]
        sort_key = lambda x: (int(x.get('height') or 0), int(x.get('bitrate') or 0))
        sdr.sort(key=sort_key, reverse=True)
        hdr.sort(key=sort_key, reverse=True)
        tracks = []
        if sdr:
            item = sdr[0].copy()
            item['track_name'] = 'SDR'
            item['is_hdr'] = False
            tracks.append(item)
        if hdr:
            item = hdr[0].copy()
            item['track_name'] = 'HDR'
            item['is_hdr'] = True
            tracks.append(item)
        if not tracks:
            item = self.choose_playable(formats, quality)
            if item:
                item = item.copy()
                item['track_name'] = 'HDR' if self._is_hdr_video(item) else 'SDR'
                item['is_hdr'] = self._is_hdr_video(item)
                tracks.append(item)
        debug_log('video tracks selected', [{'name': x.get('track_name'), 'itag': x.get('itag'), 'height': x.get('height'), 'codecs': x.get('codecs')} for x in tracks])
        return tracks

    def _is_hdr_video(self, item):
        mime = (item.get('mimeType') or '').lower()
        codecs = (item.get('codecs') or '').lower()
        color = item.get('colorInfo') or {}
        return 'vp9.2' in mime or 'vp09.02' in codecs or bool(color.get('hdrMetadataInfo'))

    def choose_audio(self, formats):
        candidates = [x for x in formats if x.get('acodec') != 'none' and x.get('vcodec') == 'none']
        if not candidates:
            return None
        candidates.sort(key=lambda x: (1 if x.get('ext') == 'mp4' else 0, int(x.get('bitrate') or 0)), reverse=True)
        selected = candidates[0]
        debug_log('audio selected fast', {
            'itag': selected.get('itag'),
            'mime': selected.get('mimeType'),
            'bitrate': selected.get('bitrate'),
            'probe_skipped': True,
        })
        return selected

    def _probe_format(self, item):
        try:
            headers = self.headers.copy()
            headers.update(item.get('headers') or {})
            headers['Range'] = 'bytes=0-1'
            r = self.session.get(item.get('url'), headers=headers, stream=True, timeout=10)
            if r.url and r.url != item.get('url'):
                item['url'] = r.url
                item['redirected'] = True
                debug_log('probe redirected url', self._url_summary(r.url))
            status_code = r.status_code
            r.close()
            return status_code in (200, 206), status_code
        except Exception as e:
            return False, repr(e)

    def choose_best_video_audio(self, formats):
        videos = [x for x in formats if x.get('vcodec') != 'none' and x.get('acodec') == 'none']
        audios = [x for x in formats if x.get('acodec') != 'none' and x.get('vcodec') == 'none']
        videos.sort(key=lambda x: (int(x.get('height') or 0), int(x.get('bitrate') or 0)), reverse=True)
        audios.sort(key=lambda x: int(x.get('bitrate') or 0), reverse=True)
        return (videos[0] if videos else None), (audios[0] if audios else None)

    def _url_summary(self, media_url):
        parsed = urlparse(media_url or '')
        query = parse_qs(parsed.query)
        keys = ['itag', 'mime', 'c', 'expire', 'ip', 'mip', 'source', 'requiressl', 'gir', 'clen', 'dur', 'n', 'pot', 'sig', 'lsig', 'cms_redirect']
        return {
            'host': parsed.netloc,
            'path': parsed.path,
            'len': len(media_url or ''),
            'params': {k: bool(query.get(k)) if k in ('pot', 'sig', 'lsig', 'cms_redirect') else (query.get(k, [''])[0][:80]) for k in keys if k in query}
        }

    def _get(self, url, **kwargs):
        headers = self.headers.copy()
        headers.update(kwargs.pop('headers', {}) or {})
        r = self.session.get(url, headers=headers, timeout=kwargs.pop('timeout', 15), **kwargs)
        r.raise_for_status()
        return r

    def _post_json(self, url, payload, headers=None):
        h = self.headers.copy()
        h.update({'Content-Type': 'application/json', 'Origin': 'https://www.youtube.com'})
        if headers:
            h.update({k: v for k, v in headers.items() if v})
        r = self.session.post(url, json=payload, headers=h, timeout=15)
        r.raise_for_status()
        return r.json()

    def _call_player_api(self, video_id, api_key, context, referer, visitor_data=None, sts=None):
        clients = [
            {'client': {'clientName': 'ANDROID_VR', 'clientVersion': '1.65.10', 'deviceMake': 'Oculus', 'deviceModel': 'Quest 3', 'androidSdkVersion': 32, 'userAgent': 'com.google.android.apps.youtube.vr.oculus/1.65.10 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip', 'osName': 'Android', 'osVersion': '12L', 'hl': 'en', 'gl': 'US'}},
            {'client': {'clientName': 'ANDROID', 'clientVersion': '21.02.35', 'androidSdkVersion': 30, 'userAgent': 'com.google.android.youtube/21.02.35 (Linux; U; Android 11) gzip', 'osName': 'Android', 'osVersion': '11', 'hl': 'en', 'gl': 'US'}},
            {'client': {'clientName': 'IOS', 'clientVersion': '21.02.3', 'deviceMake': 'Apple', 'deviceModel': 'iPhone16,2', 'userAgent': 'com.google.ios.youtube/21.02.3 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)', 'osName': 'iPhone', 'osVersion': '18.3.2.22D82', 'hl': 'en', 'gl': 'US'}},
            context,
            {'client': {'clientName': 'MWEB', 'clientVersion': '2.20260115.01.00', 'userAgent': 'Mozilla/5.0 (iPad; CPU OS 16_7_10 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1,gzip(gfe)', 'hl': 'en', 'gl': 'US'}},
        ]
        results = []
        fallback = None
        for ctx in clients:
            client_name = (ctx.get('client') or {}).get('clientName')
            try:
                url = f'https://www.youtube.com/youtubei/v1/player?key={api_key}&prettyPrint=false'
                payload = {
                    'context': ctx,
                    'videoId': video_id,
                    'playbackContext': {'contentPlaybackContext': {'html5Preference': 'HTML5_PREF_WANTS', **({'signatureTimestamp': sts} if sts else {})}},
                    'contentCheckOk': True,
                    'racyCheckOk': True,
                }
                client = ctx.get('client') or {}
                headers = {
                    'Referer': referer,
                    'X-YouTube-Client-Name': str(self._client_name_id(client.get('clientName'))),
                    'X-YouTube-Client-Version': client.get('clientVersion') or '',
                }
                if visitor_data:
                    headers['X-Goog-Visitor-Id'] = visitor_data
                client_ua = client.get('userAgent')
                if client_ua:
                    headers['User-Agent'] = client_ua
                data = self._post_json(url, payload, headers=headers)
                status = (data.get('playabilityStatus') or {}).get('status')
                streaming = data.get('streamingData') or {}
                formats = streaming.get('formats') or []
                adaptive = streaming.get('adaptiveFormats') or []
                direct_video = [x for x in adaptive if (x.get('url') or x.get('signatureCipher') or x.get('cipher')) and str(x.get('mimeType') or '').startswith('video/')]
                direct_any = [x for x in formats + adaptive if x.get('url') or x.get('signatureCipher') or x.get('cipher')]
                has_streaming = bool(streaming)
                debug_log('player api client', {'client': client_name, 'status': status, 'has_streaming': has_streaming, 'formats': len(formats), 'adaptive': len(adaptive), 'direct_any': len(direct_any), 'direct_video': len(direct_video)})
                if has_streaming:
                    data['_client_name'] = client_name
                    data['_client_ua'] = client_ua
                    results.append(data)
                    # VR 明文格式最完整，成功后立即返回，避免再串行请求 4 个客户端。
                    if client_name == 'ANDROID_VR' and direct_video:
                        debug_log('player api fast return', {'client': client_name, 'direct_video': len(direct_video)})
                        return results
                if has_streaming and fallback is None:
                    fallback = data
                elif fallback is None:
                    fallback = data
            except Exception as e:
                debug_log('player api client error', {'client': client_name, 'error': repr(e)})
                continue
        return results or ([fallback] if fallback else [])

    def _normalize_format(self, fmt, player_url):
        media_url = fmt.get('url')
        if not media_url:
            cipher = fmt.get('signatureCipher') or fmt.get('cipher')
            if cipher:
                media_url = self._decrypt_signature_cipher(cipher, player_url)
        if not media_url:
            return None
        media_url = self._decrypt_nsig(media_url, player_url)
        client_name = fmt.get('_client_name')
        po_token = self._get_po_token(client_name, 'gvs') if client_name else None
        if po_token:
            sep = '&' if '?' in media_url else '?'
            media_url = f'{media_url}{sep}pot={quote(po_token)}'
        mime = fmt.get('mimeType') or ''
        ext = 'mp4' if 'mp4' in mime else 'webm' if 'webm' in mime else 'unknown'
        codecs = self._search(r'codecs="([^"]+)"', mime) or ''
        has_audio = mime.startswith('audio/') or any(x in codecs for x in ('mp4a', 'opus', 'vorbis'))
        has_video = mime.startswith('video/') or any(x in codecs for x in ('avc', 'vp9', 'av01', 'h264'))
        headers = (fmt.get('http_headers') or {}).copy()
        if fmt.get('_client_ua'):
            headers['User-Agent'] = fmt.get('_client_ua')
        return {
            'itag': fmt.get('itag'),
            'url': media_url,
            'mimeType': mime,
            'client': fmt.get('_client_name'),
            'ext': ext,
            'width': fmt.get('width') or 0,
            'height': fmt.get('height') or 0,
            'fps': fmt.get('fps') or 0,
            'bitrate': fmt.get('bitrate') or fmt.get('averageBitrate') or 0,
            'contentLength': fmt.get('contentLength'),
            'initRange': fmt.get('initRange') or {},
            'indexRange': fmt.get('indexRange') or {},
            'codecs': codecs,
            'quality': fmt.get('qualityLabel') or fmt.get('quality'),
            'colorInfo': fmt.get('colorInfo') or {},
            'vcodec': codecs if has_video else 'none',
            'acodec': codecs if has_audio else 'none',
            'headers': headers,
        }

    def _decrypt_signature_cipher(self, cipher, player_url):
        data = parse_qs(cipher)
        media_url = unquote(data.get('url', [''])[0])
        sig = unquote(data.get('s', [''])[0])
        sp = data.get('sp', ['sig'])[0]
        if not media_url:
            return ''
        if sig:
            decoded = self._decrypt_sig(sig, player_url)
            debug_log('signature cipher', {'sp': sp, 'sig_len': len(sig), 'decoded_changed': decoded != sig, 'has_player': bool(player_url)})
            sep = '&' if '?' in media_url else '?'
            media_url = f'{media_url}{sep}{sp}={quote(decoded)}'
        return media_url

    def _decrypt_sig(self, sig, player_url):
        cache_key = player_url or ''
        if cache_key in self.sig_plan_cache:
            plan = self.sig_plan_cache.get(cache_key)
            debug_log('sig plan cache', {'has_plan': bool(plan), 'plan': plan[:8] if plan else None})
        else:
            code = self._get_player_code(player_url)
            plan = self._extract_sig_plan(code)
            self.sig_plan_cache[cache_key] = plan
            debug_log('sig plan', {'code_len': len(code), 'has_plan': bool(plan), 'plan': plan[:8] if plan else None})
        if not plan:
            return sig
        arr = list(sig)
        for op, arg in plan:
            if op == 'reverse':
                arr.reverse()
            elif op in ('slice', 'splice'):
                arr = arr[int(arg):]
            elif op == 'swap' and arr:
                j = int(arg) % len(arr)
                arr[0], arr[j] = arr[j], arr[0]
        return ''.join(arr)

    def _decrypt_nsig(self, media_url, player_url):
        try:
            parsed = urlparse(media_url)
            query = parse_qs(parsed.query)
            n_value = query.get('n', [None])[0]
            if not n_value:
                return media_url
            path_match = re.search(r'/n/([^/]+)', parsed.path)
            if path_match and path_match.group(1) != n_value:
                new_path = parsed.path.replace(f"/n/{path_match.group(1)}", f"/n/{n_value}", 1)
                fixed = urlunparse(parsed._replace(path=new_path))
                debug_log('n path synced', {'old': path_match.group(1), 'new_len': len(n_value), 'changed': fixed != media_url})
                return fixed
            debug_log('n present', {'n_len': len(n_value), 'has_path_n': bool(path_match)})
            return media_url
        except Exception as e:
            debug_log('n sync error', repr(e))
            return media_url

    def _get_player_code(self, player_url):
        if not player_url:
            return ''
        if player_url in self.player_cache:
            return self.player_cache[player_url]
        if player_url.startswith('//'):
            player_url = 'https:' + player_url
        elif player_url.startswith('/'):
            player_url = 'https://www.youtube.com' + player_url
        try:
            code = self._get(player_url).text
        except Exception:
            code = ''
        self.player_cache[player_url] = code
        return code

    def _extract_sig_plan(self, code):
        if not code:
            return None
        name = None
        for pattern in [
            r'\.sig\|\|([a-zA-Z0-9_$]+)\(',
            r'"signature",\s*([a-zA-Z0-9_$]+)\(',
            r'([a-zA-Z0-9_$]+)=function\(a\)\{a=a\.split\(""\);',
        ]:
            m = re.search(pattern, code)
            if m:
                name = m.group(1)
                break
        if not name:
            return None
        body = self._extract_js_function_body(code, name)
        if not body:
            return None
        helper = self._search(r'([a-zA-Z0-9_$]+)\.[a-zA-Z0-9_$]+\(a,\d+\)', body)
        helper_map = self._extract_helper_object(code, helper) if helper else {}
        plan = []
        for part in body.split(';'):
            if 'reverse()' in part:
                plan.append(('reverse', 0))
                continue
            m = re.search(r'\.slice\((\d+)\)', part)
            if m:
                plan.append(('slice', int(m.group(1))))
                continue
            m = re.search(r'\.splice\(0,(\d+)\)', part)
            if m:
                plan.append(('splice', int(m.group(1))))
                continue
            m = re.search(r'([a-zA-Z0-9_$]+)\.([a-zA-Z0-9_$]+)\(a,(\d+)\)', part)
            if m and m.group(1) == helper:
                op = helper_map.get(m.group(2))
                if op:
                    plan.append((op, int(m.group(3))))
        return plan or None

    def _extract_helper_object(self, code, name):
        if not name:
            return {}
        m = re.search(r'var\s+' + re.escape(name) + r'=\{(.+?)\};', code, re.S) or re.search(re.escape(name) + r'=\{(.+?)\};', code, re.S)
        if not m:
            return {}
        result = {}
        for method, body in re.findall(r'([a-zA-Z0-9_$]+):function\([a-z,]+\)\{(.*?)\}', m.group(1)):
            if '.reverse(' in body:
                result[method] = 'reverse'
            elif '.splice(' in body:
                result[method] = 'splice'
            elif '.slice(' in body:
                result[method] = 'slice'
            elif 'a[0]' in body and 'length' in body:
                result[method] = 'swap'
        return result

    def _extract_n_function(self, code):
        if not code:
            return None
        name = None
        for pattern in [
            r'\.get\("n"\)\)&&\(b=([a-zA-Z0-9_$]+)(?:\[(\d+)\])?\(b\)',
            r'\.get\("n"\)\)&&\(b=([a-zA-Z0-9_$]+)\(b\)',
            r'([a-zA-Z0-9_$]+)=function\(a\)\{var b=a\.split\(""\)',
            r'function\s+([a-zA-Z0-9_$]+)\(a\)\{var b=a\.split\(""\)',
            r'([a-zA-Z0-9_$]+)=function\(a\)\{a=a\.split\(""\)',
        ]:
            m = re.search(pattern, code)
            if m:
                name = m.group(1)
                break
        if not name:
            return None
        body = self._extract_js_function_body(code, name)
        debug_log('n function', {'name': name, 'body_len': len(body)})
        if not body:
            return None
        def transform(value):
            arr = list(value)
            for part in body.split(';'):
                if 'reverse()' in part:
                    arr.reverse()
                m = re.search(r'\.slice\((\d+)\)', part)
                if m:
                    arr = arr[int(m.group(1)):]
                m = re.search(r'\.splice\(0,(\d+)\)', part)
                if m:
                    arr = arr[int(m.group(1)):]
            return ''.join(arr) or value
        return transform

    def _extract_js_function_body(self, code, name):
        starts = []
        for pattern in [
            r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{',
            re.escape(name) + r'\s*=\s*function\s*\([^)]*\)\s*\{',
            r'var\s+' + re.escape(name) + r'\s*=\s*function\s*\([^)]*\)\s*\{',
        ]:
            m = re.search(pattern, code)
            if m:
                starts.append(m.end() - 1)
        if not starts:
            return ''
        start = starts[0]
        depth = 0
        in_str = None
        escape = False
        for i in range(start, len(code)):
            ch = code[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if in_str:
                if ch == in_str:
                    in_str = None
                continue
            if ch in ('"', "'", '`'):
                in_str = ch
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return code[start + 1:i]
        return ''

    def _extract_ytcfg(self, text):
        m = re.search(r'ytcfg\.set\s*\(\s*({.+?})\s*\)\s*;', text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except Exception:
            return None

    def _extract_initial_player_response(self, text):
        return self._extract_json_after(text, 'ytInitialPlayerResponse')

    def _extract_json_after(self, text, marker):
        pos = text.find(marker)
        if pos < 0:
            return None
        start = text.find('{', pos)
        if start < 0:
            return None
        depth = 0
        in_str = None
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if in_str:
                if ch == in_str:
                    in_str = None
                continue
            if ch == '"':
                in_str = ch
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:
                        return None
        return None

    def _extract_player_url(self, text):
        for pattern in [
            r'"jsUrl":"([^"]+)"',
            r'"PLAYER_JS_URL":"([^"]+)"',
            r'(/s/player/[^"\\]+/base\.js)',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1).replace('\\/', '/')
        return ''

    @staticmethod
    def _search(pattern, text, default=None):
        m = re.search(pattern, text or '', re.S)
        return m.group(1) if m else default

class Spider(Spider):
    def getName(self):
        return 'YouTube视频'

    def init(self, extend):
        try:
            self.extendDict = json.loads(extend) if extend else {}
        except Exception:
            self.extendDict = {}
        self.session = requests.Session()
        self.proxy_str = None
        proxy_val = self.extendDict.get('proxy')
        if proxy_val:
            if isinstance(proxy_val, dict):
                self.session.proxies = proxy_val
                self.proxy_str = (proxy_val.get('http') or proxy_val.get('https') or '').replace('http://', '').replace('https://', '')
            elif isinstance(proxy_val, str):
                self.proxy_str = proxy_val.replace('http://', '').replace('https://', '')
                proxy_url = f'http://{self.proxy_str}'
                self.session.proxies = {'http': proxy_url, 'https': proxy_url}
        self.header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://www.youtube.com/'
        }
        self.session.headers.update(self.header)
        self.yt = YouTubeLite(self.session, self.header, self.extendDict)
        self.config = {}
        self.search_page_cache = {}

    def homeContent(self, filter):
        result = {'class': YOUTUBE_CLASSES}
        if filter:
            result['filters'] = CATEGORY_FILTERS
        return result

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, cid, page, filter, ext):
        page = int(page)
        filters = ext if isinstance(ext, dict) else {}
        query = self._build_category_keyword(cid, filters)
        videos, has_more = self._search_youtube_page(query, page)
        return {'list': videos, 'page': page, 'pagecount': page + 1 if has_more else page, 'limit': len(videos), 'total': len(videos)}

    def searchContent(self, key, quick, pg=1):
        page = int(pg)
        videos, has_more = self._search_youtube_page(key, page)
        return {'list': videos, 'page': page, 'pagecount': page + 1 if has_more else page, 'limit': len(videos), 'total': len(videos)}

    def detailContent(self, did):
        video_id = did[0]
        title = self._get_video_title(video_id)
        safe_title = self._safe_title(title)
        play_sources = []
        play_urls = []
        try:
            data = self.yt.extract(video_id)
            tracks = self.yt.choose_video_tracks(data.get('formats') or [], 'best')
            for track in tracks:
                height = int(track.get('height') or 0)
                kind = track.get('track_name') or ('HDR' if track.get('is_hdr') else 'SDR')
                name = f'{height}p {kind}' if height else kind
                quality = 'hdr' if kind == 'HDR' else 'best'
                play_sources.append(name)
                play_urls.append(f'{safe_title} {name}${video_id}@{quality}')
            debug_log('detail dynamic sources', {'video_id': video_id, 'sources': play_sources})
        except Exception as e:
            debug_log('detail dynamic sources error', {'video_id': video_id, 'error': repr(e)})
        if not play_sources:
            play_sources = ['SDR', 'HDR']
            play_urls = [
                f'{safe_title} SDR${video_id}@best',
                f'{safe_title} HDR${video_id}@hdr',
            ]
        vod = {
            'vod_id': video_id,
            'vod_name': title,
            'vod_pic': f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg',
            'vod_play_from': '$$$'.join(play_sources),
            'vod_play_url': '$$$'.join(play_urls)
        }
        return {'list': [vod]}

    def _build_direct_play_url(self, media_url, headers, ext):
        header_query = urlencode({k: v for k, v in (headers or {}).items() if v})
        return f'{media_url}|{header_query}' if header_query else media_url

    def playerContent(self, flag, pid, vipFlags):
        raw_pid = pid.split('$')[-1]
        if '@' in raw_pid:
            video_id, quality = raw_pid.rsplit('@', 1)
        else:
            video_id, quality = raw_pid, '1080p'
        if quality not in ('best', 'hdr', '4k', '2k', '1080p'):
            quality = 'best'
        debug_log('playerContent', {'flag': flag, 'pid': pid, 'video_id': video_id, 'quality': quality})
        try:
            data = self.yt.extract(video_id)
            all_tracks = self.yt.choose_video_tracks(data['formats'], 'best')
            wanted_name = 'HDR' if quality == 'hdr' else 'SDR'
            video_tracks = [x for x in all_tracks if x.get('track_name') == wanted_name]
            if not video_tracks and all_tracks:
                video_tracks = [all_tracks[0]]
            if video_tracks:
                audio = self.yt.choose_audio(data['formats'])
                debug_log('selected track', {'requested': wanted_name, 'track': {'name': video_tracks[0].get('track_name'), 'itag': video_tracks[0].get('itag'), 'height': video_tracks[0].get('height'), 'mime': video_tracks[0].get('mimeType')}, 'audio': audio.get('itag') if audio else None})
                if audio:
                    cache_key = f'yt_{video_id}_{quality}'
                    self.setCache(cache_key, {
                        'video_tracks': video_tracks,
                        'video_url': video_tracks[0]['url'],
                        'audio_url': audio['url'],
                        'video_item': video_tracks[0],
                        'audio_item': audio,
                        'duration': data.get('duration') or 0,
                        'expires': time.time() + 300,
                    })
                    return {'parse': 0, 'jx': 0, 'url': f'http://127.0.0.1:9978/proxy?do=py&type=mpd&vid={video_id}&quality={quality}', 'format': 'application/dash+xml'}
                playable = video_tracks[0]
                headers = self.header.copy()
                headers.update(playable.get('headers') or {})
                return {'parse': 0, 'jx': 0, 'url': playable['url'], 'header': headers}
            raise Exception(f'没有可直接播放的 {quality} 视频流格式')
        except Exception as e:
            debug_log('playerContent error', repr(e))
            print(f'[YouTubeLite] 解析失败: {e}')
            res = {'parse': 1, 'url': f'https://www.youtube.com/embed/{video_id}?autoplay=1', 'header': json.dumps(self.header)}
            if self.proxy_str:
                res['proxy'] = self.proxy_str
            return res

    def localProxy(self, params):
        if params.get('do') != 'py':
            return None
        if params.get('type') == 'mpd':
            return self._proxy_mpd(params)
        if params.get('type') == 'media':
            return self._proxy_media(params)
        if params.get('type') == 'single':
            return self._proxy_single(params)
        return None

    def _proxy_single(self, params):
        vid = params.get('vid')
        debug_log('proxy single request', {'vid': vid, 'range': params.get('range'), 'keys': sorted(list(params.keys()))[:20]})
        data = self.getCache(f'yt_single_{vid}') if vid else None
        if not data:
            return [404, 'text/plain', '播放缓存已过期或不存在']
        target_url = data.get('url')
        if not target_url:
            return [404, 'text/plain', '播放地址不存在']
        headers = (data.get('headers') or self.header).copy()
        range_header = params.get('range') or params.get('Range')
        if range_header:
            headers['Range'] = range_header
        try:
            r = self.session.get(target_url, headers=headers, stream=True, timeout=30)
            debug_log('proxy single response', {'status': r.status_code, 'content_type': r.headers.get('content-type'), 'content_length': r.headers.get('content-length'), 'content_range': r.headers.get('content-range')})
            content_type = r.headers.get('content-type', 'video/mp4')
            resp_headers = {
                'Content-Type': content_type,
                'Accept-Ranges': 'bytes',
                'Cache-Control': 'no-cache',
            }
            if r.headers.get('content-range'):
                resp_headers['Content-Range'] = r.headers.get('content-range')
            if r.headers.get('content-length'):
                resp_headers['Content-Length'] = r.headers.get('content-length')
            return [r.status_code, content_type, r.content, resp_headers]
        except Exception as e:
            debug_log('proxy single error', repr(e))
            return [500, 'text/plain', f'代理播放失败: {str(e)}']

    def _proxy_mpd(self, params):
        vid = params.get('vid')
        quality = params.get('quality') or '1080p'
        data = self.getCache(f'yt_{vid}_{quality}') if vid else None
        if not data:
            return [404, 'text/plain', '视频缓存已过期或不存在']
        audio_url = data.get('audio_url')
        duration = data.get('duration') or 0
        video_tracks = data.get('video_tracks') or [data.get('video_item') or {}]
        audio_item = data.get('audio_item') or {}
        media_base = f'http://127.0.0.1:9978/proxy?do=py&type=media&vid={vid}&quality={quality}'
        direct_segments = str(self.extendDict.get('seg') or 'proxy').lower() == 'direct'
        duration_pt = f"PT{int(duration or 0)}S"
        mpd = f'''<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="{duration_pt}" minBufferTime="PT1.5S" profiles="urn:mpeg:dash:profile:isoff-on-demand:2011">
  <Period id="1" start="PT0S">
'''
        for item in video_tracks:
            init_range = item.get('initRange') or {}
            index_range = item.get('indexRange') or {}
            name = item.get('track_name') or ('HDR' if item.get('is_hdr') else 'SDR')
            base_url = item.get('url') if direct_segments else media_base + f"&track=video&itag={item.get('itag')}"
            mpd += f'''    <AdaptationSet mimeType="{html.escape((item.get('mimeType') or 'video/webm').split(';')[0])}" startWithSAP="1" segmentAlignment="true" scanType="progressive">
      <Representation id="v{item.get('itag', 1)}" bandwidth="{item.get('bitrate', 1000000)}" codecs="{html.escape(item.get('codecs') or '')}" height="{item.get('height', 0)}" width="{item.get('width', 0)}">
        <BaseURL>{html.escape(base_url)}</BaseURL>
        <SegmentBase indexRange="{index_range.get('start', '0')}-{index_range.get('end', '0')}"><Initialization range="{init_range.get('start', '0')}-{init_range.get('end', '0')}"/></SegmentBase>
      </Representation>
    </AdaptationSet>
'''
        if audio_url:
            audio_init = audio_item.get('initRange') or {}
            audio_index = audio_item.get('indexRange') or {}
            audio_base = audio_url if direct_segments else media_base + '&track=audio'
            mpd += f'''    <AdaptationSet mimeType="{html.escape((audio_item.get('mimeType') or 'audio/mp4').split(';')[0])}" startWithSAP="1" segmentAlignment="true" lang="und">
      <Representation id="audio" bandwidth="{audio_item.get('bitrate', 128000)}" codecs="{html.escape(audio_item.get('codecs') or '')}" audioSamplingRate="44100">
        <BaseURL>{html.escape(audio_base)}</BaseURL>
        <SegmentBase indexRange="{audio_index.get('start', '0')}-{audio_index.get('end', '0')}"><Initialization range="{audio_init.get('start', '0')}-{audio_init.get('end', '0')}"/></SegmentBase>
      </Representation>
    </AdaptationSet>
'''
        mpd += '  </Period>\n</MPD>'
        debug_log('proxy mpd tracks', {'vid': vid, 'quality': quality, 'tracks': [{'name': x.get('track_name'), 'itag': x.get('itag')} for x in video_tracks], 'audio': audio_item.get('itag'), 'direct': direct_segments, 'duration': duration_pt})
        return [200, 'application/dash+xml', mpd]

    def _proxy_media(self, params):
        vid = params.get('vid')
        quality = params.get('quality') or '1080p'
        track = params.get('track')
        data = self.getCache(f'yt_{vid}_{quality}') if vid else None
        if not data or track not in ('video', 'audio'):
            return [404, 'text/plain', '媒体不存在']
        if track == 'video':
            wanted_itag = str(params.get('itag') or '')
            tracks = data.get('video_tracks') or [data.get('video_item') or {}]
            media_item = next((x for x in tracks if str(x.get('itag')) == wanted_itag), tracks[0] if tracks else {})
            target_url = media_item.get('url')
        else:
            media_item = data.get('audio_item') or {}
            target_url = data.get('audio_url') or media_item.get('url')
        if not target_url:
            return [404, 'text/plain', f'{track} 流不存在']
        headers = self.header.copy()
        headers.update((media_item or {}).get('headers') or {})
        range_header = params.get('range') or params.get('Range')
        if range_header:
            headers['Range'] = range_header
        try:
            r = self.session.get(target_url, headers=headers, stream=True, timeout=30)
            content_type = r.headers.get('content-type', 'application/octet-stream')
            debug_log('proxy media response', {'track': track, 'itag': media_item.get('itag'), 'track_name': media_item.get('track_name'), 'status': r.status_code, 'range': range_header, 'content_type': content_type, 'content_length': r.headers.get('content-length'), 'content_range': r.headers.get('content-range')})
            resp_headers = {'Content-Type': content_type, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-cache'}
            if r.headers.get('content-range'):
                resp_headers['Content-Range'] = r.headers.get('content-range')
            if r.headers.get('content-length'):
                resp_headers['Content-Length'] = r.headers.get('content-length')
            return [r.status_code, content_type, r.content, resp_headers]
        except Exception as e:
            return [500, 'text/plain', f'代理媒体失败: {str(e)}']

    def _normalize_category_id(self, cid):
        raw = str(cid or '').strip()
        return CATEGORY_ALIASES.get(raw, raw)

    def _normalize_filter_term(self, value):
        if isinstance(value, (list, tuple)):
            return ' '.join([self._normalize_filter_term(item) for item in value if item])
        if isinstance(value, dict):
            return ' '.join([self._normalize_filter_term(item) for item in value.values() if item])
        return re.sub(r'\s+', ' ', str(value or '')).strip()[:180]

    def _build_category_keyword(self, cid, filters=None):
        category_id = self._normalize_category_id(cid)
        terms = []
        base = CATEGORY_QUERY.get(category_id) or CATEGORY_QUERY.get(str(cid or '').strip()) or category_id or str(cid or '').strip()
        if base:
            terms.append(base)
        if isinstance(filters, dict):
            for value in filters.values():
                term = self._normalize_filter_term(value)
                if term:
                    terms.append(term)
        seen = set()
        output = []
        for term in terms:
            term = term.strip()
            if term and term not in seen:
                seen.add(term)
                output.append(term)
        return ' '.join(output)

    def _search_cache_key(self, key):
        return re.sub(r'\s+', ' ', str(key or '')).strip().lower()

    def _search_youtube(self, key):
        videos, _ = self._search_youtube_page(key, 1)
        return videos

    def _search_youtube_page(self, key, page=1):
        page = max(1, int(page or 1))
        cache_key = self._search_cache_key(key)
        session = self.search_page_cache.get(cache_key)
        if page == 1 or not session:
            session = self._fetch_search_first_page(key)
            self.search_page_cache[cache_key] = session
        while len(session.get('pages', [])) < page and session.get('next'):
            data = self._fetch_search_continuation(session)
            videos = self._extract_videos_from_api(data, 30)
            session.setdefault('pages', []).append(videos)
            session['next'] = self._extract_continuation_token(data)
        pages = session.get('pages', [])
        videos = pages[page - 1] if len(pages) >= page else []
        has_more = bool(session.get('next')) or len(pages) > page
        return videos, has_more

    def _fetch_search_first_page(self, key):
        search_url = f'https://www.youtube.com/results?search_query={quote(str(key or ""))}'
        r = self.session.get(search_url, timeout=10)
        html_str = r.text
        data = self.yt._extract_json_after(html_str, 'ytInitialData') or {}
        ytcfg = self.yt._extract_ytcfg(html_str) or {}
        api_key = ytcfg.get('INNERTUBE_API_KEY') or self.yt._search(r'"INNERTUBE_API_KEY":"([^"]+)"', html_str)
        context = ytcfg.get('INNERTUBE_CONTEXT') or {'client': {'clientName': 'WEB', 'clientVersion': '2.20240310.01.00', 'hl': 'zh-CN', 'gl': 'US'}}
        client = context.get('client') or {}
        return {
            'key': key,
            'api_key': api_key,
            'context': context,
            'client_name': client.get('clientName') or 'WEB',
            'client_version': client.get('clientVersion') or '2.20240310.01.00',
            'referer': search_url,
            'pages': [self._extract_videos_from_api(data, 30)],
            'next': self._extract_continuation_token(data),
        }

    def _fetch_search_continuation(self, session):
        token = session.get('next')
        api_key = session.get('api_key')
        if not token or not api_key:
            return {}
        url = f'https://www.youtube.com/youtubei/v1/search?key={quote(api_key)}'
        headers = self.header.copy()
        headers.update({
            'Content-Type': 'application/json',
            'Origin': 'https://www.youtube.com',
            'Referer': session.get('referer') or 'https://www.youtube.com/',
            'X-YouTube-Client-Name': str(self.yt._client_name_id(session.get('client_name'))),
            'X-YouTube-Client-Version': session.get('client_version') or '2.20240310.01.00',
        })
        payload = {'context': session.get('context') or {}, 'continuation': token}
        r = self.session.post(url, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()

    def _extract_continuation_token(self, data):
        tokens = []
        def scan(obj):
            if isinstance(obj, dict):
                endpoint = obj.get('continuationEndpoint') or {}
                token = endpoint.get('continuationCommand', {}).get('token')
                if token:
                    tokens.append(token)
                renderer = obj.get('continuationItemRenderer') or {}
                token = renderer.get('continuationEndpoint', {}).get('continuationCommand', {}).get('token')
                if token:
                    tokens.append(token)
                for value in obj.values():
                    scan(value)
            elif isinstance(obj, list):
                for value in obj:
                    scan(value)
        scan(data)
        return tokens[0] if tokens else ''

    def _extract_videos_fixed(self, html_str, limit=30):
        data = None
        match = re.search(r'var ytInitialData = (\{.*?\});', html_str)
        if match:
            try:
                data = json.loads(match.group(1))
            except Exception:
                data = None
        if not data:
            return []
        return self._extract_videos_from_api(data, limit)

    def _extract_videos_from_api(self, data, limit=30):
        videos = []
        seen = set()
        def scan(obj):
            if len(videos) >= limit:
                return
            if isinstance(obj, dict):
                for key in ('videoRenderer', 'compactVideoRenderer', 'gridVideoRenderer', 'reelItemRenderer'):
                    if key in obj:
                        item = self._parse_renderer(obj[key])
                        if item and item['vod_id'] not in seen:
                            seen.add(item['vod_id'])
                            videos.append(item)
                for value in obj.values():
                    scan(value)
            elif isinstance(obj, list):
                for value in obj:
                    scan(value)
        scan(data)
        return videos[:limit]

    def _parse_renderer(self, renderer):
        try:
            vid = renderer.get('videoId')
            if not vid:
                nav = renderer.get('navigationEndpoint') or {}
                vid = (nav.get('watchEndpoint') or {}).get('videoId')
            if not vid:
                return None
            title_obj = renderer.get('title') or renderer.get('headline') or {}
            title = title_obj.get('simpleText') or ''.join([x.get('text', '') for x in title_obj.get('runs', [])]) or 'YouTube Video'
            dur = (renderer.get('lengthText') or {}).get('simpleText') or 'YouTube'
            return {'vod_id': vid, 'vod_name': html.unescape(title), 'vod_pic': f'https://img.youtube.com/vi/{vid}/hqdefault.jpg', 'vod_remarks': dur}
        except Exception:
            return None

    def _get_video_title(self, vid):
        try:
            r = self.session.get(f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json', timeout=5)
            return r.json().get('title') or vid
        except Exception:
            return vid

    def _safe_title(self, title):
        if not title:
            return 'video'
        return re.sub(r'[#$@%&!?*|\\/:<>]', ' ', title)[:60]

    def _seconds_to_iso_duration(self, seconds):
        seconds = float(seconds or 0)
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds - hours * 3600 - minutes * 60
        parts = []
        if hours:
            parts.append(f'{hours}H')
        if minutes:
            parts.append(f'{minutes}M')
        parts.append(f'{secs:.3f}S')
        return 'PT' + ''.join(parts)

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass
