# BTCUSDT + ETHUSDT 5m Telegram signal bot

## Logic
- MEXC USDT Perpetual native 5-minute candles.
- P1: candle #1, #2 and #6 match the base colour; #3–#5 are unrestricted.
- P2: #1, #2, #3 and #6 match; #4–#5 unrestricted.
- P3: #1, #2, #3, #4 and #6 match; #5 unrestricted.
- P4 and P5: all six match. They are kept as separate rule names but grouped as one P4/P5 alert to prevent duplicate signals.
- Base GREEN => confirmed SHORT; base RED => confirmed LONG.
- PRE: when no more than 120 seconds remain before candle #6 closes, if the live #6 colour currently matches the base and the first five candles meet a rule. If #6 changes before close, no confirmed signal is sent.
- Signal only after #6 is closed.
- After signal, inspect the next six CLOSED candles. First target colour is WIN 1/6 ... WIN 6/6. If none of six has target colour, LOSS 6/6.
- Doji (open == close) is neither GREEN nor RED.
- No automatic orders.

## Railway
Deploy this folder from GitHub. Add variables:
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- SYMBOLS=BTCUSDT,ETHUSDT
- POLL_SECONDS=3
- TEST_MODE=false

Persistent storage is recommended for state files `state_BTC_USDT.json` and `state_ETH_USDT.json`.

## Local test
Python 3.10+:
```bash
pip install -r requirements.txt
TEST_MODE=true python main.py
```
The test mode prints configuration only; it does not call MEXC or Telegram.
