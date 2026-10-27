import asyncio
import json
import math
import socket
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import matplotlib.pyplot as plt
from bleak import BleakScanner
from matplotlib.animation import FuncAnimation

PORT = 8000
DISPLAY_PERIOD = 1.0   # giây giữa hai lần in ra terminal
STALE_S = 3.0          # quá thời gian này không có mẫu mới thì hiện "--"

# Kích thước phòng theo sơ đồ: X = 5 m, Y = 3 m (tính nội bộ bằng cm)
ROOM_W_CM = 300        # PC (0,0) -> MayB (5,0), trục X
ROOM_H_CM = 400       # PC (0,0) -> MayA (0,3), trục Y
CELL_CM = 40       # mỗi ô lưới = 1 m

# Bộ lọc trung bình trượt (chạy trước Kalman)
SAMPLING = 9           # số mẫu RSSI gần nhất dùng để lấy trung bình

# Bình phương tối thiểu
# Trọng số độ tin cậy của từng đường (lớn = tin hơn). Đường chưa hiệu chuẩn nên đặt thấp hơn.
WEIGHTS = {"A": 1.0, "B": 1.0, "C": 1.0}
LSQ_MAX_ITER = 30      # số vòng lặp tối đa
LSQ_TOL = 0.01         # dừng khi bước dịch nhỏ hơn giá trị này (cm)

# Tham số riêng cho từng đường đo (nên hiệu chuẩn riêng cho từng đường)
# key = tên thiết bị phát; "realme8" do laptop tự quét bằng bleak
PARAMS = {
    "MayA": {"label": "d_A", "RSSI_1M": -73.35, "N_FACTOR": 1.63},
    "MayB": {"label": "d_B", "RSSI_1M": -78.79, "N_FACTOR": 1.74},
    "realme8": {"label": "d_C", "RSSI_1M": -58, "N_FACTOR": 2.1},  # laptop thu realme8
}

# Tham số bộ lọc Kalman
Q = 0.03   # nhiễu quá trình (nhỏ = mượt hơn, phản ứng chậm hơn)
R = 4.0     # nhiễu đo (lớn = tin RSSI mới ít hơn, mượt hơn)


class MovingAverage:
    """Trung bình của `n` mẫu gần nhất. Khi chưa đủ n mẫu thì lấy trung bình số mẫu đang có."""

    def __init__(self, n):
        self.buf = deque(maxlen=max(1, int(n)))

    def update(self, z):
        self.buf.append(z)
        return sum(self.buf) / len(self.buf)


class Kalman1D:
    def __init__(self, q, r):
        self.q = q
        self.r = r
        self.x = None
        self.p = 1.0

    def update(self, z):
        if self.x is None:
            self.x = z
            return self.x
        self.p += self.q
        k = self.p / (self.p + self.r)
        self.x += k * (z - self.x)
        self.p *= (1 - k)
        return self.x


PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>realme8</title></head>
<body style="font-family:sans-serif;padding:16px">
<h3>realme8: đo RSSI của MayA và MayB</h3>
<button id="b" style="font-size:20px;padding:12px">Bắt đầu đo</button>
<div id="fb" style="display:none;margin-top:12px">
  <button id="bA" style="font-size:18px;padding:10px">Chọn MayA</button>
  <button id="bB" style="font-size:18px;padding:10px">Chọn MayB</button>
</div>
<pre id="o" style="font-size:20px;white-space:pre-wrap">Chưa kết nối</pre>
<pre id="n" style="font-size:13px;color:#a50;white-space:pre-wrap"></pre>
<pre id="d" style="font-size:13px;color:#555;white-space:pre-wrap"></pre>
<script>
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

const dem = {MayA: 0, MayB: 0};
const last = {MayA: null, MayB: null};
const tenDaThay = new Set();

function hienThi() {
  o.textContent = 'MayA: ' + (last.MayA === null ? '--' : last.MayA + ' dBm (' + dem.MayA + ' mẫu)') +
                  '\\nMayB: ' + (last.MayB === null ? '--' : last.MayB + ' dBm (' + dem.MayB + ' mẫu)');
}

