# from langchain_ollama import ChatOllama
from langgraph.graph import START,StateGraph,END
from typing import TypedDict
from langchain_qwq import ChatQwen
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
import os
from langchain_openai import ChatOpenAI

load_dotenv()
# llm = ChatOllama(
#     model="llama3.2:latest",
#     temperature=0,
#     num_predict=-1
# )

# llm = ChatOpenAI(
#     model="Qwen/Qwen3-4B-MLX-4bit",
#     base_url="http://localhost:8080/v1",
#     api_key="not-needed",
#     temperature=0.2
# )



api_key=os.getenv("GOOGLE_API_KEY")

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
    google_api=api_key
)



def call_llm(query: str):

    res = llm.invoke(query)

    return res.content

# print(call_llm("Hi there"))