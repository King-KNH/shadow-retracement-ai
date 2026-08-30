# Shadow Retracement AI — Installation (une seule fois, étape par étape)

## Ce qui est testé et vérifié, bout en bout
- Détection (structure, order block, R:R) : testée sur 3,5 ans de données réelles
- Mémoire des setups (state.json) : testée sur 2 runs simulés, zéro doublon,
  zéro notification répétée
- Historique de prix persistant (history_*.csv) : testé bootstrap + mise à
  jour incrémentale, zéro doublon, fenêtre glissante correcte
- Tous les fichiers .py et .yml : syntaxe vérifiée, imports croisés vérifiés

## Ce qui ne peut être testé que chez toi (pas d'accès depuis mon environnement)
- L'appel réel à l'API Deriv (mon sandbox n'a pas accès à ce domaine)
- L'envoi Telegram réel
- L'appel à Gemini

## Comment ça fonctionne maintenant (après optimisation)

1. **Premier run** : aucun historique local -> récupère 60 jours de H1 et
   3,5 jours de M1 en une fois (bootstrap), les sauvegarde dans
   history_XAUUSD_H1.csv, history_XAUUSD_M1.csv, etc.

2. **Runs suivants (toutes les 15 min)** : charge l'historique déjà connu,
   ne demande à Deriv QUE les bougies nouvelles depuis la dernière fois,
   les ajoute, purge les plus anciennes (fenêtre glissante constante).
   Beaucoup plus léger que tout redemander à chaque fois.

3. **Mémoire des setups (state.json)** : chaque setup détecté est suivi
   individuellement (détecté -> déclenché -> clôturé). Tu n'es notifié
   qu'aux VRAIS changements, jamais en double.

## Étapes d'installation

1. Crée un dépôt GitHub PUBLIC, uploade tous ces fichiers en gardant la
   structure (le dossier .github/workflows/ se crée via "Create new file"
   en tapant le chemin complet, ex: .github/workflows/scan.yml)

2. Données de marché (Deriv) : aucun compte supplémentaire nécessaire,
   accès public aux données de marché.

3. Bot Telegram : @BotFather sur Telegram -> /newbot -> note le token.
   Envoie-lui un message, puis va sur
   https://api.telegram.org/bot<TON_TOKEN>/getUpdates pour ton chat_id

4. Clé Gemini gratuite (recommandé) : https://aistudio.google.com/apikey

5. GitHub -> Settings -> Secrets and variables -> Actions -> New repository
   secret. Ajoute ces 3 secrets :
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_CHAT_ID
   - GEMINI_API_KEY

6. Onglet "Actions" -> sélectionne "Shadow Retracement - Scan" ->
   "Run workflow" pour tester manuellement une première fois.

## Ce qui tourne automatiquement une fois configuré

- **scan.yml** : toutes les 15 minutes, lundi-vendredi (marché fermé le
  week-end). Détecte les nouveaux setups, suit ceux en cours (déclenché,
  TP, SL), notifie sur Telegram uniquement aux changements réels.

- **daily_digest.yml** : chaque jour à 12h heure du Cameroun.
  - En semaine : court commentaire sur le contexte de marché
  - Le week-end : réflexion stratégique, piste d'optimisation à explorer
    (idée en langage naturel uniquement — à valider par backtest avant
    adoption, aucune modification automatique de la stratégie)

## Si le premier test échoue
Le point le plus susceptible de poser souci au premier essai est la
connexion Deriv (jamais testée en conditions réelles depuis mon
environnement). Regarde le message d'erreur exact dans Actions -> clique
sur l'exécution en échec -> logs, et partage-le moi ici.
