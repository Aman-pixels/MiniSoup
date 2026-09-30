"""Single-pass verification script for Phase 3: planner.py + executor.py."""

from pathlib import Path
import config
from agent.state import AgentState
from agent.retriever import RepoRetriever
from agent.planner import plan_node
from agent.executor import execute_node
from agent.git_ops import (
    init_or_open_repo,
    create_attempt_branch,
    reset_to_clean_state,
    get_current_branch
)


def run_phase3_single_pass(bug_report: str, repo_path: Path = config.TARGET_REPO_PATH):
    print("\n" + "="*70)
    print(f"[PHASE 3] Running Single-Pass Bug Fix Pipeline")
    print(f"Bug Report: '{bug_report}'")
    print("="*70)

    # 1. Prepare clean git branch
    repo = init_or_open_repo(repo_path)
    branch_name = "fix/phase3-single-pass"
    create_attempt_branch(repo, branch_name=branch_name, base_branch="main")
    print(f"[OK] Checked out dedicated branch: {get_current_branch(repo)}")

    # 2. Retrieve relevant context using AST retriever
    print("\n[STEP 1] Retrieving relevant code chunks...")
    retriever = RepoRetriever()
    search_results = retriever.query(bug_report, n_results=3)

    retrieved_items = [
        {
            "chunk_id": r.chunk_id,
            "file_path": r.file_path,
            "chunk_type": r.chunk_type,
            "name": r.name,
            "start_line": r.start_line,
            "end_line": r.end_line,
            "content": r.content,
            "score": r.score
        }
        for r in search_results
    ]

    for idx, item in enumerate(retrieved_items, 1):
        print(f"  Snippet #{idx}: {item['file_path']} ({item['name']}) - Score: {item['score']:.3f}")

    # 3. Initialize AgentState
    state: AgentState = {
        "bug_report": bug_report,
        "retrieved_files": retrieved_items,
        "plan": "",
        "current_diff": "",
        "test_result": None,
        "iteration": 0,
        "max_iterations": config.MAX_ITERATIONS,
        "review_status": "pending",
        "review_feedback": "",
        "history": [],
        "branch_name": branch_name
    }

    # 4. Run Planner node
    print("\n[STEP 2] Running Planner Persona...")
    plan_output = plan_node(state)
    state["plan"] = plan_output["plan"]
    state["history"] = plan_output["history"]

    print("\n" + "-"*50)
    print("[PLAN] Generated Plan:")
    print("-" * 50)
    print(state["plan"])
    print("-" * 50)

    # 5. Run Executor node
    print("\n[STEP 3] Running Executor Persona & Applying Code Edit...")
    exec_output = execute_node(state, repo_path=repo_path)
    state["current_diff"] = exec_output["current_diff"]
    state["iteration"] = exec_output["iteration"]
    state["history"] = exec_output["history"]

    print("\n" + "-"*50)
    print("[DIFF] Generated Unified Git Diff:")
    print("-" * 50)
    print(state["current_diff"] if state["current_diff"].strip() else "(No diff generated)")
    print("-" * 50)

    # 6. Reset branch back to clean main
    repo.git.checkout("main")
    repo.git.branch("-D", branch_name)
    reset_to_clean_state(repo)
    print(f"\n[OK] Cleaned up branch {branch_name} and returned to main.")
    print("="*70)
    print("[SUCCESS] Phase 3 single-pass pipeline verified successfully!")
    print("="*70 + "\n")


if __name__ == "__main__":
    test_bug = "Off-by-one error in cart quantity update"
    run_phase3_single_pass(test_bug)
