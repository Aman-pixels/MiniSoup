"""Executor module for the autonomous bug-fixing agent.

Role: Executor (Software Engineer & Code Editor)
- Fresh conversation context (no shared state with planner/reviewer).
- Takes the planner's repair plan and the target file's current content.
- Applies the exact, minimal code edit to the target repository.
- Commits the attempt and generates the unified diff.
"""

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
from agent.git_ops import init_or_open_repo, commit_attempt, get_diff

EXECUTOR_SYSTEM_PROMPT = """You are an expert Senior Software Engineer specializing in surgical code edits.

Your objective:
Given the Plan and the current Target File Content, output the updated, complete content of the file with the bug fix applied.

Rules:
1. Make ONLY the minimal change required by the plan.
2. Do NOT refactor, reformat, or rename unrelated functions, variables, or comments.
3. Preserve all imports and docstrings unless explicitly instructed otherwise.
4. Output the complete updated file content inside a single python markdown code block:
```python
# complete updated file content here
```
Do not include conversational preamble or explanation outside the code block.
"""


def _extract_code_block(text: str) -> str:
    """Extract code from markdown code block."""
    pattern = r"```(?:python)?\s*\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1)
    return text.strip()


def execute_edit_claude(
    plan: str,
    file_path: Path,
    current_content: str,
    api_key: str,
    model: str = config.EXECUTOR_MODEL
) -> str:
    """Invoke Claude Anthropic API with dedicated Executor persona."""
    client = anthropic.Anthropic(api_key=api_key)

    user_message = f"""### Fix Plan:
{plan.strip()}

### Target File:
`{file_path.as_posix()}`

### Current File Content:
```python
{current_content}
```

Please output the complete, updated file content with the fix applied:"""

    response = client.messages.create(
        model=model,
        max_tokens=3000,
        temperature=0.0,
        system=EXECUTOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}]
    )

    raw_output = response.content[0].text
    return _extract_code_block(raw_output)


def execute_edit_gemini(
    plan: str,
    file_path: Path,
    current_content: str,
    api_key: str,
    model: str = config.EXECUTOR_MODEL
) -> str:
    """Invoke Google Gemini API with dedicated Executor persona."""
    client = genai.Client(api_key=api_key)

    user_message = f"""### Fix Plan:
{plan.strip()}

### Target File:
`{file_path.as_posix()}`

### Current File Content:
```python
{current_content}
```

Please output the complete, updated file content with the fix applied:"""

    response = client.models.generate_content(
        model=model,
        contents=user_message,
        config=genai_types.GenerateContentConfig(
            system_instruction=EXECUTOR_SYSTEM_PROMPT,
            temperature=0.0,
            max_output_tokens=4000,
        )
    )

    raw_output = response.text or ""
    return _extract_code_block(raw_output)


def execute_edit_mock(plan: str, target_file: Path, current_content: str) -> str:
    """Fallback deterministic code editor for offline development and testing."""
    filename = target_file.name

    if filename == "cart.py":
        # Fix Bug 3: off-by-one error
        return current_content.replace(
            "self.items[item_id] = new_quantity + 1",
            "self.items[item_id] = new_quantity"
        )
    elif filename == "auth.py":
        # Fix Bug 1: check auth_jwt cookie
        return current_content.replace(
            'return cookies.get("access_token")',
            'return cookies.get("auth_jwt") or cookies.get("access_token")'
        )
    elif filename == "api_client.py":
        # Fix Bug 2: endpoint and auth header
        content = current_content.replace(
            'return f"{self.base_url}/v1/order/{order_id}"',
            'return f"{self.base_url}/api/v2/orders/{order_id}"'
        )
        content = content.replace(
            '        # Bug: token is received but omitted from headers!\n        return headers',
            '        if token:\n            headers["Authorization"] = f"Bearer {token}"\n        return headers'
        )
        return content
    elif filename == "checkout.py":
        # Fix Bug 4: empty cart check
        return current_content.replace(
            '        if not cart.items:\n            # Bug: tries to inspect first item without checking if empty\n            first_item_id = list(cart.items.keys())[0]\n            return self.item_prices.get(first_item_id, 0.0)',
            '        if not cart.items:\n            return 0.0'
        )

    return current_content


