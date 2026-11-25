import * as catvod from 'catvod';

// 新版 FongMi 的 catvod 模块同时导出 Spider 与 net。net.stream() 才是大文件
// proxy 的正确姿势：JS 先快速返回，Java 按 1MB 大块 pull，减少跨界回调卡顿。
const Spider = catvod.Spider || (catvod.default && catvod.default.Spider);
const NET = catvod.net || (catvod.default && catvod.default.net) || null;

// 红果短剧 —— HGTV.py (5985 行) 移植为 FongMi / TVBox type 3 JS。
// 分类/搜索/详情：官网 hongguoduanju.com 的 _ROUTER_DATA / 搜索 API。
// 播放：注册匿名设备 -> Android v5 签名取 video_model（公开无签名入口已空）
//       -> 下载加密 MP4 -> 纯 JS 完成 CENC(AES-128-CTR) 解密与 moov 盒修复
//       -> proxy 返回解密后的 MP4。
// JS 无本地 HTTP 服务器，改用模块级渐进式明文缓冲：
// 并行预取开头几 MB 并解密后立即返回播放地址，其余在后台补齐；
// proxy() 从本地明文缓冲直出，播放期间没有回源/AES/逐块 JS 回调。
// playerContent 立即返回地址，和 Python 本机流一样把首段等待放进 proxy()；
// 稳定优先：详情/播放都不做后台预热，首播与换集都只处理当前集。

const SITE = 'https://hongguoduanju.com';
const UA = 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36';
const MEDIA_UA = 'com.phoenix.read/71332';
const APP_UA = 'com.phoenix.read/73532 (Linux; U; Android 16; zh_CN; 25053RT47C; Build/BP2A.250605.031.A3; Cronet/TTNetVersion:04657795 2026-01-23 QuicVersion:c67e9834 2025-09-08)';
const EPISODE_PREFIX = 'hg-episode-v1:';

const QUALITY_LINES = [
    ['1080', '超清'], ['720', '高清'], ['540', '标准'],
    ['480', '流畅'], ['360', '极速'],
];
const QUALITY_NAME_TO_Q = {
    '超清': '1080', '高清': '720', '标准': '540', '流畅': '480', '极速': '360',
    '1080': '1080', '720': '720', '540': '540', '480': '480', '360': '360',
};
const QUALITY_ORDER = ['2160', '1440', '1080', '720', '576', '540', '480', '360'];

// FongMi 的每次 proxy HTTP 请求可能是新的 Spider 实例，实例缓存无法复用。
// 这里用模块级缓存，避免播放器每次 Range 请求都重新下载并解密 20MB+ 的 MP4。
var MEDIA_CACHE = {};
var MEDIA_CACHE_ORDER = [];
var MEDIA_PENDING = {};
// 渐进式明文缓冲：先备好开头几 MB 就返回播放地址，其余在后台继续备齐。
// 播放器所有 Range 都从这份本地缓冲直出，播放中既不回源也不做 AES。
var PROGRESS_CACHE = {};
var PROGRESS_PENDING = {};
// 明文整片缓存是播放最快路径；保留最近三集，连续追剧和回看都能直接命中。
var MEDIA_CACHE_MAX = 3;
// 整集下载路径每份约 20MB，电视盒上只保留当前一集，避免长时间播放后 GC 卡顿。
var SOURCE_CACHE = {};
var SOURCE_ORDER = [];
var SOURCE_MAX = 1;
var SOURCE_PENDING = {};
// moov 顶层盒实测可达 250KB，头部一次取够，避免二次 Range 往返。
var HG_HEAD_PROBE = 256 << 10;
var HG_TAIL_PROBE = 1 << 20;
// 播放器常发 bytes=0- 这种开放式 Range。不能因此等整集下载完，
// 先回一段带 Content-Range 的开头窗口，后续 Range 再从本地缓冲取。
// 首帧只等 512KB，尽快出画。中途停播再起播时播放器会跳回旧进度，
// 那个跳转不再靠扩大首帧窗口硬扛，而是用“只补缺口”的直达补段处理。
var PROXY_START_WINDOW = 512 << 10;
// 非开头的开放式 Range 只回 1MB，避免一次请求等掉大半集。
var HG_OPEN_WINDOW = 1 << 20;
// 直达补段只服务播放器当前显式请求的 1MB，不是后台预取。旧版限制 2 次，
// 真机在跳到旧进度后连续发 1MB Range，第 3 次直接退化成等整集顺序缓冲，卡死。
// 这里保留安全上限，但足够覆盖一集内所有前台跳转；补到的明文会写回本地复用。
var HG_RESCUE_MAX = 64;
var HG_RANGE_ATTEMPTS = 3;
// 解密必须小块：电视盒上单次同步 AES 解密 1MB 会阻塞 QuickJS 线程数秒，
// 导致播放器的 proxy 请求排队（实测 queue 4.6s）。256KB 解密后立刻让出事件循环。
var HG_FETCH_CHUNK = 1 << 18;
var HG_STREAM_CHUNK = 1 << 20;
// 后台缓冲只领先播放器一段距离；开局不要把整集下载/解密和播放器抢网络。
// 领先太小会让后续 Range 触发直达补段，实测单次 1MB 直达反而更慢；
// 保持 4MB 让顺序缓冲覆盖后续请求，暂停点随播放器前进。
var HG_PLAYER_LOOKAHEAD = 4 << 20;
// 相邻集关系仅保留给旧链接兼容；稳定优先策略不在播放期间预热下一集。
var NEXT_EPISODE = {};
var NEXT_WARMED = {};
// 后台预热总开关恒为关闭：电视盒上签名/网络请求会同步堵住 QuickJS 线程，
// 实测让播放中的 proxy 排队数秒，因此播放中绝不再发起下一集的任何请求。
var PREWARM_ACTIVE = false;
var PREWARM_VIDS = {};
var LAST_PLAYED_VID = '';
// 注册身份和播放模型跨实例复用，避免每次换集都重新走注册/签名请求。
var SHARED_DEVICE = null;
var SHARED_DEVICE_TIME = 0;
var MODEL_CACHE = {};
var MODEL_CACHE_TTL = 5 * 60 * 1000;
var HOME_RECOMMEND = {time: 0, rows: []};
var HOME_CACHE_TTL = 10 * 60 * 1000;
function sourceGet(key) {
    if (Object.prototype.hasOwnProperty.call(SOURCE_CACHE, key)) return SOURCE_CACHE[key];
    return null;
}
function sourcePut(key, source) {
    if (!SOURCE_CACHE[key]) SOURCE_ORDER.push(key);
    SOURCE_CACHE[key] = source;
    while (SOURCE_ORDER.length > SOURCE_MAX) {
        var old = SOURCE_ORDER.shift();
        delete SOURCE_CACHE[old];
    }
}
function dropSource(key) {
    if (!Object.prototype.hasOwnProperty.call(SOURCE_CACHE, key)) return;
    delete SOURCE_CACHE[key];
    var at = SOURCE_ORDER.indexOf(key);
    if (at >= 0) SOURCE_ORDER.splice(at, 1);
}
function progressGet(key) {
    return Object.prototype.hasOwnProperty.call(PROGRESS_CACHE, key) ? PROGRESS_CACHE[key] : null;
}
function notifyProgress(h) {
    var keep = [];
    for (var i = 0; i < h.waiters.length; i++) {
        var w = h.waiters[i];
        if (h.frontier > w.offset || h.done) w.resolve();
        else keep.push(w);
    }
    h.waiters = keep;
}
function finishProgress(h) {
    if (h.finished) return;
    h.finished = true;
    h.done = true;
    if (!h.error && h.data && h.data.length > 64) {
        cachePut(h.key, h.data);
        dropSource(h.key);
        delete PROGRESS_CACHE[h.key];
    }
    notifyProgress(h);
}
// 播放器读到这里时唤醒后台缓冲，避免 proxy 等在暂停点。
function wakeProgress(h) {
    if (!h || !h.resume) return;
    var resume = h.resume;
    h.resume = null;
    resume();
}
// 后台顺序拉取密文并写成本地明文；iterator 一次只被一个循环消费，避免乱序。
function pumpProgress(h) {
    if (h.pumping || h.done) return;
    h.pumping = true;
    (async () => {
        while (!h.done && h.frontier < h.total) {
            // 起播初期直达补段时暂停顺序拉取，避免和那一个 Range 抢网络/AES。
            if (h.hold) {
                await new Promise(function (resolve) { h.resume = resolve; });
                continue;
            }
            // 领先播放器太多就暂停：把网络/QuickJS 让给正在播放的分段。
            // proxy 收到新的 Range 后会唤醒这里继续补到新的领先距离。
            if (h.playerEnd && h.frontier > h.playerEnd + HG_PLAYER_LOOKAHEAD) {
                hgLog('hg prog pause', h.key, (Date.now() - (h.t0 || 0)) + 'ms', h.frontier);
                await new Promise(function (resolve) { h.resume = resolve; });
                continue;
            }
            var next = await h.iterator.next();
            if (next.done) break;
            var chunk = u8(next.value);
            if (chunk.length) {
                h.data.set(chunk, h.frontier);
                h.frontier += chunk.length;
                if (!h.firstLogged) {
                    h.firstLogged = true;
                    hgLog('hg prog first chunk', h.key, (Date.now() - (h.t0 || 0)) + 'ms', chunk.length);
                }
                notifyProgress(h);
            }
        }
        finishProgress(h);
        h.pumping = false;
    })().catch(function (e) {
        h.error = e;
        finishProgress(h);
        h.pumping = false;
        wakeProgress(h);
    });
}
function waitProgress(h, offset) {
    if (h.frontier > offset || h.done) return Promise.resolve();
    return new Promise(function (resolve) { h.waiters.push({offset: offset, resolve: resolve}); });
}
// 直达补段取回的明文写回 prog.data，并记录区间。播放器跳到旧进度后会连续发
// 相邻/重叠的 1MB Range，命中这里就直接本地返回，不再回源也不再重复 AES。
function progressRescueCover(prog, start, end) {
    if (end < prog.frontier) return true;
    var list = prog.rescued;
    if (!list) return false;
    for (var i = list.length - 1; i >= 0; i--) {
        var r = list[i];
        if (r[0] <= start && end <= r[1]) return true;
    }
    return false;
}
function progressRescueRemember(prog, start, end) {
    if (!prog.rescued) prog.rescued = [];
    var list = prog.rescued, out = [], cur = [start, end], i, r;
    for (i = 0; i < list.length; i++) {
        r = list[i];
        if (r[1] + 1 < cur[0] || cur[1] + 1 < r[0]) { out.push(r); continue; }
        cur[0] = Math.min(cur[0], r[0]);
        cur[1] = Math.max(cur[1], r[1]);
    }
    out.push(cur);
    out.sort(function (a, b) { return a[0] - b[0]; });
    prog.rescued = out;
}
// 把顺序 Range 请求变成「并行预取 + 按序交付」：开头几块并发拉取，
// 首段不再等整集；后台再把预取深度调大，迅速补齐整集明文。
function makePrefetchFetcher(rawFetch, chunkSize, ahead, total) {
    var chunks = {}, pending = {}, depth = ahead, limit = total || Infinity;
    function schedule(idx) {
        if (chunks[idx] || pending[idx]) return;
        var start = idx * chunkSize;
        if (start >= limit) return;
        var end = Math.min(limit - 1, start + chunkSize - 1);
        pending[idx] = Promise.resolve().then(function () { return rawFetch(start, end); })
            .then(function (got) { chunks[idx] = u8(got.bytes); delete pending[idx]; })
            .catch(function (e) { delete pending[idx]; throw e; });
    }
    return {
        setAhead: function (n) { depth = Math.max(1, n | 0); },
        fetch: async function (start, end) {
            var parts = [], pos = start, firstIdx = Math.floor(start / chunkSize);
            for (var k = 0; k < depth; k++) schedule(firstIdx + k);
            while (pos <= end) {
                var idx = Math.floor(pos / chunkSize), base = idx * chunkSize;
                if (!chunks[idx]) {
                    schedule(idx);
                    if (pending[idx]) await pending[idx];
                }
                var block = chunks[idx];
                if (!block) {
                    // 文件末尾之后的块不存在，直接结束本次请求。
                    if (idx * chunkSize >= limit) break;
                    throw new Error('预取分片缺失 ' + idx);
                }
                var from = pos - base, to = Math.min(block.length, end - base + 1);
                if (to > from) parts.push(block.subarray(from, to));
                schedule(idx + depth);
                pos += Math.max(1, to - from);
            }
            return {bytes: parts.length === 1 ? parts[0] : concatAll(parts)};
        }
    };
}
// 有序且互不重叠的 regions 里，找到第一个末尾大于 pos 的下标；
// 避免每个 Range 请求都从 regions[0] 线性扫到当前播放位置。
function firstRegionAfter(regions, pos) {
    if (!regions || !regions.length) return 0;
    var lo = 0, hi = regions.length;
    while (lo < hi) {
        var mid = (lo + hi) >> 1;
        if (regions[mid].start + regions[mid].size <= pos) lo = mid + 1;
        else hi = mid;
    }
    return lo;
}
// 播放器拿到开头后会跳到 moov 读索引；这份明文盒在会话建立时已在内存里，
// 不必等后台顺序缓冲走到那个偏移，否则起播后必卡一下。
function progressMoovRange(prog, start, end) {
    if (!prog || !prog.moov || !prog.moov.length) return null;
    var ms = prog.moovStart || 0, me = ms + prog.moov.length;
    if (end < ms || start >= me) return null;
    return {from: Math.max(start, ms), to: Math.min(end, me - 1)};
}
// 在 bitset 中标记 [from,to) 已解密；只占样本数据 1/8 的内存。
function decBitsMark(bits, from, to) {
    if (!bits || to <= from) return;
    var first = from >> 3, last = (to - 1) >> 3;
    if (first === last) {
        bits[first] |= ((255 << (from & 7)) & (255 >> (7 - ((to - 1) & 7)))) & 255;
        return;
    }
    bits[first] |= (255 << (from & 7)) & 255;
    for (var i = first + 1; i < last; i++) bits[i] = 255;
    bits[last] |= 255 >> (7 - ((to - 1) & 7));
}
function cacheGet(key) {
    if (Object.prototype.hasOwnProperty.call(MEDIA_CACHE, key)) return MEDIA_CACHE[key];
    return null;
}
function cachePut(key, bytes) {
    if (!MEDIA_CACHE[key]) MEDIA_CACHE_ORDER.push(key);
    MEDIA_CACHE[key] = bytes;
    while (MEDIA_CACHE_ORDER.length > MEDIA_CACHE_MAX) {
        var old = MEDIA_CACHE_ORDER.shift();
        delete MEDIA_CACHE[old];
    }
}
// 新版 FongMi 直接把 TypedArray 当 byte[]；旧版会 JSON.stringify(proxy 返回值)，
// 此时 TypedArray 会变成对象。挂上 toJSON 让旧版拿到 base64 字符串，
// 再配合返回值第 5 格 = 1，旧版会解码成真正的 MP4 字节。
function proxyBody(bytes) {
    if (bytes && typeof bytes === 'object' && !bytes.toJSON) {
        bytes.toJSON = function () { return b64enc(this); };
    }
    return bytes;
}
function parseProxyRange(rangeHeader, total, windowSize, openWindow) {
    var headers = {'Accept-Ranges': 'bytes'};
    var window = Math.max(1, windowSize || total);
    var open = Math.max(1, openWindow || window);
    var text = String(rangeHeader || '').trim();
    if (!text) {
        if (window >= total) {
            headers['Content-Length'] = String(total);
            return {status: 200, start: 0, end: total - 1, headers: headers};
        }
        var openEnd = Math.min(total - 1, window - 1);
        headers['Content-Range'] = 'bytes 0-' + openEnd + '/' + total;
        headers['Content-Length'] = String(openEnd + 1);
        return {status: 206, start: 0, end: openEnd, headers: headers};
    }
    var match = /bytes=(\d*)-(\d*)/i.exec(text);
    if (!match) {
        if (window >= total) {
            headers['Content-Length'] = String(total);
            return {status: 200, start: 0, end: total - 1, headers: headers};
        }
        var openEnd2 = Math.min(total - 1, window - 1);
        headers['Content-Range'] = 'bytes 0-' + openEnd2 + '/' + total;
        headers['Content-Length'] = String(openEnd2 + 1);
        return {status: 206, start: 0, end: openEnd2, headers: headers};
    }
    var start, end;
    if (match[1] === '') {
        var suffix = parseInt(match[2], 10);
        if (!isFinite(suffix) || suffix <= 0) return {status: 416, headers: {'Content-Range': 'bytes */' + total}};
        start = Math.max(0, total - suffix);
        end = total - 1;
    } else {
        start = parseInt(match[1], 10);
        // bytes=0- 回开头窗口；非开头的开放式 Range 用较小的 open 窗口，
        // 避免播放器从 3.9MB 再要 3MB，导致 proxy 等几乎整集下载完。
        end = match[2] === '' ? Math.min(total - 1, start + open - 1) : parseInt(match[2], 10);
    }
    if (!isFinite(start) || !isFinite(end) || start < 0 || start >= total || end < start) {
        return {status: 416, headers: {'Content-Range': 'bytes */' + total}};
    }
    end = Math.min(end, total - 1);
    headers['Content-Range'] = 'bytes ' + start + '-' + end + '/' + total;
    headers['Content-Length'] = String(end - start + 1);
    return {status: 206, start: start, end: end, headers: headers};
}
function hgLog() {
    try { if (typeof console !== 'undefined' && console.log) console.log.apply(console, arguments); } catch (e) {}
}

const CONTENT_TYPES = [
    ['real-drama', '真人剧', [
        ['', '全部'], ['romance', '爱情'], ['period', '年代'], ['comeback', '逆袭'],
        ['legend', '传奇'], ['growth', '成长'], ['family', '家庭'], ['clan', '家族'],
        ['cute-kids', '萌宝'], ['suspense', '悬疑'], ['thriller', '惊悚'], ['horror', '恐怖'],
        ['supernatural', '志怪'], ['costume', '古装'], ['fantasy', '玄幻'], ['wonder', '奇幻'],
        ['urban', '都市'], ['youth', '青春'], ['comedy', '喜剧'], ['sci-fi', '科幻'],
        ['disaster', '灾难'], ['action-adventure', '动作冒险'], ['war', '战争'],
        ['variety', '综艺'], ['drama', '剧情'],
    ]],
    ['comic-drama', '漫剧', [
        ['', '全部'], ['creative', '脑洞'], ['fantasy', '玄幻'], ['drama', '剧情'],
        ['apocalypse', '末世'], ['wealthy-family', '豪门'], ['wonder', '奇幻'],
        ['sci-fi', '科幻'], ['adventure', '冒险'],
    ]],
    ['ai-drama', 'AI剧', [
        ['', '全部'], ['creative', '脑洞'], ['fantasy', '玄幻'], ['drama', '剧情'],
        ['apocalypse', '末世'], ['wealthy-family', '豪门'], ['wonder', '奇幻'],
        ['sci-fi', '科幻'], ['adventure', '冒险'],
    ]],
];
const ROUTE_ALIAS = {
    'all': 'real-drama', 'latest': 'real-drama', 'hot': 'real-drama',
    'male': 'real-drama', 'female': 'real-drama', '短剧': 'real-drama',
    'ai_comic': 'ai-drama', 'ai_manju': 'ai-drama', 'AI漫剧': 'ai-drama',
    'manju': 'comic-drama', '漫剧': 'comic-drama',
    'comic': 'comic-drama', '漫画': 'comic-drama',
};
const AI_MANJU_KEYWORDS = ['AI漫剧', 'AI动画', 'AI短剧', 'AI动漫', '漫剧AI', '二次元AI', 'AI漫画', '动画短剧'];
const MANJU_KEYWORDS = ['漫剧', '动漫短剧', '二次元', '漫画短剧', '国漫短剧', '日漫', '动态漫', '动画剧'];

const PLAYER_BASE = 'https://api5-normal-sinfonlineb.fqnovel.com';
const MULTI_PATHS = [
    ['/novel/player/multi_video_model/v1/', '1'],
    ['/novel/player/multi_video_model/v1/', '1004'],
    ['/novel/player/multi_video_model/preload/v1/', '1004'],
];
const SINGLE_PATH = '/novel/player/video_model/v1/';
const BIZ_PARAM = {
    detail_page_version: 0, device_level: 4,
    disable_digg_stat: false, disable_video_relate_book: false,
    need_all_video_definition: true, need_mp4_align: false,
    use_os_player: false, use_server_dns: false, video_platform: 1024,
};
const PUBLIC_PARAMS = {
    aid: '8662', app_name: 'novelread', version_code: '73532',
    version_name: '7.3.5.32', manifest_version_code: '73532',
    update_version_code: '73532', channel: 'update_64',
    device_platform: 'android', os: 'android', ssmix: 'a',
    device_type: '25053RT47C', device_brand: 'Redmi', language: 'zh',
    os_api: '36', os_version: '16', resolution: '1280*2772',
    dpi: '520', ac: 'wifi',
};
const PUBLIC_HEADERS = {
    'user-agent': APP_UA,
    'accept': 'application/json',
    'x-xs-from-web': '0',
    'sdk-version': '2',
    'content-type': 'application/json; charset=utf-8',
};
const V5_PLAYER_API = 'https://api5-normal-sinfonlineb.fqnovel.com/novel/player/multi_video_model/player/v1';
const V5_PLAYER_API_ALT = 'https://api5-normal-sinfonlinea.fqnovel.com/novel/player/multi_video_model/player/v1';
const V5_UA = 'com.phoenix.read/73932 (Linux; U; Android 12; zh_CN_#Hans; PGT-AN10; Build/V417IR;tt-ok/3.12.13.20)';
const V5_PROFILE = {
    aid: '8662', app_name: 'novelread', version_code: '74332', version_name: '7.4.3.32',
    channel: 'vivo_8662_64', device_platform: 'android', device_type: 'PGT-AN10', os_version: '12',
    update_version_code: '74332',
};
// 空响应恢复接口：同一个注册身份 + 73932 画像签名 GET，无正文。
const VIDEO_TAB_API = 'https://api5-normal-sinfonlineb.fqnovel.com/reading/bookapi/video_tab/multi_video_model/v1/';
const VIDEO_TAB_UA = 'com.phoenix.read/71332 (Linux; U; Android 16; zh_CN; 25053RT47C; Build/BP2A.250605.031.A3; Cronet/TTNetVersion:04657795 2026-01-23 QuicVersion:c67e9834 2025-09-08)';
// query 顺序参与签名，必须与上游 VIDEO_TAB_DEVICE 保持一致。
const VIDEO_TAB_PROFILE = {
    ac: 'wifi', channel: 'update_64', aid: '8662', app_name: 'novelread',
    version_code: '73932', version_name: '7.3.9.32', device_platform: 'android',
    os: 'android', ssmix: 'a', device_type: '25053RT47C', device_brand: 'Redmi',
    language: 'zh', os_api: '36', os_version: '16',
    manifest_version_code: '73932', resolution: '1280*2772', dpi: '520',
    update_version_code: '73932', host_abi: 'arm64-v8a', dragon_device_type: 'phone',
    pv_player: '73932', compliance_status: '0', need_personal_recommend: '1',
    player_so_load: '1', is_android_pad_screen: '0',
};
const V5_BIZ_PARAM = {
    detail_page_version: 0, device_level: 3,
    disable_digg_stat: false, disable_video_relate_book: false,
    need_all_video_definition: true, need_mp4_align: false,
    use_os_player: false, use_server_dns: false, video_platform: 1024,
};

