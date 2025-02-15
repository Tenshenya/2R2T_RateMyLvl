import os
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from typing import List
from utils import RequestError
import random

username: str = os.environ.get("PROXY_USERNAME")
password: str = os.environ.get("PROXY_PASSWORD")
proxy_adress: str = os.environ.get("PROXY_ADRESS")
proxy: str = "https://user-%s:%s@%s" % (username, password, proxy_adress)

async def format_rank(rank_text: str) -> str:
    rank_text = rank_text.upper()
    parts = rank_text.split(" ", 1)
    roman_map = {1: "I", 2: "II", 3: "III", 4: "IV"}
    if len(parts) == 2 and parts[1].isdigit():
        number = int(parts[1])
        if number in roman_map:
            parts[1] = roman_map[number]
        return {"tier": parts[0], "rank": parts[1]}
    if len(parts) == 1: # Master+
        return {"tier": parts[0], "rank": "I"}

async def get_previous_rank(
    session: aiohttp.ClientSession, name: str, region: str = "euw",
    conditions: List[str] = ["2024 S3", "2024 S2", "2024 S1"], timeout: int = random.uniform(5, 10), max_retries: int = 5
    ) -> str:
    encoded_name = name.replace(" ", "%20").replace("#", "-")
    url = f"https://{region}.op.gg/summoners/{region}/{encoded_name}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.5615.137 Safari/537.36"
    }
    if session is None:
        session = aiohttp.ClientSession()
    for attempt in range(max_retries):
        try:
            async with session.get(url, headers = headers, proxy = proxy) as response:
                if response.status != 200:
                    if response.status == 429:
                        await asyncio.sleep(timeout)
                        timeout *= 2
                    else:
                        raise RequestError(f"Erreur HTTP {response.status} lors de la requête.", url = url, status_code = response.status)
                else:
                    soup = BeautifulSoup(await response.text(), "html.parser")
                    # Cas 1 : Premier chemin avec condition "2024 S3"
                    condition_1 = soup.select_one(
                        "div:nth-of-type(4) > table > tbody > tr:nth-of-type(1) > td:nth-of-type(1) > b"
                    )
                    if condition_1:
                        condition_1_text = condition_1.text
                        if any(cond in condition_1_text for cond in conditions):
                            rank_1 = soup.select_one(
                                "div:nth-of-type(4) > table > tbody > tr:nth-of-type(1) > td:nth-of-type(2) > div > div > span"
                            )
                            lp_1 = soup.select_one(
                                "div:nth-of-type(4) > table > tbody > tr:nth-of-type(1) > td:nth-of-type(3) > div"
                            )
                            if rank_1 and lp_1:
                                rank = await format_rank(rank_1.text.strip()) 
                                rank["leaguePoints"] = int(lp_1.text.strip().replace(",", "")) # LP supérieurs à 999.
                                return rank
                    # Cas 2 : Deuxième chemin avec condition "2024 S3"
                    condition_2 = soup.select_one(
                        "div:nth-of-type(2) > table > tbody > tr:nth-of-type(1) > td:nth-of-type(1) > b"
                    )
                    if condition_2:
                        condition_2_text = condition_2.text
                        if any(cond in condition_2_text for cond in conditions):
                            rank_2 = soup.select_one(
                                "div:nth-of-type(2) > table > tbody > tr:nth-of-type(1) > td:nth-of-type(2) > div > div > span"
                            )
                            lp_2 = soup.select_one(
                                "div:nth-of-type(2) > table > tbody > tr:nth-of-type(1) > td:nth-of-type(3) > div"
                            )
                            if rank_2 and lp_2:
                                rank = await format_rank(rank_2.text.strip()) 
                                rank["leaguePoints"] = int(lp_2.text.strip().replace(",", "")) # LP supérieurs à 999.
                                return rank
                    # Si aucun rang ou LP correspondant n'est trouvé
                    return None
        except ConnectionResetError:
            if session is not None and not session.closed:
                await session.close()
            session = aiohttp.ClientSession()
            await asyncio.sleep(timeout)
            timeout *= 2
        except:
            await asyncio.sleep(timeout)
            timeout *= 2
    raise RequestError(f"Erreur HTTP {response.status} lors de la requête.", url = url, status_code = response.status)