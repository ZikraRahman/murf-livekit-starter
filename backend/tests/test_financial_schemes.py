import asyncio
import json

import agent as agent_module
import financial_schemes

OFFICIAL_ELIGIBILITY_RESULT = {
    "results": [
        {
            "title": "Example Employment Scheme | Government of Bihar",
            "url": "https://state.bihar.gov.in/scheme",
            "content": (
                "Eligibility: Bihar residents aged 18 to 35 who are unemployed graduates "
                "and whose annual family income must not exceed Rs. 300000."
            ),
            "published_date": "2026-01-01",
        }
    ]
}


def _live_search(monkeypatch, result=OFFICIAL_ELIGIBILITY_RESULT) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(
        financial_schemes, "_search_tavily", lambda query, api_key: result
    )


def test_official_url_filter() -> None:
    assert financial_schemes._is_official_indian_government_url(
        "https://myscheme.gov.in/a"
    )
    assert not financial_schemes._is_official_indian_government_url(
        "https://gov.in.example/a"
    )
    assert not financial_schemes._is_scheme_result("Press Release Page")


def test_tavily_search_does_not_restrict_to_literal_gov_in(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def read(self) -> bytes:
            return b'{"results": []}'

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(financial_schemes, "urlopen", fake_urlopen)

    assert financial_schemes._search_tavily("Delhi schemes", "test-key") == {
        "results": []
    }
    assert "include_domains" not in captured["payload"]


def test_eligibility_uses_remembered_profile_and_matches_criteria(monkeypatch) -> None:
    _live_search(monkeypatch)
    result = asyncio.run(
        financial_schemes.discover_financial_schemes(
            state="Bihar",
            user_need=None,
            facts={
                "age": "25",
                "education": "graduate",
                "employment status": "unemployed",
                "state": "Bihar",
                "annual income": "200000",
            },
            check_eligibility=True,
        )
    )
    scheme = result["schemes"][0]
    assert result["eligibility_check"] is True
    assert result["profile_fields_used"] == [
        "age",
        "annual_income",
        "education",
        "employment_status",
        "state",
    ]
    assert scheme["eligibility_status"] == "appears_eligible"
    assert scheme["missing_information"] == []
    assert scheme["source_last_updated"] == "2026-01-01"


def test_eligibility_identifies_missing_required_profile_information(
    monkeypatch,
) -> None:
    _live_search(monkeypatch)
    result = asyncio.run(
        financial_schemes.discover_financial_schemes(
            state="Bihar",
            user_need=None,
            facts={
                "age": "25",
                "education": "graduate",
                "employment_status": "unemployed",
                "state": "Bihar",
            },
            check_eligibility=True,
        )
    )
    scheme = result["schemes"][0]
    assert scheme["eligibility_status"] == "needs_more_information"
    assert scheme["missing_information"] == ["annual_income"]


def test_eligibility_identifies_non_matching_profile(monkeypatch) -> None:
    _live_search(monkeypatch)
    result = asyncio.run(
        financial_schemes.discover_financial_schemes(
            state="Bihar",
            user_need=None,
            facts={
                "age": "45",
                "education": "graduate",
                "employment_status": "unemployed",
                "state": "Bihar",
                "annual_income": "200000",
            },
            check_eligibility=True,
        )
    )
    assert result["schemes"][0]["eligibility_status"] == "appears_not_eligible"


def test_eligibility_requires_official_verification_for_unclear_criteria(
    monkeypatch,
) -> None:
    _live_search(
        monkeypatch,
        {
            "results": [
                {
                    "title": "Example Scheme",
                    "url": "https://example.gov.in/scheme",
                    "content": "This scheme provides financial support to young people.",
                }
            ]
        },
    )
    result = asyncio.run(
        financial_schemes.discover_financial_schemes(
            state="Bihar", user_need=None, facts={"age": "25"}, check_eligibility=True
        )
    )
    assert result["schemes"][0]["eligibility_status"] == "needs_official_verification"


def test_eligibility_prefers_official_page_extract_over_search_snippet(
    monkeypatch,
) -> None:
    _live_search(
        monkeypatch,
        {
            "results": [
                {
                    "title": "Example Scheme | Bihar Government",
                    "url": "https://example.gov.in/scheme",
                    "content": "Financial support is available.",
                    "raw_content": (
                        "Eligibility: Bihar residents aged 18 to 35 with annual "
                        "family income not exceeding Rs. 300000."
                    ),
                }
            ]
        },
    )
    result = asyncio.run(
        financial_schemes.discover_financial_schemes(
            state="Bihar",
            user_need=None,
            facts={"age": "25", "state": "Bihar", "annual_income": "200000"},
            check_eligibility=True,
        )
    )
    scheme = result["schemes"][0]
    assert scheme["eligibility_status"] == "appears_eligible"
    assert scheme["source_url"] == "https://example.gov.in/scheme"


def test_eligibility_queries_each_saved_candidate_on_its_official_domain(
    monkeypatch,
) -> None:
    queries: list[str] = []
    candidates = [
        {
            "scheme_name": "Punjab Farmer Support Scheme",
            "source_url": "https://agri.punjab.gov.in/farmer-support",
        },
        {
            "scheme_name": "Punjab Worker Support Scheme",
            "source_url": "https://labour.punjab.gov.in/worker-support",
        },
    ]

    def fake_search(query: str, api_key: str) -> dict:
        queries.append(query)
        if "Farmer Support" in query:
            return {
                "results": [
                    {
                        "title": "Farmer Support",
                        "url": "https://agri.punjab.gov.in/farmer-support/criteria",
                        "raw_content": (
                            "Target beneficiaries: Punjab residents who are farmers "
                            "aged 18 to 60. Requirements: annual family income must not "
                            "exceed Rs. 500000."
                        ),
                    }
                ]
            }
        return {
            "results": [
                {
                    "title": "Worker Support",
                    "url": "https://labour.punjab.gov.in/worker-support/criteria",
                    "raw_content": "Who can apply: Punjab residents aged 18 to 60.",
                }
            ]
        }

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(financial_schemes, "_search_tavily", fake_search)
    result = asyncio.run(
        financial_schemes.discover_financial_schemes(
            state="Punjab",
            user_need=None,
            facts={
                "age": "40",
                "state": "Punjab",
                "occupation": "farmer",
                "annual_income": "300000",
            },
            check_eligibility=True,
            scheme_candidates=candidates,
        )
    )

    assert len(queries) == 2
    assert "Punjab Farmer Support Scheme" in queries[0]
    assert "site:agri.punjab.gov.in" in queries[0]
    assert "Punjab Worker Support Scheme" in queries[1]
    assert "site:labour.punjab.gov.in" in queries[1]
    assert result["schemes"][0]["scheme_name"] == "Punjab Farmer Support Scheme"
    assert result["schemes"][0]["eligibility_status"] == "appears_eligible"


def test_candidate_eligibility_reports_missing_profile_information(monkeypatch) -> None:
    _live_search(
        monkeypatch,
        {
            "results": [
                {
                    "title": "Farmer Support",
                    "url": "https://agri.punjab.gov.in/farmer-support/criteria",
                    "raw_content": (
                        "Who can apply: Punjab residents who are farmers aged 18 to 60."
                    ),
                }
            ]
        },
    )
    result = asyncio.run(
        financial_schemes.discover_financial_schemes(
            state="Punjab",
            user_need=None,
            facts={"state": "Punjab", "farmer": "farmer"},
            check_eligibility=True,
            scheme_candidates=[
                {
                    "scheme_name": "Punjab Farmer Support Scheme",
                    "source_url": "https://agri.punjab.gov.in/farmer-support",
                }
            ],
        )
    )

    scheme = result["schemes"][0]
    assert scheme["eligibility_status"] == "needs_more_information"
    assert scheme["missing_information"] == ["age"]


def test_candidate_eligibility_keeps_safe_fallback_for_ambiguous_criteria(
    monkeypatch,
) -> None:
    _live_search(
        monkeypatch,
        {
            "results": [
                {
                    "title": "Farmer Support",
                    "url": "https://agri.punjab.gov.in/farmer-support/criteria",
                    "raw_content": "Financial support is available to rural communities.",
                }
            ]
        },
    )
    result = asyncio.run(
        financial_schemes.discover_financial_schemes(
            state="Punjab",
            user_need=None,
            facts={"age": "40", "state": "Punjab", "farmer": "farmer"},
            check_eligibility=True,
            scheme_candidates=[
                {
                    "scheme_name": "Punjab Farmer Support Scheme",
                    "source_url": "https://agri.punjab.gov.in/farmer-support",
                }
            ],
        )
    )

    assert result["schemes"][0]["eligibility_status"] == "needs_official_verification"


def test_discovery_does_not_claim_to_be_an_eligibility_check(monkeypatch) -> None:
    _live_search(monkeypatch)
    result = asyncio.run(
        financial_schemes.discover_financial_schemes(
            state="Bihar", user_need=None, facts={"age": "25"}
        )
    )
    assert result["schemes"][0]["eligibility_status"] == "needs_official_verification"


def test_discovery_handles_tavily_failure(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(
        financial_schemes,
        "_search_tavily",
        lambda query, api_key: (_ for _ in ()).throw(RuntimeError("network down")),
    )
    result = asyncio.run(
        financial_schemes.discover_financial_schemes(
            state=None, user_need=None, facts={}, check_eligibility=True
        )
    )
    assert result["status"] == "unavailable"
    assert result["schemes"] == []


def test_candidate_eligibility_handles_tavily_failure(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(
        financial_schemes,
        "_search_tavily",
        lambda query, api_key: (_ for _ in ()).throw(RuntimeError("network down")),
    )
    result = asyncio.run(
        financial_schemes.discover_financial_schemes(
            state="Punjab",
            user_need=None,
            facts={},
            check_eligibility=True,
            scheme_candidates=[
                {
                    "scheme_name": "Punjab Farmer Support Scheme",
                    "source_url": "https://agri.punjab.gov.in/farmer-support",
                }
            ],
        )
    )

    assert result["status"] == "unavailable"
    assert result["schemes"] == []


def test_livekit_tool_reuses_day_four_memory(monkeypatch) -> None:
    remembered_facts = {"age": "25", "state": "Bihar", "annual_income": "200000"}
    received: dict[str, object] = {}

    async def fake_discover(**kwargs):
        received.update(kwargs)
        return {"status": "ok", "schemes": []}

    monkeypatch.setattr(
        agent_module, "get_user", lambda user_id: {"facts": remembered_facts}
    )
    monkeypatch.setattr(agent_module, "discover_financial_schemes", fake_discover)
    assistant = agent_module.Assistant(user_id="caller-1")
    tool = next(
        tool for tool in assistant.tools if tool._info.name == "find_financial_schemes"
    )

    asyncio.run(tool._func(assistant, None, check_eligibility=True))

    assert received["facts"] == remembered_facts
    assert received["state"] == "Bihar"
    assert received["check_eligibility"] is True


def test_livekit_tool_rechecks_schemes_discovered_earlier_in_the_call(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_discover(**kwargs):
        calls.append(kwargs)
        if kwargs["check_eligibility"]:
            return {"status": "ok", "schemes": []}
        return {
            "status": "ok",
            "schemes": [],
            "scheme_candidates": [
                {
                    "scheme_name": "Example Employment Scheme",
                    "source_url": "https://example.gov.in/scheme",
                }
            ],
        }

    monkeypatch.setattr(agent_module, "get_user", lambda user_id: {"facts": {}})
    monkeypatch.setattr(agent_module, "discover_financial_schemes", fake_discover)
    assistant = agent_module.Assistant(user_id="caller-1")
    tool = next(
        tool for tool in assistant.tools if tool._info.name == "find_financial_schemes"
    )

    asyncio.run(tool._func(assistant, None, state="Bihar"))
    asyncio.run(tool._func(assistant, None, check_eligibility=True))

    assert calls[1]["scheme_candidates"] == [
        {
            "scheme_name": "Example Employment Scheme",
            "source_url": "https://example.gov.in/scheme",
        }
    ]
