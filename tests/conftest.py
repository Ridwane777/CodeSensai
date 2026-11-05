"""Réglages communs à toute la suite de tests.

Un terminal qui exporte FORCE_COLOR (certains terminaux, la CI) fait écrire à
`rich` des codes de couleur même quand la sortie est capturée : le texte que
les tests cherchent (« prompts : system v3 ») se retrouvait coupé par ces
codes. La console de `sensai.ui` est créée à l'import ; on retire donc la
variable ici, avant que les tests n'importent le module.
"""
import os

os.environ.pop("FORCE_COLOR", None)
# La suite exerce team_task depuis le CLI, dont le projet est ce dépôt : sans ça, la
# chaîne d'équipe lancerait pytest sur ce dépôt, qui relancerait team_task… (ADR-0056).
os.environ["SENSAI_NO_PROJECT_TESTS"] = "1"

import pytest


@pytest.fixture(autouse=True)
def _parametres_de_generation_neutres():
    """Le CLI règle les paramètres de génération pour tout le processus (ADR-0057) :
    sans remise à zéro, un test qui lance le CLI les laisserait aux tests suivants."""
    from sensai.core.ollama_client import set_generation_options

    set_generation_options(None)
    yield
    set_generation_options(None)
