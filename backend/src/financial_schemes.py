"""Tavily-backed discovery of official Indian financial and welfare schemes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MAX_RESULTS = 4

_PROFILE_ALIASES = {
    "income": "annual_income",
    "annual income": "annual_income",
    "family income": "annual_income",
    "employment status": "employment_status",
    "employment_status": "employment_status",
}


def _is_official_indian_government_url(url: str) -> bool:
    """Accept government domains without trusting similarly named sites."""
    host = (urlparse(url).hostname or "").lower()
    return host == "gov.in" or host.endswith(".gov.in")


def _is_scheme_result(title: str) -> bool:
    """Avoid presenting a generic government press index as a scheme."""
    normalized_title = title.strip().lower()
    return not normalized_title.startswith(
        ("press release page", "press note details", "press release")
    )


def _profile_for_evaluation(facts: dict[str, str]) -> dict[str, str]:
    """Keep only ordinary, non-identifying facts useful for broad matching."""
    useful_keys = {
        "state",
        "age",
        "occupation",
        "annual_income",
        "employment_status",
        "education",
        "gender",
        "category",
        "farmer",
    }
    return {
        _PROFILE_ALIASES.get(key.strip().lower(), key.strip().lower()): value.strip()
        for key, value in facts.items()
        if _PROFILE_ALIASES.get(key.strip().lower(), key.strip().lower()) in useful_keys
        and value.strip()
    }


def _number(value: str) -> int | None:
    match = re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:lakh|lakhs)?", value.lower())
    if not match:
        return None
    number = float(match.group().replace(",", "").replace("lakh", "").strip())
    return int(number * 100_000) if "lakh" in match.group() else int(number)


def _extract_criteria(text: str, state: str | None) -> dict[str, Any]:
    """Extract only unambiguous, explicitly stated rules from an official snippet."""
    lower = text.lower()
    eligibility_context = re.compile(
        r"\b(?:eligibility|eligible|who can apply|beneficiar(?:y|ies)|"
        r"target beneficiaries|eligible applicants|eligible beneficiaries|"
        r"requirements?|conditions?)\b"
    )
    sentences = re.split(r"(?<=[!?])\s+|(?<!rs)\.\s+", lower)
    relevant_text = " ".join(
        sentence for sentence in sentences if eligibility_context.search(sentence)
    )
    if not relevant_text:
        return {}
    criteria: dict[str, Any] = {}
    age_range = re.search(
        r"(?:age|aged)\s*(?:between)?\s*(\d{1,2})\s*(?:to|-|and)\s*(\d{1,2})",
        relevant_text,
    )
    if age_range:
        criteria["age_range"] = (int(age_range.group(1)), int(age_range.group(2)))
    income_match = re.search(
        r"(?:annual|family)?\s*income[^.]{0,80}?(?:not exceed|up to|less than|below|under|maximum of)\s*(?:rs\.?|inr)?\s*([\d,.]+\s*(?:lakh|lakhs)?)",
        relevant_text,
    )
    if income_match:
        criteria["income_max"] = _number(income_match.group(1))
    if state and (
        f"resident of {state.lower()}" in relevant_text
        or f"{state.lower()} resident" in relevant_text
        or f"{state.lower()} residents" in relevant_text
    ):
        criteria["state"] = state.lower()
    for field, phrases in {
        "employment_status": ("unemployed",),
        "education": ("graduate",),
        "gender": ("women", "woman", "female"),
        "farmer": ("farmer", "farmers"),
    }.items():
        if any(re.search(rf"\b{phrase}\b", relevant_text) for phrase in phrases):
            criteria[field] = phrases[0]
    return criteria


def _evaluate_eligibility(
    profile: dict[str, str], criteria: dict[str, Any]
) -> tuple[str, str, list[str]]:
    """Compare known facts with explicit criteria, never filling in unknown details."""
    if not criteria:
        return (
            "needs_official_verification",
            "The official source extract did not provide clear enough eligibility criteria "
            "for a reliable preliminary check.",
            [],
        )
    missing: list[str] = []
    mismatches: list[str] = []
    for field, expected in criteria.items():
        profile_field = {
            "age_range": "age",
            "income_max": "annual_income",
        }.get(field, field)
        value = profile.get(profile_field)
        if field == "farmer" and not value:
            value = profile.get("occupation")
        if not value:
            missing.append(profile_field)
            continue
        if field == "age_range":
            age = _number(value)
            if age is None:
                missing.append("age")
            elif not expected[0] <= age <= expected[1]:
                mismatches.append(
                    f"age must be between {expected[0]} and {expected[1]}"
                )
        elif field == "income_max":
            income = _number(value)
            if income is None:
                missing.append("annual_income")
            elif income > expected:
                mismatches.append(f"annual income must not exceed {expected}")
        elif field == "state":
            if value.lower() != expected:
                mismatches.append(f"residency requirement is {expected.title()}")
        elif expected not in value.lower():
            mismatches.append(f"requires {expected}")
    if mismatches:
        return (
            "appears_not_eligible",
            "The available profile does not match the listed criterion: "
            + "; ".join(mismatches)
            + ".",
            missing,
        )
    if missing:
        return (
            "needs_more_information",
            "A preliminary check needs: " + ", ".join(missing) + ".",
            missing,
        )
    return (
        "appears_eligible",
        "The available profile matches the explicitly listed criteria in this official "
        "source. Final eligibility requires official verification.",
        [],
    )


def _compact_text(value: object, limit: int = 550) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip()


def _result_text(item: dict[str, Any]) -> str:
    """Prefer Tavily's page extract over its short result snippet."""
    return _compact_text(item.get("raw_content") or item.get("content"), 4_000)


