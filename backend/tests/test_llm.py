import requests
from app.core.config import settings

API_KEY = settings.OPENROUTER_API_KEY

url = "https://openrouter.ai/api/v1/chat/completions"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

data = {
    "model": "openai/gpt-4o-mini",
    "messages": [
        {"role": "user", "content": "Say hello"}
    ],
    "temperature": 0.2
}

response = requests.post(url, headers=headers, json=data)

print("STATUS:", response.status_code)
print("RAW:", response.text)