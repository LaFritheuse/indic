"""Trade-level and equity-curve metrics."""

import numpy as np
import pandas as pd


def compute_metrics(trades_df: pd.DataFrame, risk_per_trade_pct: float = 0.01, initial_equity: float = 10_000.0) -> dict:
    if trades_df.empty:
        return {
            "n_trades": 0, "winrate_pct": None, "expectancy_R": None,
            "net_return_pct": None, "max_drawdown_pct": None,
            "profit_factor": None, "avg_R": None,
        }

    r = trades_df["r_multiple"]
    wins = r[r > 0]
    losses = r[r <= 0]

    winrate_pct = 100 * len(wins) / len(r)
    expectancy_R = r.mean()

    # Equity curve: each trade risks risk_per_trade_pct of CURRENT equity,
    # scaled by its R multiple (compounding).
    equity = [initial_equity]
    for rm in r:
        equity.append(equity[-1] * (1 + risk_per_trade_pct * rm))
    equity = pd.Series(equity)

    net_return_pct = 100 * (equity.iloc[-1] / equity.iloc[0] - 1)

    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_drawdown_pct = 100 * drawdown.min()

    gross_win = wins.sum() if len(wins) else 0.0
    gross_loss = -losses.sum() if len(losses) else 0.0
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else np.nan

    return {
        "n_trades": len(r),
        "winrate_pct": round(winrate_pct, 1),
        "expectancy_R": round(expectancy_R, 4),
        "net_return_pct": round(net_return_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "profit_factor": round(profit_factor, 2) if not np.isnan(profit_factor) else None,
        "avg_R": round(expectancy_R, 4),
        "equity_curve": equity,
    }
