"""Print the Markdown of one document (run inside the sensai-docs container).

Exit code 3: the file could not be turned into text. MarkItDown falls back to
its plain-text converter when a parser fails (measured on a broken PDF: it
printed the raw bytes), so that output is rejected here.
"""
import sys

from markitdown import MarkItDown

path = sys.argv[1]
# No plugin and no LLM: only the converters installed in the image.
text = MarkItDown(enable_plugins=False).convert(path).text_content or ""
with open(path, "rb") as handle:
    start = handle.read(64)
if "\x00" in text or (start and text.encode("utf-8", errors="ignore").startswith(start)):
    sys.stderr.write("the converter returned the raw file, not its text\n")
    sys.exit(3)
sys.stdout.write(text)
