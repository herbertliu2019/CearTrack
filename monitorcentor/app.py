"""Monitorcenter Flask entrypoint."""

from flask import Flask, jsonify, render_template, request

import config
from core.module_registry import register_modules
from core import storage, index_db

app = Flask(
    __name__,
    static_url_path='/laptop/static',
    static_folder=str(config.STATIC_DIR),
    template_folder=str(config.TEMPLATE_DIR),
)

MODULES = register_modules(app)


def _extract_sns_for_module(module_name: str, envelope: dict) -> list[dict]:
    inst = MODULES.get(module_name)
    if inst is not None and hasattr(inst, "extract_searchable_sns"):
        return inst.extract_searchable_sns(envelope)
    return [{"sn": envelope.get("sn", ""), "kind": "system"}]


index_db.init_schema()
if index_db.count() == 0:
    n = index_db.rebuild_all(_extract_sns_for_module)
    if n:
        print(f"\u2713 Rebuilt SN index from {n} history envelope(s)")


@app.route("/")
def index():
    return render_template("index.html", modules=list(MODULES.keys()))


@app.route("/search")
def search():
    """Cross-module SN search — returns {sn, count, results} envelope."""
    sn = (request.args.get("sn") or "").strip()
    results: list[dict] = []
    if sn:
        for m in MODULES:
            try:
                results.extend(storage.search_sn(m, sn))
            except Exception as e:
                print(f"Search error for {m}: {e}")
    results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return jsonify({"sn": sn, "count": len(results), "results": results})


@app.route("/api/search")
def api_search():
    """Cross-module SN search — returns a flat list of envelopes.

    Used by the landing-page global search. Individual module failures
    are logged and skipped so one broken module cannot break search.
    """
    sn = (request.args.get("sn") or "").strip()
    if not sn:
        return jsonify({"error": "sn parameter required"}), 400

    results: list[dict] = []
    for m in MODULES:
        try:
            results.extend(storage.search_sn(m, sn))
        except Exception as e:
            print(f"Search error for {m}: {e}")

    results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return jsonify(results)


@app.route("/api/admin/rebuild_index", methods=["POST"])
def admin_rebuild_index():
    """Manual full rebuild of the SQLite index from history files."""
    n = index_db.rebuild_all(_extract_sns_for_module)
    return jsonify({"rebuilt": n, "total": index_db.count()})


if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
