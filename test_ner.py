print("DEBUT")
import os
from dotenv import load_dotenv
load_dotenv()

from langchain_groq import ChatGroq
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0
)
resp = llm.invoke('Respond only with: {"test": "ok"}')
print("REPONSE:", resp.content)
print("FIN")