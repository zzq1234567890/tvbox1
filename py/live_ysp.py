# -*- coding: utf-8 -*-
"""
央视频直播代理插件（支持直播+7天回看）
- 完全移除 requests 依赖，使用 urllib + self.fetch
- 与 4GTV.py 同架构，兼容 TVBox 环境
- 支持直播和回看（需 TVBox 传递 playseek 参数）
"""

import sys
import os
import time
import json
import random
import struct
import binascii
import hashlib
import base64
import urllib.request
import urllib.error
import ssl
import traceback
from datetime import datetime
from urllib.parse import urlparse, urljoin, urlencode

# ==================== 日志控制 ====================
DEBUG = os.environ.get('CCTV_DEBUG', '0') == '1'

def log(msg, level='INFO'):
    if DEBUG or level == 'ERROR':
        print(f'[CCTV] {level}: {msg}')

# ==================== 基础 Spider 兼容 ====================
try:
    from base.spider import Spider as BaseSpider
    log("成功导入 BaseSpider")
except ImportError as e:
    log(f"导入 BaseSpider 失败: {e}", 'ERROR')
    class BaseSpider:
        def getProxyUrl(self):
            return "http://127.0.0.1:9978/proxy?do=py&"
        def init(self, extend): pass
        def getName(self): return "CCTV"
        def liveContent(self, url): return ""
        def localProxy(self, params): return []
        def destroy(self): return ""

