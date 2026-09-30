"""Verification script for Phase 6: FastAPI and WebSocket UI backend."""

from fastapi.testclient import TestClient
from ui.backend import app
import json


def test_api_endpoints():
    print("\n" + "="*70)
    print("[TEST 1] Testing FastAPI REST Endpoints")
    print("="*70)

    client = TestClient(app)

    # 1. Health check
    res = client.get("/api/health")
    print(f"[OK] GET /api/health Status: {res.status_code}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    print(f"     Docker image: {data['docker_image']}")
    print(f"     Max iterations: {data['max_iterations']}")

    # 2. Demo bugs
    res2 = client.get("/api/demo-bugs")
    print(f"[OK] GET /api/demo-bugs Status: {res2.status_code}")
    assert res2.status_code == 200
    bugs = res2.json()
    assert len(bugs) == 4
    for b in bugs:
        print(f"     Found bug: {b['id']} - {b['title']}")

    # 3. Frontend static HTML
    res3 = client.get("/")
    print(f"[OK] GET / Status: {res3.status_code}")
    assert res3.status_code == 200
    assert "Autonomous Bug-Fixing Agent" in res3.text

    print("[SUCCESS] Test 1 PASSED!\n")


def test_websocket_streaming():
    print("\n" + "="*70)
    print("[TEST 2] Testing Live WebSocket Streaming (/ws/fix)")
    print("="*70)

    client = TestClient(app)

    with client.websocket_connect("/ws/fix") as ws:
        # Send fix request
        request = {
            "bug_report": "Off-by-one error in cart quantity update",
            "max_iterations": 4
        }
        ws.send_text(json.dumps(request))
        print("[OK] Sent fix request over WebSocket.")

        messages_received = []
        nodes_executed = []

        while True:
            msg_raw = ws.receive_text()
            msg = json.loads(msg_raw)
            messages_received.append(msg)
            msg_type = msg.get("type")

            if msg_type == "started":
                print(f"[WS STREAM] Agent started on branch: {msg.get('branch')}")
            elif msg_type == "node_update":
                node_name = msg.get("node")
                nodes_executed.append(node_name)
                print(f"[WS STREAM] Node Completed: {node_name.upper()} (Iteration #{msg.get('iteration')})")
            elif msg_type == "completed":
                print(f"[WS STREAM] Fix Completed! Passed: {msg.get('passed')}, Iterations: {msg.get('iterations')}")
                print(f"[WS STREAM] Review Status: {msg.get('review_status')}")
                assert msg.get("diff"), "Expected diff in completion message"
                assert msg.get("pr_body"), "Expected pr_body in completion message"
                break
            elif msg_type == "error":
                raise RuntimeError(f"WebSocket reported error: {msg.get('message')}")

        print(f"\n[OK] Streamed {len(messages_received)} live WebSocket messages.")
        print(f"[OK] Sequential nodes streamed: {' -> '.join(nodes_executed)}")

        assert "retrieve" in nodes_executed
        assert "plan" in nodes_executed
        assert "edit" in nodes_executed
        assert "test" in nodes_executed
        assert "review" in nodes_executed

    print("[SUCCESS] Test 2 PASSED!\n")


if __name__ == "__main__":
    test_api_endpoints()
    test_websocket_streaming()
    print("="*70)
    print("[ALL PASSED] Phase 6 UI Backend and WebSocket streaming verified completely!")
    print("="*70)
