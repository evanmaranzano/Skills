#!/usr/bin/env python3
# fw_dnat.py — 安恒明御 DAS-Gateway-A1 (10.10.127.254) 目的NAT 全脚本化操作
# 2026-10-21 实测固化：登录/建服务对象/建DNAT/调序/删除 全程无浏览器。
# 凭据走环境变量，绝不落盘：FW_HOST FW_USER FW_PASS
#   export FW_HOST=https://10.10.127.254 FW_USER=admin FW_PASS='...'
#
# 用法:
#   fw_dnat.py login                                  # 只测登录
#   fw_dnat.py list                                   # 列 DNAT 规则(全分页,按匹配顺序)
#   fw_dnat.py services                               # 列自定义服务对象(全分页)
#   fw_dnat.py add-service TCP3001 3001 --desc "xx"   # 建服务对象
#   fw_dnat.py add-dnat 3001 --to 10.10.127.15 --desc "xx"   # 建 DNAT(对象不存在则自动建)
#   fw_dnat.py move-before 28 22                      # 规则28 移到规则22之前
#   fw_dnat.py delete 28                              # 删规则28(对象另行在页面上删)
#   fw_dnat.py watch 28 29                            # 轮询匹配计数
#   fw_dnat.py open-port 33001 --to 10.10.127.15 --desc "molispark-demo 孵化平台"
#       # 一条龙: 冲突检查→建对象→建DNAT→移到兜底前→报命中等待
#
# 依赖: requests pycryptodome pillow + 系统 tesseract 命令
import base64, io, json, os, re, subprocess, sys, time, warnings

warnings.filterwarnings("ignore")
import requests
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA
from PIL import Image

BASE = os.environ.get("FW_HOST", "https://10.10.127.254").rstrip("/")
USER = os.environ.get("FW_USER", "admin")
PW = os.environ.get("FW_PASS")
NP = {"http": None, "https": None}          # 禁走本机代理(VPN 内网地址)
# RSA 公钥来自 /webui/js/rsajs/rsa-security.js(页面公开内容,非秘密)
PUBKEY_B64 = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC3//sR2tXw0wrC2DySx8vNGlqt3Y7ldU9+LBLI6e1KS5lfc5jlTGF7KBTSkCHBM3ouEHWqp1ZJ85iJe59aF5gIB2klBd6h4wrbbHA2XE1sq21ykja/Gqx7/IRia3zQfxGv/qEkyGOx+XALVoOlZqDwh76o2n1vP1D+tD3amHsK7QIDAQAB"

def rsa_encrypt(s):
    key = RSA.import_key(base64.b64decode(PUBKEY_B64))
    return base64.b64encode(PKCS1_v1_5.new(key).encrypt(s.encode())).decode()

def ocr(img_bytes):
    # 实测管线: 灰度→LANCZOS 4x 放大→阈值140 二值→tesseract psm 7/8/6
    img = Image.open(io.BytesIO(img_bytes)).convert("L")
    img = img.resize((img.width * 4, img.height * 4), Image.LANCZOS)
    img = img.point(lambda p: 255 if p > 140 else 0)
    img.save("/tmp/fw_cap.png")
    for psm in (7, 8, 6):
        out = subprocess.run(["tesseract", "/tmp/fw_cap.png", "stdout", "--psm", str(psm)],
                             capture_output=True, text=True).stdout
        code = re.sub(r"[^0-9A-Za-z]", "", out)
        if len(code) == 4:
            return code
    return None

