[Workstream D - Christopher] Web interface (feature [X1]).

A facade over the CLI core: the web layer calls `sensai.core`, it does not
reimplement the agent loop (ADR-0005). FastAPI is allowed, it is not an LLM
framework.

Two things to show, not one: the conversation, and the reasoning trace
(Thought / Action / Observation) turn by turn - that is the transparency
requirement, and it is what shows in a demo.
