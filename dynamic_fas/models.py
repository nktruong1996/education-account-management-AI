from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QuestionStatus = Literal["missing", "existing", "suggested", "pending_update"]
QuestionType = Literal["text", "textarea", "select"]

class DynamicQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: int = Field(gt=0)
    question_text: str = Field(min_length=1, max_length=500)
    is_required: bool = False
    description: Optional[str] = Field(default=None, max_length=1000)
    type: QuestionType = "textarea"
    options: List[str] = Field(default_factory=list, max_length=100)

    @field_validator("question_text")
    @classmethod
    def normalize_question_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]) -> Optional[str]:
        normalized = value.strip() if value else ""
        return normalized or None

    @field_validator("options")
    @classmethod
    def normalize_options(cls, options: List[str]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for option in options:
            value = option.strip()
            key = value.casefold()
            if value and key not in seen:
                normalized.append(value)
                seen.add(key)
        return normalized

    @model_validator(mode="after")
    def validate_select_options(self):
        if self.type == "select" and not self.options:
            raise ValueError("select questions must define at least one option")
        if self.type != "select" and self.options:
            self.options = []
        return self

class DynamicChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=200)
    fas_scheme_id: int = Field(gt=0)
    message: str = Field(min_length=1, max_length=4000)
    questions: List[DynamicQuestion] = Field(default_factory=list, max_length=100)
    current_answers: Dict[str, str] = Field(default_factory=dict)

    @field_validator("session_id", "message")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("current_answers")
    @classmethod
    def normalize_answers(cls, answers: Dict[str, str]) -> Dict[str, str]:
        return {
            str(question_id): value.strip()
            for question_id, value in answers.items()
            if isinstance(value, str)
        }

    @model_validator(mode="after")
    def validate_unique_questions(self):
        question_ids = [question.question_id for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("question_id must be unique within a FAS scheme")
        return self

class DynamicResetSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=200)

    @field_validator("session_id")
    @classmethod
    def normalize_session_id(cls, value: str) -> str:
        return value.strip()

class DynamicQuestionState(BaseModel):
    question_id: int
    question_text: str
    is_required: bool
    description: Optional[str] = None
    type: QuestionType = "textarea"
    options: List[str] = Field(default_factory=list)
    value: Optional[str] = None
    pending_value: Optional[str] = None
    status: QuestionStatus = "missing"
    source: Optional[str] = None

class DynamicAssistantState(BaseModel):
    fas_scheme_id: int
    questions: Dict[str, DynamicQuestionState] = Field(default_factory=dict)
    question_order: List[str] = Field(default_factory=list)
    pending_question_id: Optional[int] = None
    pending_update_question_id: Optional[int] = None

class DynamicProgress(BaseModel):
    completed: int
    total: int
    required_question_ids: List[int]

class DynamicChatResponse(BaseModel):
    reply: str
    assistant_state: DynamicAssistantState
    suggested_fields: Dict[str, str]
    progress: DynamicProgress
