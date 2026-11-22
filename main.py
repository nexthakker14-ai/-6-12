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
SYMBOLS = list(dict.fromkeys((s.strip().upper().replace("USDT","") + "_USDT") for s in os.getenv("SYMBOLS","BTCUSDT,ETHUSDT").split(",") if s.strip()))
POLL = max(1, int(os.getenv("POLL_SECONDS","3")))
TEST = os.getenv("TEST_MODE","false").lower() in ("1","true","yes","on")
API = os.getenv("MEXC_KLINE_URL","https://contract.mexc.com/api/v1/contract/kline")
TF, CHECK_N = 300, 6
STATE_DIR = Path(os.getenv("STATE_DIR",".")); STATE_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("btc-eth-5m")
http = requests.Session()
http.headers.update({"User-Agent":"Mozilla/5.0 BTC-ETH-5m-Pattern-Bot/2.0"})

# P4/P5 intentionally remain separate labels but have identical conditions.
RULES = {"P1":(1,2,6), "P2":(1,2,3,6), "P3":(1,2,3,4,6),
         "P4":(1,2,3,4,5,6), "P5":(1,2,3,4,5,6)}

def candle_color(c):
    if c["close"] > c["open"]: return "GREEN"
    if c["close"] < c["open"]: return "RED"
    return "DOJI"

def kyiv(ts):
    return datetime.fromtimestamp(ts, ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d %H:%M:%S")

def send(msg):
    if TEST:
        log.info("TEST MESSAGE:\\n%s", msg); return True
    if not TOKEN or not CHAT_IDS:
        log.error("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"); return False
    ok = True
    for chat in CHAT_IDS:
        try:
            r = http.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                          json={"chat_id":chat,"text":msg}, timeout=15)
            data = r.json()
            if not r.ok or not data.get("ok"):
                ok = False; log.error("Telegram error %s %s", r.status_code, r.text[:300])
        except Exception:
            ok = False; log.exception("Telegram send failed")
    return ok

