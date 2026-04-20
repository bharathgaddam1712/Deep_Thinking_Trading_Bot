import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
print(f"API Key: {api_key[:5]}...")

try:
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=api_key)
    res = llm.invoke("Hello, respond with 'OK'")
    print(f"Result: {res.content}")
except Exception as e:
    print(f"Error: {e}")
