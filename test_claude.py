from ai_engine.services.llm_service import generate_json


result = generate_json(
    prompt="""
Return ONLY valid JSON.

{
    "status": "success",
    "message": "Claude is working"
}
"""
)

print("====================================")
print("CLAUDE TEST")
print("====================================")
print(result)
print("====================================")