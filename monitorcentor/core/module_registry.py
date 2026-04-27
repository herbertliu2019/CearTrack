"""Auto-discover and register test modules under the modules/ package.

Each module is a subpackage under modules/ (e.g. modules/laptop/). The
package must expose a `blueprint` attribute on its `module` submodule —
i.e. `modules.<name>.module.blueprint` — which gets mounted at
`/<name>/`. If it also exposes `_module` (a TestModule instance) the
instance is returned in the registry so callers can use its hooks
(e.g. extract_searchable_sns for the SQLite index).
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any


def register_modules(app) -> dict[str, Any]:
    """Auto-discover and register all modules under modules/.

    Returns a dict of {module_name: TestModule instance | None}. The dict
    iterates/len-s like a list of names, so legacy call-sites that only
    care about the names keep working.
    """
    import modules  # local import so this file stays dependency-free

    registered: dict[str, Any] = {}
    for _, name, is_pkg in pkgutil.iter_modules(modules.__path__):
        if name == "base" or not is_pkg:
            continue
        try:
            mod = importlib.import_module(f"modules.{name}.module")
            if hasattr(mod, "blueprint"):
                app.register_blueprint(mod.blueprint, url_prefix=f"/{name}")
                registered[name] = getattr(mod, "_module", None)
                print(f"\u2713 Registered module: {name}")
        except Exception as e:
            print(f"\u2717 Failed to register {name}: {e}")

    if not registered:
        print("No modules registered")
    return registered
