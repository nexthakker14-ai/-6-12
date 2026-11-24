
# -*- coding: utf-8 -*-
import os, time, json, logging
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_IDS = [x.strip() for x in os.getenv("TELEGRAM_CHAT_ID", "").split(",") if x.strip()]
SYMBOLS = list(dict.fromkeys((s.strip().upper().replace("USDT", "") + "_USDT") for s in os.getenv("SYMBOLS", "BTCUSDT").split(",") if s.strip()))
POLL = max(1, int(os.getenv("POLL_SECONDS", "3")))
TEST = os.getenv("TEST_MODE", "false").lower() in ("1", "true", "yes", "on")
API = os.getenv("MEXC_KLINE_URL", "https://contract.mexc.com/api/v1/contract/kline")
TIMEFRAMES = {300: "5 хвилин", 600: "10 хвилин"}
CHECK_N = 6
STATE_DIR = Path(os.getenv("STATE_DIR", ".")); STATE_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("mexc-mtf-pattern-bot")
http = requests.Session()
http.headers.update({"User-Agent": "Mozilla/5.0 MEXC-MTF-Pattern-Bot/3.0"})

RULES = {
    "P2": (1, 2, 3, 6),
    "P3": (1, 2, 3, 4, 6),
    "P4": (1, 2, 3, 4, 5, 6),
    "P5": (1, 2, 3, 4, 5, 6)
}

def candle_color(c):
    if c["close"] > c["open"]:
        return "GREEN"
    if c["close"] < c["open"]:
        return "RED"
    return "DOJI"


def send(msg):
    if TEST:
        log.info("TEST MESSAGE:\n%s", msg)
        return True

    if not TOKEN or not CHAT_IDS:
        log.error("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return False

    ok = True
    for chat in CHAT_IDS:
        try:
            r = http.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": chat, "text": msg},
                timeout=15
            )
            data = r.json()
            if not r.ok or not data.get("ok"):
                ok = False
                log.error("Telegram error %s %s", r.status_code, r.text[:300])
        except Exception:
            ok = False
            log.exception("Telegram send failed")
    return ok


