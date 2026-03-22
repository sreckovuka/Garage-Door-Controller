# =========================================================
# Pico W Gate Controller — MASTER v10
# FIX: Blynk handler registration order
# =========================================================

import network
import machine
import blynklib
import uasyncio as asyncio
import time

# ================= CONFIG =================
SSID = "YoruSSID"
PASSWORD = "YourPassword"
BLYNK_AUTH = "YourBlynkKeyxxxxxxxxxxxxxxxxxxxxx"

RELAY_PIN = 15
REED_PIN  = 14
HEARTBEAT_INTERVAL_MS = 300
RELAY_PULSE_MS = 1000

# ================= PINS ===================
relay = machine.Pin(RELAY_PIN, machine.Pin.OUT)
reed  = machine.Pin(REED_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
led   = machine.Pin("LED", machine.Pin.OUT)

relay.value(0)
led.value(0)

# ================= GLOBALS ================
blynk = None
last_reed_state = reed.value()
relay_busy = False

# ================= WIFI ===================
def wifi_connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print("Connecting to Wi-Fi...")
        wlan.connect(SSID, PASSWORD)
        for _ in range(20):
            if wlan.isconnected():
                break
            time.sleep(0.5)

    if wlan.isconnected():
        print("Wi-Fi connected:", wlan.ifconfig()[0])
        return True
    else:
        print("Wi-Fi failed")
        return False

wifi_connect()

# ================= BLYNK ==================
async def create_blynk():
    global blynk
    while True:
        try:
            blynk = blynklib.Blynk(BLYNK_AUTH, insecure=True)
            print("Blynk connected")
            return
        except Exception as e:
            print("Blynk connect failed:", e)
            await asyncio.sleep(5)   # non-blocking

# ================= RELAY ==================
async def pulse_relay():
    global relay_busy
    if relay_busy:
        return

    relay_busy = True
    relay.value(1)
    blynk.virtual_write(2, 255)
    print("Relay ON")

    try:
        blynk.log_event("gate_opened", "Gate relay pulsed")
    except:
        pass

    await asyncio.sleep_ms(RELAY_PULSE_MS)

    relay.value(0)
    blynk.virtual_write(2, 0)
    print("Relay OFF")

    try:
        blynk.log_event("gate_closed", "Gate relay released")
    except:
        pass

    relay_busy = False

# ================= REED MONITOR ===========
async def reed_monitor():
    global last_reed_state
    while True:
        state = reed.value()

        if state != last_reed_state:
            last_reed_state = state

            if state == 1:
                print("Gate: OPEN")
                value = 1
            else:
                print("Gate: CLOSED")
                value = 0

            try:
                blynk.virtual_write(1, value)
            except:
                pass

        await asyncio.sleep_ms(50)

# ================= HEARTBEAT ==============
async def heartbeat():
    while True:
        led.toggle()
        await asyncio.sleep_ms(HEARTBEAT_INTERVAL_MS)

# ================= BLYNK LOOP =============
async def blynk_loop():
    while True:
        try:
            blynk.run()
        except Exception as e:
            print("Blynk error:", e)
            await create_blynk()
            register_blynk_handlers()
        await asyncio.sleep_ms(20)

# ================= HANDLERS ===============
def register_blynk_handlers():
    @blynk.on("V0")
    def handle_v0(value):
        if int(value[0]) == 1:
            asyncio.create_task(pulse_relay())

# ================= MAIN ===================
async def main():
    await create_blynk()
    register_blynk_handlers()

    asyncio.create_task(blynk_loop())
    asyncio.create_task(heartbeat())
    asyncio.create_task(reed_monitor())

    while True:
        await asyncio.sleep(1)

print("Starting Pico W Gate Controller MASTER v10")
asyncio.run(main())