# ==================== 频道数据 ====================
CHANNELS = {
    'cctv1':     {'name': 'CCTV1',     'cnlid': '2024078201', 'livepid': '600001859', 'defn': 'fhd'},
    'cctv2':     {'name': 'CCTV2',     'cnlid': '2024075401', 'livepid': '600001800', 'defn': 'fhd'},
    'cctv3':     {'name': 'CCTV3',     'cnlid': '2024068501', 'livepid': '600001801', 'defn': 'fhd'},
    'cctv4':     {'name': 'CCTV4',     'cnlid': '2029797101', 'livepid': '600001814', 'defn': 'fhd'},
    'cctv5':     {'name': 'CCTV5',     'cnlid': '2024078401', 'livepid': '600001818', 'defn': 'fhd'},
    'cctv5p':    {'name': 'CCTV5+',    'cnlid': '2024078001', 'livepid': '600001817', 'defn': 'fhd'},
    'cctv6':     {'name': 'CCTV6',     'cnlid': '2013693901', 'livepid': '600108442', 'defn': 'fhd'},
    'cctv7':     {'name': 'CCTV7',     'cnlid': '2024072001', 'livepid': '600004092', 'defn': 'fhd'},
    'cctv8':     {'name': 'CCTV8',     'cnlid': '2029793001', 'livepid': '600001803', 'defn': 'fhd'},
    'cctv9':     {'name': 'CCTV9',     'cnlid': '2024078601', 'livepid': '600004078', 'defn': 'fhd'},
    'cctv10':    {'name': 'CCTV10',    'cnlid': '2024078701', 'livepid': '600001805', 'defn': 'fhd'},
    'cctv11':    {'name': 'CCTV11',    'cnlid': '2027248701', 'livepid': '600001806', 'defn': 'fhd'},
    'cctv12':    {'name': 'CCTV12',    'cnlid': '2027248801', 'livepid': '600001807', 'defn': 'fhd'},
    'cctv13':    {'name': 'CCTV13',    'cnlid': '2029797201', 'livepid': '600001811', 'defn': 'fhd'},
    'cctv14':    {'name': 'CCTV14',    'cnlid': '2027248901', 'livepid': '600001809', 'defn': 'fhd'},
    'cctv15':    {'name': 'CCTV15',    'cnlid': '2027249001', 'livepid': '600001815', 'defn': 'fhd'},
    'cctv16':    {'name': 'CCTV16',    'cnlid': '2027249101', 'livepid': '600098637', 'defn': 'fhd'},
    'cctv164k':  {'name': 'CCTV16(4K)',    'cnlid': '2027249301', 'livepid': '600099502', 'defn': 'fhd'},
    'cctv17':    {'name': 'CCTV17',    'cnlid': '2027249401', 'livepid': '600001810', 'defn': 'fhd'},
    'cctv4k':    {'name': 'CCTV4K',        'cnlid': '2029810301', 'livepid': '600002264', 'defn': 'fhd'},
    'cctv8k':    {'name': 'CCTV8K',        'cnlid': '2026774101', 'livepid': '600156816', 'defn': 'fhd'},
    'cgtn':      {'name': 'CGTN',           'cnlid': '2024181701', 'livepid': '600014550', 'defn': 'fhd'},
    'cgtnfy':    {'name': 'CGTN法语频道',   'cnlid': '2024181801', 'livepid': '600084704', 'defn': 'fhd'},
    'cgtney':    {'name': 'CGTN俄语频道',   'cnlid': '2024181901', 'livepid': '600084758', 'defn': 'fhd'},
    'cgtnalby':  {'name': 'CGTN阿拉伯语频道','cnlid': '2024182001', 'livepid': '600084782', 'defn': 'fhd'},
    'cgtnxby':   {'name': 'CGTN西班牙语频道','cnlid': '2024182101', 'livepid': '600084744', 'defn': 'fhd'},
    'cgtnwyjl':  {'name': 'CGTN外语纪录频道','cnlid': '2024182301', 'livepid': '600084781', 'defn': 'fhd'},
    'cctvfyjc':  {'name': '风云剧场',   'cnlid': '2025637103', 'livepid': '600099658', 'defn': 'shd'},
    'cctvdyjc':  {'name': '第一剧场',   'cnlid': '2026874203', 'livepid': '600099655', 'defn': 'shd'},
    'cctvhjjc':  {'name': '怀旧剧场',   'cnlid': '2026874303', 'livepid': '600099620', 'defn': 'shd'},
    'cctvsjdl':  {'name': '世界地理',   'cnlid': '2026874403', 'livepid': '600099637', 'defn': 'shd'},
    'cctvfyyy':  {'name': '风云音乐',   'cnlid': '2026874503', 'livepid': '600099660', 'defn': 'shd'},
    'cctvbqkj':  {'name': '兵器科技',   'cnlid': '2026874603', 'livepid': '600099649', 'defn': 'shd'},
    'cctvfyzq':  {'name': '风云足球',   'cnlid': '2026966203', 'livepid': '600099636', 'defn': 'shd'},
    'cctvgeqwq': {'name': '高尔夫·网球','cnlid': '2026874703', 'livepid': '600099659', 'defn': 'shd'},
    'cctvnxss':  {'name': '女性时尚',   'cnlid': '2026874803', 'livepid': '600099650', 'defn': 'shd'},
    'cctvyswhjp':{'name': '央视文化精品','cnlid': '2026874903', 'livepid': '600099653', 'defn': 'shd'},
    'cctvystq':  {'name': '央视台球',   'cnlid': '2026875003', 'livepid': '600099652', 'defn': 'shd'},
    'cctvdszn':  {'name': '电视指南',   'cnlid': '2026875103', 'livepid': '600099656', 'defn': 'shd'},
    'cctvwsjk':  {'name': '卫生健康',   'cnlid': '2025637003', 'livepid': '600099651', 'defn': 'shd'},
    'bjws':      {'name': '北京卫视',       'cnlid': '2024052703', 'livepid': '600002309', 'defn': 'fhd'},
    'jsws':      {'name': '江苏卫视',       'cnlid': '2024171103', 'livepid': '600002521', 'defn': 'fhd'},
    'dfws':      {'name': '东方卫视',       'cnlid': '2024054503', 'livepid': '600002483', 'defn': 'fhd'},
    'zjws':      {'name': '浙江卫视',       'cnlid': '2024054703', 'livepid': '600002520', 'defn': 'fhd'},
    'hnws':      {'name': '湖南卫视',       'cnlid': '2024054803', 'livepid': '600002475', 'defn': 'fhd'},
    'hbws':      {'name': '湖北卫视',       'cnlid': '2024171203', 'livepid': '600002508', 'defn': 'fhd'},
    'gdws':      {'name': '广东卫视',       'cnlid': '2024060903', 'livepid': '600002485', 'defn': 'fhd'},
    'gxws':      {'name': '广西卫视',       'cnlid': '2024060703', 'livepid': '600002509', 'defn': 'fhd'},
    'hljws':     {'name': '黑龙江卫视',     'cnlid': '2029797003', 'livepid': '600002498', 'defn': 'fhd'},
    'hnws2':     {'name': '海南卫视',       'cnlid': '2024055603', 'livepid': '600002506', 'defn': 'fhd'},
    'cqws':      {'name': '重庆卫视',       'cnlid': '2024061103', 'livepid': '600002531', 'defn': 'fhd'},
    'szws':      {'name': '深圳卫视',       'cnlid': '2024061303', 'livepid': '600002481', 'defn': 'fhd'},
    'scws':      {'name': '四川卫视',       'cnlid': '2024061403', 'livepid': '600002516', 'defn': 'fhd'},
    'henanws':   {'name': '河南卫视',       'cnlid': '2029797303', 'livepid': '600002525', 'defn': 'fhd'},
    'fjdnhz':    {'name': '东南卫视',       'cnlid': '2024061503', 'livepid': '600002484', 'defn': 'fhd'},
    'gzhws':     {'name': '贵州卫视',       'cnlid': '2024061603', 'livepid': '600002490', 'defn': 'fhd'},
    'jxws':      {'name': '江西卫视',       'cnlid': '2024061703', 'livepid': '600002503', 'defn': 'fhd'},
    'lnws':      {'name': '辽宁卫视',       'cnlid': '2024171303', 'livepid': '600002505', 'defn': 'fhd'},
    'ahws':      {'name': '安徽卫视',       'cnlid': '2024171403', 'livepid': '600002532', 'defn': 'fhd'},
    'hbws2':     {'name': '河北卫视',       'cnlid': '2024171503', 'livepid': '600002493', 'defn': 'fhd'},
    'sdws':      {'name': '山东卫视',       'cnlid': '2029787903', 'livepid': '600002513', 'defn': 'fhd'},
    'tjws':      {'name': '天津卫视',       'cnlid': '2019927003', 'livepid': '600152137', 'defn': 'fhd'},
    'jlws':      {'name': '吉林卫视',       'cnlid': '2025561503', 'livepid': '600190405', 'defn': 'fhd'},
    'shanxiws':  {'name': '陕西卫视',       'cnlid': '2029795103', 'livepid': '600190400', 'defn': 'fhd'},
    'nxws':      {'name': '宁夏卫视',       'cnlid': '2025608503', 'livepid': '600190737', 'defn': 'fhd'},
    'nmgws':     {'name': '内蒙古卫视',     'cnlid': '2025561203', 'livepid': '600190401', 'defn': 'fhd'},
    'ynws':      {'name': '云南卫视',       'cnlid': '2025561303', 'livepid': '600190402', 'defn': 'fhd'},
    'shanxiws2': {'name': '山西卫视',       'cnlid': '2025560803', 'livepid': '600190407', 'defn': 'fhd'},
    'qhws':      {'name': '青海卫视',       'cnlid': '2025559103', 'livepid': '600190406', 'defn': 'fhd'},
    'xzws':      {'name': '西藏卫视',       'cnlid': '2025558003', 'livepid': '600190403', 'defn': 'fhd'},
    'cetv1':     {'name': '中国教育电视台1','cnlid': '2022823801', 'livepid': '600171827', 'defn': 'fhd'},
    'gxpd':      {'name': '国学频道',       'cnlid': '2029360403', 'livepid': '600213139', 'defn': 'fhd'},
    'xjws':      {'name': '新疆卫视',       'cnlid': '2019927403', 'livepid': '600152138', 'defn': 'fhd'}
}

