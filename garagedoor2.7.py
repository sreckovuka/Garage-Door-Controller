# =========================================================
# Pico W Gate Controller — Blynk Relay Master (v2.7)
# - Reed switch updates only on state change
# - Blynk log events on garage open/close
# =========================================================

__version__ = "v2.7"

import time, network, machine, uasyncio as asyncio, json
import blynklib
import ntptime

# ==== Configuration ====
SSID = "xxx"
PASSWORD = "password"
BLYNK_AUTH = "xxx"
SETTINGS_FILE = "gate_schedule.json"

# ==== Pins ====
relay = machine.Pin(15, machine.Pin.OUT)
reed = machine.Pin(14, machine.Pin.IN, machine.Pin.PULL_UP)
led = machine.Pin("LED", machine.Pin.OUT)  # onboard LED

# ==== Globals / defaults ====
relay_active = False
melbourne_offset_enabled = True
schedule_enabled = True
RELAY_DURATION = 1
blynk = None
blynk_last_seen = time.time()
BLINK_OFFLINE_TIMEOUT = 300  # 5 min
last_reed_state = None  # track previous reed state

# ==== Wi-Fi ====
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

# ==== Load / Save schedule ====
def load_schedule():
    global RELAY_DURATION, schedule_enabled
    try:
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
            open_time = tuple(data.get("open_time", [8, 0]))
            close_time = tuple(data.get("close_time", [18, 0]))
            RELAY_DURATION = int(data.get("relay_duration", RELAY_DURATION))
            melbourne = data.get("melbourne_offset", True)
            schedule_enabled = data.get("schedule_enabled", True)
            return open_time, close_time, melbourne
    except Exception:
        return (8, 0), (18, 0), True

def save_schedule(open_time, close_time, relay_duration, melbourne):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({
                "open_time": list(open_time),
                "close_time": list(close_time),
                "relay_duration": int(relay_duration),
                "melbourne_offset": bool(melbourne),
                "schedule_enabled": schedule_enabled
            }, f)
            f.flush()
        print("Schedule saved")
    except Exception as e:
        print("Error saving schedule:", e)

OPEN_TIME, CLOSE_TIME, melbourne_offset_enabled = load_schedule()

# ==== Gate logic ====
def is_gate_open():
    return reed.value() == 1

async def trigger_gate():
    global relay_active
    if relay_active:
        print("Trigger requested but relay already active.")
        return
    relay.value(1)
    relay_active = True
    led.value(1)
    if blynk:
        try: blynk.virtual_write(13, 1)
        except: pass
    await asyncio.sleep(RELAY_DURATION)
    relay.value(0)
    relay_active = False
    if blynk:
        try: blynk.virtual_write(13, 0)
        except: pass
    print("Gate toggled")

# ==== DST / Melbourne time ====
def melbourne_time():
    tm = time.localtime()
    hour, minute, second = tm[3], tm[4], tm[5]
    mel_hour = (hour + 10) % 24
    if melbourne_offset_enabled:
        mel_hour = (mel_hour + 1) % 24
    return mel_hour, minute, second

# ==== Schedule loop ====
async def schedule_loop():
    while True:
        if not schedule_enabled:
            await asyncio.sleep(1)
            continue

        hour, minute, _ = melbourne_time()
        if (hour, minute) == OPEN_TIME and not is_gate_open():
            print("Scheduled open")
            await trigger_gate()
            await asyncio.sleep(60)
        if (hour, minute) == CLOSE_TIME and is_gate_open():
            print("Scheduled close")
            await trigger_gate()
            await asyncio.sleep(60)
        await asyncio.sleep(1)

# ==== Blynk ====
def create_blynk():
    global blynk
    try:
        obj = blynklib.Blynk(BLYNK_AUTH, insecure=True)
        globals()['blynk'] = obj
        print("Blynk client created.")
    except Exception as e:
        print("Failed to create Blynk client:", e)
        globals()['blynk'] = None

def ensure_blynk_and_register_handlers():
    global blynk
    if not blynk:
        return
    try:
        @blynk.on("V15")
        def v15_write_handler(value):
            asyncio.create_task(trigger_gate())
        print("Blynk handlers registered.")
    except Exception as e:
        print("Failed to register Blynk handlers:", e)

async def blynk_update_loop():
    global blynk, blynk_last_seen, last_reed_state
    while True:
        if not wlan.isconnected() or not blynk:
            await asyncio.sleep(1)
            continue
        try:
            blynk.run()
            blynk_last_seen = time.time()

            # send reed state only if changed
            current_state = is_gate_open()
            if last_reed_state != current_state:
                last_reed_state = current_state
                try:
                    blynk.virtual_write(14, 1 if current_state else 0)
                    blynk.log_event("garage_open" if current_state else "garage_close")
                except: pass

        except Exception as e:
            print("Blynk run error:", e)
            blynk = None  # force full recreate
        await asyncio.sleep_ms(100)

async def blynk_connect_loop():
    global blynk
    while True:
        if wlan.isconnected() and not blynk:
            try:
                create_blynk()
                ensure_blynk_and_register_handlers()
            except: pass
        await asyncio.sleep(5)

async def blynk_watchdog_loop():
    global blynk_last_seen
    while True:
        if time.time() - blynk_last_seen > BLINK_OFFLINE_TIMEOUT:
            print("Blynk offline > timeout, restarting Pico...")
            machine.reset()
        await asyncio.sleep(10)

# ==== NTP resync ====
async def ntp_resync_loop():
    while not wlan.isconnected(): await asyncio.sleep(1)
    try:
        ntptime.settime()
        print("Initial NTP sync done.")
    except Exception as e:
        print("Initial NTP sync failed:", e)
    while True:
        await asyncio.sleep(3600)
        if wlan.isconnected():
            try: ntptime.settime(); print("NTP resync done")
            except: pass

# ==== Wi-Fi reconnect ====
async def wifi_reconnect_loop():
    if not wlan.isconnected():
        try: wlan.connect(SSID, PASSWORD)
        except: pass
    while True:
        if not wlan.isconnected():
            try:
                wlan.connect(SSID, PASSWORD)
                for _ in range(15):
                    if wlan.isconnected(): break
                    await asyncio.sleep(1)
            except: pass
        await asyncio.sleep(5)

# ==== Fast heartbeat LED ====
async def heartbeat_loop():
    while True:
        if relay_active:
            led.value(1)
            await asyncio.sleep(0.1)
        else:
            led.value(1)
            await asyncio.sleep(0.15)
            led.value(0)
            await asyncio.sleep(0.15)

# ==== Main ====
async def main():
    if not wlan.isconnected():
        try: wlan.connect(SSID, PASSWORD)
        except: pass
        for _ in range(15):
            if wlan.isconnected(): break
            await asyncio.sleep(1)

    if wlan.isconnected():
        print(f"Startup Wi-Fi IP address: {wlan.ifconfig()[0]}")
    else:
        print("Wi-Fi not connected at startup!")

    try:
        if wlan.isconnected(): ntptime.settime()
        print("Initial NTP sync OK")
    except: pass

    create_blynk()
    ensure_blynk_and_register_handlers()

    # Start all tasks
    asyncio.create_task(wifi_reconnect_loop())
    asyncio.create_task(blynk_update_loop())
    asyncio.create_task(blynk_connect_loop())
    asyncio.create_task(blynk_watchdog_loop())
    asyncio.create_task(ntp_resync_loop())
    asyncio.create_task(schedule_loop())
    asyncio.create_task(heartbeat_loop())

    while True:
        await asyncio.sleep(10)

# ==== Run ====
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Stopped")

