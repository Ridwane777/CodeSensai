"""BrowserSandbox logic with a fake Docker client: no daemon, no Chromium image."""
import base64

from sensai.execution.sandbox.browser_sandbox import BrowserSandbox
from sensai.execution.sandbox.config import BrowserConfig

from .fakes import FakeClient, FakeContainer, broken_client


def bing_link(url):
    encoded = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return f"https://www.bing.com/ck/a?!&amp;&amp;p=abc&amp;ptn=3&amp;u=a1{encoded}&amp;ntb=1"


def results_page(*urls):
    blocks = "".join(
        f'<li class="b_algo"><h2><a href="{bing_link(u)}">T{i}</a></h2>'
        f'<div class="b_caption"><p>snippet {i}</p></div></li>'
        for i, u in enumerate(urls)
    )
    return f'<html><body><ol id="b_results">{blocks}</ol></body></html>'.encode()


NO_RESULTS = b'<html><body><ol id="b_results"><li class="b_no">No results</li></ol></body></html>'


def search(container, query="python asyncio", **kwargs):
    client = FakeClient(container)
    outcome = BrowserSandbox(client=client).search(query, **kwargs)
    return outcome, client, container


def test_search_returns_plain_results():
    outcome, _, container = search(FakeContainer(stdout=results_page("https://a.org/", "https://b.org/")))

    assert outcome.ok is True
    assert [r.url for r in outcome.results] == ["https://a.org/", "https://b.org/"]
    assert outcome.results[0].snippet == "snippet 0"
    assert container.started and container.removed


def test_result_count_is_capped():
    urls = [f"https://site{i}.org/" for i in range(30)]
    outcome, _, _ = search(FakeContainer(stdout=results_page(*urls)), max_results=3)
    assert len(outcome.results) == 3

    outcome, _, _ = search(FakeContainer(stdout=results_page(*urls)), max_results=999)
    assert len(outcome.results) == 10


def test_empty_results_are_a_success_not_an_error():
    outcome, _, _ = search(FakeContainer(stdout=NO_RESULTS))
    assert outcome.ok is True and outcome.results == []


def test_container_is_locked_down():
    _, client, _ = search(FakeContainer(stdout=results_page("https://a.org/")))
    kwargs = client.created_with

    assert kwargs["user"] == "65534:65534"
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges"]
    assert kwargs["mem_limit"] == kwargs["memswap_limit"]
    assert kwargs.get("privileged") is None
    for forbidden in ("volumes", "binds", "devices", "network_mode", "pid_mode", "ipc_mode"):
        assert forbidden not in kwargs


def test_browser_can_only_resolve_the_search_host():
    _, client, _ = search(FakeContainer(stdout=results_page("https://a.org/")))
    command = client.created_with["command"]

    assert command[0] == "chromium"
    assert (
        "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE html.duckduckgo.com , EXCLUDE www.bing.com"
        in command
    )
    # --dump-dom prints nothing with it; JavaScript is off through the image policy.
    assert "--blink-settings=scriptEnabled=false" not in command
    assert "--dump-dom" in command


def test_browser_presents_itself_as_a_regular_browser_not_headless():
    _, client, _ = search(FakeContainer(stdout=results_page("https://a.org/")))
    command = client.created_with["command"]

    agents = [arg for arg in command if arg.startswith("--user-agent=")]
    assert len(agents) == 1
    assert "Mozilla/5.0" in agents[0]
    assert "HeadlessChrome" not in agents[0]


def test_query_travels_as_one_url_argument_never_through_a_shell():
    _, client, _ = search(FakeContainer(), query='x"; rm -rf / #')
    command = client.created_with["command"]

    assert command[-1].startswith("https://www.bing.com/search?q=")
    assert " " not in command[-1] and '"' not in command[-1]


def test_invalid_query_never_starts_a_container():
    client = FakeClient()
    outcome = BrowserSandbox(client=client).search("   ")

    assert outcome.error_type == "InvalidQuery"
    assert client.created_with == {}


def test_timeout_kills_the_container():
    outcome, _, container = search(FakeContainer(hang=True), timeout_s=3)

    assert outcome.error_type == "Timeout"
    assert container.killed and container.removed
    assert container.wait_timeout == 3.0


def test_timeout_is_capped():
    _, _, container = search(FakeContainer(stdout=NO_RESULTS), timeout_s=10_000)
    # No results: the fallback engine runs too, on what is left of the same budget.
    assert 0 < container.wait_timeout <= BrowserConfig().max_timeout_s


def test_out_of_memory_is_reported():
    outcome, _, _ = search(FakeContainer(exit_code=137, oom=True))
    assert outcome.error_type == "OOMKilled"


def test_browser_crash_is_reported():
    outcome, _, _ = search(FakeContainer(exit_code=1))
    assert outcome.error_type == "BrowserError" and "code 1" in outcome.error_message


def test_bot_wall_is_reported_as_blocked():
    page = b"<html><body><div id='b_captcha'>Please solve the captcha</div></body></html>"
    outcome, _, _ = search(FakeContainer(stdout=page))
    assert outcome.error_type == "SearchBlocked"


def test_empty_dump_is_reported_as_an_empty_page_not_as_unreachable():
    for dump in (b"", b"  \n\t "):
        outcome, _, _ = search(FakeContainer(stdout=dump))
        assert outcome.error_type == "SearchEmptyPage"
        assert "empty page" in outcome.error_message


