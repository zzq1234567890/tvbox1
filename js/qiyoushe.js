// 妻友社 v1.0.0 -> FongMi / 影视TV QuickJS spider
// Site config: {"key":"qiyou","name":"妻友社","type":3,"api":"./QiyouShe.js","ext":{}}
//
// ext 可选：
// {
//   "host": "https://d1kmvkv4iwtiup.cloudfront.net",
//   "imageHost": "https://qiyouimage.arpuum.cn/",
//   "worker": "https://your-worker.example.com/poster",
//   "timeout": 20000,
//   "ua": "Mozilla/5.0 ...",
//   "devID": "fongmi-qiyou"
// }
//
// 说明：
// 1. 接口响应为 salt(12) + AES-256-CBC，本文件纯 JS 实现 SHA256 / AES / HMAC-SHA1，不依赖 CryptoJS。
// 2. 游客登录 + 请求签名即可读取全部接口；VIP/付费影片由服务端签发完整 HLS 直链，无需登录/购买。
// 3. 海报前 100 字节被异或加密（密钥 2019ysapp7527），本文件通过 proxy 解密后交给播放器显示。
//    若 ext.worker 有值，则改用外部 Worker；支持 {img}/{url} 占位符，否则追加 img/url 查询参数。
// 4. 详情页两条线：正片 + 相关推荐；失效/不存在的影片保留条目但返回空播放来源。
// 5. 代理规则建议（Clash/TUN 或路由器级代理）：
//    DOMAIN-SUFFIX,cloudfront.net,PROXY
//    DOMAIN-SUFFIX,gcwe44p.com,PROXY
//    DOMAIN-SUFFIX,arpuum.cn,PROXY

import {Spider, link} from "catvod";

const DEFAULT_HOST = "https://d1kmvkv4iwtiup.cloudfront.net";
const DEFAULT_IMAGE_HOST = "https://qiyouimage.arpuum.cn/";
const DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";
const DEFAULT_TIMEOUT = 20000;
const RESPONSE_KEY = "vEukA&w15z4VAD3kAY#fkL#rBnU!WDhN";
const REQUEST_KEY = "gH3nA7fR9tV1jY6z";
const SALT_LENGTH = 12;
const IMAGE_XOR_KEY = "2019ysapp7527";
const IMAGE_XOR_LENGTH = 100;
const PAGE_SIZE = 20;
const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

// 13 个分类；sorts 依次对应：热门推荐、最新上架、最多观看、最多收藏。
// 部分分类服务端没有完全同名的排序，使用最接近的官方排序值。
const CATEGORIES = [
    {id: "376401", name: "最新", sorts: ["1", "2", "3", "4"]},
    {id: "342081", name: "推荐", sorts: ["1", "2", "3", "4"]},
    {id: "342083", name: "国产", sorts: ["1", "2", "6", "4"]},
    {id: "696021", name: "换妻原创", sorts: ["1", "2", "3", "4"]},
    {id: "342082", name: "乱伦", sorts: ["1", "2", "3", "4"]},
    {id: "342088", name: "AV", sorts: ["1", "2", "3", "4"]},
    {id: "717241", name: "AI漫剧", sorts: ["1", "2", "3", "4"]},
    {id: "342089", name: "传媒", sorts: ["1", "2", "3", "6"]},
    {id: "342085", name: "网黄", sorts: ["1", "2", "6", "4"]},
    {id: "19201", name: "动漫", sorts: ["1", "2", "3", "4"]},
    {id: "159061", name: "欧美", sorts: ["1", "2", "3", "6"]},
    {id: "696261", name: "重口", sorts: ["1", "2", "3", "6"]},
    {id: "696281", name: "禁片", sorts: ["1", "2", "3", "5"]},
];
const SORT_NAMES = ["热门推荐", "最新上架", "最多观看", "最多收藏"];

function str(value) {
    if (value == null) return "";
    return String(value);
}

