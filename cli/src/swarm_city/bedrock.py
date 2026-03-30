"""SwarmCity Bedrock client — config I/O and AWS client factory.

Credentials are NEVER stored here. boto3's credential chain is used:
  env vars (AWS_ACCESS_KEY_ID, etc.) → ~/.aws/credentials → IAM role

Install: pip install swarm-city[ai]
"""

from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "swarm" / "config.toml"

DEFAULT_MODEL  = "anthropic.claude-3-5-haiku-20241022-v1:0"
DEFAULT_REGION = "us-east-1"

# ---------------------------------------------------------------------------
# Config read / write
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Return {'model': ..., 'region': ...} with defaults if file missing."""
    if CONFIG_PATH.exists():
        try:
            data = tomllib.loads(CONFIG_PATH.read_text())
            bedrock = data.get("bedrock", {})
            return {
                "model":  bedrock.get("model",  DEFAULT_MODEL),
                "region": bedrock.get("region", DEFAULT_REGION),
            }
        except Exception:
            pass
    return {"model": DEFAULT_MODEL, "region": DEFAULT_REGION}


def save_config(model: str, region: str) -> None:
    """Write model and region to ~/.config/swarm/config.toml atomically."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = f'[bedrock]\nmodel  = "{model}"\nregion = "{region}"\n'
    tmp = CONFIG_PATH.with_suffix(".toml.tmp")
    tmp.write_text(content)
    tmp.replace(CONFIG_PATH)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def get_bedrock_client(region: str):
    """Return a boto3 bedrock-runtime client using the credential chain.

    Never accepts credentials as arguments — always delegates to boto3.
    Raises ImportError if boto3 is not installed.
    Raises botocore.exceptions.NoCredentialsError if no credentials found.
    """
    import boto3  # local import — not available in base install
    return boto3.client("bedrock-runtime", region_name=region)


def test_connectivity(client, model: str) -> tuple[bool, str]:
    """Send a minimal converse request to verify model access.

    Returns (True, "OK") on success, or (False, error_message) on failure.
    """
    try:
        client.converse(
            modelId=model,
            messages=[{"role": "user", "content": [{"text": "ping"}]}],
            inferenceConfig={"maxTokens": 8, "temperature": 0.0},
        )
        return True, "OK"
    except Exception as e:
        # Preserve the original exception class name for actionable messages
        kind = type(e).__name__
        return False, f"{kind}: {e}"