CHANNEL_GROUPS = {
    '央视': [
        'cctv1', 'cctv2', 'cctv3', 'cctv4', 'cctv5', 'cctv5p', 'cctv6', 'cctv7',
        'cctv8', 'cctv9', 'cctv10', 'cctv11', 'cctv12', 'cctv13', 'cctv14',
        'cctv15', 'cctv16', 'cctv164k', 'cctv17', 'cctv4k', 'cctv8k',
        'cgtn', 'cgtnfy', 'cgtney', 'cgtnalby', 'cgtnxby', 'cgtnwyjl'
    ],
    '卫视': [
        'bjws', 'jsws', 'dfws', 'zjws', 'hnws', 'hbws', 'gdws', 'gxws',
        'hljws', 'hnws2', 'cqws', 'szws', 'scws', 'henanws', 'fjdnhz',
        'gzhws', 'jxws', 'lnws', 'ahws', 'hbws2', 'sdws', 'tjws', 'jlws',
        'shanxiws', 'nxws', 'nmgws', 'ynws', 'shanxiws2', 'qhws', 'xzws',
        'cetv1', 'xjws'
    ],
    '数字付费': [
        'cctvfyjc', 'cctvdyjc', 'cctvhjjc', 'cctvsjdl', 'cctvfyyy',
        'cctvbqkj', 'cctvfyzq', 'cctvgeqwq', 'cctvnxss', 'cctvyswhjp',
        'cctvystq', 'cctvdszn', 'cctvwsjk', 'gxpd'
    ]
}

CACHE_TTL = 1800
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache')
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR, 0o755, True)

