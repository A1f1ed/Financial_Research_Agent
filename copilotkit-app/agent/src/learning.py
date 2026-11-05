"""Published skill delivery; the FastAPI lifespan owns the async client."""

import os
from copilotkit_intelligence_langgraph import create_skill_registry_middleware

skills = (
    create_skill_registry_middleware()
    if os.getenv("CPK_INTELLIGENCE_API_KEY")
    and os.getenv("CPK_INTELLIGENCE_LEARNING_CONTAINER_ID")
    else None
)
