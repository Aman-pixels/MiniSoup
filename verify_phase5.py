"""Verification script for Phase 5: Reviewer persona and reject-to-executor edge."""

from pathlib import Path
import config
from agent.orchestrator import run_orchestrator
from agent.git_ops import init_or_open_repo, reset_to_clean_state
from agent.reviewer import review_diff_mock, ReviewVerdict


def test_reviewer_approved_clean_diff():
    print("\n" + "="*70)
    print("[TEST 1] Testing Reviewer Approval on Clean, Plan-Aligned Diff")
    print("="*70)

    bug_report = "Off-by-one error in cart quantity update"
    repo_path = config.TARGET_REPO_PATH

    final_state = run_orchestrator(
        bug_report=bug_report,
        max_iterations=config.MAX_ITERATIONS,
        repo_path=repo_path
    )

    print(f"[OK] Iterations: {final_state.get('iteration')}")
    print(f"[OK] Test Passed: {final_state.get('test_result', {}).get('passed')}")
    print(f"[OK] Review Status: {final_state.get('review_status')}")
    print(f"[OK] Review Feedback: {final_state.get('review_feedback')}")

    assert final_state.get("review_status") == "approved", "Expected clean diff to be approved"
    assert final_state.get("review_rejection_count") == 0, "Expected 0 rejections for clean diff"

    # Verify history contains Reviewer reasoning
    history_text = "\n".join(final_state.get("history", []))
    assert "[Reviewer" in history_text, "Expected Reviewer node log in history"
    print("[OK] Reviewer persona executed and verified plan adherence.")

    # Clean up
    repo = init_or_open_repo(repo_path)
    repo.git.checkout("main")
    reset_to_clean_state(repo)
    print("[SUCCESS] Test 1 PASSED!\n")


def test_reviewer_scope_creep_rejection():
    print("\n" + "="*70)
    print("[TEST 2] Testing Reviewer Detection of Scope Creep & Rejection Edge (Allowed Once)")
    print("="*70)

    plan = "Modify ecommerce/cart.py to update item quantity."
    
    # 1. Simulate diff with scope creep (touches auth.py which is not in plan)
    diff_with_scope_creep = """diff --git a/ecommerce/cart.py b/ecommerce/cart.py
index 0604a27..7694cf7 100644
--- a/ecommerce/cart.py
+++ b/ecommerce/cart.py
@@ -26,3 +26,3 @@
-        self.items[item_id] = new_quantity + 1
+        self.items[item_id] = new_quantity
diff --git a/ecommerce/auth.py b/ecommerce/auth.py
index 1111111..2222222 100644
--- a/ecommerce/auth.py
+++ b/ecommerce/auth.py
@@ -10,2 +10,3 @@
+# Extraneous unrequested change
"""
    verdict1 = review_diff_mock(
        bug_report="Fix cart quantity",
        plan=plan,
        diff=diff_with_scope_creep
    )

    print(f"[OK] Injected scope creep diff verdict: {verdict1.status.upper()}")
    print(f"[OK] Feedback: {verdict1.feedback}")
    assert verdict1.status == "rejected"
    assert "Scope Creep Detected" in verdict1.feedback

    # 2. Simulate diff with unapproved refactoring / comments
    diff_with_refactor = """diff --git a/ecommerce/cart.py b/ecommerce/cart.py
--- a/ecommerce/cart.py
+++ b/ecommerce/cart.py
@@ -26,3 +26,3 @@
-        self.items[item_id] = new_quantity + 1
+        self.items[item_id] = new_quantity # SCOPE_CREEP_TEST
"""
    verdict2 = review_diff_mock(
        bug_report="Fix cart quantity",
        plan=plan,
        diff=diff_with_refactor
    )
    print(f"\n[OK] Injected refactoring diff verdict: {verdict2.status.upper()}")
    print(f"[OK] Feedback: {verdict2.feedback}")
    assert verdict2.status == "rejected"

    # 3. Clean diff should pass review
    clean_diff = """diff --git a/ecommerce/cart.py b/ecommerce/cart.py
--- a/ecommerce/cart.py
+++ b/ecommerce/cart.py
@@ -26,3 +26,3 @@
-        self.items[item_id] = new_quantity + 1
+        self.items[item_id] = new_quantity
"""
    verdict3 = review_diff_mock(
        bug_report="Fix cart quantity",
        plan=plan,
        diff=clean_diff
    )
    print(f"\n[OK] Clean surgical diff verdict: {verdict3.status.upper()}")
    assert verdict3.status == "approved"

    print("[SUCCESS] Test 2 PASSED!\n")


if __name__ == "__main__":
    test_reviewer_approved_clean_diff()
    test_reviewer_scope_creep_rejection()
    print("="*70)
    print("[ALL PASSED] Phase 5 Reviewer & Scope Creep Guards verified completely!")
    print("="*70)
