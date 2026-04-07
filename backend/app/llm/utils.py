from app.utils.llm_safety_utils import safe_json_parse
from app.llm.schemas import AnalysisResult, EvaluationResult, RefinementResult
from app.llm.fallbacks import FALLBACKS


def parse_and_validate(task: str, response):

    if isinstance(response, str):
        parsed = safe_json_parse(response, None)
    elif isinstance(response, dict):
        parsed = response
    else:
        return FALLBACKS.get(task)

    try:
        if task == "analysis":
            return AnalysisResult(**parsed).dict()

        elif task == "evaluation":
            return EvaluationResult(**parsed).dict()

        elif task == "refinement":
            return RefinementResult(**parsed).dict()

    except Exception:
        return FALLBACKS.get(task)

    return FALLBACKS.get(task)