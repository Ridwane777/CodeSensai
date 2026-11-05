# ADR-0034 — Lire et indexer n'importe quel format de fichier : identification par le contenu, conversion MarkItDown dans la sandbox, réponse honnête sinon

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-18
- **Décideurs** : Ridwane (lot C) ; à valider avec Méric (lot B), dont l'outil `read_file` et la sandbox sont touchés
- **Lot concerné** : C (issue #64) ; B (`tools/read_file_tool.py`, sandbox)

## Contexte
Issue #64, issue de l'US-R1-4 : quand on interroge l'agent sur un fichier
qui n'est pas du texte (le sujet en PDF, un cahier des charges en `.docx`, un
tableau `.xlsx`), il doit lire le contenu ou dire précisément quoi faire,
jamais l'inventer. Aujourd'hui, `read_file` renvoie seulement « Not a UTF-8
text file (binary?) », et l'indexation du RAG liste les PDF et documents
bureautiques ignorés avec un conseil (`UNSUPPORTED_FORMATS`). `pypdf` n'est
utilisé nulle part.

L'objectif à long terme : lire le contenu, quel que soit le format.

Ce qui se fait ailleurs :
- les agents de code convertissent le document en texte ou en Markdown avant
  de le lire. Claude Code lit les PDF de base, et on lui ajoute des
  « skills » de conversion (pdfplumber, MinerU) ; OpenHands intègre une
  conversion des PDF ;
- MarkItDown (Microsoft, MIT) convertit en Markdown, pour les LLM : PDF,
  docx, pptx, xlsx, xls, EPUB, HTML, ipynb, msg, ZIP, images (métadonnées)
  et audio, avec des dépendances à la carte et des plugins.

Contraintes :
- **La sécurité.** pypdf a eu plusieurs failles en 2025-2026 : un PDF piégé
  peut provoquer une boucle infinie ou consommer 1 Go de mémoire
  (CVE-2026-59936, CVE-2026-57204, CVE-2025-66019). La pratique recommandée
  (Dangerzone) est d'analyser les documents dans un conteneur isolé, sans
  réseau.
- **Notre sandbox** (ADR-0012, `python:3.12-slim`) n'a ni réseau ni accès aux
  fichiers du projet.
