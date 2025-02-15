import os
import json
from typing import Dict, List, Tuple, Any, Optional
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, Row
from database_manager import DatabaseManager
from api_manager import APIManager
from opgg_scrapper import get_previous_rank
from utils import RequestError
from collections import defaultdict
import asyncio
import math
import random

class Game:
    """Données d'une game."""

    def __init__(self, api_manager, game_id: str, is_new: bool, game_date: Optional[str] = None, is_soloq: Optional[bool] = None,
        win_points_count: Optional[int] = None, lose_points_count: Optional[int] = None, is_solo: Optional[bool] = None, is_win: Optional[bool] = None,
        players: Optional[List[str]] = None, enemy_players: Optional[List[str]] = None
    ) -> None:
        self.api_manager: APIManager = api_manager
        self.game_id: str = game_id
        self.is_new: bool = is_new
        self.game_date: Optional[str] = game_date
        self.is_soloq: Optional[bool] = is_soloq
        self.win_points_count: Optional[int] = win_points_count
        self.lose_points_count: Optional[int] = lose_points_count
        self.is_solo: Optional[bool] = is_solo
        self.is_win: Optional[bool] = is_win
        self.players: List[str] = [] if players is None else players # Pour verif premade.
        self.enemy_players: List[str] = [] if enemy_players is None else enemy_players # Pour points.

    def get_participant_value(self, solo_rank: dict[str, str]) -> float:
        tier: str = solo_rank["tier"]
        if tier in ["MASTER", "GRANDMASTER", "CHALLENGER"]: # Traitement pour Master, Grandmaster et Challenger.
            return 14.5 + solo_rank.get("leaguePoints", 0) / 200 # Master + 1 point tous les 200 LP.
        rank: str = solo_rank["rank"]
        tier_values: dict[str, int] = {"IRON": 1, "BRONZE": 3, "SILVER": 5, "GOLD": 7, "PLATINUM": 9, "EMERALD": 11, "DIAMOND": 13}
        rank_values: dict[str, float] = {"IV": -0.5, "III": 0.0, "II": 0.5, "I": 1.0}
        return tier_values[tier] + rank_values[rank] + solo_rank.get("leaguePoints", 0) / 200

    async def get_participant_solo_rank_value(self, participant: str) -> Optional[float]:
        try:
            participant: Any = await self.api_manager.get_profile_from_puuid(participant)
            participant_id = participant["id"]
            rank_data: Any = await self.api_manager.get_elo(participant_id)
            solo_rank: dict[str, str] = next((data for data in rank_data if data["queueType"] == "RANKED_SOLO_5x5"), None)
            return self.get_participant_value(solo_rank) if solo_rank else None
        except RequestError:
            raise
        except Exception:
            return None

    async def get_participant_old_solo_rank_value(self, participant: str) -> Optional[float]: # Scrapping via op.gg si début de saison.
        try:
            participant_data: Optional[Any] = await self.api_manager.get_tag_from_puuid(participant)
            participant_name: str = f"""{participant_data["gameName"]}#{participant_data["tagLine"]}"""
            solo_rank: dict[str, str] = await get_previous_rank(self.api_manager.session, participant_name)
            return self.get_participant_value(solo_rank) if solo_rank else None
        except RequestError:
            raise
        except Exception:
            return None

    async def add_points_count(self) -> bool:
        valid_players: int = 0
        total_value: float = 0
        tasks = []
        for participant in self.enemy_players:
            tasks.append(asyncio.create_task(self.get_participant_old_solo_rank_value(participant)))
            await asyncio.sleep(0.2)
        participants_values: List[float] = [task.result() for task in (await asyncio.wait(tasks, return_when = asyncio.FIRST_EXCEPTION))[0]]
        for participant_value in participants_values:
            if participant_value:
                valid_players += 1
                total_value += participant_value
        self.enemy_players.clear()
        if valid_players < 3:
            return False
        setattr(self, ("win_points_count" if self.is_win else "lose_points_count"), round(total_value / valid_players + 1e-10))
        return True

    def change_solo_to_premade(self) -> None:
        self.is_solo = False

    def remove_players(self) -> None:
        self.players.clear()

