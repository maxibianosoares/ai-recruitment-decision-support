import json

from .llm_service import generate_json


DEFAULT_REPORT = {
    "decision": "",
    "confidence": 0,
    "reasoning": [],
    "risks": [],
    "recommendation": ""
}


def generate_explainable_report(
    profile,
    job_profile,
    rule_result,
    semantic_result,
    gap_result
):

    prompt = f"""
You are a senior HR recruitment expert.

Review all recruitment evidence below and make the final hiring recommendation.

Candidate Profile

{json.dumps(profile, indent=2)}

Job Profile

{json.dumps(job_profile, indent=2)}

Rule-Based Evaluation

{json.dumps(rule_result, indent=2)}

Semantic Matching

{json.dumps(semantic_result, indent=2)}

Skill Gap Analysis

{json.dumps(gap_result, indent=2)}

Return ONLY JSON.

Schema:

{{
    "decision":"",
    "confidence":0,
    "reasoning":[],
    "risks":[],
    "recommendation":""
}}

Decision must be one of:

- Highly Recommended
- Recommended
- Consider
- Not Recommended
"""
    return generate_json(
    prompt=prompt,
    default=DEFAULT_REPORT
)