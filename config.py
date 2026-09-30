import os
from pathlib import Path
from dotenv import load_dotenv

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TARGET_REPO_PATH = Path(os.environ.get("TARGET_REPO_PATH", BASE_DIR / "target_repo"))
CHROMA_PERSIST_DIR = Path(os.environ.get("CHROMA_PERSIST_DIR", BASE_DIR / ".chroma_db"))

# LLM Configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "")

# Active provider: 'gemini', 'anthropic', or 'mock'
DEFAULT_PROVIDER = "gemini" if GEMINI_API_KEY else ("anthropic" if ANTHROPIC_API_KEY else "mock")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER).lower()

DEFAULT_MODEL = "gemini-2.5-flash" if LLM_PROVIDER == "gemini" else "claude-3-5-sonnet-20241022"
PLANNER_MODEL = os.environ.get("PLANNER_MODEL", DEFAULT_MODEL)
EXECUTOR_MODEL = os.environ.get("EXECUTOR_MODEL", DEFAULT_MODEL)
REVIEWER_MODEL = os.environ.get("REVIEWER_MODEL", DEFAULT_MODEL)

# Retrieval Configuration
VOYAGE_EMBED_MODEL = "voyage-code-2"
CHROMA_COLLECTION_NAME = "repo_code_chunks"

# Docker Sandbox Configuration
DOCKER_IMAGE = os.environ.get("DOCKER_IMAGE", "python:3.11-slim")
DEFAULT_TEST_COMMAND = os.environ.get("DEFAULT_TEST_COMMAND", "pytest")
SANDBOX_TIMEOUT_SECONDS = int(os.environ.get("SANDBOX_TIMEOUT_SECONDS", "120"))
CONTAINER_WORKSPACE = "/workspace"

# Orchestrator Limits
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "4"))
