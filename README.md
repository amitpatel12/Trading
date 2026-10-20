# Pre-market plan website (automated)

Every weekday ~8:30 AM IST a GitHub Action runs `screener.py`, which:
1. Downloads daily prices for ~50 large NSE stocks (free, via yfinance) and global cues.
2. Scores each stock for buy / intraday-short setups (trend, RSI, volume, momentum, close position).
3. Checks Google News headlines for risk words.
4. Calculates entry, stop-loss, target and quantity for Rs 1 lakh with 1% risk per trade.
5. Writes `docs/index.html`, which GitHub Pages serves as your website.

## Setup (about 10 minutes)
1. Create a new GitHub repo and upload everything in this folder.
2. Settings > Pages > Source: "Deploy from a branch", branch `main`, folder `/docs`.
3. Actions tab > "Daily pre-market plan" > Run workflow (to test now).
4. Your site: https://YOUR-USERNAME.github.io/REPO-NAME/

Test locally: `pip install -r requirements.txt && python screener.py --demo`

## Tune it
Edit the SETTINGS block at the top of `screener.py` (capital, risk %, stop/target multiples, stock list).
GitHub scheduled runs can be delayed 10-30 min; if you need it earlier, change the cron to `30 2 * * 1-5`.

## Honest limits
- Targets are 1.5 x daily ATR, so with Rs 1 lakh and 1% risk each trade aims for roughly Rs 500-1,500, not a guaranteed Rs 2,000.
- It uses yesterday's close. It cannot see the opening gap, so check the price at 9:15 before entering.
- No backtest yet. Paper trade for 3-4 weeks before using real money.
- Educational tool, not investment advice.

