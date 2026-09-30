"""Launcher for the Autonomous Bug-Fixing Agent Dashboard."""

import uvicorn

if __name__ == "__main__":
    print("\n" + "="*65)
    print("🚀 Launching Autonomous Bug-Fixing Agent UI Dashboard")
    print("📍 URL: http://localhost:8000")
    print("="*65 + "\n")
    uvicorn.run("ui.backend:app", host="0.0.0.0", port=8000, reload=False)
