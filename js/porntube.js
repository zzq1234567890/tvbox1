// PornTube v1.0.2 -> FongMi / 影视TV QuickJS spider
// Site config: {"key":"porntube","name":"PornTube","type":3,"api":"./PornTube.js","ext":{}}
// ext 可选：
// {
//   "hosts": ["https://v2.cdn199.com", "https://v2.kekecdn.net"],
//   "timeout": 20000,
//   "app": "porntube.cool",
//   "version": "260901"
// }
//
// 说明：
// 1. 接口响应为 CryptoJS AES-CBC ("xxx") OpenSSL 格式，本文件纯 JS 解密，不依赖 CryptoJS。
// 2. m3u8s[0] 是服务端生成的临时签名直链（约 2 小时有效），playerContent 每次重新请求详情现取现用。
// 3. 详情页两条线：正片 + 同作者相关推荐；相关推荐通过 /searchSevenVideos 的 user_<作者> 查询。
// 4. VIP 由接口直接返回 m3u8s，无需登录、无需 Cookie。

import {Spider, link} from "catvod";

const DEFAULT_HOSTS = [
    "https://v2.cdn199.com",
    "https://v2.kekecdn.net",
    "https://v2.luchu.org",
    "https://v2.madou.ws",
    "https://v2.papapa.biz",
    "https://v2.xiaoshuo.info",
    "https://v2.xiaoshuo.la",
];
const DEFAULT_APP = "porntube.cool";
const DEFAULT_VERSION = "260901";
const DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
const DEFAULT_TIMEOUT = 20000;
const PAGE_SIZE = 24;
const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

// 32 个细分分类：VIP 免登录专享 + 20 个站点主分类 + 11 个榜单/标签。
const CATEGORIES = [
    ["home_vip", "VIP专享（免登录）"],
    ["hot", "91Porn大神"],
    ["banana", "淫工工作室"],
    ["c1", "麻豆视频"],
    ["c2", "91制片厂"],
    ["c3", "玩偶姐姐"],
    ["c4", "小鸟酱专题"],
    ["c5", "糖心Vlog"],
    ["c6", "天美传媒"],
    ["c7", "蜜桃传媒"],
    ["c8", "皇家华人"],
    ["c9", "星空传媒"],
    ["ca", "精东影业"],
    ["cc", "成人头条"],
    ["cd", "乌鸦传媒"],
    ["cl", "开心鬼传媒"],
    ["cq", "BDSM"],
    ["pissvids", "欧美重口 (pissvids)"],
    ["lesbian", "女同系列"],
    ["xart", "欧美唯美"],
    ["kink", "欧美重口"],
    ["recent", "最近更新"],
    ["hd", "高清视频"],
    ["recent_hot", "最近加精"],
    ["91original", "91原创"],
    ["10mins", "10分钟以上"],
    ["20mins", "20分钟以上"],
    ["month_discuss", "本月讨论"],
    ["month_favs", "本月收藏"],
    ["favs", "收藏最多"],
    ["month_hot", "本月最热"],
    ["last_month_hot", "上月最热"],
];

function str(value) {
    if (value == null) return "";
    return String(value);
}

function parseExtend(extend) {
    if (extend == null || extend === "") return {};
    if (typeof extend === "object") return extend;
    try {
        const value = JSON.parse(extend);
        return value && typeof value === "object" ? value : {};
    } catch (error) {
        return {};
    }
}

function intValue(value, fallback) {
    const number = parseInt(value, 10);
    return isFinite(number) ? number : fallback;
}

