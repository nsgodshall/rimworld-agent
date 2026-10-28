"""Find the Manager classes in rimagent.managers, and reload them when their files change."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from types import ModuleType

from .manager import Manager


class ManagerLoader:
    def __init__(self, package: str = "rimagent.managers"):
        self.package = package
        self._mtimes: dict[str, float] = {}
        self._modules: dict[str, ModuleType] = {}

    def _files(self) -> dict[str, Path]:
        pkg = importlib.import_module(self.package)
        root = Path(pkg.__file__).parent
        return {
            f"{self.package}.{info.name}": root / f"{info.name}.py"
            for info in pkgutil.iter_modules([str(root)])
            if not info.ispkg and not info.name.startswith("_")
        }

    def changed(self) -> bool:
        files = self._files()
        return set(files) != set(self._mtimes) or any(f.stat().st_mtime != self._mtimes[m] for m, f in files.items())

    def load(self, previous: list[Manager] = ()) -> list[Manager]:
        """(Re)import every manager module and instantiate its Manager subclasses, keeping schedules."""
        last_ticks = {m.name: m.last_tick for m in previous}
        managers: list[Manager] = []
        files = self._files()
        for module_name, path in sorted(files.items()):
            if module_name in self._modules and path.stat().st_mtime != self._mtimes.get(module_name):
                module = importlib.reload(self._modules[module_name])
            else:
                module = self._modules.get(module_name) or importlib.import_module(module_name)
            self._modules[module_name] = module
            self._mtimes[module_name] = path.stat().st_mtime
            for _, cls in inspect.getmembers(module, inspect.isclass):
                if issubclass(cls, Manager) and cls is not Manager and cls.__module__ == module.__name__:
                    manager = cls()
                    manager.last_tick = last_ticks.get(manager.name)
                    managers.append(manager)
        managers.sort(key=lambda m: (m.priority, m.name))
        for gone in set(self._mtimes) - set(files):
            del self._mtimes[gone]
            self._modules.pop(gone, None)
        return managers
