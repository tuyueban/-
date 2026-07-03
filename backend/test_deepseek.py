import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("AI_API_KEY")
api_base = os.getenv("AI_API_BASE")
model = os.getenv("AI_MODEL", "deepseek-v4-flash")

print("API_BASE:", api_base)
print("MODEL:", model)
print("KEY_PREFIX:", api_key[:8] if api_key else "None")

client = OpenAI(
    api_key=api_key,
    base_url=api_base,
)

response = client.chat.completions.create(
    model=model,
    messages=[
        {"role": "user", "content": "你好，请回复：接口正常"}
    ],
    stream=False,
)

print(response.choices[0].message.content)