def test_browser_error_page_means_the_engine_was_unreachable():
    page = b"<html><body><h1>This site can't be reached</h1>ERR_NAME_NOT_RESOLVED</body></html>"
    outcome, _, _ = search(FakeContainer(stdout=page))
    assert outcome.error_type == "SearchUnavailable"
    assert "could not be reached" in outcome.error_message


def test_page_blocked_by_the_policy_is_reported_as_unreachable():
    page = b"<html><body>ERR_BLOCKED_BY_ADMINISTRATOR</body></html>"
    outcome, _, _ = search(FakeContainer(stdout=page))
    assert outcome.error_type == "SearchUnavailable"


def test_unknown_page_is_reported_as_unexpected():
    page = b"<html><body><h1>Welcome</h1><p>Something else entirely</p></body></html>"
    outcome, _, _ = search(FakeContainer(stdout=page))
    assert outcome.error_type == "SearchUnexpectedPage"
    assert "not a results page" in outcome.error_message


def test_results_page_that_mentions_captcha_is_still_results():
    page = (
        b'<ol id="b_results"><li class="b_algo"><h2><a href="https://a.org/">captcha</a></h2>'
        b'<div class="b_caption"><p>how a captcha works</p></div></li></ol>'
    )
    outcome, _, _ = search(FakeContainer(stdout=page))
    assert outcome.ok is True and [r.url for r in outcome.results] == ["https://a.org/"]


def test_missing_image_tells_how_to_build_it():
    client = FakeClient(image_present=False)
    outcome = BrowserSandbox(client=client).search("python")

    assert outcome.error_type == "ImageMissing"
    assert "docker build" in outcome.error_message
    assert client.pulled == []  # a local image has no registry to pull from


def test_docker_failure_is_an_outcome_not_an_exception():
    outcome = BrowserSandbox(client=broken_client()).search("python")
    assert outcome.ok is False and outcome.error_type == "SandboxError"


def test_container_is_removed_even_when_reading_the_dump_fails():
    class BadLogs(FakeContainer):
        def logs(self, stdout=True, stderr=True):
            raise OSError("socket closed")

    container = BadLogs()
    outcome = BrowserSandbox(client=FakeClient(container)).search("python")

    assert outcome.error_type == "SandboxError"
    assert container.removed is True


def test_oversized_dump_is_cut_before_parsing():
    config = BrowserConfig(max_output_bytes=10)
    client = FakeClient(FakeContainer(stdout=results_page("https://a.org/")))
    outcome = BrowserSandbox(config=config, client=client).search("python")

    assert outcome.error_type == "SearchUnexpectedPage"  # the cut page no longer looks like results


# --- Moteur de repli (ADR-0040) -----------------------------------------------------------

DDG_RESULTS = (
    b'<html><body><div class="result results_links web-result"><h2 class="result__title">'
    b'<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fddg.example%2F&amp;rut=x">'
    b'DDG</a></h2><a class="result__snippet" href="#">from duckduckgo</a></div></body></html>'
)
DDG_WALL = b'<html><body><div class="anomaly-modal">Unusual traffic</div></body></html>'


def engines_run(*containers, **kwargs):
    client = FakeClient()
    client.sequence = list(containers)
    outcome = BrowserSandbox(client=client).search("python asyncio", **kwargs)
    return outcome, [c["command"][-1] for c in client.all_created]


def test_duckduckgo_is_tried_first_and_kept_when_it_answers():
    outcome, urls = engines_run(FakeContainer(stdout=DDG_RESULTS))
    assert outcome.ok and [r.url for r in outcome.results] == ["https://ddg.example/"]
    assert urls == ["https://html.duckduckgo.com/html/?q=python+asyncio"]


def test_bing_takes_over_when_duckduckgo_blocks():
    outcome, urls = engines_run(FakeContainer(stdout=DDG_WALL),
                                FakeContainer(stdout=results_page("https://bing.example/")))
    assert outcome.ok and [r.url for r in outcome.results] == ["https://bing.example/"]
    assert [u.split("/")[2] for u in urls] == ["html.duckduckgo.com", "www.bing.com"]


def test_bing_takes_over_when_duckduckgo_finds_nothing():
    empty_ddg = b'<html><body><div class="no-results">No results.</div></body></html>'
    outcome, urls = engines_run(FakeContainer(stdout=empty_ddg),
                                FakeContainer(stdout=results_page("https://bing.example/")))
    assert [r.url for r in outcome.results] == ["https://bing.example/"]
    assert len(urls) == 2


def test_when_every_engine_fails_the_last_failure_is_reported():
    outcome, urls = engines_run(FakeContainer(stdout=DDG_WALL), FakeContainer(stdout=b""))
    assert not outcome.ok and outcome.error_type == "SearchEmptyPage"
    assert len(urls) == 2


def test_no_fallback_when_the_image_is_missing():
    client = FakeClient(image_present=False)
    outcome = BrowserSandbox(client=client).search("python")
    assert outcome.error_type == "ImageMissing" and client.all_created == []


def test_the_fallback_shares_the_time_budget(monkeypatch):
    from sensai.execution.sandbox import browser_sandbox

    clock = iter([0.0, 0.0, 0.0, 0.0, 42.0, 42.0, 42.0, 42.0])
    monkeypatch.setattr(browser_sandbox.time, "monotonic", lambda: next(clock, 42.0))
    outcome, urls = engines_run(FakeContainer(stdout=DDG_WALL),
                                FakeContainer(stdout=results_page("https://bing.example/")),
                                timeout_s=45)
    # 45 s of budget, 42 s spent: less than MIN_ATTEMPT_S left, Bing is not started.
    assert len(urls) == 1 and outcome.error_type == "SearchBlocked"
