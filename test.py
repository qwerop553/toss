print(__file__)

from pathlib import Path

print(Path(__file__))
print(Path(__file__).parent)


import pkgutil
for module_info in pkgutil.walk_packages([str(Path(__file__).parent)]):
    print (module_info)
    print (module_info.name.rsplit(".", 1))
    print (module_info.name.rsplit(".", 1)[-1])
'''
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='backtest', ispkg=False)
['backtest']
backtest
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='backtest_engine', ispkg=False)
['backtest_engine']
backtest_engine
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='metrics', ispkg=False)
['metrics']
metrics
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='optimize', ispkg=False)
['optimize']
optimize
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='print_summary', ispkg=False)
['print_summary']
print_summary
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='run_optimize', ispkg=False)
['run_optimize']
run_optimize
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='scrap', ispkg=False)
['scrap']
scrap
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='strategies', ispkg=True)
['strategies']
strategies
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss\\strategies'), name='strategies.base', ispkg=False)
['strategies', 'base']
base
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss\\strategies'), name='strategies.mean_reversion', ispkg=True)
['strategies', 'mean_reversion']
mean_reversion
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss\\strategies\\mean_reversion'), name='strategies.mean_reversion.bollinger_band', ispkg=False)
['strategies.mean_reversion', 'bollinger_band']
bollinger_band
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss\\strategies'), name='strategies.session_based', ispkg=True)
['strategies', 'session_based']
session_based
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss\\strategies\\session_based'), name='strategies.session_based.session_close', ispkg=False)
['strategies.session_based', 'session_close']
session_close
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss\\strategies'), name='strategies.trend_following', ispkg=True)
['strategies', 'trend_following']
trend_following
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss\\strategies\\trend_following'), name='strategies.trend_following.ema_cross', ispkg=False)
['strategies.trend_following', 'ema_cross']
ema_cross
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss\\strategies\\trend_following'), name='strategies.trend_following.ema_cross_with_adx',ispkg=False)
['strategies.trend_following', 'ema_cross_with_adx']
ema_cross_with_adx
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss\\strategies\\trend_following'), name='strategies.trend_following.ema_cross_with_atr',ispkg=False)
['strategies.trend_following', 'ema_cross_with_atr']
ema_cross_with_atr
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='test', ispkg=False)
['test']
test
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='validation', ispkg=False)
['validation']
validation
'''
print("--------------")
for module_info in pkgutil.walk_packages([str(Path(__file__).parent)], prefix=f"{__name__}."):
    print (module_info)
    print (module_info.name.rsplit(".", 1))
    print (module_info.name.rsplit(".", 1)[-1])

    """
    ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='__main__.backtest', ispkg=False)
['__main__', 'backtest']
backtest
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='__main__.backtest_engine', ispkg=False)
['__main__', 'backtest_engine']
backtest_engine
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='__main__.metrics', ispkg=False)
['__main__', 'metrics']
metrics
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='__main__.optimize', ispkg=False)
['__main__', 'optimize']
optimize
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='__main__.print_summary', ispkg=False)
['__main__', 'print_summary']
print_summary
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='__main__.run_optimize', ispkg=False)
['__main__', 'run_optimize']
run_optimize
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='__main__.scrap', ispkg=False)
['__main__', 'scrap']
scrap
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='__main__.strategies', ispkg=True)
['__main__', 'strategies']
strategies
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='__main__.test', ispkg=False)
['__main__', 'test']
test
ModuleInfo(module_finder=FileFinder('c:\\Users\\sungwon\\Desktop\\Project\\toss'), name='__main__.validation', ispkg=False)
['__main__', 'validation']
validation
"""

import importlib 

module = importlib.import_module('scrap')
print(module)
# <module 'scrap' from 'c:\\Users\\sungwon\\Desktop\\Project\\toss\\scrap.py'>

print(module.__dict__)