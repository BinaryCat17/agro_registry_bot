import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini/gemini-3.1-flash-lite")  # под LiteLLM

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
USER_PROMPT_FILE = CONFIG_DIR / "user_promt.txt"
SYSTEM_PROMPT_FILE = CONFIG_DIR / "system_promt.txt"

current_user_prompt = ""
current_system_prompt = ""

def load_prompts():
    global current_user_prompt, current_system_prompt
    if USER_PROMPT_FILE.exists():
        current_user_prompt = USER_PROMPT_FILE.read_text(encoding="utf-8").strip()
    else:
        current_user_prompt = "Ты полезный помощник по реестру пестицидов."
    if SYSTEM_PROMPT_FILE.exists():
        current_system_prompt = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    else:
        current_system_prompt = "You are an AI Agent with tools."
