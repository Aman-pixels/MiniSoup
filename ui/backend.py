"""FastAPI and WebSocket backend for the autonomous bug-fixing agent."""

import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse

import config
from agent.state import AgentState
from agent.orchestrator import (
    build_orchestrator_graph,
    init_or_open_repo,
    create_attempt_branch,
    generate_pr_body
)

app = FastAPI(
    title="Autonomous Bug-Fixing Agent API",
    description="Live WebSocket streaming of bug fixing pipeline",
    version="1.0.0"
)

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

DEMO_BUGS = [
    {
        "id": "bug-1",
        "title": "Users logged out on page refresh (JWT/cookie bug)",
        "module": "ecommerce/auth.py",
        "description": "When users refresh the webpage, their session is unexpectedly terminated. Browser cookies send 'auth_jwt' key but session extractor only looks for 'access_token'."
    },
    {
        "id": "bug-2",
        "title": "Broken API call (wrong endpoint/missing header)",
        "module": "ecommerce/api_client.py",
        "description": "Order lookup requests are returning 404 and 401 errors. Client calls deprecated '/v1/order' instead of '/api/v2/orders' and misses 'Authorization: Bearer <token>' header."
    },
    {
        "id": "bug-3",
        "title": "Off-by-one error in cart quantity update",
        "module": "ecommerce/cart.py",
        "description": "Updating product quantity in the shopping cart increments the value by 1 extra item (setting quantity to 5 results in 6 items in cart)."
    },
    {
        "id": "bug-4",
        "title": "Null-pointer on empty checkout",
        "module": "ecommerce/checkout.py",
        "description": "Checking out with an empty cart crashes with IndexError or AttributeError when attempting to access cart.items without empty verification."
    }
]


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "llm_provider": config.LLM_PROVIDER,
        "embedding_provider": "voyageai" if config.VOYAGE_API_KEY else "local",
        "docker_image": config.DOCKER_IMAGE,
        "max_iterations": config.MAX_ITERATIONS,
        "planner_model": config.PLANNER_MODEL,
        "executor_model": config.EXECUTOR_MODEL,
        "reviewer_model": config.REVIEWER_MODEL
    }


