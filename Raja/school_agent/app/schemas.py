# app/schemas.py
from typing import List, Optional
from pydantic import BaseModel, Field

class ParsedAssignment(BaseModel):
    title: str = Field(description="The extracted title of the assignment")
    subject: str = Field(description="School subject, e.g., Math, Science")
    instructions: str = Field(description="Step by step instructions for the student")
    due_date: Optional[str] = Field(None, description="ISO format due date if present")
    
    # Crucial for the "Ask, Don't Guess" requirement
    is_ambiguous: bool = Field(description="Set to True if critical data like due date is missing")
    clarification_question: Optional[str] = Field(None, description="The explicit question to ask the teacher if ambiguous")

# app/services/ai_parser.py
from openai import OpenAI
from app.config import settings
from app.schemas import ParsedAssignment

client = OpenAI(api_key=settings.OPENAI_API_KEY)

def parse_assignment_brief(document_text: str) -> ParsedAssignment:
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-mini",  # Fast and highly reliable for structured outputs
        messages=[
            {"role": "system", "content": "You are an expert school administrative assistant. Extract structured details from the text. If a due date or clear target group is completely missing, flag it as ambiguous and formulate a precise question to ask the teacher."},
            {"role": "user", "content": document_text}
        ],
        response_format=ParsedAssignment,
    )
    return completion.choices[0].message.parsed
