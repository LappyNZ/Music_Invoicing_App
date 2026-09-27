from flask import Flask, render_template
from config import get_config
from db import init_db
from utils import fmt_date, parse_date_any, nz_school_term
from routes.students import students_bp
from routes.lessons import lessons_bp
from routes.invoices import invoices_bp
import os


# --------------------------------------------------------------------------------------
# App setup
# --------------------------------------------------------------------------------------
app = Flask(__name__)
app.config.from_object(get_config())
app.secret_key = app.config["SECRET_KEY"]

os.makedirs(os.path.dirname(app.config["DB_PATH"]), exist_ok=True)
os.makedirs(app.config["INVOICE_PDF_DIR"], exist_ok=True)

app.register_blueprint(students_bp)
app.register_blueprint(lessons_bp)
app.register_blueprint(invoices_bp)

# Create or upgrade the database. start.sh also imports this module once before gunicorn starts.
with app.app_context():
    init_db()


# Make helpers available in Jinja templates
app.jinja_env.globals["fmt_date_display"] = fmt_date
app.jinja_env.globals["fmt_date"] = fmt_date
app.jinja_env.globals["parse_date_any"] = parse_date_any
app.jinja_env.globals["nz_school_term"] = nz_school_term


@app.context_processor
def inject_version():
    return {"app_version": app.config["APP_VERSION"][:7]}


@app.route("/health")
def health():
    return "OK", 200


@app.route("/version")
def version():
    return {"version": app.config["APP_VERSION"]}


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=app.config["DEBUG"])