# MEXC Telegram signal bot — 5m + 10m (10m aggregated from two MEXC 5m candles)

## What it monitors
- MEXC USDT perpetual candles on both native 5-minute and 10-minute (10-minute bars are locally aggregated from two consecutive MEXC 5-minute bars) timeframes.
- Symbols are controlled by `SYMBOLS` (default: `BTCUSDT`). Set `SYMBOLS=BTCUSDT` for BTC only.
- P2–P5 pattern rules; P4/P5 share identical conditions and are grouped in one label.
- FIVE rule: five consecutive RED candles = LONG; five consecutive GREEN candles = SHORT.
- For FIVE, PRE is sent 2 minutes before the fifth candle closes if it currently has the required color; confirmed signal follows the fifth close.
- FIVE result checkpoints are candles #6, #7, #8, #9, and #13. First target-color checkpoint = WIN; otherwise LOSS at #13.
- Additional EIGHT rule: eight consecutive GREEN candles = SHORT; eight consecutive RED candles = LONG.
- For P2–P5, PRE is sent up to 120 seconds before candle #7 closes; confirmed signal follows #7 close if it matches #6.
- For EIGHT, PRE is sent up to 120 seconds before candle #8 closes only when the previous seven closed candles and the live eighth candle all have the same non-doji colour. Confirmed signal follows #8 close only if all eight candles match.
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
