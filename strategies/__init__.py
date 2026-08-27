# __init__.py 파일은
# 이 폴더(strategies)는 그냥 폴더가 아닌 파이썬 패키지라는 표시를 해 주는 파일이다
# 단순 base.py 모듈과 ema_cross 모듈(두 개의 파이썬 파일)이 아닌 하나의 팀이라고 생각한다.
# 그러면 상대 import 가 사용 가능하다.

# strategies/__init__.py
import importlib
import inspect
import pkgutil
from pathlib import Path

from .base import Strategy

# from strategies import * 을 하면 어떤 이름을 가져올지 알려준다.
# __all__이 없다면 밑줄로 시작하지 않는 모든 이름을 가져온다.
__all__ = ["Strategy"]

# 밑줄로 시작하여 import시 자동으로 제외됨
_EXCLUDED = {"base", "registry"}
_package_dir = Path(__file__).parent


# ( pkgutil.iter_modules -> (module_finder, 모듈명, 패키지인지[또폴더인지]))
for module_info in pkgutil.walk_packages([str(_package_dir)], prefix=f"{__name__}."):
    module_name = module_info.name.rsplit(".", 1)[-1]
    if module_name in _EXCLUDED:
        continue


    # from .ema_cross_with_atr import EmaCrossStrategyWithATR 와 같은 작업을 하는 것
    module = importlib.import_module(module_info.name)

    for name, obj in inspect.getmembers(module, inspect.isclass):
        # 방금 import한 모듈에 정의되어 있거나 해당 import한 모듈에서 import한 모듈의 클래스만 가져온다.
        if issubclass(obj, Strategy) and obj is not Strategy:
            # 해당 클래스가 Strategy의 클래스라면 가져와서
            globals()[name] = obj
            # 딕셔너리 형태의 전역 네임스페이스에 저장한다.
            __all__.append(name)
            # 해당 값을 __all__에 추가한다.