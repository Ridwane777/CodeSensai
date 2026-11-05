# Disposable Chromium used by the web search tool (execution/sandbox/browser_sandbox.py).
#
#   docker build -t sensai-browser:latest docker/browser
#
# The image holds no secret and no application code. It is started as a fresh
# container for each search, with the hardening options set by BrowserSandbox
# (non-root, no capabilities, read-only root, memory / process limits), and
# removed right after.
FROM debian:bookworm-slim

# Must match BrowserConfig.search_hosts: the only URLs the browser may open
# (DuckDuckGo HTML first, Bing as fallback: docs/decisions/0040-*.md).
ARG SEARCH_HOST_1=html.duckduckgo.com
ARG SEARCH_HOST_2=www.bing.com

RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Enterprise policy: every URL is blocked except the search host, and the
# browser cannot be turned into a download or sync client. This is a second
# layer behind --host-resolver-rules, which does not cover IP-literal URLs.
# It is also what turns JavaScript off: the --blink-settings=scriptEnabled=false
# flag makes --dump-dom print nothing.
RUN mkdir -p /etc/chromium/policies/managed \
    && printf '{\n\
  "URLBlocklist": ["*"],\n\
  "URLAllowlist": ["https://%s", "https://%s"],\n\
  "JavascriptEnabled": false,\n\
  "DownloadRestrictions": 3,\n\
  "DefaultPopupsSetting": 2,\n\
  "PasswordManagerEnabled": false,\n\
  "SyncDisabled": true,\n\
  "MetricsReportingEnabled": false,\n\
  "DnsOverHttpsMode": "off"\n\
}\n' "${SEARCH_HOST_1}" "${SEARCH_HOST_2}" > /etc/chromium/policies/managed/sensai.json

# No ENTRYPOINT and no CMD: the command is always given by BrowserSandbox.