def fetch(symbol, tf_seconds):
    now = int(time.time())
    source_interval = "Min5"

    r = http.get(
        f"{API.rstrip('/')}/{symbol}",
        params={"interval": source_interval, "limit": 600, "end": now},
        timeout=20
    )
    r.raise_for_status()
    payload = r.json()

    if not payload.get("success"):
        raise RuntimeError(f"MEXC API error: {payload}")

    d = payload.get("data") or {}
    if not isinstance(d, dict) or any(k not in d for k in ("time", "open", "close")):
        raise RuntimeError(f"Unexpected MEXC response: {str(d)[:300]}")

    n = min(len(d["time"]), len(d["open"]), len(d["close"]))
    raw = []

    for i in range(n):
        raw.append({
            "ts": int(d["time"][i]),
            "open": float(d["open"][i]),
            "close": float(d["close"][i])
        })

    raw.sort(key=lambda x: x["ts"])

    if tf_seconds == 300:
        closed = [c for c in raw if c["ts"] + 300 <= now]
        live = next(
            (c for c in reversed(raw) if c["ts"] <= now < c["ts"] + 300),
            None
        )
        return closed, live

    if tf_seconds != 600:
        raise ValueError(f"Unsupported timeframe: {tf_seconds}")

    buckets = {}
    for c in raw:
        bucket_ts = (c["ts"] // 600) * 600
        buckets.setdefault(bucket_ts, []).append(c)

    closed, live = [], None

    for bucket_ts in sorted(buckets):
        parts = sorted(buckets[bucket_ts], key=lambda x: x["ts"])

        first = next((x for x in parts if x["ts"] == bucket_ts), None)
        second = next((x for x in parts if x["ts"] == bucket_ts + 300), None)

        if first and second and bucket_ts + 600 <= now:
            closed.append({
                "ts": bucket_ts,
                "open": first["open"],
                "close": second["close"]
            })

        elif bucket_ts <= now < bucket_ts + 600 and first:
            latest = second if second and second["ts"] <= now else first
            live = {
                "ts": bucket_ts,
                "open": first["open"],
                "close": latest["close"]
            }

    return closed, live


def read_state(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"last_ts": None, "seen": [], "pending": [], "pre": []}
    except Exception:
        log.exception("Bad state file %s; starting clean", path)
        return {"last_ts": None, "seen": [], "pending": [], "pre": []}


def write_state(state, path):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    os.replace(tmp, path)


class Engine:

    def __init__(self, symbol, tf_seconds):
        self.symbol = symbol
        self.tf = tf_seconds
        self.tf_label = TIMEFRAMES[tf_seconds]
        self.path = STATE_DIR / f"state_{symbol}_{tf_seconds}.json"
        self.state = read_state(self.path)

        for k, v in (
            ("seen", []),
            ("pending", []),
            ("pre", []),
            ("last_ts", None)
        ):
            self.state.setdefault(k, v)

        self.candles = {}

    def add_history(self, closed):
        for c in closed:
            self.candles[c["ts"]] = c

        for ts in sorted(self.candles)[:-350]:
            self.candles.pop(ts, None)

    def seq(self, start, n=6):
        return [
            self.candles.get(start + i * self.tf)
            for i in range(n)
        ]

    def matched(self, seq, base):
        if not all(seq):
            return []

        cols = [candle_color(c) for c in seq]

        if any(x not in ("GREEN", "RED") for x in cols):
            return []

        out = [
            r for r, pos in RULES.items()
            if all(cols[p - 1] == base for p in pos)
        ]

        if "P4" in out and "P5" in out:
            out = [
                r for r in out if r not in ("P4", "P5")
            ] + ["P4/P5"]

        return out

    def msg(self, kind, rule, direction, result=None):
        icon = "🟢" if direction == "LONG" else "🔴"

        lines = [
            kind,
            "",
            f"{self.symbol.replace('_', '')} | MEXC Futures",
            "",
            f"Таймфрейм: {self.tf_label}",
            f"Правило: {rule}",
            f"Напрямок: {icon} {direction}"
        ]

        if result:
            lines.extend(["", result])

        return "\n".join(lines)

    # PRE для чинних P1-P5: за 2 хвилини до закриття 7-ї свічки.
    # PRE для EIGHT: за 2 хвилини до закриття 8-ї свічки,
    # якщо попередні 7 закритих і поточна незакрита свічки одного кольору.
    def pre_alert(self, live):
        if not live:
            return

        remain = self.tf - (int(time.time()) - live["ts"])
        if not (0 < remain <= 120):
            return

        # FIVE: 4 closed candles and live fifth candle are the same required colour.
        start5 = live["ts"] - 4 * self.tf
        first4 = self.seq(start5, 4)
        if all(first4):
            cols4 = [candle_color(c) for c in first4]
            live_color = candle_color(live)
            if (cols4[0] in ("RED", "GREEN")
                    and all(color == cols4[0] for color in cols4)
                    and live_color == cols4[0]):
                base = cols4[0]
                key = f"{start5}:{base}:FIVE"
                if key not in self.state["pre"]:
                    direction = "LONG" if base == "RED" else "SHORT"
                    text = self.msg(
                        "⚠️ ПОПЕРЕДЖЕННЯ PRE", "FIVE", direction,
                        "4 попередні свічки та live 5-та одного кольору. Сигнал після закриття 5-ї."
                    )
                    if send(text):
                        self.state["pre"].append(key)
                        self.state["pre"] = self.state["pre"][-1500:]
                        write_state(self.state, self.path)
                        log.info("PRE %s %s FIVE %s", self.symbol, self.tf_label, direction)

        # Старі правила P2-P5 (перші 6 свічок + поточна 7-ма).
        start = live["ts"] - 6 * self.tf
        first6 = self.seq(start, 6)

        if all(first6):
            cols = [candle_color(c) for c in first6]
            if all(x in ("GREEN", "RED") for x in cols):
                base = cols[0]
                rules = self.matched(first6, base)
                if rules:
                    rule = ", ".join(rules)
                    key = f"{start}:{base}:{rule}"
                    if key not in self.state["pre"]:
                        direction = "SHORT" if base == "GREEN" else "LONG"
                        text = self.msg(
                            "⚠️ ПОПЕРЕДЖЕННЯ PRE",
                            rule,
                            direction,
                            "Очікується закриття 7-ї свічки. Сигнал буде лише якщо її колір збігається з 6-ю."
                        )
                        if send(text):
                            self.state["pre"].append(key)
                            self.state["pre"] = self.state["pre"][-1500:]
                            write_state(self.state, self.path)
                            log.info("PRE %s %s %s %s", self.symbol, self.tf_label, rule, direction)

        # Нове правило EIGHT: 7 попередніх свічок одного кольору,
        # а поточна (8-ма) вже має бути цього самого кольору.
        start8 = live["ts"] - 7 * self.tf
        first7 = self.seq(start8, 7)
        if not all(first7):
            return

        cols7 = [candle_color(c) for c in first7]
        live_color = candle_color(live)
        if (cols7[0] not in ("GREEN", "RED")
                or any(color != cols7[0] for color in cols7)
                or live_color != cols7[0]):
            return

        base = cols7[0]
        rule = "EIGHT"
        key = f"{start8}:{base}:{rule}"
        if key in self.state["pre"]:
            return

        direction = "SHORT" if base == "GREEN" else "LONG"
        text = self.msg(
            "⚠️ ПОПЕРЕДЖЕННЯ PRE",
            rule,
            direction,
            "Попередні 7 свічок і поточна 8-ма мають однаковий колір. Очікується закриття 8-ї свічки."
        )
        if send(text):
            self.state["pre"].append(key)
            self.state["pre"] = self.state["pre"][-1500:]
            write_state(self.state, self.path)
            log.info("PRE %s %s %s %s", self.symbol, self.tf_label, rule, direction)

    # ПЕРЕВІРКА РЕЗУЛЬТАТУ НА НАСТУПНИХ 6 СВІЧКАХ
    def process_closed(self, c):
        ts = c["ts"]
        current = candle_color(c)
        still = []

        for p in self.state["pending"]:
            if ts <= p["signal_ts"]:
                still.append(p)
                continue

            idx = (ts - p["signal_ts"]) // self.tf

            if p.get("rule") == "FIVE":
                checkpoints = (6, 7, 8, 9, 13)
                if idx not in checkpoints:
                    still.append(p)
                    continue
                wanted = "GREEN" if p["direction"] == "LONG" else "RED"
                checkpoint_pos = checkpoints.index(idx) + 1
                if current == wanted:
                    send(self.msg(
                        f"✅ РЕЗУЛЬТАТ: WIN на свічці #{idx} ({checkpoint_pos}/5)",
                        p["rule"], p["direction"]
                    ))
                    log.info("WIN %s %s FIVE %s candle #%d (%d/5)",
                             self.symbol, self.tf_label, p["direction"], idx, checkpoint_pos)
                elif idx == 13:
                    send(self.msg(
                        "❌ РЕЗУЛЬТАТ: LOSS на свічці #13 (5/5)",
                        p["rule"], p["direction"]
                    ))
                    log.info("LOSS %s %s FIVE %s at #13",
                             self.symbol, self.tf_label, p["direction"])
                else:
                    p["progress"] = checkpoint_pos
                    still.append(p)
                continue

            if not 1 <= idx <= CHECK_N:
                continue

            wanted = "GREEN" if p["direction"] == "LONG" else "RED"
            if current == wanted:
                send(self.msg(
                    f"✅ РЕЗУЛЬТАТ: WIN {idx}/6", p["rule"], p["direction"]
                ))
                log.info("WIN %s %s %s %s %d/6",
                         self.symbol, self.tf_label, p["rule"], p["direction"], idx)
            elif idx == CHECK_N:
                send(self.msg(
                    "❌ РЕЗУЛЬТАТ: LOSS 6/6", p["rule"], p["direction"]
                ))
                log.info("LOSS %s %s %s %s 6/6",
                         self.symbol, self.tf_label, p["rule"], p["direction"])
            else:
                p["progress"] = idx
                still.append(p)

        self.state["pending"] = still

        # FIVE signal: 5 consecutive RED = LONG; 5 consecutive GREEN = SHORT.
        start5 = ts - 4 * self.tf
        first4 = self.seq(start5, 4)
        if all(first4):
            cols4 = [candle_color(x) for x in first4]
            if (cols4[0] in ("RED", "GREEN")
                    and all(color == cols4[0] for color in cols4)
                    and current == cols4[0]):
                base = cols4[0]
                rule = "FIVE"
                key = f"{start5}:{base}:{rule}"
                if key not in self.state["seen"]:
                    direction = "LONG" if base == "RED" else "SHORT"
                    if send(self.msg("🔔 ПІДТВЕРДЖЕНИЙ СИГНАЛ", rule, direction)):
                        self.state["seen"].append(key)
                        self.state["seen"] = self.state["seen"][-3000:]
                        self.state["pending"].append({
                            "rule": rule, "direction": direction,
                            "start_ts": start5, "signal_ts": ts, "progress": 0
                        })
                        log.info("SIGNAL %s %s FIVE %s", self.symbol, self.tf_label, direction)

        # Старі правила P2-P5: оброблювана свічка є сьомою.
        start7 = ts - 6 * self.tf
        first6 = self.seq(start7, 6)

        if all(first6):
            cols = [candle_color(x) for x in first6]
            if all(x in ("GREEN", "RED") for x in cols):
                # Сьома свічка має бути того самого кольору, що й шоста.
                if current in ("GREEN", "RED") and current == cols[5]:
                    base = cols[0]
                    rules = self.matched(first6, base)
                    if rules:
                        rule = ", ".join(rules)
                        key = f"{start7}:{base}:{rule}"
                        if key not in self.state["seen"]:
                            direction = "SHORT" if base == "GREEN" else "LONG"
                            if send(self.msg("🔔 ПІДТВЕРДЖЕНИЙ СИГНАЛ", rule, direction)):
                                self.state["seen"].append(key)
                                self.state["seen"] = self.state["seen"][-3000:]
                                self.state["pending"].append({
                                    "rule": rule,
                                    "direction": direction,
                                    "start_ts": start7,
                                    "signal_ts": ts,
                                    "progress": 0
                                })
                                log.info("SIGNAL %s %s %s %s", self.symbol, self.tf_label, rule, direction)

        # НОВЕ ПРАВИЛО EIGHT: рівноцінна умова — 8 поспіль зелених або 8 поспіль червоних.
        # Сигнал надсилається після закриття восьмої свічки.
        start8 = ts - 7 * self.tf
        first7 = self.seq(start8, 7)
        if all(first7):
            cols7 = [candle_color(x) for x in first7]
            if (cols7[0] in ("GREEN", "RED")
                    and all(color == cols7[0] for color in cols7)
                    and current == cols7[0]):
                base = cols7[0]
                rule = "EIGHT"
                key = f"{start8}:{base}:{rule}"
                if key not in self.state["seen"]:
                    direction = "SHORT" if base == "GREEN" else "LONG"
                    if send(self.msg("🔔 ПІДТВЕРДЖЕНИЙ СИГНАЛ", rule, direction)):
                        self.state["seen"].append(key)
                        self.state["seen"] = self.state["seen"][-3000:]
                        self.state["pending"].append({
                            "rule": rule,
                            "direction": direction,
                            "start_ts": start8,
                            "signal_ts": ts,
                            "progress": 0
                        })
                        log.info("SIGNAL %s %s EIGHT %s", self.symbol, self.tf_label, direction)

    def cycle(self, closed, live):
        if not self.candles:
            self.add_history(closed)

            if self.state["last_ts"] is None:
                self.state["last_ts"] = (
                    closed[-1]["ts"] if closed else None
                )
                write_state(self.state, self.path)

                log.info(
                    "Initialized %s %s; waiting for new candles",
                    self.symbol, self.tf_label
                )

                self.pre_alert(live)
                return
        else:
            self.add_history(closed)

        self.pre_alert(live)

        last = int(self.state["last_ts"] or 0)
        fresh = [x for x in closed if x["ts"] > last]

        for c in fresh:
            self.process_closed(c)
            self.state["last_ts"] = c["ts"]
            write_state(self.state, self.path)


def main():
    if not SYMBOLS:
        raise RuntimeError("No symbols configured")

    engines = {
        (s, tf): Engine(s, tf)
        for s in SYMBOLS
        for tf in TIMEFRAMES
    }

    log.info(
        "MEXC multi-timeframe bot started: %s | 5m + 10m | poll=%ss",
        SYMBOLS, POLL
    )

    if not TEST:
        send(
            "🤖 БОТ ЗАПУЩЕНО\n"
            "MEXC Futures | 5 хв + 10 хв\n"
            "P2–P5 + FIVE + EIGHT | PRE / SIGNAL / WIN-LOSS"
        )

    while True:
        for (sym, tf), eng in engines.items():
            try:
                closed, live = fetch(sym, tf)
                eng.cycle(closed, live)
            except Exception:
                log.exception(
                    "Cycle failed for %s %s",
                    sym, eng.tf_label
                )

        time.sleep(POLL)


if __name__ == "__main__":
    if TEST:
        print("TEST MODE: UTF-8 source OK")
        print("Symbols:", ", ".join(SYMBOLS))
        print("Timeframes: 5 minutes and 10 minutes")
        print("Rules:", ", ".join(RULES), "and EIGHT (8 consecutive same-colour candles)")
        print("PRE: 2 minutes before candle #5 close for FIVE; up to 120 seconds before candle #7 close for P2-P5; before #8 close for EIGHT")
        print("Signal: FIVE after #5 closes; P2-P5 after #7 closes; EIGHT after #8 closes with 8 consecutive same-colour candles")
        print("Outcome: next six closed candles; WIN on first target colour, else LOSS 6/6")
    else:
        main()