class FW:
    def __init__(self):
        if not PW:
            sys.exit("FATAL: export FW_PASS 后再用")
        self.s = requests.Session()
        self.s.verify = False
        self.s.headers.update({"User-Agent": "Mozilla/5.0",
                               "Referer": BASE + "/webui/?g=net_dnat_show",
                               "X-Requested-With": "XMLHttpRequest"})
        self.login()

    def login(self):
        s = self.s
        s.get(BASE + "/login.html", timeout=10, proxies=NP)
        for i in range(8):
            r = s.get(BASE + "/php/common/checknum_creat.php?module=config_authnum",
                      timeout=10, proxies=NP)
            code = ocr(r.content)
            if not code:
                continue
            r = s.post(BASE + "/login_auth.php",
                       data={"user": USER, "pwd": rsa_encrypt(PW), "vldcode": code,
                             "encrypt": "1"}, timeout=15, proxies=NP)
            if '"code":"1"' in r.text.replace(" ", ""):
                print(f"login ok (captcha attempt {i+1})")
                return True
            time.sleep(1)
        sys.exit("FATAL: login failed after 8 captcha attempts")

    # ---------- 只读 ----------
    def dnat_rules(self):
        """全分页, 返回按列表顺序(=匹配顺序)的规则数组"""
        rows = []
        for p in range(1, 10):
            r = self.s.get(f"{BASE}/webui/?g=net_dnat_jsondata&page={p}&rows=20",
                           timeout=10, proxies=NP)
            g = json.loads(r.text.strip())["group"]
            rows += g
            if len(g) < 20:
                break
        return rows

    def services(self):
        rows = []
        for p in range(1, 20):
            r = self.s.get(f"{BASE}/webui/?g=obj_service_custom_jsondata&page={p}&rows=20",
                           timeout=10, proxies=NP,
                           headers={"Referer": BASE + "/webui/?g=obj_service_custom_show"})
            g = json.loads(r.text.strip()).get("group", [])
            rows += g
            if len(g) < 20:
                break
        return rows

    def fallback_id(self, rules):
        for r in rules:
            if r.get("service") == "any" or "API域名" in r.get("description", ""):
                return int(r["id"])
        return None

    # ---------- 写 ----------
    def add_service(self, name, port, desc=""):
        # ⚠️ 保存走 ?g=obj_service_custom_add (form target=iframe, 不是 addsave URL)
        # ⚠️ 字段错位坑: tcp_src_port_* 的值最终进 destination(显示为"目的端口")
        items = [{"type": "tcp", "source": "0-65535", "destination": f"{port}-{port}"}]
        r = self.s.get(BASE + "/webui/?g=obj_service_custom_add", timeout=10, proxies=NP)
        token = re.findall(r'name="token"\s+value="([^"]+)"', r.text)[0]
        r2 = self.s.post(BASE + "/webui/?g=obj_service_custom_add", data={
            "name": name, "description": desc, "type": "1",
            "tcp_src_port_start": str(port), "src_port_end": str(port),   # end 框 name 是 src_port_end!
            "tcp_dst_port_start": "0", "tcp_dst_port_end": "65535",
            "service_items": json.dumps(items),
            "submit_post": "obj_service_custom_addsave", "token": token,
        }, timeout=15, proxies=NP)
        time.sleep(0.5)
        if self._service_exists(name):
            print(f"service {name} ok (TCP 目的端口:{port}-{port} 源端口:0-65535)")
            return True
        sys.exit(f"FATAL: service {name} not created (resp {len(r2.text)}B)")

    def _service_exists(self, name):
        r = self.s.get(BASE + "/webui/?g=net_dnat_add", timeout=10, proxies=NP)
        return f"<option value='{name}'>" in r.text

    def add_dnat(self, service, port, to_ip, desc, trans_port=None):
        r = self.s.get(BASE + "/webui/?g=net_dnat_add", timeout=10, proxies=NP)
        token = re.findall(r'name="token"\s+value="([^"]+)"', r.text)[0]
        # ⚠️ POST 目标是无 action 的当前页 ?g=net_dnat_add, 带 submit_post 分发
        self.s.post(BASE + "/webui/?g=net_dnat_add", data={
            "enable": "1", "addr_type": "0",
            "src_addr": "any", "dst_addr": "58.22.5.109",
            "service": service, "trans_if": "ge9", "trans_type": "2",
            "trans_dst": to_ip, "trans_port": str(trans_port or port),
            "description": desc,
            "submit_post": "net_dnat_addsave", "token": token,
        }, timeout=15, proxies=NP)
        time.sleep(0.5)
        rules = self.dnat_rules()
        hit = [x for x in rules if x["service"] == service and x["trans_dst"] == to_ip]
        if not hit:
            sys.exit(f"FATAL: DNAT for {service} not found after add")
        rid = int(hit[0]["id"])
        print(f"dnat id={rid} ok ({service} -> {to_ip}:{trans_port or port})")
        return rid

    def move_before(self, rid, dst_id):
        # directval: 1=目标ID之前 0=之后 2=最前 3=最后
        r = self.s.post(BASE + "/webui/?g=net_dnat_show&t=0.9",
                        data={"directval": "1", "id": str(rid), "dst_id": str(dst_id),
                              "submit_post": "net_nat_priority"}, timeout=15, proxies=NP)
        time.sleep(0.5)
        print(f"move id={rid} before id={dst_id} -> {r.status_code}")

    def delete(self, rid):
        rules = self.dnat_rules()
        hit = [x for x in rules if int(x["id"]) == int(rid)]
        if not hit:
            sys.exit(f"FATAL: rule id={rid} not found")
        pro_type = hit[0].get("pro_type", "0")
        self.s.get(f"{BASE}/webui/?g=net_dnat_delete&id={rid}&pro_type={pro_type}",
                   timeout=10, proxies=NP)
        time.sleep(0.5)
        print(f"deleted rule id={rid}")

    def watch(self, ids, seconds=30):
        ids = {str(i) for i in ids}
        end = time.time() + seconds
        while time.time() < end:
            hits = {r["id"]: r["match_count"] for r in self.dnat_rules() if r["id"] in ids}
            print("match_count:", hits, flush=True)
            time.sleep(5)

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit(1)
    cmd = args[0]

    def getopt(flag, default=None):
        return args[args.index(flag) + 1] if flag in args else default

    if cmd == "login":
        FW(); print("ok")
    elif cmd == "list":
        for r in FW().dnat_rules():
            print(f"id={r['id']:>3} {r['dst_addr']}:{r['service']:<12} -> "
                  f"{r['trans_dst']}:{r['trans_port']:<6} enable={r['enable']} "
                  f"hits={r['match_count']} desc={r['description']}")
    elif cmd == "services":
        for r in FW().services():
            print(f"id={r.get('id'):>4} name={r.get('name'):<24} items={r.get('service_items')}")
    elif cmd == "add-service":
        fw = FW(); fw.add_service(args[1], int(args[2]), getopt("--desc", ""))
    elif cmd == "add-dnat":
        fw = FW()
        port = int(args[1])
        svc = getopt("--service", f"TCP{port}")
        if not fw._service_exists(svc):
            fw.add_service(svc, port, getopt("--desc", ""))
        fw.add_dnat(svc, port, getopt("--to", "10.10.127.15"), getopt("--desc", ""),
                    getopt("--trans-port"))
    elif cmd == "move-before":
        FW().move_before(int(args[1]), int(args[2]))
    elif cmd == "delete":
        FW().delete(int(args[1]))
    elif cmd == "watch":
        FW().watch(args[1:], int(getopt("--seconds", "30")))
    elif cmd == "open-port":
        port = int(args[1])
        to_ip = getopt("--to", "10.10.127.15")
        desc = getopt("--desc", f"port-{port}")
        fw = FW()
        rules = fw.dnat_rules()
        clash = [r for r in rules
                 if r["service"] == f"TCP{port}" or r["service"] == str(port)]
        if clash:
            sys.exit(f"FATAL: public {port} already mapped: {clash}")
        fb = fw.fallback_id(rules)
        svc = f"TCP{port}"
        if not fw._service_exists(svc):
            fw.add_service(svc, port, desc)
        rid = fw.add_dnat(svc, port, to_ip, desc)
        if fb:
            fw.move_before(rid, fb)
        # 终验: 列表顺序中新规则必须在兜底前
        order = [int(r["id"]) for r in fw.dnat_rules()]
        if fb and order.index(rid) > order.index(fb):
            sys.exit("FATAL: new rule still after fallback; move manually")
        print(f"DONE: public {port} -> {to_ip}:{port}, rule id={rid}. "
              f"watch it: fw_dnat.py watch {rid}")
    else:
        print(__doc__); sys.exit(1)

if __name__ == "__main__":
    main()
