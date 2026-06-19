import requests

# 1. DEFINE the payload (the data you want to send)
payload = {
    "name": "Your Name",
    "email": "yourname@example.com",
    "phone_number": "+1222222222",
    "message": "This is a test message from my script."
}

# 2. NOW you can use it in the request
response = requests.post(
    "https://api.preprod.coralacademy.com/submit-enquiry",
    json=payload
)

# 3. Handle the response
print(f"Status Code: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    print("Success! Response data:")
    print(data)
else:
    print("Failed to submit.")
    print(f"Response text: {response.text}")