from app.llm.groq_provider import GroqProvider

def get_llm(task: str):
    if task == "analysis":
        return GroqProvider(model="openai/gpt-oss-20b")  # rapide

    if task == "evaluation":
        return GroqProvider(model="openai/gpt-oss-120b")  # précis

    if task == "refinement":
        return GroqProvider(model="openai/gpt-oss-120b")  # puissant

    return GroqProvider(model="openai/gpt-oss-20b")  # par défaut