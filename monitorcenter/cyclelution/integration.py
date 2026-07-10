"""Register the Cyclelution export blueprint with the Flask app.

Mirrors modules/wipe/integration.py so app.py stays a one-liner and no
existing module code changes.
"""

from .web import blueprint
from . import sync_state


def register_cyclelution_module(app):
    sync_state.init_schema()          # ensure laptop_sync exists on boot
    app.register_blueprint(blueprint)
