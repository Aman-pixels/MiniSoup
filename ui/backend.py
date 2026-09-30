"""FastAPI and WebSocket backend for the autonomous bug-fixing agent."""

import asyncio
from pathlib import Path
from typing import Dict, Any, List
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


@app.get("/api/repo-info")
async def get_repo_info(path: str = ""):
    target = Path(path).resolve() if path.strip() else Path(config.TARGET_REPO_PATH).resolve()
    exists = target.exists()
    is_git = (target / ".git").exists()
    branch = "unknown"
    if exists and is_git:
        try:
            r = init_or_open_repo(target)
            branch = r.active_branch.name
        except Exception:
            branch = "main"
    return {
        "path": str(target),
        "exists": exists,
        "is_git": is_git,
        "branch": branch,
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