function cleanEpisodeName(value) {
    return str(value)
        .replace(/\$/g, " ")
        .replace(/#/g, " ")
        .replace(/[\r\n]+/g, " ")
        .replace(/\s+/g, " ")
        .trim() || "播放";
}

function yearOf(timestamp) {
    const value = intValue(timestamp, 0);
    if (!value) return "";
    try {
        return str(new Date(value).getFullYear());
    } catch (error) {
        return "";
    }
}

function pageCount(list, page) {
    return list.length >= PAGE_SIZE ? page + 1 : page;
}

function normalizeVideo(item) {
    if (!item || typeof item !== "object") return null;
    const id = str(item.id || item.vId);
    if (!id) return null;
    const thumbs = item.thumbnails || item.thumbNails || [];
    const pic = thumbs.length ? str(thumbs[0]) : "";
    const keywords = str(item.keywords_gem || item.keywords || "");
    const author = str(item.user || item.user_en || "");
    const vip = Boolean(item.vip);
    const remarks = [str(item.durationStr || ""), str(item.time || ""), vip ? "VIP" : ""]
        .filter(Boolean).join(" · ");
    return {
        vod_id: id,
        vod_name: str(item.title || item.title_en || id),
        vod_pic: pic,
        vod_type: keywords,
        vod_tag: keywords,
        vod_remarks: remarks,
        vod_year: yearOf(item.createdTime),
        vod_actor: author,
        vod_director: author,
        vod_content: [
            keywords ? "标签：" + keywords : "",
            author ? "作者：" + author : "",
            item.durationStr ? "时长：" + str(item.durationStr) : "",
            item.size ? "大小：" + str(item.size) : "",
            item.views != null ? "播放：" + str(item.views) : "",
            str(item.time || ""),
        ].filter(Boolean).join("\n"),
        style: {type: "rect", ratio: 1.78},
        _raw: item,
    };
}

function videoCards(items) {
    const cards = [];
    const seen = {};
    for (const item of items) {
        const card = normalizeVideo(item);
        if (!card || seen[card.vod_id]) continue;
        seen[card.vod_id] = true;
        delete card._raw;
        if (card.vod_actor) {
            card.vod_actor = link(card.vod_actor, {
                id: "user_" + card.vod_actor,
                name: card.vod_actor,
                type_flag: "1",
            });
        }
        cards.push(card);
    }
    return cards;
}

// ---------- CryptoJS-compatible OpenSSL AES-256-CBC / MD5 KDF ----------
// CryptoJS.AES.decrypt(r, "xxx").toString(CryptoJS.enc.Utf8)

function rotl32(value, count) {
    return (((value << count) | (value >>> (32 - count))) >>> 0);
}

function xtime(value) {
    return ((value << 1) ^ ((value & 0x80) ? 0x1b : 0)) & 0xff;
}

function gfMul(left, right) {
    let result = 0;
    let a = left;
    let b = right;
    while (b) {
        if (b & 1) result ^= a;
        a = xtime(a);
        b >>>= 1;
    }
    return result & 0xff;
}

function gfInverse(value) {
    if (!value) return 0;
    for (let candidate = 1; candidate < 256; candidate++) {
        if (gfMul(value, candidate) === 1) return candidate;
    }
    return 0;
}

function rotl8(value, count) {
    return (((value << count) | (value >>> (8 - count))) & 0xff);
}

const S_BOX = new Uint8Array(256);
const INV_S_BOX = new Uint8Array(256);
for (let index = 0; index < 256; index++) {
    const inverse = gfInverse(index);
    const substituted = (inverse ^ rotl8(inverse, 1) ^ rotl8(inverse, 2) ^
        rotl8(inverse, 3) ^ rotl8(inverse, 4) ^ 0x63) & 0xff;
    S_BOX[index] = substituted;
    INV_S_BOX[substituted] = index;
}

const MD5_K = [
    0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
    0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
    0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
    0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
    0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
    0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
    0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
    0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391,
];

const MD5_S = [
    7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
    5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
    4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
    6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
];

function md5Bytes(input) {
    const message = Array.prototype.slice.call(input);
    const bitLength = message.length * 8;
    message.push(0x80);
    while (message.length % 64 !== 56) message.push(0);
    const low = bitLength >>> 0;
    const high = Math.floor(bitLength / 4294967296) >>> 0;
    const lengthBytes = [
        low & 0xff, (low >>> 8) & 0xff, (low >>> 16) & 0xff, (low >>> 24) & 0xff,
        high & 0xff, (high >>> 8) & 0xff, (high >>> 16) & 0xff, (high >>> 24) & 0xff,
    ];
    for (const byte of lengthBytes) message.push(byte);

    let a0 = 0x67452301;
    let b0 = 0xefcdab89;
    let c0 = 0x98badcfe;
    let d0 = 0x10325476;
    const words = new Array(16);

    for (let offset = 0; offset < message.length; offset += 64) {
        for (let index = 0; index < 16; index++) {
            const position = offset + index * 4;
            words[index] = (message[position] | (message[position + 1] << 8) |
                (message[position + 2] << 16) | (message[position + 3] << 24)) >>> 0;
        }
        let a = a0;
        let b = b0;
        let c = c0;
        let d = d0;
        for (let index = 0; index < 64; index++) {
            let mix;
            let wordIndex;
            if (index < 16) {
                mix = (b & c) | (~b & d);
                wordIndex = index;
            } else if (index < 32) {
                mix = (d & b) | (~d & c);
                wordIndex = (5 * index + 1) % 16;
            } else if (index < 48) {
                mix = b ^ c ^ d;
                wordIndex = (3 * index + 5) % 16;
            } else {
                mix = c ^ (b | ~d);
                wordIndex = (7 * index) % 16;
            }
            mix = (mix + a + MD5_K[index] + words[wordIndex]) >>> 0;
            a = d;
            d = c;
            c = b;
            b = (b + rotl32(mix, MD5_S[index])) >>> 0;
        }
        a0 = (a0 + a) >>> 0;
        b0 = (b0 + b) >>> 0;
        c0 = (c0 + c) >>> 0;
        d0 = (d0 + d) >>> 0;
    }

    const result = [];
    for (const word of [a0, b0, c0, d0]) {
        result.push(word & 0xff, (word >>> 8) & 0xff, (word >>> 16) & 0xff, (word >>> 24) & 0xff);
    }
    return result;
}

function utf8Encode(text) {
    const bytes = [];
    for (let index = 0; index < text.length; index++) {
        const code = text.charCodeAt(index);
        if (code < 0x80) bytes.push(code);
        else if (code < 0x800) bytes.push(0xc0 | (code >>> 6), 0x80 | (code & 0x3f));
        else bytes.push(0xe0 | (code >>> 12), 0x80 | ((code >>> 6) & 0x3f), 0x80 | (code & 0x3f));
    }
    return bytes;
}

function utf8Decode(bytes) {
    let text = "";
    for (let index = 0; index < bytes.length; index++) {
        const byte = bytes[index];
        if (byte < 0x80) {
            text += String.fromCharCode(byte);
            continue;
        }
        let code;
        if ((byte & 0xe0) === 0xc0) {
            code = ((byte & 0x1f) << 6) | (bytes[++index] & 0x3f);
        } else if ((byte & 0xf0) === 0xe0) {
            code = ((byte & 0x0f) << 12) | ((bytes[++index] & 0x3f) << 6) | (bytes[++index] & 0x3f);
        } else if ((byte & 0xf8) === 0xf0) {
            code = ((byte & 0x07) << 18) | ((bytes[++index] & 0x3f) << 12) |
                ((bytes[++index] & 0x3f) << 6) | (bytes[++index] & 0x3f);
        } else {
            code = byte;
        }
        if (code > 0xffff) {
            code -= 0x10000;
            text += String.fromCharCode(0xd800 + (code >>> 10), 0xdc00 + (code & 0x3ff));
        } else {
            text += String.fromCharCode(code);
        }
    }
    return text;
}

function evpBytesToKey(password, salt, keyLength, ivLength) {
    const passBytes = utf8Encode(password);
    let previous = [];
    const derived = [];
    while (derived.length < keyLength + ivLength) {
        previous = md5Bytes(previous.concat(passBytes, salt));
        for (const byte of previous) derived.push(byte);
    }
    return {
        key: derived.slice(0, keyLength),
        iv: derived.slice(keyLength, keyLength + ivLength),
    };
}

function base64ToBytes(value) {
    const text = str(value).replace(/[\s\r\n]/g, "");
    const bytes = [];
    let buffer = 0;
    let bits = 0;
    for (let index = 0; index < text.length; index++) {
        if (text.charAt(index) === "=") break;
        const digit = B64.indexOf(text.charAt(index));
        if (digit < 0) continue;
        buffer = (buffer << 6) | digit;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            bytes.push((buffer >>> bits) & 0xff);
        }
    }
    return bytes;
}

