# MEXC Telegram signal bot — 5m + 10m

## What it monitors
- MEXC USDT perpetual candles on both native 5-minute and 10-minute timeframes.
- Symbols are controlled by `SYMBOLS` (default: `BTCUSDT`). Set `SYMBOLS=BTCUSDT` for BTC only.
- P1–P5 pattern rules; P4/P5 share identical conditions and are grouped in one label.
- PRE is sent up to 120 seconds before candle #6 closes when the live candle currently matches.
- Confirmed signal is sent only after candle #6 closes.
- Each signal is checked against the next six CLOSED candles of its own timeframe. First target-colour candle = WIN n/6; otherwise LOSS 6/6.
- GREEN base produces SHORT; RED base produces LONG. Doji candles do not qualify.
- No automatic orders are placed.

## Telegram message format
PRE, signal and result messages contain only symbol/exchange, timeframe, rule and direction (plus the PRE/result heading).

## Railway variables
- `TELEGRAM_BOT_TOKEN` — BotFather token
- `TELEGRAM_CHAT_ID` — chat ID (comma-separated IDs supported)
- `SYMBOLS=BTCUSDT` (add `,ETHUSDT` if needed)
- `POLL_SECONDS=3`
- `TEST_MODE=false`
- `STATE_DIR=/data` (recommended when a Railway Volume is mounted at `/data`)

Start command: `python main.py`. Python 3.9+ is required (`zoneinfo`).

## Important
The code has been syntax-checked and UTF-8 checked. This does not constitute a live API/Telegram integration test. Confirm MEXC API availability in Railway logs after deployment.