class Player:
    """Données d'un joueur."""

    def __init__(self, api_manager: APIManager, puuid: str, points_count: float) -> None:
        self.api_manager: APIManager = api_manager
        self.puuid: str = puuid
        self.points_count: float = points_count
        self.point_count_recap: Optional[str] = None
        self.premades_check: List[str] = []
        self.premades: List[str] = []
        self.solo_games: List[Game] = []
        self.premade_games: List[Game] = []

    def add_previous_games(self, previous_games: List[Row]) -> None:
        for game_db in previous_games:
            game: Game = Game(
                self.api_manager, game_db.riot_game_id, False, game_db.game_date, game_db.is_soloq,
                game_db.win_points_count, game_db.lose_points_count,
                game_db.is_solo, game_db.is_win, None, None
            )
            if game.is_solo:
                self.solo_games.append(game)
            else:
                self.premade_games.append(game)

    async def get_games_ids_list(self, update_time: int|str, end_time: Optional[int|str]) -> List[str]:
        full_games_ids_list: List[str] = []
        part_games_ids_list: Optional[List[str]] = None
        index_start: int = 0
        while part_games_ids_list != []:
            part_games_ids_list = await self.api_manager.get_matches_list(self.puuid, update_time = update_time,  end_time = end_time, index_start = index_start, count = 100)
            full_games_ids_list += part_games_ids_list
            index_start += 100
            await asyncio.sleep(random.uniform(0.2, 0.4))
        previous_games_ids = {game.game_id for game in self.solo_games + self.premade_games}
        cleared_full_games_ids_list: List[str] = [game_id for game_id in full_games_ids_list if game_id not in previous_games_ids]
        return cleared_full_games_ids_list

    async def update_premades(self, participant: str) -> None:
        lock = asyncio.Lock()
        if participant in self.premades:
            return
        elif participant in self.premades_check:
            async with lock:
                self.premades.append(participant)
        else:
            async with lock:
                self.premades_check.append(participant)

    async def update_previous_games(self) -> List[Game]:
        previous_solo_games_to_verify: List[Game] = []
        semaphore = asyncio.Semaphore(10)
        async def process_game(game):
            async with semaphore:
                print(f"\rNombre de games traitées : {len(self.solo_games) + len(self.premade_games)} ", end="")
                game_data: Any = await self.api_manager.get_game_data(game.game_id)
                solo_game_verif: bool = game.is_solo and not game.is_soloq
                for participant in game_data["metadata"]["participants"]:
                    if participant != self.puuid:
                        await self.update_premades(participant)
                        if solo_game_verif:
                            game.players.append(participant)
                if solo_game_verif:
                    return game
        tasks = []
        for game in self.solo_games + self.premade_games:
            tasks.append(asyncio.create_task(process_game(game)))
            await asyncio.sleep(0.05)
        if tasks:
            games: List[Game] = [task.result() for task in (await asyncio.wait(tasks, return_when = asyncio.FIRST_EXCEPTION))[0]]
            for game in games:
                if game:
                    previous_solo_games_to_verify.append(game)
        return previous_solo_games_to_verify

    async def analyze_game_data(self, game_data: Any) -> dict[str, bool|List[str]]:
        player_index = game_data["metadata"]["participants"].index(self.puuid)
        is_win = game_data["info"]["participants"][player_index]["win"]
        players = []
        enemy_players = []
        for participant in game_data["metadata"]["participants"]:
            if participant != self.puuid:
                participant_index = game_data["metadata"]["participants"].index(participant)
                players.append(participant)
                if game_data["info"]["participants"][participant_index]["win"] != is_win:
                    enemy_players.append(participant)
                await self.update_premades(participant)
        return {
            "is_win": is_win,
            "players": players,
            "enemy_players": enemy_players
    }

    async def create_new_game(self, game_data: Any, game_id: str, is_soloq: bool) -> Game:
        game_info: dict[str, bool|List[str]] = await self.analyze_game_data(game_data)
        return Game(
            self.api_manager,
            game_id,
            True,
            game_date = str(math.floor(game_data["info"]["gameCreation"] / 1000)),
            is_soloq = is_soloq,
            is_solo = True,
            is_win = game_info["is_win"],
            players = game_info["players"],
            enemy_players = game_info["enemy_players"]
        )

    async def add_existing_games(self, game_db: Row) -> Optional[Game]:
        print(f"\rNombre de games traitées : {len(self.solo_games) + len(self.premade_games)} ", end="")
        game_data: Any = await self.api_manager.get_game_data(game_db.riot_game_id)
        game_info: dict[str, bool|List[str]] = await self.analyze_game_data(game_data)
        if (game_info["is_win"] and game_db.win_points_count) or (not game_info["is_win"] and game_db.lose_points_count):
            game: Game = Game(
                self.api_manager, game_db.riot_game_id, True, game_db.game_date, game_db.is_soloq,
                game_db.win_points_count, game_db.lose_points_count, True, game_info["is_win"], game_info["players"], None
            )
            lock = asyncio.Lock()
            async with lock:
                self.solo_games.append(game)
            return game

    async def add_new_games(self, games_ids_list: List[str]) -> List[Game]:
        new_solo_games_to_verify: List[Game] = []
        semaphore = asyncio.Semaphore(10)
        lock = asyncio.Lock()
        async def process_game(game_id: str) -> Optional[Game]:
            async with semaphore:
                print(f"\rNombre de games traitées : {len(self.solo_games) + len(self.premade_games)} ", end="")
                try:
                    game_data: Any = await self.api_manager.get_game_data(game_id)
                    if game_data["info"]["queueId"] not in [400, 420, 430, 440, 480, 490]:
                        return None
                    is_soloq: bool = game_data["info"]["queueId"] == 420
                    game: Game = await self.create_new_game(game_data, game_id, is_soloq)
                    security_check: bool = await game.add_points_count()
                    if not security_check:
                        del game
                        return None
                    async with lock:
                        self.solo_games.append(game)
                    if not is_soloq:
                        return game
                except RequestError:
                    raise
                except Exception:
                    return None
        tasks = []
        for game_id in games_ids_list:
            tasks.append(asyncio.create_task(process_game(game_id)))
            await asyncio.sleep(random.uniform(1/3, 2/3))
        if tasks:
            games: List[Game] = [task.result() for task in (await asyncio.wait(tasks, return_when = asyncio.FIRST_EXCEPTION))[0]]
            for game in games:
                if game:
                    new_solo_games_to_verify.append(game)
        return new_solo_games_to_verify

    def move_solo_game_to_premade_games(self, game: Game) -> None:
        self.solo_games.remove(game)
        self.premade_games.append(game)
        game.change_solo_to_premade()
        game.remove_players()

    def premade_checking(self, solo_games_to_verify: List[Game]) -> None:
        games_to_move = []
        for game in solo_games_to_verify:
            if any(participant != self.puuid and participant in self.premades for participant in game.players):
                games_to_move.append(game)
        for game in games_to_move:
            self.move_solo_game_to_premade_games(game)
            solo_games_to_verify.remove(game)
 
    def sort_games_by_timestamp(self) -> None:
        self.solo_games.sort(key = lambda game: int(game.game_date), reverse = True)
        self.premade_games.sort(key = lambda game: int(game.game_date), reverse = True)

    def clear_games(self) -> None:
        self.solo_games.clear()
        self.premade_games.clear()