function subWord(value) {
    return ((S_BOX[(value >>> 24) & 0xff] << 24) | (S_BOX[(value >>> 16) & 0xff] << 16) |
        (S_BOX[(value >>> 8) & 0xff] << 8) | S_BOX[value & 0xff]) >>> 0;
}

function rotWord(value) {
    return ((value << 8) | (value >>> 24)) >>> 0;
}

function expandKey(key) {
    const nk = key.length / 4;
    const rounds = nk + 6;
    const wordCount = 4 * (rounds + 1);
    const words = new Array(wordCount);
    for (let index = 0; index < nk; index++) {
        words[index] = ((key[4 * index] << 24) | (key[4 * index + 1] << 16) |
            (key[4 * index + 2] << 8) | key[4 * index + 3]) >>> 0;
    }
    const rcon = [0, 1];
    for (let index = 2; index < 16; index++) rcon[index] = xtime(rcon[index - 1]);
    for (let index = nk; index < wordCount; index++) {
        let temp = words[index - 1];
        if (index % nk === 0) {
            temp = (subWord(rotWord(temp)) ^ (rcon[index / nk] << 24)) >>> 0;
        } else if (nk > 6 && index % nk === 4) {
            temp = subWord(temp);
        }
        words[index] = (words[index - nk] ^ temp) >>> 0;
    }
    const roundKeys = new Uint8Array(wordCount * 4);
    for (let index = 0; index < wordCount; index++) {
        roundKeys[4 * index] = (words[index] >>> 24) & 0xff;
        roundKeys[4 * index + 1] = (words[index] >>> 16) & 0xff;
        roundKeys[4 * index + 2] = (words[index] >>> 8) & 0xff;
        roundKeys[4 * index + 3] = words[index] & 0xff;
    }
    return {roundKeys, rounds};
}

