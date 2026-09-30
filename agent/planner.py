"""Planner module for the autonomous bug-fixing agent.

Role: Planner (Architect & Root-Cause Analyst)
- Fresh conversation context (no shared state with executor/reviewer).
- Synthesizes bug report and AST-retrieved code chunks.
- Identifies root cause and specifies exact step-by-step repair plan.
"""

import os
from typing import Dict, List, Any, Optional

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None
    genai_types = None

import config
from agent.state import AgentState, CodeContextItem

PLANNER_SYSTEM_PROMPT = """You are an elite Senior Staff Engineer specializing in root cause analysis and software debugging.

Your objective:
Analyze the user's natural language bug report together with the provided AST-retrieved codebase chunks.
Formulate a precise, step-by-step repair plan that addresses the root cause directly while avoiding scope creep.

Requirements:
1. Identify the root cause of the bug from the code snippets.
2. Specify the exact file path(s) and function/class names that require modification.
3. Detail the exact logic change needed (e.g. condition fix, header injection, off-by-one correction, null check).
4. Outline the verification expectations (which tests should pass).
5. Keep the plan strictly scoped to the reported issue. Do NOT refactor surrounding unrelated code.
"""


def _format_context_for_prompt(retrieved_files: List[CodeContextItem]) -> str:
    """Format retrieved AST chunks into readable prompt context."""
    if not retrieved_files:
        return "(No code context retrieved)"

    parts = []
    for idx, item in enumerate(retrieved_files, 1):
        parts.append(
            f"--- Snippet #{idx}: {item['file_path']} "
            f"({item['chunk_type']}: {item['name']}, Lines {item['start_line']}-{item['end_line']}) ---\n"
            f"{item['content']}\n"
        )
    return "\n".join(parts)


def generate_plan_claude(
    bug_report: str,
    retrieved_files: List[CodeContextItem],
    api_key: str,
    model: str = config.PLANNER_MODEL
) -> str:
    """Invoke Claude Anthropic API with dedicated Planner persona."""
    client = anthropic.Anthropic(api_key=api_key)
    context_text = _format_context_for_prompt(retrieved_files)

    user_message = f"""### Bug Report:
{bug_report.strip()}

### Retrieved Codebase Snippets:
{context_text}

Formulate your root cause diagnosis and step-by-step fix plan now:"""

    response = client.messages.create(
        model=model,
        max_tokens=1500,
        temperature=0.0,
        system=PLANNER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}]
    )

    return response.content[0].text


def generate_plan_gemini(
    bug_report: str,
    retrieved_files: List[CodeContextItem],
    api_key: str,
    model: str = config.PLANNER_MODEL
) -> str:
    """Invoke Google Gemini API with dedicated Planner persona."""
    client = genai.Client(api_key=api_key)
    context_text = _format_context_for_prompt(retrieved_files)

    user_message = f"""### Bug Report:
{bug_report.strip()}

### Retrieved Codebase Snippets:
{context_text}

Formulate your root cause diagnosis and step-by-step fix plan now:"""

    response = client.models.generate_content(
        model=model,
        contents=user_message,
        config=genai_types.GenerateContentConfig(
            system_instruction=PLANNER_SYSTEM_PROMPT,
            temperature=0.0,
            max_output_tokens=2000,
        )
    )
    return response.text


