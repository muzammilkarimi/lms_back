import os
import json
from urllib import request
from dotenv import load_dotenv

load_dotenv()

def test_gemini():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ ERROR: No GEMINI_API_KEY found in .env")
        return

    print(f"Testing API Key: {api_key[:4]}...{api_key[-4:]}")
    
    prompt = "Say 'Gemini is working' if you can read this."
    
    versions = ["v1", "v1beta"]
    models = ["gemini-1.5-flash", "gemini-pro"]
    
    success = False
    for version in versions:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/{version}/models/{model}:generateContent?key={api_key}"
            body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
            
            print(f"Trying {version}/{model}...")
            try:
                req = request.Request(url, data=body, headers={"Content-Type": "application/json"})
                with request.urlopen(req, timeout=10) as res:
                    data = json.loads(res.read().decode("utf-8"))
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    print(f"✅ SUCCESS ({version}/{model}): {text.strip()}")
                    success = True
                    break
            except Exception as e:
                print(f"❌ FAILED ({version}/{model}): {str(e)}")
        if success: break

    if not success:
        print("\n--- TROUBLESHOOTING ---")
        print("1. Go to https://aistudio.google.com/app/apikey")
        print("2. Ensure your API key is active.")
        print("3. Ensure 'Generative Language API' is enabled in your Google Cloud Project.")

if __name__ == "__main__":
    test_gemini()