function guiRssi(id, rssi) {
  dem[id]++;
  last[id] = rssi;
  hienThi();
  fetch('/rssi', {method: 'POST', body: JSON.stringify({id: id, rssi: rssi})})
    .catch(() => {});
}

function chuanHoa(ten) {
  const t = (ten || '').trim().toLowerCase();
  if (t === 'maya') return 'MayA';
  if (t === 'mayb') return 'MayB';
  return null;
}

async function cachQuet() {
  await navigator.bluetooth.requestLEScan({acceptAllAdvertisements: true});
  navigator.bluetooth.addEventListener('advertisementreceived', e => {
    const ten = e.device.name || e.name || '';
    if (ten) tenDaThay.add(ten);
    const id = chuanHoa(ten);
    if (id) {
      guiRssi(id, e.rssi);
    } else {
      nn.textContent = 'Tên đã thấy: ' + Array.from(tenDaThay).join(', ');
    }
  });
  o.textContent = 'Đang quét tìm MayA và MayB...';
}

async function chonThietBi(id) {
  try {
    const d = await navigator.bluetooth.requestDevice({acceptAllDevices: true});
    d.addEventListener('advertisementreceived', e => guiRssi(id, e.rssi));
    await d.watchAdvertisements();
    nn.textContent = 'Đang lắng nghe ' + id + ' = ' + (d.name || 'thiết bị');
  } catch (err) {
    nn.textContent = 'Lỗi: ' + err;
  }
}

document.getElementById('bA').onclick = () => chonThietBi('MayA');
document.getElementById('bB').onclick = () => chonThietBi('MayB');

