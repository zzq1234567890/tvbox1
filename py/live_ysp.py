# -*- coding: utf-8 -*-
# 极简诊断版 - 仅测试插件能否被加载

import sys
import os

# 强制写日志到多个位置，确保能捕获
LOG_PATHS = [
    '/sdcard/Download/cctv_diag.log',
    '/storage/emulated/0/Download/cctv_diag.log',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cctv_diag.log')
]

def write_log(msg):
    for path in LOG_PATHS:
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(msg + '\n')
        except:
            pass
    print(msg)

write_log('=== 脚本开始执行 ===')

try:
    from base.spider import Spider as BaseSpider
    write_log('成功导入 BaseSpider')
except Exception as e:
    write_log(f'导入失败: {e}')
    class BaseSpider:
        def getProxyUrl(self): return "http://127.0.0.1:9978/proxy?do=py&"
        def init(self, extend): pass
        def getName(self): return "诊断"
        def liveContent(self, url): return ""
        def localProxy(self, params): return []
        def destroy(self): return ""

class Spider(BaseSpider):
    def __init__(self):
        write_log('Spider.__init__ 被调用')
    def getName(self):
        return "诊断插件"
    def init(self, extend):
        write_log(f'init 被调用, extend={extend}')
    def liveContent(self, url):
        write_log('liveContent 开始执行')
        # 返回两个硬编码测试频道
        return '''#EXTM3U
#EXTINF:-1 tvg-id="CCTV1" tvg-name="CCTV1" group-title="测试",CCTV1
http://devimages.apple.com.edgekey.net/streaming/examples/bipbop_4x3/gear3/prog_index.m3u8
#EXTINF:-1 tvg-id="CCTV2" tvg-name="CCTV2" group-title="测试",CCTV2
http://devimages.apple.com.edgekey.net/streaming/examples/bipbop_4x3/gear3/prog_index.m3u8'''
    def localProxy(self, params):
        write_log(f'localProxy 被调用: {params}')
        return [500, "application/vnd.apple.mpegurl", "#EXTM3U\n#EXT-X-ENDLIST"]
    def destroy(self):
        write_log('destroy 被调用')

write_log('脚本加载完成，Spider 类已定义')
