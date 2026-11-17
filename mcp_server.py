#!/usr/bin/env python3

import csv
import io
import re
import urllib.parse

from typing import Optional, List, Dict, Any

import httpx
from fastmcp import FastMCP


mcp = FastMCP("LeetCode Company Questions")


GITHUB_RAW_BASE = (
    "https://raw.githubusercontent.com/"
    "liquidslr/leetcode-company-wise-problems/main"
)

GITHUB_API_TREE = (
    "https://api.github.com/repos/"
    "liquidslr/leetcode-company-wise-problems/git/trees/main"
)


TIMEFRAME_MAP = {
    "30 days": "1. Thirty Days.csv",
    "1 month": "1. Thirty Days.csv",
    "thirty days": "1. Thirty Days.csv",

    "3 months": "2. Three Months.csv",
    "three months": "2. Three Months.csv",

    "6 months": "3. Six Months.csv",
    "six months": "3. Six Months.csv",

    "more than 6 months": "4. More Than Six Months.csv",
    ">6 months": "4. More Than Six Months.csv",

    "all": "5. All.csv",
    "all time": "5. All.csv",
}

DEFAULT_TIMEFRAME = "5. All.csv"


# In-memory caches
CACHE_COMPANIES: List[str] = []
CACHE_CSVS: Dict[str, str] = {}


async def get_all_companies(
    client: httpx.AsyncClient
) -> List[str]:

    global CACHE_COMPANIES

    if CACHE_COMPANIES:
        return CACHE_COMPANIES

    response = await client.get(GITHUB_API_TREE)
    response.raise_for_status()

    data = response.json()

    CACHE_COMPANIES = sorted(
        [
            item["path"]
            for item in data.get("tree", [])
            if item["type"] == "tree"
            and not item["path"].startswith(".")
        ],
        key=str.lower
    )

    return CACHE_COMPANIES


def resolve_company_name(
    query: str,
    available_companies: List[str]
) -> Optional[str]:

    query_norm = query.strip().lower()

    # Exact match
    exact = [
        company
        for company in available_companies
        if company.lower() == query_norm
    ]

    if exact:
        return exact[0]

    # Substring match
    matches = [
        company
        for company in available_companies
        if query_norm in company.lower()
    ]

    # Return only unambiguous matches
    if len(matches) == 1:
        return matches[0]

    return None


def resolve_timeframe_filename(
    timeframe: Optional[str]
) -> str:

    if not timeframe:
        return DEFAULT_TIMEFRAME

    return TIMEFRAME_MAP.get(
        timeframe.strip().lower(),
        DEFAULT_TIMEFRAME
    )


async def fetch_company_csv(
    client: httpx.AsyncClient,
    company: str,
    filename: str
) -> Optional[str]:

    cache_key = f"{company}/{filename}"

    if cache_key in CACHE_CSVS:
        return CACHE_CSVS[cache_key]

    encoded_company = urllib.parse.quote(company, safe="")
    encoded_filename = urllib.parse.quote(filename, safe="")

    url = (
        f"{GITHUB_RAW_BASE}/"
        f"{encoded_company}/{encoded_filename}"
    )

    response = await client.get(url)

    if response.status_code == 404:
        return None

    response.raise_for_status()

    CACHE_CSVS[cache_key] = response.text

    return response.text


