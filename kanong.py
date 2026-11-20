#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""卡农羊毛区关键词监控 - GitHub Actions 定时任务版（零依赖，仅标准库）

与手机单文件版的区别：
1. 推送令牌从环境变量 WXP_SPT 读取（在 GitHub 仓库 Secret 里配置，不写死在代码中）
2. 去重记录存到 seen.json，由 GitHub Actions 每次运行后 git commit 持久化
3. 单次运行抓取一轮就退出，靠 GitHub Actions 的 cron 定时触发（无需常驻）
"""
import os, re, sys, time, hashlib, json, urllib.request
from http.cookiejar import CookieJar
from urllib.parse import urljoin

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BASE = "https://www.51kanong.com/"
URLS = [BASE + "yh-282-1.htm", BASE + "yh-169-1.htm"]
NAMES = {"yh-282": "羊毛专区", "yh-169": "羊毛交流"}
NUMS = [
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15",
    "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30",
    "31", "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "42", "43", "44", "45",
    "46", "47", "48", "49", "50", "51", "52", "53", "54", "55", "56", "57", "58", "59", "60",
    "61", "62", "63", "64", "65", "66", "67", "68", "69", "70", "71", "72", "73", "74", "75",
    "76", "77", "78", "79", "80", "81", "82", "83", "84", "85", "86", "87", "88", "89", "90",
    "91", "92", "93", "94", "95", "96", "97", "98", "99", "100", "101", "102", "103", "104", "105",
    "106", "107", "108", "109", "110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120",
    "121", "122", "123", "124", "125", "126", "127", "128", "129", "130", "131", "132", "133", "134", "135",
    "136", "137", "138", "139", "140", "141", "142", "143", "144", "145", "146", "147", "148", "149", "150",
    "151", "152", "153", "154", "155", "156", "157", "158", "159", "160", "161", "162", "163", "164", "165",
    "166", "167", "168", "169", "170", "171", "172", "173", "174", "175", "176", "177", "178", "179", "180",
    "181", "182", "183", "184", "185", "186", "187", "188", "189", "190", "191", "192", "193", "194", "195",
    "196", "197", "198", "199", "200", "201", "202", "203", "204", "205", "206", "207", "208", "209", "210",
    "211", "212", "213", "214", "215", "216", "217", "218", "219", "220", "221", "222", "223", "224", "225",
    "226", "227", "228", "229", "230", "231", "232", "233", "234", "235", "236", "237", "238", "239", "240",
    "241", "242", "243", "244", "245", "246", "247", "248", "249", "250", "251", "252", "253", "254", "255",
    "256", "257", "258", "259", "260", "261", "262", "263", "264", "265", "266", "267", "268", "269", "270",
    "271", "272", "273", "274", "275", "276", "277", "278", "279", "280", "281", "282", "283", "284", "285",
    "286", "287", "288", "289", "290", "291", "292", "293", "294", "295", "296", "297", "298", "299", "300",
]
KEYWORDS = ["人人", "速度", "几毛", "信用卡", "银行", "招商", "工商", "建行", "中行", "农行", "工行", "交行", "农业", "交通", "浦发", "中信", "光大", "华夏", "民生", "广发", "兴业", "平安", "邮储", "农商", "信用社", "浙商", "渤海", "恒丰", "徽商"] + NUMS
EXCLUDE = ["招聘", "版规", "公告"]

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN_FILE = os.path.join(HERE, "seen.json")
# 令牌从环境变量读取；本地调试也可临时在此填，但 GitHub 上请务必用 Secret
WXP_SPT = os.environ.get("WXP_SPT", "").strip()
WXP_API = "https://wxpusher.zjiecode.com/api/send/message/simple-push"
MAX_PUSH = 10  # 单轮最多推送条数，防止刷屏


def fetch(url, retries=3):
    jar = CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    last = ""
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9", "Referer": BASE})
            data = op.open(req, timeout=25).read()
            if len(data) > 3000:
                return data.decode("utf-8", "replace")
            last = "拦截页 %d 字节" % len(data)
        except Exception as e:
            last = str(e)
        time.sleep(1.5)
    raise RuntimeError(last)


BLOCK = re.compile(r'<tbody\s+id="normalthread_\d+".*?</tbody>', re.S)
T1 = re.compile(r'<a[^>]+class="[^"]*\bxst\b[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
T2 = re.compile(r'<a[^>]+href="([^"]+)"[^>]*class="[^"]*\bxst\b[^"]*"[^>]*>(.*?)</a>', re.S)
TAG = re.compile(r"<[^>]+>")


def clean(s):
    s = TAG.sub("", s)
    for a, b in [("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'")]:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def parse(html, site):
    out = []
    for b in BLOCK.findall(html):
        m = T1.search(b) or T2.search(b)
        if not m:
            continue
        title = clean(m.group(2))
        if not title:
            continue
        link = urljoin(BASE, m.group(1))
        uid = hashlib.md5((site + link).encode()).hexdigest()
        out.append((uid, title, link, site))
    return out


def hit(title):
    if any(x in title for x in EXCLUDE):
        return ""
    for k in KEYWORDS:
        if k in title:
            return k
    return ""


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    try:
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    # 只保留最近 3000 条 uid，避免文件无限膨胀
    keep = list(seen)[-3000:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(keep, f, ensure_ascii=False)


def push_one(title, url, site, kw):
    payload = {
        "spt": WXP_SPT,
        "content": "[%s] %s\n命中词：%s" % (site, title, kw),
        "summary": "[%s] %s" % (site, title[:30]),
        "contentType": 1,
        "url": url,
        "verifyPayType": 0,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(WXP_API, data=data,
                                 headers={"Content-Type": "application/json"})
    rsp = urllib.request.urlopen(req, timeout=15).read()
    j = json.loads(rsp)
    return j.get("code") == 1000, j.get("msg", "")


def notify(new):
    if not new:
        return
    if not WXP_SPT:
        print("[错误] 未配置 WXP_SPT，无法推送。请在仓库 Settings > Secrets 添加 WXP_SPT")
        return
    ok = 0
    for uid, t, u, s, kw in new:
        try:
            good, msg = push_one(t, u, s, kw)
            if good:
                ok += 1
            else:
                print("[WxPusher失败]", msg)
        except Exception as e:
            print("[WxPusher异常]", e)
    print("[WxPusher] 已推送 %d/%d 条" % (ok, len(new)))


def once(first=False):
    seen = load_seen()
    baseline = first and not seen  # 首次、且无历史记录 -> 只建基线不推送
    new = []
    for url in URLS:
        key = url.split("/")[-1].replace("-1.htm", "")
        site = NAMES.get(key, key)
        try:
            rows = parse(fetch(url), site)
        except Exception as e:
            print("[抓取失败]", site, e)
            continue
        for uid, title, link, s in rows:
            if not hit(title):
                continue
            if uid in seen:
                continue
            seen.add(uid)
            if not baseline and len(new) < MAX_PUSH:
                new.append((uid, title, link, s, hit(title)))
    save_seen(seen)
    print("[结果] 命中新增 %d 条%s" % (len(new), "（首轮基线，只记录不推送）" if baseline else ""))
    if new:
        notify(new)


def check():
    print("[令牌] %s" % ("已配置 WXP_SPT" if WXP_SPT else "未配置（推送会失败）"))
    total = 0
    for url in URLS:
        key = url.split("/") [-1].replace("-1.htm", "")
        site = NAMES.get(key, key)
        try:
            rows = parse(fetch(url), site)
            hits = [r for r in rows if hit(r[1])]
            total += len(hits)
            print("[%s] 解析 %d 条，命中 %d" % (site, len(rows), len(hits)))
            for r in hits:
                print("   *", hit(r[1]), "|", r[1][:50])
        except Exception as e:
            print("[%s] 失败 %s" % (site, e))
    print("[合计] 当前页面命中 %d 条" % total)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "check":
        check()
    elif cmd == "once":
        once(first=True)
    elif cmd == "notify-test":
        if not WXP_SPT:
            print("[错误] 未配置 WXP_SPT")
            sys.exit(1)
        ok, msg = push_one("测试", "点击打开卡农论坛首页", "https://www.51kanong.com/forum.php", "测试")
        print("[测试] %s %s" % ("已发送，去 WxPusher 看" if ok else "失败: " + msg))
    else:
        print("用法: python kanong.py check | once | notify-test")


if __name__ == "__main__":
    main()
