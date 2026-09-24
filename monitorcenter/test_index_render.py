"""Quick Jinja/markup sanity check for the homepage's new Memory tile."""
import config
from flask import Flask

app = Flask(__name__, template_folder=str(config.TEMPLATE_DIR), static_folder=str(config.STATIC_DIR))

with app.test_request_context("/"):
    html = app.jinja_env.get_template("index.html").render(modules=["laptop", "wipe", "cpu", "mem", "gpu"])

ok = True


def check(label, cond):
    global ok
    print(f"  [{'OK' if cond else 'FAIL'}] {label}")
    if not cond:
        ok = False


check("renders without Jinja error", bool(html))
check("Memory tile present", 'href="/mem/"' in html)
check("Memory label present", ">Memory<" in html)
check("summary.mem wired in JS", "summary.mem" in html)
check("5-column grid", "repeat(5,1fr)" in html)
print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