@mcp.tool()
async def get_company_leetcode_questions(
    company: Optional[str] = None,
    difficulty: Optional[str] = None,
    topic: Optional[str] = None,
    timeframe: Optional[str] = None,
    limit: int = 10,
    min_frequency: float = 0.0,
) -> List[Dict[str, Any]]:

    """
    Retrieve company-wise LeetCode questions.

    Args:
        company:
            Company name, e.g. Amazon, Google, Meta.

        difficulty:
            EASY, MEDIUM, or HARD.

        topic:
            Topic filter, e.g. Graph, Array, Dynamic Programming.

        timeframe:
            30 days, 3 months, 6 months,
            more than 6 months, or all.

        limit:
            Maximum number of questions.

        min_frequency:
            Minimum frequency score (0-100).
    """

    if limit < 1 or limit > 100:
        raise ValueError("Limit must be between 1 and 100.")

    if difficulty:
        difficulty = difficulty.strip().upper()

        if difficulty not in {"EASY", "MEDIUM", "HARD"}:
            raise ValueError(
                "Difficulty must be EASY, MEDIUM, or HARD."
            )

    if not 0 <= min_frequency <= 100:
        raise ValueError(
            "Minimum frequency must be between 0 and 100."
        )

    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers={"User-Agent": "LeetCode-FastMCP"}
    ) as client:

        available_companies = await get_all_companies(client)

        if company:

            resolved = resolve_company_name(
                company,
                available_companies
            )

            if not resolved:
                raise ValueError(
                    f"Company '{company}' not found or ambiguous. "
                    "Use list_available_companies to find its name."
                )

            target_companies = [resolved]

        else:

            defaults = [
                "Google",
                "Meta",
                "Amazon",
                "Microsoft",
                "Apple"
            ]

            target_companies = [
                c for c in defaults
                if c in available_companies
            ]

        csv_file = resolve_timeframe_filename(timeframe)

        all_questions: Dict[str, Dict[str, Any]] = {}

        for comp in target_companies:

            content = await fetch_company_csv(
                client,
                comp,
                csv_file
            )

            if not content and csv_file != DEFAULT_TIMEFRAME:

                content = await fetch_company_csv(
                    client,
                    comp,
                    DEFAULT_TIMEFRAME
                )

            if not content:
                continue

            reader = csv.DictReader(
                io.StringIO(content)
            )

            for row in reader:

                diff = (row.get("Difficulty") or "").strip()
                title = (row.get("Title") or "").strip()
                link = (row.get("Link") or "").strip()
                topics = (row.get("Topics") or "").strip()

                if not title:
                    continue

                try:
                    freq = float(
                        re.sub(
                            r"[^\d.]",
                            "",
                            row.get("Frequency") or "0"
                        )
                    )
                except ValueError:
                    freq = 0.0

                try:
                    acc_val = float(
                        row.get("Acceptance Rate") or "0"
                    )

                    acc_rate = (
                        f"{acc_val * 100:.1f}%"
                        if acc_val <= 1
                        else f"{acc_val:.1f}%"
                    )

                except ValueError:
                    acc_rate = "N/A"

                # Apply filters

                if difficulty and diff.upper() != difficulty:
                    continue

                if freq < min_frequency:
                    continue

                if topic and topic.strip().lower() not in topics.lower():
                    continue

                key = title.lower()

                if key not in all_questions:

                    all_questions[key] = {
                        "title": title,
                        "difficulty": diff,
                        "frequency": freq,
                        "acceptance_rate": acc_rate,
                        "link": link,
                        "topics": [
                            t.strip()
                            for t in topics.split(",")
                            if t.strip()
                        ],
                        "companies": [comp],
                    }

                else:

                    question = all_questions[key]

                    if comp not in question["companies"]:
                        question["companies"].append(comp)

                    if freq > question["frequency"]:
                        question["frequency"] = freq

        results = sorted(
            all_questions.values(),
            key=lambda q: q["frequency"],
            reverse=True
        )

        return results[:limit]


@mcp.tool()
async def list_available_companies(
    search: Optional[str] = None
) -> List[str]:

    """
    List all supported companies.

    Args:
        search:
            Optional substring to filter company names.
    """

    async with httpx.AsyncClient(
        timeout=20.0,
        headers={"User-Agent": "LeetCode-FastMCP"}
    ) as client:

        companies = await get_all_companies(client)

        if search:
            return [
                company
                for company in companies
                if search.lower() in company.lower()
            ]

        return companies


if __name__ == "__main__":
    mcp.run()