class Main:
    """Script principal."""

    def __init__(self, **config: int|float) -> None:
        database_path: str = os.environ.get("DB_2R2T_PATH")
        api_key: str = os.environ.get("RIOT_API_KEY")
        engine: Engine = create_engine(database_path)
        self.database_manager: DatabaseManager = DatabaseManager(engine)
        self.api_manager: APIManager = APIManager(api_key)
        self.config: Dict[str, int|float] = config

    def create_player(self, player_db: Row) -> None:
        self.player: Player = Player(self.api_manager, player_db.riot_puuid, player_db.points_count)
        previous_games: List[Row] = self.database_manager.get_previous_games(self.player.puuid)
        self.player.add_previous_games(previous_games)

    def verif_games_number(self, min_case: bool = True) -> Dict[str, bool]: # min = True pour le nombre minimum, False dans le cas d'une première update.
        if min_case:
            seuil_solo: int = self.config["games_min_solo"]
            seuil_total: int = self.config["games_min_total"]
        else:
            seuil_solo: int = self.config["games_min_total"]
            seuil_total: int = self.config["games_max_total"]
        return {
            "solo": len(self.player.solo_games) >= seuil_solo,
            "total": len(self.player.solo_games) + len(self.player.premade_games) >= seuil_total
        }

    def write_current_player_duration(self, ign: str, games_number: int) -> None:
        duration: int = round(games_number * 1.1)
        self.database_manager.update_current_player(ign, duration)

    async def verify_and_add_existing_games(self, games_ids_list: List[str], solo_games_to_verify: List[Game]) -> None:
        existing_games: List[Row] = self.database_manager.get_existing_games(games_ids_list) # Traitement des games joués par d'autres joueurs.
        if existing_games:
            semaphore = asyncio.Semaphore(10)
            async def add_existing_games_limiter(game_db: Row) -> Optional[Game]:
                async with semaphore:
                    return await self.player.add_existing_games(game_db)
            tasks = []
            for game_db in existing_games:
                tasks.append(asyncio.create_task(add_existing_games_limiter(game_db)))
                await asyncio.sleep(0.05)
            if tasks:
                games: List[Game] = [task.result() for task in (await asyncio.wait(tasks, return_when = asyncio.FIRST_EXCEPTION))[0]]
                for game in games:
                    if game:
                        if not game.is_soloq:
                            solo_games_to_verify.append(game)
                        if game.game_id in games_ids_list:
                            games_ids_list.remove(game.game_id)
                self.player.premade_checking(solo_games_to_verify)

    async def games_update(self) -> List[Game]:
        print("Nombre de games traitées : 0 ", end="")
        solo_games_to_verify: List[Game] = []
        profile: Any = await self.api_manager.get_tag_from_puuid(self.player.puuid)
        ign: str = f"""{profile["gameName"]}#{profile["tagLine"]}"""
        updated_at: int = (
            self.config["min_date"] if self.player.points_count < 0.5 else
            sorted(
                [int(game.game_date) for game in self.player.solo_games + self.player.premade_games], reverse = True
            )[self.config["games_min_total"] - 1] + 1 # Seulement les games + récentes que la dernière considérée dans le calcul.
        )
        games_ids_list: List[str] = await self.player.get_games_ids_list(updated_at, self.config["max_date"])
        self.write_current_player_duration(ign, len(games_ids_list))
        verification_min: Dict[str, bool] = self.verif_games_number()
        if games_ids_list or not verification_min["solo"] or not verification_min["total"]:
            solo_games_to_verify += await self.player.update_previous_games()
            await self.verify_and_add_existing_games(games_ids_list, solo_games_to_verify)
            for i in range(0, len(games_ids_list), 50):
                solo_games_to_verify += await self.player.add_new_games(games_ids_list[i:i+50])
                self.player.premade_checking(solo_games_to_verify)
                verification_max: Dict[str, bool] = self.verif_games_number(min_case = False)
                if self.player.points_count < 0.5 and verification_max["solo"] and verification_max["total"]:
                    break
                await asyncio.sleep(5) # Uniquement si utilisation de l'op.gg scrapper.
        return solo_games_to_verify

    async def ensure_minimum_games(self, solo_games_to_verify: List[Game]) -> None:
        verification_min: Dict[str, bool] = self.verif_games_number()
        while not verification_min["solo"] or not verification_min["total"]:
            games_ids_list = await self.player.get_games_ids_list(self.config["max_date"], None)
            if not games_ids_list:
                break
            games_ids_list.reverse()  # Plus ancien au plus récent
            for game_id in games_ids_list:
                solo_games_to_verify += await self.player.add_new_games([game_id])
                self.player.premade_checking(solo_games_to_verify)
                verification_min = self.verif_games_number()

    def clean_up_excess_games(self) -> None:
        all_games: List[Game] = self.player.solo_games + self.player.premade_games
        all_games.sort(key = lambda game: int(game.game_date), reverse = True)
        while len(self.player.solo_games) + len(self.player.premade_games) > self.config["games_min_total"]:
            game: Game = all_games.pop(0)
            if int(game.game_date) > self.config["max_date"]:
                if game.is_solo:
                    if len(self.player.solo_games) > self.config["games_min_solo"]:
                        self.player.solo_games.remove(game)
                else:
                    self.player.premade_games.remove(game)
            else:
                break

    def initialize_points_count(self, is_max_solo: bool) -> Tuple[dict[int, list[Game]], float]:
        if is_max_solo:
            solo_games_number: int = min(len(self.player.solo_games), self.config["games_min_total"])
            per_solo: float = solo_games_number / self.config["games_min_total"]
            premade_games_number: int = self.config["games_min_total"] - solo_games_number
        else:
            per_solo: float = max(
                len(self.player.solo_games) / (len(self.player.solo_games) + len(self.player.premade_games)),
                self.config["games_min_solo"] / self.config["games_min_total"]
            )
            solo_games_number: int = round(per_solo * self.config["games_min_total"])
            premade_games_number: int = self.config["games_min_total"] - solo_games_number
        games_list: List[Game] = self.player.solo_games[:solo_games_number] + self.player.premade_games[:premade_games_number]
        scaling_per_solo: float = self.config["scaling_per_solo_min"] + self.config["flat_per_solo_scaling"] * (3 * per_solo - 1)
        sorted_games: dict[int, list[Game]] = defaultdict(list)
        for game in games_list:
            if game.is_win:
                sorted_games[game.win_points_count].append(game)
            else:
                sorted_games[game.lose_points_count].append(game)
        return dict(sorted(sorted_games.items())), scaling_per_solo

    def get_tier_points_count_and_recap(self, tier: int, games_list: List[Game], scaling_per_solo: float, dis_tier: float = 1) -> Tuple[float, str]:
        number_factor: float = math.log(self.config["scaling_log"] * len(games_list) + self.config["flat_log"]) ** self.config["power_log"]
        solo_games: List[Game] = [game for game in games_list if game.is_solo]
        premade_games: List[Game] = [game for game in games_list if not game.is_solo]
        solo_games_number: int = len(solo_games)
        premade_games_number: int = len(premade_games)
        
        tier_per_solo: float = solo_games_number / len(games_list)
        solo_wins_number: int = len([game for game in solo_games if game.is_win])
        premade_wins_number: int = len([game for game in premade_games if game.is_win])
        solo_winrate: float = 0 if solo_wins_number == 0 else solo_wins_number / solo_games_number
        premade_winrate: float = 0 if premade_wins_number == 0 else premade_wins_number / premade_games_number
        winrate_diff: float = abs(solo_winrate - premade_winrate)
        premade_pond: float = max(
            1 - self.config["scaling_pond_max"] * (1 - 2 * abs(tier_per_solo - 0.5)),
            1 - winrate_diff * self.config["scaling_pond_max"] / self.config["seuil_pond_max"] * (1 - 2 * abs(tier_per_solo - 0.5))
        )
        solo_pond: float = 1 + (1 - premade_pond) / scaling_per_solo
        solo_winrate_factor: float = 1 if solo_winrate >= 0.5 else 1 + 2 * (solo_winrate - 0.5)
        premade_winrate_factor: float = 1 if premade_winrate >= 0.5 else 1 + 2 * (premade_winrate - 0.5)
        winrate_factor: float = (
                            (
                    1 + (self.config["scaling_winrate"] / dis_tier) * (
                    tier_per_solo * scaling_per_solo * solo_pond * solo_winrate_factor ** self.config["power_delta_winrate"] +
                    (1 - tier_per_solo) * premade_pond * premade_winrate_factor ** self.config["power_delta_winrate"]
                )
            ) ** (1 + self.config["scaling_tier_power"] * tier) - 1
        )
        tier_points_count: float = number_factor * winrate_factor 
        tier_recap: str = f"{tier:02X}{solo_games_number:02X}{premade_games_number:02X}{solo_wins_number:02X}{premade_wins_number:02X}"
        return tier_points_count, tier_recap

    def get_points_count_and_recap(
            self, games: dict[int, list[Game]], scaling_per_solo: float, points_count_recap: str,
            max_solo_points_count: Optional[float] = None, dis_tier_power: Optional[float] = None, dis_tier_factor: Optional[float] = None
        ) -> Tuple[float, str]:
        numerator: float = 0.0
        denominator: float = 0.0
        points_count_recap: str = points_count_recap
        dis_tier: float = 1.0
        for tier, games_list in games.items():
            if len(games_list) < self.config["games_min_tier"]:
                continue
            if max_solo_points_count:
                dis_tier: float = 1 + dis_tier_factor * (abs(max_solo_points_count - tier) + (max_solo_points_count - tier) * self.config["scaling_distier_dir"]) ** dis_tier_power
            tier_points_count, tier_recap = self.get_tier_points_count_and_recap(tier, games_list, scaling_per_solo, dis_tier = dis_tier)
            numerator += tier * tier_points_count
            denominator += tier_points_count
            points_count_recap += tier_recap
        points_count: float = numerator / denominator
        return points_count, points_count_recap

    def points_count_calculation(self) -> None:
        max_solo_games, max_solo_scaling_per_solo = self.initialize_points_count(is_max_solo = True)
        average_games, average_scaling_per_solo = self.initialize_points_count(is_max_solo = False)
        dis_tier_power: float = self.config["power_distier_min"] + self.config["flat_distier_power"] * (max_solo_scaling_per_solo - average_scaling_per_solo)
        dis_tier_factor: float = (
            (self.config["scaling_distier_min"] + self.config["flat_distier_scaling"] * (max_solo_scaling_per_solo - 2)) /
            ((13 - 13 * self.config["scaling_distier_dir"]) ** dis_tier_power)
        )
        max_solo_points_count, points_count_recap = self.get_points_count_and_recap(max_solo_games, max_solo_scaling_per_solo, points_count_recap = "")
        average_points_count, points_count_recap = self.get_points_count_and_recap(average_games, average_scaling_per_solo, points_count_recap = points_count_recap + "FF",
            max_solo_points_count = max_solo_points_count, dis_tier_power = dis_tier_power, dis_tier_factor = dis_tier_factor
        )
        final_points_count: float = round(max(max_solo_points_count, average_points_count), 1)
        self.player.points_count = final_points_count
        self.player.point_count_recap = points_count_recap

    def save_data(self, security_save: bool = False) -> None:
        old_premade_games_ids_to_verify: List[str] = [game.game_id for game in self.player.premade_games if not game.is_new and not game.is_solo]
        self.database_manager.update_solo_games_to_premade_games(self.player.puuid, old_premade_games_ids_to_verify)
        all_games: List[Game] = self.player.solo_games + self.player.premade_games
        new_games_to_save: dict[str, dict[str, str|bool|float]] = {
            game.game_id: {
                "game_date": game.game_date,
                "is_soloq": game.is_soloq,
                "win_points_count": game.win_points_count,
                "lose_points_count": game.lose_points_count,
                "is_solo": game.is_solo,
                "is_win": game.is_win
            }
            for game in all_games if game.is_new
        }
        self.database_manager.add_new_games(self.player.puuid, new_games_to_save)
        print("Games sauvegardées.")
        if not security_save:
            self.database_manager.update_player(self.player.puuid, self.player.points_count, self.player.point_count_recap)
            print("Joueur sauvegardé.")
        self.player.clear_games()
        self.write_current_player_duration("", 0)
        del self.player

    async def algo(self, player_db: Row) -> None:
        self.create_player(player_db)
        print(f"Joueur en cours : {self.player.puuid}")
        solo_games_to_verify: List[Game] = await self.games_update()
        await self.ensure_minimum_games(solo_games_to_verify)
        print(f"\rNombre de games traitées : {len(self.player.solo_games) + len(self.player.premade_games)} ", end="")
        self.clean_up_excess_games()
        self.player.sort_games_by_timestamp()
        for game in solo_games_to_verify:
            game.remove_players()
        del solo_games_to_verify
        print("\nRécupération des games terminées.")
        verification_min: Dict[str, bool] = self.verif_games_number()
        if verification_min["solo"] and verification_min["total"]:
            self.points_count_calculation()
        else:
            solo_games_number = min(len(self.player.solo_games), self.config["games_min_solo"])
            total_games_number = min(solo_games_number + len(self.player.premade_games), self.config["games_min_total"])
            print(f"""Manque de games : {solo_games_number}/{self.config["games_min_solo"]} games solo ; {total_games_number}/{self.config["games_min_total"]} games totales.""")
        self.save_data()

    async def run(self) -> None:
        players_in_queue: List[Row] = self.database_manager.get_players_in_queue()
        for player_db in players_in_queue:
            try:
                await self.algo(player_db)
            except RequestError as r:
                print(f"\nErreur sur une requête détectée : {r}")
                self.save_data(security_save = True)
                break
            except Exception as e:
                print(f"\nErreur sur le compte {player_db.riot_puuid} : {e}")
                if hasattr(self, "player"):
                    self.player.clear_games()
                    del self.player
                continue
            await asyncio.sleep(15) # Uniquement si utilisation de l'op.gg scrapper.

async def main_loop(main: Main) -> None:
    while True:
        await main.run()
        await asyncio.sleep(150) # 2 minutes 30 de pause.

if __name__ == "__main__":
    with open(os.getenv("CONFIG_2R2T_PATH"), "r", encoding = "utf-8") as file:
        config: Dict[str, int|float] = json.load(file)
    main: Main = Main(**config)
    asyncio.run(main_loop(main))