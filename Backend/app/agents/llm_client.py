"""
Single place every agent (Investigation, Decision, Verification --
Phase 12/15/20) gets its LLM instance from, so the model/provider is
never hardcoded in multiple places.

IMPORTANT: I cannot make a live call to Groq's API from the sandbox
this was built in (no network access to api.groq.com there), so this
wrapper is written carefully against Groq's documented, OpenAI-compatible
API shape but has NOT been tested end-to-end against a real API key.
Run test_llm_connection() below once you have GROQ_API_KEY set to
confirm it actually works before building Phase 12 on top of it.
"""
from langchain_groq import ChatGroq

from app.config import settings


def get_llm(temperature: float = 0.0, max_tokens: int = 1024) -> ChatGroq:
    """
    temperature=0.0 by default: investigation/decision agents should be
    as deterministic and repeatable as possible for the same evidence --
    this is a diagnostic tool, not a creative one. Override for cases
    where more varied phrasing is actually desirable (e.g. explanatory
    text in Phase 16's OR-Tools result summaries).
    """
    if not settings.GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to your .env file -- get one at https://console.groq.com/keys"
        )

    return ChatGroq(
        model=settings.GROQ_MODEL,
        api_key=settings.GROQ_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=30,      # guardrail: don't let one slow call hang an incident investigation forever
        max_retries=2,
    )


def test_llm_connection() -> dict:
    """
    Quick sanity check you can run manually once you have a real API key:

        python -c "from app.agents.llm_client import test_llm_connection; print(test_llm_connection())"

    Not run automatically anywhere -- costs a real API call.
    """
    llm = get_llm()
    response = llm.invoke("Reply with exactly the word: OK")
    return {"model": settings.GROQ_MODEL, "response": response.content}