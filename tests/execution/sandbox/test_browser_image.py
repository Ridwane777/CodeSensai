"""The browser image definition must agree with the code that starts it."""
import re
from pathlib import Path

from sensai.execution.sandbox.config import BrowserConfig

DOCKERFILE = Path(__file__).resolve().parents[3] / "docker" / "browser" / "Dockerfile"


def instructions() -> str:
    lines = DOCKERFILE.read_text().splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def test_policy_hosts_match_the_hosts_the_code_allows():
    declared = re.findall(r"^ARG SEARCH_HOST_\d=(\S+)", instructions(), re.MULTILINE)
    assert tuple(declared) == BrowserConfig().search_hosts


def test_everything_but_the_search_host_is_blocked_by_policy():
    text = instructions()
    assert '"URLBlocklist": ["*"]' in text
    assert '"URLAllowlist": ["https://%s", "https://%s"]' in text
    assert '"JavascriptEnabled": false' in text


def test_image_cannot_run_anything_by_itself():
    text = instructions()
    assert not re.search(r"^(ENTRYPOINT|CMD)\b", text, re.MULTILINE)
    assert not re.search(r"^(COPY|ADD)\b", text, re.MULTILINE)  # no application code inside


def test_image_name_in_the_build_instructions_matches_the_config():
    header = DOCKERFILE.read_text()
    assert f"-t {BrowserConfig().image}" in header
