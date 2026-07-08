import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Full Gmail access (read + send)
SCOPES = ["https://mail.google.com/"]

CREDENTIALS_FILE = "credentials_sat.json"
TOKEN_FILE = "token_sat.json"


def get_token():

    creds = None

    # Load existing token if present
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(
            TOKEN_FILE,
            SCOPES
        )

    # If token is missing or expired
    if not creds or not creds.valid:

        if creds and creds.expired and creds.refresh_token:

            creds.refresh(Request())

        else:

            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE,
                SCOPES
            )

            # Opens browser for Google login
            creds = flow.run_local_server(port=0)

        # Save new token
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    print("✅ token_sat.json created successfully!")


if __name__ == "__main__":
    get_token()