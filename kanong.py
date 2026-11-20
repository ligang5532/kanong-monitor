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
NAMES = {"yh-282": "羊毛专区", "yh-169": "羊毛交流", "yh-320": "下款线报"}
KEYWORDS = ["人人", "速度", "几毛", "银行", "招商", "工商", "建设", "农业", "交通", "浦发", "中信", "光大", "华夏", "民生", "广发", "兴业", "平安", "邮储", "农商", "信用社"]
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