def generate_plan_mock(
    bug_report: str,
    retrieved_files: List[CodeContextItem]
) -> str:
    """Fallback deterministic planner for offline development and demonstration."""
    top_file = retrieved_files[0]["file_path"] if retrieved_files else "unknown"
    top_symbol = retrieved_files[0]["name"] if retrieved_files else "unknown"

    lower_report = bug_report.lower()
    
    if "cart" in lower_report or "off-by-one" in lower_report:
        return (
            "### Root Cause Diagnosis:\n"
            f"In `{top_file}` within `{top_symbol}`, when updating an item's quantity, "
            "the method adds 1 extra to `new_quantity` (`self.items[item_id] = new_quantity + 1`).\n\n"
            "### Step-by-Step Fix Plan:\n"
            f"1. Target File: `{top_file}`\n"
            f"2. Method: `{top_symbol}`\n"
            "3. Change: Replace `self.items[item_id] = new_quantity + 1` with `self.items[item_id] = new_quantity`.\n"
            "4. Verification: Run `pytest tests/test_cart.py` and confirm exact quantity assertion succeeds."
        )
    elif "jwt" in lower_report or "logged out" in lower_report or "cookie" in lower_report:
        return (
            "### Root Cause Diagnosis:\n"
            f"In `{top_file}` within `{top_symbol}`, the method only inspects the 'access_token' cookie key, "
            "ignoring 'auth_jwt' sent by the browser on page refresh.\n\n"
            "### Step-by-Step Fix Plan:\n"
            f"1. Target File: `{top_file}`\n"
            f"2. Method: `{top_symbol}`\n"
            "3. Change: Check for 'auth_jwt' in addition to 'access_token'.\n"
            "4. Verification: Run `pytest tests/test_auth.py` to confirm session persistence."
        )
    elif "api" in lower_report or "header" in lower_report or "endpoint" in lower_report:
        return (
            "### Root Cause Diagnosis:\n"
            f"In `{top_file}`, the API client points to deprecated `/v1/order/` and omits the Authorization header.\n\n"
            "### Step-by-Step Fix Plan:\n"
            f"1. Target File: `{top_file}`\n"
            "2. Update endpoint path to `/api/v2/orders/`.\n"
            "3. Add Authorization: Bearer <token> header when token is present.\n"
            "4. Verification: Run `pytest tests/test_api_client.py`."
        )
    elif "empty checkout" in lower_report or "null" in lower_report:
        return (
            "### Root Cause Diagnosis:\n"
            f"In `{top_file}` within `{top_symbol}`, accessing `list(cart.items.keys())[0]` crashes on empty cart.\n\n"
            "### Step-by-Step Fix Plan:\n"
            f"1. Target File: `{top_file}`\n"
            "2. Guard against empty cart items (`if not cart.items: return 0.0`).\n"
            "3. Verification: Run `pytest tests/test_checkout.py`."
        )

    return (
        f"### Diagnostic Plan for: {bug_report}\n"
        f"1. Analyze primary module: `{top_file}` ({top_symbol})\n"
        "2. Apply targeted bug patch addressing the issue.\n"
        "3. Run automated tests to verify."
    )


def plan_node(state: AgentState) -> Dict[str, Any]:
    """LangGraph node execution for the Planner role.
    
    Args:
        state: Current AgentState.
        
    Returns:
        State update dictionary containing 'plan' and updated 'history'.
    """
    bug_report = state["bug_report"]
    retrieved_files = state.get("retrieved_files", [])

    gemini_key = os.environ.get("GEMINI_API_KEY", config.GEMINI_API_KEY).strip()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", config.ANTHROPIC_API_KEY).strip()
    provider = config.LLM_PROVIDER

    if (provider == "gemini" or not anthropic_key) and gemini_key and genai is not None:
        try:
            plan = generate_plan_gemini(bug_report, retrieved_files, gemini_key, model=config.PLANNER_MODEL)
            log_msg = f"[Planner (Gemini: {config.PLANNER_MODEL})] Generated plan for: '{bug_report[:60]}...'"
        except Exception as e:
            log_msg = f"[Planner (Fallback)] Gemini API error ({e}), generated fallback plan."
            plan = generate_plan_mock(bug_report, retrieved_files)
    elif anthropic_key and anthropic is not None:
        try:
            plan = generate_plan_claude(bug_report, retrieved_files, anthropic_key, model=config.PLANNER_MODEL)
            log_msg = f"[Planner (Claude: {config.PLANNER_MODEL})] Generated plan for: '{bug_report[:60]}...'"
        except Exception as e:
            log_msg = f"[Planner (Fallback)] Claude API error ({e}), generated fallback plan."
            plan = generate_plan_mock(bug_report, retrieved_files)
    else:
        log_msg = "[Planner (Local Mock)] Generated plan (API keys not set)."
        plan = generate_plan_mock(bug_report, retrieved_files)

    history = list(state.get("history", []))
    history.append(f"{log_msg}\nPlan Preview:\n{plan}")

    return {
        "plan": plan,
        "history": history
    }
