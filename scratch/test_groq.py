import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
print(f"API Key: {api_key[:5]}...")

try:
    llm = ChatGroq(model="llama3-70b-8192", groq_api_key=api_key)
    res = llm.invoke("Hello, respond with 'OK'")
    print(f"Result: {res.content}")
except Exception as e:
    print(f"Error: {e}")