function intValue(value, fallback) {
    const number = parseInt(value, 10);
    return isFinite(number) ? number : fallback;
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

function clean(text) {
    return str(text)
        .replace(/[\r\n]+/g, " ")
        .replace(/\$/g, " ")
        .replace(/#/g, " ")
        .replace(/\s+/g, " ")
        .trim();
}

function episodeName(text) {
    return clean(text) || "正片";
}

function durationText(seconds) {
    const total = intValue(seconds, 0);
    if (total <= 0) return "";
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    if (hours) return hours + ":" + String(minutes).padStart(2, "0") + ":" + String(secs).padStart(2, "0");
    return String(minutes).padStart(2, "0") + ":" + String(secs).padStart(2, "0");
}

function countText(value) {
    const number = intValue(value, 0);
    if (number >= 100000000) return (number / 100000000).toFixed(1).replace(/\.0$/, "") + "亿";
    if (number >= 10000) return (number / 10000).toFixed(1).replace(/\.0$/, "") + "万";
    return String(number);
}

function payText(value) {
    const type = intValue(value, 0);
    if (type === 1) return "VIP";
    if (type === 2) return "付费";
    return "免费";
}

function yearOf(value) {
    const match = str(value).match(/(19|20)\d{2}/);
    return match ? match[0] : "";
}

function topicText(value) {
    if (!Array.isArray(value)) return "";
    const names = [];
    for (const item of value) {
        if (typeof item === "string") names.push(item);
        else if (item && typeof item === "object") names.push(str(item.name || item.title || item.tagName || ""));
    }
    return names.filter(Boolean).join(",");
}

function utf8Encode(text) {
    const bytes = [];
    const source = str(text);
    for (let index = 0; index < source.length; index++) {
        const code = source.charCodeAt(index);
        if (code < 0x80) bytes.push(code);
        else if (code < 0x800) bytes.push(0xc0 | (code >>> 6), 0x80 | (code & 0x3f));
        else if (code >= 0xd800 && code <= 0xdbff && index + 1 < source.length) {
            const next = source.charCodeAt(++index);
            const point = 0x10000 + ((code - 0xd800) << 10) + (next - 0xdc00);
            bytes.push(0xf0 | (point >>> 18), 0x80 | ((point >>> 12) & 0x3f),
                0x80 | ((point >>> 6) & 0x3f), 0x80 | (point & 0x3f));
        } else {
            bytes.push(0xe0 | (code >>> 12), 0x80 | ((code >>> 6) & 0x3f), 0x80 | (code & 0x3f));
        }
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
        let point;
        if ((byte & 0xe0) === 0xc0) point = ((byte & 0x1f) << 6) | (bytes[++index] & 0x3f);
        else if ((byte & 0xf0) === 0xe0) point = ((byte & 0x0f) << 12) | ((bytes[++index] & 0x3f) << 6) | (bytes[++index] & 0x3f);
        else if ((byte & 0xf8) === 0xf0) point = ((byte & 0x07) << 18) | ((bytes[++index] & 0x3f) << 12) |
            ((bytes[++index] & 0x3f) << 6) | (bytes[++index] & 0x3f);
        else point = byte;
        if (point > 0xffff) {
            point -= 0x10000;
            text += String.fromCharCode(0xd800 + (point >>> 10), 0xdc00 + (point & 0x3ff));
        } else {
            text += String.fromCharCode(point);
        }
    }
    return text;
}

function bytesToHex(bytes) {
    let text = "";
    for (let index = 0; index < bytes.length; index++) text += ("0" + (bytes[index] & 0xff).toString(16)).slice(-2);
    return text;
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

const SHA256_K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

function rotr(value, count) {
    return ((value >>> count) | (value << (32 - count))) >>> 0;
}

function rotl(value, count) {
    return ((value << count) | (value >>> (32 - count))) >>> 0;
}

function sha256Bytes(input) {
    const message = Array.prototype.slice.call(input);
    const bitLength = message.length * 8;
    message.push(0x80);
    while (message.length % 64 !== 56) message.push(0);
    const high = Math.floor(bitLength / 4294967296) >>> 0;
    const low = bitLength >>> 0;
    message.push((high >>> 24) & 0xff, (high >>> 16) & 0xff, (high >>> 8) & 0xff, high & 0xff,
        (low >>> 24) & 0xff, (low >>> 16) & 0xff, (low >>> 8) & 0xff, low & 0xff);

    let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a;
    let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;
    const words = new Array(64);

    for (let offset = 0; offset < message.length; offset += 64) {
        for (let index = 0; index < 16; index++) {
            const position = offset + index * 4;
            words[index] = ((message[position] << 24) | (message[position + 1] << 16) |
                (message[position + 2] << 8) | message[position + 3]) >>> 0;
        }
        for (let index = 16; index < 64; index++) {
            const s0 = rotr(words[index - 15], 7) ^ rotr(words[index - 15], 18) ^ (words[index - 15] >>> 3);
            const s1 = rotr(words[index - 2], 17) ^ rotr(words[index - 2], 19) ^ (words[index - 2] >>> 10);
            words[index] = (words[index - 16] + s0 + words[index - 7] + s1) >>> 0;
        }
        let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
        for (let index = 0; index < 64; index++) {
            const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
            const ch = (e & f) ^ (~e & g);
            const t1 = (h + S1 + ch + SHA256_K[index] + words[index]) >>> 0;
            const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
            const majority = (a & b) ^ (a & c) ^ (b & c);
            const t2 = (S0 + majority) >>> 0;
            h = g; g = f; f = e; e = (d + t1) >>> 0;
            d = c; c = b; b = a; a = (t1 + t2) >>> 0;
        }
        h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0;
        h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + h) >>> 0;
    }
    const result = [];
    for (const word of [h0, h1, h2, h3, h4, h5, h6, h7]) {
        result.push((word >>> 24) & 0xff, (word >>> 16) & 0xff, (word >>> 8) & 0xff, word & 0xff);
    }
    return result;
}

const SHA1_K = [0x5a827999, 0x6ed9eba1, 0x8f1bbcdc, 0xca62c1d6];

function sha1Bytes(input) {
    const message = Array.prototype.slice.call(input);
    const bitLength = message.length * 8;
    message.push(0x80);
    while (message.length % 64 !== 56) message.push(0);
    const high = Math.floor(bitLength / 4294967296) >>> 0;
    const low = bitLength >>> 0;
    message.push((high >>> 24) & 0xff, (high >>> 16) & 0xff, (high >>> 8) & 0xff, high & 0xff,
        (low >>> 24) & 0xff, (low >>> 16) & 0xff, (low >>> 8) & 0xff, low & 0xff);
    let h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476, h4 = 0xc3d2e1f0;
    const words = new Array(80);
    for (let offset = 0; offset < message.length; offset += 64) {
        for (let index = 0; index < 16; index++) {
            const position = offset + index * 4;
            words[index] = ((message[position] << 24) | (message[position + 1] << 16) |
                (message[position + 2] << 8) | message[position + 3]) >>> 0;
        }
        for (let index = 16; index < 80; index++) {
            words[index] = rotl(words[index - 3] ^ words[index - 8] ^ words[index - 14] ^ words[index - 16], 1) >>> 0;
        }
        let a = h0, b = h1, c = h2, d = h3, e = h4;
        for (let index = 0; index < 80; index++) {
            let mix;
            let key;
            if (index < 20) { mix = (b & c) | (~b & d); key = SHA1_K[0]; }
            else if (index < 40) { mix = b ^ c ^ d; key = SHA1_K[1]; }
            else if (index < 60) { mix = (b & c) | (b & d) | (c & d); key = SHA1_K[2]; }
            else { mix = b ^ c ^ d; key = SHA1_K[3]; }
            const temp = (rotl(a, 5) + mix + e + key + words[index]) >>> 0;
            e = d; d = c; c = rotl(b, 30) >>> 0; b = a; a = temp;
        }
        h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0; h4 = (h4 + e) >>> 0;
    }
    const result = [];
    for (const word of [h0, h1, h2, h3, h4]) {
        result.push((word >>> 24) & 0xff, (word >>> 16) & 0xff, (word >>> 8) & 0xff, word & 0xff);
    }
    return result;
}

function hmacSha1Bytes(key, data) {
    let keyBytes = Array.prototype.slice.call(key);
    if (keyBytes.length > 64) keyBytes = sha1Bytes(keyBytes);
    while (keyBytes.length < 64) keyBytes.push(0);
    const inner = [];
    const outer = [];
    for (let index = 0; index < 64; index++) {
        inner.push(keyBytes[index] ^ 0x36);
        outer.push(keyBytes[index] ^ 0x5c);
    }
    return sha1Bytes(outer.concat(sha1Bytes(inner.concat(Array.prototype.slice.call(data)))));
}

function hmacSha1Hex(keyText, dataText) {
    return bytesToHex(hmacSha1Bytes(utf8Encode(keyText), utf8Encode(dataText)));
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
    for (let candidate = 1; candidate < 256; candidate++) if (gfMul(value, candidate) === 1) return candidate;
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
        if (index % nk === 0) temp = (subWord(rotWord(temp)) ^ (rcon[index / nk] << 24)) >>> 0;
        else if (nk > 6 && index % nk === 4) temp = subWord(temp);
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
        const a0 = state[index], a1 = state[index + 1], a2 = state[index + 2], a3 = state[index + 3];
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
    if (!bytes.length) throw new Error("响应明文为空");
    const padding = bytes[bytes.length - 1];
    if (padding < 1 || padding > 16) throw new Error("AES 填充无效");
    for (let index = bytes.length - padding; index < bytes.length; index++) {
        if (bytes[index] !== padding) throw new Error("AES 填充无效");
    }
    return bytes.subarray(0, bytes.length - padding);
}

function deriveKeyIv(salt) {
    const seed = utf8Encode(RESPONSE_KEY).concat(Array.prototype.slice.call(salt));
    const half = Math.floor(seed.length / 2);
    const middle = sha256Bytes(seed).slice(8, 24);
    const leftInput = middle.concat(seed.slice(0, half));
    const rightInput = seed.slice(half).concat(middle);
    const left = sha256Bytes(leftInput);
    const right = sha256Bytes(rightInput);
    return {
        key: left.slice(0, 8).concat(right.slice(8, 24), left.slice(24, 32)),
        iv: right.slice(0, 4).concat(left.slice(12, 20), right.slice(28, 32)),
    };
}

function decryptResponse(cipherText) {
    const all = base64ToBytes(cipherText);
    if (all.length <= SALT_LENGTH) throw new Error("响应密文过短");
    const salt = all.slice(0, SALT_LENGTH);
    const body = all.slice(SALT_LENGTH);
    const derived = deriveKeyIv(salt);
    return utf8Decode(removePadding(aesCbcDecrypt(body, derived.key, derived.iv)));
}

function uuid() {
    const hex = "0123456789abcdef";
    const bytes = [];
    for (let index = 0; index < 36; index++) bytes[index] = hex.charAt(Math.floor(Math.random() * 16));
    bytes[14] = "4";
    bytes[19] = hex.charAt((parseInt(bytes[19], 16) & 3) | 8);
    bytes[8] = bytes[13] = bytes[18] = bytes[23] = "-";
    return bytes.join("");
}

function jwtExpiration(token) {
    const parts = str(token).split(".");
    if (parts.length < 2) return 0;
    try {
        const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
        const json = JSON.parse(utf8Decode(base64ToBytes(payload)));
        return intValue(json.exp, 0) * 1000;
    } catch (error) {
        return 0;
    }
}

function signedM3u8Url(host, token, videoUrl) {
    const path = "/api/app/media/h5/m3u8/" + str(videoUrl).replace(/^\/+/, "");
    const timestamp = Math.floor(Date.now() / 1000);
    const nonce = uuid();
    const sign = hmacSha1Hex(REQUEST_KEY, token + "&" + path + "&&" + timestamp + "&" + nonce);
    return host + path + "?token=" + token + "&timestamp=" + timestamp + "&sign=" + sign + "&nonce=" + nonce;
}

function filterRows(category) {
    return [{
        key: "sort",
        name: "排序",
        init: category.sorts[0],
        value: SORT_NAMES.map((name, index) => ({n: name, v: category.sorts[index]})),
    }];
}

export class QiyouShe extends Spider {
    async init(extend) {
        const ext = parseExtend(extend);
        this.host = str(ext.host || ext.apiHost || ext.api || DEFAULT_HOST).replace(/\/+$/, "");
        this.imageHost = str(ext.imageHost || ext.image || DEFAULT_IMAGE_HOST);
        this.worker = str(ext.worker || ext.imageWorker || ext.posterWorker || "");
        this.ua = str(ext.ua || DEFAULT_UA);
        this.timeout = intValue(ext.timeout, DEFAULT_TIMEOUT);
        this.devID = str(ext.devID || ext.devid || "fongmi-qiyou");
        this.token = "";
        this.tokenExp = 0;
    }

    async rawRequest(apiPath, body, token) {
        const timestamp = Math.floor(Date.now() / 1000);
        const nonce = uuid();
        const signData = token + "&" + apiPath + "&" + this.ua + "&" + timestamp + "&" + nonce;
        const apiKey = "timestamp=" + timestamp + ";sign=" + hmacSha1Hex(REQUEST_KEY, signData) + ";nonce=" + nonce;
        const response = await this.net.req(this.host + apiPath, {
            method: "POST",
            headers: {
                "Content-Type": "application/json;charset=UTF-8",
                "User-Agent": this.ua,
                "X-User-Agent": this.ua,
                "Authorization": token,
                "x-api-key": apiKey,
                "qiyou.authSessionEpoch": "",
                "qiyou.authRequestCredentialScope": "",
                "Origin": this.host,
                "Referer": this.host + "/",
                "Accept": "application/json, text/plain, */*",
            },
            body: JSON.stringify(body == null ? {} : body),
            timeout: this.timeout,
            callTimeout: this.timeout,
        });
        if (response.error) throw new Error(str(response.error));
        const httpCode = intValue(response.code, 200);
        if (httpCode < 200 || httpCode >= 300) throw new Error("HTTP " + httpCode);
        let content = response.content;
        if (content == null) throw new Error("接口返回为空");
        if (typeof content !== "string") content = str(content);
        let outer;
        try {
            outer = JSON.parse(content);
        } catch (error) {
            throw new Error("接口返回不是 JSON");
        }
        const result = {
            code: intValue(outer.code, 0),
            msg: str(outer.msg || ""),
            tip: str(outer.tip || ""),
            data: outer.data == null ? null : outer.data,
        };
        if (typeof result.data === "string") {
            result.data = JSON.parse(decryptResponse(result.data));
        }
        return result;
    }

    async ensureToken() {
        if (this.token && this.tokenExp > Date.now() + 60000) return this.token;
        const result = await this.rawRequest("/api/app/login/guest", {
            devID: this.devID,
            affCode: "{}",
        }, "");
        if (result.code !== 200 || !result.data || !result.data.token) {
            throw new Error("游客登录失败: " + (result.msg || result.code));
        }
        this.token = str(result.data.token);
        const expiration = jwtExpiration(this.token);
        this.tokenExp = expiration > Date.now() ? expiration : Date.now() + 12 * 3600 * 1000;
        return this.token;
    }

    async request(apiPath, body, retry) {
        const shouldRetry = retry !== false;
        let token;
        try {
            token = await this.ensureToken();
        } catch (error) {
            if (!shouldRetry) throw error;
            this.token = "";
            this.tokenExp = 0;
            token = await this.ensureToken();
        }
        let result;
        try {
            result = await this.rawRequest(apiPath, body, token);
        } catch (error) {
            if (!shouldRetry) throw error;
            this.token = "";
            this.tokenExp = 0;
            return this.request(apiPath, body, false);
        }
        const invalid = result.code === 1000 || result.code === 401 || result.code === 6015 ||
            /非法请求|登录|token|签名/i.test(result.msg);
        if (invalid && shouldRetry) {
            this.token = "";
            this.tokenExp = 0;
            return this.request(apiPath, body, false);
        }
        return result;
    }

    poster(cover) {
        const path = str(cover);
        if (!path) return "";
        if (/^https?:\/\//i.test(path)) return path;
        const encoded = encodeURIComponent(path);
        const absolute = this.imageHost.replace(/\/+$/, "") + "/" + path.replace(/^\/+/, "");
        if (this.worker) {
            const placeholder = /\{(img|url)\}/i.test(this.worker);
            if (placeholder) {
                return this.worker.replace(/\{img\}/gi, encoded).replace(/\{url\}/gi, encodeURIComponent(absolute));
            }
            const separator = this.worker.indexOf("?") >= 0 ? "&" : "?";
            return this.worker + separator + "img=" + encoded + "&url=" + encodeURIComponent(absolute);
        }
        if (typeof this.proxyUrl !== "function") return "";
        try {
            return this.proxyUrl({type: "image", img: path});
        } catch (error) {
            return "";
        }
    }

    card(item) {
        if (!item || typeof item !== "object") return null;
        const id = str(item.id || item.vId || item.videoId);
        if (!id) return null;
        const publisher = item.publisher && typeof item.publisher === "object" ? item.publisher : {};
        const author = clean(publisher.name || item.author || "");
        const duration = durationText(item.playTime || item.duration);
        const views = countText(item.watchTimes || item.watchNum || item.views);
        const remarks = [duration ? duration : "", views ? views + "次观看" : "", payText(item.payType)].filter(Boolean).join(" · ");
        const authorLink = author ? link(author, {id: "author_" + author, name: author, type_flag: "1"}) : "";
        return {
            vod_id: id,
            vod_name: clean(item.title || item.name || id),
            vod_type: clean(item.categoryName || ""),
            vod_pic: this.poster(item.coverImg || item.cover || item.img || ""),
            vod_remarks: remarks,
            vod_actor: authorLink,
            vod_director: author,
            vod_tag: topicText(item.tagInfoList || item.topics || item.tags),
            vod_year: yearOf(item.addedTime || item.createdAt || ""),
            vod_content: clean(item.desc || item.title || ""),
            vod_play_from: "",
            vod_play_url: "",
            _raw: item,
        };
    }

    cards(items) {
        if (!Array.isArray(items)) return [];
        const result = [];
        for (const item of items) {
            const card = this.card(item);
            if (card) result.push(card);
        }
        return result;
    }

    homeContent(filter) {
        const result = {class: []};
        for (const category of CATEGORIES) {
            result.class.push({type_id: category.id, type_name: category.name});
        }
        if (filter) {
            result.filters = {};
            for (const category of CATEGORIES) result.filters[category.id] = filterRows(category);
        }
        return result;
    }

    homeVideoContent() {
        return this.categoryContent(CATEGORIES[0].id, "1", false, {});
    }

    async categoryContent(tid, pg, filter, extend) {
        const page = Math.max(1, intValue(pg, 1));
        const category = CATEGORIES.find((item) => item.id === str(tid)) || CATEGORIES[0];
        const selected = parseExtend(extend);
        const requested = str(selected.sort || category.sorts[0]);
        const sort = category.sorts.indexOf(requested) >= 0 ? requested : category.sorts[0];
        let items = [];
        try {
            const result = await this.request("/api/app/media/home", {
                id: intValue(category.id, 0),
                sort: intValue(sort, 1),
                pageNum: page,
                pageSize: PAGE_SIZE,
            });
            const data = result.data && typeof result.data === "object" ? result.data : {};
            items = data.mediaList || [];
        } catch (error) {
            items = [];
        }
        const list = this.cards(items);
        return {
            page,
            pagecount: list.length >= PAGE_SIZE ? page + 1 : page,
            limit: PAGE_SIZE,
            total: list.length,
            list,
        };
    }

    async relatedItems(media, data) {
        const attempts = [];
        const gather = data && data.recommendGather;
        let gatherItems = [];
        if (Array.isArray(gather)) gatherItems = gather;
        else if (gather && typeof gather === "object") gatherItems = gather.mediaList || gather.list || [];
        if (Array.isArray(gatherItems) && gatherItems.length) attempts.push({items: gatherItems});

        const tags = [];
        if (Array.isArray(media.tagInfoList)) tags.push(...media.tagInfoList);
        if (Array.isArray(media.topics)) tags.push(...media.topics);
        for (const tag of tags) {
            const tagId = tag && typeof tag === "object" ? str(tag.id || tag.tagId || "") : "";
            if (!tagId) continue;
            attempts.push({
                path: "/api/app/media/tag/details",
                body: {
                    contentType: intValue(media.contentType, 1) || 1,
                    sort: 1,
                    id: intValue(tagId, 0),
                    pageNum: 1,
                    pageSize: 18,
                },
            });
            break;
        }
        const categoryId = intValue(media.categoryId, 0);
        if (categoryId) {
            attempts.push({
                path: "/api/app/media/home",
                body: {id: categoryId, sort: 1, pageNum: 1, pageSize: 18},
            });
        }
        attempts.push({path: "/api/app/media/short/recommend", body: {pageNum: 1, pageSize: 18, type: null}});

        const currentId = str(media.id || "");
        const seen = {};
        const result = [];
        for (const attempt of attempts) {
            let items = attempt.items || [];
            if (!items.length && attempt.path) {
                try {
                    const response = await this.request(attempt.path, attempt.body);
                    const payload = response.data && typeof response.data === "object" ? response.data : {};
                    items = payload.mediaList || [];
                } catch (error) {
                    items = [];
                }
            }
            for (const card of this.cards(items)) {
                if (card.vod_id === currentId || seen[card.vod_id]) continue;
                seen[card.vod_id] = true;
                result.push(card);
                if (result.length >= 18) return result;
            }
            if (result.length) return result;
        }
        return result;
    }

    async detailContent(ids) {
        const result = [];
        const values = Array.isArray(ids) ? ids : [ids];
        for (const rawId of values) {
            const id = str(rawId);
            if (!id) continue;
            let payload = null;
            try {
                payload = await this.request("/api/app/media/play", {
                    id: /^\d+$/.test(id) ? intValue(id, 0) : id,
                    isCollet: false,
                });
            } catch (error) {
                payload = null;
            }
            const data = payload && payload.data && typeof payload.data === "object" ? payload.data : {};
            const media = data.mediaInfo && typeof data.mediaInfo === "object" ? data.mediaInfo : null;
            if (!media || !media.videoUrl) {
                result.push({
                    vod_id: id,
                    vod_name: id,
                    vod_pic: "",
                    vod_play_from: "",
                    vod_play_url: "",
                });
                continue;
            }
            const card = this.card(media);
            if (!card) continue;
            delete card._raw;
            const videoId = str(media.id || id);
            card.vod_id = videoId;
            card.vod_content = clean(media.desc || media.title || "") || card.vod_name;

            const related = await this.relatedItems(media, data);

            const mainLine = "正片$" + videoId;
            const relatedLine = related.map((item) => episodeName(item.vod_name) + "$" + item.vod_id).join("#");
            card.vod_play_from = relatedLine ? "正片$$$相关推荐" : "正片";
            card.vod_play_url = relatedLine ? mainLine + "$$$" + relatedLine : mainLine;
            result.push(card);
        }
        return {list: result};
    }

    async searchContent(key, quick, pg = "1") {
        const page = Math.max(1, intValue(pg, 1));
        const keyword = clean(key);
        if (!keyword) return {page, pagecount: page, limit: PAGE_SIZE, total: 0, list: []};
        const bodies = [
            {content: keyword, mediaType: 1, sort: 0, pageNum: page, pageSize: PAGE_SIZE},
            {content: keyword, mediaType: 2, sort: 0, pageNum: page, pageSize: PAGE_SIZE},
        ];
        const all = [];
        let hasMore = false;
        for (const body of bodies) {
            try {
                const result = await this.request("/api/app/search/details", body);
                const data = result.data && typeof result.data === "object" ? result.data : {};
                const items = data.mediaList || [];
                if (items.length >= PAGE_SIZE) hasMore = true;
                for (const item of items) all.push(item);
            } catch (error) {
                // 单个搜索类型失败不影响另一个类型
            }
        }
        const seen = {};
        const list = [];
        for (const card of this.cards(all)) {
            if (seen[card.vod_id]) continue;
            seen[card.vod_id] = true;
            list.push(card);
        }
        return {
            page,
            pagecount: hasMore ? page + 1 : page,
            limit: PAGE_SIZE,
            total: list.length,
            list,
        };
    }

    // 直链签名有时效，播放时重新请求详情现取现用。
    async playerContent(flag, id, vipFlags) {
        const videoId = str(id);
        if (!/^\d+$/.test(videoId)) return {parse: 0, url: "", msg: "无效的播放 ID"};
        let payload;
        try {
            payload = await this.request("/api/app/media/play", {
                id: intValue(videoId, 0),
                isCollet: false,
            });
        } catch (error) {
            return {parse: 0, url: "", msg: "播放信息获取失败"};
        }
        const data = payload && payload.data && typeof payload.data === "object" ? payload.data : {};
        const media = data.mediaInfo && typeof data.mediaInfo === "object" ? data.mediaInfo : null;
        const videoUrl = media && media.videoUrl ? str(media.videoUrl) : "";
        if (!videoUrl) return {parse: 0, url: "", msg: "未找到可用的 m3u8 直链"};
        const token = this.token || await this.ensureToken();
        const url = signedM3u8Url(this.host, token, videoUrl);
        return {
            parse: 0,
            jx: 0,
            url,
            header: {
                "User-Agent": this.ua,
                "X-User-Agent": this.ua,
                "Referer": this.host + "/",
                "Origin": this.host,
            },
        };
    }

    async proxy(params) {
        const options = parseExtend(params);
        const type = str(options.type || "");
        const image = str(options.img || options.path || (type === "image" ? options.url : ""));
        if (!image && !options.url) return [400, "text/plain", "missing image"];
        const path = image || str(options.url);
        const absolute = /^https?:\/\//i.test(path);
        const url = absolute ? path : this.imageHost.replace(/\/+$/, "") + "/" + path.replace(/^\/+/, "");
        let response;
        try {
            response = await this.net.req(url, {
                method: "GET",
                headers: {
                    "User-Agent": this.ua,
                    "X-User-Agent": this.ua,
                    "Referer": this.host + "/",
                },
                timeout: this.timeout,
                callTimeout: this.timeout,
                buffer: 3,
            });
        } catch (error) {
            return [500, "text/plain", str(error && error.message ? error.message : error)];
        }
        if (response.error) return [500, "text/plain", str(response.error)];
        const code = intValue(response.code, 200);
        if (code < 200 || code >= 300) return [code, "text/plain", "image HTTP " + code];
        let body = response.content;
        if (body instanceof ArrayBuffer) body = new Uint8Array(body);
        else if (Array.isArray(body)) body = new Uint8Array(body);
        else if (body && typeof body === "object" && body.buffer && body.byteLength != null) {
            body = new Uint8Array(body.buffer, body.byteOffset || 0, body.byteLength);
        } else return [500, "text/plain", "invalid image body"];
        if (!absolute && body.length > 1 && body[0] !== 0xff && body[1] !== 0xd8) {
            const limit = Math.min(IMAGE_XOR_LENGTH, body.length);
            for (let index = 0; index < limit; index++) {
                body[index] ^= IMAGE_XOR_KEY.charCodeAt(index % IMAGE_XOR_KEY.length);
            }
        }
        const headers = response.headers || {};
        let contentType = str(headers["Content-Type"] || headers["content-type"] || "image/jpeg");
        if (contentType.indexOf("application/octet-stream") >= 0) contentType = "image/jpeg";
        return [code, contentType, body, {"Cache-Control": "public, max-age=86400"}];
    }

    destroy() {
        this.token = "";
        this.tokenExp = 0;
    }

    home(filter) { return this.homeContent(filter); }
    homeVod() { return this.homeVideoContent(); }
    category(tid, pg, filter, extend) { return this.categoryContent(tid, pg, filter, extend); }
    detail(id) { return this.detailContent(Array.isArray(id) ? id : [id]); }
    search(wd, quick, pg) { return this.searchContent(wd, quick, pg); }
    play(flag, id, vipFlags) { return this.playerContent(flag, id, vipFlags); }
}

export default QiyouShe;
