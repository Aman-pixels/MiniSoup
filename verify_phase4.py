"""Verification script for Phase 4: LangGraph StateGraph Orchestration."""

from pathlib import Path
import config
from agent.orchestrator import build_orchestrator_graph, run_orchestrator
from agent.git_ops import init_or_open_repo, reset_to_clean_state, generate_pr_body


def test_orchestrator_successful_flow():
    print("\n" + "="*70)
    print("[TEST 1] Testing Orchestrator Successful End-to-End Run (Attempt 1)")
    print("="*70)

    bug_report = "Off-by-one error in cart quantity update"
    repo_path = config.TARGET_REPO_PATH

    final_state = run_orchestrator(
        bug_report=bug_report,
        max_iterations=config.MAX_ITERATIONS,
        repo_path=repo_path,
        simulate_fail_attempts=0
    )

    print(f"\n[OK] Orchestrator completed.")
    print(f"Iterations used: {final_state.get('iteration')}/{final_state.get('max_iterations')}")
    print(f"Test Status: {'PASSED' if final_state.get('test_result', {}).get('passed') else 'FAILED'}")

    print("\n" + "-"*50)
    print("[TRACE] Node Reasoning History:")
    print("-" * 50)
    for idx, log_entry in enumerate(final_state.get("history", []), 1):
        print(f"\nStep #{idx}:\n{log_entry.strip()}")
    print("-" * 50)

    print("\n" + "-"*50)
    print("[DIFF] Final Proposed Diff:")
    print("-" * 50)
    diff = final_state.get("current_diff", "")
    print(diff if diff.strip() else "(No diff)")
    print("-" * 50)

    assert final_state.get("test_result", {}).get("passed") is True, "Expected test to pass"
    assert "self.items[item_id] = new_quantity" in diff

    # Clean up repo back to main
    repo = init_or_open_repo(repo_path)
    repo.git.checkout("main")
    reset_to_clean_state(repo)
    print("[OK] Working tree reset to main.")
    print("[SUCCESS] Test 1 PASSED!\n")


def test_retry_loop_with_git_revert():
    print("\n" + "="*70)
    print("[TEST 2] Testing Retry Loop with Git Revert on Test Failure")
    print("="*70)

    # Configure simulate_fail_attempts=1 so attempt 1 triggers revert_and_debug, and attempt 2 succeeds
    bug_report = "Broken API call: wrong endpoint or missing header"
    repo_path = config.TARGET_REPO_PATH

    final_state = run_orchestrator(
        bug_report=bug_report,
        max_iterations=4,
        repo_path=repo_path,
        simulate_fail_attempts=1
    )

    iterations = final_state.get("iteration", 0)
    print(f"[OK] Completed retry flow. Total iterations used: {iterations}")
    assert iterations == 2, f"Expected exactly 2 iterations (1 retry), got {iterations}"

    # Verify history contains revert_and_debug entries
    history_text = "\n".join(final_state.get("history", []))
    assert "[Node: Revert & Debug]" in history_text, "Expected Revert & Debug node execution in retry flow"
    print("[OK] Confirmed git revert node executed between failed retry attempts.")
    print(f"[OK] Final test status: {'PASSED' if final_state.get('test_result', {}).get('passed') else 'FAILED'}")
    assert final_state.get("test_result", {}).get("passed") is True

    # Clean up
    repo = init_or_open_repo(repo_path)
    repo.git.checkout("main")
    reset_to_clean_state(repo)
    print("[SUCCESS] Test 2 PASSED!\n")


def test_max_iterations_bounded_cap():
    print("\n" + "="*70)
    print("[TEST 3] Testing MAX_ITERATIONS Strict Bounded Capping")
    print("="*70)

    # Set simulate_fail_attempts=5 and max_iterations=2 to verify strict termination
    bug_report = "Complex bug exceeding retry budget"
    repo_path = config.TARGET_REPO_PATH

    final_state = run_orchestrator(
        bug_report=bug_report,
        max_iterations=2,
        repo_path=repo_path,
        simulate_fail_attempts=5
    )

    iterations = final_state.get("iteration", 0)
    print(f"[OK] Execution terminated. Iterations: {iterations} (Cap: 2)")
    assert iterations == 2, f"Expected iterations capped at 2, got {iterations}"
    assert final_state.get("test_result", {}).get("passed") is False, "Expected final status to remain FAILED"
    print("[OK] Confirmed no infinite loop: strictly terminated when MAX_ITERATIONS reached.")

    # Clean up
    repo = init_or_open_repo(repo_path)
    repo.git.checkout("main")
    reset_to_clean_state(repo)
    print("[SUCCESS] Test 3 PASSED!\n")


if __name__ == "__main__":
    test_orchestrator_successful_flow()
    test_retry_loop_with_git_revert()
    test_max_iterations_bounded_cap()
    print("="*70)
    print("[ALL PASSED] Phase 4 LangGraph Orchestrator verified completely!")
    print("="*70)
