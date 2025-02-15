import os
import asyncio
import aiohttp
from typing import Dict, List, Any, Optional
from utils import RequestError
import random

class APIManager:
    """
    Classe pour effectuer les requêtes à l'API de Riot Games.
    Les noms des variables peuvent ne pas correspondrent parfaitement aux noms utilisés ailleurs car il s'agit de recyclage.
    L'écologie, c'est important.
    """

    def __init__(self, api_key: str) -> None:
        self._key: str = api_key
        self.session: Optional[aiohttp.ClientSession] = None

    async def _arequests(self, url: str, timeout: float = random.uniform(2.5, 5), max_retries: int = 5) -> Any:
        """
        Méthode asynchrone pour envoyer les requêtes et gérer les erreurs.

        Args:
            url: URL de la requête.
            timeout: Temps d'attente en cas de rate limit.
            max_retries: Nombre maximal de tentatives en cas d'échec.

        Returns:
            La réponse JSON de la requête.
        """
        if self.session is None:
            self.session = aiohttp.ClientSession()
        headers: Dict[str, str] = {"X-Riot-Token": self._key}
        for attempt in range(max_retries):
            try:
                async with self.session.get(url, headers = headers) as response:
                    match response.status:
                        case 200:
                            return await response.json()
                        case 400:
                            return []
                        case 404:
                            return None
                        case 429:
                            await asyncio.sleep(timeout)
                            timeout *= 2
                        case _:
                            await asyncio.sleep(timeout)
                            timeout *= 2
            except ConnectionResetError:
                if self.session is not None and not self.session.closed:
                    await self.session.close()
                self.session = aiohttp.ClientSession()
                await asyncio.sleep(timeout)
                timeout *= 2
            except:
                await asyncio.sleep(timeout)
                timeout *= 2
        raise RequestError(f"Erreur HTTP après {max_retries} tentatives.", url = url, status_code = response.status)

    """
    Les méthodes suivantes sont des wrappers pour différents endpoints.
    Chaque méthode a ses propres arguments.
    """

    async def get_tag_from_puuid(self, puuid: str) -> Any:
        """
        Get player riot tag from puuid.

        Args:
            puuid: puuid of the player.
        """
        url = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-puuid/{puuid}"
        return await self._arequests(url)

    async def get_profile_from_puuid(self, puuid: str) -> Any:
        """
        Profil d'un joueur selon son puuid.

        Args:
            puuid: puuid du joueur.
        """
        url = f"https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        return await self._arequests(url)
    
    async def get_elo(self, summoner_id: str) -> Any:
        """
        Informations sur le classement d'un joueur selon son id.

        Args:
            id: id du joueur.
        """
        url = f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
        return await self._arequests(url)
    
    async def get_matches_list(
        self,
        puuid: str,
        update_time: Optional[str | int] = None,
        end_time: Optional[str | int] = None,
        queue: Optional[str | int] = None,
        index_start: Optional[str | int] = None,
        count: Optional[str | int] = None
    ) -> Any:
        """
        Liste de matchs pour un joueur à partir de son puuid.

        Args:
            puuid: puuid du joueur. (obligatoire)
            update_time: Timestamp le plus ancien.
            end_time: Timestamp le plus récent.
            queue: File considérée pour la requête.
            index_start: Numéro de la game à considérer depuis la dernière.
            count: Nombre de games à récupérer. (max 100)
        """
        url: str = f"https://europe.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?"
        if update_time:
            url += f"startTime={update_time}&"
        if end_time:
            url += f"endTime={end_time}&"
        if index_start:
            url += f"start={index_start}&"
        if count:
            url += f"count={count}"
        if url.endswith("&"):
            url = url[:-1]
        return await self._arequests(url)
    
    async def get_game_data(self, gameid: str) -> Any:
        """
        Informations d'une game à partir de son id.

        Args:
            gameid: id de la game.
        """
        url = f"https://europe.api.riotgames.com/lol/match/v5/matches/{gameid}"
        return await self._arequests(url)