const NATIVE_PLAYER_QUERY = 'device_platform=android&os=android&ssmix=a&_rticket=__RTICKET__&channel=69310258a&aid=8662&app_name=novelread&version_code=74332&version_name=7.4.3.32&manifest_version_code=74332&update_version_code=74332&resolution=1280*2772&dpi=520&device_type=25053RT47C&device_brand=Redmi&language=zh&os_api=36&os_version=16&ac=wifi&host_abi=arm64-v8a&dragon_device_type=phone&pv_player=74332&compliance_status=0&need_personal_recommend=1&player_so_load=1&is_android_pad_screen=0&iid=1633188196935384&device_id=1633188196931288&klink_egdi=AAI_yct20zJlL44TjMhrN5xSOsNDVSxcQWPjSy5rBsm-wqITrJI8RWrt';
const NATIVE_PLAYER_HEADERS = {
    'User-Agent': 'com.phoenix.read/74332 (Linux; U; Android 16; zh_CN; 25053RT47C; Build/BP2A.250605.031.A3; Cronet/TTNetVersion:8d40f833 2026-03-03 QuicVersion:21ac1950 2025-11-18)',
    'Accept': 'application/json; charset=utf-8,application/x-protobuf',
    'sdk-version': '2',
    'passport-sdk-version': '5051452',
    'lc': '101',
    'x-vc-bdturing-sdk-version': '4.0.3.cn',
    'x-xs-from-web': '0',
    'x-ss-dp': '8662',
    'x-tt-store-region': 'cn-gd',
    'x-tt-store-region-src': 'did',
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Encoding': 'gzip',
    'x-reading-request': '1795434281414-1115622124',
    'x-tt-trace-id': '00-7680823e49a4483599b5e2a46e4b7914-7680823e49a44835-01',
    'Cookie': 'install_id=1633188196935384; store-region=cn-jx; ttreq=1$8e71c59a0f214681559c7bd49b3958283e3acf05; store-region-src=did',
};
const NATIVE_MEDUSA_SCHEMA = [[1,15,null],[2,1,null],[3,1,null],[4,14,null],[5,14,null],[6,14,null],[7,14,null],[8,14,null],[9,1,null],[10,15,null],[11,13,null],[12,4,null],[13,15,null],[14,15,null],[15,16,[[1,1,null],[2,1,null],[3,1,null],[4,1,null],[5,1,null]]],[16,14,null],[17,1,null],[18,15,null],[19,15,null],[20,14,null],[21,1,null],[22,1,null],[23,16,[[1,1,null],[2,4,null],[3,4,null],[4,1,null],[5,1,null],[6,14,null],[7,1,null],[8,14,null],[9,14,null],[10,14,null],[11,14,null],[12,16,[[1,1,null],[2,1,null],[3,14,null],[4,14,null],[5,14,null],[6,14,null],[7,1,null],[8,1,null],[9,1,null],[10,1,null],[11,14,null],[12,14,null],[13,14,null],[14,1,null],[15,14,null],[16,10,null],[17,10,null],[18,10,null],[19,10,null],[20,10,null],[21,10,null],[22,14,null],[23,1,null],[24,1,null],[25,4,null],[26,4,null],[27,4,null],[28,4,null],[29,1,null],[30,14,null],[31,14,null],[32,14,null],[33,14,null],[34,14,null],[35,14,null],[36,14,null],[37,14,null],[38,4,null],[39,15,null],[40,4,null]]],[13,16,[[1,4,null],[2,13,null],[3,14,null],[4,1,null],[5,1,null],[6,1,null]]],[14,14,null],[15,1,null],[16,4,null],[17,4,null],[18,4,null],[19,1,null],[20,4,null],[21,1,null],[22,1,null],[23,1,null],[24,1,null]]],[24,14,null],[25,16,[[1,14,null],[2,14,null],[3,14,null],[4,1,null]]],[26,1,null],[27,15,null],[28,1,null],[29,6,null]];
const NATIVE_MEDUSA_TEMPLATE = {1:hexdec('2d4b4fca49750d433fb5ae2c226dcc56'),2:5,3:1209951667,4:hexdec('38363632'),5:hexdec('31363333313838313936393331323838'),6:hexdec('363436363337373934'),7:hexdec('372e342e332e3332'),8:hexdec('7630342e31302e30332d6d6c2d616e64726f6964'),9:67764992,10:hexdec('0485000000000000'),12:1795434281,13:hexdec('daf6da4471f74f2e52be5068ff038a413ecee854'),14:hexdec('c299f7d7ee75'),15:{1:317,2:5,3:694367,5:281826712},16:hexdec('6d2d4e4671435141584c30654e4154554337556d6b386275'),17:1795434281,20:hexdec('6e6f6e65'),21:312,23:{1:52,2:247235599,3:247235596,5:7,6:hexdec('7630342e31302e30332e30342d627567666978'),7:22088,8:hexdec('363933313032353861'),12:{1:1,2:2,3:hexdec('38363632'),4:hexdec('31363333313838313936393331323838'),5:hexdec('5570544c77796a527261714750434d476a78497741636474'),6:hexdec('216e6f7065726d21'),7:-888888,8:-888888,9:2,10:-888888,11:hexdec('216e6f7473657421'),12:hexdec('417369612f5368616e676861692c38'),13:hexdec('7a685f434e'),14:3,15:hexdec('506879736963616c2073697a653a20313238307832373732'),16:1123679104,17:1123272447,18:1081505568,19:1036126208,20:1132067712,21:1131661055,22:hexdec('3136'),23:102,24:5,25:1795427472579,26:1795434228763,27:1795428291678,28:1795434446237,29:-1,30:hexdec('32353035335254343743'),31:hexdec('5265646d69'),32:hexdec('6b6f6e61'),33:hexdec('61726d36345f6d61635f71656d75'),34:hexdec('4f6e65506c75733850726f'),35:hexdec('4f6e65506c7573'),36:hexdec('756e6b6e6f776e'),38:21,40:1795434228390},13:{1:1795434231,2:-2,4:200},14:hexdec('372e342e332e3332'),15:2113,16:27,17:2491,18:799528637,19:1795432485,20:517593478845,22:-780914011,23:-780914011},24:hexdec('7b22636d72223a31363737373231362c22636d7232223a31363737373231362c22756e5f68223a313839333939363533362c2276706e223a302c22737473223a33323235312c226b64223a302c22666b64223a323138373734363437312c227064223a313431373831383630362c226c70223a22327c3532303833303931333139317c3532313234313134373136307c323034313338303933383233387c353233343235323438323536222c22666c223a22307c307c3133373839383735367c36393934313235367c333935313333353231367c3138373537323235387c313031353537343837317c307c307c353239393036373532222c2264796e223a22222c22646f223a312c22746b223a747275657d')};

// ===========================================================================
// 通用字节 / 编码工具
// ===========================================================================
function u8(v) {
    if (v instanceof Uint8Array) return v;
    if (v instanceof ArrayBuffer) return new Uint8Array(v);
    if (Array.isArray(v)) {
        var out = new Uint8Array(v.length);
        for (var i = 0; i < v.length; i++) out[i] = v[i] & 255;
        return out;
    }
    if (typeof v === 'string') {
        var out2 = new Uint8Array(v.length);
        for (var j = 0; j < v.length; j++) out2[j] = v.charCodeAt(j) & 255;
        return out2;
    }
    return new Uint8Array(0);
}

function b64dec(value) {
    var s = String(value == null ? '' : value).trim();
    s = s.replace(/-/g, '+').replace(/_/g, '/');
    s = s.replace(/[^A-Za-z0-9+/]/g, '');
    while (s.length % 4) s += '=';
    var tbl = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
    var out = [], buf = 0, bits = 0;
    for (var i = 0; i < s.length; i++) {
        if (s[i] === '=') break;
        var v = tbl.indexOf(s[i]);
        if (v < 0) continue;
        buf = (buf << 6) | v;
        bits += 6;
        if (bits >= 8) { bits -= 8; out.push((buf >> bits) & 255); }
    }
    return new Uint8Array(out);
}

function hexdec(s) {
    var t = String(s || '').replace(/[^0-9a-fA-F]/g, '');
    var out = new Uint8Array(t.length >> 1);
    for (var i = 0; i < out.length; i++) out[i] = parseInt(t.substr(i * 2, 2), 16);
    return out;
}

function utf8dec(bytes) {
    var b = u8(bytes), out = '', i = 0;
    while (i < b.length) {
        var c = b[i++];
        if (c < 0x80) { out += String.fromCharCode(c); }
        else if ((c & 0xe0) === 0xc0) {
            out += String.fromCharCode(((c & 0x1f) << 6) | ((b[i++] || 0) & 0x3f));
        } else if ((c & 0xf0) === 0xe0) {
            out += String.fromCharCode(((c & 0x0f) << 12) | (((b[i++] || 0) & 0x3f) << 6) | ((b[i++] || 0) & 0x3f));
        } else {
            out += String.fromCharCode(((c & 0x07) << 18) | (((b[i++] || 0) & 0x3f) << 12)
                | (((b[i++] || 0) & 0x3f) << 6) | ((b[i++] || 0) & 0x3f));
        }
    }
    return out;
}

function utf8enc(s) {
    var out = [];
    for (var i = 0; i < s.length; i++) {
        var c = s.charCodeAt(i);
        if (c < 0x80) out.push(c);
        else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f));
        else if (c >= 0xd800 && c <= 0xdbff) {
            var c2 = s.charCodeAt(++i);
            var cp = 0x10000 + ((c - 0xd800) << 10) + (c2 - 0xdc00);
            out.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 0x3f), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
        } else out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
    }
    return new Uint8Array(out);
}

function concatBytes(a, b) {
    var x = u8(a), y = u8(b), out = new Uint8Array(x.length + y.length);
    out.set(x, 0); out.set(y, x.length); return out;
}
function concatAll(parts) {
    var total = 0, i;
    for (i = 0; i < parts.length; i++) total += u8(parts[i]).length;
    var out = new Uint8Array(total), off = 0;
    for (i = 0; i < parts.length; i++) {
        var p = u8(parts[i]); out.set(p, off); off += p.length;
    }
    return out;
}
function sliceBytes(a, start, end) {
    var x = u8(a); return x.subarray(start, end === undefined ? x.length : end);
}
function readU32(d, i) {
    return ((d[i] << 24) | (d[i + 1] << 16) | (d[i + 2] << 8) | d[i + 3]) >>> 0;
}
function readU32LE(d, i) {
    return ((d[i + 3] << 24) | (d[i + 2] << 16) | (d[i + 1] << 8) | d[i]) >>> 0;
}
function readU64(d, i) {
    return readU32(d, i) * 4294967296 + readU32(d, i + 4);
}
function str4(d, i) {
    return String.fromCharCode(d[i], d[i + 1], d[i + 2], d[i + 3]);
}
function randHex(n) {
    var s = '';
    while (s.length < n) s += Math.floor(Math.random() * 16).toString(16);
    return s.substring(0, n);
}
function uuid() {
    return randHex(8) + '-' + randHex(4) + '-4' + randHex(3) + '-a' + randHex(3) + '-' + randHex(12);
}

// ===========================================================================
// SHA-512（spade URL 解密用；输入均为字节）
// ===========================================================================
var MASK64 = 0xffffffffffffffffn;
// CENC 的 AES-CTR 计数器是完整 128 位；MASK64 只用于 SHA-512 的 64 位字。
var K512 = [
    '428a2f98d728ae22','7137449123ef65cd','b5c0fbcfec4d3b2f','e9b5dba58189dbbc',
    '3956c25bf348b538','59f111f1b605d019','923f82a4af194f9b','ab1c5ed5da6d8118',
    'd807aa98a3030242','12835b0145706fbe','243185be4ee4b28c','550c7dc3d5ffb4e2',
    '72be5d74f27b896f','80deb1fe3b1696b1','9bdc06a725c71235','c19bf174cf692694',
    'e49b69c19ef14ad2','efbe4786384f25e3','0fc19dc68b8cd5b5','240ca1cc77ac9c65',
    '2de92c6f592b0275','4a7484aa6ea6e483','5cb0a9dcbd41fbd4','76f988da831153b5',
    '983e5152ee66dfab','a831c66d2db43210','b00327c898fb213f','bf597fc7beef0ee4',
    'c6e00bf33da88fc2','d5a79147930aa725','06ca6351e003826f','142929670a0e6e70',
    '27b70a8546d22ffc','2e1b21385c26c926','4d2c6dfc5ac42aed','53380d139d95b3df',
    '650a73548baf63de','766a0abb3c77b2a8','81c2c92e47edaee6','92722c851482353b',
    'a2bfe8a14cf10364','a81a664bbc423001','c24b8b70d0f89791','c76c51a30654be30',
    'd192e819d6ef5218','d69906245565a910','f40e35855771202a','106aa07032bbd1b8',
    '19a4c116b8d2d0c8','1e376c085141ab53','2748774cdf8eeb99','34b0bcb5e19b48a8',
    '391c0cb3c5c95a63','4ed8aa4ae3418acb','5b9cca4f7763e373','682e6ff3d6b2b8a3',
    '748f82ee5defb2fc','78a5636f43172f60','84c87814a1f0ab72','8cc702081a6439ec',
    '90befffa23631e28','a4506cebde82bde9','bef9a3f7b2c67915','c67178f2e372532b',
    'ca273eceea26619c','d186b8c721c0c207','eada7dd6cde0eb1e','f57d4f7fee6ed178',
    '06f067aa72176fba','0a637dc5a2c898a6','113f9804bef90dae','1b710b35131c471b',
    '28db77f523047d84','32caab7b40c72493','3c9ebe0a15c9bebc','431d67c49c100d4c',
    '4cc5d4becb3e42b6','597f299cfc657e2a','5fcb6fab3ad6faec','6c44198c4a475817',
].map(function (x) { return BigInt('0x' + x); });
var H512 = [
    '6a09e667f3bcc908','bb67ae8584caa73b','3c6ef372fe94f82b','a54ff53a5f1d36f1',
    '510e527fade682d1','9b05688c2b3e6c1f','1f83d9abfb41bd6b','5be0cd19137e2179',
].map(function (x) { return BigInt('0x' + x); });

function rotr64(x, n) { return ((x >> BigInt(n)) | (x << BigInt(64 - n))) & MASK64; }

function sha512(msg) {
    var m = u8(msg);
    var bitLen = BigInt(m.length) * 8n;
    var total = Math.ceil((m.length + 17) / 128) * 128;
    var buf = new Uint8Array(total);
    buf.set(m); buf[m.length] = 0x80;
    var len = bitLen;
    for (var i = 0; i < 8; i++) { buf[total - 1 - i] = Number(len & 255n); len >>= 8n; }
    var h = H512.slice(), w = new Array(80);
    for (var blk = 0; blk < total; blk += 128) {
        for (var i2 = 0; i2 < 16; i2++) w[i2] = BigInt('0x' + bytesToHex(sliceBytes(buf, blk + i2 * 8, blk + i2 * 8 + 8)));
        for (var i3 = 16; i3 < 80; i3++) {
            var s0 = rotr64(w[i3 - 15], 1) ^ rotr64(w[i3 - 15], 8) ^ (w[i3 - 15] >> 7n);
            var s1 = rotr64(w[i3 - 2], 19) ^ rotr64(w[i3 - 2], 61) ^ (w[i3 - 2] >> 6n);
            w[i3] = (w[i3 - 16] + s0 + w[i3 - 7] + s1) & MASK64;
        }
        var a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
        for (var j = 0; j < 80; j++) {
            var S1 = rotr64(e, 14) ^ rotr64(e, 18) ^ rotr64(e, 41);
            var ch = (e & f) ^ ((~e & MASK64) & g);
            var t1 = (hh + S1 + ch + K512[j] + w[j]) & MASK64;
            var S0 = rotr64(a, 28) ^ rotr64(a, 34) ^ rotr64(a, 39);
            var maj = (a & b) ^ (a & c) ^ (b & c);
            var t2 = (S0 + maj) & MASK64;
            hh = g; g = f; f = e; e = (d + t1) & MASK64;
            d = c; c = b; b = a; a = (t1 + t2) & MASK64;
        }
        h[0] = (h[0] + a) & MASK64; h[1] = (h[1] + b) & MASK64;
        h[2] = (h[2] + c) & MASK64; h[3] = (h[3] + d) & MASK64;
        h[4] = (h[4] + e) & MASK64; h[5] = (h[5] + f) & MASK64;
        h[6] = (h[6] + g) & MASK64; h[7] = (h[7] + hh) & MASK64;
    }
    var out = new Uint8Array(64);
    for (var k = 0; k < 8; k++) {
        var v = h[k];
        for (var q = 7; q >= 0; q--) { out[k * 8 + q] = Number(v & 255n); v >>= 8n; }
    }
    return out;
}
function bytesToHex(b) {
    var x = u8(b), s = '';
    for (var i = 0; i < x.length; i++) s += ('0' + x[i].toString(16)).slice(-2);
    return s;
}

// ===========================================================================
// AES-128：S 盒运行时生成，ECB / CBC / CTR 全纯 JS（无第三方依赖）
// ===========================================================================
function gmul(a, b) {
    var r = 0;
    for (var i = 0; i < 8; i++) {
        if (b & 1) r ^= a;
        var hi = a & 0x80; a = (a << 1) & 255; if (hi) a ^= 0x1b;
        b >>= 1;
    }
    return r;
}
function gpow(a, n) {
    var r = 1;
    while (n > 0) { if (n & 1) r = gmul(r, a); a = gmul(a, a); n >>= 1; }
    return r;
}
var AES_S = new Uint8Array(256), AES_INV = new Uint8Array(256);
(function () {
    for (var i = 0; i < 256; i++) {
        var x = i === 0 ? 0 : gpow(i, 254), y = x;
        for (var k = 0; k < 4; k++) { x = ((x << 1) | (x >>> 7)) & 255; y ^= x; }
        AES_S[i] = y ^ 0x63; AES_INV[y ^ 0x63] = i;
    }
})();

function expandKey128(key) {
    var k = u8(key).subarray(0, 16), w = new Uint8Array(176);
    w.set(k, 0);
    var rcon = 1;
    for (var i = 16; i < 176; i += 4) {
        var t0 = w[i - 4], t1 = w[i - 3], t2 = w[i - 2], t3 = w[i - 1];
        if (i % 16 === 0) {
            var tmp = AES_S[t1]; t1 = AES_S[t2]; t2 = AES_S[t3]; t3 = AES_S[t0]; t0 = tmp;
            t0 ^= rcon; rcon = gmul(rcon, 2);
        }
        w[i] = w[i - 16] ^ t0; w[i + 1] = w[i - 15] ^ t1;
        w[i + 2] = w[i - 14] ^ t2; w[i + 3] = w[i - 13] ^ t3;
    }
    return w;
}

// T-table AES（对齐 HGTV.py 的 _pure_aes_keystream）：32 位字运算 + 查表，
// 比逐字节 SubBytes/ShiftRows/MixColumns 快一个数量级，解决低端电视卡顿。
var AES_T0 = new Int32Array(256), AES_T1 = new Int32Array(256),
    AES_T2 = new Int32Array(256), AES_T3 = new Int32Array(256);
(function () {
    for (var v = 0; v < 256; v++) {
        var s = AES_S[v], s2 = (s & 0x80) ? (((s << 1) ^ 0x1B) & 255) : ((s << 1) & 255);
        var w = ((s2 << 24) | (s << 16) | (s << 8) | (s2 ^ s)) | 0;
        AES_T0[v] = w;
        AES_T1[v] = ((w >>> 8) | (w << 24)) | 0;
        AES_T2[v] = ((w >>> 16) | (w << 16)) | 0;
        AES_T3[v] = ((w >>> 24) | (w << 8)) | 0;
    }
})();
function u32be(b, o) {
    return ((b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]) | 0;
}
function expandKeyWords(key) {
    var k = u8(key).subarray(0, 16), w = new Int32Array(44), i;
    for (i = 0; i < 4; i++) w[i] = u32be(k, i * 4);
    var rcon = 1;
    for (i = 4; i < 44; i++) {
        var t = w[i - 1];
        if (i % 4 === 0) {
            t = ((t << 8) | (t >>> 24)) | 0;
            t = ((AES_S[(t >>> 24) & 255] << 24) | (AES_S[(t >>> 16) & 255] << 16) |
                 (AES_S[(t >>> 8) & 255] << 8) | AES_S[t & 255]) ^ (rcon << 24);
            rcon = (rcon & 0x80) ? (((rcon << 1) ^ 0x1B) & 255) : ((rcon << 1) & 255);
        }
        w[i] = (w[i - 4] ^ t) | 0;
    }
    return w;
}

function addRoundKey(s, w, round) {
    for (var i = 0; i < 16; i++) s[i] ^= w[round * 16 + i];
}
function shiftRows(s) {
    var t;
    t = s[1]; s[1] = s[5]; s[5] = s[9]; s[9] = s[13]; s[13] = t;
    t = s[2]; s[2] = s[10]; s[10] = t; t = s[6]; s[6] = s[14]; s[14] = t;
    t = s[15]; s[15] = s[11]; s[11] = s[7]; s[7] = s[3]; s[3] = t;
}
function invShiftRows(s) {
    var t;
    t = s[13]; s[13] = s[9]; s[9] = s[5]; s[5] = s[1]; s[1] = t;
    t = s[2]; s[2] = s[10]; s[10] = t; t = s[6]; s[6] = s[14]; s[14] = t;
    t = s[3]; s[3] = s[7]; s[7] = s[11]; s[11] = s[15]; s[15] = t;
}
function mixColumns(s) {
    for (var c = 0; c < 4; c++) {
        var i = c * 4, a0 = s[i], a1 = s[i + 1], a2 = s[i + 2], a3 = s[i + 3];
        s[i] = gmul(a0, 2) ^ gmul(a1, 3) ^ a2 ^ a3;
        s[i + 1] = a0 ^ gmul(a1, 2) ^ gmul(a2, 3) ^ a3;
        s[i + 2] = a0 ^ a1 ^ gmul(a2, 2) ^ gmul(a3, 3);
        s[i + 3] = gmul(a0, 3) ^ a1 ^ a2 ^ gmul(a3, 2);
    }
}
function invMixColumns(s) {
    for (var c = 0; c < 4; c++) {
        var i = c * 4, a0 = s[i], a1 = s[i + 1], a2 = s[i + 2], a3 = s[i + 3];
        s[i] = gmul(a0, 14) ^ gmul(a1, 11) ^ gmul(a2, 13) ^ gmul(a3, 9);
        s[i + 1] = gmul(a0, 9) ^ gmul(a1, 14) ^ gmul(a2, 11) ^ gmul(a3, 13);
        s[i + 2] = gmul(a0, 13) ^ gmul(a1, 9) ^ gmul(a2, 14) ^ gmul(a3, 11);
        s[i + 3] = gmul(a0, 11) ^ gmul(a1, 13) ^ gmul(a2, 9) ^ gmul(a3, 14);
    }
}

