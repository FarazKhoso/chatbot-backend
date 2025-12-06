import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

# Configure the API key
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable is not set")

genai.configure(api_key=api_key)

# Get the model
model = genai.GenerativeModel('gemini-2.0-flash')

def generate_response(prompt: str, instructions: str = ""):
    """
    Generate response from the Gemini model
    """
    try:
        # Combine instructions with the user prompt
        full_prompt = f"{instructions}\n\nUser: {prompt}" if instructions else prompt
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        return f"Error generating response: {str(e)}"

# Create a simple model interface that matches your original code
class GeminiModel:
    def __init__(self):
        self.model_name = 'gemini-2.0-flash'
    
    def generate_response(self, prompt: str, instructions: str = ""):
        return generate_response(prompt, instructions)

# Create an instance that can be used
gemini_model = GeminiModel()