from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from app.config import GEMINI_API_KEY, GROQ_API_KEY


llm_gemini = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.7,
    top_p=0.9,
    google_api_key=GEMINI_API_KEY
)

llm_groq = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0.7,
    api_key=GROQ_API_KEY
)

llm_rapido = ChatGroq(
    model="qwen/qwen3.8-27b",
    temperature=0.0,
    reasoning_format="hidden",
    max_tokens=100,
    api_key=GROQ_API_KEY
)


llm_especialista = llm_gemini.with_fallbacks([llm_groq])