- **Le nombre d'outils.** Avec M4, ajouter un outil a fait chuter les appels
  structurés de `read_file` à 1/5 (#78) : chaque outil de plus perturbe
  qwen3-coder.

## Options envisagées

**Où brancher la lecture**

| Option | Pour | Contre |
| --- | --- | --- |
| Un nouvel outil `explain_format` (ce qu'écrit l'issue) | Aucun changement à `read_file` | Le modèle doit penser à l'appeler ; un outil de plus, ce qui a fait régresser M4 |
| **Dans `read_file`** (retenu) | Le modèle fait ce qu'il fait déjà ; aucun outil de plus | Modifie un fichier du lot B |

**Avec quoi convertir**

| Option | Pour | Contre |
| --- | --- | --- |
| pypdf seul (BSD-3) | Léger, Python pur | PDF seulement ; plus faible sur les mises en page en colonnes ; failles récentes |
| pdfplumber (MIT) | Bons tableaux | PDF seulement |
| PyMuPDF / PyMuPDF4LLM | Très rapide, Markdown structuré | **AGPL-3.0** : licence commerciale nécessaire pour un produit fermé (business plan) |
| Docling (IBM), Marker, MinerU | Mise en page, OCR | Lourds (modèles, torch) ; surdimensionnés |
| **MarkItDown (MIT), extras `pdf`, `docx`, `pptx`, `xlsx`, `xls`, `outlook`** (retenu) | Un seul outil pour la plupart des formats courants ; conçu pour les LLM ; plugins | Dépendances plus nombreuses (pdfminer.six, pdfplumber, mammoth, lxml, openpyxl…) ; qualité moyenne sur les PDF complexes |

**Quand convertir : à la demande seulement, ou aussi à l'indexation du RAG**

| Option | Pour | Contre |
| --- | --- | --- |
| Seulement quand l'agent appelle `read_file` | Aucun coût à l'indexation | Une question qui ne nomme pas le fichier (« quels frameworks sont imposés ? ») ne trouve jamais le sujet en PDF |
| **Aussi à l'indexation du RAG** (retenu) | C'est ce que font les RAG de documents : LlamaIndex (`SimpleDirectoryReader`), AnythingLLM et PrivateGPT indexent PDF, docx, xlsx, pptx par défaut ; c'est ce que demande l'US-R1-4 | De 3 à 8 s par document à la première indexation ; Docker requis pour en profiter |

Les indexeurs de code (Cursor) s'en tiennent au code, mais CodeSensei doit
aussi répondre sur les documents du projet (US-R1-4).

**Où exécuter la conversion**

| Option | Pour | Contre |
| --- | --- | --- |
| Dans le processus de l'agent | Simple, rapide | Un fichier piégé peut bloquer ou saturer l'agent |
| **Dans la sandbox, image `sensai-docs`** (retenu) | Un fichier piégé n'atteint qu'un conteneur jetable, sans réseau, à la mémoire, au CPU et au temps limités | Docker obligatoire ; une image de 659 Mo à construire ; de 3 à 8 s par conversion (mesuré) |

## Décision
`read_file` traite tout fichier en quatre niveaux :

1. **Identifier le type par le contenu** (octets magiques, `puremagic`,
   Python pur, MIT), pas par l'extension.
2. **Texte** (code, Markdown, CSV, JSON, XML…) : lu directement, comme
   aujourd'hui.
3. **Format de document connu** : converti en Markdown par MarkItDown, dans un
   conteneur `sensai-docs`. Le fichier y est copié en lecture seule, le
   conteneur n'a pas de réseau, et les limites de la sandbox s'appliquent.
4. **Tout le reste**, ou une conversion vide : une réponse qui nomme le type
   détecté, donne la taille et la marche à suivre (`ocrmypdf` pour un PDF
   scanné, une exportation pour un format propriétaire, la commande pour
   construire l'image si elle manque). Jamais de contenu inventé.

Aucun nouvel outil n'est proposé au modèle.

**À l'indexation du RAG**, les PDF, docx, pptx, xlsx, xls, EPUB et msg de
moins de 20 Mo sont convertis par le même conteneur, puis découpés comme du
Markdown : ses numéros de ligne sont ceux que `read_file` renvoie pour le
même fichier. Un document n'est reconverti que s'il a changé. Si la
conversion échoue (Docker absent, image non construite, PDF scanné), le
document est listé avec la marche à suivre, comme avant, et réessayé à
l'indexation suivante.

Garde-fou mesuré : quand un parseur échoue, MarkItDown renvoie le fichier
brut ; une sortie qui reproduit le début du fichier ou contient un octet nul
est rejetée (dans l'image et côté agent).

## Conséquences
- ✅ L'agent lit les formats bureautiques courants, et pour tous les autres il sait ce qu'est le fichier et quoi faire.
- ✅ Le RAG retrouve un document sans qu'on le nomme : 4 questions sur 4 trouvent le bon passage (PDF, docx, xlsx), mesuré sur le pod (`docs/performance/64-documents.md`).
- ✅ Un document piégé ne touche pas l'agent : même principe que Dangerzone.
- ✅ Aucun outil de plus pour le modèle ; une licence MIT compatible avec un produit commercial.
- ❌ Docker et l'image `sensai-docs` sont nécessaires pour le niveau 3 ; sans eux, l'agent ne donne que le niveau 4.
- ❌ Une conversion coûte de 3 à 8 s, mesuré (démarrage du conteneur et chargement de MarkItDown ; les pages suivantes du même fichier sont réutilisées), et l'image pèse 659 Mo.
- ❌ Les images ne donnent que leurs métadonnées : qwen3-coder n'est pas multimodal, et l'OCR (Tesseract) est reporté. L'audio n'est pas transcrit. Les PDF scannés demandent `ocrmypdf`.
- ❌ La qualité dépend de MarkItDown : les PDF à mise en page complexe (colonnes, tableaux imbriqués) sortent imparfaits. Mesuré sur un sujet the school : des mots collés (« highlycustomizabledashboard »), un défaut connu de pdfminer.
- ❌ La première indexation d'un projet riche en documents est plus longue : 29,5 s pour 4 documents (mesuré). Les suivantes ne reconvertissent que les documents modifiés.
- ❌ Les documents indexés peuvent partir au serveur de modèle comme le code : un sujet ou un cahier des charges confidentiel est concerné au même titre.
- ❌ Une nouvelle dépendance Python, `puremagic` (MIT, sans dépendance), et une image Docker de plus à construire.
- ❌ Modifie `read_file` (lot B) et l'outillage de la sandbox : à valider avec Méric.
- Suivi : tests sur des fichiers d'exemple (PDF, docx, xlsx, fichier inconnu, fichier vide) ; essai réel avec le sujet du projet ; mesure du temps de conversion. À revoir si un modèle multimodal est adopté (images), ou si la qualité des PDF ne suffit pas (Docling).
