"""TypedDict state definitions for the autonomous bug-fixing agent."""

from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class CodeContextItem(TypedDict):
    """Retrieved code context metadata and content."""
    chunk_id: str
    file_path: str
    chunk_type: str
    name: str
    start_line: int
    end_line: int
    content: str
    score: float


class TestExecutionResult(TypedDict):
    """Captured sandbox test execution results."""
    passed: bool
    exit_code: int
    output: str
    stdout: str
    stderr: str
    duration_sec: float
    error_message: Optional[str]


class AgentState(TypedDict):
    """Central state shared across LangGraph agent nodes.
    
    Fields:
    - bug_report: Original natural language bug description.
    - retrieved_files: AST-retrieved code chunks relevant to the bug.
    - plan: Step-by-step diagnostic and execution plan produced by Planner.
    - current_diff: Unified git diff of current attempt against base branch.
    - test_result: Outcome of Docker container test execution.
    - iteration: Current retry attempt count (1-indexed).
    - max_iterations: Maximum allowed attempts before terminating.
    - review_status: Outcome of self-reviewer check ('pending', 'approved', 'rejected').
    - review_feedback: Constructive critique from Reviewer persona.
    - history: Chronological log of reasoning from each agent node.
    - branch_name: Dedicated Git attempt branch name.
    """
    bug_report: str
    retrieved_files: List[CodeContextItem]
    plan: str
    current_diff: str
    test_result: Optional[TestExecutionResult]
    iteration: int
    max_iterations: int
    review_status: str
    review_feedback: str
    history: List[str]
    branch_name: str
    simulate_fail_attempts: int
    review_rejection_count: int
    repo_path: Optional[str]