function Aes(key) {
    if (!(this instanceof Aes)) return new Aes(key);
    this.w = expandKey128(key);
    this.rk = expandKeyWords(key);
    // 复用 CTR 密钥流缓冲，避免每个 64KB pull 都新建 Uint8Array 造成 GC 卡顿。
    this.ks = null;
}
Aes.prototype.encryptBlock = function (input, off, out, outOff) {
    var s = new Uint8Array(16);
    for (var i = 0; i < 16; i++) s[i] = input[off + i];
    addRoundKey(s, this.w, 0);
    for (var r = 1; r < 10; r++) {
        for (var j = 0; j < 16; j++) s[j] = AES_S[s[j]];
        shiftRows(s); mixColumns(s); addRoundKey(s, this.w, r);
    }
    for (var j2 = 0; j2 < 16; j2++) s[j2] = AES_S[s[j2]];
    shiftRows(s); addRoundKey(s, this.w, 10);
    for (var j3 = 0; j3 < 16; j3++) out[outOff + j3] = s[j3];
};
Aes.prototype.decryptBlock = function (input, off, out, outOff) {
    var s = new Uint8Array(16);
    for (var i = 0; i < 16; i++) s[i] = input[off + i];
    addRoundKey(s, this.w, 10);
    for (var r = 9; r >= 1; r--) {
        invShiftRows(s);
        for (var j = 0; j < 16; j++) s[j] = AES_INV[s[j]];
        addRoundKey(s, this.w, r); invMixColumns(s);
    }
    invShiftRows(s);
    for (var j2 = 0; j2 < 16; j2++) s[j2] = AES_INV[s[j2]];
    addRoundKey(s, this.w, 0);
    for (var j3 = 0; j3 < 16; j3++) out[outOff + j3] = s[j3];
};
// 生成 nblocks 个 CTR 密钥流块；32 位 T 表查表，速度约为逐字节实现的 10 倍。
// 写入实例复用的缓冲，streaming 时不再为每 64KB 分配临时数组。
Aes.prototype.keystreamInto = function (counter16, nblocks) {
    var rk = this.rk, need = nblocks * 16;
    if (!this.ks || this.ks.length < need) this.ks = new Uint8Array(need);
    var out = this.ks, ctr = new Uint8Array(16);
    ctr.set(u8(counter16).subarray(0, 16));
    var pos = 0;
    for (var b = 0; b < nblocks; b++) {
        var s0 = (u32be(ctr, 0) ^ rk[0]) | 0, s1 = (u32be(ctr, 4) ^ rk[1]) | 0;
        var s2 = (u32be(ctr, 8) ^ rk[2]) | 0, s3 = (u32be(ctr, 12) ^ rk[3]) | 0;
        for (var ci = 15; ci >= 0; ci--) { ctr[ci] = (ctr[ci] + 1) & 255; if (ctr[ci]) break; }
        var k = 4;
        for (var r = 0; r < 9; r++) {
            var t0 = (AES_T0[s0 >>> 24] ^ AES_T1[(s1 >>> 16) & 255] ^ AES_T2[(s2 >>> 8) & 255] ^ AES_T3[s3 & 255] ^ rk[k]) | 0;
            var t1 = (AES_T0[s1 >>> 24] ^ AES_T1[(s2 >>> 16) & 255] ^ AES_T2[(s3 >>> 8) & 255] ^ AES_T3[s0 & 255] ^ rk[k + 1]) | 0;
            var t2 = (AES_T0[s2 >>> 24] ^ AES_T1[(s3 >>> 16) & 255] ^ AES_T2[(s0 >>> 8) & 255] ^ AES_T3[s1 & 255] ^ rk[k + 2]) | 0;
            var t3 = (AES_T0[s3 >>> 24] ^ AES_T1[(s0 >>> 16) & 255] ^ AES_T2[(s1 >>> 8) & 255] ^ AES_T3[s2 & 255] ^ rk[k + 3]) | 0;
            s0 = t0; s1 = t1; s2 = t2; s3 = t3; k += 4;
        }
        var f0 = ((AES_S[s0 >>> 24] << 24) | (AES_S[(s1 >>> 16) & 255] << 16) | (AES_S[(s2 >>> 8) & 255] << 8) | AES_S[s3 & 255]) ^ rk[k];
        var f1 = ((AES_S[s1 >>> 24] << 24) | (AES_S[(s2 >>> 16) & 255] << 16) | (AES_S[(s3 >>> 8) & 255] << 8) | AES_S[s0 & 255]) ^ rk[k + 1];
        var f2 = ((AES_S[s2 >>> 24] << 24) | (AES_S[(s3 >>> 16) & 255] << 16) | (AES_S[(s0 >>> 8) & 255] << 8) | AES_S[s1 & 255]) ^ rk[k + 2];
        var f3 = ((AES_S[s3 >>> 24] << 24) | (AES_S[(s0 >>> 16) & 255] << 16) | (AES_S[(s1 >>> 8) & 255] << 8) | AES_S[s2 & 255]) ^ rk[k + 3];
        out[pos] = (f0 >>> 24) & 255; out[pos + 1] = (f0 >>> 16) & 255; out[pos + 2] = (f0 >>> 8) & 255; out[pos + 3] = f0 & 255;
        out[pos + 4] = (f1 >>> 24) & 255; out[pos + 5] = (f1 >>> 16) & 255; out[pos + 6] = (f1 >>> 8) & 255; out[pos + 7] = f1 & 255;
        out[pos + 8] = (f2 >>> 24) & 255; out[pos + 9] = (f2 >>> 16) & 255; out[pos + 10] = (f2 >>> 8) & 255; out[pos + 11] = f2 & 255;
        out[pos + 12] = (f3 >>> 24) & 255; out[pos + 13] = (f3 >>> 16) & 255; out[pos + 14] = (f3 >>> 8) & 255; out[pos + 15] = f3 & 255;
        pos += 16;
    }
    return out;
};
Aes.prototype.keystream = function (counter16, nblocks) {
    return this.keystreamInto(counter16, nblocks).slice(0, nblocks * 16);
};
Aes.prototype.ctr = function (counter16, data) {
    var x = u8(data), out = new Uint8Array(x.length);
    if (!x.length) return out;
    var ks = this.keystream(counter16, (x.length + 15) >> 4);
    for (var i = 0; i < x.length; i++) out[i] = x[i] ^ ks[i];
    return out;
};
Aes.prototype.cbcDecrypt = function (iv16, data) {
    var x = u8(data);
    x = x.subarray(0, x.length - (x.length % 16));
    var out = new Uint8Array(x.length);
    var prev = new Uint8Array(16), iv = u8(iv16);
    prev.set(iv.subarray(0, Math.min(16, iv.length)), 0);
    var dec = new Uint8Array(16);
    for (var i = 0; i < x.length; i += 16) {
        this.decryptBlock(x, i, dec, 0);
        for (var j = 0; j < 16; j++) out[i + j] = dec[j] ^ prev[j];
        for (var k = 0; k < 16; k++) prev[k] = x[i + k];
    }
    return out;
};

// ===========================================================================
// 红果密钥材料
// ===========================================================================
function deriveContentKey(spadeB64) {
    var raw = b64dec(spadeB64);
    if (raw.length < 3) throw new Error('spade_a 太短');
    var v8 = raw.length - (raw[0] ^ raw[1] ^ raw[2]) + 47;
    if (v8 <= 0 || 1 + v8 > raw.length) v8 = raw.length - 1;
    if (v8 < 33) throw new Error('spade_a 长度异常');
    var value = raw.slice(1, 1 + v8);
    var va = 85, vb = 246;
    for (var i = 0; i < v8; i++) {
        var prev = (i & 1) ? va : vb;
        if (i & 1) va = value[i]; else vb = value[i];
        var pc = 0, n = i; while (n) { pc += n & 1; n >>= 1; }
        value[i] = (-21 - pc + (prev ^ value[i])) & 255;
    }
    return hexdec(utf8dec(value.subarray(1, 33)));
}

var SPADE_CONSTANTS = hexdec(
    '4dd4c2e6b83162090e52b3c7a6733ba4' +
    '1cb2462b829ab58a196b39db57177524' +
    'f49baf7f08e8d68d26a72e37c1a95a2f' +
    '1f05a51892aef2949732b62a38aadd58'
);
function decryptSpadeUrl(value, keySeed) {
    var raw = b64dec(value);
    if (raw.length < 20 || raw[0] !== 0xa8 || raw[2] !== 0x01 || raw[3] !== 0x00)
        throw new Error('spade URL 头无效');
    var cipherLen = raw.length - 4 - ((raw.length - 4) % 16);
    var cipher = raw.subarray(4, 4 + cipherLen);
    if (!cipher.length) throw new Error('spade URL 密文为空');
    var first = sha512(u8(keySeed));
    var second = sha512(concatBytes(first, SPADE_CONSTANTS));
    var aes = new Aes(second.subarray(0, 16));
    var plain = aes.cbcDecrypt(second.subarray(16, 32), cipher);
    if (plain.length) {
        var pad = plain[plain.length - 1];
        if (pad >= 1 && pad <= 16 && pad <= plain.length) plain = plain.subarray(0, plain.length - pad);
    }
    while (plain.length && plain[plain.length - 1] === 0) plain = plain.subarray(0, plain.length - 1);
    return utf8dec(plain);
}

// ===========================================================================
// MP4 / CENC 解密
// ===========================================================================
function findBox(data, cc, start) {
    var a = cc.charCodeAt(0), b = cc.charCodeAt(1), c = cc.charCodeAt(2), d = cc.charCodeAt(3);
    var begin = Math.max(4, start || 0);
    for (var i = begin; i < data.length - 4; i++) {
        if (data[i] !== a || data[i + 1] !== b || data[i + 2] !== c || data[i + 3] !== d) continue;
        var size = readU32(data, i - 4);
        if (size === 1 && i + 12 <= data.length) size = readU64(data, i + 4);
        if (size >= 8 && size <= 5000000 && i - 4 + size <= data.length) return [i - 4, size];
    }
    return [-1, 0];
}
// 在已有数据窗口里找 moov；允许 moov 只露出一部分（盒体继续在窗口外），
// 找到后按绝对偏移单独取完整 moov。faststart / 尾部 moov 都适用。
function findMoovWindow(data, base, total) {
    for (var i = 4; i < data.length - 4; i++) {
        if (str4(data, i) !== 'moov') continue;
        var size = readU32(data, i - 4), header = 8;
        if (size === 1) { if (i + 12 > data.length) continue; size = readU64(data, i + 4); header = 16; }
        else if (size === 0) size = total - (base + i - 4);
        if (size < header || size > 5000000) continue;
        var start = base + i - 4;
        if (start >= 0 && start + size <= total) return [start, size];
    }
    return [-1, 0];
}
function findMoovInTail(tail, tailStart, total) {
    for (var i = 4; i < tail.length - 4; i++) {
        if (str4(tail, i) !== 'moov') continue;
        var size = readU32(tail, i - 4);
        if (size === 1) { if (i + 12 > tail.length) continue; size = readU64(tail, i + 4); }
        if (size < 8 || size > 5000000) continue;
        var start = tailStart + i - 4;
        if (start >= 0 && start + size <= total) return [start, size];
    }
    return [-1, 0];
}
function headerGet(headers, name) {
    if (!headers) return '';
    if (headers[name] !== undefined) return String(headers[name]);
    var low = name.toLowerCase();
    for (var k in headers) {
        if (Object.prototype.hasOwnProperty.call(headers, k) && k.toLowerCase() === low) return String(headers[k]);
    }
    return '';
}
function iterBoxes(data, start, end) {
    var out = [], cursor = start || 0, limit = end === undefined ? data.length : Math.min(end, data.length);
    while (cursor + 8 <= limit) {
        var size = readU32(data, cursor), cc = str4(data, cursor + 4), header = 8;
        if (size === 1) { if (cursor + 16 > limit) break; size = readU64(data, cursor + 8); header = 16; }
        else if (size === 0) size = limit - cursor;
        if (size < header || cursor + size > limit) break;
        out.push([cursor, size, cc, header]);
        cursor += size;
    }
    return out;
}
function nodeHeader(data, off) {
    try { return readU32(data, off) === 1 ? 16 : 8; } catch (e) { return 8; }
}
function moovContent(data) {
    var boxes = iterBoxes(data, 0, data.length);
    if (boxes.length && boxes[0][2] === 'moov') return [boxes[0][0] + boxes[0][3], boxes[0][0] + boxes[0][1]];
    return [0, data.length];
}
function firstBox(data, parent, cc) {
    if (!parent) return null;
    var boxes = iterBoxes(data, parent[0] + parent[3], parent[0] + parent[1]);
    for (var i = 0; i < boxes.length; i++) if (boxes[i][2] === cc) return boxes[i];
    return null;
}
function boxPath(data, root) {
    var node = root;
    // arguments[0] 是 data，arguments[1] 是 root，路径从 arguments[2] 开始。
    for (var i = 2; i < arguments.length; i++) {
        node = firstBox(data, node, arguments[i]);
        if (!node) return null;
    }
    return node;
}
function nodeBody(data, node) {
    if (!node) return null;
    return data.subarray(node[0] + node[3], node[0] + node[1]);
}
function trackInfo(moov, off, size) {
    var info = {handler: '', format: '', encrypted: false, sampleCount: 0};
    if (off < 0 || size <= 0) return info;
    var root = [off, size, 'trak', nodeHeader(moov, off)];
    var mdia = firstBox(moov, root, 'mdia');
    if (!mdia) return info;
    var hdlrBody = nodeBody(moov, firstBox(moov, mdia, 'hdlr'));
    if (hdlrBody && hdlrBody.length >= 12) info.handler = str4(hdlrBody, 8);
    var stbl = boxPath(moov, mdia, 'minf', 'stbl');
    if (!stbl) return info;
    var stsz = nodeBody(moov, firstBox(moov, stbl, 'stsz'));
    if (stsz && stsz.length >= 12) info.sampleCount = readU32(stsz, 8);
    var stsd = nodeBody(moov, firstBox(moov, stbl, 'stsd'));
    if (stsd && stsd.length >= 16) {
        var es = readU32(stsd, 8);
        if (es >= 8 && 8 + es <= stsd.length) {
            info.format = str4(stsd, 12);
            info.encrypted = (info.format === 'encv' || info.format === 'enca');
        }
    }
    return info;
}
function qualityHint(v) {
    var m = /(2160|1440|1080|720|576|540|480|360)/.exec(String(v == null ? '' : v).toLowerCase());
    return m ? m[1] : '';
}

function parseTrack(moov, off, size) {
    if (off < 0) return null;
    if (size <= 0) size = moov.length - off;
    var root = [off, size, 'trak', nodeHeader(moov, off)];
    var stbl = boxPath(moov, root, 'mdia', 'minf', 'stbl');
    if (!stbl) return null;
    var stsz = nodeBody(moov, firstBox(moov, stbl, 'stsz'));
    var stco = nodeBody(moov, firstBox(moov, stbl, 'stco'));
    var co64 = nodeBody(moov, firstBox(moov, stbl, 'co64'));
    var stsc = nodeBody(moov, firstBox(moov, stbl, 'stsc'));
    var saiz = nodeBody(moov, firstBox(moov, stbl, 'saiz'));
    var saio = nodeBody(moov, firstBox(moov, stbl, 'saio'));
    if (!stsz || !stsc || !saiz || !saio || (!stco && !co64)) return null;
    if (stsz.length < 12 || stsc.length < 8) return null;
    var defSize = readU32(stsz, 4), sampleCount = readU32(stsz, 8);
    var sizes = [];
    if (defSize) { for (var i = 0; i < sampleCount; i++) sizes.push(defSize); }
    else { for (var j = 0; j < sampleCount; j++) sizes.push(readU32(stsz, 12 + j * 4)); }
    var table = stco || co64, cw = stco ? 4 : 8;
    var chunkCount = readU32(table, 4), offsets = [];
    for (var k = 0; k < chunkCount; k++) {
        offsets.push(cw === 4 ? readU32(table, 8 + k * 4) : readU64(table, 8 + k * 8));
    }
    var entryCount = readU32(stsc, 4), entries = [];
    for (var m = 0; m < entryCount; m++) entries.push([readU32(stsc, 8 + m * 12), readU32(stsc, 12 + m * 12)]);
    var chunkSamples = new Array(chunkCount).fill(0);
    for (var n = 0; n < entries.length; n++) {
        var end = n + 1 < entries.length ? entries[n + 1][0] - 1 : chunkCount;
        for (var ch = entries[n][0] - 1; ch < Math.min(end, chunkCount); ch++) chunkSamples[ch] = entries[n][1];
    }
    var saizVer = saiz[0], saizCur = saizVer === 1 ? 12 : 4;
    if (saiz.length < saizCur + 5) return null;
    var defaultAux = saiz[saizCur], auxCount = readU32(saiz, saizCur + 1), auxSizes = [];
    if (defaultAux) { for (var a = 0; a < auxCount; a++) auxSizes.push(defaultAux); }
    else { for (var b = 0; b < auxCount; b++) auxSizes.push(saiz[saizCur + 5 + b] || 0); }
    if (auxSizes.length !== auxCount) return null;
    var saioVer = saio[0], saioCur = saioVer === 1 ? 12 : 4, ow = saioVer === 1 ? 8 : 4;
    if (saio.length < saioCur + 4 + ow) return null;
    var ec = readU32(saio, saioCur);
    if (ec < 1) return null;
    var auxOffset = ow === 4 ? readU32(saio, saioCur + 4) : readU64(saio, saioCur + 4);
    return {sizes: sizes, offsets: offsets, chunkCounts: chunkSamples,
        auxSizes: auxSizes, auxOffset: auxOffset, sampleCount: sampleCount};
}

function cencSubsamplePlan(entry, sampleSize) {
    if (entry.length <= 8) return null;
    var count = (entry[8] << 8) | entry[9];
    if (count <= 0 || 10 + count * 6 > entry.length) return null;
    var plan = [], pos = 10, total = 0;
    for (var i = 0; i < count; i++) {
        if (pos + 6 > entry.length) break;
        var clear = (entry[pos] << 8) | entry[pos + 1];
        var protect = (entry[pos + 2] << 24) | (entry[pos + 3] << 16) | (entry[pos + 4] << 8) | entry[pos + 5];
        pos += 6; plan.push([clear, protect]); total += clear + protect;
    }
    if (!plan.length || total <= 0 || total > sampleSize) return null;
    return plan;
}
function cencIV(entry, plan) {
    var out = new Uint8Array(16);
    if (!plan && entry.length >= 16) out.set(entry.subarray(0, 16), 0);
    else out.set(entry.subarray(0, Math.min(8, entry.length)), 0);
    return out;
}
function counterFromIV(iv, addBlocks) {
    var ctr = u8(iv).subarray(0, 16).slice();
    if (addBlocks) {
        var carry = addBlocks;
        for (var i = 15; i >= 0 && carry > 0; i--) {
            var v = ctr[i] + (carry % 256);
            ctr[i] = v & 255; carry = Math.floor(carry / 256) + (v >= 256 ? 1 : 0);
        }
    }
    return ctr;
}
// 把 AES-CTR 密钥流按样本内偏移切片应用：流式播放每次只解 64KB，
// 不必先解完整个样本，因此单次 FongMi pull 不会因关键帧过大而卡顿。
function aesCtrXor(aes, iv, src, from, to, out, outOff, extraBlocks, srcOff) {
    if (to <= from) return;
    var startBlock = Math.floor(from / 16);
    var endBlock = Math.floor((to - 1) / 16);
    var nblocks = endBlock - startBlock + 1;
    var ctr = counterFromIV(iv, startBlock + (extraBlocks || 0));
    var ks = aes.keystreamInto(ctr, nblocks);
    var startOff = from - startBlock * 16;
    var so = srcOff || 0;
    for (var i = 0, p = startOff; i < to - from; i++, p++) {
        out[outOff + i] = src[so + i] ^ ks[p];
    }
}
// srcBase 表示 src[0] 对应的样本内偏移。整片解密时为 0；
// 按需 Range 流式解密时 src 只是样本的一段，srcBase 就是这段的起点。
function cencDecryptSlice(aes, iv, src, plan, from, to, out, outOff, srcBase) {
    outOff = outOff || 0;
    var base = srcBase === undefined ? 0 : srcBase;
    var len = to - from;
    if (len <= 0) return out;
    for (var k = 0; k < len; k++) out[outOff + k] = src[from + k - base];
    if (!plan) {
        aesCtrXor(aes, iv, src, from, to, out, outOff, 0, from - base);
        return out;
    }
    var pos = 0, blocks = 0;
    for (var i = 0; i < plan.length; i++) {
        pos += plan[i][0];
        var prot = plan[i][1];
        if (prot <= 0) continue;
        var segEnd = pos + prot;
        var a = Math.max(from, pos), b = Math.min(to, segEnd);
        if (a < b) {
            // CTR 密钥流从每个 protected 段的第 0 字节开始，clear 段不消耗计数器。
            var seg = src.subarray(a - base, b - base);
            aesCtrXor(aes, iv, seg, a - pos, b - pos, out, outOff + (a - from), blocks, 0);
        }
        blocks += Math.ceil(prot / 16);
        pos = segEnd;
    }
    return out;
}
function cencDecryptSample(aes, iv, data, plan) {
    var src = u8(data);
    return cencDecryptSlice(aes, iv, src, plan, 0, src.length, new Uint8Array(src.length), 0);
}

function iterSampleEntries(data) {
    var out = [], range = moovContent(data);
    var tracks = iterBoxes(data, range[0], range[1]);
    for (var i = 0; i < tracks.length; i++) {
        if (tracks[i][2] !== 'trak') continue;
        var root = [tracks[i][0], tracks[i][1], 'trak', tracks[i][3]];
        var stbl = boxPath(data, root, 'mdia', 'minf', 'stbl');
        if (!stbl) continue;
        var stsd = firstBox(data, stbl, 'stsd');
        if (!stsd) continue;
        var base = stsd[0] + stsd[3], limit = stsd[0] + stsd[1];
        if (base + 8 > limit) continue;
        var count = readU32(data, base + 4), cursor = base + 8;
        for (var j = 0; j < count; j++) {
            if (cursor + 8 > limit) break;
            var size = readU32(data, cursor);
            if (size < 8 || cursor + size > limit) break;
            out.push([cursor, size, str4(data, cursor + 4)]);
            cursor += size;
        }
    }
    return out;
}
function formatFromConfig(blob, kind) {
    var audio = [['esds', 'mp4a'], ['opusC', 'Opus'], ['ac-3', 'ac-3'], ['ec-3', 'ec-3']];
    var video = [['hvcC', 'hvc1'], ['hev1C', 'hev1'], ['av1C', 'av01'], ['vpcC', 'vp09'],
        ['avcC', 'avc1'], ['dvvC', 'dvh1'], ['dvhC', 'dvh1'], ['bv2C', 'bvc2']];
    var probes = kind === 'enca' ? audio.concat(video) : video.concat(audio);
    var bytes = u8(blob), hitPos = -1, hitFmt = '';
    for (var i = 0; i < probes.length; i++) {
        var text = probes[i][0], needle = [];
        for (var c = 0; c < text.length; c++) needle.push(text.charCodeAt(c));
        var p = -1, idx = 0;
        while (true) {
            p = indexOfBytes(bytes, needle, idx, bytes.length);
            if (p < 0) break;
            if (hitPos < 0 || p < hitPos) { hitPos = p; hitFmt = probes[i][1]; }
            idx = p + 1;
        }
    }
    return hitFmt;
}
function formatFromEntry(blob, kind) {
    // 必须按原始字节查找：sample entry 内含非 UTF-8 字节，先解码成字符串会让
    // 后续偏移错位，把 HEVC(hvcC) 误判成默认 avc1，造成「有声音没画面」。
    var bytes = u8(blob), idx = 0, frma = [102, 114, 109, 97];
    while (true) {
        var pos = indexOfBytes(bytes, frma, idx, bytes.length);
        if (pos < 0) break;
        if (pos + 8 <= bytes.length) {
            var fmt = str4(bytes, pos + 4);
            if (fmt && fmt !== '\0\0\0\0' && fmt !== 'encv' && fmt !== 'enca' && /^[\x20-\x7e]{4}$/.test(fmt)) return fmt;
        }
        idx = pos + 4;
    }
    return formatFromConfig(bytes, kind);
}
var PLAYABLE_FORMATS = ['avc1', 'avc3', 'hvc1', 'hev1', 'av01', 'vp09', 'vp08', 'dvh1', 'dvhe'];

function restoreCodecsAndSinf(moovBuf) {
    var entries = iterSampleEntries(moovBuf);
    for (var i = 0; i < entries.length; i++) {
        var e = entries[i], fmt = e[2], def = '', kind = '';
        if (fmt === 'encv') { def = 'avc1'; kind = 'encv'; }
        else if (fmt === 'enca') { def = 'mp4a'; kind = 'enca'; }
        else continue;
        var blob = moovBuf.subarray(e[0], e[0] + e[1]);
        var real = formatFromEntry(blob, kind) || def;
        for (var j = 0; j < 4; j++) moovBuf[e[0] + 4 + j] = real.charCodeAt(j);
    }
    // sinf -> free 并清零（仅 sample entry 范围内、首个子盒为 frma/schm/schi）
    for (var n = 0; n < entries.length; n++) {
        var en = entries[n], limit2 = en[0] + en[1], pos = en[0];
        while (true) {
            var at = -1, idx = pos;
            while (true) { at = indexOfBytes(moovBuf, [115, 105, 110, 102], idx, limit2); if (at < 0) break;
                if (at >= 4) {
                    var size = readU32(moovBuf, at - 4), end = at - 4 + size, child = str4(moovBuf, at + 8);
                    if (size >= 8 && size < 50000 && end <= limit2 && (child === 'frma' || child === 'schm' || child === 'schi')) {
                        moovBuf[at] = 102; moovBuf[at + 1] = 114; moovBuf[at + 2] = 101; moovBuf[at + 3] = 101;
                        for (var z = at + 4; z < end; z++) moovBuf[z] = 0;
                        pos = end; break;
                    }
                }
                idx = at + 4;
            }
            if (at < 0) break;
        }
    }
}
function indexOfBytes(arr, needle, start, end) {
    var limit = end === undefined ? arr.length : Math.min(end, arr.length);
    for (var i = start || 0; i <= limit - needle.length; i++) {
        if (arr[i] === needle[0] && arr[i + 1] === needle[1] && arr[i + 2] === needle[2] && arr[i + 3] === needle[3]) return i;
    }
    return -1;
}
function videoPlayable(moov) {
    var range = moovContent(moov), boxes = iterBoxes(moov, range[0], range[1]);
    for (var i = 0; i < boxes.length; i++) {
        if (boxes[i][2] !== 'trak') continue;
        var info = trackInfo(moov, boxes[i][0], boxes[i][1]);
        if (info.handler !== 'vide') continue;
        var stbl = boxPath(moov, [boxes[i][0], boxes[i][1], 'trak', boxes[i][3]], 'mdia', 'minf', 'stbl');
        var stsd = stbl ? nodeBody(moov, firstBox(moov, stbl, 'stsd')) : null;
        if (!stsd || stsd.length < 12) return true;
        var es = readU32(stsd, 8);
        if (es < 8 || 8 + es > stsd.length) return true;
        var fmt = formatFromEntry(stsd.subarray(8, 8 + es), 'encv');
        return fmt ? PLAYABLE_FORMATS.indexOf(fmt) >= 0 : true;
    }
    return true;
}
function hasVideoTrack(moov) {
    var range = moovContent(moov), boxes = iterBoxes(moov, range[0], range[1]), found = false;
    for (var i = 0; i < boxes.length; i++) {
        if (boxes[i][2] !== 'trak') continue;
        found = true;
        if (trackInfo(moov, boxes[i][0], boxes[i][1]).handler === 'vide') return true;
    }
    return !found;
}