function addRoundKey(state, roundKeys, round) {
    const base = round * 16;
    for (let index = 0; index < 16; index++) state[index] ^= roundKeys[base + index];
}

function inverseShiftRows(state) {
    const temp = new Uint8Array(16);
    for (let row = 0; row < 4; row++) {
        for (let column = 0; column < 4; column++) {
            temp[row + 4 * column] = state[row + 4 * ((column - row + 4) % 4)];
        }
    }
    for (let index = 0; index < 16; index++) state[index] = temp[index];
}

function inverseSubBytes(state) {
    for (let index = 0; index < 16; index++) state[index] = INV_S_BOX[state[index]];
}

function inverseMixColumns(state) {
    for (let column = 0; column < 4; column++) {
        const index = column * 4;
        const a0 = state[index];
        const a1 = state[index + 1];
        const a2 = state[index + 2];
        const a3 = state[index + 3];
        state[index] = gfMul(a0, 14) ^ gfMul(a1, 11) ^ gfMul(a2, 13) ^ gfMul(a3, 9);
        state[index + 1] = gfMul(a0, 9) ^ gfMul(a1, 14) ^ gfMul(a2, 11) ^ gfMul(a3, 13);
        state[index + 2] = gfMul(a0, 13) ^ gfMul(a1, 9) ^ gfMul(a2, 14) ^ gfMul(a3, 11);
        state[index + 3] = gfMul(a0, 11) ^ gfMul(a1, 13) ^ gfMul(a2, 9) ^ gfMul(a3, 14);
    }
}

function decryptBlock(block, roundKeys, rounds) {
    const state = new Uint8Array(block);
    addRoundKey(state, roundKeys, rounds);
    for (let round = rounds - 1; round >= 1; round--) {
        inverseShiftRows(state);
        inverseSubBytes(state);
        addRoundKey(state, roundKeys, round);
        inverseMixColumns(state);
    }
    inverseShiftRows(state);
    inverseSubBytes(state);
    addRoundKey(state, roundKeys, 0);
    return state;
}

function aesCbcDecrypt(data, key, iv) {
    const expanded = expandKey(key);
    const output = new Uint8Array(data.length);
    let previous = iv.slice();
    for (let offset = 0; offset < data.length; offset += 16) {
        const block = new Uint8Array(16);
        for (let index = 0; index < 16; index++) block[index] = data[offset + index];
        const plain = decryptBlock(block, expanded.roundKeys, expanded.rounds);
        for (let index = 0; index < 16; index++) output[offset + index] = plain[index] ^ previous[index];
        previous = block;
    }
    return output;
}

