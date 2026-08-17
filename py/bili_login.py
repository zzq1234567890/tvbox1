"""
哔哩哔哩扫码登录小工具
================================
在电脑上运行本脚本，会自动弹出二维码。
用手机哔哩哔哩 APP 扫码 → 确认登录 → 将 Cookie 保存为 bili_cookie.json。
把这个文件同步到电视盒子，TVBox 爬虫即可加载 Cookie、看高清画质。

依赖：
    pip install qrcode[pil]

文件保存位置（按顺序找第一个可写路径）：
    1. ~/Downloads/bili_cookie.json
    2. ~ (用户家目录)
    3. /storage/emulated/0/Download/bili_cookie.json
    4. /sdcard/Download/bili_cookie.json
    5. 当前目录
"""
import json
import os
import sys
import time
import webbrowser

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")

COOKIE_DIR_CANDIDATES = [
    os.path.join(os.path.expanduser("~"), "Downloads"),
    os.path.expanduser("~"),
    "/storage/emulated/0/Download",   # Android TV 内置存储
    "/sdcard/Download",
    os.getcwd(),
]

QR_GEN_URL  = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"


def find_save_dir():
    """找第一个可写目录"""
    for d in COOKIE_DIR_CANDIDATES:
        try:
            os.makedirs(d, exist_ok=True)
            test = os.path.join(d, ".bili_write_test")
            with open(test, "w") as f:
                f.write("ok")
            os.remove(test)
            return d
        except Exception:
            continue
    return os.getcwd()


def gen_qr(sess):
    resp = sess.get(QR_GEN_URL)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"生成二维码失败: {data}")
    return data["data"]


def poll_qr(sess, qrcode_key):
    resp = sess.get(QR_POLL_URL, params={"qrcode_key": qrcode_key})
    return resp.json()


def show_qr(qr_url):
    """优先在终端打印二维码；没有库就让浏览器打开"""
    try:
        import qrcode
        qr = qrcode.QRCode(border=2, box_size=1)
        qr.add_data(qr_url)
        qr.make(fit=True)
        qr.print_ascii(tty=True)
        return True
    except ImportError:
        pass
    print("  (终端二维码不可用，可执行 `pip install qrcode[pil]` 启用)")
    try:
        webbrowser.open(qr_url)
        return True
    except Exception as e:
        print(f"  浏览器打开失败: {e}")
        print(f"  请手动复制此链接到浏览器：\n  {qr_url}")
        return False


def main():
    print("=" * 60)
    print(" 哔哩哔哩扫码登录工具")
    print("=" * 60)

    save_dir = find_save_dir()
    cookie_path = os.path.join(save_dir, "bili_cookie.json")
    print(f"Cookie 将保存到:\n  {cookie_path}\n")

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    })

    # Step 1: 生成
    print("[1/4] 生成二维码...")
    try:
        qr = gen_qr(sess)
    except Exception as e:
        print(f"  ✗ {e}")
        sys.exit(1)
    qr_url = qr["url"]
    qr_key = qr["qrcode_key"]
    print(f"  qrcode_key = {qr_key}")

    # Step 2: 显示
    print("\n[2/4] 请用哔哩哔哩 APP 扫一扫 ↓")
    show_qr(qr_url)

    # Step 3: 轮询
    print("\n[3/4] 等待手机确认登录（最长 3 分钟）...")
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            data = poll_qr(sess, qr_key)
        except Exception as e:
            print(f"  轮询异常: {e}")
            time.sleep(2)
            continue
        code = data.get("data", {}).get("code", -1)
        # 0=成功  86038=已失效  86090=已扫码待确认  86101=未扫码
        if code == 0:
            print("  ✓ 登录成功！")
            break
        elif code == 86038:
            print("  ✗ 二维码已失效，请重新运行本程序")
            return
        elif code == 86090:
            print("  [已扫码] 请在手机上点击「确认登录」...")
        elif code == 86101:
            print("  [等待扫码] ...")
        else:
            print(f"  [{code}] {data.get('data', {}).get('message')}")
        time.sleep(2)
    else:
        print("  ✗ 登录超时（3 分钟无操作）")
        sys.exit(1)

    # Step 4: 保存
    cookies = sess.cookies.get_dict()
    if not cookies.get("SESSDATA"):
        print("  ✗ 响应里没有 SESSDATA，请重试")
        sys.exit(1)

    payload = {
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "user_id":  cookies.get("DedeUserID", ""),
        "buvid":    cookies.get("buvid3", ""),
        "cookies":  cookies,
    }
    with open(cookie_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n[4/4] Cookie 已保存\n  -> {cookie_path}")
    print(f"  user_id  = {payload['user_id']}")
    print(f"  saved_at = {payload['saved_at']}")
    print(f"  fields   = {', '.join(cookies.keys())}")

    print("\n" + "=" * 60)
    print(" 下一步：把这个文件复制到电视盒子的任意下列路径：")
    for p in ("/storage/emulated/0/Download/bili_cookie.json",
              "/sdcard/Download/bili_cookie.json"):
        print(f"   {p}")
    print(" 然后重启电视端爬虫，init 时会打印「[cookie] loaded ...」即生效。")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(1)
