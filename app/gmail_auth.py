"""Connect the app to Gmail, or connect it again after Google has signed it out.

Run it inside the container and follow the instructions:

    docker exec -it music-invoice python -m gmail_auth

It prints a Google sign-in link to open on any computer or phone. After you allow access, Google
sends the browser to an address on "localhost" that doesn't load; copy that address back here.
"""
import os
import sys
from urllib.parse import parse_qs, urlparse

from google_auth_oauthlib.flow import InstalledAppFlow

from config import get_config
from services.email_service import GMAIL_SCOPES


def main(ask=input):
    config = get_config()
    if not os.path.exists(config.GOOGLE_OAUTH_CREDENTIALS):
        print(f"Can't find the app's Google credentials at {config.GOOGLE_OAUTH_CREDENTIALS}.")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(
        config.GOOGLE_OAUTH_CREDENTIALS, GMAIL_SCOPES, redirect_uri=f"http://localhost:{config.OAUTH_PORT}/")
    url, state = flow.authorization_url(access_type="offline", prompt="consent")

    print(f"1. Open this link in a web browser and sign in as {config.SENDER_EMAIL}:\n\n{url}\n")
    print("2. Allow the app to send email. The browser then shows an error such as \"This site can't be")
    print("   reached\". That's expected.")
    print("3. Copy the whole address from the browser's address bar, paste it here and press Enter.\n")
    query = parse_qs(urlparse(ask("Address: ").strip()).query)

    if "code" not in query:
        print("\nThat address doesn't contain Google's answer"
              + (f" ({query['error'][0]})" if "error" in query else "") + ". Nothing was changed; run this again.")
        return 1
    if query.get("state") != [state]:
        print("\nThat address is from a different attempt. Nothing was changed; run this again.")
        return 1

    flow.fetch_token(code=query["code"][0])
    with open(config.GOOGLE_OAUTH_TOKEN, "w") as token:
        token.write(flow.credentials.to_json())
    print("\nGmail is connected. You can send invoices again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