// 下载完成后先解析 CENC 结构并修复 moov；AES 解密由 mediaBytes() 在
// playerContent 预热阶段一次性完成，播放时只读明文缓存。
function buildCencSession(data, contentKey) {
    if (!contentKey || contentKey.length !== 16) throw new Error('CENC 密钥长度错误');
    var result = u8(data).slice();
    if (result.length < 16) throw new Error('MP4 数据过短');
    var found = findBox(result, 'moov', 0);
    var moovStart = found[0], moovSize = found[1];
    if (moovStart < 0 || moovSize < 8) throw new Error('MP4 moov 越界');
    var moov = result.subarray(moovStart, moovStart + moovSize);
    var range = moovContent(moov), tracks = iterBoxes(moov, range[0], range[1]);
    var aes = new Aes(contentKey), regions = [], sawVideo = false;
    for (var t = 0; t < tracks.length; t++) {
        if (tracks[t][2] !== 'trak') continue;
        var info = trackInfo(moov, tracks[t][0], tracks[t][1]);
        if (info.handler === 'vide') sawVideo = true;
        var parsed = parseTrack(moov, tracks[t][0], tracks[t][1]);
        if (!parsed || !parsed.sampleCount || parsed.auxOffset < 0) continue;
        var auxLen = 0;
        for (var q = 0; q < parsed.auxSizes.length; q++) auxLen += Math.max(parsed.auxSizes[q], 8);
        if (parsed.auxOffset + auxLen > result.length) continue;
        var aux = result.subarray(parsed.auxOffset, parsed.auxOffset + auxLen);
        var sampleIndex = 0, auxIndex = 0;
        for (var ci = 0; ci < parsed.offsets.length; ci++) {
            var current = parsed.offsets[ci];
            for (var s = 0; s < parsed.chunkCounts[ci]; s++) {
                if (sampleIndex >= parsed.sampleCount || sampleIndex >= parsed.sizes.length) break;
                var sz = parsed.sizes[sampleIndex];
                if (current + sz > result.length) throw new Error('MP4 样本越界');
                if (sampleIndex >= parsed.auxSizes.length) break;
                var esz = Math.max(parsed.auxSizes[sampleIndex], 8);
                var entry = aux.subarray(auxIndex, auxIndex + esz);
                var plan = cencSubsamplePlan(entry, sz), iv = cencIV(entry, plan);
                regions.push({start: current, size: sz, iv: iv, plan: plan});
                current += sz; sampleIndex++; auxIndex += esz;
            }
        }
    }
    if (!regions.length) throw new Error('MP4 没有可解密的 CENC 样本');
    if (!sawVideo) throw new Error('MP4 中没有视频轨');
    var moovBuf = result.slice(moovStart, moovStart + moovSize);
    restoreCodecsAndSinf(moovBuf);
    if (!hasVideoTrack(moovBuf)) throw new Error('视轨解析失败');
    if (!videoPlayable(moovBuf)) throw new Error('视轨编码不受支持');
    result.set(moovBuf, moovStart);
    regions.sort(function (a, b) { return a.start - b.start; });
    // dec 初始化为密文副本：明文区间（moov 等）本来就是正确的，
    // 流式 pull 时只把解密后的样本写回 dec，全部完成后即可作为完整明文缓存。
    var dec = result.slice(), decDone = new Uint8Array(regions.length), decovered = new Array(regions.length);
    var decBits = [];
    for (var di = 0; di < regions.length; di++) {
        decovered[di] = regions[di].start;
        decBits.push(new Uint8Array(Math.ceil(regions[di].size / 8)));
    }
    // remaining 用共享对象保存：每个 Range 请求克隆会话时仍指向同一份计数，
    // 完成判定不再需要每次遍历几千个样本。
    return {data: result, regions: regions, aes: aes, key: '',
        dec: dec, decDone: decDone, decovered: decovered, decBits: decBits,
        decState: {remaining: regions.length, cached: false}, cached: false};
}

// 每个 Range 请求共享同一份已下载的源/解密缓冲，只保留独立的遍历游标。
// 解密结果写入新分配的 chunk，不修改源数据，因此重叠 Range 也不会二次 XOR。
function cloneCencSession(src, start) {
    return {remote: !!src.remote, url: src.url || '', total: src.total || 0,
        moovStart: src.moovStart || 0, moov: src.moov || null, fetch: src.fetch || null,
        data: src.data, regions: src.regions, aes: src.aes,
        key: src.key || '', next: firstRegionAfter(src.regions, start || 0),
        dec: src.dec, decDone: src.decDone, decovered: src.decovered, decBits: src.decBits || null,
        decState: src.decState || null, cached: src.cached};
}

function decryptCencAll(session) {
    for (var i = 0; i < session.regions.length; i++) {
        var r = session.regions[i];
        var plain = cencDecryptSlice(session.aes, r.iv,
            session.data.subarray(r.start, r.start + r.size), r.plan,
            0, r.size, new Uint8Array(r.size), 0);
        session.data.set(plain, r.start);
    }
    return session.data;
}

// 按输出顺序生成字节：明文区间直接引用源数据，加密样本按 1MB 切片解密后输出。
// 与 Python _STREAM_CHUNK 一致，避免每 64KB 触发一次 JS/Java 回调造成播放卡顿。
async function* cencByteStream(session, start, end) {
    var total = session.data.length;
    if (!start || start < 0) start = 0;
    if (end === undefined || end === null || end < 0 || end >= total) end = total - 1;
    if (start >= total || end < start) return;
    // 与 Python 的 _STREAM_CHUNK 对齐：1MB 一块，减少 JS/Java pull 回调次数。
    var pos = start, chunk = HG_STREAM_CHUNK;
    while (pos <= end) {
        var region = session.regions[session.next];
        while (region && region.start + region.size <= pos) {
            session.next++;
            region = session.regions[session.next];
        }
        var gapEnd = !region ? end + 1 : Math.min(region.start, end + 1);
        if (gapEnd < pos) gapEnd = pos;
        while (pos < gapEnd) {
            var n = Math.min(chunk, gapEnd - pos);
            // 明文区间直接给视图，由 net.streamBody 在跨界时复制一次；
            // 不再多一次 .slice()，减少大块播放时的内存分配和 GC。
            yield session.data.subarray(pos, pos + n);
            pos += n;
        }
        if (pos > end) break;
        if (!region || region.start > pos) continue;
        var regionIdx = session.next;
        var lim = Math.min(region.start + region.size, end + 1);
        var sample = session.data.subarray(region.start, region.start + region.size);
        while (pos < lim) {
            var m = Math.min(chunk, lim - pos);
            var out = cencDecryptSlice(session.aes, region.iv, sample, region.plan,
                pos - region.start, pos + m - region.start, new Uint8Array(m), 0);
            if (session.dec && session.decovered && session.decBits) {
                // 任意顺序的 Range 都先写入；bitset 记录样本内已解密字节，
                // 之后把连续前缀推进到第一个空洞，乱序探测也能拼出完整明文。
                session.dec.set(out, pos);
                var bits = session.decBits[regionIdx];
                decBitsMark(bits, pos - region.start, pos + m - region.start);
                var covered = session.decovered[regionIdx], regionEnd = region.start + region.size;
                while (covered < regionEnd) {
                    var rel = covered - region.start;
                    if (!(bits[rel >> 3] & (1 << (rel & 7)))) break;
                    covered++;
                }
                session.decovered[regionIdx] = covered;
                if (covered >= regionEnd && !session.decDone[regionIdx]) {
                    session.decDone[regionIdx] = 1;
                    if (session.decState) session.decState.remaining--;
                }
            }
            yield out;
            pos += m;
        }
        session.next++;
    }
    // 全部样本解密完成后把完整明文放入缓存；后续 Range 请求直接走明文快路径，
    // 不再产生任何 AES 解密或 per-chunk JS 回调。
    if (session.dec && session.key && session.decState &&
        session.decState.remaining === 0 && !session.decState.cached) {
        cachePut(session.key, session.dec);
        session.decState.cached = true;
        session.cached = true;
        // 明文已经持有同一份缓冲，释放源缓存里的密文副本，降低 GC 压力。
        dropSource(session.key);
    }
}

// Python 同款流式会话：只拿 moov + CENC 辅助信息，播放时按 Range 取密文再解密。
// 会话只有几 MB，因此换集可以提前预热当前集和下一集，首字节不再等整集下载。
async function buildRemoteCencSession(info, contentKey, fetcher, cacheKey) {
    var rawMoov = u8(info.moov).slice();
    var range = moovContent(rawMoov), tracks = iterBoxes(rawMoov, range[0], range[1]);
    var aes = new Aes(contentKey), regions = [], sawVideo = false, videoSamples = 0;
    for (var t = 0; t < tracks.length; t++) {
        if (tracks[t][2] !== 'trak') continue;
        var ti = trackInfo(rawMoov, tracks[t][0], tracks[t][1]);
        if (ti.handler === 'vide') sawVideo = true;
        var parsed = parseTrack(rawMoov, tracks[t][0], tracks[t][1]);
        if (!parsed || !parsed.sampleCount || parsed.auxOffset < 0) continue;
        var auxLen = 0;
        for (var q = 0; q < parsed.auxSizes.length; q++) auxLen += Math.max(parsed.auxSizes[q], 8);
        if (!auxLen) continue;
        var aux, local = parsed.auxOffset - info.moovStart;
        if (local >= 0 && local + auxLen <= rawMoov.length) {
            aux = rawMoov.subarray(local, local + auxLen);
        } else {
            var got = await fetcher(parsed.auxOffset, parsed.auxOffset + auxLen - 1);
            aux = got.bytes;
            if (!aux || aux.length !== auxLen) throw new Error('CENC 辅助信息分片长度不符');
        }
        var sampleIndex = 0, auxIndex = 0;
        for (var ci = 0; ci < parsed.offsets.length; ci++) {
            var current = parsed.offsets[ci];
            for (var s = 0; s < parsed.chunkCounts[ci]; s++) {
                if (sampleIndex >= parsed.sampleCount || sampleIndex >= parsed.sizes.length) break;
                if (sampleIndex >= parsed.auxSizes.length) break;
                var sz = parsed.sizes[sampleIndex];
                var esz = Math.max(parsed.auxSizes[sampleIndex], 8);
                var entry = aux.subarray(auxIndex, auxIndex + esz);
                var plan = cencSubsamplePlan(entry, sz), iv = cencIV(entry, plan);
                regions.push({start: current, size: sz, iv: iv, plan: plan});
                if (ti.handler === 'vide') videoSamples++;
                current += sz; sampleIndex++; auxIndex += esz;
            }
        }
    }
    if (!regions.length) throw new Error('moov 中没有可解密的 CENC 样本');
    if (!sawVideo || !videoSamples) throw new Error('moov 中没有可解密的视轨');
    var moovPatch = rawMoov.slice();
    restoreCodecsAndSinf(moovPatch);
    if (!hasVideoTrack(moovPatch)) throw new Error('视轨解析失败');
    if (!videoPlayable(moovPatch)) throw new Error('视轨编码不受支持');
    regions.sort(function (a, b) { return a.start - b.start; });
    return {remote: true, url: info.url, total: info.total,
        moovStart: info.moovStart, moov: moovPatch, data: null,
        regions: regions, aes: aes, key: cacheKey || '', fetch: fetcher, next: 0};
}

// 按需取密文并解密；moov 区间直接返回修复后的明文盒。
async function* cencRemoteByteStream(session, start, end) {
    var total = session.total;
    if (!start || start < 0) start = 0;
    if (end === undefined || end === null || end < 0 || end >= total) end = total - 1;
    if (start >= total || end < start) return;
    var pos = start, chunk = HG_FETCH_CHUNK;
    var moovStart = session.moovStart, moovEnd = moovStart + session.moov.length;
    while (pos <= end) {
        if (pos >= moovStart && pos < moovEnd) {
            var moovLim = Math.min(moovEnd, end + 1);
            yield session.moov.subarray(pos - moovStart, moovLim - moovStart).slice();
            pos = moovLim;
            continue;
        }
        var region = session.regions[session.next];
        while (region && region.start + region.size <= pos) {
            session.next++;
            region = session.regions[session.next];
        }
        var gapEnd = !region ? end + 1 : Math.min(region.start, end + 1);
        if (moovStart > pos && moovStart < gapEnd) gapEnd = moovStart;
        if (gapEnd < pos) gapEnd = pos;
        while (pos < gapEnd) {
            var n = Math.min(chunk, gapEnd - pos);
            var gap = await session.fetch(pos, pos + n - 1);
            yield gap.bytes.slice();
            pos += n;
        }
        if (pos > end) break;
        if (pos >= moovStart && pos < moovEnd) continue;
        if (!region || region.start > pos) continue;
        var lim = Math.min(region.start + region.size, end + 1);
        if (moovStart > pos && moovStart < lim) lim = moovStart;
        while (pos < lim) {
            var m = Math.min(chunk, lim - pos);
            var raw = await session.fetch(pos, pos + m - 1);
            var fromRel = pos - region.start, toRel = pos + m - region.start;
            var out = cencDecryptSlice(session.aes, region.iv, raw.bytes, region.plan,
                fromRel, toRel, new Uint8Array(m), 0, fromRel);
            yield out;
            pos += m;
        }
        session.next++;
    }
}

function decryptMp4Cenc(data, contentKey) {
    return decryptCencAll(buildCencSession(data, contentKey));
}

// ===========================================================================
// 页面 / API 辅助
// ===========================================================================
function parseRouterData(html) {
    var m = /(?:window\.)?_ROUTER_DATA\s*=\s*/.exec(String(html || ''));
    if (!m) return {};
    var start = m.index + m[0].length;
    while (start < html.length && html[start] !== '{' && html[start] !== '[') start++;
    if (start >= html.length) return {};
    var depth = 0, inStr = false, esc = false, quote = '';
    for (var i = start; i < html.length; i++) {
        var ch = html.charAt(i);
        if (inStr) {
            if (esc) esc = false;
            else if (ch === '\\') esc = true;
            else if (ch === quote) inStr = false;
            continue;
        }
        if (ch === '"' || ch === "'") { inStr = true; quote = ch; continue; }
        if (ch === '{' || ch === '[') depth++;
        else if (ch === '}' || ch === ']') {
            depth--;
            if (depth === 0) {
                try { return JSON.parse(html.substring(start, i + 1)); } catch (e) { return {}; }
            }
        }
    }
    return {};
}

function routeOf(tid) {
    var t = String(tid == null ? '' : tid).trim();
    for (var i = 0; i < CONTENT_TYPES.length; i++) if (CONTENT_TYPES[i][0] === t) return t;
    return ROUTE_ALIAS[t] || 'real-drama';
}
function itemOf(x) {
    x = x || {};
    var vd = (x.video_data && typeof x.video_data === 'object') ? x.video_data : x;
    function first() { for (var i = 0; i < arguments.length; i++) if (arguments[i]) return arguments[i]; return ''; }
    var sid = String(first(vd.series_id, x.series_id, x.keyword, vd.keyword));
    var name = String(first(vd.series_title, vd.series_name, x.series_name, x.name, '未命名'));
    var count = first(vd.episode_cnt, x.episode_cnt, 0);
    return {
        vod_id: sid,
        vod_name: name,
        vod_pic: String(first(vd.series_cover, x.series_cover, x.background_cover, x.background_cover_pc)),
        vod_remarks: count ? ('全' + count + '集') : '',
        vod_content: String(first(vd.series_intro, x.series_intro)),
    };
}
function splitEpisodeToken(token) {
    var body = String(token || '');
    if (body.indexOf(EPISODE_PREFIX) === 0) body = body.substring(EPISODE_PREFIX.length);
    var p = body.indexOf(':');
    if (p >= 0) {
        var head = body.substring(0, p);
        if (/^\d+$/.test(head)) return [head, body.substring(p + 1)];
    }
    return ['1080', body];
}
function modelFromResponse(result, vid) {
    if (!result || typeof result !== 'object') throw new Error('video_model 数据为空');
    var data = result.data !== undefined ? result.data : result;
    if (Array.isArray(data)) { for (var i = 0; i < data.length; i++) if (data[i] && typeof data[i] === 'object') { data = data[i]; break; } }
    if (!data || typeof data !== 'object') throw new Error('video_model 数据为空');
    var entry = data[String(vid)];
    if (entry === undefined || entry === null) {
        var keys = Object.keys(data);
        for (var k = 0; k < keys.length; k++) {
            var v = data[keys[k]];
            if (v && typeof v === 'object' && !Array.isArray(v)) { entry = v; break; }
            if (Array.isArray(v) && v.length && v[0] && typeof v[0] === 'object') { entry = v[0]; break; }
        }
    }
    if (Array.isArray(entry)) { for (var j = 0; j < entry.length; j++) if (entry[j] && typeof entry[j] === 'object') { entry = entry[j]; break; } }
    if (!entry || typeof entry !== 'object') entry = data;
    var raw = entry.video_model !== undefined ? entry.video_model : data.video_model;
    if (raw === undefined || raw === null) {
        var hit = ['video_list', 'dynamic_video_list', 'dynamic_video', 'video_info', 'data'].some(function (key) { return Object.prototype.hasOwnProperty.call(entry, key); });
        if (hit) raw = entry;
    }
    if (typeof raw === 'string') { try { raw = JSON.parse(raw); } catch (e) { throw new Error('video_model JSON 无效'); } }
    if (!raw || typeof raw !== 'object') throw new Error('video_model 为空');
    return raw;
}
function videoListFromModel(model) {
    var keys = ['video_list', 'dynamic_video_list'];
    for (var i = 0; i < keys.length; i++) if (model[keys[i]] !== undefined && model[keys[i]] !== null) return model[keys[i]];
    if (model.dynamic_video && typeof model.dynamic_video === 'object') {
        var d = model.dynamic_video;
        var ks = ['dynamic_video_list', 'video_list', 'list'];
        for (var j = 0; j < ks.length; j++) if (d[ks[j]] !== undefined && d[ks[j]] !== null) return d[ks[j]];
    }
    if (model.video_info && typeof model.video_info === 'object' && model.video_info.data && typeof model.video_info.data === 'object')
        return videoListFromModel(model.video_info.data);
    if (model.data && typeof model.data === 'object') return videoListFromModel(model.data);
    return null;
}
function firstNonNull() { for (var i = 0; i < arguments.length; i++) if (arguments[i] !== undefined && arguments[i] !== null && arguments[i] !== '') return arguments[i]; return ''; }
function mediaUrl(item) {
    return firstNonNull(item.main_url, item.backup_url, item.backup_url_1, item.play_addr, item.url);
}
function spadeValue(item) {
    var info = (item.encrypt_info && typeof item.encrypt_info === 'object') ? item.encrypt_info : {};
    return firstNonNull(item.spade_a, info.spade_a);
}
function definitionOf(item) {
    if (!item || typeof item !== 'object') return '';
    var meta = (item.video_meta && typeof item.video_meta === 'object') ? item.video_meta : {};
    var vals = [item.definition, item.definition_code, item.video_definition, item.definition_type,
        item.vheight, item.height, item.quality, item.gear_name, item.quality_name, item.p,
        meta.definition, meta.vheight, meta.height, meta.quality];
    for (var i = 0; i < vals.length; i++) { var h = qualityHint(vals[i]); if (h) return h; }
    return '';
}
function selectQuality(videoList, wanted) {
    function rows(value, hinted) {
        var out = [];
        if (Array.isArray(value)) { for (var i = 0; i < value.length; i++) out = out.concat(rows(value[i], hinted)); return out; }
        if (!value || typeof value !== 'object') return out;
        var keys = ['main_url', 'backup_url', 'backup_url_1', 'play_addr', 'spade_a', 'encrypt_info'];
        for (var k = 0; k < keys.length; k++) if (Object.prototype.hasOwnProperty.call(value, keys[k])) return [[hinted || '', value]];
        var names = Object.keys(value);
        for (var j = 0; j < names.length; j++) {
            var key = names[j], v = value[key];
            if (['dynamic_video', 'video_info', 'data'].indexOf(key) >= 0 && v && typeof v === 'object') { out = out.concat(rows(v, hinted)); continue; }
            if (['video_list', 'dynamic_video_list', 'list'].indexOf(key) >= 0) { out = out.concat(rows(v, qualityHint(key))); continue; }
            if (v && typeof v === 'object') out = out.concat(rows(v, qualityHint(key)));
        }
        return out;
    }
    var candidates = rows(videoList, ''), map = {};
    for (var i = 0; i < candidates.length; i++) {
        var def = definitionOf(candidates[i][1]) || qualityHint(candidates[i][0]) || ('idx' + i);
        if (!map[def]) map[def] = candidates[i][1];
    }
    var defs = Object.keys(map);
    if (!defs.length) throw new Error('播放模型没有清晰度');
    var req = qualityHint(wanted) || '1080';
    var order = [req];
    for (var q = 0; q < QUALITY_ORDER.length; q++) if (QUALITY_ORDER[q] !== req) order.push(QUALITY_ORDER[q]);
    for (var o = 0; o < order.length; o++) if (map[order[o]]) return map[order[o]];
    defs.sort(function (a, b) { return parseInt((b.match(/\d+/) || [0])[0]) - parseInt((a.match(/\d+/) || [0])[0]); });
    return map[defs[0]];
}
function keySeedFromModel(model) {
    var v = String(model.key_seed == null ? '' : model.key_seed).trim();
    if (v) return b64dec(v);
    var nested = ['dynamic_video', 'video_info', 'data'];
    for (var i = 0; i < nested.length; i++) {
        if (model[nested[i]] && typeof model[nested[i]] === 'object') {
            var r = keySeedFromModel(model[nested[i]]);
            if (r && r.length) return r;
        }
    }
    return new Uint8Array(0);
}

// ===========================================================================
// Android v5 播放器签名链路（当前唯一可用的取流入口）
// 说明：公开无签名入口目前返回 HTTP 200 + 0 字节，PY 已切到 player/v1；
// 这里逐条移植 PY 的 SM3 / MD5 / f13 / medusa / helios / carrier。
// ===========================================================================
function md5(data) {
    var msg = u8(data).slice(), bitLen = BigInt(msg.length) * 8n;
    var total = Math.ceil((msg.length + 9) / 64) * 64;
    var buf = new Uint8Array(total);
    buf.set(msg); buf[msg.length] = 0x80;
    var l = bitLen;
    for (var i = 0; i < 8; i++) { buf[total - 8 + i] = Number(l & 255n); l >>= 8n; }
    var s = [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476];
    var K = [];
    for (var ki = 0; ki < 64; ki++) K.push(Math.floor(Math.abs(Math.sin(ki + 1)) * 4294967296) >>> 0);
    var S = [7,12,17,22,7,12,17,22,7,12,17,22,7,12,17,22,
        5,9,14,20,5,9,14,20,5,9,14,20,5,9,14,20,
        4,11,16,23,4,11,16,23,4,11,16,23,4,11,16,23,
        6,10,15,21,6,10,15,21,6,10,15,21,6,10,15,21];
    function rol(v, n) { return ((v << n) | (v >>> (32 - n))) >>> 0; }
    for (var off = 0; off < total; off += 64) {
        var m = [];
        for (var j = 0; j < 16; j++) m.push(readU32LE(buf, off + j * 4));
        var a = s[0], b = s[1], c = s[2], d = s[3];
        for (var k = 0; k < 64; k++) {
            var f, g;
            if (k < 16) { f = (b & c) | (~b & d); g = k; }
            else if (k < 32) { f = (d & b) | (~d & c); g = (5 * k + 1) & 15; }
            else if (k < 48) { f = b ^ c ^ d; g = (3 * k + 5) & 15; }
            else { f = c ^ (b | ~d); g = (7 * k) & 15; }
            var tmp = (d >>> 0);
            d = c; c = b;
            b = (b + rol((a + f + K[k] + m[g]) >>> 0, S[k])) >>> 0;
            a = tmp;
        }
        s[0] = (s[0] + a) >>> 0; s[1] = (s[1] + b) >>> 0;
        s[2] = (s[2] + c) >>> 0; s[3] = (s[3] + d) >>> 0;
    }
    var out = new Uint8Array(16);
    for (var q = 0; q < 4; q++) {
        out[q * 4] = s[q] & 255; out[q * 4 + 1] = (s[q] >>> 8) & 255;
        out[q * 4 + 2] = (s[q] >>> 16) & 255; out[q * 4 + 3] = (s[q] >>> 24) & 255;
    }
    return out;
}
function md5Hex(data) { return bytesToHex(md5(data)); }