function removePadding(bytes) {
    if (!bytes.length) return bytes;
    const padding = bytes[bytes.length - 1];
    if (padding < 1 || padding > 16) throw new Error("无效的 AES 填充");
    for (let index = bytes.length - padding; index < bytes.length; index++) {
        if (bytes[index] !== padding) throw new Error("无效的 AES 填充");
    }
    return bytes.subarray(0, bytes.length - padding);
}

function decryptResponse(cipherText) {
    const raw = base64ToBytes(cipherText);
    if (raw.length < 32) throw new Error("响应密文过短");
    const magic = String.fromCharCode(raw[0], raw[1], raw[2], raw[3], raw[4], raw[5], raw[6], raw[7]);
    if (magic !== "Salted__") throw new Error("响应格式错误: " + magic);
    const salt = raw.slice(8, 16);
    const payload = raw.slice(16);
    if (payload.length % 16 !== 0) throw new Error("密文长度错误");
    const derived = evpBytesToKey("xxx", salt, 32, 16);
    const decrypted = removePadding(aesCbcDecrypt(payload, derived.key, derived.iv));
    return JSON.parse(utf8Decode(decrypted));
}

// ------------------------------------------------------------------------

function filterRows() {
    return [
        {
            key: "sortBy", name: "排序", init: "time",
            value: [{n: "最新", v: "time"}, {n: "最热", v: "views"}],
        },
        {
            key: "filterTimeInDays", name: "发布时间", init: "all",
            value: [
                {n: "全部时间", v: "all"},
                {n: "1星期内", v: "7"},
                {n: "2星期内", v: "14"},
                {n: "1个月内", v: "30"},
                {n: "3个月内", v: "90"},
                {n: "半年内", v: "180"},
                {n: "1年内", v: "365"},
            ],
        },
        {
            key: "filterViews", name: "播放量", init: "all",
            value: [
                {n: "全部", v: "all"},
                {n: "1000+", v: "1000"},
                {n: "5000+", v: "5000"},
                {n: "10000+", v: "10000"},
                {n: "100000+", v: "100000"},
            ],
        },
        {
            key: "filterDurationInMins", name: "时长(分钟)", init: "all",
            value: [
                {n: "全部", v: "all"},
                {n: "10分钟以上", v: "10"},
                {n: "20分钟以上", v: "20"},
                {n: "30分钟以上", v: "30"},
                {n: "60分钟以上", v: "60"},
            ],
        },
    ];
}

function selectedFilters(extend) {
    const options = parseExtend(extend);
    return {
        sortBy: str(options.sortBy || "time"),
        filterTimeInDays: str(options.filterTimeInDays || "all"),
        filterViews: str(options.filterViews || "all"),
        filterDurationInMins: str(options.filterDurationInMins || "all"),
        keywordLogic: str(options.keywordLogic || "or"),
    };
}

function hasActiveFilter(selected) {
    return selected.sortBy !== "time" || selected.filterTimeInDays !== "all" ||
        selected.filterViews !== "all" || selected.filterDurationInMins !== "all";
}

export default class PornTube extends Spider {
    init(extend = "") {
        const options = parseExtend(extend);
        const customHosts = options.hosts || options.apiHosts || options.host;
        const hosts = Array.isArray(customHosts)
            ? customHosts.map((host) => str(host).replace(/\/+$/, ""))
            : customHosts ? [str(customHosts).replace(/\/+$/, "")] : DEFAULT_HOSTS;
        this.hosts = hosts.filter(Boolean);
        if (!this.hosts.length) this.hosts = DEFAULT_HOSTS.slice();
        this.app = str(options.app || DEFAULT_APP);
        this.version = str(options.version || DEFAULT_VERSION);
        this.timeout = intValue(options.timeout, DEFAULT_TIMEOUT);
        this.ua = str(options.userAgent || DEFAULT_UA);
    }

