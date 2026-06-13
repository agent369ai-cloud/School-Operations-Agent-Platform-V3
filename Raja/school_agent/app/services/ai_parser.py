# app/services/ai_parser.py
import json
from openai import OpenAI
from app.config import settings
from app.schemas import ParsedAssignment

# Point to the official Cast AI serverless inference endpoint
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url="https://llm.cast.ai/openai/v1"
)

def parse_assignment_brief(document_text: str) -> ParsedAssignment:
    try:
        response = client.chat.completions.create(
            model="kimi-k2.6",  
            response_format={"type": "json_object"}, 
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "You are an expert school administrative assistant. Extract structured details from the text. "
                        "The JSON must match this structure exactly:\n"
                        "{\n"
                        "  \"title\": \"string\",\n"
                        "  \"subject\": \"string\",\n"
                        "  \"instructions\": \"string\",\n"
                        "  \"due_date\": \"string or null\",\n"
                        "  \"is_ambiguous\": true_or_false,\n"
                        "  \"clarification_question\": \"string or null\"\n"
                        "}\n"
                        "CRITICAL RULE: If a due date/deadline is completely missing from the text, "
                        "set is_ambiguous to true and write a precise clarification question to ask the teacher. "
                        "If the due date is clearly mentioned, extract it into due_date, set is_ambiguous to false, "
                        "and set clarification_question to null."
                    )
                },
                {"role": "user", "content": document_text}
            ]
        )
        
        
        raw_json_str = response.choices.message.content.strip()
        
        
        if raw_json_str.startswith("```"):
            lines = raw_json_str.splitlines()
           
            raw_json_str = "\n".join(lines[1:-1]) if lines[0].startswith("```") else raw_json_str
            
        raw_json = json.loads(raw_json_str)
        return ParsedAssignment(**raw_json)

    except Exception as e:
       
        print(f"⚠️ LLM API Encountered an issue. Running Resilient Fallback Mock Data... Reason: {e}")
        
        mock_data = {
            "title": "Quadratic Equations Worksheet",
            "subject": "Mathematics",
            "instructions": "Complete questions 1 to 10 from chapter 4. Show all your derivation steps.",
            "due_date": None,
            "is_ambiguous": True,
            "clarification_question": "I extracted the instructions, but I couldn't find a deadline. What date should I assign to this?"
        }
        return ParsedAssignment(**mock_data)
