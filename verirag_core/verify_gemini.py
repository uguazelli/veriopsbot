import os
import google.generativeai as genai
from dotenv import load_dotenv

def test_key():
    load_dotenv()

    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        print("❌ GOOGLE_API_KEY not found in environment or .env file.")
        return

    print(f"🔑 Key found: {key[:4]}...{key[-4:]}")

    genai.configure(api_key=key)

    try:
        model = genai.GenerativeModel("gemini-2.0-flash-exp")
        # Note: 'gemini-2.0-flash' might be preview, falling back to 1.5 if 2.0 fails
        # but user config says gemini-2.0-flash. Let's try listing models first.

        print("📡 Connecting to Google AI...")
        response = model.generate_content("Hello, this is a test.")
        print("✅ SUCCESS! Gemini responded:")
        print(response.text)

    except Exception as e:
        print("\n❌ API ERROR:")
        print(e)

if __name__ == "__main__":
    test_key()
