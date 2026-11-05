[Lot D — Valentino] Interface Web (feature [X1]).

Façade au-dessus du cœur CLI : le web appelle `sensai.core`, il ne
réimplémente pas la boucle de l'agent (ADR-0005). FastAPI est autorisé,
ce n'est pas un framework LLM.

Deux choses à afficher, pas une : la conversation, et le déroulé du
raisonnement (Thought / Action / Observation) tour par tour — c'est
l'exigence de transparence, et c'est ce qui se voit en démo.
