"""Reviewer module for the autonomous bug-fixing agent.

Role: Reviewer (Security, Quality & Scope Creep Auditor)
- Distinct LLM persona with independent system prompt and conversation context.
- Inspects the git diff strictly against the approved plan and bug report.
- Flags scope creep, unrelated refactorings, unwanted comments, or logic drift.
- Returns status ('approved' | 'rejected') and structured feedback.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Dict, Any, Optional

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
from agent.state import AgentState

REVIEWER_SYSTEM_PROMPT = """You are a meticulous Principal Security & Code Review Auditor.

Your objective:
Conduct an adversarial, rigorous code review of the proposed Git Diff against the Approved Plan and Bug Report.
Your primary mission is to detect and reject:
1. SCOPE CREEP: Any edits to files, classes, or functions NOT explicitly requested in the plan.
2. UNRELATED REFACTORING: Unnecessary renames, whitespace churn, stylistic modifications, or gratuitous comments.
3. LOGIC DRIFT: Changes that do not directly contribute to solving the root cause identified in the plan.

Output Format:
You MUST begin your response with either:
VERDICT: APPROVED
or
VERDICT: REJECTED

Followed by your detailed rationale:
FEEDBACK: <explain clearly what was acceptable or why the diff was rejected>
"""


@dataclass
class ReviewVerdict:
    """Outcome of code review examination."""
    status: str  # 'approved' or 'rejected'
    feedback: str


def review_diff_claude(
    bug_report: str,
    plan: str,
    diff: str,
    api_key: str,
    model: str = config.REVIEWER_MODEL
) -> ReviewVerdict:
    """Invoke Claude Anthropic API with dedicated Reviewer persona."""
    client = anthropic.Anthropic(api_key=api_key)

    user_message = f"""### Original Bug Report:
{bug_report.strip()}

### Approved Fix Plan:
{plan.strip()}

### Proposed Git Diff:
```diff
{diff.strip() if diff.strip() else "(No diff)"}
```

Review this diff for scope creep and plan adherence. Issue your verdict:"""

    response = client.messages.create(
        model=model,
        max_tokens=1000,
        temperature=0.0,
        system=REVIEWER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}]
    )

    text = response.content[0].text.strip()
    status = "approved" if "VERDICT: APPROVED" in text.upper() else "rejected"
    
    # Extract feedback
    feedback = text
    if "FEEDBACK:" in text:
        feedback = text.split("FEEDBACK:", 1)[1].strip()

    return ReviewVerdict(status=status, feedback=feedback)


def review_diff_gemini(
    bug_report: str,
    plan: str,
    diff: str,
    api_key: str,
    model: str = config.REVIEWER_MODEL
) -> ReviewVerdict:
    """Invoke Google Gemini API with dedicated Reviewer persona."""
    client = genai.Client(api_key=api_key)

    user_message = f"""### Original Bug Report:
{bug_report.strip()}

### Approved Fix Plan:
{plan.strip()}

### Proposed Git Diff:
```diff
{diff.strip() if diff.strip() else "(No diff)"}
```

Review this diff for scope creep and plan adherence. Issue your verdict:"""

    response = client.models.generate_content(
        model=model,
        contents=user_message,
        config=genai_types.GenerateContentConfig(
            system_instruction=REVIEWER_SYSTEM_PROMPT,
            temperature=0.0,
            max_output_tokens=1000,
        )
    )

    text = (response.text or "").strip()
    status = "approved" if "VERDICT: APPROVED" in text.upper() else "rejected"

    feedback = text
    if "FEEDBACK:" in text:
        feedback = text.split("FEEDBACK:", 1)[1].strip()

    return ReviewVerdict(status=status, feedback=feedback)


def review_diff_mock(
    bug_report: str,
    plan: str,
    diff: str
) -> ReviewVerdict:
    """Deterministic reviewer for offline development and testing."""
    if not diff or not diff.strip():
        return ReviewVerdict(
            status="rejected",
            feedback="Diff is completely empty. No changes were applied."
        )

    # Detect scope creep: check if diff modifies files outside the plan
    diff_files = re.findall(r"diff --git a/(\S+) b/\S+", diff)
    for f in diff_files:
        if f not in plan and Path(f).name not in plan:
            return ReviewVerdict(
                status="rejected",
                feedback=f"Scope Creep Detected: File '{f}' was modified in the diff but is NOT part of the approved plan."
            )

    # Detect extraneous unwanted edits
    if "TODO" in diff or "refactor" in diff.lower() or "SCOPE_CREEP_TEST" in diff:
        return ReviewVerdict(
            status="rejected",
            feedback="Scope Creep Detected: Unrelated comments or refactoring detected in code diff."
        )

    return ReviewVerdict(
        status="approved",
        feedback="Diff adheres strictly to the approved plan without scope creep or extraneous refactoring."
    )


def review_node(state: AgentState) -> Dict[str, Any]:
    """LangGraph node execution for the Reviewer role.
    
    Args:
        state: Current AgentState.
        
    Returns:
        State update dictionary containing 'review_status', 'review_feedback', and updated 'history'.
    """
    bug_report = state["bug_report"]
    plan = state["plan"]
    diff = state.get("current_diff", "")
    history = list(state.get("history", []))

    gemini_key = os.environ.get("GEMINI_API_KEY", config.GEMINI_API_KEY).strip()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", config.ANTHROPIC_API_KEY).strip()
    provider = config.LLM_PROVIDER

    if (provider == "gemini" or not anthropic_key) and gemini_key and genai is not None:
        try:
            verdict = review_diff_gemini(bug_report, plan, diff, gemini_key, model=config.REVIEWER_MODEL)
            log_prefix = f"[Reviewer (Gemini: {config.REVIEWER_MODEL})]"
        except Exception as e:
            log_prefix = f"[Reviewer (Fallback: {e})]"
            verdict = review_diff_mock(bug_report, plan, diff)
    elif anthropic_key and anthropic is not None:
        try:
            verdict = review_diff_claude(bug_report, plan, diff, anthropic_key, model=config.REVIEWER_MODEL)
            log_prefix = f"[Reviewer (Claude: {config.REVIEWER_MODEL})]"
        except Exception as e:
            log_prefix = f"[Reviewer (Fallback: {e})]"
            verdict = review_diff_mock(bug_report, plan, diff)
    else:
        log_prefix = "[Reviewer (Local Mock)]"
        verdict = review_diff_mock(bug_report, plan, diff)

    log_msg = (
        f"{log_prefix} Verdict: {verdict.status.upper()}\n"
        f"Feedback: {verdict.feedback}"
    )
    history.append(log_msg)

    return {
        "review_status": verdict.status,
        "review_feedback": verdict.feedback,
        "history": history
    }
