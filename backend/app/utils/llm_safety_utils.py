import json
import re

def safe_json_parse(text: str, fallback: dict = None) -> dict:
    """Parse LLM output to JSON with aggressive cleanup."""
    if not text:
        return fallback or None
    try:
        text = re.sub(r"```json|```", "", text).strip()

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return fallback or None

        cleaned = text[start : end + 1]

        cleaned = re.sub(r",\s*}", "}", cleaned)
        cleaned = re.sub(r",\s*]", "]", cleaned)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            cleaned = cleaned.replace(": True", ": true")
            cleaned = cleaned.replace(":True", ": true")
            cleaned = cleaned.replace(": False", ": false")
            cleaned = cleaned.replace(":False", ": false")
            cleaned = cleaned.replace(": None", ": null")
            cleaned = cleaned.replace(":None", ": null")

            cleaned = re.sub(
                r'(?<=": ")(.*?)(?=")',
                lambda m: m.group(0).replace("\n", "\\n"),
                cleaned,
                flags=re.DOTALL,
            )

            cleaned = re.sub(r"(?<!\\)'", '"', cleaned)
            cleaned = re.sub(r"(\{|,)\s*(\w+)\s*:", r'\1 "\2":', cleaned)

            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError as e:
                print(f"[JSON PARSE ERROR] {str(e)[:120]}")
                print(f"[JSON RAW SNIPPET] {cleaned[:200]}")
                return fallback or None

        if isinstance(parsed, dict):
            if fallback:
                return {**fallback, **parsed}
            return parsed
        return fallback or None

    except Exception as e:
        print(f"[JSON PARSE ERROR] {e}")
        return fallback or None

   
def is_llm_failed(response: str) -> bool:
    if not response:
        return True

    lowered = response.lower()

    return any(keyword in lowered for keyword in [
        "llm failure",
        "quota exceeded",
        "rate limit",
        "resourceexhausted",
        "429",
    ])

def safe_float(value, default=0.0):
    """
    Safely cast a value to float.
    Prevents crashes if LLM returns invalid data.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
  