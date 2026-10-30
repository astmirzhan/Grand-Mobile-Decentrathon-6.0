from __future__ import annotations

import importlib
import pkgutil

# Автоматически импортируем все чек-модули в пакете checks
__all__ = []

for _, mod_name, _ in pkgutil.iter_modules(__path__):
    if mod_name != "__init__":
        module = importlib.import_module(f".{mod_name}", package=__name__)
        globals()[mod_name] = module
        __all__.append(mod_name)