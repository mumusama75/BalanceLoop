"""Check the LLM endpoint configured in backend/.env with one structured call.

    uv run python backend/llm_check.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import get_settings  # noqa: E402
from app.llm.cloud_client import CloudLLMClient  # noqa: E402
from app.llm.gateway import LLMUnavailable  # noqa: E402

s = get_settings()
print(f"provider={s.llm_provider}  base_url={CloudLLMClient.normalise_base_url(s.llm_base_url)}  model={s.llm_model}  key={'set' if s.llm_api_key else 'MISSING'}")
if s.llm_provider != "cloud":
    print("BL_LLM_PROVIDER is not 'cloud' — the app will use the offline mock. Set it to cloud to test a real endpoint.")
    sys.exit(0)
client = CloudLLMClient(s.llm_base_url, s.llm_api_key, s.llm_model, s.llm_timeout_seconds)
t = time.time()
try:
    r = client.identify_food("2 boiled eggs and a bowl of rice", {"clarifications": [], "known_allergies": []})
except LLMUnavailable as e:
    print(f"FAILED after {time.time() - t:.1f}s: {e}")
    sys.exit(1)
print(f"OK in {time.time() - t:.1f}s  (json_mode={'on' if client._json_mode else 'off'})  usage={client.last_meta.get('usage')}")
print(json.dumps(r.model_dump(), indent=1)[:600])
