from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader("templates"))
t = env.get_template("wipe/dashboard.html")
print("wipe/dashboard.html: OK")
