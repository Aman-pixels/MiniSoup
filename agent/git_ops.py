"""Git operations module for the autonomous bug-fixing agent.

Responsibilities:
- Create isolated branches per bug fix / attempt.
- Stage and commit changes after each edit iteration.
- Cleanly reset/revert failed attempts to avoid compounding errors.
- Extract clean git diffs against the base branch.
- Generate pull request / review summaries without auto-merging.
"""

from pathlib import Path
from typing import Optional
import git


class GitOpsError(Exception):
    """Custom exception for Git operation failures."""
    pass


def init_or_open_repo(repo_path: str | Path) -> git.Repo:
    """Open an existing git repository or initialize a new one if not present.
    
    Args:
        repo_path: Absolute or relative path to the repository directory.
        
    Returns:
        git.Repo instance.
    """
    path = Path(repo_path).resolve()
    try:
        return git.Repo(path)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        path.mkdir(parents=True, exist_ok=True)
        repo = git.Repo.init(path)
        # Ensure default branch is set to main
        try:
            repo.git.checkout("-b", "main")
        except git.GitCommandError:
            pass
        try:
            if not repo.heads:
                repo.git.add("-A")
                repo.git.commit("-m", "Initial e-commerce target repo with seed bugs and test suites")
        except Exception:
            pass
        return repo


def get_current_branch(repo: git.Repo) -> str:
    """Return the name of the currently checked out branch."""
    try:
        return repo.active_branch.name
    except TypeError:
        # Detached HEAD state
        return repo.head.commit.hexsha[:8]


def create_attempt_branch(
    repo: git.Repo,
    branch_name: str,
    base_branch: str = "main",
    force_new: bool = True
) -> str:
    """Create and check out a dedicated branch for a bug fix attempt.
    
    Args:
        repo: git.Repo instance.
        branch_name: Name of the new branch (e.g., 'fix/bug-123-attempt-1').
        base_branch: Branch to branch off from (default: 'main').
        force_new: If True, delete existing branch with same name before creating.
        
    Returns:
        The name of the checked-out branch.
    """
    try:
        # First checkout base branch
        repo.git.checkout(base_branch)
        
        # If branch already exists and force_new is requested, remove it
        if force_new and branch_name in [b.name for b in repo.branches]:
            repo.git.branch("-D", branch_name)
            
        # Create and switch to new branch
        repo.git.checkout("-b", branch_name)
        return branch_name
    except git.GitCommandError as e:
        raise GitOpsError(f"Failed to create attempt branch '{branch_name}': {e}") from e


def commit_attempt(repo: git.Repo, iteration: int, message: str) -> str:
    """Stage all tracked and untracked changes and commit with iteration metadata.
    
    Args:
        repo: git.Repo instance.
        iteration: The attempt index (e.g., 1, 2, ...).
        message: Commit message describing the changes made.
        
    Returns:
        Commit SHA hash of the created commit, or empty string if no changes.
    """
    try:
        # Stage all changes (new, modified, deleted)
        repo.git.add("-A")
        
        # Check if there is anything staged to commit
        if not repo.is_dirty(untracked_files=True) and not repo.index.diff("HEAD"):
            return ""
            
        full_message = f"[Autonomous Fix Attempt #{iteration}] {message.strip()}"
        commit = repo.index.commit(full_message)
        return commit.hexsha
    except git.GitCommandError as e:
        raise GitOpsError(f"Failed to commit attempt #{iteration}: {e}") from e


def reset_to_clean_state(repo: git.Repo, base_ref: Optional[str] = None) -> None:
    """Discard all uncommitted changes, untracked files, or reset to a base reference.
    
    Used before retry attempts so failed edits don't compound into the next try.
    
    Args:
        repo: git.Repo instance.
        base_ref: Optional commit SHA or branch to hard-reset to.
    """
    try:
        # Discard working tree changes and untracked files
        repo.git.reset("--hard", base_ref) if base_ref else repo.git.reset("--hard")
        repo.git.clean("-fd")
    except git.GitCommandError as e:
        raise GitOpsError(f"Failed to reset repo to clean state: {e}") from e


def get_diff(repo: git.Repo, base_branch: str = "main") -> str:
    """Extract a clean unified diff between base branch and the current HEAD/working tree.
    
    Args:
        repo: git.Repo instance.
        base_branch: Target base branch to compare against.
        
    Returns:
        Unified git diff string.
    """
    try:
        # First check committed diff against base_branch
        diff = repo.git.diff(f"{base_branch}...HEAD")
        
        # If there are also uncommitted changes in working tree, include them
        uncommitted_diff = repo.git.diff("HEAD")
        if uncommitted_diff:
            diff = f"{diff}\n\n# Uncommitted working tree changes:\n{uncommitted_diff}".strip()
            
        # If no commit yet, diff directly against base_branch working tree
        if not diff.strip():
            diff = repo.git.diff(base_branch)
            
        return diff
    except git.GitCommandError as e:
        # Fallback to diffing against HEAD
        try:
            return repo.git.diff("HEAD")
        except git.GitCommandError:
            return ""


def generate_pr_body(
    bug_report: str,
    plan: str,
    diff: str,
    test_output: str,
    iterations: int,
    passed: bool
) -> str:
    """Generate a clean Pull Request description.
    
    NEVER auto-merges: output is formatted for human engineering review.
    
    Args:
        bug_report: Original user/system bug report.
        plan: Proposed fix strategy by the planner.
        diff: Git diff of the proposed fix.
        test_output: Captured test output from Docker sandbox.
        iterations: Number of iterations taken.
        passed: Whether all tests passed.
        
    Returns:
        Markdown-formatted PR summary.
    """
    status_emoji = "✅ PASSED" if passed else "⚠️ FAILED / REQUIRES HUMAN REVIEW"
    
    body = f"""## 🤖 Autonomous Bug-Fixing Agent Summary

### Status: {status_emoji}
**Iterations Used:** {iterations}

---

### 📋 Original Bug Report
```text
{bug_report.strip()}
```

---

### 💡 Fix Strategy & Plan
{plan.strip()}

---

### 🧪 Test Verification in Docker Sandbox
```text
{test_output.strip() if test_output.strip() else "No test output captured."}
```

---

### 📝 Proposed Git Diff
```diff
{diff.strip() if diff.strip() else "(No code modifications detected)"}
```

---
*Notice: This fix was prepared autonomously inside an isolated Docker sandbox. It is submitted as a PR/diff for human review and will NOT be auto-merged.*
"""
    return body
