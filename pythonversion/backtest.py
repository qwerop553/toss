import strategies
from DB import DB
import pandas as pd

buy_slippage = 0.00015
sell_slippage =  0.00215
db = DB()
def backtest(name: str, ticker: str):
    strategy = strategies.REGISTRY[name]()
    df = db.load(ticker)

    signal = strategy.generate_signals(df)
    
    holdings = 0
    cash = 0
    trades = []

    for i in range(len(df)):
        price = df["close"].iloc[i]
        sig = signal.iloc[i]

        if sig > 0:
            cash += price * (1 + buy_slippage) * sig * -1
            holdings += sig
            trades.append({"date": df["timestamp"].iloc[i],
                           "transaction": "buy",
                           "price": price,
                           "number": sig,
                           "cash_now": cash
                           })

        elif sig < 0:
            cash += price * (1 - sell_slippage) * sig * -1
            holdings += sig
            trades.append({"date": df["timestamp"].iloc[i],
                            "transaction": "sell",
                            "price": price,
                            "number": -1 * sig,
                            "cash_now": cash
                            })

    trades.append({"date": df["timestamp"].iloc[i],
                            "transaction": "Final",
                            "price": 0,
                            "number": 0,
                            "cash_now": cash + df["close"].iloc[len(df)-1] * holdings
                            })
    return pd.DataFrame(trades)

if __name__ == "__main__":
    print(backtest("OpeningRangeStrategy", "005930"))
    

    