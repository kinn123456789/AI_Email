from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "credentials.json",
    scopes=["https://mail.google.com/"]
)

creds = flow.run_local_server(port=0)

with open("token_engineering.json", "w") as token:
    token.write(creds.to_json())

print("✅ token_engineering.json created successfully")