def _find_target_file(plan: str, repo_path: Path) -> Optional[Path]:
    """Identify the target file from the plan text or repository structure."""
    # Look for paths mentioned in plan like ecommerce/cart.py or cart.py
    for py_file in repo_path.rglob("*.py"):
        rel = py_file.relative_to(repo_path).as_posix()
        if rel in plan or py_file.name in plan:
            if "test" not in rel:  # Prioritize source files over test files
                return py_file

    # Fallback to first non-test python file found
    for py_file in repo_path.rglob("*.py"):
        if "test" not in py_file.name and "__" not in py_file.name:
            return py_file
    return None


def execute_node(state: AgentState, repo_path: Path = config.TARGET_REPO_PATH) -> Dict[str, Any]:
    """LangGraph node execution for the Executor role.
    
    Args:
        state: Current AgentState.
        repo_path: Target repository root path.
        
    Returns:
        State update dictionary containing 'current_diff', 'iteration', and updated 'history'.
    """
    plan = state["plan"]
    iteration = state.get("iteration", 0) + 1
    repo = init_or_open_repo(repo_path)

    target_file = _find_target_file(plan, repo_path)
    if not target_file or not target_file.exists():
        raise FileNotFoundError(f"Could not determine target file from plan:\n{plan}")

    current_content = target_file.read_text(encoding="utf-8")
    gemini_key = os.environ.get("GEMINI_API_KEY", config.GEMINI_API_KEY).strip()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", config.ANTHROPIC_API_KEY).strip()
    provider = config.LLM_PROVIDER

    if (provider == "gemini" or not anthropic_key) and gemini_key and genai is not None:
        try:
            updated_content = execute_edit_gemini(plan, target_file, current_content, gemini_key, model=config.EXECUTOR_MODEL)
            log_msg = f"[Executor (Gemini: {config.EXECUTOR_MODEL})] Applied code edit to: {target_file.relative_to(repo_path)}"
        except Exception as e:
            log_msg = f"[Executor (Fallback)] Gemini error ({e}), applied fallback edit."
            updated_content = execute_edit_mock(plan, target_file, current_content)
    elif anthropic_key and anthropic is not None:
        try:
            updated_content = execute_edit_claude(plan, target_file, current_content, anthropic_key, model=config.EXECUTOR_MODEL)
            log_msg = f"[Executor (Claude: {config.EXECUTOR_MODEL})] Applied code edit to: {target_file.relative_to(repo_path)}"
        except Exception as e:
            log_msg = f"[Executor (Fallback)] Claude error ({e}), applied fallback edit."
            updated_content = execute_edit_mock(plan, target_file, current_content)
    else:
        log_msg = f"[Executor (Local Mock)] Applied code edit to: {target_file.relative_to(repo_path)}"
        updated_content = execute_edit_mock(plan, target_file, current_content)

    # Write changes to the working tree
    target_file.write_text(updated_content, encoding="utf-8")

    # Commit the attempt via git_ops
    rel_path = target_file.relative_to(repo_path).as_posix()
    commit_sha = commit_attempt(
        repo=repo,
        iteration=iteration,
        message=f"Fix in {rel_path} following Plan"
    )

    # Compute clean unified diff against base branch (main)
    diff = get_diff(repo, base_branch="main")

    history = list(state.get("history", []))
    history.append(f"{log_msg} (Commit: {commit_sha[:8] if commit_sha else 'uncommitted'})\nDiff:\n{diff}")

    return {
        "current_diff": diff,
        "iteration": iteration,
        "history": history
    }