def detect_test_framework(target: Path) -> tuple[Optional[str], Optional[str]]:
    """Detect test runner and command for a given repository path."""
    if not target.exists() or not target.is_dir():
        return None, None

    # 1. Pytest detection
    try:
        if (
            (target / "pytest.ini").exists() or
            (target / "conftest.py").exists() or
            ((target / "setup.cfg").exists() and "pytest" in (target / "setup.cfg").read_text(encoding="utf-8", errors="ignore")) or
            ((target / "pyproject.toml").exists() and "pytest" in (target / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")) or
            ((target / "requirements.txt").exists() and "pytest" in (target / "requirements.txt").read_text(encoding="utf-8", errors="ignore")) or
            ((target / "tests").is_dir() and any((target / "tests").glob("test_*.py")))
        ):
            return "pytest", "pytest"
    except Exception:
        pass

    # 2. Node/JS package.json test script detection
    pkg_json = target / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
            scripts = data.get("scripts", {})
            if "test" in scripts and "no test specified" not in scripts["test"].lower():
                return f"npm test ({scripts['test'][:25]})", "npm test"
        except Exception:
            pass

    # 3. Python unittest fallback
    if (target / "tests").is_dir() or any(target.glob("test_*.py")):
        return "python -m unittest", "python -m unittest discover"

    # 4. Cargo test
    if (target / "Cargo.toml").exists():
        return "cargo test", "cargo test"

    # 5. Go test
    if (target / "go.mod").exists() or any(target.glob("*_test.go")):
        return "go test", "go test ./..."

    return None, None


@app.get("/api/repo-info")
async def get_repo_info(path: str = ""):
    target = Path(path).resolve() if path.strip() else Path(config.TARGET_REPO_PATH).resolve()
    exists = target.exists() and target.is_dir()
    
    # Auto-initialize default seed target_repo if needed
    if exists and target == Path(config.TARGET_REPO_PATH).resolve() and not (target / ".git").exists():
        try:
            init_or_open_repo(target)
        except Exception:
            pass

    is_git = False
    branch = "unknown"
    if exists:
        try:
            import git
            r = git.Repo(target, search_parent_directories=False)
            is_git = True
            try:
                branch = r.active_branch.name
            except Exception:
                branch = r.head.commit.hexsha[:8] if r.heads else "main"
        except Exception:
            is_git = False

    test_framework, test_cmd = detect_test_framework(target) if exists else (None, None)
    is_valid = bool(exists and is_git)
    status_summary = "valid" if is_valid else ("not_git" if exists else "not_found")

    return {
        "path": str(target),
        "exists": exists,
        "is_dir": target.is_dir() if target.exists() else False,
        "is_git": is_git,
        "branch": branch,
        "test_framework": test_framework,
        "test_command": test_cmd or config.DEFAULT_TEST_COMMAND,
        "is_valid": is_valid,
        "status_summary": status_summary,
        "default_path": str(Path(config.TARGET_REPO_PATH).resolve())
    }


@app.get("/api/demo-bugs")
async def get_demo_bugs():
    return DEMO_BUGS


@app.websocket("/ws/fix")
async def websocket_fix_endpoint(websocket: WebSocket):
    """WebSocket endpoint to stream each node's reasoning and state updates live."""
    await websocket.accept()
    
    try:
        # Receive configuration / bug report
        data = await websocket.receive_text()
        request = json.loads(data)
        bug_report = request.get("bug_report", "").strip()
        custom_repo = request.get("repo_path", "").strip()
        max_iterations = int(request.get("max_iterations", config.MAX_ITERATIONS))

        if not bug_report:
            await websocket.send_json({
                "type": "error",
                "message": "Bug report text is required."
            })
            return

        repo_target = Path(custom_repo).resolve() if custom_repo else Path(config.TARGET_REPO_PATH).resolve()
        if not repo_target.exists():
            await websocket.send_json({
                "type": "error",
                "message": f"Target repository path does not exist: {repo_target}"
            })
            return

        # Prepare isolated Git attempt branch
        repo = init_or_open_repo(repo_target)
        branch_name = f"fix/ui-attempt-{abs(hash(bug_report)) % 10000}"
        create_attempt_branch(repo, branch_name=branch_name, base_branch="main")

        initial_state: AgentState = {
            "bug_report": bug_report,
            "retrieved_files": [],
            "plan": "",
            "current_diff": "",
            "test_result": None,
            "iteration": 0,
            "max_iterations": max_iterations,
            "review_status": "pending",
            "review_feedback": "",
            "history": [],
            "branch_name": branch_name,
            "simulate_fail_attempts": 0,
            "review_rejection_count": 0,
            "repo_path": str(repo_target)
        }

        # Send initial status
        await websocket.send_json({
            "type": "started",
            "branch": branch_name,
            "bug_report": bug_report,
            "repo_path": str(repo_target),
            "max_iterations": max_iterations
        })

        # Build compiled LangGraph StateGraph
        app_graph = build_orchestrator_graph()

        current_state = dict(initial_state)

        # Stream node execution events
        for event in app_graph.stream(initial_state, stream_mode="updates"):
            for node_name, node_update in event.items():
                current_state.update(node_update)

                # Extract latest history log
                history_list = current_state.get("history", [])
                latest_log = history_list[-1] if history_list else f"Node {node_name} completed."

                payload = {
                    "type": "node_update",
                    "node": node_name,
                    "iteration": current_state.get("iteration", 0),
                    "log": latest_log,
                    "plan": current_state.get("plan", ""),
                    "current_diff": current_state.get("current_diff", ""),
                    "test_result": current_state.get("test_result"),
                    "review_status": current_state.get("review_status", "pending"),
                    "review_feedback": current_state.get("review_feedback", "")
                }

                await websocket.send_json(payload)
                # Small pause to allow smooth streaming UI animation
                await asyncio.sleep(0.15)

        # Generate PR summary for final output
        passed = bool(current_state.get("test_result", {}).get("passed", False))
        test_out = current_state.get("test_result", {}).get("output", "No test output")
        diff = current_state.get("current_diff", "")
        pr_body = generate_pr_body(
            bug_report=bug_report,
            plan=current_state.get("plan", ""),
            diff=diff,
            test_output=test_out,
            iterations=current_state.get("iteration", 1),
            passed=passed
        )

        await websocket.send_json({
            "type": "completed",
            "passed": passed,
            "iterations": current_state.get("iteration", 1),
            "diff": diff,
            "pr_body": pr_body,
            "review_status": current_state.get("review_status", "pending")
        })

    except WebSocketDisconnect:
        print("[INFO] WebSocket client disconnected.")
    except Exception as e:
        print(f"[ERROR] WebSocket pipeline exception: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except Exception:
            pass


@app.get("/")
async def serve_index():
    """Serve frontend dashboard."""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h2>Autonomous Bug-Fixing Agent Dashboard</h2><p>Frontend initializing...</p>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ui.backend:app", host="0.0.0.0", port=8000, reload=False)
