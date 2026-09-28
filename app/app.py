from flask import Flask
from config import get_config
from db import init_db
import terms
from utils import fmt_date, fmt_day, fmt_dm, fmt_full, fmt_long, invoice_number_of, money, parse_date_any, nz_school_term, utc_to_local
from routes.home import home_bp
from routes.invoices import invoices_bp
from routes.lessons import lessons_bp
from routes.register import register_bp
from routes.students import students_bp
import os


# --------------------------------------------------------------------------------------
# App setup
# --------------------------------------------------------------------------------------
app = Flask(__name__)
app.config.from_object(get_config())
app.secret_key = app.config["SECRET_KEY"]

os.makedirs(os.path.dirname(app.config["DB_PATH"]), exist_ok=True)
os.makedirs(app.config["INVOICE_PDF_DIR"], exist_ok=True)

app.register_blueprint(home_bp)
app.register_blueprint(register_bp)
app.register_blueprint(invoices_bp)
app.register_blueprint(students_bp)
app.register_blueprint(lessons_bp)

# Create or upgrade the database. start.sh also imports this module once before gunicorn starts.
with app.app_context():
    init_db()


# Make helpers available in Jinja templates
app.jinja_env.globals["fmt_date_display"] = fmt_date
app.jinja_env.globals["fmt_date"] = fmt_date
app.jinja_env.globals["parse_date_any"] = parse_date_any
app.jinja_env.globals["nz_school_term"] = nz_school_term
app.jinja_env.globals["invoice_number_of"] = invoice_number_of
app.jinja_env.filters["local_time"] = utc_to_local
app.jinja_env.filters["money"] = money
app.jinja_env.filters["todate"] = terms.day
for helper in (fmt_day, fmt_dm, fmt_full, fmt_long):
    app.jinja_env.globals[helper.__name__] = helper


@app.context_processor
def inject_version():
    return {"app_version": app.config["APP_VERSION"][:7]}


@app.route("/health")
def health():
    return "OK", 200


@app.route("/version")
def version():
    return {"version": app.config["APP_VERSION"]}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=app.config["DEBUG"])