document.getElementById('b').onclick = async () => {
  if (!navigator.bluetooth) {
    o.textContent = 'Chưa có Web Bluetooth. Kiểm tra flag insecure origin và mở bằng Chrome.';
    return;
  }
  try {
    if (hasScan) {
      await cachQuet();
    } else if (hasWatch) {
      document.getElementById('fb').style.display = 'block';
      o.textContent = 'Máy không có requestLEScan: bấm lần lượt "Chọn MayA" và "Chọn MayB".';
    } else {
      o.textContent = 'Chrome chưa bật hàm nhận quảng bá.\\n' +
        'Vào chrome://flags/#enable-experimental-web-platform-features, chọn Enabled, Relaunch.';
    }
  } catch (err) {
    o.textContent = 'Lỗi: ' + err;
  }
};
</script></body></html>"""

# ---------------- Trạng thái dùng chung ----------------
t0 = time.time()
lock = threading.Lock()
stop_event = threading.Event()
state = {
    name: {"ma": MovingAverage(SAMPLING), "kf": Kalman1D(Q, R), "d": None, "t": 0.0}
    for name in PARAMS
}
files = {}
for name in PARAMS:
    fh = open(f"rssi_{name}.csv", "w", encoding="utf-8")
    fh.write("time_s,rssi_dbm\n")
    files[name] = fh


def cap_nhat(name, raw_rssi):
    """RSSI thô -> trung bình trượt -> Kalman -> khoảng cách. Gọi từ nhiều luồng nên có khóa."""
    p = PARAMS[name]
    with lock:
        s = state[name]
        avg = s["ma"].update(raw_rssi)
        rssi = s["kf"].update(avg)
        s["d"] = 10 ** ((p["RSSI_1M"] - rssi) / (10 * p["N_FACTOR"]))
        s["t"] = time.time()
        files[name].write(f"{time.time() - t0:.3f},{raw_rssi}\n")
        files[name].flush()


# ---------------- Tính vị trí ----------------
def lay_khoang_cach_cm():
    """Trả về (dA, dB, dC) theo cm, hoặc None nếu có đường nào mất tín hiệu."""
    now = time.time()
    with lock:
        out = []
        for name in ("MayA", "MayB", "realme8"):
            s = state[name]
            if s["d"] is None or now - s["t"] > STALE_S:
                return None
            out.append(s["d"] * 100.0)
    return tuple(out)


def giai_binh_phuong_toi_thieu(dA, dB, dC):
    """
    Tìm (x, y) làm nhỏ nhất  sum( w_i * (|P - mốc_i| - d_i)^2 )  với 3 mốc:
      MayA (0, H), MayB (W, 0), PC (0, 0).
    Dùng Gauss-Newton có giảm chấn Levenberg-Marquardt, điểm xuất phát là nghiệm công thức đóng.
    """
    W, H = float(ROOM_W_CM), float(ROOM_H_CM)
    anchors = [
        (0.0, H, dA, WEIGHTS["A"]),
        (W, 0.0, dB, WEIGHTS["B"]),
        (0.0, 0.0, dC, WEIGHTS["C"]),
    ]

    def cost(px, py):
        total = 0.0
        for ax, ay, d, w in anchors:
            r = math.hypot(px - ax, py - ay) - d
            total += w * r * r
        return total

    # Điểm xuất phát: nghiệm công thức đóng cũ
    x = (W ** 2 + dC ** 2 - dB ** 2) / (2.0 * W)
    y = (H ** 2 + dC ** 2 - dA ** 2) / (2.0 * H)

    lam = 1e-3
    for _ in range(LSQ_MAX_ITER):
        a11 = a12 = a22 = g1 = g2 = 0.0
        for ax, ay, d, w in anchors:
            dx, dy = x - ax, y - ay
            rho = max(math.hypot(dx, dy), 1e-6)
            r = rho - d
            jx, jy = dx / rho, dy / rho
            a11 += w * jx * jx
            a12 += w * jx * jy
            a22 += w * jy * jy
            g1 += w * jx * r
            g2 += w * jy * r

        a11d = a11 * (1.0 + lam)
        a22d = a22 * (1.0 + lam)
        det = a11d * a22d - a12 * a12
        if abs(det) < 1e-12:
            break
        sx = -(a22d * g1 - a12 * g2) / det
        sy = -(-a12 * g1 + a11d * g2) / det

        if cost(x + sx, y + sy) < cost(x, y):
            x += sx
            y += sy
            lam = max(lam / 10.0, 1e-9)
            if math.hypot(sx, sy) < LSQ_TOL:
                break
        else:
            lam *= 10.0
            if lam > 1e8:
                break
    return x, y


def tinh_vi_tri():
    """
    Định vị bằng bình phương tối thiểu có trọng số từ cả 3 khoảng cách (cm).
    PC (0,0), MayB (W,0) trên trục X, MayA (0,H) trên trục Y.
    Trả về (x, y, dA, dB, dC) theo cm hoặc None.
    """
    d = lay_khoang_cach_cm()
    if d is None:
        return None
    dA, dB, dC = d
    x, y = giai_binh_phuong_toi_thieu(dA, dB, dC)
    return x, y, dA, dB, dC


# ---------------- HTTP server (nhận dữ liệu từ realme8) ----------------
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            msg = json.loads(self.rfile.read(n))
            name = msg["id"]
            if name not in ("MayA", "MayB"):
                raise ValueError(f"id lạ: {name}")
            cap_nhat(name, msg["rssi"])
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


def chay_http():
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


# ---------------- bleak (laptop quét realme8), chạy ở luồng riêng ----------------
def on_detect(device, adv):
    name = (device.name or adv.local_name or "").strip()
    if name.lower() != "realme8":
        return
    cap_nhat("realme8", adv.rssi)


def dinh_dang(name):
    p = PARAMS[name]
    s = state[name]
    if s["d"] is None or time.time() - s["t"] > STALE_S:
        return f"{p['label']}=--"
    return f"{p['label']}={s['d']:.2f}"


async def ble_main():
    scanner = BleakScanner(detection_callback=on_detect)
    await scanner.start()
    try:
        while not stop_event.is_set():
            await asyncio.sleep(DISPLAY_PERIOD)
            with lock:
                dong = {name: dinh_dang(name) for name in PARAMS}
            print(dong["MayA"])
            print(dong["MayB"])
            print(dong["realme8"])
            pos = tinh_vi_tri()
            if pos is None:
                print("x=--, y=--")
            else:
                print(f"x={pos[0]/100:.2f} m, y={pos[1]/100:.2f} m")
            print()
    finally:
        await scanner.stop()


def chay_ble():
    asyncio.run(ble_main())


# ---------------- Vẽ đồ thị ----------------
def ve_do_thi():
    # Đổi cm sang m để hiển thị trực tiếp tọa độ theo mét.
    W = ROOM_W_CM / 100.0
    H = ROOM_H_CM / 100.0
    L = CELL_CM / 100.0

    fig, ax = plt.subplots(figsize=(9, 6.5))
    fig.canvas.manager.set_window_title("Vị trí realme8")
    ax.set_aspect("equal")
    ax.set_xticks([i * L for i in range(int(W / L) + 1)])
    ax.set_yticks([i * L for i in range(int(H / L) + 1)])
    ax.grid(True, color="#cccccc", linewidth=0.8)
    ax.set_xlabel("X (m) → về phía MayB")
    ax.set_ylabel("Y (m) → về phía MayA")
    ax.set_title("Định vị realme8 bằng RSSI (bình phương tối thiểu)")

    # Các mốc cố định: PC là gốc tọa độ.
    ax.plot(0, 0, "o", color="red", markersize=10, markerfacecolor="none", markeredgewidth=2)
    ax.plot(0, H, "o", color="red", markersize=10, markerfacecolor="none", markeredgewidth=2)
    ax.plot(W, 0, "o", color="red", markersize=10, markerfacecolor="none", markeredgewidth=2)
    ax.annotate("PC (0, 0)", (0, 0), textcoords="offset points", xytext=(8, -18), color="red")
    ax.annotate("MayA ", (0, H), textcoords="offset points", xytext=(8, 8), color="red")
    ax.annotate("MayB ", (W, 0), textcoords="offset points", xytext=(-38, 8), color="red")

    phone, = ax.plot([], [], "p", color="green", markersize=16, markeredgecolor="darkgreen")
    line_x, = ax.plot([], [], "--", color="purple", linewidth=1.2)
    line_y, = ax.plot([], [], "--", color="purple", linewidth=1.2)
    txt = ax.text(0.02, 0.97, "x=-- m, y=-- m", transform=ax.transAxes,
                  va="top", fontsize=14, fontweight="bold",
                  bbox=dict(boxstyle="round", facecolor="white", edgecolor="green"))

    def cap_nhat_hinh(_frame):
        pos = tinh_vi_tri()  # tọa độ trả về tính bằng cm
        if pos is None:
            phone.set_data([], [])
            line_x.set_data([], [])
            line_y.set_data([], [])
            txt.set_text("x=-- m, y=-- m (đang chờ RSSI)")
        else:
            x_cm, y_cm, dA, dB, dC = pos
            x, y = x_cm / 100.0, y_cm / 100.0
            phone.set_data([x], [y])
            line_x.set_data([x, x], [0, y])
            line_y.set_data([0, x], [y, y])
            txt.set_text(f"x={x:.2f} m, y={y:.2f} m")

            # Tự mở rộng trục nếu điện thoại vượt vùng ban đầu.
            ax.set_xlim(min(-0.5, x - 0.5), max(W + 0.5, x + 0.5))
            ax.set_ylim(min(-0.5, y - 0.5), max(H + 0.5, y + 0.5))
        return phone, line_x, line_y, txt

    anim = FuncAnimation(fig, cap_nhat_hinh, interval=200, blit=False,
                         cache_frame_data=False)
    fig._anim = anim
    plt.show()


if __name__ == "__main__":
    threading.Thread(target=chay_http, daemon=True).start()
    ble_thread = threading.Thread(target=chay_ble, daemon=True)
    ble_thread.start()

    ip = get_ip()
    print(f"Địa chỉ nhập vào flag Chrome VÀ để mở trang trên realme8: http://{ip}:{PORT}")
    print(f"Khu vực {ROOM_W_CM/100:.1f}x{ROOM_H_CM/100:.1f} m, mỗi ô l={CELL_CM/100:.1f} m. "
          f"Bộ lọc: trung bình trượt {SAMPLING} mẫu -> Kalman. "
          f"Định vị: bình phương tối thiểu, trọng số A/B/C = "
          f"{WEIGHTS['A']}/{WEIGHTS['B']}/{WEIGHTS['C']}.")
    print("Đóng cửa sổ đồ thị hoặc nhấn Ctrl+C để dừng.\n")

    try:
        ve_do_thi()           # chạy ở luồng chính cho tới khi đóng cửa sổ
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        ble_thread.join(timeout=3)
        for fh in files.values():
            fh.close()