var SM3_W = new Uint32Array(68);
function sm3(data) {
    // 签名时 v5Sign 会循环调用本函数几十到几百次；老实现每轮用 BigInt 和 push 数组，
    // 电视盒上一次签名要数秒并堵住整个 JS 线程。这里改成定长 TypedArray + Number 位长。
    var msg = u8(data), len = msg.length;
    var total = Math.ceil((len + 9) / 64) * 64;
    var buf = new Uint8Array(total);
    buf.set(msg); buf[len] = 0x80;
    var bits = len * 8;
    buf[total - 4] = (bits >>> 24) & 255;
    buf[total - 3] = (bits >>> 16) & 255;
    buf[total - 2] = (bits >>> 8) & 255;
    buf[total - 1] = bits & 255;
    var iv = [0x7380166f, 0x4914b2b9, 0x172442d7, 0xda8a0600,
        0xa96f30bc, 0x163138aa, 0xe38dee4d, 0xb0fb0e4e];
    function rol(v, n) { return ((v << n) | (v >>> (32 - n))) >>> 0; }
    var w = SM3_W;
    for (var off = 0; off < total; off += 64) {
        for (var j = 0; j < 16; j++) w[j] = readU32(buf, off + j * 4);
        for (var t = 16; t < 68; t++) {
            var x = (w[t - 16] ^ w[t - 9] ^ rol(w[t - 3], 15)) >>> 0;
            w[t] = (x ^ rol(x, 15) ^ rol(x, 23) ^ rol(w[t - 13], 7) ^ w[t - 6]) >>> 0;
        }
        var a = iv[0], b = iv[1], c = iv[2], d = iv[3], e = iv[4], f = iv[5], g = iv[6], h = iv[7];
        for (var k = 0; k < 64; k++) {
            var tj = k < 16 ? 0x79cc4519 : 0x7a879d8a;
            var a12 = rol(a, 12);
            var ss1 = rol((a12 + e + rol(tj, k % 32)) >>> 0, 7);
            var ss2 = (ss1 ^ a12) >>> 0;
            var ff = k < 16 ? (a ^ b ^ c) : (((a & b) | (a & c) | (b & c)) >>> 0);
            var gg = k < 16 ? (e ^ f ^ g) : (((e & f) | ((~e >>> 0) & g)) >>> 0);
            var tt1 = (ff + d + ss2 + (w[k] ^ w[k + 4])) >>> 0;
            var tt2 = (gg + h + ss1 + w[k]) >>> 0;
            d = c; c = rol(b, 9); b = a; a = tt1;
            h = g; g = rol(f, 19); f = e;
            e = (tt2 ^ rol(tt2, 9) ^ rol(tt2, 17)) >>> 0;
        }
        iv = [(iv[0] ^ a) >>> 0, (iv[1] ^ b) >>> 0, (iv[2] ^ c) >>> 0, (iv[3] ^ d) >>> 0,
            (iv[4] ^ e) >>> 0, (iv[5] ^ f) >>> 0, (iv[6] ^ g) >>> 0, (iv[7] ^ h) >>> 0];
    }
    var out = new Uint8Array(32);
    for (var q = 0; q < 8; q++) {
        out[q * 4] = (iv[q] >>> 24) & 255; out[q * 4 + 1] = (iv[q] >>> 16) & 255;
        out[q * 4 + 2] = (iv[q] >>> 8) & 255; out[q * 4 + 3] = iv[q] & 255;
    }
    return out;
}

function b64enc(data) {
    var x = u8(data), tbl = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/', out = '';
    for (var i = 0; i < x.length; i += 3) {
        var a = x[i], b = i + 1 < x.length ? x[i + 1] : 0, c = i + 2 < x.length ? x[i + 2] : 0;
        out += tbl.charAt(a >>> 2) + tbl.charAt(((a & 3) << 4) | (b >>> 4));
        out += i + 1 < x.length ? tbl.charAt(((b & 15) << 2) | (c >>> 6)) : '=';
        out += i + 2 < x.length ? tbl.charAt(c & 63) : '=';
    }
    return out;
}
function b64urlenc(data) { return b64enc(data).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); }

