from app.llm.smart_llm import SmartLLM

_llm_cache = {}

def get_llm(task: str = "default"):
    if task not in _llm_cache:
        _llm_cache[task] = SmartLLM(task=task)
    return _llm_cache[task]