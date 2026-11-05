# ADR-0023 — Accès à l'API web : jeton, écoute locale, un seul accès public

- **Statut** : Accepté (2026-11-01, validé par l'équipe)
- **Date** : 2026-10-14
- **Décideurs** : Valentino (Lot D)
- **Lot concerné** : D (impacte B pour les filtres de secrets, et le volet légal)

## Contexte
Écrit **après** les user stories [US-WEB-11, 13, 14 et 16](../architecture/web-api.md). Exposer l'agent sur le web,
c'est exposer l'**exécution de code** : [ADR-0005](0005-interface-web-facade.md) et le contrat du Lot A exigent
une authentification, mais `web-api.md` la laisse « à implémenter par le Lot D » sans mécanisme. Il faut le
choisir, avec une exception à traiter : la feature X3 demande un lien de partage **public, sans compte**.

## Options envisagées
| Option | Pour | Contre |
| --- | --- | --- |
| Aucune authentification, écoute locale seulement | Le plus simple | Refusé par le contrat du Lot A : tout programme local, ou toute page ouverte dans le navigateur de la développeuse, peut piloter l'agent |
| Compte et mot de passe, sessions par cookie | Familier, plusieurs utilisateurs | Un système de comptes entier à écrire et protéger (stockage de mots de passe, cookies, CSRF) pour un outil individuel |
| OAuth / SSO | Délègue l'identité | Dépendance à un fournisseur externe, inutilisable hors ligne, démesuré |
| **Jeton porteur généré au démarrage, écoute locale par défaut, origines autorisées fermées** | Simple, vérifiable, adapté à un usage individuel ; aucun secret stocké | Un seul utilisateur ; voir les inconvénients |

## Décision
1. Au démarrage, le serveur génère un **jeton aléatoire** (32 octets), l'affiche **une fois** dans la console et ne l'écrit jamais dans un fichier, un journal ni une URL. Toutes les routes de l'API, flux compris, le demandent dans l'en-tête `Authorization: Bearer`.
2. La comparaison est en temps constant ; un jeton absent, faux ou mal formé reçoit la **même** réponse `401`.
3. Le serveur écoute sur **la machine locale uniquement**. L'ouvrir au réseau demande une option explicite et un avertissement.
4. Les origines autorisées (CORS) sont **une liste fermée** ; jamais `*`. La documentation interactive de l'API est désactivée.
5. `GET /api/health` est la seule route sans jeton, et ne dit rien d'autre que « ok ».
6. `GET /api/config` ne renvoie jamais d'adresse Ollama, de jeton ni de chemin.
7. **Seule exception : le lien de partage** (X3). Désactivé par défaut, demandé explicitement, **jeton opaque distinct de l'identifiant de session**, lecture seule, révocable, à expiration annoncée, contenu filtré des secrets comme le flux.

## Conséquences
- ✅ Personne ne pilote l'agent sans le jeton, même depuis un autre onglet ou un autre programme du même poste, tant que le jeton n'a pas fui.
- ✅ Aucun secret n'est stocké par le serveur ; la surface publique se limite à une route de santé et aux liens de partage explicitement créés.
- ❌ **Un seul utilisateur**, pas de comptes ni de rôles. Plusieurs personnes sur un même serveur imposeraient une vraie authentification.
- ❌ **Le jeton est affiché dans la console et perdu à chaque redémarrage** : l'utilisateur doit le recopier. Le navigateur doit le garder en mémoire, ce qui l'expose à un script malveillant injecté dans la page.
- ❌ **L'écoute locale ne protège pas des autres utilisateurs du même poste** ni des programmes qui y tournent déjà.
- ❌ **Aucune limitation de débit** : un jeton de 32 octets ne se devine pas, mais rien n'empêche de saturer le serveur.
- ❌ **Le lien de partage est public par construction** : toute personne qui le reçoit lit la séance. C'est un risque pour les données personnelles, à traiter dans les documents légaux ; le filtrage des secrets réduit le risque sans le supprimer.
- ❌ **Le texte écrit par le modèle n'est pas filtré** : la passerelle ne voit que les outils. Si le modèle recopie un secret dans sa réponse, il apparaît dans le flux, l'export et le partage. Risque résiduel, à traiter avec le Lot B.
- Suivi : tester 401 sur chaque route (fait pour le prototype) ; `docs/legal/` à mettre à jour pour le partage. **Seuil de révision** : dès qu'une deuxième personne doit utiliser le même serveur.
