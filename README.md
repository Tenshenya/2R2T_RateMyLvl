# 2R2T_RateMyLVL
- L'usage de ce script est strictement réservé à la série de tournois 2R2T : https://2r2t.gg/
- Si vous ne faites pas partie de l'équipe 2R2T, cette page n'existe que dans un but de documentation.
- Le code n'est pas encore commenté (à venir) et le script opgg_scrapper.py n'a pas été réalisé par mes soins mais grâce à ChatGPT (merci à lui), une version rédigée manuellement sera faite dès que possible.

## Prérequis
- Python 3.10 ou supérieur
- Dépendances installables avec la commande "pip install -r requirements.txt"

## Information pour fonctionnement
L'adresse vers le fichier de configuration, la base de donnée, la clé API Riot Games ainsi que les données pour accéder aux proxies sont définis dans le script par des variables d'environnements suivantes :
- "CONFIG_2R2T_PATH"
- "DB_2R2T_PATH"
- "RIOT_API_KEY"
- "PROXY_USERNAME"
- "PROXY_PASSWORD"
- "PROXY_ADRESS"

## La base de données doit contenir les tables suivantes :
### algo_players
- id (uuid, primary key)
- riot_puuid (string)
- is_queued (bool, default = True)
- points_count (float, default = 0.0)
- points_count_recap (string)
- created_at (timestamp)
- updated_at (timestamp)

Lorsqu'un nouveau joueur est ajouté à la table, merci de respecter les defaults values indiquées ci-dessus.

### algo_games
- id (uuid, primary key)
- riot_game_id (string)
- game_date (string)
- is_soloq (bool)
- win_points_count (integer)
- lose_points_count (integer)

### algo_players_games
- id (uuid, primary key)
- riot_game_id (string, foreign key)
- riot_puuid (string, foreign key)
- is_solo (bool)
- is_win (bool)

### algo_current_player
- id (uuid, primary key)
- riot_ign (string)
- duration (integer)
- updated_at (timestamp)

## Lecture de la table algo_players
Un joueur dans la table est :
- En attente de traitement si son champ "is_queued" = True
- Traité avec succès si son champ "is_queued" = False et son champ "points_count" > 0.0
- Traité sans succès si son champ "is_queued" = False et son champ "points_count" = 0.0

## Informations sur les joueurs traités sans succès
Un traitement sans succès indique un nombre de games insuffisant en solo et/ou au total. Le nombre de games manquantes peut être déterminé par une lecture de la table algo_players_games avec un filtre sur le "riot_puuid".
- Le nombre de games dont le champ "is_solo" = True doit être supérieur ou égal à la clé "games_min_solo" du fichier de config
- Le nombre de games au total doit être supérieur ou égal à la clé "games_min_total" du fichier de config
