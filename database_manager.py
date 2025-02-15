from sqlalchemy import MetaData, Table, select, insert, update, delete, and_, or_, not_
from sqlalchemy.engine import Engine, Result, Row
from typing import List, Optional
from datetime import datetime
import uuid

class DatabaseManager:
    """Gestionnaire des requêtes à la base de données."""

    def __init__(self, engine: Engine) -> None:
        self._engine: Engine = engine
        self._metadata: MetaData = MetaData()
        self._metadata.reflect(bind = self._engine)
        self._players_table: Table = self._metadata.tables["algo_players"]
        self._games_table: Table = self._metadata.tables["algo_games"]
        self._joint_table: Table = self._metadata.tables["algo_players_games"]
        self._current_player_table: Table = self._metadata.tables["algo_current_player"]
        self._initialize_current_player()

    def _execute_edit(self, query_list) -> None:
        with self._engine.connect() as connection:
            transaction = connection.begin()
            try:
                for query in query_list:
                    connection.execute(query)
                transaction.commit() # Valider la transaction
            except Exception as e:
                transaction.rollback() # Annuler en cas d'erreur
                print(f"Erreur lors de l'exécution des requêtes : {e}")
                raise

    def _initialize_current_player(self) -> None:
        query = (
            select(self._current_player_table)
        )
        with self._engine.connect() as connection:
            result: List[Row] = connection.execute(query).fetchall()
        if not result:
            db_timestamp: datetime = datetime.now().replace(microsecond=0)
            current_player_table_data: dict[str, str|int] = {
            "id": str(uuid.uuid4()),
            "riot_ign": "",
            "duration": 0,
            "updated_at": db_timestamp
        }
            query = (
                insert(self._current_player_table)
                .values(**current_player_table_data)
            )
            self._execute_edit([query])

    def get_players_in_queue(self) -> List[Row]:
        query = (
            select(self._players_table.c.riot_puuid, self._players_table.c.points_count)
            .where(self._players_table.c.is_queued)
        )
        with self._engine.connect() as connection:
            return connection.execute(query).fetchall()

    def get_previous_games(self, puuid: str) -> List[Row]:
        games_list_query = (
            select(self._joint_table.c.riot_game_id, self._joint_table.c.is_solo, self._joint_table.c.is_win)
            .where(self._joint_table.c.riot_puuid == puuid)
        ).subquery()
        query = (
            select(self._games_table, games_list_query.c.is_solo, games_list_query.c.is_win)
            .join(games_list_query, games_list_query.c.riot_game_id == self._games_table.c.riot_game_id)
            .order_by(self._games_table.c.game_date.desc())
        )
        with self._engine.connect() as connection:
            return connection.execute(query).fetchall()

    def update_current_player(self, ign: str, duration: int) -> None:
        query = (
            select(self._current_player_table)
        )
        with self._engine.connect() as connection:
            result: List[Row] = connection.execute(query).fetchone()
        db_timestamp: datetime = datetime.now().replace(microsecond=0)
        current_player_table_data: dict[str, str|int] = {
            "riot_ign": ign,
            "duration": duration,
            "updated_at": db_timestamp
        }
        query = (
            update(self._current_player_table)
            .where(self._current_player_table.c.id == result.id)
            .values(**current_player_table_data)
        )
        self._execute_edit([query])

    def update_solo_games_to_premade_games(self, puuid: str, games_ids_list: List[str]) -> None:
        query = (
            update(self._joint_table)
            .where(self._joint_table.c.riot_game_id.in_(games_ids_list))
            .where(self._joint_table.c.riot_puuid == puuid)
            .where(self._joint_table.c.is_solo)
            .values(is_solo = False)
        )
        self._execute_edit([query])

    def get_existing_games(self, games_ids_list: List[str]) -> List[Row]:
        query = (
            select(self._games_table)
            .where(self._games_table.c.riot_game_id.in_(games_ids_list))
        )
        with self._engine.connect() as connection:
            return connection.execute(query).fetchall()

    def check_existing_games(self, games_ids_list: List[str]) -> List[str]:
        query = (
            select(self._games_table.c.riot_game_id)
            .where(self._games_table.c.riot_game_id.in_(games_ids_list))
        )
        with self._engine.connect() as connection:
            result = connection.execute(query).fetchall()
        return [row.riot_game_id for row in result]

    def add_new_games(self, puuid: str, games: dict[str, dict[str, str|bool|float]]) -> None:
        games_table_query_list = []
        joint_table_query_list = []
        games_ids_list: List[str] = list(games.keys())
        existing_games_ids: List[str] = self.check_existing_games(games_ids_list)
        for game_id, game_data in games.items():
            if game_id in existing_games_ids:
                games_table_query = (
                    update(self._games_table)
                    .where(self._games_table.c.riot_game_id == game_id)
                    .values(
                        game_date=game_data["game_date"],
                        is_soloq=game_data["is_soloq"],
                        win_points_count=game_data["win_points_count"],
                        lose_points_count=game_data["lose_points_count"]
                    )
                )
                games_table_query_list.append(games_table_query)
            else:
                game_uuid = str(uuid.uuid4())
                games_table_data = {
                    key: value for key, value in game_data.items()
                    if key in {"game_date", "is_soloq", "win_points_count", "lose_points_count"}
                }
                games_table_data.update({
                    "id": game_uuid,
                    "riot_game_id": game_id
                })
                games_table_query = (
                    insert(self._games_table)
                    .values(**games_table_data)
                )
                games_table_query_list.append(games_table_query)
            joint_uuid = str(uuid.uuid4())
            joint_table_data = {
                key: value for key, value in game_data.items()
                if key in {"is_solo", "is_win"}
            }
            joint_table_data.update({
                "id": joint_uuid,
                "riot_game_id": game_id,
                "riot_puuid": puuid
            })
            joint_table_query = (
                insert(self._joint_table)
                .values(**joint_table_data)
            )
            joint_table_query_list.append(joint_table_query)
        self._execute_edit(games_table_query_list + joint_table_query_list)

    def update_player(self, puuid: str, points_count: float, points_count_recap: str) -> None:
        db_timestamp: datetime = datetime.now().replace(microsecond=0)
        query = (
            update(self._players_table)
            .where(self._players_table.c.riot_puuid == puuid)
            .values(is_queued = False, points_count = points_count, points_count_recap = points_count_recap, updated_at = db_timestamp)
        )
        self._execute_edit([query])
