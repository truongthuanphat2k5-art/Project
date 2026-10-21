import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TARGET = "MayB"        # <-- đổi tên thiết bị cần đo ở đây (MayA, MayB, ...)
PORT = 8000
RECORD_S = 60
OUT_FILE = "rssi_mayb_5m.csv"

PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>realme8</title></head>
<body style="font-family:sans-serif;padding:16px">
<h3>realme8: đo RSSI của __TARGET__</h3>
<button id="b" style="font-size:20px;padding:12px">Bắt đầu đo</button>
<button id="bA" style="display:none;font-size:18px;padding:10px;margin-top:12px">Chọn __TARGET__</button>
<pre id="o" style="font-size:20px;white-space:pre-wrap">Chưa kết nối</pre>
<pre id="n" style="font-size:13px;color:#a50;white-space:pre-wrap"></pre>
<pre id="d" style="font-size:13px;color:#555;white-space:pre-wrap"></pre>
<script>
const TEN = '__TARGET__';
const o = document.getElementById('o');
const nn = document.getElementById('n');
const dbg = document.getElementById('d');
const hasScan = !!(navigator.bluetooth && navigator.bluetooth.requestLEScan);
const hasWatch = !!(window.BluetoothDevice && BluetoothDevice.prototype.watchAdvertisements);

dbg.textContent = 'Địa chỉ trang: ' + location.origin +
  '\\nisSecureContext: ' + window.isSecureContext +
  '\\nnavigator.bluetooth: ' + (navigator.bluetooth ? 'có' : 'KHÔNG CÓ') +
  '\\nrequestLEScan: ' + (hasScan ? 'có' : 'không') +
  '\\nwatchAdvertisements: ' + (hasWatch ? 'có' : 'không');

let dem = 0;
const tenDaThay = new Set();

function guiRssi(rssi) {
  dem++;
  o.textContent = TEN + ': RSSI = ' + rssi + ' dBm   (mẫu thứ ' + dem + ')';
  fetch('/rssi', {method: 'POST', body: JSON.stringify({rssi: rssi})})
    .catch(() => {});
}

async function cachQuet() {
  await navigator.bluetooth.requestLEScan({acceptAllAdvertisements: true});
  navigator.bluetooth.addEventListener('advertisementreceived', e => {
    const ten = (e.device.name || e.name || '').trim();
    if (ten) tenDaThay.add(ten);
    if (ten.toLowerCase() === TEN.toLowerCase()) {
      guiRssi(e.rssi);
    } else {
      nn.textContent = 'Chưa thấy "' + TEN + '". Tên đã thấy: ' + Array.from(tenDaThay).join(', ');
    }
  });
  o.textContent = 'Đang quét tìm ' + TEN + '...';
}

async function chonThietBi() {
  try {
    const d = await navigator.bluetooth.requestDevice({acceptAllDevices: true});
    d.addEventListener('advertisementreceived', e => guiRssi(e.rssi));
    await d.watchAdvertisements();
    nn.textContent = 'Đang lắng nghe ' + (d.name || 'thiết bị');
  } catch (err) {
    nn.textContent = 'Lỗi: ' + err;
  }
}

document.getElementById('bA').onclick = chonThietBi;

document.getElementById('b').onclick = async () => {
  if (!navigator.bluetooth) {
    o.textContent = 'Chưa có Web Bluetooth. Kiểm tra flag insecure origin và mở bằng Chrome.';
    return;
  }
  try {
    if (hasScan) {
      await cachQuet();
    } else if (hasWatch) {
      document.getElementById('bA').style.display = 'inline-block';
      o.textContent = 'Máy không có requestLEScan: bấm "Chọn ' + TEN + '".';
    } else {
      o.textContent = 'Chrome chưa bật hàm nhận quảng bá.\\n' +
        'Vào chrome://flags/#enable-experimental-web-platform-features, chọn Enabled, Relaunch.';
    }
  } catch (err) {
    o.textContent = 'Lỗi: ' + err;
  }
};
</script></body></html>"""

PAGE = PAGE.replace("__TARGET__", TARGET)

lock = threading.Lock()
samples = []          # [(time_s, rssi), ...]
last_rssi = None
t0 = None             # thời điểm nhận mẫu đầu tiên (bắt đầu timer)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        global last_rssi, t0
        n = int(self.headers.get("Content-Length", 0))
        try:
            rssi = int(json.loads(self.rfile.read(n))["rssi"])
            now = time.time()
            with lock:
                if t0 is None:
                    t0 = now
                    print(f">>> NHẬN MẪU ĐẦU TIÊN, BẮT ĐẦU THU {RECORD_S} GIÂY <<<")
                if now - t0 <= RECORD_S:
                    samples.append((now - t0, rssi))
                last_rssi = rssi
        except Exception as e:
            print("Lỗi dữ liệu:", e)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def save_csv():
    with lock:
        data = list(samples)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("time_s,rssi_dbm\n")
        for t, r in data:
            f.write(f"{t:.3f},{r}\n")
    print(f"\nĐã ghi {OUT_FILE}: {len(data)} mẫu")


if __name__ == "__main__":
    ip = get_ip()
    print(f"Địa chỉ nhập vào flag Chrome VÀ để mở trang trên realme8: http://{ip}:{PORT}")
    print(f"Đo RSSI của {TARGET}. Timer {RECORD_S}s tự bắt đầu khi nhận mẫu đầu tiên. Ctrl+C để dừng.\n")

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        while True:
            time.sleep(1)
            with lock:
                started = t0 is not None
                elapsed = time.time() - t0 if started else 0
                r = last_rssi
            print(f"rssi={r if r is not None else '--'}")
            if started and elapsed >= RECORD_S:
                break
    except KeyboardInterrupt:
        pass
    finally:
        if t0 is not None:
            save_csv()
        server.shutdown()