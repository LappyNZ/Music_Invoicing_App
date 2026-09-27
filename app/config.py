import os


def as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class BaseConfig:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
    DEBUG = as_bool(os.getenv("FLASK_DEBUG"), False)

    DB_PATH = os.getenv("DB_PATH", "/data/music_school.db")
    INVOICE_PDF_DIR = os.getenv("INVOICE_PDF_DIR", "/data/invoices_pdfs")

    SENDER_EMAIL = os.getenv("SENDER_EMAIL", "example@example.com")
    SENDER_NAME = os.getenv("SENDER_NAME", "Your Name")
    BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Your Business Name")
    BUSINESS_ADDRESS_LINE1 = os.getenv("BUSINESS_ADDRESS_LINE1", "123 Example Street")
    BUSINESS_ADDRESS_LINE2 = os.getenv("BUSINESS_ADDRESS_LINE2", "Example City")
    BUSINESS_PHONE = os.getenv("BUSINESS_PHONE", "000 000 0000")
    BUSINESS_MOBILE = os.getenv("BUSINESS_MOBILE", "000 000 0000")
    BANK_ACCOUNT = os.getenv("BANK_ACCOUNT", "00-0000-0000000-000")

    SECRETS_DIR = os.getenv("SECRETS_DIR", "/secrets")
    GOOGLE_OAUTH_CREDENTIALS = os.getenv("GOOGLE_OAUTH_CREDENTIALS", "/secrets/credentials.json")
    GOOGLE_OAUTH_TOKEN = os.getenv("GOOGLE_OAUTH_TOKEN", "/secrets/token.json")
    OAUTH_PORT = int(os.getenv("OAUTH_PORT", "8090"))

    APP_ENV = os.getenv("APP_ENV", "production")
    APP_VERSION = os.getenv("APP_VERSION", "dev")  # git commit, set when the Docker image is built
    EMAIL_ENABLED = as_bool(os.getenv("EMAIL_ENABLED"), True)
    EMAIL_REDIRECT_TO = os.getenv("EMAIL_REDIRECT_TO", "")
    SAFE_MODE = as_bool(os.getenv("SAFE_MODE"), False)

    STATIC_DIR = "static"
    LOGO_FILE = "logo_Small.png"

class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    DEBUG = False


def get_config():
    env = os.getenv("APP_ENV", "production").lower()
    if env == "development":
        return DevelopmentConfig
    return ProductionConfig