def fetch(symbol):
    now = int(time.time())
    r = http.get(f"{API.rstrip('/')}/{symbol}",
                 params={"interval":"Min5","limit":300,"end":now}, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if not payload.get("success"): raise RuntimeError(f"MEXC API error: {payload}")
    d = payload.get("data") or {}
    if not isinstance(d,dict) or any(k not in d for k in ("time","open","close")):
        raise RuntimeError(f"Unexpected MEXC response: {str(d)[:300]}")
    n = min(len(d["time"]),len(d["open"]),len(d["close"]))
    closed, live = [], None
    for i in range(n):
        ts=int(d["time"][i]); c={"ts":ts,"open":float(d["open"][i]),"close":float(d["close"][i])}
        if ts+TF <= now: closed.append(c)
        elif ts <= now < ts+TF: live=c
    closed.sort(key=lambda x:x["ts"])
    return closed,live

def read_state(path):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError: return {"last_ts":None,"seen":[],"pending":[],"pre":[]}
    except Exception:
        log.exception("Bad state file %s; starting clean",path)
        return {"last_ts":None,"seen":[],"pending":[],"pre":[]}

def write_state(state,path):
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(tmp,path)

class Engine:
    def __init__(self,symbol):
        self.symbol=symbol; self.path=STATE_DIR/f"state_{symbol}.json"
        self.state=read_state(self.path)
        for k,v in (("seen",[]),("pending",[]),("pre",[]),("last_ts",None)):
            self.state.setdefault(k,v)
        self.candles={}

    def add_history(self,closed):
        for c in closed: self.candles[c["ts"]]=c
        for ts in sorted(self.candles)[:-350]: self.candles.pop(ts,None)

    def seq(self,start,n=6):
        return [self.candles.get(start+i*TF) for i in range(n)]

    def matched(self,seq,base):
        if not all(seq): return []
        cols=[candle_color(c) for c in seq]
        if any(x not in ("GREEN","RED") for x in cols): return []
        out=[r for r,pos in RULES.items() if all(cols[p-1]==base for p in pos)]
        if "P4" in out and "P5" in out:
            out=[r for r in out if r not in ("P4","P5")]+["P4/P5"]
        return out

    def msg(self,head,rule,direction,start,extra=""):
        icon="🟢" if direction=="LONG" else "🔴"
        lines=[head,f"{self.symbol.replace('_','')} | MEXC Futures","Таймфрейм: 5 хвилин",
               f"Правило: {rule}",f"Напрямок: {icon} {direction}",
               f"Початок комбінації: {kyiv(start)} (Київ)"]
        if extra: lines.append(extra)
        lines.append("Автоматичні угоди не виконуються.")
        return "\\n".join(lines)

    def pre_alert(self,live):
        if not live: return
        start=live["ts"]-5*TF
        first5=self.seq(start,5)
        if not all(first5): return
        remain=TF-(int(time.time())-live["ts"])
        if not (0 < remain <= 120): return
        cols=[candle_color(c) for c in first5]
        if any(x not in ("GREEN","RED") for x in cols): return
        base=cols[0]
        possible=[r for r,pos in RULES.items() if all(cols[p-1]==base for p in pos if p<=5)]
        if not possible or candle_color(live)!=base: return
        rule="P4/P5" if "P4" in possible and "P5" in possible else ",".join(possible)
        key=f"{start}:{base}:{rule}"
        if key in self.state["pre"]: return
        direction="SHORT" if base=="GREEN" else "LONG"
        text=self.msg("⚠️ PRE-ПОПЕРЕДЖЕННЯ",rule,direction,start,
          "До закриття свічки №6 не більше 2 хвилин. Якщо її колір зміниться до закриття, сигналу не буде.")
        if send(text):
            self.state["pre"].append(key); self.state["pre"]=self.state["pre"][-1500:]
            write_state(self.state,self.path)
            log.info("PRE %s %s %s",self.symbol,rule,direction)

    def process_closed(self,c):
        ts=c["ts"]; current=candle_color(c)
        # Resolve active signals against the next six closed candles.
        still=[]
        for p in self.state["pending"]:
            if ts<=p["signal_ts"]: still.append(p); continue
            idx=(ts-p["signal_ts"])//TF
            if not 1<=idx<=CHECK_N: continue
            wanted="GREEN" if p["direction"]=="LONG" else "RED"
            if current==wanted:
                send(self.msg("✅ WIN",p["rule"],p["direction"],p["start_ts"],
                              f"Результат: WIN {idx}/6 — потрібний колір на свічці {idx}/6."))
                log.info("WIN %s %s %s %d/6",self.symbol,p["rule"],p["direction"],idx)
            elif idx==CHECK_N:
                send(self.msg("❌ LOSS",p["rule"],p["direction"],p["start_ts"],
                              "Результат: LOSS 6/6 — потрібного кольору не було в усіх шести свічках."))
                log.info("LOSS %s %s %s 6/6",self.symbol,p["rule"],p["direction"])
            else:
                p["progress"]=idx; still.append(p)
                log.info("CHECK %s %s %s %d/6",self.symbol,p["rule"],p["direction"],idx)
        self.state["pending"]=still

        # Current just-closed candle is #6 of a possible pattern.
        start=ts-5*TF; s=self.seq(start,6)
        if not all(s): return
        cols=[candle_color(x) for x in s]
        if any(x not in ("GREEN","RED") for x in cols): return
        base=cols[0]; rules=self.matched(s,base)
        if not rules: return
        rule=",".join(rules); key=f"{start}:{base}:{rule}"
        if key in self.state["seen"]: return
        direction="SHORT" if base=="GREEN" else "LONG"
        if send(self.msg("🔔 ПІДТВЕРДЖЕНИЙ СИГНАЛ",rule,direction,start,
                         "Свічка №6 закрилася потрібним кольором. Перевіряються наступні 6 свічок.")):
            self.state["seen"].append(key); self.state["seen"]=self.state["seen"][-3000:]
            self.state["pending"].append({"rule":rule,"direction":direction,"start_ts":start,
                                          "signal_ts":ts,"progress":0})
            log.info("SIGNAL %s %s %s",self.symbol,rule,direction)

    def cycle(self,closed,live):
        if not self.candles:
            self.add_history(closed)
            if self.state["last_ts"] is None:
                self.state["last_ts"]=closed[-1]["ts"] if closed else None
                write_state(self.state,self.path)
                log.info("Initialized %s; waiting for new candles",self.symbol)
                self.pre_alert(live)
                return
        else:
            self.add_history(closed)
        self.pre_alert(live)
        last=int(self.state["last_ts"] or 0)
        fresh=[x for x in closed if x["ts"]>last]
        for c in fresh:
            self.process_closed(c)
            self.state["last_ts"]=c["ts"]
            write_state(self.state,self.path)

def main():
    if not SYMBOLS: raise RuntimeError("No symbols configured")
    log.info("MEXC 5m bot starting: %s; poll=%ss",SYMBOLS,POLL)
    log.info("PRE <=120s before #6 close; results: next six candles.")
    engines={s:Engine(s) for s in SYMBOLS}
    if not TEST: send("🤖 БОТ ЗАПУЩЕНО\\nMEXC Futures | BTCUSDT, ETHUSDT | 5m\\nP1–P5 LONG/SHORT\\nPRE за 2 хв до закриття №6\\nПеревірка результату: до 6 свічок (1/6–6/6).")
    while True:
        for sym,eng in engines.items():
            try:
                closed,live=fetch(sym); eng.cycle(closed,live)
            except Exception: log.exception("Cycle failed for %s",sym)
        time.sleep(POLL)

if __name__=="__main__":
    if TEST:
        print("TEST MODE: UTF-8 source OK")
        print("Symbols:",", ".join(SYMBOLS))
        print("Rules:",", ".join(RULES))
        print("PRE: <=120 seconds before candle #6 close")
        print("Outcome: next 6 closed candles; WIN on first target colour, else LOSS 6/6")
    else:
        main()
