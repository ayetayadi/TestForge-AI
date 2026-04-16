import requests
from app.core.config import settings

API_KEY = settings.GROQ_API_KEY

url = "https://api.groq.com/openai/v1/chat/completions"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

data = {
    "model": "openai/gpt-oss-20b",
    "messages": [
        {"role": "user", "content": "Say hello"}
    ],
    "temperature": 0.2
}

response = requests.post(url, headers=headers, json=data)

print("STATUS:", response.status_code)
print("RAW:", response.text)