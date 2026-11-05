# Disposable document converter used by read_file (issue #64, ADR-0034):
# execution/sandbox/document_sandbox.py.
#
#   docker build -t sensai-docs:latest docker/docs
#
# MarkItDown (Microsoft, MIT) turns PDF, Word, PowerPoint, Excel, Outlook and
# EPUB files into Markdown. The container is started for one file and removed
# right after, with the hardening set by DocumentSandbox: no network,
# read-only root, no capabilities, memory / CPU / process / time limits, and
# the document mounted read-only.
FROM python:3.12-slim

# Pinned: the parsers are the attack surface, an upgrade is a deliberate change.
RUN pip install --no-cache-dir "markitdown[pdf,docx,pptx,xlsx,xls,outlook]==0.1.8"

COPY convert.py /opt/convert.py

USER 65534:65534