# ==================== CKeyManager（完整加密，仅修改网络请求） ====================
class CKeyManager:
    DELTA = 0x9e3779b9
    ROUNDS = 16
    LOG_ROUNDS = 4
    SALT_LEN = 2
    ZERO_LEN = 7
    TEA_CKEY = binascii.unhexlify('59b2f7cf725ef43c34fdd7c123411ed3')
    GUARD_TEA_KEY = binascii.unhexlify('110DBEC10C23E7D2E56A1CAD6914EF1B')

    def __init__(self):
        self.xorKey = bytes([0x84, 0x2E, 0xED, 0x08, 0xF0, 0x66, 0xE6, 0xEA,
                             0x48, 0xB4, 0xCA, 0xA9, 0x91, 0xED, 0x6F, 0xF3])
        self.guardXorKey = bytes([0xB3, 0xC9, 0x53, 0xA0, 0x69, 0x13, 0xAD, 0x4D])
        self.standardAlphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/='
        self.customAlphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-='
        self.guid = ''
        self.generate_guid()

    def generate_guid(self):
        parts = [
            format(random.getrandbits(32), '08x'),
            format(random.getrandbits(16), '04x'),
            format(random.getrandbits(16), '04x'),
            format(random.getrandbits(16), '04x'),
            format(random.getrandbits(48), '012x')
        ]
        self.guid = ''.join(parts)
        if len(self.guid) != 32:
            self.guid = self.guid.ljust(32, '0')
        return self.guid

    def get_guid(self):
        return self.guid

    @staticmethod
    def calc_signature(buffer_bytes):
        signature = 0
        for b in buffer_bytes:
            signature = (0x83 * signature + b) & 0x7FFFFFFF
        return signature

    def custom_decode(self, text):
        if not text:
            return b''
        text = text.rstrip('=')
        if len(text) % 4 != 0:
            text += '=' * (4 - len(text) % 4)
        trans = str.maketrans(self.customAlphabet[:64], self.standardAlphabet[:64])
        translated = text.translate(trans)
        return base64.b64decode(translated)

    def custom_encode(self, data):
        encoded = base64.b64encode(data).decode()
        trans = str.maketrans(self.standardAlphabet[:64], self.customAlphabet[:64])
        translated = encoded.translate(trans)
        return translated.rstrip('=')

    def xor_array(self, byte_array):
        if isinstance(byte_array, bytes):
            byte_array = list(byte_array)
        result = bytearray(len(byte_array))
        for i, b in enumerate(byte_array):
            result[i] = b ^ self.xorKey[i & 0xF]
        return bytes(result)

    def tea_encrypt_ecb(self, p_in_buf, p_key):
        if len(p_in_buf) < 8:
            p_in_buf = p_in_buf.ljust(8, b'\0')
        y, z = struct.unpack('>2I', p_in_buf[:8])
        k = struct.unpack('>4I', p_key[:16])
        sum_val = 0
        for _ in range(self.ROUNDS):
            sum_val = (sum_val + self.DELTA) & 0xFFFFFFFF
            y = (y + (((z << 4) + k[0]) ^ (z + sum_val) ^ ((z >> 5) + k[1]))) & 0xFFFFFFFF
            z = (z + (((y << 4) + k[2]) ^ (y + sum_val) ^ ((y >> 5) + k[3]))) & 0xFFFFFFFF
        return struct.pack('>2I', y, z)

    def tea_decrypt_ecb(self, p_in_buf, p_key):
        y, z = struct.unpack('>2I', p_in_buf[:8])
        k = struct.unpack('>4I', p_key[:16])
        sum_val = (self.DELTA << self.LOG_ROUNDS) & 0xFFFFFFFF
        for _ in range(self.ROUNDS):
            z = (z - (((y << 4) + k[2]) ^ (y + sum_val) ^ ((y >> 5) + k[3]))) & 0xFFFFFFFF
            y = (y - (((z << 4) + k[0]) ^ (z + sum_val) ^ ((z >> 5) + k[1]))) & 0xFFFFFFFF
            sum_val = (sum_val - self.DELTA) & 0xFFFFFFFF
        return struct.pack('>2I', y, z)

    def oi_symmetry_encrypt2(self, p_in_buf, n_in_buf_len, p_key):
        n_pad_salt_body_zero_len = n_in_buf_len + 1 + self.SALT_LEN + self.ZERO_LEN
        n_pad_len = n_pad_salt_body_zero_len % 8
        if n_pad_len:
            n_pad_len = 8 - n_pad_len

        p_out_buf = bytearray()
        src_buf = bytearray(8)
        src_buf[0] = (random.randint(0, 255) & 0xF8) | n_pad_len
        src_i = 1

        while n_pad_len:
            src_buf[src_i] = random.randint(0, 255)
            src_i += 1
            n_pad_len -= 1

        iv_plain = bytearray(8)
        iv_crypt = bytearray(8)

        i = 0
        while i < self.SALT_LEN:
            if src_i < 8:
                src_buf[src_i] = random.randint(0, 255)
                src_i += 1
                i += 1
            if src_i == 8:
                for j in range(8):
                    src_buf[j] ^= iv_crypt[j]
                temp_out = self.tea_encrypt_ecb(bytes(src_buf), p_key)
                temp_bytes = list(temp_out)
                for j in range(8):
                    temp_bytes[j] ^= iv_plain[j]
                iv_plain = src_buf[:]
                iv_crypt = bytes(temp_bytes)
                p_out_buf.extend(temp_bytes)
                src_i = 0

        p_in_buf_index = 0
        while n_in_buf_len:
            if src_i < 8:
                src_buf[src_i] = p_in_buf[p_in_buf_index]
                p_in_buf_index += 1
                src_i += 1
                n_in_buf_len -= 1
            if src_i == 8:
                for j in range(8):
                    src_buf[j] ^= iv_crypt[j]
                temp_out = self.tea_encrypt_ecb(bytes(src_buf), p_key)
                temp_bytes = list(temp_out)
                for j in range(8):
                    temp_bytes[j] ^= iv_plain[j]
                iv_plain = src_buf[:]
                iv_crypt = bytes(temp_bytes)
                p_out_buf.extend(temp_bytes)
                src_i = 0

        i = 0
        while i < self.ZERO_LEN:
            if src_i < 8:
                src_buf[src_i] = 0
                src_i += 1
                i += 1
            if src_i == 8:
                for j in range(8):
                    src_buf[j] ^= iv_crypt[j]
                temp_out = self.tea_encrypt_ecb(bytes(src_buf), p_key)
                temp_bytes = list(temp_out)
                for j in range(8):
                    temp_bytes[j] ^= iv_plain[j]
                iv_plain = src_buf[:]
                iv_crypt = bytes(temp_bytes)
                p_out_buf.extend(temp_bytes)
                src_i = 0

        if src_i > 0:
            for j in range(src_i, 8):
                src_buf[j] = 0
            for j in range(8):
                src_buf[j] ^= iv_crypt[j]
            temp_out = self.tea_encrypt_ecb(bytes(src_buf), p_key)
            temp_bytes = list(temp_out)
            for j in range(8):
                temp_bytes[j] ^= iv_plain[j]
            p_out_buf.extend(temp_bytes)

        return bytes(p_out_buf)

    def oi_symmetry_decrypt2(self, p_in_buf, n_in_buf_len, p_key):
        if n_in_buf_len % 8 != 0 or n_in_buf_len < 16:
            return None
        dest_buf = list(self.tea_decrypt_ecb(p_in_buf[:8], p_key))
        n_pad_len = dest_buf[0] & 0x07
        i = n_in_buf_len - 1
        i = i - n_pad_len - self.SALT_LEN - self.ZERO_LEN
        if i < 0:
            return None
        p_out_buf_len = i

        iv_pre_crypt = bytearray(8)
        iv_cur_crypt = list(p_in_buf[:8])
        p_in_buf_offset = 8
        dest_i = 1 + n_pad_len

        salt_count = 1
        while salt_count <= self.SALT_LEN:
            if dest_i < 8:
                dest_i += 1
                salt_count += 1
            elif dest_i == 8:
                iv_pre_crypt = iv_cur_crypt[:]
                iv_cur_crypt = list(p_in_buf[p_in_buf_offset:p_in_buf_offset+8])
                for j in range(8):
                    if p_in_buf_offset + j >= n_in_buf_len:
                        return None
                    dest_buf[j] ^= iv_cur_crypt[j]
                temp_buf = self.tea_decrypt_ecb(bytes(dest_buf), p_key)
                dest_buf = list(temp_buf)
                p_in_buf_offset += 8
                dest_i = 0

        plain_bytes = bytearray()
        n_plain_len = p_out_buf_len
        while n_plain_len > 0:
            if dest_i < 8:
                plain_bytes.append(dest_buf[dest_i] ^ iv_pre_crypt[dest_i])
                dest_i += 1
                n_plain_len -= 1
            elif dest_i == 8:
                iv_pre_crypt = iv_cur_crypt[:]
                iv_cur_crypt = list(p_in_buf[p_in_buf_offset:p_in_buf_offset+8])
                for j in range(8):
                    if p_in_buf_offset + j >= n_in_buf_len:
                        return None
                    dest_buf[j] ^= iv_cur_crypt[j]
                temp_buf = self.tea_decrypt_ecb(bytes(dest_buf), p_key)
                dest_buf = list(temp_buf)
                p_in_buf_offset += 8
                dest_i = 0
        return bytes(plain_bytes)

    def generate_ck_guard_time(self, timestamp, guid, guard_data='-1', package_name='null', process_name='null'):
        body = struct.pack('>I', timestamp)
        for part in [self.guard_last_five(guid), self.guard_last_five(package_name),
                     self.guard_last_five(process_name), guard_data]:
            body += struct.pack('>H', len(part)) + part.encode('utf-8')
        plain = struct.pack('>H', len(body)) + body
        checksum = self.calc_signature(plain)
        encrypted = self.oi_symmetry_encrypt2(plain, len(plain), self.GUARD_TEA_KEY)
        encrypted += struct.pack('>I', checksum)
        bytes_list = list(encrypted)
        for i in range(len(bytes_list)):
            bytes_list[i] ^= self.guardXorKey[i & 7]
        return binascii.hexlify(bytes(bytes_list)).decode().upper()

    @staticmethod
    def guard_last_five(value):
        s = str(value)
        return s[-5:] if len(s) >= 5 else ''

    def encrypt_data_to_ckey(self, data):
        data_len = len(data)
        checksum = self.calc_signature(data)
        encrypted = self.oi_symmetry_encrypt2(data, data_len, self.TEA_CKEY)
        encrypted += struct.pack('>I', checksum)
        xor_encrypted = self.xor_array(encrypted)
        base64_encoded = self.custom_encode(xor_encrypted)
        return "--01" + base64_encoded

    def decrypt_ckey_to_data(self, ckey):
        ckey_without_prefix = ckey[4:]
        base64_decoded = self.custom_decode(ckey_without_prefix)
        if base64_decoded is None:
            return None
        xor_decrypted = self.xor_array(base64_decoded)
        data_len = len(xor_decrypted) - 4
        encrypted_data = xor_decrypted[:data_len]
        checksum_bytes = xor_decrypted[data_len:]
        checksum = struct.unpack('>I', checksum_bytes)[0]
        decrypted = self.oi_symmetry_decrypt2(encrypted_data, data_len, self.TEA_CKEY)
        if decrypted is None:
            return None
        return {'data': decrypted, 'checksum': checksum}

    def build_packet(self, params):
        data = bytearray(binascii.unhexlify('0000004200000004000004d2'))
        data += struct.pack('>I', params['Platform'])
        data += struct.pack('>I', 0)
        data += struct.pack('>I', params['Timestamp'])
        for key in ['Sdtfrom', 'randFlag', 'appVer', 'vid', 'guid']:
            val = params[key].encode('utf-8')
            data += struct.pack('>H', len(val)) + val
        data += struct.pack('>I', 1)
        data += struct.pack('>I', 1)
        uid = "2622783A".encode('utf-8')
        data += struct.pack('>H', len(uid)) + uid
        bundleID = "nil".encode('utf-8')
        data += struct.pack('>H', len(bundleID)) + bundleID
        uuid4 = params['uuid4'].encode('utf-8')
        data += struct.pack('>H', len(uuid4)) + uuid4
        data += struct.pack('>H', len(bundleID)) + bundleID
        ckeyVersion = "v0.1.000".encode('utf-8')
        data += struct.pack('>H', len(ckeyVersion)) + ckeyVersion
        packageName = "com.cctv.yangshipin.app.iphone".encode('utf-8')
        data += struct.pack('>H', len(packageName)) + packageName
        platform_str = "4330403".encode('utf-8')
        data += struct.pack('>H', len(platform_str)) + platform_str
        ex_json_bus = "ex_json_bus".encode('utf-8')
        data += struct.pack('>H', len(ex_json_bus)) + ex_json_bus
        ex_json_vs = "ex_json_vs".encode('utf-8')
        data += struct.pack('>H', len(ex_json_vs)) + ex_json_vs
        ck_guard_time = params['ck_guard_time'].encode('utf-8')
        data += struct.pack('>H', len(ck_guard_time)) + ck_guard_time

        body_length = len(data)
        buffer = struct.pack('>H', body_length) + data
        signature = self.calc_signature(buffer)
        buffer = buffer[:18] + struct.pack('>I', signature) + buffer[22:]
        return buffer

    def generate_ckey(self, cnlid, timestamp=None):
        if timestamp is None:
            timestamp = int(time.time())
        randFlag = base64.b64encode(os.urandom(18)).decode()
        uuid4 = f"{random.getrandbits(16):04x}{random.getrandbits(16):04x}-{random.getrandbits(16):04x}-{random.getrandbits(16):04x}-{random.getrandbits(16):04x}-{random.getrandbits(16):04x}{random.getrandbits(16):04x}{random.getrandbits(16):04x}"
        ck_guard_time = self.generate_ck_guard_time(timestamp, self.guid)
        params = {
            'Platform': 4330403,
            'Timestamp': timestamp,
            'Sdtfrom': 'dcgh',
            'vid': cnlid,
            'guid': self.guid,
            'appVer': 'V8.22.1035.3031',
            'randFlag': randFlag,
            'uuid4': uuid4,
            'ck_guard_time': ck_guard_time
        }
        buffer = self.build_packet(params)
        ckey = self.encrypt_data_to_ckey(buffer)
        return {'ckey': ckey, 'params': params}

    def make_live_request(self, cnlid, livepid, defn):
        self.generate_guid()
        ckey_result = self.generate_ckey(cnlid)
        ckey = ckey_result['ckey']
        params = ckey_result['params']

        flowid = f"{random.getrandbits(16):04X}{random.getrandbits(16):04X}-{random.getrandbits(16):04X}-{random.getrandbits(16):04X}-{random.getrandbits(16):04X}-{random.getrandbits(16):04X}{random.getrandbits(16):04X}{random.getrandbits(16):04X}_4330403"

        spvcode = "MSgzMDoyMTYwLDYwOjIxNjB8MzA6MjE2MCw2MDoyMTYwKTsyKDMwOjIxNjAsNjA6MjE2MHwzMDoyMTYwLDYwOjIxNjAp"

        request_params = {
            "atime": "120",
            "livepid": livepid,
            "cnlid": cnlid,
            "appVer": "V8.22.1035.3031",
            "app_version": "300090",
            "caplv": "1",
            "cmd": "2",
            "defn": defn,
            "device": "iPhone",
            "encryptVer": "4.2",
            "getpreviewinfo": "0",
            "hevclv": "33",
            "lang": "zh-Hans_JP",
            "livequeue": "0",
            "logintype": "1",
            "nettype": "1",
            "newnettype": "1",
            "newplatform": "4330403",
            "platform": "4330403",
            "sdtfrom": "v3021",
            "spacode": "23",
            "spaudio": "1",
            "spdemuxer": "6",
            "spdrm": "2",
            "spdynamicrange": "7",
            "spflv": "1",
            "spflvaudio": "1",
            "sphdrfps": "60",
            "sphttps": "0",
            "spvcode": spvcode,
            "spvideo": "4",
            "stream": "1",
            "system": "1",
            "sysver": "ios18.2.1",
            "uhd_flag": "4",
            "cKey": ckey,
            "guid": self.guid,
            "fntick": str(params['Timestamp']),
            "flowid": flowid,
            "playbacktime": "0"
        }
        return self.send_http_request(request_params)

    def make_playback_request(self, cnlid, livepid, defn, playback_timestamp):
        """回看请求"""
        self.generate_guid()
        ckey_result = self.generate_ckey(cnlid)
        ckey = ckey_result['ckey']
        params = ckey_result['params']

        flowid = f"{random.getrandbits(16):04X}{random.getrandbits(16):04X}-{random.getrandbits(16):04X}-{random.getrandbits(16):04X}-{random.getrandbits(16):04X}-{random.getrandbits(16):04X}{random.getrandbits(16):04X}{random.getrandbits(16):04X}_4330403"

        spvcode = "MSgzMDoyMTYwLDYwOjIxNjB8MzA6MjE2MCw2MDoyMTYwKTsyKDMwOjIxNjAsNjA6MjE2MHwzMDoyMTYwLDYwOjIxNjAp"

        request_params = {
            "atime": "120",
            "livepid": livepid,
            "cnlid": cnlid,
            "appVer": "V8.22.1035.3031",
            "app_version": "300090",
            "caplv": "1",
            "cmd": "2",
            "defn": defn,
            "device": "iPhone",
            "encryptVer": "4.2",
            "getpreviewinfo": "0",
            "hevclv": "33",
            "lang": "zh-Hans_JP",
            "livequeue": "0",
            "logintype": "1",
            "nettype": "1",
            "newnettype": "1",
            "newplatform": "4330403",
            "platform": "4330403",
            "sdtfrom": "v3021",
            "spacode": "23",
            "spaudio": "1",
            "spdemuxer": "6",
            "spdrm": "2",
            "spdynamicrange": "7",
            "spflv": "1",
            "spflvaudio": "1",
            "sphdrfps": "60",
            "sphttps": "0",
            "spvcode": spvcode,
            "spvideo": "4",
            "stream": "1",
            "system": "1",
            "sysver": "ios18.2.1",
            "uhd_flag": "4",
            "cKey": ckey,
            "guid": self.guid,
            "fntick": str(params['Timestamp']),
            "flowid": flowid,
            "playbacktime": str(playback_timestamp)
        }
        return self.send_http_request(request_params)

    # ---------- 核心网络请求（使用 urllib，无 requests） ----------
    def send_http_request(self, params):
        url = "https://bkliveinfo.ysp.cctv.cn"
        # 构建 GET 参数
        query = urlencode(params)
        full_url = f"{url}?{query}"
        headers = {
            'User-Agent': 'qqlive',
            'Connection': 'Keep-Alive',
            'Accept': 'application/json'
        }

        try:
            log(f"请求 bkliveinfo: {full_url[:200]}...", 'DEBUG')
            req = urllib.request.Request(full_url, headers=headers, method='GET')
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('iretcode') == 0:
                    playurl = data.get('playurl')
                    log(f"获取 playurl 成功: {playurl}")
                    return {'success': True, 'playurl': playurl}
                else:
                    log(f"接口返回错误 iretcode={data.get('iretcode')}, msg={data.get('msg', '')}", 'ERROR')
                    return {'success': False, 'iretcode': data.get('iretcode')}
        except Exception as e:
            log(f"请求异常: {e}", 'ERROR')
            return {'success': False, 'error': str(e)}

    def get_play_url(self, cnlid, livepid, defn, playback_timestamp=None):
        if playback_timestamp:
            result = self.make_playback_request(cnlid, livepid, defn, playback_timestamp)
        else:
            result = self.make_live_request(cnlid, livepid, defn)
        if result.get('success') and result.get('playurl'):
            return result['playurl']
        return None


