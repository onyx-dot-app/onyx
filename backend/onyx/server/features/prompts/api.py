from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, List, Optional
from pydantic import BaseModel, RootModel
from sqlalchemy.orm import Session

from onyx.prompts.agent_search import (
    ASSISTANT_SYSTEM_PROMPT_DEFAULT,
    ASSISTANT_SYSTEM_PROMPT_PERSONA,
    COMMON_RAG_RULES,
    DOCUMENT_VERIFICATION_PROMPT,
    ENTITY_TERM_EXTRACTION_PROMPT,
    ENTITY_TERM_EXTRACTION_PROMPT_JSON_EXAMPLE,
    HISTORY_CONTEXT_SUMMARY_PROMPT,
    INITIAL_ANSWER_PROMPT_W_SUB_QUESTIONS,
    INITIAL_ANSWER_PROMPT_WO_SUB_QUESTIONS,
    INITIAL_DECOMPOSITION_PROMPT_QUESTIONS_AFTER_SEARCH,
    INITIAL_DECOMPOSITION_PROMPT_QUESTIONS_AFTER_SEARCH_ASSUMING_REFINEMENT,
    INITIAL_QUESTION_DECOMPOSITION_PROMPT,
    INITIAL_QUESTION_DECOMPOSITION_PROMPT_ASSUMING_REFINEMENT,
    INITIAL_REFINED_ANSWER_COMPARISON_PROMPT,
    QUERY_REWRITING_PROMPT,
    REFINEMENT_QUESTION_DECOMPOSITION_PROMPT,
    SUB_ANSWER_CHECK_PROMPT,
    SUB_QUESTION_ANSWER_TEMPLATE,
    SUB_QUESTION_ANSWER_TEMPLATE_REFINED,
    SUB_QUESTION_RAG_PROMPT,
)

from onyx.auth.users import current_user
from onyx.db.engine import get_session
from onyx.db.models import SystemPrompt, User
from sqlalchemy import select

router = APIRouter(prefix="/prompts", tags=["prompts"])

# Create a dictionary mapping prompt names to their templates
# This will be populated from the database at startup
PROMPT_MAP = {
    "assistant_system_prompt_default": ASSISTANT_SYSTEM_PROMPT_DEFAULT,
    "assistant_system_prompt_persona": ASSISTANT_SYSTEM_PROMPT_PERSONA,
    "common_rag_rules": COMMON_RAG_RULES,
    "document_verification_prompt": DOCUMENT_VERIFICATION_PROMPT,
    "entity_term_extraction_prompt": ENTITY_TERM_EXTRACTION_PROMPT,
    "entity_term_extraction_prompt_json_example": ENTITY_TERM_EXTRACTION_PROMPT_JSON_EXAMPLE,
    "history_context_summary_prompt": HISTORY_CONTEXT_SUMMARY_PROMPT,
    "initial_answer_prompt_with_sub_questions": INITIAL_ANSWER_PROMPT_W_SUB_QUESTIONS,
    "initial_answer_prompt_without_sub_questions": INITIAL_ANSWER_PROMPT_WO_SUB_QUESTIONS,
    "initial_decomposition_prompt_questions_after_search": INITIAL_DECOMPOSITION_PROMPT_QUESTIONS_AFTER_SEARCH,
    "initial_decomposition_prompt_questions_after_search_assuming_refinement": INITIAL_DECOMPOSITION_PROMPT_QUESTIONS_AFTER_SEARCH_ASSUMING_REFINEMENT,
    "initial_question_decomposition_prompt": INITIAL_QUESTION_DECOMPOSITION_PROMPT,
    "initial_question_decomposition_prompt_assuming_refinement": INITIAL_QUESTION_DECOMPOSITION_PROMPT_ASSUMING_REFINEMENT,
    "initial_refined_answer_comparison_prompt": INITIAL_REFINED_ANSWER_COMPARISON_PROMPT,
    "query_rewriting_prompt": QUERY_REWRITING_PROMPT,
    "refinement_question_decomposition_prompt": REFINEMENT_QUESTION_DECOMPOSITION_PROMPT,
    "sub_answer_check_prompt": SUB_ANSWER_CHECK_PROMPT,
    "sub_question_answer_template": SUB_QUESTION_ANSWER_TEMPLATE,
    "sub_question_answer_template_refined": SUB_QUESTION_ANSWER_TEMPLATE_REFINED,
    "sub_question_rag_prompt": SUB_QUESTION_RAG_PROMPT,
}

class PromptTemplate(BaseModel):
    template: str

class PromptUpdate(RootModel):
    root: Dict[str, str]

    @staticmethod
    def validate_prompt_names(prompt_names: List[str], db_session: Session) -> None:
        """Validate that all prompt names exist in the database."""
        stmt = select(SystemPrompt).where(SystemPrompt.name.in_(prompt_names))
        result = db_session.execute(stmt)
        existing_prompts = {prompt.name for prompt in result.scalars().all()}
        
        invalid_names = [name for name in prompt_names if name not in existing_prompts]
        if invalid_names:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid prompt names: {', '.join(invalid_names)}",
            )

def get_system_prompt(prompt_name: str, db_session: Session) -> str:
    """Fetch a system prompt from the database."""
    stmt = select(SystemPrompt).where(SystemPrompt.name == prompt_name)
    result = db_session.execute(stmt)
    db_prompt = result.scalar_one_or_none()
    return db_prompt.contents if db_prompt else None

def get_system_prompts_from_db(db_session: Session) -> Dict[str, str]:
    """Fetch system prompts from the database."""
    stmt = select(SystemPrompt)
    result = db_session.execute(stmt)
    system_prompts = result.scalars().all()
    
    # Convert to dictionary format
    prompt_dict = {}
    for prompt in system_prompts:
        prompt_dict[prompt.name] = prompt.contents
    
    return prompt_dict

@router.get("")
async def list_prompts(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session)
) -> Dict[str, str]:
    """List all available prompts."""
    # Get system prompts from database
    return get_system_prompts_from_db(db_session)

@router.get("/{prompt_name}")
async def get_prompt(
    prompt_name: str, 
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session)
) -> PromptTemplate:
    """Get a specific prompt by name."""
    # First check if it's in the database
    stmt = select(SystemPrompt).where(SystemPrompt.name == prompt_name)
    result = db_session.execute(stmt)
    db_prompt = result.scalar_one_or_none()
    
    if db_prompt:
        return PromptTemplate(template=db_prompt.contents)
    
    # If not in database, check hardcoded prompts
    if prompt_name not in PROMPT_MAP:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_name}' not found")
    
    return PromptTemplate(template=PROMPT_MAP[prompt_name])

@router.post("")
async def update_prompts(
    updates: PromptUpdate, 
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session)
) -> Dict[str, str]:
    """Update multiple prompts at once."""
    # Validate that all prompt names exist
    PromptUpdate.validate_prompt_names(list(updates.root.keys()), db_session=db_session)
    
    # Update the prompts in the database
    for name, content in updates.root.items():
        stmt = select(SystemPrompt).where(SystemPrompt.name == name)
        result = db_session.execute(stmt)
        db_prompt = result.scalar_one_or_none()
        
        if db_prompt:
            # Update existing prompt
            db_prompt.contents = content
        else:
            # Create new prompt
            new_prompt = SystemPrompt(name=name, contents=content)
            db_session.add(new_prompt)
    
    db_session.commit()
    
    # Return updated prompts
    return await list_prompts(user, db_session)
