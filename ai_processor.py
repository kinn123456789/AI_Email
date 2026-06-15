import requests

TOKEN = "eyJhbGciOiJIUzI1NiIsImtpZCI6Ik84RUlWd3c5UmI2d2VMaEUiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL2t3aHB6aHZjc25lenZ0cG9xbWhqLnN1cGFiYXNlLmNvL2F1dGgvdjEiLCJzdWIiOiI5ODAwYzg0OC1lZWRmLTQ4MmUtODlmYi1kMTZhYjNmODZmMTciLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzgxNTIwMzA2LCJpYXQiOjE3ODE1MTY3MDYsImVtYWlsIjoieWFzaG9kaGFuQGNvcmFsYWNhZGVteS5jb20iLCJwaG9uZSI6IiIsImFwcF9tZXRhZGF0YSI6eyJwcm92aWRlciI6ImVtYWlsIiwicHJvdmlkZXJzIjpbImVtYWlsIiwiZ29vZ2xlIl19LCJ1c2VyX21ldGFkYXRhIjp7ImN1c3RvbV9jbGFpbXMiOnsiaGQiOiJjb3JhbGFjYWRlbXkuY29tIn0sImVtYWlsIjoieWFzaG9kaGFuQGNvcmFsYWNhZGVteS5jb20iLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwiZnVsbF9uYW1lIjoiWWFzaG9kaGFuIEJoYXRhd2Rla2FyIiwiaXNfcHJlbGF1bmNoIjp0cnVlLCJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJuYW1lIjoiWWFzaG9kaGFuIEJoYXRhd2Rla2FyIiwicGhvbmVfdmVyaWZpZWQiOmZhbHNlLCJwcm92aWRlcl9pZCI6IjExMzIxNTc2ODcwNTkxNTE5NjExOSIsInN1YiI6IjExMzIxNTc2ODcwNTkxNTE5NjExOSJ9LCJyb2xlIjoiYXV0aGVudGljYXRlZCIsImFhbCI6ImFhbDEiLCJhbXIiOlt7Im1ldGhvZCI6Im90cCIsInRpbWVzdGFtcCI6MTc4MTE4ODc5OH1dLCJzZXNzaW9uX2lkIjoiY2QzODM0ZmYtNTUxMC00ZmMwLThkYzYtZGZiMmM5YjM5NjRhIiwiaXNfYW5vbnltb3VzIjpmYWxzZX0.tzUR5y_0-9YXzZRWJ2x5QiGJLWMZxdnCY2z3LSjzP7g"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Ca-Id": "0af796a6-e7fd-4537-a67a-94d5292e1b91",
    "Website-Base-Url": "https://www.preprod.coralacademy.com",
    "Origin": "https://www.preprod.coralacademy.com",
    "Referer": "https://www.preprod.coralacademy.com/",
    "Content-Type": "application/json"
}

response = requests.post(
    "https://api.preprod.coralacademy.com/chats/0e3583ec-47ce-4fca-866c-f423bbdc3ae1/messages",
    headers=headers,
    json={
        "text": "Hello"
    }
)

print("STATUS:", response.status_code)
print("RESPONSE:", response.text)