    async request(host, route, extra) {
        const body = {
            app: this.app,
            isStandalone: false,
            theLink: "novaluenull",
            uuid: "novalue",
            version: this.version,
            deviceInfo: {},
            url: route,
        };
        const values = parseExtend(extra);
        for (const key of Object.keys(values)) body[key] = values[key];

        const response = await this.net.req(host + "/js", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer undefined",
                "User-Agent": this.ua,
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://porntube.cool",
                "Referer": "https://porntube.cool/",
            },
            body: JSON.stringify(body),
            timeout: this.timeout,
            callTimeout: this.timeout,
        });
        if (response.error) throw new Error(str(response.error));
        const code = intValue(response.code, 200);
        if (code < 200 || code >= 300) throw new Error("HTTP " + code);
        let content = response.content;
        if (content == null) throw new Error("空响应");
        if (typeof content !== "string") content = JSON.stringify(content);
        let json;
        try {
            json = JSON.parse(content);
        } catch (error) {
            throw new Error("响应不是 JSON");
        }
        if (json.error) throw new Error(str(json.error));
        if (!json.r) throw new Error("响应缺少密文");
        return decryptResponse(json.r);
    }

    async api(route, extra) {
        let lastError = null;
        for (const host of this.hosts) {
            try {
                return await this.request(host, route, extra);
            } catch (error) {
                lastError = error;
            }
        }
        throw lastError || new Error("接口不可用");
    }

    homeContent(filter) {
        const result = {class: []};
        for (const item of CATEGORIES) {
            result.class.push({type_id: item[0], type_name: item[1]});
        }
        if (filter) {
            result.filters = {};
            for (const item of CATEGORIES) result.filters[item[0]] = filterRows();
        }
        return result;
    }

    async homeVideoContent() {
        return this.categoryContent("home_hot", "1", false, {});
    }

    async categoryContent(tid, pg, filter, extend) {
        const page = Math.max(1, intValue(pg, 1));
        const type = str(tid) || "hot";
        const selected = selectedFilters(extend);
        let items;
        try {
            if (hasActiveFilter(selected)) {
                const filterCategory = type.indexOf("home_") === 0 ? "all" : type;
                items = await this.api("/searchSevenVideos", {
                    page,
                    keywords: "",
                    filterCategory,
                    filterTimeInDays: selected.filterTimeInDays,
                    filterViews: selected.filterViews,
                    filterDurationInMins: selected.filterDurationInMins,
                    sortBy: selected.sortBy,
                    keywordLogic: selected.keywordLogic,
                });
            } else {
                items = await this.api("/sevenVideos?page=" + page + "&type=" + encodeURIComponent(type));
            }
        } catch (error) {
            items = [];
        }
        if (!Array.isArray(items)) items = [];
        const list = videoCards(items);
        return {
            page,
            pagecount: pageCount(list, page),
            limit: PAGE_SIZE,
            total: list.length,
            list,
        };
    }

    async detailContent(ids) {
        const result = [];
        const list = Array.isArray(ids) ? ids : [ids];
        for (const rawId of list) {
            const id = str(rawId);
            if (!id) continue;
            let detail;
            try {
                detail = await this.api("/sevenVideos/" + encodeURIComponent(id), {url_search: ""});
            } catch (error) {
                detail = null;
            }
            if (!detail || typeof detail !== "object" || !(detail.id || detail.vId)) {
                // 影片不存在或接口失败：保留条目但返回空播放来源
                result.push({
                    vod_id: id,
                    vod_name: id,
                    vod_pic: "",
                    vod_play_from: "",
                    vod_play_url: "",
                });
                continue;
            }

            const videoId = str(detail.id || detail.vId || id);
            const base = normalizeVideo(detail);
            if (!base) continue;
            delete base._raw;

            const author = str(detail.user || detail.user_en || "");
            const authorLink = author ? link(author, {
                id: "user_" + author,
                name: author,
                type_flag: "1",
            }) : "";
            base.vod_id = videoId;
            base.vod_actor = authorLink;
            base.vod_director = author;

            let related = [];
            if (author) {
                try {
                    const rows = await this.api("/searchSevenVideos", {
                        page: 1,
                        keywords: "user_" + author,
                        filterCategory: "all",
                        filterTimeInDays: "all",
                        filterViews: "all",
                        filterDurationInMins: "all",
                        sortBy: "time",
                        keywordLogic: "or",
                    });
                    if (Array.isArray(rows)) {
                        related = videoCards(rows).filter((item) => item.vod_id !== videoId).slice(0, 18);
                    }
                } catch (error) {
                    related = [];
                }
            }

            const mainLine = cleanEpisodeName(detail.title || videoId) + "$" + videoId;
            const relatedLine = related.map((item) =>
                cleanEpisodeName(item.vod_name) + "$" + item.vod_id).join("#");
            base.vod_play_from = relatedLine ? "正片$$$相关推荐（同作者）" : "正片";
            base.vod_play_url = relatedLine ? mainLine + "$$$" + relatedLine : mainLine;
            result.push(base);
        }
        return {list: result};
    }

    async searchContent(key, quick, pg = "1") {
        const page = Math.max(1, intValue(pg, 1));
        const keyword = str(key).trim();
        if (!keyword) {
            return {page, pagecount: page, limit: PAGE_SIZE, total: 0, list: []};
        }
        let items;
        try {
            items = await this.api("/searchSevenVideos", {
                page,
                keywords: keyword,
                filterCategory: "all",
                filterTimeInDays: "all",
                filterViews: "all",
                filterDurationInMins: "all",
                sortBy: "time",
                keywordLogic: "or",
            });
        } catch (error) {
            items = [];
        }
        if (!Array.isArray(items)) items = [];
        const list = videoCards(items);
        return {
            page,
            pagecount: pageCount(list, page),
            limit: PAGE_SIZE,
            total: list.length,
            list,
        };
    }

    // 签名直链有时效，播放时重新请求详情，绝不复用详情页缓存的 m3u8。
    async playerContent(flag, id, vipFlags) {
        const videoId = str(id);
        if (!videoId) return {parse: 0, url: "", msg: "无效的播放 ID"};
        let detail;
        try {
            detail = await this.api("/sevenVideos/" + encodeURIComponent(videoId), {url_search: ""});
        } catch (error) {
            return {parse: 0, url: "", msg: "播放地址获取失败"};
        }
        let urls = [];
        if (detail && Array.isArray(detail.m3u8s)) urls = detail.m3u8s;
        else if (detail && detail.m3u8) urls = [detail.m3u8];
        urls = urls.map((url) => str(url)).filter((url) => /^https?:\/\//i.test(url));
        if (!urls.length) return {parse: 0, url: "", msg: "未找到可用的 m3u8 直链"};
        return {
            parse: 0,
            jx: 0,
            url: urls[0],
            header: {
                "User-Agent": this.ua,
                "Referer": "https://porntube.cool/",
                "Origin": "https://porntube.cool",
            },
        };
    }

    async proxy(params) {
        const options = parseExtend(params);
        const url = str(options.url || params);
        if (!/^https?:\/\//i.test(url)) return [400, "text/plain", "invalid url"];
        try {
            const response = await this.net.req(url, {
                method: "GET",
                headers: {
                    "User-Agent": this.ua,
                    "Referer": "https://porntube.cool/",
                },
                timeout: this.timeout,
                callTimeout: this.timeout,
                buffer: 1,
            });
            const code = intValue(response.code, 200);
            if (response.error) return [500, "text/plain", str(response.error)];
            const contentType = str(response.headers && (response.headers["Content-Type"] ||
                response.headers["content-type"])) || "application/octet-stream";
            return [code, contentType, response.content == null ? "" : response.content];
        } catch (error) {
            return [500, "text/plain", str(error && error.message ? error.message : error)];
        }
    }

    home(filter) { return this.homeContent(filter); }
    homeVod() { return this.homeVideoContent(); }
    category(tid, pg, filter, extend) { return this.categoryContent(tid, pg, filter, extend); }
    detail(id) { return this.detailContent(Array.isArray(id) ? id : [id]); }
    search(wd, quick, pg) { return this.searchContent(wd, quick, pg); }
    play(flag, id, vipFlags) { return this.playerContent(flag, id, vipFlags); }
}