def _scheme_candidates_from_results(
    results: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Keep just enough non-sensitive context to revisit discovered schemes."""
    return [
        {
            "scheme_name": str(scheme.get("scheme_name") or ""),
            "source_url": str(
                scheme.get("source_url") or scheme.get("official_source_url") or ""
            ),
        }
        for scheme in results
        if scheme.get("scheme_name")
        and scheme.get("source_url", scheme.get("official_source_url"))
    ]


def _candidate_eligibility_query(candidate: dict[str, str]) -> str | None:
    """Target one saved scheme on its known official government domain."""
    scheme_name = _compact_text(candidate.get("scheme_name"), 120)
    host = (urlparse(candidate.get("source_url", "")).hostname or "").lower()
    if not scheme_name or not _is_official_indian_government_url(f"https://{host}"):
        return None
    return (
        f'"{scheme_name}" eligibility criteria who can apply beneficiaries '
        f"requirements conditions site:{host}"
    )


def _candidate_result_item(
    candidate: dict[str, str], response: dict[str, Any]
) -> dict[str, Any] | None:
    """Use only a result from the candidate's previously verified official domain."""
    candidate_host = (urlparse(candidate.get("source_url", "")).hostname or "").lower()
    for item in response["results"]:
        if not isinstance(item, dict):
            continue
        result_host = (urlparse(str(item.get("url", ""))).hostname or "").lower()
        if result_host == candidate_host and _is_official_indian_government_url(
            str(item.get("url", ""))
        ):
            return item
    return None


def _search_tavily(query: str, api_key: str) -> dict[str, Any]:
    payload = json.dumps(
        {
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": MAX_RESULTS,
            "include_answer": False,
            "include_raw_content": True,
        }
    ).encode("utf-8")
    request = Request(
        TAVILY_SEARCH_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        logger.warning("Tavily scheme search failed: %s", type(error).__name__)
        raise RuntimeError("Tavily search could not be completed") from error
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise RuntimeError("Tavily returned an invalid search response")
    return data


async def discover_financial_schemes(
    *,
    state: str | None,
    user_need: str | None,
    facts: dict[str, str] | None,
    check_eligibility: bool = False,
    scheme_candidates: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Search official sources and return only compact, voice-ready structured data."""
    retrieved_at = datetime.now(timezone.utc).isoformat()
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return {
            "status": "unavailable",
            "eligibility_check": check_eligibility,
            "reason": "The live scheme-search service is not configured.",
            "retrieved_at": retrieved_at,
            "schemes": [],
        }

    state = _compact_text(state, 80) or None
    profile = _profile_for_evaluation(facts or {})
    profile_terms = " ".join(profile.values())
    scope = f"{state} state" if state else "India nationwide"
    need = _compact_text(user_need, 160) or "financial welfare"
    candidate_items: list[tuple[dict[str, str], dict[str, Any] | None]] = []
    if check_eligibility and scheme_candidates:
        for candidate in scheme_candidates[:MAX_RESULTS]:
            query = _candidate_eligibility_query(candidate)
            if not query:
                continue
            try:
                response = await asyncio.to_thread(_search_tavily, query, api_key)
            except RuntimeError as error:
                return {
                    "status": "unavailable",
                    "eligibility_check": check_eligibility,
                    "reason": (
                        "Latest official scheme information could not be verified right "
                        "now. Do not provide scheme details from memory."
                    ),
                    "retrieved_at": retrieved_at,
                    "schemes": [],
                    "error": str(error),
                }
            candidate_items.append(
                (candidate, _candidate_result_item(candidate, response))
            )
    else:
        if check_eligibility:
            query = (
                f"official government {scope} scheme eligibility criteria {need} "
                f"{profile_terms} site:gov.in age income education employment residency"
            )
        else:
            query = (
                f"official government {scope} schemes {need} {profile_terms} "
                "site:gov.in benefit application"
            )
        try:
            response = await asyncio.to_thread(_search_tavily, query, api_key)
        except RuntimeError as error:
            return {
                "status": "unavailable",
                "eligibility_check": check_eligibility,
                "reason": (
                    "Latest official scheme information could not be verified right now. "
                    "Do not provide scheme details from memory."
                ),
                "retrieved_at": retrieved_at,
                "schemes": [],
                "error": str(error),
            }

    schemes: list[dict[str, Any]] = []
    if candidate_items:
        result_items = candidate_items
    elif check_eligibility and scheme_candidates:
        result_items = []
    else:
        result_items = [(None, item) for item in response["results"]]
    for candidate, item in result_items:
        if candidate and item is None:
            item = {
                "title": candidate["scheme_name"],
                "url": candidate["source_url"],
            }
        if item is None:
            continue
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", ""))
        title = _compact_text(
            candidate.get("scheme_name") if candidate else item.get("title"), 180
        )
        if not _is_official_indian_government_url(url) or not _is_scheme_result(title):
            continue
        summary = _result_text(item)
        criteria = _extract_criteria(summary, state)
        if check_eligibility:
            eligibility_status, reason, missing_information = _evaluate_eligibility(
                profile, criteria
            )
        else:
            eligibility_status = "needs_official_verification"
            reason = "This was a scheme-discovery search, not an eligibility check."
            missing_information = []
        schemes.append(
            {
                "scheme_name": title or "Official scheme page",
                "scope": "state-specific" if state else "nationwide",
                "state": state,
                "purpose_or_benefit": summary or "See the official source for details.",
                "relevant_eligibility_criteria": summary
                or "Not available in search result.",
                "official_criteria_found": criteria,
                "eligibility_status": eligibility_status,
                "reason": reason,
                "missing_information": missing_information,
                "source_url": url,
                "official_source_url": url,
                "source_title": title,
                "source_last_updated": item.get("published_date") or None,
                "retrieved_at": retrieved_at,
                "application_information": "Check the official source page for application details.",
            }
        )
        if len(schemes) >= MAX_RESULTS:
            break

    if not schemes:
        return {
            "status": "no_verified_results",
            "eligibility_check": check_eligibility,
            "reason": (
                "No relevant authoritative Indian government source was found for this "
                "search. Do not infer or invent scheme details."
            ),
            "retrieved_at": retrieved_at,
            "schemes": [],
        }
    result = {
        "status": "ok",
        "scope": scope,
        "eligibility_check": check_eligibility,
        "profile_fields_used": sorted(profile),
        "retrieved_at": retrieved_at,
        "schemes": schemes,
    }
    if not check_eligibility:
        result["scheme_candidates"] = _scheme_candidates_from_results(schemes)
    return result
