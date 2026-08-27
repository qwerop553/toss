import scrap
import strategies
from backtest_engine import run_backtest
from validation import walk_forward_split
from print_summary import print_summary, plot_backtest, to_daily_summary

ticker = "000660"
interval = "1m"
df = scrap.load_candles(ticker, interval)
train, test = walk_forward_split(df)

strategy = 
signal = strategy.generate_signals(test)
result = run_backtest(test, signal)

print_summary(result)

title=f"SessionClose"
fig = plot_backtest(test, result, title)
fig.savefig(r"C:\Users\sungwon\Desktop\Project\toss\graph" + f"{strategy.__str__}with{ticker}.png", dpi=120)

daily_report = to_daily_summary(test, result)
print(daily_report)