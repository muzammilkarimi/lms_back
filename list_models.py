import os
import json
from urllib import request
from dotenv import load_dotenv

load_dotenv()

def list_models():
    api_key = os.getenv("GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    
    try:
        req = request.Request(url)
        with request.urlopen(req) as res:
            data = json.loads(res.read().decode("utf-8"))
            print("AVAILABLE MODELS:")
            for m in data.get("models", []):
                print(f"- {m['name']}")
    except Exception as e:
        print(f"Error listing models: {e}")

if __name__ == "__main__":
    list_models()
