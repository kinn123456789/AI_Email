from gmail_watch import register_watch

TOKENS = [
    "token_support.json",
    "token_lucy.json",
    "token_engineering.json",
]

for token in TOKENS:
    try:
        register_watch(token)
    except Exception as e:
        print(f"Failed: {token}")
        print(e)