var CRC32_TABLE = (function () {
    var t = new Uint32Array(256);
    for (var i = 0; i < 256; i++) {
        var c = i;
        for (var j = 0; j < 8; j++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
        t[i] = c >>> 0;
    }
    return t;
})();
function crc32(data) {
    var x = u8(data), c = 0xffffffff;
    for (var i = 0; i < x.length; i++) c = CRC32_TABLE[(c ^ x[i]) & 255] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
}
function gzipStored(data, mtime) {
    var x = u8(data), out = [];
    var mt = (mtime === undefined ? 0 : mtime) >>> 0;
    var head = [0x1f, 0x8b, 0x08, 0x00, mt & 255, (mt >>> 8) & 255,
        (mt >>> 16) & 255, (mt >>> 24) & 255, 0, 0x03];
    for (var i = 0; i < head.length; i++) out.push(head[i]);
    for (var off = 0; off < x.length; off += 65535) {
        var end = Math.min(off + 65535, x.length), len = end - off, last = end === x.length ? 1 : 0;
        out.push(last, len & 255, (len >>> 8) & 255, (~len) & 255, ((~len) >>> 8) & 255);
        for (var j = off; j < end; j++) out.push(x[j]);
    }
    if (!x.length) out.push(1, 0, 0, 255, 255);
    var crc = crc32(x), size = x.length >>> 0;
    out.push(crc & 255, (crc >>> 8) & 255, (crc >>> 16) & 255, (crc >>> 24) & 255);
    out.push(size & 255, (size >>> 8) & 255, (size >>> 16) & 255, (size >>> 24) & 255);
    return new Uint8Array(out);
}

var V5_SBOX = hexdec(
    '53290fe9e51f316f90f74a7e034d367784ab49237cd0135cdc632c322fd3be0e2624a417ecd9151a7ff64f60730a87f9' +
    '445ec6ada2f865d22b696c4188f24c0df37b75510b939f6bc2fe6883e68bc8c722181ba0bdb08c9871b50c9a16b46eea' +
    '8eed20ba4b8a14e0fcf1468dbbef05a93e5a9d7dcf06898635c1fd99f5de287a80c594daaab19b6279fbd75070cb52eb' +
    '2555c456e39e7839853874e2f0013ac0b64742d8ca10e4b79c955de8b843ce4ed464a6a72ed508091c92e7b3eedd1e1d' +
    'd12afac321618fa3d65f9167c982f43d66a53c6a1997585b346dbf9672ff37cdbc073b2dae11453304df00815476b2a1' +
    '3fccdb30b957a8acafe127400248591238922563e36406d37a24100b7902a028044e218453c2a399199c9d13dc40c55b' +
    'a67e502273850ebdc1a2e2188b8f2d9e3cb909b8c46a2a9f4a6dd93007eafa65b7b3a881aa908cc74f0ad76bbbb58617' +
    'c37012ca05a469fd44e62eecf1e4272ce860c0ae5eadf99b20d8f0234174006f3f110d7657d01645d4eff8f71471cbfe' +
    '1cb2f52648727bf3c9de55153e031b4d61757db63dbf7782eeafe9018a8891362fb14759ac32bab03b349aeb5a377c51' +
    '56be4c8dfbe13a684bda39cf836697c894545fe0f2491acea9fc6252f4ff1e0fe72bd2df6e67a7f635e5bcc6d1a5dd95' +
    '1d89960887a18eb40c785cdb1f80ed42299333ab98cdd67f316cd54346585dccd759fb722789b08807cc0fda293f7e5e' +
    '1819bb0353517020b31d3d00374952bea2c421e862040a9ec892a05b266b7a0d0cc316f483b81af39715657ffe32ad8d' +
    'e0c13077646035236ee5363e5f900e9a7cf850a81cd9960b6df73317226f99eaa6fff15cec34acb98246639b918ab285' +
    '1466a7cdfc4ad1b52c2ae95a58d3734e47ddd5b7560193f644ef9c408b7dee39b4d6aabf4de761e3252d4c7ba3843187' +
    '745d55e6a5db05d42b45caed43c0c5d0b64bfa9d94a4a9d8f2f0e1a108dcfd288fd2bc1fc7bd675412138169cb092498' +
    '75ba3b68cfb11180afae104fc9789571c6dfce02413886796ae21e3c488cc21b9f423a066c2eabf98e2fdeeb5776e4f5' +
    'd09a515ba58cbbab3e37b09fd4f6d9244df80512e84cd7956be301cf64f1429d58577cc241f3a2c655144f81aaf95a4e' +
    '108da894b38970561ae9002619fbbac91fa922ed202bfc62cb08e0de2a7f3631435f8b47c8a3c563b4db4071ce74c46d' +
    'a6fa696a9e282d1e825d663b93bfd56c48dce1884bb10fccea063929f746443fd830a4232e53da21a1f2d1bdfebc3a02' +
    'c10a1b8ad31d04fd616590d272ac737e98eb33af60528716bee78ec0ee8699031177277d9cff32542c67caf5f4459168' +
    '1335ae0e178f3409a7803db83892dde5b9b7f0c750e24aef077badd678a09b850b84ec1597e4963cb5e675df1c0d6fb6' +
    '18496ecd76c35c798325590c2fb27a5e'
);
var V5_HASH_TABLE = [
    0xebb64faf,0x07aadcc2,0xcf3187bf,0xe01138ff,0x6d0bfcff,0x5a30a3be,0xb41ad638,0x34180eb8,
    0xf233eb6f,0xb1a584cc,0xccc30dc7,0x47d1db51,0xd55653de,0x70a84fa1,0x57473c12,0xf76f0288,
    0x2c077f0a,0xda0dcad0,0xfbb86f6c,0xfdc4cf00,0x688a020d,0xe676c6a6,0x8cd6338b,0x1a3c8d0e,
    0xcce8b06b,0x6ad0ed0b,0xa0522717,0xdc71ac83,0x2285db71,0xd5b4dda6,0x736f8650,0x6560306c,
    0x617ce2a6,0xe423417e,0x0a40e143,0x544e4032,0x88dffb2a,0x716c1ae0,0x4c467a88,0x05b23bb3,
    0xe1d0b866,0xbaa3dcb8,0xae3374d3,0xc3381a50,0x1702f75b,0xfe6da368,0xf0b4cf48,0x4e0ffbb8,
    0x72aad10d,0x26c53a3d,0xf2bce0f6,0xb4557581,0x4a257fdd,0x8c3182a2,0xab0b3b86,0x3d5dfb14,
    0x4f103634,0xd37b52d7,0x444eff16,0xeb0a33d1,0x6ca86f6e,0x0284ba7,0x08387cfa,0x5fb37586,
];
var V5_MAGIC = hexdec('2d4b4fca49750d433fb5ae2c226dcc56');
var V5_SIGN_KEY = hexdec('b23c2a470a20d105dc3f8c4438f8272ed46d6c89ffdcdedd5108698d26e9489d');
var V5_PROCESS_NONCE = b64urlenc(Array.from({length: 18}, function () { return Math.floor(Math.random() * 256); }));
var V5_PROCESS_STARTED = Date.now();
var V5_MASK64 = 0xffffffffffffffffn;

function v5Rol32(v, n) { n &= 31; return (((v << n) | (v >>> ((32 - n) & 31))) >>> 0); }
function v5Ror32(v, n) { return v5Rol32(v, 32 - (n & 31)); }
function v5Ror64(v, n) { n &= 63n; return ((v >> n) | (v << (64n - n))) & V5_MASK64; }
function v5Le32(v) {
    var x = BigInt.asUintN(32, BigInt(v)), out = new Uint8Array(4);
    for (var i = 0; i < 4; i++) out[i] = Number((x >> BigInt(8 * i)) & 255n);
    return out;
}
function v5Xor(a, b) {
    var x = u8(a), y = u8(b), n = Math.min(x.length, y.length), out = new Uint8Array(n);
    for (var i = 0; i < n; i++) out[i] = x[i] ^ y[i];
    return out;
}
function v5Varint(value) {
    var n = BigInt(value), out = [];
    while (n > 127n) { out.push(Number((n & 127n) | 128n)); n >>= 7n; }
    out.push(Number(n));
    return new Uint8Array(out);
}
function v5Proto(fields) {
    var parts = [];
    for (var i = 0; i < fields.length; i++) {
        var tag = fields[i][0], value = fields[i][1], kind = fields[i][2];
        if (kind === 'sint') {
            var n = BigInt(value), zz = n < 0n ? ((-n * 2n) - 1n) : (n * 2n);
            parts.push(v5Varint(tag * 8), v5Varint(zz));
            continue;
        }
        var raw = typeof value === 'string' ? utf8enc(value) : u8(value);
        if (!raw.length) continue;
        parts.push(v5Varint(tag * 8 + 2), v5Varint(raw.length), raw);
    }
    var total = 0;
    for (var j = 0; j < parts.length; j++) total += parts[j].length;
    var out = new Uint8Array(total), pos = 0;
    for (var k = 0; k < parts.length; k++) { out.set(parts[k], pos); pos += parts[k].length; }
    return out;
}
function v5GetIV(initial, data) {
    var value = initial >>> 0, d = u8(data);
    for (var i = 0; i < d.length; i++) {
        var byte = d[i];
        if ((i & 1) === 0) {
            value = ((value >>> 4) ^ value ^ ((value << 6) >>> 0) ^ byte) >>> 0;
        } else {
            var tmp = ((value >>> 7) ^ value ^ (byte | ((value << 12) >>> 0))) >>> 0;
            value = (~tmp) >>> 0;
        }
    }
    return value >>> 0;
}
function v5Branch(query, body, ts) {
    return v5GetIV(v5GetIV(v5GetIV(0x20230928, query), body), v5Le32(ts)) & 15;
}
function v5SumMd5(data) {
    var d = u8(data), check = 0x20220420;
    for (var i = 0; i < 12; i++) {
        var temp = ((check >>> ((i & 1) === 0 ? 3 : 5)) ^ check) >>> 0;
        var expr = (i & 1) === 0
            ? ((d[i] ^ ((check << 7) >>> 0)) >>> 0)
            : ((~((d[i] | ((check << 11) >>> 0)) >>> 0)) >>> 0);
        check = (expr ^ temp) >>> 0;
    }
    return ((check | 4) ^ 0x1000000) >>> 0;
}
function v5HashF13(query, body, ts) {
    if (v5Branch(query, body, ts) !== 12) throw new Error('Unsupported v5 hash branch');
    var seed = 0x9d4a97c2, count = (seed + ts) >>> 0;
    var table = V5_HASH_TABLE.map(function (v) { return v5Ror32(v, (count + 1) & 31); });
    var shift = (count + 2) & 7;
    var pad = new Uint8Array([0xfa, 0x45, 0x61, 0xd7]).map(function (v) { return ((v | (v << 8)) >>> shift) & 255; });
    var data = concatBytes(concatBytes(concatBytes(concatBytes(query, body), v5Le32(ts)), pad), hexdec('00000000000001a0'));
    var schedule = [];
    for (var i = 0; i + 4 <= data.length; i += 4) schedule.push(readU32(data, i));
    for (var n = 0; n < 112; n++) {
        var x = schedule[n + 1], y = schedule[n + 14];
        var value = (schedule[n] + schedule[n + 9]
            + (v5Rol32(x, 14) ^ v5Rol32(x, 25) ^ (x >>> 3))
            + (v5Rol32(y, 13) ^ v5Rol32(y, 15) ^ (y >>> 10))) >>> 0;
        schedule.push(value);
    }
    var initial = [0x7aba4fc8, 0x67166507, 0x6403fa00, 0x340f512f,
        984304912, 3005047866, 2874125293, 2152413264];
    initial = initial.map(function (v) { return v5Ror32(v, count & 31); });
    var state = initial.slice();
    for (var r = 0; r < 96; r++) {
        var base = seed + r;
        var n1 = ((state[4] ^ state[0]) & state[1]) ^ state[4];
        var n2 = v5Rol32(state[1], 26) ^ v5Rol32(state[1], 21) ^ v5Rol32(state[1], 7);
        var n4 = (schedule[base & 127] + n1 + n2 + table[base & 63] + state[6]) >>> 0;
        var n5 = v5Rol32(state[3], 30) ^ v5Rol32(state[3], 19) ^ v5Rol32(state[3], 10);
        var n6 = ((state[3] & state[5]) | ((state[3] | state[5]) & state[2])) >>> 0;
        var old = state[7];
        state = [state[7], state[0], state[1], state[2], state[3], state[4], state[5], state[6]];
        state[7] = (n5 + n6 + n4) >>> 0;
        state[0] = (old + n4) >>> 0;
    }
    var output = new Uint8Array(32);
    for (var o = 0; o < 8; o++) {
        var w = (state[o] + initial[o]) >>> 0;
        output[o * 4] = (w >>> 24) & 255; output[o * 4 + 1] = (w >>> 16) & 255;
        output[o * 4 + 2] = (w >>> 8) & 255; output[o * 4 + 3] = w & 255;
    }
    var folded = v5Xor(output.subarray(0, 16), output.subarray(16, 32));
    return concatBytes(folded, v5Le32((v5SumMd5(folded) | 0x20) >>> 0));
}

function V5Carrier(key, ts) {
    var word = ts & 3;
    this.box = V5_SBOX.subarray(word * 256, (word + 1) * 256);
    this.con = [[2,0,3,1], [1,3,2,0], [3,2,1,0], [2,3,1,0]][word];
    this.order = [
        [0,9,14,15,4,13,2,7,8,1,6,3,12,5,10,11],
        [0,9,14,11,4,13,2,3,8,1,6,15,12,5,10,7],
        [0,9,14,3,4,13,2,15,8,1,6,11,12,5,10,7],
        [0,9,14,15,4,13,2,3,8,1,6,11,12,5,10,7],
    ][word];
    var initial = [0xbbb5de72, 0xd4638d5b, 0x92a5f73b, 0x89f8a1c9][word];
    var base = v5Le32(initial), seed = new Uint8Array(48);
    for (var i = 0; i < 4; i++) seed.set(base, i * 4);
    var expanded = new Uint8Array(64);
    expanded.set(v5Xor(seed, key), 0);
    var rounds = 8;
    for (var n = 4; n < 12; n++) {
        var at = 4 * (n - 1);
        var a = expanded[at], b = expanded[at + 1], c = expanded[at + 2], d = expanded[at + 3];
        if ((n & 3) === 0) {
            var temp = ((initial >>> (rounds & 24)) ^ this.box[b]) & 255;
            b = this.box[c]; c = this.box[d]; d = this.box[a]; a = temp;
        }
        rounds += 2;
        expanded[at + 4] = a ^ expanded[at - 12];
        expanded[at + 5] = b ^ expanded[at - 11];
        expanded[at + 6] = c ^ expanded[at - 10];
        expanded[at + 7] = d ^ expanded[at - 9];
    }
    this.keys = [];
    for (var k = 0; k < 12; k++) this.keys.push(expanded.subarray(k * 4, k * 4 + 4));
}
V5Carrier.prototype.add = function (rows, offset) {
    for (var i = 0; i < 4; i++) for (var j = 0; j < 4; j++) rows[i][j] ^= this.keys[offset + i][this.con[j]];
};
V5Carrier.prototype.block = function (value) {
    var rows = [];
    for (var i = 0; i < 4; i++) rows.push([value[i * 4], value[i * 4 + 1], value[i * 4 + 2], value[i * 4 + 3]]);
    this.add(rows, 0);
    var self = this;
    for (var r = 1; r <= 2; r++) {
        var before = rows.map(function (row) { return row.map(function (v) { return self.box[v]; }); });
        var flat = [];
        for (var c = 0; c < 4; c++) flat = flat.concat(before[self.con[c]]);
        rows = [];
        for (var q = 0; q < 4; q++) rows.push([flat[self.order[q * 4]], flat[self.order[q * 4 + 1]],
            flat[self.order[q * 4 + 2]], flat[self.order[q * 4 + 3]]]);
        if (r === 1) {
            rows = rows.map(function (row) { return [row[self.con[0]], row[self.con[1]], row[self.con[2]], row[self.con[3]]]; });
            function xt(x) { return ((x << 1) ^ (x & 128 ? 0x1b : 0)) & 255; }
            for (var col = 0; col < 4; col++) {
                var t = rows[0][col] ^ rows[1][col] ^ rows[2][col] ^ rows[3][col], u = rows[0][col];
                rows[0][col] ^= t ^ xt(rows[0][col] ^ rows[1][col]);
                rows[1][col] ^= t ^ xt(rows[1][col] ^ rows[2][col]);
                rows[2][col] ^= t ^ xt(rows[2][col] ^ rows[3][col]);
                rows[3][col] ^= t ^ xt(rows[3][col] ^ u);
            }
        }
        this.add(rows, r * 4);
    }
    var out = new Uint8Array(16), pos = 0;
    for (var a = 0; a < 4; a++) for (var b = 0; b < 4; b++) {
        out[pos++] = rows[a][b] ^ this.keys[4 + a][b];
    }
    return out;
};
V5Carrier.prototype.encrypt = function (source, iv) {
    var src = u8(source);
    if (src.length < 248) throw new Error('V5 carrier requires at least 248 bytes');
    var wire = [6,5,3,4,2,7,1,0], compact = [1,7,3,6,2,0,4,5];
    var plaintext = new Uint8Array(32);
    for (var i = 0; i < 31; i++) for (var j = 0; j < 8; j++) {
        plaintext[i] |= ((src[i * 8 + j] >> wire[j]) & 1) << compact[j];
    }
    plaintext[31] = 1;
    var first = this.block(v5Xor(plaintext.subarray(0, 16), iv));
    var key = concatBytes(first, this.block(v5Xor(plaintext.subarray(16, 32), first)));
    var output = src.slice();
    for (var a = 0; a < 31; a++) for (var b = 0; b < 8; b++) {
        var at = a * 8 + b, mask = 0xff ^ (1 << wire[b]);
        output[at] = (output[at] & mask) | (((key[a] >> compact[b]) & 1) << wire[b]);
    }
    return concatBytes(key.subarray(31), output);
};
function v5Xmxor(data, key) {
    var d = u8(data), k = u8(key), encoded = new Uint8Array(d.length);
    for (var i = 0; i < d.length; i++) {
        var at = (i * 4) & 28, d0 = k[at], d1 = k[at + 1], value = d[i];
        var rot = ((value << 4) | (value >>> 4)) & 255;
        var v = ((~(rot + d0)) >>> 0) ^ d1;
        v = (((v & 255) << 3) | ((v & 255) >>> 5)) & 255;
        encoded[d.length - i - 1] = ((~(((v + d1) & 255) ^ d0)) >>> 0) & 255;
    }
    var last = encoded[encoded.length - 1] ^ encoded[encoded.length - 2];
    var first = encoded[0];
    encoded[0] = (((~last + first) >>> 0) & 255);
    encoded[1] = (((encoded[0] ^ encoded[encoded.length - 1] ^ 254) + encoded[1]) & 255);
    var rot1 = ((encoded[1] << 3) | (encoded[1] >>> 5)) & 255;
    encoded[2] = (encoded[2] + ((last - first) ^ rot1 ^ 2)) & 255;
    for (var n = 0; n < encoded.length - 4; n++) {
        var rot2 = ((encoded[n + 2] << 3) | (encoded[n + 2] >>> 5)) & 255;
        var temp = rot2 ^ encoded[n + 1] ^ (n + 3);
        encoded[n + 3] = ((~temp + encoded[n + 3]) >>> 0) & 255;
    }
    encoded[encoded.length - 1] ^= encoded[encoded.length - 2];
    var sum = 0;
    for (var s = 1; s < encoded.length; s++) sum = (sum + encoded[s]) & 255;
    encoded[0] = ((encoded[0] ^ encoded[1]) + sum) & 255;
    return encoded;
}
function v5Medusa(query, f13, ts, who, nonce) {
    var flags = new Uint8Array(8);
    var device = v5Proto([
        [1, 1, 'sint'], [2, 2, 'sint'], [3, '8662'], [4, who.device_id],
        [5, V5_PROCESS_NONCE], [6, '!noperm!'], [12, 'Asia/Shanghai,8'], [13, 'zh_CN'],
        [22, who.os_version], [25, V5_PROCESS_STARTED, 'sint'], [30, who.device_type],
        [31, 'HONOR'], [32, who.device_type], [34, 'HONOR'],
    ]);
    var env = v5Proto([
        [6, 'v04.10.03.04-bugfix'], [8, who.channel], [12, device], [14, who.version_name],
    ]);
    var message = v5Proto([
        [1, V5_MAGIC], [2, 5, 'sint'], [3, v5Random32(), 'sint'], [4, '8662'],
        [5, who.device_id], [6, '646637794'], [7, who.version_name],
        [8, 'v04.10.03-ml-android'], [9, 0x040a0300, 'sint'], [10, flags],
        [12, ts, 'sint'], [13, f13], [14, query.subarray(0, 6)],
        [15, v5Proto([[1,1,'sint'], [2,1,'sint'], [3,1,'sint'], [5,1,'sint']])],
        [17, ts, 'sint'], [20, 'none'], [21, 377, 'sint'], [23, env],
        [24, '{"cmr":16777216,"cmr2":16777216,"un_h":11,"vpn":0,"kd":0,"dyn":"","do":1,"tk":true}'],
    ]);
    if (nonce === undefined || nonce === null) nonce = v5Random32();
    nonce = nonce >>> 0;
    var high = (nonce >>> 16) & 255;
    var hashBytes = sm3(concatBytes(concatBytes(V5_SIGN_KEY, v5Le32(nonce)), V5_SIGN_KEY));
    var tmp = (((high << 11) | (nonce >>> 24)) ^ (high >>> 5) ^ high) >>> 0;
    var seed = v5Le32((~tmp) >>> 0);
    var transformed = concatBytes(flags, v5Xmxor(message, hashBytes)).slice();
    transformed.reverse();
    for (var i = 0; i < transformed.length; i++) transformed[i] ^= seed[(~i) & 3];
    var check = 0x18000001 | ((query[0] & 63) << 14) | ((f13[0] & 63) << 8);
    var packed = concatBytes(concatBytes(concatBytes(new Uint8Array([0xca]), v5Le32(v5Random32())), v5Le32(check)), transformed);
    packed = concatBytes(packed, new Uint8Array([(nonce >>> 16) & 255, (nonce >>> 24) & 255]));
    var encrypted = new V5Carrier(md5(V5_SIGN_KEY.subarray(0, 16)), ts).encrypt(packed, md5(V5_SIGN_KEY.subarray(16, 32)));
    var prefix = concatBytes(v5Le32(5), V5_MAGIC).slice(), timeBytes = v5Le32(ts);
    for (var p = 0; p < prefix.length; p++) prefix[p] ^= timeBytes[p & 3];
    var tail = new Uint8Array([nonce & 255, (nonce >>> 8) & 255, 0, 1]);
    return b64enc(concatBytes(concatBytes(prefix, tail), encrypted));
}
function v5Random32() {
    return (Math.floor(Math.random() * 256) | (Math.floor(Math.random() * 256) << 8)
        | (Math.floor(Math.random() * 256) << 16) | (Math.floor(Math.random() * 256) << 24)) >>> 0;
}
function v5Helios(ts, nonce) {
    if (nonce === undefined || nonce === null) nonce = v5Random32();
    nonce = nonce >>> 0;
    var ascii = utf8enc(md5Hex(concatBytes(v5Le32(nonce), utf8enc('8662'))));
    var words = [];
    for (var i = 0; i < 4; i++) {
        var w = 0n;
        for (var j = 7; j >= 0; j--) w = (w << 8n) | BigInt(ascii[i * 8 + j]);
        words.push(w & V5_MASK64);
    }
    var queue = [words[2], words[3]], table = [words[0]], b0 = words[0], b8 = words[1];
    for (var n = 0; n < 34; n++) {
        var value = ((v5Ror64(b8, 8n) + b0) & V5_MASK64) ^ BigInt(n);
        queue.push(value);
        value = (value ^ v5Ror64(b0, 61n)) & V5_MASK64;
        table.push(value); b0 = value; b8 = queue.shift();
    }
    var text = utf8enc(String(ts) + '-646637794-8662');
    var padding = 16 - (text.length % 16);
    var data = concatBytes(text, new Uint8Array(padding).fill(padding));
    var out = [];
    for (var off = 0; off < data.length; off += 16) {
        var a = 0n, b = 0n;
        for (var q = 7; q >= 0; q--) a = (a << 8n) | BigInt(data[off + q]);
        for (var r = 7; r >= 0; r--) b = (b << 8n) | BigInt(data[off + 8 + r]);
        for (var k = 0; k < 34; k++) {
            b = table[k] ^ ((a + v5Ror64(b, 8n)) & V5_MASK64);
            a = (b ^ v5Ror64(a, 61n)) & V5_MASK64;
        }
        for (var z = 0; z < 8; z++) { out.push(Number(a & 255n)); a >>= 8n; }
        for (var y = 0; y < 8; y++) { out.push(Number(b & 255n)); b >>= 8n; }
    }
    return b64enc(concatBytes(v5Le32(nonce), new Uint8Array(out)));
}
function v5Encode(value) {
    return encodeURIComponent(String(value)).replace(/[!'()]/g, function (c) {
        return '%' + c.charCodeAt(0).toString(16).toUpperCase();
    });
}
function v5Sign(base, values, body, now, nonce) {
    // GET 恢复请求没有正文：签名里用 16 字节全零，且不能带 x-ss-stub / req-ticket。
    var noBody = body === null || body === undefined;
    var ts = Math.floor(now / 1000);
    var bodyHash = noBody ? new Uint8Array(16) : md5(u8(body));
    var who = {};
    Object.keys(values).forEach(function (k) { who[k] = values[k]; });
    if (Object.prototype.hasOwnProperty.call(who, 'ts')) who.ts = String(ts);
    for (var offset = 0; offset < 1024; offset++) {
        var ticket = now + offset, qv = {};
        Object.keys(who).forEach(function (k) { qv[k] = who[k]; });
        qv._rticket = String(ticket);
        var query = Object.keys(qv).map(function (k) { return v5Encode(k) + '=' + v5Encode(qv[k]); }).join('&');
        var queryHash = sm3(utf8enc(query));
        if (v5Branch(queryHash, bodyHash, ts) !== 12) continue;
        var f13 = v5HashF13(queryHash, bodyHash, ts);
        var headers = {
            'x-khronos': String(ts),
            'x-helios': v5Helios(ts, nonce),
            'x-medusa': v5Medusa(queryHash, f13, ts, who, nonce),
        };
        if (!noBody) {
            headers['x-ss-stub'] = bytesToHex(bodyHash).toUpperCase();
            headers['x-ss-req-ticket'] = String(ticket);
        }
        return {url: base + '?' + query, headers: headers};
    }
    throw new Error('Unable to select V5 playback signature branch');
}

// ---- Native com.hgtv.star request generation (validated against Frida) ----
// The short medusa/carrier payload below is only used by the video_tab recovery path.
// Player requests now use the full native schema and native query template proven above.
var NATIVE_MEDUSA_A2 = hexdec('0485000000000000');
var NATIVE_MEDUSA_A3 = hexdec('b23c2a470a20d105dc3f8c4438f8272ed46d6c89ffdcdedd5108698d26e9489d');

function v5Le64(value) {
    var x = BigInt.asUintN(64, BigInt(value)), out = new Uint8Array(8);
    for (var i = 0; i < 8; i++) out[i] = Number((x >> BigInt(8 * i)) & 255n);
    return out;
}
function nativeBe32(value) {
    var v = value >>> 0;
    return new Uint8Array([(v >>> 24) & 255, (v >>> 16) & 255, (v >>> 8) & 255, v & 255]);
}
function nativeC(data, initial, i2, i3, i4, i5) {
    var j = initial >>> 0, d = u8(data);
    for (var i = 0; i < d.length; i++) {
        var x = d[i];
        if ((i & 1) === 0) {
            j = ((j >>> i3) ^ (x ^ (((j << i2) >>> 0) ^ j))) >>> 0;
        } else {
            var t = ((j >>> i5) ^ j ^ (x | ((j << i4) >>> 0))) >>> 0;
            j = (~t) >>> 0;
        }
    }
    return j >>> 0;
}
function nativeByteRot(value, shift) {
    var s = ((shift % 8) + 8) % 8;
    return s === 0 ? (value & 255) : (((value >> (8 - s)) | (value << s)) & 255);
}

var F13_K1 = {
    0: [[0, 1, 3, 7, 4, 5, 2, 6], 7, 15, 100],
    3: [[5, 3, 6, 4, 0, 2, 7, 1], 2, 13, 96],
    6: [[7, 6, 5, 4, 3, 1, 0, 2], 3, 62, 94],
    9: [[6, 7, 4, 0, 2, 5, 1, 3], 4, 79, 97],
    12: [[3, 5, 2, 7, 1, 0, 4, 6], 7, 66, 96],
    15: [[6, 2, 7, 4, 1, 3, 0, 5], 6, 127, 99],
};
var F13_B = [2059030472, 1729520903, 1677982208, 873419055, 984304912,
    -1289919430, -1420842003, -2142554032];
var F13_KC = [-340373585, 128638146, -818837569, -535742209, 1829502207, 1513137086,
    -1273309640, 873991864, -231478417, -1314552628, -859632185, 1204935505,
    -715762722, 1890078625, 1464286226, -143719800, 738688778, -636630320,
    -71798932, -37433600, 1753874957, -428423514, -1932119157, 440175886,
    -857165717, 1792077067, -1605228777, -596530045, 579197809, -709567066,
    1936688720, 1700802668, 1635574438, -467451522, 172024131, 1414414386,
    -1998587094, 1902910176, 1279687304, 95566771, -506415002, -1163666248,
    -1372359469, -1019733424, 386070363, -26369176, -256585912, 1309670328,
    1923797261, 650459709, -222502666, -1269467775, 1243971549, -1942912350,
    -1425327226, 1029569300, 1326462516, -746892585, 1146027798, -351652911,
    1822977902, 2640807, 137919738, 1605596550];
var F13_D4 = [-6, 69, 97, -41, -62, 117, 97, 26, 127, -29, 109, -77, 87, 83, -66, 123,
    95, 124, 107, -33, 74, 122, -76, 90, -78, 20, -83, 45, -60, 77, 82, -120, 43, 86,
    -41, 26, 20, 127, 95, 12, 87, 8, -58, 81, -95, -93, 97, 7, -96, -128, 102, -10,
    22, -21, -91, 44, -1, -34, 118, 125, 71, 93, -40, -42];

function nativeF13(query, body, ts) {
    var qh = sm3(query), bh = md5(body);
    var b4 = concatAll([qh.subarray(0, 32), bh, v5Le32(ts)]);
    var selector = nativeC(b4, 539167016, 6, 4, 12, 7) & 15;
    var conf = F13_K1[selector];
    if (!conf) throw new Error('Unsupported native f13 selector ' + selector);
    var perm = conf[0], outIdx = conf[1], i68 = conf[2], i83d = conf[3];
    var i69 = (i68 + ts) >>> 0, i69s = i69 | 0;
    var b14 = new Uint8Array(64);
    b14.set(b4);
    for (var p = 0; p < 4; p++) b14[52 + p] = nativeByteRot(F13_D4[p] & 255, -((i69s + 2) | 0));
    var tailBytes = [0, 0, 0, 0, 0, 0, 1, 0xa0];
    for (var q = 0; q < 8; q++) b14[56 + q] = tailBytes[q];
    var w = new Uint32Array(128);
    for (var i = 0; i < 16; i++) {
        var at = i * 4;
        w[i] = (((b14[at + 1] & 255) << 16) | ((b14[at] & 255) << 24)
            | ((b14[at + 2] & 255) << 8) | b14[at + 3]) >>> 0;
    }
    for (i = 16; i < 128; i++) {
        var a = w[i - 15] >>> 0, b = w[i - 2] >>> 0;
        w[i] = (w[i - 16] + (v5Ror32(a, 18) ^ v5Ror32(a, 7) ^ (a >>> 3))
            + w[i - 7] + (v5Ror32(b, 17) ^ v5Ror32(b, 19) ^ (b >>> 10))) >>> 0;
    }
    var h0 = F13_B.map(function (v) { return v5Ror32(v >>> 0, i69s & 31); });
    var kc = F13_KC.map(function (v) { return v5Ror32(v >>> 0, (i69s + 1) & 31); });
    var vv = h0.slice();
    var end = i68 + i83d;
    for (var idx = i68; idx < end; idx++) {
        var v0 = vv[perm[0]], v1 = vv[perm[1]], v2 = vv[perm[2]], v3 = vv[perm[3]];
        var v4 = vv[perm[4]], v5 = vv[perm[5]], v6 = vv[perm[6]], v7 = vv[perm[7]];
        var maj = ((v0 | v1) & v2) | (v0 & v1);
        var sig2 = v5Ror32(v0, 2) ^ v5Ror32(v0, 13) ^ v5Ror32(v0, 22);
        var t2 = ((v5Ror32(v4, 25) ^ (v5Ror32(v4, 11) ^ v5Ror32(v4, 6)))
            + (v6 ^ (v4 & (v5 ^ v6)))) >>> 0;
        var sum = (v7 + t2 + kc[idx & 63] + w[idx & 127]) >>> 0;
        var next = [vv[7], vv[0], vv[1], vv[2], vv[3], vv[4], vv[5], vv[6]];
        next[(perm[3] + 1) & 7] = (v3 + sum) >>> 0;
        next[outIdx] = (sum + sig2 + maj) >>> 0;
        vv = next;
    }
    var big = new Uint8Array(32);
    for (i = 0; i < 8; i++) {
        var word = (vv[i] + h0[i]) >>> 0;
        big[i * 4] = (word >>> 24) & 255; big[i * 4 + 1] = (word >>> 16) & 255;
        big[i * 4 + 2] = (word >>> 8) & 255; big[i * 4 + 3] = word & 255;
    }
    var folded = new Uint8Array(16);
    for (i = 0; i < 16; i++) folded[i] = big[i] ^ big[i + 16];
    var tail = nativeC(folded.subarray(0, 12), 539100192, 7, 3, 11, 5) >>> 0;
    var out = new Uint8Array(20);
    out.set(folded);
    out[16] = tail & 255; out[17] = (tail >>> 8) & 255;
    out[18] = (tail >>> 16) & 255; out[19] = (tail >>> 24) & 255;
    out[16] |= 4; out[16] |= 32;
    out[19] ^= 1;
    return out;
}

function nativeVarint(value) {
    var n = BigInt(value);
    if (n < 0n) throw new Error('negative varint');
    var out = [];
    while (n > 127n) { out.push(Number((n & 127n) | 128n)); n >>= 7n; }
    out.push(Number(n));
    return new Uint8Array(out);
}
function nativeZigzag(value) {
    var n = BigInt(value);
    return n >= 0n ? (n << 1n) : ((-n << 1n) - 1n);
}
function nativeSer(values, schema) {
    var parts = [], total = 0;
    function add(part) { parts.push(part); total += part.length; }
    for (var i = 0; i < schema.length; i++) {
        var field = schema[i][0], type = schema[i][1], nested = schema[i][2];
        if (!Object.prototype.hasOwnProperty.call(values, field)) continue;
        var value = values[field];
        if (value === null || value === undefined) continue;
        if (type === 1 || type === 4 || type === 13) {
            var zz = nativeZigzag(value);
            if (zz === 0n) continue;
            add(nativeVarint(field * 8));
            add(nativeVarint(zz));
        } else if (type === 6 || type === 10) {
            if (Number(value) === 0) continue;
            add(nativeVarint(field * 8 + 5));
            add(v5Le32(value));
        } else if (type === 16) {
            var sub = nativeSer(value, nested || []);
            add(nativeVarint(field * 8 + 2));
            add(nativeVarint(sub.length));
            add(sub);
        } else {
            var raw = u8(value);
            if (!raw.length) continue;
            add(nativeVarint(field * 8 + 2));
            add(nativeVarint(raw.length));
            add(raw);
        }
    }
    var out = new Uint8Array(total), pos = 0;
    for (var k = 0; k < parts.length; k++) { out.set(parts[k], pos); pos += parts[k].length; }
    return out;
}

var NATIVE_E_Q = [[2, 0, 3, 1], [1, 3, 2, 0], [3, 2, 1, 0], [2, 3, 1, 0]];
var NATIVE_E_R = [[15, 7, 3, 11], [11, 3, 15, 7], [3, 15, 11, 7], [15, 3, 11, 7]];
var NATIVE_E_S = [[5, 7], [0, 6], [4, 2], [2, 3], [6, 1], [7, 0], [3, 4], [1, 5]];
var NATIVE_E_T = [[7, 1, 5], [6, 3, 4], [3, 2, 3], [5, 7, 0], [4, 6, 1], [1, 0, 6], [0, 5, 7], [2, 4, 2]];
var NATIVE_E_P = [3149258354, 3563294043, 2460350267, 2314772937];
function nativeG0(value, shift) {
    var v = value & 255, s = shift & 7;
    return s === 0 ? v : ((v >> (8 - s)) | (v << s)) & 255;
}
function nativeJ(value) {
    return (value & 128) ? (((value << 1) & 255) ^ 27) : ((value << 1) & 255);
}
function nativeD(arr, word, key) {
    var q = NATIVE_E_Q[word];
    for (var base = 0; base < 16; base += 4) {
        for (var i = 0; i < 4; i++) arr[base + i] ^= key[q[i] + base];
    }
}
function nativeH(arr, word) {
    var box = V5_SBOX.subarray(word * 256, (word + 1) * 256), q = NATIVE_E_Q[word];
    var idx = new Uint8Array(16), idx2 = new Uint8Array(16);
    for (var i = 0; i < 16; i++) idx[i] = (i % 4) + q[(i / 4) | 0] * 4;
    idx2.set(idx);
    var pairs = [1, 9, 5, 13, 9, 1, 13, 5, 2, 14, 6, 2, 10, 6, 14, 10];
    for (i = 0; i < 15; i += 2) idx2[pairs[i]] = idx[pairs[i + 1]];
    var cols = [3, 7, 11, 15], r = NATIVE_E_R[word];
    for (i = 0; i < 4; i++) idx2[cols[i]] = idx[r[i]];
    var cp = arr.slice();
    for (i = 0; i < 16; i++) arr[i] = box[cp[idx2[i]] & 255];
}
function nativeE(data, j2, j3, j4, arr2, arr3) {
    var d = u8(data), m = v5Le32(j3), n = v5Le64(j4);
    var m0 = sm3(concatAll([arr3, m, arr3]));
    var out = new Uint8Array(d.length);
    for (var i = 0; i < d.length; i++) {
        var at = i * 4, a = m0[at % 32], b = m0[(at + 1) % 32];
        var x = (((nativeG0(d[i], 4) + a) & 255) ^ 255 ^ b) & 255;
        var y = nativeG0(x, 3);
        out[d.length - 1 - i] = (((y + b) & 255) ^ 255 ^ a) & 255;
    }
    var j7 = out.length - 1, j8 = out.length - 2;
    out[0] = (out[0] + (((out[j7] ^ out[j8]) ^ 255) & 255)) & 255;
    out[1] = (out[1] + (((out[0] ^ out[j7]) ^ 254) & 255)) & 255;
    for (i = 0; i < out.length - 3; i++) {
        out[i + 2] = (out[i + 2] + ((((nativeG0(out[i + 1], 3) ^ out[i]) ^ (i + 2)) ^ 255) & 255)) & 255;
    }
    out[j7] ^= out[j8];
    var sum = 0;
    for (i = 1; i < out.length; i++) sum = (sum + out[i]) & 255;
    out[0] = ((out[0] ^ out[1]) + sum) & 255;
    var u1 = concatBytes(arr2, out);
    var check = nativeBe32(nativeC(m.subarray(2, 4), 0, 7, 3, 11, 5));
    var rev = new Uint8Array(u1.length);
    for (i = 0; i < u1.length; i++) rev[i] = u1[u1.length - 1 - i] ^ check[i & 3];
    var head = new Uint8Array([nativeC(arr3, 0, 7, 3, 11, 5) & 255]);
    var u2 = concatAll([head, n, rev, m.subarray(2, 4)]);
    var iarr = [];
    for (i = 0; i < 31; i++) iarr.push([i * 8, 0]);
    var bits = new Uint8Array(31);
    for (i = 0; i < iarr.length; i++) {
        for (var bs = 0; bs < NATIVE_E_S.length; bs++) {
            var sh = NATIVE_E_S[bs];
            bits[i] |= ((u2[iarr[i][0] + sh[0]] >> ((sh[1] + iarr[i][1]) & 7)) & 1) << bs;
        }
    }
    var word = j2 & 3;
    var h1 = md5(arr3.subarray(0, 16)), h2 = md5(arr3.subarray(16, 32));
    var expanded = new Uint8Array(48);
    for (i = 0; i < 16; i++) expanded[i] = h1[i] ^ ((NATIVE_E_P[word] >>> ((i % 4) * 8)) & 255);
    var sb = V5_SBOX.subarray(word * 256, (word + 1) * 256);
    for (i = 4; i < 12; i++) {
        var base = i * 4;
        var v = [expanded[base - 4], expanded[base - 3], expanded[base - 2], expanded[base - 1]];
        if ((i & 3) === 0) {
            var nv = [sb[v[1]], sb[v[2]], sb[v[3]], sb[v[0]]];
            nv[0] = (((NATIVE_E_P[word] >>> ((i << 1) & 24)) & (word === 3 ? 249 : 255)) ^ nv[0]) & 255;
            v = nv;
        }
        for (var k2 = 0; k2 < 4; k2++) expanded[base + k2] = v[k2] ^ expanded[(i - 4) * 4 + k2];
    }
    var plain = new Uint8Array(32);
    plain.set(bits); plain[31] = 1;
    var enc = new Uint8Array(32), copy = h2.slice(), q = NATIVE_E_Q[word];
    for (var off = 0; off < 32; off += 16) {
        var block = plain.slice(off, off + 16);
        for (i = 0; i < 16; i++) block[i] ^= copy[i];
        nativeD(block, word, expanded.subarray(0, 16));
        nativeH(block, word);
        var mix = new Uint8Array(16);
        for (var st = 0; st < 16; st += 4) {
            for (k2 = 0; k2 < 4; k2++) mix[st + k2] = block[st + q[k2]];
        }
        for (i = 0; i < 4; i++) {
            var aa = mix[i], bb = mix[i + 4], cc = mix[i + 8], dd = mix[i + 12];
            block[i] = (nativeJ(aa) ^ nativeJ(bb) ^ bb ^ cc ^ dd) & 255;
            block[i + 4] = (nativeJ(bb) ^ aa ^ nativeJ(cc) ^ cc ^ dd) & 255;
            block[i + 8] = (aa ^ bb ^ nativeJ(cc) ^ nativeJ(dd) ^ dd) & 255;
            block[i + 12] = (nativeJ(aa) ^ aa ^ bb ^ cc ^ nativeJ(dd)) & 255;
        }
        nativeD(block, word, expanded.subarray(16, 32));
        nativeH(block, word);
        nativeD(block, word, expanded.subarray(32, 48));
        copy = new Uint8Array(16);
        for (i = 0; i < 16; i++) copy[i] = block[i] ^ expanded[i + 16];
        enc.set(copy, off);
    }
    var copy2 = u2.slice();
    for (i = 0; i < iarr.length; i++) {
        for (var ti = 0; ti < NATIVE_E_T.length; ti++) {
            var t = NATIVE_E_T[ti], pos = iarr[i][0] + t[1], bit = (t[2] + iarr[i][1]) & 7;
            copy2[pos] = (copy2[pos] & ((1 << bit) ^ 255)) | (((enc[i] >> t[0]) & 1) << bit);
        }
    }
    var magic = [5, 3394194221, 1124955465, 749647167, 1456237858];
    var pieces = [];
    for (i = 0; i < magic.length; i++) pieces.push(v5Le32(BigInt(j2) ^ BigInt(magic[i])));
    pieces.push(new Uint8Array([m[0], m[1], 0, enc.length - iarr.length]));
    pieces.push(enc.subarray(iarr.length));
    pieces.push(copy2);
    var total = 0;
    for (i = 0; i < pieces.length; i++) total += pieces[i].length;
    var out2 = new Uint8Array(total), pos2 = 0;
    for (i = 0; i < pieces.length; i++) { out2.set(pieces[i], pos2); pos2 += pieces[i].length; }
    return b64enc(out2);
}
function cloneNativeTemplate(value) {
    if (value instanceof Uint8Array) return value.slice();
    if (Array.isArray(value)) return value.map(cloneNativeTemplate);
    if (value && typeof value === 'object') {
        var out = {};
        Object.keys(value).forEach(function (k) { out[k] = cloneNativeTemplate(value[k]); });
        return out;
    }
    return value;
}
function nativeMedusa(query, f13, ts) {
    var vals = cloneNativeTemplate(NATIVE_MEDUSA_TEMPLATE);
    var qh = sm3(query), delta = ts - vals[12];
    vals[12] = ts; vals[17] = ts;
    vals[3] = v5Random32() & 0x7fffffff;
    vals[13] = f13;
    vals[14] = qh.slice(0, 6);
    var env = vals[23];
    if (env) {
        [25, 26, 27, 28, 40].forEach(function (f) {
            if (Object.prototype.hasOwnProperty.call(env, f)) env[f] = Number(env[f]) + delta * 1000;
        });
        if (env[13] && Object.prototype.hasOwnProperty.call(env[13], 1)) {
            env[13][1] = Number(env[13][1]) + delta;
        }
    }
    var plain = nativeSer(vals, NATIVE_MEDUSA_SCHEMA);
    var j3 = v5Random32() & 0x7fffffff;
    var low = v5Random32() & 0x7fffffff;
    var j4 = (BigInt(qh[0] & 63) << 46n) | 0x1800000000000000n
        | (BigInt(f13[0] & 63) << 40n) | 0x100000000n | BigInt(low);
    return nativeE(plain, ts, j3, j4, NATIVE_MEDUSA_A2, NATIVE_MEDUSA_A3);
}
function nativeV5Sign(raw, now, alternate) {
    var ts = Math.floor(now / 1000);
    var query = NATIVE_PLAYER_QUERY.replace('__RTICKET__', String(now));
    var qb = utf8enc(query), qh = sm3(qb);
    var body = null, bodyHash = null;
    for (var mt = 0; mt < 65536; mt++) {
        var candidate = gzipStored(raw, mt);
        var candidateHash = md5(candidate);
        var b4 = concatAll([qh.subarray(0, 32), candidateHash, v5Le32(ts)]);
        var selector = nativeC(b4, 539167016, 6, 4, 12, 7) & 15;
        if (F13_K1[selector]) { body = candidate; bodyHash = candidateHash; break; }
    }
    if (!body) throw new Error('Unable to select native playback hash branch');
    var f13 = nativeF13(qb, body, ts);
    var headers = Object.assign({}, NATIVE_PLAYER_HEADERS);
    headers['x-khronos'] = String(ts);
    headers['x-helios'] = v5Helios(ts);
    headers['x-medusa'] = nativeMedusa(qb, f13, ts);
    headers['x-ss-stub'] = bytesToHex(bodyHash).toUpperCase();
    headers['x-ss-req-ticket'] = String(now);
    var base = alternate ? V5_PLAYER_API_ALT : V5_PLAYER_API;
    return {url: base + '?' + query, headers: headers, body: body};
}

// ===========================================================================
// Spider
// ===========================================================================
export default class Hgtv extends Spider {
    init(extend = '') {
        this.device = null;
        this.lastError = '';
        this.memCache = {};
    }
    getName() { return '红果短剧'; }
    isVideoFormat(url) {
        var s = String(url || '');
        return /\.mp4|video_mp4|m3u8|mime_type/i.test(s) || /\/proxy\?|siteKey=hgtv/i.test(s);
    }

    request(url, options) {
        if (this.net && typeof this.net.req === 'function') return this.net.req(url, options);
        if (typeof this.req === 'function') return this.req(url, options);
        if (typeof req === 'function') return req(url, options);
        throw new Error('找不到网络请求 API（net.req / req）');
    }
    async fetch(url, options) {
        var reply = await this.request(url, options || {});
        if (typeof reply === 'string') return {content: reply, code: 200, headers: {}};
        if (!reply || typeof reply !== 'object') throw new Error('返回类型异常');
        if (reply.error) throw new Error(String(reply.error));
        var code = reply.code;
        if (code !== undefined && code !== null && (code < 200 || code >= 300)) throw new Error('HTTP ' + code);
        return {content: reply.content, code: code || 200, headers: reply.headers || {}};
    }
    async getText(url, headers, timeout) {
        var r = await this.fetch(url, {method: 'GET', headers: headers || {'User-Agent': UA}, timeout: timeout || 15000});
        return typeof r.content === 'string' ? r.content : utf8dec(r.content);
    }
    async getBytes(url, headers, timeout) {
        var opts = {method: 'GET', headers: headers || {}, timeout: timeout || 60000};
        var r;
        try { r = await this.fetch(url, Object.assign({}, opts, {buffer: 3})); }
        catch (e) { r = await this.fetch(url, opts); }
        return u8(r.content);
    }
    async postText(url, headers, body, timeout) {
        var r = await this.fetch(url, {
            method: 'POST', headers: headers || {}, body: body,
            timeout: timeout || 15000,
        });
        return typeof r.content === 'string' ? r.content : utf8dec(r.content);
    }
    async postBytes(url, headers, bytes, timeout) {
        // FongMi 的二进制 body 使用 0~255 整数数组，不能直接传 Uint8Array。
        var r = await this.fetch(url, {
            method: 'POST', headers: headers || {}, body: Array.from(u8(bytes)),
            timeout: timeout || 30000,
        });
        return typeof r.content === 'string' ? r.content : utf8dec(r.content);
    }
    async routerData(url) {
        var html = await this.getText(url, {
            'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8', 'Cache-Control': 'no-cache',
        }, 20000);
        return parseRouterData(html);
    }

    async homeRecommendations(limit) {
        limit = limit || 24;
        if (HOME_RECOMMEND.rows.length && Date.now() - HOME_RECOMMEND.time < HOME_CACHE_TTL) {
            return HOME_RECOMMEND.rows.slice(0, limit);
        }
        var data = {};
        try { data = await this.routerData(SITE + '/'); } catch (e) { data = {}; }
        var page = (data.loaderData || {}).page || {};
        var rows = [], seen = {};
        var raw = (page.bannerList || []).concat(page.mBannerList || []);
        var sections = page.homeSections || [];
        for (var s = 0; s < sections.length; s++) {
            raw = raw.concat(sections[s] && sections[s].video_list ? sections[s].video_list : []);
        }
        for (var i = 0; i < raw.length && rows.length < limit; i++) {
            var x = raw[i] || {};
            var sid = String(x.series_id || '');
            if (!sid || seen[sid]) continue;
            seen[sid] = 1;
            var item = itemOf(x);
            item.vod_id = sid;
            rows.push(item);
        }
        HOME_RECOMMEND = {time: Date.now(), rows: rows};
        return rows.slice(0, limit);
    }

    async homeContent(filter) {
        var classes = [{type_id: 'recommend', type_name: '推荐'}], filters = {};
        for (var i = 0; i < CONTENT_TYPES.length; i++) {
            var c = CONTENT_TYPES[i];
            classes.push({type_id: c[0], type_name: c[1]});
            if (c[2].length > 1) {
                filters[c[0]] = [{key: 'cat', name: '分类', value: c[2].map(function (v) { return {n: v[1], v: v[0]}; })}];
            }
        }
        return {class: classes, filters: filters};
    }

    async homeVideoContent() {
        var list = [];
        try { list = await this.homeRecommendations(36); } catch (e) {}
        return {list: list};
    }

    async categoryContent(tid, pg, filter, extend) {
        var page = parseInt(pg, 10) || 1; if (page < 1) page = 1;
        if (String(tid || '') === 'recommend') {
            var recRows = [];
            try { recRows = await this.homeRecommendations(36); } catch (e) {}
            return {
                page: 1, pagecount: 1, limit: recRows.length,
                total: recRows.length, list: recRows,
            };
        }
        var route = routeOf(tid), cat = '';
        if (typeof extend === 'string' && extend) { try { extend = JSON.parse(extend); } catch (e) { extend = {}; } }
        if (extend && typeof extend === 'object') cat = String(extend.cat || extend['分类'] || '');
        if (filter && typeof filter === 'object' && !cat) cat = String(filter.cat || filter['分类'] || '');
        if (['all', '全部', '0', 'all_cat'].indexOf(cat) >= 0) cat = '';
        var data = {};
        try { data = await this.routerData(SITE + '/category/' + route + (cat ? '/' + encodeURIComponent(cat) : '') + '?page=' + page); }
        catch (e) { try { data = await this.routerData(SITE + '/category/real-drama?page=' + page); } catch (e2) { data = {}; } }
        var loader = (data.loaderData || {});
        var p = loader['category_$'] || loader['category_page'] || {};
        var rows = p.recommendList || [], pgData = p.pagination || {};
        return {
            page: page,
            pagecount: parseInt(pgData.totalPages, 10) || 1,
            limit: rows.length,
            total: parseInt(pgData.total, 10) || rows.length,
            list: rows.map(itemOf),
        };
    }

    async searchContent(key, quick, pg) {
        var page = parseInt(pg, 10) || 1; if (page < 1) page = 1;
        key = String(key == null ? '' : key).trim() || '短剧';
        var low = key.toLowerCase();
        if (key === 'AI漫剧' || key === 'ai漫剧' || low.indexOf('ai漫') >= 0) return this.keywordSearch(AI_MANJU_KEYWORDS, page);
        if (key === '漫剧' || key === '动漫短剧') return this.keywordSearch(MANJU_KEYWORDS, page);

        var p = await this.searchApi(key, page);
        var rows = p.searchList || [];
        if (!rows.length) {
            var scan = await this.searchScan(key, page);
            if (scan.list.length) return scan;
        }
        var out = [], seen = {};
        for (var i = 0; i < rows.length; i++) {
            var it = itemOf(rows[i]);
            if (!it.vod_id || seen[it.vod_id]) continue;
            seen[it.vod_id] = 1; out.push(it);
        }
        var total = parseInt(p.totalCount, 10) || out.length;
        var pages = parseInt(p.totalPages, 10) || 1;
        return {page: page, pagecount: Math.max(1, Math.min(50, pages)), limit: out.length, total: total, list: out};
    }

    async searchApi(key, page) {
        var url = SITE + '/api/search/result?aid=8662&query=' + encodeURIComponent(key) + '&page=' + page;
        var headers = {'User-Agent': UA, 'Accept': 'application/json, text/plain, */*', 'Referer': SITE + '/'};
        var client = null;
        try {
            if (this.net && typeof this.net.session === 'function') {
                client = this.net.session();
                try { await client.req(SITE + '/', {method: 'GET', headers: {'User-Agent': UA}, timeout: 8000}); } catch (e) {}
                var d = await client.json(url, {headers: headers, timeout: 15000});
                if (d && d.searchList && d.searchList.length) return d;
            }
            var txt = await this.getText(url, headers, 15000);
            var j = JSON.parse(txt);
            return {searchList: j.searchList || [], totalCount: j.totalCount || 0, totalPages: j.totalPages || 1, hasMore: !!j.hasMore};
        } catch (e) {
            return {searchList: [], totalCount: 0, totalPages: 1, hasMore: false};
        } finally {
            if (client && typeof client.close === 'function') { try { client.close(); } catch (e) {} }
        }
    }

    async keywordSearch(keywords, page) {
        var kws = keywords && keywords.length ? keywords : ['短剧'];
        var key = kws[(page - 1) % kws.length];
        var p = await this.searchApi(key, 1);
        var out = [], seen = {};
        var rows = p.searchList || [];
        for (var i = 0; i < rows.length; i++) {
            var it = itemOf(rows[i]);
            if (!it.vod_id || seen[it.vod_id]) continue;
            seen[it.vod_id] = 1; out.push(it);
        }
        var total = parseInt(p.totalCount, 10) || 0;
        var pages = Math.max(kws.length, total ? Math.ceil(total / 10) : kws.length);
        return {page: page, pagecount: pages, limit: out.length, total: total || out.length * pages, list: out};
    }

    async searchScan(key, page) {
        var routes = CONTENT_TYPES.map(function (c) { return c[0]; });
        var hits = [], seen = {};
        for (var r = 0; r < routes.length; r++) {
            for (var p = 1; p <= 8; p++) {
                try {
                    var data = await this.routerData(SITE + '/category/' + routes[r] + '?page=' + p);
                    var rows = ((data.loaderData || {})['category_$'] || {}).recommendList || [];
                    for (var i = 0; i < rows.length; i++) {
                        var nm = String(rows[i].series_name || rows[i].series_title || '');
                        if (nm.indexOf(key) < 0) continue;
                        var it = itemOf(rows[i]);
                        if (!it.vod_id || seen[it.vod_id]) continue;
                        seen[it.vod_id] = 1; hits.push(it);
                    }
                } catch (e) {}
            }
        }
        if (!hits.length) return {page: page, pagecount: 1, limit: 0, total: 0, list: []};
        var st = (page - 1) * 20;
        return {page: page, pagecount: Math.ceil(hits.length / 20), limit: Math.min(20, hits.length - st),
            total: hits.length, list: hits.slice(st, st + 20)};
    }

    async detailContent(ids) {
        var sid = String(Array.isArray(ids) ? ids[0] : ids);
        if (sid.indexOf('hg-series-v1:') === 0) sid = sid.substring('hg-series-v1:'.length);
        var data = await this.routerData(SITE + '/detail?series_id=' + encodeURIComponent(sid));
        var p = ((data.loaderData || {})['detail_page'] || {});
        var s = p.seriesDetail || {}, vids = s.vid_list || [];
        NEXT_EPISODE = {};
        for (var ni = 0; ni + 1 < vids.length; ni++) NEXT_EPISODE[String(vids[ni])] = String(vids[ni + 1]);
        var actors = [];
        for (var i = 0; i < (s.celebrities || []).length; i++) {
            var c = s.celebrities[i];
            if (c && c.nickname) actors.push(String(c.nickname));
        }
        var from = [], urls = [];
        for (var q = 0; q < QUALITY_LINES.length; q++) {
            var eps = [];
            for (var v = 0; v < vids.length; v++)
                eps.push('第' + (v + 1) + '集$' + EPISODE_PREFIX + QUALITY_LINES[q][0] + ':' + String(vids[v]));
            from.push(QUALITY_LINES[q][1]); urls.push(eps.join('#'));
        }
        var result = {list: [{
            vod_id: sid, vod_name: String(s.series_name || ''), vod_pic: String(s.series_cover || ''),
            vod_year: '', vod_area: '', vod_director: '', vod_actor: actors.join(','),
            vod_content: String(s.series_intro || ''), vod_remarks: String(s.episode_right_text || ''),
            vod_play_from: from.join('$$$'), vod_play_url: urls.join('$$$'),
        }]};
        // 稳定优先：详情页不做任何后台预热。
        // 盒子上的网络请求会同步阻塞 QuickJS 线程，预热无论发生在播放中还是
        // 详情页未结束就点播，都会造成 proxy 排队数秒。只保留播放时按需缓冲。
        PREWARM_ACTIVE = false;
        PREWARM_VIDS = {};
        return result;
    }

    async registerDevice(force) {
        if (!force && this.device && this.device.device_id && this.device.install_id) return this.device;
        if (!force && SHARED_DEVICE && SHARED_DEVICE.device_id && SHARED_DEVICE.install_id &&
            Date.now() - SHARED_DEVICE_TIME < 3600000) {
            this.device = SHARED_DEVICE;
            return this.device;
        }
        var header = {
            display_name: '红果免费短剧', aid: 8662, app_version: '7.3.5.32', version_code: 73532,
            manifest_version_code: 73532, update_version_code: 73532, channel: 'update_64',
            package: 'com.phoenix.read', app_language: 'zh', os: 'Android', os_version: '16', os_api: 36,
            device_model: '25053RT47C', device_brand: 'Redmi', device_manufacturer: 'Xiaomi',
            cpu_abi: 'arm64-v8a', density_dpi: 520, display_density: 'xxhdpi', resolution: '2772x1280',
            language: 'zh', timezone: 8, access: 'wifi', openudid: randHex(16), clientudid: uuid(),
            cdid: uuid(), region: 'CN', tz_name: 'Asia/Shanghai', tz_offset: 28800, sim_region: 'cn',
            device_platform: 'android', not_request_sender: 0, is_system_app: 0, sdk_flavor: 'china',
            rom: 'OS2.0', rom_version: 'BP2A.250605.031.A3',
        };
        var body = JSON.stringify({magic_tag: 'ss_app_log', header: header, _gen_time: Date.now()});
        var url = 'https://log.snssdk.com/service/2/device_register/?req_id=' + uuid() + '&_rticket=' + Date.now();
        try {
            var txt = await this.postText(url, {
                'User-Agent': APP_UA, 'Accept': 'application/json', 'Content-Type': 'application/json; charset=utf-8',
            }, body, 15000);
            var d = JSON.parse(txt);
            var did = String(d.device_id_str || d.device_id || '');
            var iid = String(d.install_id_str || d.install_id || '');
            if (/^\d+$/.test(did) && /^\d+$/.test(iid) && did !== '0' && iid !== '0') {
                this.device = {
                    device_id: did, install_id: iid,
                    device_token: String(d.device_token || d.device_token_str || d.x_tt_dt || ''),
                    cdid: header.cdid,
                };
                SHARED_DEVICE = this.device;
                SHARED_DEVICE_TIME = Date.now();
                return this.device;
            }
        } catch (e) { this.lastError = String(e && e.message || e); }
        this.device = {device_id: String(Math.floor(Math.random() * 9e17) + 1e17),
            install_id: String(Math.floor(Math.random() * 9e17) + 1e17), device_token: '', cdid: uuid()};
        SHARED_DEVICE = this.device;
        SHARED_DEVICE_TIME = Date.now();
        return this.device;
    }

    // 上游不支持/忽略 Range 时按请求起点自己切片，避免样本偏移整体错位。
    async rangeGet(url, start, end) {
        var expected = end - start + 1, lastErr = null;
        var headers = {'User-Agent': MEDIA_UA, 'Referer': 'https://novel.snssdk.com/',
            'Range': 'bytes=' + start + '-' + end};
        for (var attempt = 0; attempt < HG_RANGE_ATTEMPTS; attempt++) {
            try {
                var r;
                try { r = await this.fetch(url, {method: 'GET', headers: headers, buffer: 3, timeout: 60000}); }
                catch (e) { r = await this.fetch(url, {method: 'GET', headers: headers, timeout: 60000}); }
                var code = Number(r.code || 200);
                if (code < 200 || code >= 300) throw new Error('媒体分片 HTTP ' + code);
                var bytes = u8(r.content);
                if (code === 200) {
                    bytes = start > 0 ? bytes.subarray(start, start + expected) : bytes.subarray(0, expected);
                }
                if (!bytes || bytes.length < expected) {
                    throw new Error('媒体分片长度不足 ' + (bytes ? bytes.length : 0) + '/' + expected);
                }
                var total = 0, cr = headerGet(r.headers, 'Content-Range');
                var slash = cr.lastIndexOf('/');
                if (slash >= 0 && /^\d+$/.test(cr.substring(slash + 1).trim())) total = parseInt(cr.substring(slash + 1).trim(), 10);
                if (!total) {
                    var len = headerGet(r.headers, 'Content-Length');
                    if (/^\d+$/.test(len)) total = parseInt(len, 10);
                }
                return {bytes: bytes.slice(), total: total, code: code};
            } catch (e) { lastErr = e; }
        }
        throw lastErr || new Error('媒体分片请求失败');
    }

    async fetchMoov(url) {
        var head = await this.rangeGet(url, 0, HG_HEAD_PROBE - 1);
        var total = head.total;
        if (!total) throw new Error('媒体总长度未知');
        var found = findMoovWindow(head.bytes, 0, total);
        if (found[0] < 0) {
            var tailStart = Math.max(0, total - HG_TAIL_PROBE);
            var tail = await this.rangeGet(url, tailStart, total - 1);
            found = findMoovInTail(tail.bytes, tailStart, total);
        }
        if (found[0] < 0 || found[1] < 8) throw new Error('未找到 moov 顶层盒');
        if (found[0] + found[1] > total) throw new Error('moov 越界');
        var moov;
        if (found[0] + found[1] <= head.bytes.length) {
            moov = head.bytes.subarray(found[0], found[0] + found[1]);
        } else {
            moov = (await this.rangeGet(url, found[0], found[0] + found[1] - 1)).bytes;
        }
        return {url: url, total: total, moovStart: found[0], moovSize: found[1], moov: moov};
    }

    // 单连接 GET 实测会被上游拖到 40 秒；并行 Range 拉同一文件后本地拼回，
    // 得到的仍是一份完整密文，后续播放完全走本地 Range，稳定且不卡顿。
    async parallelDownload(url, total) {
        var count = 10, size = Math.ceil(total / count), tasks = [], self = this;
        for (var i = 0; i < count; i++) {
            (function (at, stop) {
                tasks.push(self.rangeGet(url, at, stop).then(function (got) {
                    return {start: at, got: got};
                }));
            })(i * size, Math.min(total - 1, i * size + size - 1));
        }
        var results = await Promise.all(tasks);
        if (results.length && results[0].got.code === 200) return results[0].got.bytes;
        var body = new Uint8Array(total);
        for (var r = 0; r < results.length; r++) {
            body.set(results[r].got.bytes, results[r].start);
        }
        return body;
    }

    // player/v1 返回 HTTP 200 空 body 时的恢复路径：同一身份签名 GET video_tab。
    // 严格只认本集；别集或者空模型都按最初的空响应处理，避免播错分集。
    async videoTabVideoModel(vid, identity, original) {
        var values = Object.assign({}, VIDEO_TAB_PROFILE, {
            iid: String(identity.iid || ''),
            cdid: String(identity.cdid || ''),
            device_id: String(identity.device_id || ''),
            video_id: String(vid),
            video_id_type: '0',
            device_level: '1',
            need_all_video_definition: '1',
            need_mp4_align: '0',
            use_os_player: '0',
            video_platform: '1024',
            source: '0',
            from_video_id: '',
        });
        var signed = v5Sign(VIDEO_TAB_API, values, null, Date.now());
        var headers = Object.assign({}, signed.headers, {
            'User-Agent': VIDEO_TAB_UA,
            'Accept-Language': 'zh-CN,zh;q=0.9',
        });
        var txt = await this.getText(signed.url, headers, 15000);
        if (!txt || !txt.trim()) throw original;
        var result;
        try { result = JSON.parse(txt); } catch (e) { throw original; }
        if (!result || typeof result !== 'object') throw original;
        var codeValue = result.Code !== undefined ? result.Code : (result.code !== undefined ? result.code : 0);
        var code = Number(codeValue);
        if (code) throw new Error('上游拒绝播放请求 (code=' + code + ' msg=' + String(result.message || result.msg || '') + ')');
        var data = result.data && typeof result.data === 'object' ? result.data : result;
        var rows = data.video_model_data && typeof data.video_model_data === 'object' ? data.video_model_data : data;
        var entry = rows[String(vid)];
        if (!entry || typeof entry !== 'object') throw original;
        var raw = entry.video_model;
        if (typeof raw === 'string') {
            try { raw = JSON.parse(raw); } catch (e) { throw original; }
        }
        if (!raw || typeof raw !== 'object') throw original;
        return raw;
    }

    async v5VideoModel(vid, identity, alternate) {
        var payload = {
            biz_param: Object.assign({}, V5_BIZ_PARAM),
            mixed_video_id_map: {1004: [String(vid)]},
            dr_scene: 'player',
        };
        var signed = nativeV5Sign(utf8enc(JSON.stringify(payload)), Date.now(), alternate);
        var txt = await this.postBytes(signed.url, signed.headers, signed.body, 30000);
        if (!txt || !txt.trim()) {
            var empty = new Error('上游响应为空');
            empty.empty = true;
            return await this.videoTabVideoModel(vid, identity, empty);
        }
        var result = JSON.parse(txt);
        var codeValue = result.Code !== undefined ? result.Code : (result.code !== undefined ? result.code : 0);
        var code = Number(codeValue);
        if (code) throw new Error('上游拒绝播放请求 (code=' + code + ' msg=' + String(result.message || result.msg || '') + ')');
        return modelFromResponse(result, vid);
    }

    async videoModel(vid, device) {
        var modelKey = String(vid) + '|' + String((device && device.cdid) || '');
        var hit = MODEL_CACHE[modelKey];
        if (hit && Date.now() - hit.t < MODEL_CACHE_TTL) return hit.model;
        // 公开无签名入口目前返回 200 + 0 字节，先走 PY 已验证可用的 v5 协议。
        for (var round = 0; round < 2; round++) {
            if (round > 0) {
                try { device = await this.registerDevice(true); } catch (e) { this.lastError = String(e && e.message || e); }
            }
            var identity = {
                device_id: String((device && device.device_id) || ''),
                iid: String((device && (device.install_id || device.iid)) || ''),
                cdid: String((device && device.cdid) || ''),
            };
            if (!identity.device_id || !identity.iid || !identity.cdid) continue;
            for (var alt = 0; alt < 2; alt++) {
                try {
                    var model = await this.v5VideoModel(vid, identity, alt === 1);
                    MODEL_CACHE[modelKey] = {t: Date.now(), model: model};
                    return model;
                } catch (e) { this.lastError = String(e && e.message || e); }
            }
        }
        // 旧公开入口兜底：部分老环境/老设备画像可能仍然可用。
        var params = Object.assign({}, PUBLIC_PARAMS, {
            device_id: device.device_id, iid: device.install_id, _rticket: String(Date.now()),
        });
        var qs = Object.keys(params).map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); }).join('&');
        var attempts = [];
        for (var i = 0; i < MULTI_PATHS.length; i++) {
            attempts.push([MULTI_PATHS[i][0], {
                biz_param: Object.assign({}, BIZ_PARAM),
                mixed_video_id_map: ((obj) => { obj[MULTI_PATHS[i][1]] = [String(vid)]; return obj; })({}),
            }]);
        }
        attempts.push([SINGLE_PATH, {video_id: String(vid), content_type: 1, need_all_video_definition: true}]);
        for (var a = 0; a < attempts.length; a++) {
            try {
                var txt = await this.postText(PLAYER_BASE + attempts[a][0] + '?' + qs,
                    PUBLIC_HEADERS, JSON.stringify(attempts[a][1]), 15000);
                if (!txt || !txt.trim()) continue;
                var result = JSON.parse(txt);
                var legacyModel = modelFromResponse(result, vid);
                MODEL_CACHE[modelKey] = {t: Date.now(), model: legacyModel};
                return legacyModel;
            } catch (e) { this.lastError = String(e && e.message || e); }
        }
        throw new Error('video_model 数据为空: ' + this.lastError);
    }

    async resolveMedia(vid, q, device) {
        var model = await this.videoModel(vid, device);
        var rows = videoListFromModel(model);
        if (!rows) throw new Error('播放模型没有清晰度');
        var item = selectQuality(rows, q);
        var url = String(mediaUrl(item) || '');
        var spade = String(spadeValue(item) || '');
        if (!url || !spade) throw new Error('缺少播放地址或密钥材料');
        try {
            var seed = keySeedFromModel(model);
            if (seed && seed.length) url = decryptSpadeUrl(url, seed);
        } catch (e) {}
        return {url: url, contentKey: deriveContentKey(spade)};
    }

    // 整集下载兜底路径（渐进式明文缓冲失败时使用）。
    async mediaSource(vid, q, device) {
        var cacheKey = vid + '|' + q;
        var cached = sourceGet(cacheKey);
        if (cached) return cached;
        if (SOURCE_PENDING[cacheKey]) return await SOURCE_PENDING[cacheKey];
        var pending = (async () => {
            var resolved = await this.resolveMedia(vid, q, device);
            var url = resolved.url, contentKey = resolved.contentKey;
            // 恢复已验证稳定的本地 Range 解密路径；用并行 Range 加速整集预热。
            try {
                var info0 = await this.fetchMoov(url);
                var body = await this.parallelDownload(url, info0.total);
                if (!body || body.length < 1024) throw new Error('媒体下载为空');
                var source = buildCencSession(body, contentKey);
                if (source.data.length < 64) throw new Error('解密结果异常');
                source.key = cacheKey;
                sourcePut(cacheKey, source);
                return source;
            } catch (e) {
                this.lastError = String(e && e.message || e);
            }
            // 并行 Range 失败时退回普通整集下载。
            try {
                var body2 = await this.getBytes(url, {'User-Agent': MEDIA_UA, 'Referer': 'https://novel.snssdk.com/'}, 90000);
                if (!body2 || body2.length < 1024) throw new Error('媒体下载为空');
                var source2 = buildCencSession(body2, contentKey);
                if (source2.data.length < 64) throw new Error('解密结果异常');
                source2.key = cacheKey;
                sourcePut(cacheKey, source2);
                return source2;
            } catch (e1) {
                this.lastError = String(e1 && e1.message || e1);
            }
            // 仅当整集下载失败时才尝试按需 Range（兼容个别超长媒体）。
            try {
                var fetcher = (s, e) => this.rangeGet(url, s, e);
                var info = await this.fetchMoov(url);
                var remote = await buildRemoteCencSession(info, contentKey, fetcher, cacheKey);
                sourcePut(cacheKey, remote);
                return remote;
            } catch (e2) {
                this.lastError = String(e2 && e2.message || e2);
            }
            throw new Error('媒体会话创建失败: ' + this.lastError);
        })();
        SOURCE_PENDING[cacheKey] = pending;
        try { return await pending; }
        finally { delete SOURCE_PENDING[cacheKey]; }
    }

    // 建立渐进式明文缓冲：先取 moov/CENC 信息，随后顺序拉密文写入本地缓冲。
    // 只等开头一小段就绪就能交给播放器，其余在后台继续，播放时全部本地直出。
    async openProgressive(vid, q, device) {
        var key = String(vid) + '|' + q;
        var hit = progressGet(key);
        if (hit) return hit;
        if (PROGRESS_PENDING[key]) return await PROGRESS_PENDING[key];
        var self = this;
        var t0 = Date.now();
        var pending = (async () => {
            try {
                var resolved = await self.resolveMedia(vid, q, device);
                hgLog('hg prog resolved', key, (Date.now() - t0) + 'ms');
                var rawFetcher = (s, e) => self.rangeGet(resolved.url, s, e);
                var info = await self.fetchMoov(resolved.url);
                hgLog('hg prog moov', key, (Date.now() - t0) + 'ms', info.total);
                // 辅助信息用小范围直接取；媒体数据走并行预取，首段只需等 4 块。
                var session = await buildRemoteCencSession(info, resolved.contentKey, rawFetcher, key);
                hgLog('hg prog cenc', key, (Date.now() - t0) + 'ms');
                // 起播期用 10 块并发快速填满 3MB 窗口；首帧返回后立即降回 3 块。
                // 不能再保留起播后的高速窗口，否则会和播放器的 Range/AES 抢资源。
                var prefetch = makePrefetchFetcher(rawFetcher, 1 << 18, 10, info.total);
                session.fetch = prefetch.fetch;
                var h = {
                    key: key, data: new Uint8Array(info.total), total: info.total,
                    frontier: 0, iterator: cencRemoteByteStream(session, 0, info.total - 1)[Symbol.asyncIterator](),
                    waiters: [], pumping: false, done: false, finished: false, error: null,
                    playerEnd: 0, resume: null, fastAheadDone: false,
                    hold: false, rescueLeft: HG_RESCUE_MAX,
                    session: session, rawFetcher: rawFetcher,
                    moovStart: session.moovStart, moov: session.moov,
                    setAhead: prefetch.setAhead, t0: t0, firstLogged: false,
                };
                PROGRESS_CACHE[key] = h;
                hgLog('hg prog pumping', key, (Date.now() - t0) + 'ms');
                pumpProgress(h);
                return h;
            } catch (e) {
                // 渐进式方案失败时退回整集下载，保证兼容性。
                var source = await self.mediaSource(vid, q, device);
                var plain = source.remote
                    ? (await (async () => {
                        var parts = [], session2 = cloneCencSession(source, 0);
                        for await (var c of cencRemoteByteStream(session2, 0, source.total - 1)) parts.push(c);
                        return concatAll(parts);
                    })())
                    : decryptCencAll({data: source.data, regions: source.regions, aes: source.aes, next: 0});
                if (!plain || plain.length < 64) throw new Error('解密结果异常');
                cachePut(key, plain);
                dropSource(key);
                return {key: key, data: plain, total: plain.length, frontier: plain.length,
                    done: true, finished: true, error: null, waiters: []};
            }
        })();
        PROGRESS_PENDING[key] = pending;
        try { return await pending; }
        finally { delete PROGRESS_PENDING[key]; }
    }

    // 只等前 target 字节就绪就返回；用于 playerContent 秒开。
    async mediaStart(vid, q, device, target) {
        var h = await this.openProgressive(vid, q, device);
        var want = Math.min(h.total - 1, Math.max(0, (target || (4 << 20)) - 1));
        h.playerEnd = want;
        await waitProgress(h, want);
        if (h.error) throw h.error;
        // 首帧出去后立即降回低并发，避免后台和播放器抢网络/AES。
        if (h.setAhead && !h.fastAheadDone) { h.setAhead(3); h.fastAheadDone = true; }
        return h;
    }

    // 等整集明文就绪；调试/兼容性接口使用。
    async mediaBytes(vid, q, device) {
        var key = String(vid) + '|' + q;
        var cached = cacheGet(key);
        if (cached) return cached;
        var h = await this.openProgressive(vid, q, device);
        h.playerEnd = h.total - 1;
        wakeProgress(h);
        await waitProgress(h, h.total - 1);
        if (h.error) throw h.error;
        return h.data;
    }

    // 后台预热指定集：只等开头就绪即可，其余在后台继续补齐。
    // 当前集播放只读本地内存，因此后台下载不会再造成播放卡顿。
    prewarmEpisode(vid, q, device) {
        // 稳定优先：播放期间 PREWARM_ACTIVE 为 false，所有预热入口直接空转。
        if (!PREWARM_ACTIVE) return Promise.resolve();
        var key = String(vid) + '|' + q;
        if (!vid || NEXT_WARMED[key]) return Promise.resolve();
        NEXT_WARMED[key] = Date.now();
        try {
            return this.mediaStart(String(vid), q, device, 4 << 20).catch(function () {
                delete NEXT_WARMED[key];
            });
        } catch (e) {
            delete NEXT_WARMED[key];
            return Promise.resolve();
        }
    }

    async playerContent(flag, id, vipFlags) {
        var pcStart = Date.now();
        var parts = splitEpisodeToken(id), q = parts[0], vid = parts[1];
        var lineQ = '1080';
        var names = Object.keys(QUALITY_NAME_TO_Q);
        for (var i = 0; i < names.length; i++) {
            if (String(flag || '').indexOf(names[i]) >= 0) { lineQ = QUALITY_NAME_TO_Q[names[i]]; break; }
        }
        if (q === '1080' && String(flag || '')) q = lineQ;
        if (!/^\d+$/.test(String(vid))) {
            return {parse: 1, jx: 0, playUrl: '', url: SITE + '/', header: {'User-Agent': UA}};
        }
        var device = await this.registerDevice();
        var warmDevice = {device_id: device.device_id, install_id: device.install_id,
            device_token: device.device_token || '', cdid: device.cdid || ''};
        var self = this;
        LAST_PLAYED_VID = String(vid);
        // 播放一旦开始，绝不再做任何后台预热：电视盒的网络请求会同步阻塞
        // QuickJS 线程，实测让播放中的 proxy 排队 3~6 秒，必须彻底禁止。
        PREWARM_ACTIVE = false;
        this.mediaStart(String(vid), q, warmDevice, PROXY_START_WINDOW).catch(function (e) {
            self.lastError = String(e && e.message || e);
        });
        // proxy() 在 FongMi 中可能由新实例处理，必须把完整注册身份随 URL 传过去；
        // 尤其是 cdid，缺失时 V5 签名接口会拒绝播放请求。
        var params = {vid: String(vid), q: q, did: device.device_id, iid: device.install_id,
            dt: device.device_token || '', cdid: device.cdid || '',
            next: String(NEXT_EPISODE[String(vid)] || '')};
        var url = '';
        try {
            if (typeof this.proxyUrl === 'function') url = this.proxyUrl(params);
            else if (typeof this.getProxyUrl === 'function') url = this.getProxyUrl() + '?' +
                Object.keys(params).map(function (k) { return k + '=' + encodeURIComponent(params[k]); }).join('&');
        } catch (e) { url = ''; }
        if (!url) return {parse: 1, jx: 0, playUrl: '', url: SITE + '/', header: {'User-Agent': UA}};
        hgLog('hg playerContent ready', vid, q, (Date.now() - pcStart) + 'ms');
        return {parse: 0, jx: 0, playUrl: '', url: url, format: 'video/mp4',
            header: {'User-Agent': MEDIA_UA, 'Referer': 'https://novel.snssdk.com/'}};
    }

    async proxy(params) {
        params = params || {};
        hgLog('hg proxy enter', JSON.stringify({do: params.do || '', siteKey: params.siteKey || '',
            vid: params.vid || '', q: params.q || '', range: params.Range || params.range || '', debug: params.debug || ''}));
        if (String(params.debug || '') === '1') {
            return [200, 'text/plain; charset=utf-8', JSON.stringify({ok: true, route: 'js-proxy',
                do: params.do || '', siteKey: params.siteKey || '', vid: params.vid || '',
                q: params.q || '', range: params.Range || params.range || '',
                device: !!(params.did && params.iid), cache: Object.keys(MEDIA_CACHE)}),
                {'Content-Type': 'text/plain; charset=utf-8'}];
        }
        var vid = String(params.vid || params.id || params.mediaId || '').trim();
        if (!/^\d+$/.test(vid)) {
            var keys = Object.keys(params);
            for (var i = 0; i < keys.length; i++) {
                var v = String(params[keys[i]] || '').trim();
                if (/^\d{10,}$/.test(v)) { vid = v; break; }
            }
        }
        if (!vid) return [400, 'text/plain; charset=utf-8', 'missing vid'];
        var localDevice = this.device || {};
        var device = {
            device_id: String(params.did || localDevice.device_id || ''),
            install_id: String(params.iid || localDevice.install_id || ''),
            device_token: String(params.dt || localDevice.device_token || ''),
            cdid: String(params.cdid || localDevice.cdid || ''),
        };
        if (!device.device_id || !device.install_id) {
            try { device = await this.registerDevice(); } catch (e) { this.lastError = String(e && e.message || e); }
        }
        if (!device.cdid) device.cdid = uuid();
        var wanted = String(params.q || params.quality || '').trim() || '1080';
        var order = [], seen = {};
        var list = [wanted, '720', '480', '360', '1080'];
        for (var j = 0; j < list.length; j++) if (list[j] && !seen[list[j]]) { seen[list[j]] = 1; order.push(list[j]); }
        // FongMi 会把 HTTP 请求头合并进 params。播放器经常先发 Range 探测，
        // 如果一律回 200 整段，部分内核会直接判为无法播放。
        var rangeHeader = String(params.Range || params.range || params.HTTP_RANGE || '').trim();
        if (String(params.debug || '') === '2') {
            var started = Date.now();
            try {
                var probe = await this.mediaBytes(vid, order[0], device);
                return [200, 'text/plain; charset=utf-8', JSON.stringify({ok: true, vid: vid, q: order[0],
                    len: probe.length, ms: Date.now() - started, sha512: bytesToHex(sha512(probe)),
                    head: bytesToHex(probe.subarray(0, 32))}),
                    {'Content-Type': 'text/plain; charset=utf-8'}];
            } catch (e) {
                return [500, 'text/plain; charset=utf-8', JSON.stringify({ok: false,
                    error: String(e && e.message || e), ms: Date.now() - started}),
                    {'Content-Type': 'text/plain; charset=utf-8'}];
            }
        }
        if (String(params.debug || '') === '3') {
            var t3 = Date.now();
            try {
                var src3 = await this.mediaSource(vid, order[0], device);
                var first3 = src3.regions[0] || null, last3 = src3.regions[src3.regions.length - 1] || null;
                var total3 = src3.total || (src3.data ? src3.data.length : 0);
                var head3 = src3.data ? src3.data.subarray(0, 32)
                    : (src3.moovStart === 0 ? src3.moov.subarray(0, 32) : (await src3.fetch(0, 31)).bytes);
                return [200, 'text/plain; charset=utf-8', JSON.stringify({ok: true, vid: vid,
                    q: order[0], stream: !!(NET && typeof NET.stream === 'function'),
                    remote: !!src3.remote, len: total3, regions: src3.regions.length,
                    first: first3 ? [first3.start, first3.size] : null,
                    last: last3 ? [last3.start, last3.size] : null,
                    head: bytesToHex(head3), ms: Date.now() - t3}),
                    {'Content-Type': 'text/plain; charset=utf-8'}];
            } catch (e) {
                return [500, 'text/plain; charset=utf-8', JSON.stringify({ok: false,
                    error: String(e && e.message || e), ms: Date.now() - t3}),
                    {'Content-Type': 'text/plain; charset=utf-8'}];
            }
        }
        var lastErr = '';
        // 最快路径：预热已把整集解成明文缓存，直接返回 Range 字节数组，
        // 完全跳过 net.stream() 的逐块 JS/Java 回调。
        var plainReady = null, plainQ = '';
        for (var pr = 0; pr < 2 && !plainReady; pr++) {
            for (var pc = 0; pc < order.length; pc++) {
                var candidate = cacheGet(vid + '|' + order[pc]);
                if (candidate && candidate.length > 64) { plainReady = candidate; plainQ = order[pc]; break; }
            }
            // playerContent 可能被框架提前超时返回，但预热仍在跑；等它完成后
            // 仍走明文直出，绝不退化成播放中逐块解密。
            if (!plainReady) {
                var pendingPlain = null;
                for (var pp = 0; pp < order.length; pp++) {
                    if (MEDIA_PENDING[vid + '|' + order[pp]]) {
                        pendingPlain = MEDIA_PENDING[vid + '|' + order[pp]];
                        break;
                    }
                }
                if (pendingPlain) {
                    try { await pendingPlain; } catch (e) {}
                    continue;
                }
            }
        }
        if (plainReady) {
            var rangedPlain = parseProxyRange(rangeHeader, plainReady.length);
            if (rangedPlain.status === 416) {
                return [416, 'text/plain; charset=utf-8', 'invalid range', rangedPlain.headers];
            }
            var plainSlice = plainReady.subarray(rangedPlain.start, rangedPlain.end + 1);
            hgLog('hg proxy plain', vid, plainQ, rangedPlain.status, rangedPlain.start,
                rangedPlain.end, plainReady.length, rangeHeader || 'full');
            return [rangedPlain.status, 'video/mp4', proxyBody(plainSlice), rangedPlain.headers, 1];
        }
        // 渐进式明文缓冲：开头已就绪，播放器要哪段就等后台补齐到哪段，
        // 然后同样整段直出。播放期间没有回源、没有 AES、没有逐块回调。
        var prog = null, progQ = '';
        for (var qc = 0; qc < order.length; qc++) {
            var ph = progressGet(vid + '|' + order[qc]);
            if (ph) { prog = ph; progQ = order[qc]; break; }
        }
        if (!prog) {
            for (var qp = 0; qp < order.length; qp++) {
                var ppending = PROGRESS_PENDING[vid + '|' + order[qp]];
                if (ppending) {
                    try { await ppending; } catch (e) {}
                    prog = progressGet(vid + '|' + order[qp]);
                    if (prog) { progQ = order[qp]; break; }
                }
            }
        }
        // 无 Range 的完整文件请求不能只回 512KB；交给后面的流式兜底返回整集。
        if (prog && (String(rangeHeader || '').trim() || prog.done)) {
            var rangedProg = parseProxyRange(rangeHeader, prog.total, PROXY_START_WINDOW, HG_OPEN_WINDOW);
            if (rangedProg.status === 416) {
                return [416, 'text/plain; charset=utf-8', 'invalid range', rangedProg.headers];
            }
            // playerContent 可能超时没走到 mediaStart；proxy 首请求同样立即降回低并发。
            if (prog.setAhead && !prog.fastAheadDone) { prog.setAhead(3); prog.fastAheadDone = true; }
            // 播放器跳到 moov 读索引时直接从内存里的明文盒返回，不等顺序缓冲。
            var mr = progressMoovRange(prog, rangedProg.start, rangedProg.end);
            if (rangedProg.status === 206 && mr && mr.from === rangedProg.start && mr.to <= rangedProg.end) {
                if (mr.to !== rangedProg.end) {
                    rangedProg.end = mr.to;
                    rangedProg.headers['Content-Range'] = 'bytes ' + mr.from + '-' + mr.to + '/' + prog.total;
                    rangedProg.headers['Content-Length'] = String(mr.to - mr.from + 1);
                }
                var moovSlice = prog.moov.subarray(
                    mr.from - prog.moovStart, mr.to - prog.moovStart + 1).slice();
                hgLog('hg proxy moov', vid, progQ, mr.from, mr.to, prog.frontier);
                return [206, 'video/mp4', proxyBody(moovSlice), rangedProg.headers, 1];
            }
            // 之前直达补过的区间（或顺序缓冲已覆盖的区间）直接本地返回。
            if (rangedProg.status === 206 &&
                    progressRescueCover(prog, rangedProg.start, rangedProg.end)) {
                prog.playerEnd = Math.max(prog.playerEnd || 0, rangedProg.end);
                wakeProgress(prog);
                hgLog('hg proxy rescued-cache', vid, progQ, rangedProg.start,
                    rangedProg.end, prog.frontier);
                return [rangedProg.status, 'video/mp4',
                    proxyBody(prog.data.subarray(rangedProg.start, rangedProg.end + 1)),
                    rangedProg.headers, 1];
            }
            // 开局探针要等开头窗口；非开头 Range 若后台还没走到，
            // 只补缺口：已经顺序解密的部分直接复用，不重复回源、不重复解密。
            var need = rangedProg.end;
            if (rangedProg.start === 0) {
                need = Math.max(need, Math.min(prog.total - 1, PROXY_START_WINDOW - 1));
            } else if (rangedProg.end > prog.frontier &&
                       prog.session && prog.rawFetcher) {
                prog.hold = true;
                var rescueStart = Math.max(rangedProg.start, Math.min(prog.frontier, rangedProg.end));
                // 必须走分块预取：直接用 rawFetcher 会按 CENC 样本逐个发 Range，
                // 1MB 能打出 389 个请求（真机 netOps=389，卡 11 秒）。
                var rescuePrefetch = makePrefetchFetcher(
                    prog.rawFetcher, 1 << 18, 4, prog.total);
                var rescueSession = cloneCencSession(prog.session, rescueStart);
                rescueSession.fetch = rescuePrefetch.fetch;
                try {
                    var rescueParts = [];
                    if (rescueStart > rangedProg.start) {
                        rescueParts.push(prog.data.subarray(rangedProg.start, rescueStart));
                    }
                    for await (var rescueChunk of cencRemoteByteStream(
                            rescueSession, rescueStart, rangedProg.end)) {
                        rescueParts.push(u8(rescueChunk));
                    }
                    var rescueBytes = concatAll(rescueParts);
                    prog.data.set(rescueBytes, rangedProg.start);
                    progressRescueRemember(prog, rangedProg.start, rangedProg.end);
                    if (prog.rescueLeft > 0) prog.rescueLeft--;
                    prog.playerEnd = Math.max(prog.playerEnd || 0, rangedProg.end);
                    prog.hold = false;
                    wakeProgress(prog);
                    hgLog('hg proxy rescue', vid, progQ, rescueStart, rangedProg.end,
                        prog.frontier, prog.rescueLeft);
                    return [rangedProg.status, 'video/mp4', proxyBody(rescueBytes), rangedProg.headers, 1];
                } catch (rescueErr) {
                    prog.hold = false;
                    wakeProgress(prog);
                    hgLog('hg proxy rescue failed', vid, String(rescueErr && rescueErr.message || rescueErr));
                }
            }
            // 更新播放器实际位置并唤醒后台；后台只补到领先 4MB 处就暂停。
            prog.playerEnd = Math.max(prog.playerEnd || 0, rangedProg.end);
            wakeProgress(prog);
            var waitT0 = Date.now();
            await waitProgress(prog, need);
            var waited = Date.now() - waitT0;
            if (waited > 150) hgLog('hg proxy wait', vid, waited + 'ms', rangeHeader || 'full', prog.frontier);
            if (prog.error) {
                lastErr = String(prog.error && prog.error.message || prog.error);
                hgLog('hg proxy progress failed', vid, lastErr);
                prog = null;
            } else {
                var progSlice = prog.data.subarray(rangedProg.start, rangedProg.end + 1);
                hgLog('hg proxy progress', vid, progQ, rangedProg.status, rangedProg.start,
                    rangedProg.end, prog.frontier, prog.total, rangeHeader || 'full');
                return [rangedProg.status, 'video/mp4', proxyBody(progSlice), rangedProg.headers, 1];
            }
        }
        // 以上都不可用时的兜底：net.stream() 逐块解密，避免 proxy 长时间不返回。
        if (NET && typeof NET.stream === 'function') {
            var streamSource = null, streamQ = '';
            for (var c = 0; c < order.length; c++) {
                var full = cacheGet(vid + '|' + order[c]);
                if (full) { streamSource = {data: full, regions: [], next: 0, key: ''}; streamQ = order[c]; break; }
            }
            if (!streamSource) {
                for (var s = 0; s < order.length; s++) {
                    try {
                        var t1 = Date.now();
                        streamSource = await this.mediaSource(vid, order[s], device);
                        streamQ = order[s];
                        hgLog('hg proxy source', vid, streamQ,
                            streamSource.total || (streamSource.data ? streamSource.data.length : 0),
                            (Date.now() - t1) + 'ms', rangeHeader || 'full', streamSource.remote ? 'range' : 'full');
                        lastErr = '';
                        break;
                    } catch (e) {
                        lastErr = String(e && e.message || e);
                        hgLog('hg proxy quality failed', vid, order[s], lastErr);
                    }
                }
            }
            if (streamSource) {
                var streamTotal = streamSource.total || (streamSource.data ? streamSource.data.length : 0);
                var ranged = parseProxyRange(rangeHeader, streamTotal);
                if (ranged.status === 416) {
                    return [416, 'text/plain; charset=utf-8', 'invalid range', ranged.headers];
                }
                try {
                    var session = cloneCencSession(streamSource, ranged.start);
                    var streamBody = session.remote
                        ? cencRemoteByteStream(session, ranged.start, ranged.end)
                        : cencByteStream(session, ranged.start, ranged.end);
                    var streamReply = await NET.stream(streamBody);
                    hgLog('hg proxy stream', vid, streamQ, ranged.status, ranged.start, ranged.end,
                        streamTotal, session.remote ? 'range' : 'full');
                    return [ranged.status, 'video/mp4', streamReply.stream, ranged.headers, 1];
                } catch (e) {
                    lastErr = String(e && e.message || e);
                    hgLog('hg proxy stream failed', vid, lastErr);
                }
            }
        }
        // 老版 FongMi 没有流式 proxy，只能一次性解密返回（可能触发 30 秒限制）。
        for (var k = 0; k < order.length; k++) {
            try {
                var t0 = Date.now();
                var bytes = await this.mediaBytes(vid, order[k], device);
                hgLog('hg proxy media', vid, order[k], bytes.length, (Date.now() - t0) + 'ms', rangeHeader || 'full');
                var ranged2 = parseProxyRange(rangeHeader, bytes.length);
                if (ranged2.status === 416) {
                    return [416, 'text/plain; charset=utf-8', 'invalid range', ranged2.headers];
                }
                var slice = bytes.subarray(ranged2.start, ranged2.end + 1);
                if (ranged2.status === 206) ranged2.headers['Content-Length'] = String(slice.length);
                return [ranged2.status, 'video/mp4', proxyBody(slice), ranged2.headers, 1];
            } catch (e) {
                lastErr = String(e && e.message || e);
                hgLog('hg proxy quality failed', vid, order[k], lastErr);
            }
        }
        hgLog('hg proxy failed', vid, lastErr);
        return [500, 'text/plain; charset=utf-8', 'hg js proxy failed: ' + lastErr];
    }
}

