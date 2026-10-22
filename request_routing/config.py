"""Paths and settings shared by the routing system."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
FAQ_DIR = DATA_DIR / "faq"
BANKING77_TEST = DATA_DIR / "banking77" / "test.csv"
DEMO_MESSAGES = DATA_DIR / "demo_messages.json"

RUNS_DIR = Path(os.getenv("REQUEST_ROUTING_RUNS_DIR", ROOT / "runs"))
TRACES_DIR = RUNS_DIR / "traces"
OUTCOMES_LOG = RUNS_DIR / "outcomes.jsonl"
HANDOFF_QUEUE = RUNS_DIR / "queue" / "handoffs.jsonl"

MODEL = f"openai:{os.getenv('OPENAI_MODEL', 'gpt-6-luna')}"
