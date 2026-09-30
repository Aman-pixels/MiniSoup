"""Verification script for Phase 1: git_ops.py and sandbox.py."""

import sys
from pathlib import Path
import config
from agent.git_ops import (
    init_or_open_repo,
    create_attempt_branch,
    commit_attempt,
    reset_to_clean_state,
    get_diff,
    generate_pr_body,
    get_current_branch,
)
from agent.sandbox import DockerSandbox, DockerSandboxError


def test_git_ops(repo_path: Path):
    print("\n" + "="*50)
    print("[TEST] 1. Testing agent/git_ops.py")
    print("="*50)

    repo = init_or_open_repo(repo_path)
    print(f"[OK] Opened repository at: {repo_path}")
    print(f"[OK] Current branch: {get_current_branch(repo)}")

    # Test creating attempt branch
    attempt_branch = "fix/demo-cart-attempt-1"
    create_attempt_branch(repo, attempt_branch, base_branch="main")
    print(f"[OK] Created and switched to attempt branch: {get_current_branch(repo)}")
    assert get_current_branch(repo) == attempt_branch

    # Simulate code change
    cart_file = repo_path / "ecommerce" / "cart.py"
    original_content = cart_file.read_text()
    
    # Fix the off-by-one bug in cart.py
    fixed_content = original_content.replace(
        "self.items[item_id] = new_quantity + 1",
        "self.items[item_id] = new_quantity"
    )
    cart_file.write_text(fixed_content)
    print("[OK] Simulated bug fix in ecommerce/cart.py")

    # Test commit attempt
    commit_sha = commit_attempt(repo, iteration=1, message="Fix off-by-one error in update_quantity")
    print(f"[OK] Committed attempt #1: SHA {commit_sha[:8]}")
    assert commit_sha != ""

    # Test get_diff
    diff = get_diff(repo, base_branch="main")
    print(f"[OK] Generated clean unified diff against main:\n{'-'*40}\n{diff}\n{'-'*40}")
    assert "self.items[item_id] = new_quantity" in diff

    # Test PR body generation
    pr_body = generate_pr_body(
        bug_report="Off-by-one error in cart quantity update",
        plan="Update cart.py to store exact new_quantity instead of new_quantity + 1",
        diff=diff,
        test_output="1 passed in 0.05s",
        iterations=1,
        passed=True
    )
    print("[OK] Successfully formatted PR body for human review (never auto-merge).")

    # Test clean reset back to main
    repo.git.checkout("main")
    repo.git.branch("-D", attempt_branch)
    reset_to_clean_state(repo)
    print(f"[OK] Cleanly reset and returned to base branch: {get_current_branch(repo)}")
    print("[SUCCESS] git_ops.py tests PASSED!")


def test_sandbox(repo_path: Path):
    print("\n" + "="*50)
    print("[TEST] 2. Testing agent/sandbox.py (Docker Isolation)")
    print("="*50)

    sandbox = DockerSandbox(image=config.DOCKER_IMAGE, timeout_seconds=config.SANDBOX_TIMEOUT_SECONDS)
    
    if not sandbox.is_docker_available():
        print("[WARN] Docker daemon is currently not running on this system.")
        print("       To verify the Docker container run, please start Docker Desktop.")
        print("       Checking sandbox error message:")
        try:
            sandbox.get_client()
        except DockerSandboxError as e:
            print(f"       [OK] Caught expected descriptive error:\n       {e}")
        return False

    print("[OK] Connected to Docker daemon.")
    print(f"[OK] Using Docker image: {sandbox.image}")
    
    # 1. Run tests against un-fixed repo (should fail on seeded bugs)
    print("\nRunning initial test suite inside fresh container (expecting seeded bug failures)...")
    res1 = sandbox.run_tests(repo_path, test_command="pytest tests/test_cart.py")
    print(f"Passed: {res1.passed}")
    print(f"Exit Code: {res1.exit_code}")
    print(f"Duration: {res1.duration_sec:.2f}s")
    print(f"Output preview:\n{res1.output[:300]}...")
    assert not res1.passed, "Expected cart test to fail on seed bug!"
    print("[OK] Sandbox accurately detected test failure inside container!")

    # 2. Temporarily fix cart bug and verify container test passes
    cart_file = repo_path / "ecommerce" / "cart.py"
    original_content = cart_file.read_text()
    fixed_content = original_content.replace(
        "self.items[item_id] = new_quantity + 1",
        "self.items[item_id] = new_quantity"
    )
    cart_file.write_text(fixed_content)

    print("\nRunning tests after simulated fix inside another fresh container...")
    res2 = sandbox.run_tests(repo_path, test_command="pytest tests/test_cart.py")
    print(f"Passed: {res2.passed}")
    print(f"Exit Code: {res2.exit_code}")
    print(f"Duration: {res2.duration_sec:.2f}s")
    print(f"Output:\n{res2.output}")
    assert res2.passed, "Expected cart test to pass after fix!"
    print("[OK] Sandbox accurately detected test pass inside container!")

    # Revert temporary file edit
    cart_file.write_text(original_content)
    print("[OK] Cleaned up test modifications on host.")
    print("[SUCCESS] sandbox.py Docker tests PASSED!")
    return True


if __name__ == "__main__":
    repo_path = config.TARGET_REPO_PATH
    test_git_ops(repo_path)
    docker_ran = test_sandbox(repo_path)
    if not docker_ran:
        print("\nNote: Please launch Docker Desktop to complete containerized test execution.")
