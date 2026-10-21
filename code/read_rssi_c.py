import asyncio
import csv
import time

from bleak import BleakScanner

TARGET_NAME = "MayA"
DURATION_S = 6000
OUT_FILE = "rssi_3m.csv"

samples = []
t0 = None


def on_detect(device, adv):
    global t0
    name = (device.name or adv.local_name or "").strip()
    if name.lower() != TARGET_NAME.lower():
        return
    now = time.perf_counter()
    if t0 is None:
        t0 = now
    samples.append((now - t0, adv.rssi))
    print(f"rssi={adv.rssi}")


async def main():
    scanner = BleakScanner(detection_callback=on_detect)
    await scanner.start()
    await asyncio.sleep(DURATION_S)
    await scanner.stop()

    with open(OUT_FILE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "rssi_dbm"])
        w.writerows(samples)


asyncio.run(main())