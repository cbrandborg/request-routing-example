import os
import tempfile

# Must run before request_routing is imported: keeps test runs out of ./runs and needs no API key.
os.environ["REQUEST_ROUTING_RUNS_DIR"] = tempfile.mkdtemp(prefix="request-routing-tests-")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
