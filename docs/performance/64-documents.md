# Issue #64 — Lire et indexer les documents : essais réels

Décision : [ADR-0034](../decisions/0034-lire-tous-les-formats-de-fichier.md).

**Méthode** (2026-10-18). Client sur un portable Intel i7-1355U, Docker
29.9.1, image `sensai-docs` (MarkItDown 0.1.8, 659 Mo) construite
localement. Embeddings et modèle de chat sur le pod RunPod (Ollama 0.40.6,
`bge-m3`, `qwen3-coder:30b`).

Fichiers d'essai, dans un dossier temporaire hors du dépôt :
- `sujet.pdf` : un vrai sujet the school de 3,3 Mo, celui du projet Dashboard ;
- `cahier.docx`, `budget.xlsx`, `pitch.pptx` : générés avec les
  bibliothèques de l'image ;
- `plan.dwg` : un en-tête AutoCAD.

## 1. Conversion par `read_file`

| Fichier | Résultat | Temps |
| --- | --- | --- |
| `sujet.pdf` | 217 lignes de Markdown | 8,2 s |
| `cahier.docx` | « Exigence 1 : au moins deux user stories par feature. » | 3,0 s |
| `budget.xlsx` | Tableau Markdown (Poste, Coût mensuel) | 3,1 s |
| `pitch.pptx` | Titre et texte de la diapositive | 4,0 s |
| `plan.dwg` | « Generic AutoCAD drawing (306 bytes) », pas de lecteur, marche à suivre | 0,00 s |
| Page suivante de `sujet.pdf` | Réutilisée, sans nouvelle conversion | 0,000 s |

Le temps comprend le démarrage du conteneur et le chargement de MarkItDown.

## 2. L'agent sur le pod

Avec `sensai --no-rag`, donc sans l'aide du RAG :
- **« D'après sujet.pdf, quels langages et frameworks sont imposés ? »**
  L'agent appelle `read_file` (218 lignes) et répond : aucun n'est imposé
  (« free to use the languages and frameworks of your choice »), puis donne
  les recommandations, le port 8080, `/about.json` et docker-compose. Chaque
  affirmation a été retrouvée dans le texte converti.
- **« Que contient plan.dwg ? »** L'agent reçoit le type et la marche à
  suivre ; il explique comment ouvrir ou convertir le fichier, sans inventer
  de contenu.

## 3. Indexation par le RAG

Le même dossier, indexé avec la vraie conversion et `bge-m3`, interrogé avec
le RAG hybride et le reclassement de R2. **Aucune question ne nomme le
fichier.**

| Question | Premier passage | Bon ? |
| --- | --- | --- |
| Quels langages et frameworks sont imposés pour le projet ? | `sujet.pdf`, lignes 91-130 | ✅ contient « free to use the languages and frameworks » et la liste recommandée |
| Sur quel port doit tourner le serveur ? | `sujet.pdf`, ligne 121 | ✅ « MUST run on port 8080 » |
| Combien coûte le GPU par mois ? | `budget.xlsx` | ✅ le tableau (GPU RunPod : 17) |
| Combien de user stories faut-il par feature ? | `cahier.docx` | ✅ « au moins deux user stories par feature » |

- Première indexation : 4 documents, 11 passages, **29,5 s** (`plan.dwg`
  n'est pas indexé).
- Indexation suivante sans changement : **0,01 s**, aucun document reconverti.

## 4. Défauts trouvés par ces essais, corrigés

- Un fichier binaire qui contient des octets nuls se décode en UTF-8 :
  `read_file` le renvoyait comme du texte, avant ce changement. Il est
  désormais traité comme binaire (critère de Git : un octet nul dans les
  8 premiers Ko).
- `puremagic` donne au DWG le type `image/x-dwg` : l'agent recevait un
  conseil OCR absurde. Seules les images matricielles sont classées
  « image ».
- Sur un PDF abîmé, MarkItDown renvoie le fichier brut comme texte : le RAG
  l'aurait indexé. Ce cas est rejeté dans l'image (code de sortie 3) et côté
  agent.
- Les tests du CLI lançaient le vrai Docker : ils utilisent désormais un faux
  convertisseur.

## 5. Limites

- **Le temps :** de 3 à 8 s par conversion. Un projet avec beaucoup de
  documents allonge la première indexation.
- **La qualité de certains PDF :** sur ce sujet, des mots sont collés
  (« highlycustomizabledashboard »), un défaut connu de pdfminer. Le modèle
  a quand même compris, et la recherche a trouvé les bons passages.
- **Les numéros de ligne cités** pour un document sont ceux du Markdown
  converti, pas ceux des pages du PDF.
- **Pas d'OCR**, pas de description d'images, pas de transcription audio.
- **Un échantillon petit :** 4 questions sur 4 fichiers. C'est une
  vérification de fonctionnement, pas une mesure de qualité comme celles de
  R1 et R2.
