"""
백테스팅 CLI. 실행 · 자동 최적화 · 전략 비교를 전부 여기서 한다.

    python run.py EmaCrossStrategy --ticker 005930
    python run.py EmaCrossStrategy --ticker 005930 --optimize --plot --daily
    python run.py --all --ticker 005930 000660 035420 --optimize

예전에는 backtest.py와 run_optimize.py 본문을 직접 고쳐 가며 돌렸다.
이 파일이 그 둘을 대체한다.
"""
import argparse
import os

import pandas as pd

import scrap
import strategies
from backtest_engine import run_backtest
from grids import GRIDS, VALID
from metrics import sharpe_ratio, max_drawdown, trade_stats
from optimize import grid_search
from print_summary import print_summary, plot_backtest, to_daily_summary
from validation import walk_forward_split

GRAPH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graph")


def run_one(name: str, ticker: str, interval: str, optimize: bool, metric: str):
    """
    전략 하나를 종목 하나에 돌린다.

    --optimize면 train 구간에서 그리드서치를 돌려 최적 파라미터를 고르고,
    그 파라미터를 test 구간(out-of-sample)에 그대로 적용한다. 이렇게 해야
    '파라미터를 맞춰 놓고 같은 데이터로 자랑하는' 자기기만을 피할 수 있다.

    반환: (test 구간 df, BacktestResult, 사용한 파라미터 dict, 그리드서치 순위표 or None)
    """
    strategy_cls = strategies.REGISTRY[name]

    df = scrap.load_candles(ticker, interval)
    if df.empty:
        raise SystemExit(
            f"{ticker} {interval} 데이터가 없습니다. "
            f"먼저 `python scrap.py {ticker} --interval {interval}`를 실행하세요."
        )
    df = df.reset_index(drop=True)
    train, test = walk_forward_split(df)

    params: dict = {}
    leaderboard = None

    if optimize and name in GRIDS:
        opt = grid_search(
            train,
            strategy_factory=strategy_cls,
            param_grid=GRIDS[name],
            metric=metric,
            valid_combo=VALID.get(name),
        )
        params = opt.best_params
        leaderboard = opt.leaderboard

    # 그리드가 없으면 params가 빈 dict라 생성자 기본값이 그대로 쓰인다.
    strategy = strategy_cls(**params)
    signal = strategy.generate_signals(test)
    result = run_backtest(test, signal)

    return test, result, params, leaderboard


def cmd_single(args):
    """전략 하나를 자세히 본다."""
    name = args.strategy
    ticker = args.ticker[0]

    test, result, params, leaderboard = run_one(
        name, ticker, args.interval, args.optimize, args.metric
    )

    print(f"\n{name} / {ticker} / {args.interval}")
    if leaderboard is not None:
        print(f"\n[ train 그리드서치 상위 10개 — 기준: {args.metric} ]")
        print(leaderboard.head(10).to_string(index=False))
        print(f"\n최적 파라미터: {params}")
        print("\n아래는 이 파라미터를 test 구간(out-of-sample)에 적용한 결과입니다.")
    elif args.optimize:
        print(f"(grids.py에 {name}의 탐색 범위가 없어 기본 파라미터로 실행합니다)")

    print()
    print_summary(result)

    if args.daily:
        print("\n[ 일별 요약 ]")
        print(to_daily_summary(test, result).to_string())

    if args.plot:
        os.makedirs(GRAPH_DIR, exist_ok=True)
        suffix = "_opt" if leaderboard is not None else ""
        path = os.path.join(GRAPH_DIR, f"{name}_{ticker}_{args.interval}{suffix}.png")
        plot_backtest(test, result, f"{name} / {ticker}").savefig(path, dpi=120)
        print(f"\n그래프 저장: {path}")


def cmd_compare(args):
    """전략 x 종목을 전부 돌려 한 장의 순위표로 낸다."""
    rows = []

    for name in sorted(strategies.REGISTRY):
        for ticker in args.ticker:
            try:
                _, result, params, _ = run_one(
                    name, ticker, args.interval, args.optimize, args.metric
                )
            except Exception as exc:
                # 한 전략이 죽어도 나머지 비교는 계속되어야 한다.
                # (예: 시간 기반 전략에 일봉을 물린 경우)
                print(f"  건너뜀  {name} / {ticker}: {type(exc).__name__}: {exc}")
                continue

            stats = trade_stats(result.trades)
            rows.append({
                "전략": name,
                "종목": ticker,
                "샤프": round(sharpe_ratio(result.returns), 2),
                "MDD": round(max_drawdown(result.equity_curve, result.max_book_size), 4),
                "승률": round(stats["win_rate"], 3),
                "왕복": stats["round_trips"],
                "순손익": round(result.equity_curve.iloc[-1], 0),
                "벤치마크": round(result.benchmark_pnl, 0),
                "파라미터": params or "기본값",
            })

    if not rows:
        raise SystemExit("실행된 조합이 없습니다.")

    table = pd.DataFrame(rows).sort_values("샤프", ascending=False).reset_index(drop=True)
    print("\n[ 비교 결과 — test 구간(out-of-sample) 기준, 샤프 내림차순 ]")
    print(table.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(
        description="백테스팅 실행 / 최적화 / 비교",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="예시:\n"
               "  python run.py EmaCrossStrategy --ticker 005930\n"
               "  python run.py BollingerBandStrategy --ticker 005930 --optimize --plot --daily\n"
               "  python run.py --all --ticker 005930 000660 --optimize",
    )
    parser.add_argument("strategy", nargs="?",
                        help=f"전략 클래스명. 가능: {', '.join(sorted(strategies.REGISTRY))}")
    parser.add_argument("--all", action="store_true", help="등록된 전략 전부를 돌려 순위표로 비교")
    parser.add_argument("--ticker", nargs="+", default=["005930"], help="종목 코드 (여러 개 가능)")
    parser.add_argument("--interval", default="1m", help="봉 주기 (기본: 1m)")
    parser.add_argument("--optimize", action="store_true",
                        help="grids.py 범위로 train 그리드서치 후 test에 적용")
    parser.add_argument("--metric", default="sharpe",
                        choices=["sharpe", "sortino", "calmar", "mdd"],
                        help="최적화 기준 (기본: sharpe)")
    parser.add_argument("--plot", action="store_true", help="graph/에 그래프 저장")
    parser.add_argument("--daily", action="store_true", help="일별 요약표 출력")
    args = parser.parse_args()

    if args.all:
        return cmd_compare(args)

    if not args.strategy:
        parser.error("전략명을 주거나 --all을 쓰세요.")
    if args.strategy not in strategies.REGISTRY:
        parser.error(f"모르는 전략: {args.strategy}\n"
                     f"가능: {', '.join(sorted(strategies.REGISTRY))}")

    return cmd_single(args)


if __name__ == "__main__":
    main()
