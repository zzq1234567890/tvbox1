// HQPorner v1.0.1 -> FongMi / 影视TV QuickJS spider
// Site config: {"key":"hqporner","name":"HQPorner","type":3,"api":"./HQPorner.js","ext":{}}
// ext 可选：{"site":"https://hqporner.com","timeout":20000,"pageSize":50}

import {Spider, link} from "catvod";

const DEFAULT_SITE = "https://hqporner.com";
const DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
const DEFAULT_TIMEOUT = 20000;
const DEFAULT_PAGE_SIZE = 50;

// 64 个分类，取自 https://hqporner.com/categories
const CATEGORIES = [
    ["1080p-porn", "1080p porn"], ["4k-porn", "4k porn"], ["60fps-porn", "60fps"],
    ["amateur", "amateur"], ["anal-sex-hd", "anal"], ["asian", "asian"],
    ["babe", "babe"], ["bdsm", "bdsm"], ["beach-porn", "beach"],
    ["big-ass", "big ass"], ["big-dick", "big dick"], ["big-tits", "big tits"],
    ["bisexual", "bisexual"], ["blonde", "blonde"], ["blowjob", "blowjob"],
    ["bondage", "bondage"], ["brunette", "brunette"], ["casting", "casting"],
    ["creampie", "creampie"], ["cumshot", "cumshot"], ["deepthroat", "deepthroat"],
    ["ebony", "ebony"], ["fetish", "fetish"], ["fingering", "fingering"],
    ["fisting", "fisting"], ["gangbang", "gangbang"], ["group-sex", "group sex"],
    ["hairy-pussy", "hairy pussy"], ["handjob", "handjob"], ["hentai", "hentai"],
    ["interracial", "interracial"], ["japanese-girls-porn", "japanese"], ["latina", "latina"],
    ["lesbian", "lesbian"], ["long-hair", "long hair"], ["masturbation", "masturbation"],
    ["mature", "mature"], ["milf", "milf"], ["moaning", "moaning"],
    ["old-and-young", "old and young"], ["orgasm", "orgasm"], ["orgy", "orgy"],
    ["outdoor", "outdoor"], ["pickup", "pickup"], ["pov", "pov"],
    ["public", "public"], ["pussy-licking", "pussy licking"], ["redhead", "redhead"],
    ["russian", "russian"], ["porn-massage", "sex massage"], ["sex-parties", "sex party"],
    ["shaved-pussy", "shaved pussy"], ["shemale", "shemale"], ["small-tits", "small tits"],
    ["squeezing-tits", "squeezing tits"], ["squirt", "squirt"], ["stockings", "stockings"],
    ["tattooed", "tattooed"], ["teen-porn", "teen porn"], ["threesome", "threesome"],
    ["undressing", "undressing"], ["uniforms", "uniforms"], ["vibrator", "vibrator"],
    ["vintage", "vintage"],
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

function absUrl(url, base) {
    const value = str(url).trim();
    if (!value) return "";
    if (/^https?:\/\//i.test(value)) return value;
    if (/^\/\//.test(value)) return "https:" + value;
    if (/^\//.test(value)) return base.replace(/\/+$/, "") + value;
    return base.replace(/\/+$/, "") + "/" + value;
}

function cleanText(value) {
    return str(value)
        .replace(/<[^>]*>/g, " ")
        .replace(/&nbsp;/gi, " ")
        .replace(/&amp;/gi, "&")
        .replace(/&quot;/gi, '"')
        .replace(/&#39;|&apos;/gi, "'")
        .replace(/&lt;/gi, "<")
        .replace(/&gt;/gi, ">")
        .replace(/\s+/g, " ")
        .trim();
}

function firstMatch(text, regex, index = 1) {
    const match = regex.exec(text);
    return match ? str(match[index]) : "";
}

function unique(list) {
    const seen = {};
    const result = [];
    for (const item of list) {
        const key = str(item);
        if (!key || seen[key]) continue;
        seen[key] = true;
        result.push(item);
    }
    return result;
}

function pageCount(html, current) {
    const block = firstMatch(html, /<ul class="actions pagination">([\s\S]*?)<\/ul>/i);
    if (!block) return current;
    const numbers = [];
    const regex = /href="[^"]*?(?:[?&]p=|\/)(\d+)[^"]*"/gi;
    let match;
    while ((match = regex.exec(block)) !== null) numbers.push(parseInt(match[1], 10));
    if (!numbers.length) return current;
    const max = Math.max.apply(null, numbers);
    return Math.max(current, isFinite(max) ? max : current);
}

function parseVideos(html, site) {
    const items = [];
    const seen = {};
    const chunks = html.split(/<section class="box feature"/i).slice(1);
    for (const chunk of chunks) {
        const href = firstMatch(chunk, /href="(\/hdporn\/[^"'<> ]+\.html)"/i);
        if (!href) continue;
        const id = href.replace(/^\//, "");
        if (seen[id]) continue;
        seen[id] = true;

        const pic = firstMatch(chunk, /<img[^>]+id="cover_\d+"[^>]+src="([^"]+)"/i)
            || firstMatch(chunk, /<img[^>]+src="([^"]+)"/i);
        const title = cleanText(firstMatch(chunk, /<h3 class="meta-data-title">[\s\S]*?<a[^>]*>([\s\S]*?)<\/a>/i));
        const remarks = cleanText(firstMatch(chunk, /<span class="icon fa-clock-o meta-data">([\s\S]*?)<\/span>/i));
        items.push({
            vod_id: id,
            vod_name: title || id,
            vod_pic: absUrl(pic, site),
            vod_remarks: remarks,
            style: {type: "rect", ratio: 1.78},
        });
    }
    return items;
}

function parseActresses(html) {
    const items = [];
    const seen = {};
    const regex = /href="(\/actress\/[^"'<> ]+)"[^>]*>([\s\S]*?)<\/a>/gi;
    let match;
    while ((match = regex.exec(html)) !== null) {
        const slug = match[1].replace(/^\/actress\//, "").replace(/\/$/, "");
        const name = cleanText(match[2]);
        if (!slug || seen[slug]) continue;
        seen[slug] = true;
        items.push({
            vod_id: "actress/" + slug,
            vod_name: name || slug.replace(/-/g, " "),
            vod_remarks: "女优",
            vod_tag: "folder",
            style: {type: "list"},
        });
    }
    return items;
}

function parseQualities(html) {
    const urls = [];
    const regex = /(?:(?:https?:)?\/\/[a-z0-9.-]+)?\/pubs\/[^"'<>\s]+?\.(?:mp4)/gi;
    let match;
    while ((match = regex.exec(html)) !== null) {
        let url = match[0];
        if (/^\/\//.test(url)) url = "https:" + url;
        else if (/^\//.test(url)) url = "https://bigcdn.cc" + url;
        else if (!/^https?:/i.test(url)) url = "https://" + url;
        urls.push(url.split("&amp;")[0]);
    }
    return unique(urls);
}

function qualityScore(url) {
    if (/(2160|4k)/i.test(url)) return 2160;
    if (/1080/i.test(url)) return 1080;
    if (/720/i.test(url)) return 720;
    if (/480/i.test(url)) return 480;
    if (/360/i.test(url)) return 360;
    return 0;
}

function pickBestUrl(html) {
    const urls = parseQualities(html);
    if (!urls.length) return "";
    let best = urls[0];
    let score = qualityScore(best);
    for (const url of urls) {
        const value = qualityScore(url);
        if (value > score) {
            best = url;
            score = value;
        }
    }
    return best;
}

export default class HQPorner extends Spider {
    init(extend = "") {
        const options = parseExtend(extend);
        this.site = str(options.site || DEFAULT_SITE).replace(/\/+$/, "");
        this.timeout = parseInt(options.timeout, 10) || DEFAULT_TIMEOUT;
        this.pageSize = parseInt(options.pageSize, 10) || DEFAULT_PAGE_SIZE;
        this.ua = str(options.userAgent || DEFAULT_UA);
    }

    async fetch(url, referer) {
        const response = await this.net.req(url, {
            method: "GET",
            headers: {
                "User-Agent": this.ua,
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": referer || this.site + "/",
            },
            timeout: this.timeout,
            callTimeout: this.timeout,
        });
        if (response.error) throw new Error(response.error);
        if (response.code < 200 || response.code >= 300) throw new Error("HTTP " + response.code);
        const content = response.content;
        if (content == null) return "";
        return typeof content === "string" ? content : String(content);
    }

    videoUrl(tid, pg) {
        const page = Math.max(1, parseInt(pg, 10) || 1);
        const base = this.site;
        if (tid === "latest") return page === 1 ? base + "/" : base + "/hdporn/" + page;
        if (tid === "hot") return page === 1 ? base + "/top" : base + "/top/" + page;
        if (tid === "hot-month") return page === 1 ? base + "/top/month" : base + "/top/month/" + page;
        if (tid === "hot-week") return page === 1 ? base + "/top/week" : base + "/top/week/" + page;
        if (tid.indexOf("cat/") === 0) {
            const slug = tid.slice(4);
            return page === 1 ? base + "/category/" + slug : base + "/category/" + slug + "/" + page;
        }
        if (tid.indexOf("actress/") === 0) {
            const slug = tid.slice(8);
            return page === 1 ? base + "/actress/" + slug : base + "/actress/" + slug + "/" + page;
        }
        return "";
    }

    homeContent(filter) {
        const classes = [
            {type_id: "latest", type_name: "最新"},
            {type_id: "hot", type_name: "热门"},
            {type_id: "hot-month", type_name: "热门-月榜"},
            {type_id: "hot-week", type_name: "热门-周榜"},
            {type_id: "actress", type_name: "女优", type_flag: "1"},
        ];
        for (const item of CATEGORIES) {
            classes.push({type_id: "cat/" + item[0], type_name: item[1]});
        }
        return {class: classes};
    }

    async homeVideoContent() {
        return this.categoryContent("latest", "1", false, {});
    }

    async categoryContent(tid, pg, filter, extend) {
        const page = Math.max(1, parseInt(pg, 10) || 1);
        if (tid === "actress") {
            try {
                const html = await this.fetch(this.site + "/");
                return {
                    page: 1, pagecount: 1, limit: this.pageSize,
                    total: parseActresses(html).length, list: parseActresses(html),
                };
            } catch (error) {
                return {page: 1, pagecount: 1, limit: this.pageSize, total: 0, list: []};
            }
        }

        const url = this.videoUrl(tid, page);
        if (!url) return {page, pagecount: page, limit: this.pageSize, total: 0, list: []};
        try {
            const html = await this.fetch(url);
            const list = parseVideos(html, this.site);
            return {
                page,
                pagecount: pageCount(html, page),
                limit: this.pageSize,
                total: list.length,
                list,
            };
        } catch (error) {
            return {page, pagecount: page, limit: this.pageSize, total: 0, list: []};
        }
    }

    async detailContent(ids) {
        const result = [];
        const list = Array.isArray(ids) ? ids : [ids];
        for (const rawId of list) {
            const id = str(rawId).replace(/^\/?hdporn\//, "");
            if (!id) continue;
            try {
                const html = await this.fetch(this.site + "/hdporn/" + id);
                const title = cleanText(firstMatch(html, /<h1 class="main-h1"[^>]*>([\s\S]*?)<\/h1>/i));
                if (!title) continue;

                const description = cleanText(firstMatch(html, /<meta name="description" content="([^"]*)"/i));
                const date = cleanText(firstMatch(html, /<li class="icon fa-calendar">([\s\S]*?)<\/li>/i));
                const duration = cleanText(firstMatch(html, /<li class="icon fa-clock-o">([\s\S]*?)<\/li>/i));

                const categories = [];
                const catRegex = /href="(\/category\/[^"'<> ]+)"[^>]*class="[^"]*tag-link[^"]*"[^>]*>([\s\S]*?)<\/a>/gi;
                let catMatch;
                while ((catMatch = catRegex.exec(html)) !== null) {
                    categories.push(cleanText(catMatch[2]));
                }

                const actors = [];
                const actorRegex = /href="(\/actress\/[^"'<> ]+)"[^>]*>([\s\S]*?)<\/a>/gi;
                let actorMatch;
                while ((actorMatch = actorRegex.exec(html)) !== null) {
                    const slug = actorMatch[1].replace(/^\/actress\//, "").replace(/\/$/, "");
                    const name = cleanText(actorMatch[2]);
                    if (slug && name) actors.push({slug, name});
                }

                const embedRaw = firstMatch(html, /((?:https?:)?\/\/mydaddy\.cc\/video\/[a-z0-9]+\/)/i);
                const embed = embedRaw ? absUrl(embedRaw, "https://mydaddy.cc") : "";
                const playId = embed ? "play/" + encodeURIComponent(embed) : "";
                const actorText = unique(actors.map((actor) =>
                    link(actor.name, {id: "actress/" + actor.slug, name: actor.name, type_flag: "1"}))).join(",");

                const vod = {
                    vod_id: id,
                    vod_name: title,
                    vod_type: unique(categories).join(","),
                    vod_tag: unique(categories).join(","),
                    vod_actor: actorText,
                    vod_remarks: [duration, date].filter(Boolean).join(" · "),
                    vod_area: "欧美",
                    vod_content: description,
                    vod_play_from: playId ? "HQPorner" : "",
                    vod_play_url: playId ? "正片$" + playId : "",
                };
                result.push(vod);
            } catch (error) {
                // 影片不存在或读取失败时返回空来源，不抛错
            }
        }
        return {list: result};
    }

    async searchContent(key, quick, pg = "1") {
        const page = Math.max(1, parseInt(pg, 10) || 1);
        const keyword = str(key).trim();
        if (!keyword) return {page, pagecount: page, limit: this.pageSize, total: 0, list: []};
        const query = encodeURIComponent(keyword);
        const url = page === 1
            ? this.site + "/?q=" + query
            : this.site + "/?q=" + query + "&p=" + page;
        try {
            const html = await this.fetch(url);
            const list = parseVideos(html, this.site);
            return {
                page,
                pagecount: pageCount(html, page),
                limit: this.pageSize,
                total: list.length,
                list,
            };
        } catch (error) {
            return {page, pagecount: page, limit: this.pageSize, total: 0, list: []};
        }
    }

    async playerContent(flag, id, vipFlags) {
        const raw = str(id);
        if (raw.indexOf("play/") !== 0) return {parse: 0, url: "", msg: "无效的播放地址"};
        let embed;
        try {
            embed = decodeURIComponent(raw.slice(5));
        } catch (error) {
            return {parse: 0, url: "", msg: "无效的播放地址"};
        }
        embed = absUrl(embed, "https://mydaddy.cc");
        if (!/^https?:\/\/mydaddy\.cc\//i.test(embed)) return {parse: 0, url: "", msg: "无效的播放地址"};
        try {
            const html = await this.fetch(embed, this.site + "/");
            const url = pickBestUrl(html);
            if (!url) return {parse: 0, url: "", msg: "未找到可用播放地址"};
            return {
                parse: 0,
                jx: 0,
                url,
                header: {
                    "User-Agent": this.ua,
                    "Referer": "https://mydaddy.cc/",
                },
            };
        } catch (error) {
            return {parse: 0, url: "", msg: "播放地址解析失败"};
        }
    }

    home(filter) { return this.homeContent(filter); }
    homeVod() { return this.homeVideoContent(); }
    category(tid, pg, filter, extend) { return this.categoryContent(tid, pg, filter, extend); }
    detail(id) { return this.detailContent(Array.isArray(id) ? id : [id]); }
    search(wd, quick, pg) { return this.searchContent(wd, quick, pg); }
    play(flag, id, vipFlags) { return this.playerContent(flag, id, vipFlags); }
}
