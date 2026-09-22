import requests
import time
import json

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

PROMPT = """You are an AI recruitment assistant. Based on this candidate summary, return ONLY valid JSON.

Candidate: Bachelor's degree in Computer Science, 3 years experience in software development, strong in Python and databases.
Position: ICT Officer, Civil Service Commission.

Return this exact JSON shape:
{
  "decision": "Highly Recommended" | "Recommended" | "Consider" | "Not Recommended",
  "overall_score": 0-100,
  "confidence": 0-100,
  "reasoning": ["short reason 1", "short reason 2"]
}
"""

def run(model_name):
    start = time.time()
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": model_name,
            "prompt": PROMPT,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1}
        }, timeout=120)
        r.raise_for_status()
        elapsed = round(time.time() - start, 2)
        raw = r.json().get("response", "")
        try:
            parsed = json.loads(raw)
            valid = True
        except Exception:
            parsed = None
            valid = False
        return {"model": model_name, "time_sec": elapsed, "json_valid": valid, "raw": raw, "parsed": parsed}
    except Exception as e:
        return {"model": model_name, "error": str(e)}

for model in ["gemma3:4b", "qwen3.6:latest"]:
    print(f"\n{'='*60}\nMODEL: {model}\n{'='*60}")
    result = run(model)
    print(json.dumps(result, indent=2, ensure_ascii=False))