# ==================== Spider 插件类 ====================
class Spider(BaseSpider):
    def __init__(self):
        super().__init__()
        log("Spider.__init__ 被调用")
        # 不再需要 session

    def getName(self):
        return "央视频（直播+回看）"

    def init(self, extend):
        log(f"Spider.init 被调用，extend={extend}")

    # ---------- 通用 HTTP GET 请求（优先使用 self.fetch，降级 urllib） ----------
    def _http_get(self, url, headers=None, timeout=20):
        """发送 GET 请求，返回响应文本或 None"""
        if headers is None:
            headers = {}
        try:
            # 尝试使用 TVBox 提供的 fetch 方法
            if hasattr(self, 'fetch'):
                resp = self.fetch(url, headers=headers, timeout=timeout)
                if hasattr(resp, 'text'):
                    return resp.text
                elif hasattr(resp, 'content'):
                    return resp.content.decode('utf-8', errors='ignore')
                else:
                    return str(resp) if resp else None
        except Exception as e:
            log(f"self.fetch 失败，降级 urllib: {e}", 'DEBUG')

        # 降级使用 urllib
        try:
            req = urllib.request.Request(url, headers=headers, method='GET')
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                return resp.read().decode('utf-8', errors='ignore')
        except Exception as e:
            log(f"urllib 请求失败: {e}", 'ERROR')
            return None

    # ---------- 文件缓存 ----------
    def _cache_path(self, channel_id):
        return os.path.join(CACHE_DIR, hashlib.md5(channel_id.encode()).hexdigest() + '.cache')

    def _get_cached_playurl(self, channel_id):
        cache_file = self._cache_path(channel_id)
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and 'url' in data and 'time' in data:
                        age = time.time() - data['time']
                        if age < CACHE_TTL:
                            log(f"缓存命中 playurl: {channel_id}, 年龄={age:.0f}s")
                            return data['url'], True
                        else:
                            log(f"缓存过期 playurl: {channel_id}, 年龄={age:.0f}s")
            except Exception as e:
                log(f"读取缓存失败: {e}", 'ERROR')
        return None, False

    def _set_cached_playurl(self, channel_id, playurl):
        cache_file = self._cache_path(channel_id)
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({'url': playurl, 'time': int(time.time())}, f)
            log(f"已缓存 playurl: {channel_id}")
        except Exception as e:
            log(f"写入缓存失败: {e}", 'ERROR')

    # ---------- M3U8 获取与补全 ----------
    def _fetch_and_fix_m3u8(self, play_url):
        try:
            log(f"开始获取 M3U8")
            headers = {
                'User-Agent': 'qqlive',
                'Referer': 'https://ysp.cctv.cn/',
                'Accept': 'application/vnd.apple.mpegurl, */*',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive'
            }
            content = self._http_get(play_url, headers=headers, timeout=20)
            if content is None:
                log("M3U8 获取失败 (返回空)", 'ERROR')
                return None

            if '#EXTM3U' not in content:
                log("原始 M3U8 不包含 #EXTM3U 头", 'ERROR')
                return None

            parsed = urlparse(play_url)
            base = f"{parsed.scheme}://{parsed.netloc}{parsed.path[:parsed.path.rfind('/')+1]}"
            fixed_lines = []
            for line in content.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith('#') and '.ts' in stripped:
                    if not stripped.startswith(('http://', 'https://')):
                        new_url = urljoin(base, stripped)
                        fixed_lines.append(new_url)
                    else:
                        fixed_lines.append(line)
                else:
                    fixed_lines.append(line)
            result = '\n'.join(fixed_lines)
            log(f"成功获取并补全 M3U8，长度 {len(result)} 字符")
            return result
        except Exception as e:
            log(f"获取/补全 M3U8 异常: {e}", 'ERROR')
            return None

    # ---------- TVBox 接口 ----------
    def localProxy(self, params):
        log(f"*** 进入 localProxy *** params={params}")
        try:
            fun = params.get('fun')
            if fun == 'cctv':
                channel_id = params.get('id')
                if not channel_id:
                    return self._error_response("缺少频道ID")
                ch = CHANNELS.get(channel_id)
                if not ch:
                    return self._error_response(f"频道 {channel_id} 不存在")

                playseek = params.get('playseek')
                if playseek:
                    log(f"回看请求: {channel_id} ({ch['name']}), playseek={playseek}")
                    try:
                        parts = playseek.split('-')
                        if len(parts) < 1 or not parts[0]:
                            return self._error_response("回看参数格式错误")
                        start_str = parts[0]
                        start_dt = datetime.strptime(start_str, '%Y%m%d%H%M%S')
                        playback_timestamp = int(start_dt.timestamp())

                        manager = CKeyManager()
                        playurl = manager.get_play_url(
                            ch['cnlid'],
                            ch['livepid'],
                            ch['defn'],
                            playback_timestamp
                        )
                        if not playurl:
                            log("获取回看 playurl 失败", 'ERROR')
                            return self._error_response("获取回看地址失败，该频道可能不支持回看")

                        m3u8_content = self._fetch_and_fix_m3u8(playurl)
                        if not m3u8_content:
                            return self._error_response("获取回看M3U8内容失败")

                        log(f"成功返回回看 M3U8 内容，长度 {len(m3u8_content)}")
                        return [200, "application/vnd.apple.mpegurl", m3u8_content]
                    except ValueError:
                        return self._error_response("回看时间格式错误，请检查日期时间")
                    except Exception as e:
                        log(f"回看处理异常: {e}", 'ERROR')
                        return self._error_response("回看处理失败")
                else:
                    # 正常直播
                    log(f"直播请求: {channel_id} ({ch['name']})")
                    playurl, valid = self._get_cached_playurl(channel_id)
                    if not valid:
                        log("缓存失效，请求 playurl")
                        manager = CKeyManager()
                        playurl = manager.get_play_url(ch['cnlid'], ch['livepid'], ch['defn'])
                        if not playurl:
                            return self._error_response("获取播放地址失败")
                        self._set_cached_playurl(channel_id, playurl)

                    m3u8_content = self._fetch_and_fix_m3u8(playurl)
                    if not m3u8_content:
                        log("首次获取失败，重试")
                        manager = CKeyManager()
                        playurl2 = manager.get_play_url(ch['cnlid'], ch['livepid'], ch['defn'])
                        if not playurl2:
                            return self._error_response("重试获取播放地址失败")
                        self._set_cached_playurl(channel_id, playurl2)
                        m3u8_content = self._fetch_and_fix_m3u8(playurl2)
                        if not m3u8_content:
                            return self._error_response("重试获取M3U8内容失败")

                    log(f"成功返回直播 M3U8，长度 {len(m3u8_content)}")
                    return [200, "application/vnd.apple.mpegurl", m3u8_content]

            return self._error_response("未知请求")
        except Exception as e:
            log(f"localProxy 异常: {e}\n{traceback.format_exc()}", 'ERROR')
            return self._error_response("内部错误")

    def liveContent(self, url):
        lines = ['#EXTM3U']
        base_proxy = self.getProxyUrl()
        if not base_proxy.endswith(('?', '&')):
            base_proxy += '&'
        for group_name, channel_ids in CHANNEL_GROUPS.items():
            lines.append(f'\n#  {group_name}\n')
            for pid in channel_ids:
                if pid in CHANNELS:
                    info = CHANNELS[pid]
                    lines.append(f'#EXTINF:-1 tvg-id="{info["name"]}" tvg-name="{info["name"]}" group-title="{group_name}",{info["name"]}')
                    proxy_url = base_proxy + f'fun=cctv&id={pid}'
                    lines.append(proxy_url)
        log(f"生成直播列表，共 {len(CHANNELS)} 个频道")
        return '\n'.join(lines)

    def _error_response(self, msg):
        error_m3u = (
            "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-MEDIA-SEQUENCE:0\n"
            "#EXT-X-TARGETDURATION:10\n#EXTINF:10.0,\nerror.ts\n"
            f"#EXT-X-ENDLIST\n# {msg}"
        )
        log(f"返回错误: {msg}", 'ERROR')
        return [500, "application/vnd.apple.mpegurl", error_m3u]

    def destroy(self):
        log("Spider 销毁")
        pass


if __name__ == '__main__':
    # 独立测试模式
    print("开始独立测试")
    spider = Spider()
    print("=== 测试生成列表 ===")
    m3u = spider.liveContent("")
    for line in m3u.split('\n')[:10]:
        print(line)
    print("\n=== 测试直播请求 cctv1 ===")
    result = spider.localProxy({'fun': 'cctv', 'id': 'cctv1'})
    if result[0] == 200:
        print("✅ 获取成功，M3U8 内容长度:", len(result[2]))
    else:
        print("❌ 失败:", result[2])
    spider.destroy()
