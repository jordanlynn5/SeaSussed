"""Tests for the WebSocket /voice endpoint and VoiceSession."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from google.genai import types

from main import app
from models import (
    Alternative,
    PageAnalysis,
    ProductInfo,
    ScoreBreakdown,
    ScoreFactor,
    SustainabilityScore,
)
from voice_session import _filter_by_intent, _find_product_url, _sort_key_for_intent

MOCK_BASE64_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

MOCK_PRODUCT_INFO = ProductInfo(
    is_seafood=True,
    species="Atlantic cod",
    wild_or_farmed="wild",
    fishing_method="Trawl",
    origin_region="North Atlantic",
    certifications=["MSC"],
)

MOCK_SCORE = SustainabilityScore(
    score=72,
    grade="B",
    breakdown=ScoreBreakdown(biological=15, practices=18, management=22, ecological=17),
    alternatives=[
        Alternative(
            species="Pacific Salmon",
            score=85,
            grade="A",
            reason="Well-managed wild fishery",
            from_page=True,
        ),
    ],
    alternatives_label="Better alternatives",
    explanation="Atlantic cod from the North Atlantic scores a B.",
    score_factors=[
        ScoreFactor(
            category="biological",
            score=15,
            max_score=20,
            explanation="Moderate vulnerability",
            tip=None,
        ),
    ],
    product_info=MOCK_PRODUCT_INFO,
)


def _make_tool_call_response() -> types.LiveServerMessage:
    """Create a LiveServerMessage with an analyze_current_product tool call."""
    return types.LiveServerMessage(
        tool_call=types.LiveServerToolCall(
            function_calls=[
                types.FunctionCall(
                    id="call-123",
                    name="analyze_current_product",
                    args={},
                ),
            ],
        ),
    )


class MockSession:
    """Mock Gemini Live API async session."""

    def __init__(
        self, responses: list[types.LiveServerMessage] | None = None
    ) -> None:
        self.responses = responses or []
        self.send_realtime_input = AsyncMock()
        self.send_tool_response = AsyncMock()
        self.send_client_content = AsyncMock()
        self._block = asyncio.Event()

    async def receive(self) -> AsyncIterator[types.LiveServerMessage]:
        for r in self.responses:
            yield r
        # Block until cancelled (simulates waiting for Gemini)
        await self._block.wait()

    def unblock(self) -> None:
        """Unblock the receive loop (used to simulate session end)."""
        self._block.set()


def _mock_genai_client(session: MockSession) -> MagicMock:
    """Create a mock genai Client whose aio.live.connect yields the session."""
    client = MagicMock()

    @asynccontextmanager
    async def mock_connect(**kwargs: object) -> AsyncIterator[MockSession]:
        yield session

    client.aio.live.connect = mock_connect
    return client


# ── Test 1: Connect and stop ──────────────────────────────────────────────


@patch("voice_session.get_genai_client")
def test_voice_websocket_connects_and_stops(mock_get_client: MagicMock) -> None:
    session = MockSession()
    mock_get_client.return_value = _mock_genai_client(session)

    with TestClient(app) as client:
        with client.websocket_connect("/voice") as ws:
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "connecting"}

            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "listening"}

            ws.send_json({"type": "stop"})
            # Connection should close cleanly — no exception


# ── Test 2: Tool call → screenshot → score_result ────────────────────────


@patch("voice_session.get_health_info", return_value=None)
@patch("voice_session.generate_template_content", return_value=("Atlantic cod scores a B.", []))
@patch("voice_session.compute_score")
@patch("voice_session.analyze_screenshot", new_callable=AsyncMock)
@patch("voice_session.get_genai_client")
def test_voice_analyze_tool_call(
    mock_get_client: MagicMock,
    mock_analyze: AsyncMock,
    mock_compute: MagicMock,
    mock_template: MagicMock,
    mock_health: MagicMock,
) -> None:
    mock_analyze.return_value = PageAnalysis(
        page_type="single_product", products=[MOCK_PRODUCT_INFO]
    )
    mock_compute.return_value = (
        ScoreBreakdown(biological=15, practices=18, management=22, ecological=17),
        72,
        "B",
    )

    session = MockSession(responses=[_make_tool_call_response()])
    mock_get_client.return_value = _mock_genai_client(session)

    with TestClient(app) as client:
        with client.websocket_connect("/voice") as ws:
            # 1. connecting status
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "connecting"}

            # 2. listening status
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "listening"}

            # 3. analyzing status (from tool_call handler)
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "analyzing"}

            # 4. request_screenshot
            msg = ws.receive_json()
            assert msg["type"] == "request_screenshot"

            # 5. Send screenshot data
            ws.send_json({
                "type": "screenshot",
                "data": MOCK_BASE64_PNG,
                "url": "https://example.com/cod",
                "page_title": "Atlantic Cod Fillet",
                "related_products": ["Pacific Salmon", "Alaskan Halibut"],
            })

            # 6. Receive score_result
            msg = ws.receive_json()
            assert msg["type"] == "score_result"
            assert msg["score"]["grade"] == "B"
            assert msg["score"]["score"] == 72

            # 7. speaking status
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "speaking"}

            # Clean up
            ws.send_json({"type": "stop"})

    mock_analyze.assert_awaited_once_with(
        MOCK_BASE64_PNG, "https://example.com/cod", "Atlantic Cod Fillet"
    )
    mock_compute.assert_called_once()


# ── Test 3: Screenshot timeout ────────────────────────────────────────────


@patch("voice_session.SCREENSHOT_TIMEOUT_S", 0.1)
@patch("voice_session.get_genai_client")
def test_voice_screenshot_timeout(mock_get_client: MagicMock) -> None:
    session = MockSession(responses=[_make_tool_call_response()])
    mock_get_client.return_value = _mock_genai_client(session)

    with TestClient(app) as client:
        with client.websocket_connect("/voice") as ws:
            # 1. connecting
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "connecting"}

            # 2. listening
            msg = ws.receive_json()
            assert msg["type"] == "status"

            # 3. analyzing status
            msg = ws.receive_json()
            assert msg["type"] == "status"

            # 4. request_screenshot — but we never respond
            msg = ws.receive_json()
            assert msg["type"] == "request_screenshot"

            # 6. After timeout, Gemini gets error response and sends speaking status
            # The tool_response is sent with error, so we should get "speaking"
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "speaking"}

            # Clean up
            ws.send_json({"type": "stop"})


# ── Test 4: Session cleanup on disconnect ─────────────────────────────────


@patch("voice_session.get_genai_client")
def test_voice_session_cleanup_on_disconnect(mock_get_client: MagicMock) -> None:
    session = MockSession()
    mock_get_client.return_value = _mock_genai_client(session)

    # Client connects then disconnects — server should clean up without exception
    with TestClient(app) as client:
        with client.websocket_connect("/voice") as ws:
            # connecting
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "connecting"}
            # listening
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "listening"}
            ws.close()


# ── Test 5: Duplicate search_store suppressed ─────────────────────────────


def _make_search_tool_call(query: str = "salmon") -> types.LiveServerMessage:
    """Create a LiveServerMessage with a search_store tool call."""
    return types.LiveServerMessage(
        tool_call=types.LiveServerToolCall(
            function_calls=[
                types.FunctionCall(
                    id="call-search-1",
                    name="search_store",
                    args={"query": query},
                ),
            ],
        ),
    )


@patch("voice_session.analyze_screenshot", new_callable=AsyncMock)
@patch("voice_session.get_genai_client")
def test_voice_duplicate_search_suppressed(
    mock_get_client: MagicMock,
    mock_analyze: AsyncMock,
) -> None:
    """Second search_store with same query should be suppressed."""
    mock_analyze.return_value = PageAnalysis(
        page_type="product_listing", products=[MOCK_PRODUCT_INFO]
    )

    # Two identical search_store calls
    session = MockSession(
        responses=[_make_search_tool_call("salmon"), _make_search_tool_call("salmon")]
    )
    mock_get_client.return_value = _mock_genai_client(session)

    search_store_messages_sent = 0

    with TestClient(app) as client:
        with client.websocket_connect("/voice") as ws:
            # 1. connecting
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "connecting"}

            # 2. listening
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "listening"}

            # 3. searching status (first search)
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "searching"}

            # 4. search_store request sent to client
            msg = ws.receive_json()
            assert msg["type"] == "search_store"
            search_store_messages_sent += 1

            # 5. Send search results back
            ws.send_json({
                "type": "search_results",
                "data": "",
                "url": "https://example.com/search?q=salmon",
                "page_title": "Search: salmon",
                "page_text": "SEARCH RESULTS:\nMOWI Atlantic Salmon 12oz\n$8.99",
                "product_links": [
                    {"name": "MOWI Atlantic Salmon 12oz", "url": "https://example.com/salmon"},
                ],
            })

            # 6. speaking status (tool response sent)
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "speaking"}

            # 7. Second search — should be suppressed (searching status still sent)
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "searching"}

            # 8. No second search_store message — goes straight to speaking
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "speaking"}

            # Only ONE search_store message was sent to the client
            assert search_store_messages_sent == 1

            ws.send_json({"type": "stop"})


# ── Tests 6-9: _find_product_url matching ─────────────────────────────────

MOCK_LINKS = [
    {
        "name": "Amazon Grocery, Wild Caught Pacific Cod, Boneless Skinless Fillets, 16 oz",
        "url": "https://example.com/cod",
    },
    {
        "name": "Amazon Grocery, Skinless Tilapia Fillets, 12 Oz",
        "url": "https://example.com/tilapia",
    },
    {
        "name": "MOWI Atlantic Salmon 12oz, 2 Portions",
        "url": "https://example.com/salmon",
    },
]


def test_find_product_url_exact_substring() -> None:
    """Exact product name that is a substring of a link name."""
    result = _find_product_url(
        "Amazon Grocery, Wild Caught Pacific Cod, Boneless Skinless Fillets, 16 oz",
        MOCK_LINKS,
    )
    assert result == "https://example.com/cod"


def test_find_product_url_species_gated() -> None:
    """Long Gemini-extracted name with extra text — species gating picks cod, not tilapia."""
    result = _find_product_url(
        "Amazon Grocery, Wild Caught Pacific Cod, Boneless Skinless Fillets, "
        "16 oz (Previously Amazon Fresh, Packaging May Vary)",
        MOCK_LINKS,
        species="Pacific Cod",
    )
    assert result == "https://example.com/cod"


def test_find_product_url_no_match() -> None:
    """Product name with no overlap returns None."""
    result = _find_product_url("Totally Different Product", MOCK_LINKS)
    assert result is None


def test_find_product_url_salmon_not_cod() -> None:
    """Salmon product should match salmon URL, not cod or tilapia."""
    result = _find_product_url(
        "MOWI Atlantic Salmon 12oz",
        MOCK_LINKS,
        species="Atlantic Salmon",
    )
    assert result == "https://example.com/salmon"


# ── Tests 10-19: _filter_by_intent ───────────────────────────────────────

_MIXED_PRODUCTS: list[dict[str, object]] = [
    {
        "product_name": "MOWI Atlantic Salmon 12oz",
        "species": "Atlantic Salmon",
        "wild_or_farmed": "farmed",
        "score": 65,
        "practices": 18,
        "origin_region": "Norway",
        "fishing_method": None,
    },
    {
        "product_name": "Wild Alaska Sockeye Salmon Fillet",
        "species": "Sockeye Salmon",
        "wild_or_farmed": "wild",
        "score": 82,
        "practices": 22,
        "origin_region": "Alaska, USA",
        "fishing_method": "Gillnet",
    },
    {
        "product_name": "Frozen Wild Cod Fillets",
        "species": "Pacific Cod",
        "wild_or_farmed": "wild",
        "score": 70,
        "practices": 15,
        "origin_region": "Alaska, USA",
        "fishing_method": "Longline",
    },
    {
        "product_name": "Canned Albacore Tuna",
        "species": "Albacore Tuna",
        "wild_or_farmed": "wild",
        "score": 55,
        "practices": 12,
        "origin_region": "Pacific",
        "fishing_method": "Pole and line",
    },
    {
        "product_name": "Fresh Tilapia Fillet",
        "species": "Tilapia",
        "wild_or_farmed": "farmed",
        "score": 60,
        "practices": 14,
        "origin_region": "Ecuador",
        "fishing_method": None,
    },
]


def test_filter_by_intent_empty_intent() -> None:
    """Empty intent returns all products unchanged."""
    result = _filter_by_intent(_MIXED_PRODUCTS, "")
    assert result == _MIXED_PRODUCTS


def test_filter_by_intent_aquaculture_keeps_farmed_only() -> None:
    """'better aquaculture practices' excludes wild products."""
    result = _filter_by_intent(
        _MIXED_PRODUCTS, "find me one with better aquaculture practices"
    )
    assert all(p["wild_or_farmed"] == "farmed" for p in result)
    assert len(result) == 2


def test_filter_by_intent_farmed_keyword() -> None:
    """'farmed' keyword keeps only farmed products."""
    result = _filter_by_intent(_MIXED_PRODUCTS, "show me a farmed option")
    assert all(p["wild_or_farmed"] == "farmed" for p in result)


def test_filter_by_intent_wild_caught_keeps_wild_only() -> None:
    """'wild-caught' keeps only wild products."""
    result = _filter_by_intent(
        _MIXED_PRODUCTS, "find me a wild-caught alternative"
    )
    assert all(p["wild_or_farmed"] == "wild" for p in result)
    assert len(result) == 3


def test_filter_by_intent_fishing_practice() -> None:
    """'fishing practice' keeps only wild products."""
    result = _filter_by_intent(
        _MIXED_PRODUCTS, "better fishing practice score"
    )
    assert all(p["wild_or_farmed"] == "wild" for p in result)


def test_filter_by_intent_origin_alaska() -> None:
    """'Alaska' origin keeps only Alaska products."""
    result = _filter_by_intent(
        _MIXED_PRODUCTS, "show me something from Alaska"
    )
    assert len(result) == 2
    assert all("Alaska" in str(p.get("origin_region", "")) for p in result)


def test_filter_by_intent_origin_norway() -> None:
    """'Norway' origin keeps only Norwegian products."""
    result = _filter_by_intent(
        _MIXED_PRODUCTS, "find me salmon from Norway"
    )
    assert len(result) == 1
    assert result[0]["species"] == "Atlantic Salmon"


def test_filter_by_intent_method_longline() -> None:
    """'longline' method keeps only longline-caught products."""
    result = _filter_by_intent(
        _MIXED_PRODUCTS, "find me a longline caught option"
    )
    assert len(result) == 1
    assert result[0]["species"] == "Pacific Cod"


def test_filter_by_intent_form_canned() -> None:
    """'canned' form keeps only canned products."""
    result = _filter_by_intent(_MIXED_PRODUCTS, "show me a canned option")
    assert len(result) == 1
    assert result[0]["species"] == "Albacore Tuna"


def test_filter_by_intent_form_frozen() -> None:
    """'frozen' form keeps only frozen products."""
    result = _filter_by_intent(
        _MIXED_PRODUCTS, "I want a frozen alternative"
    )
    assert len(result) == 1
    assert result[0]["species"] == "Pacific Cod"


def test_filter_by_intent_fallback_when_empty() -> None:
    """Falls back to full list when filter would empty it."""
    result = _filter_by_intent(
        _MIXED_PRODUCTS, "find me something from Iceland"
    )
    # No Iceland products exist — should fall back to all
    assert result == _MIXED_PRODUCTS


def test_filter_by_intent_combined_wild_and_origin() -> None:
    """Combines wild + origin constraint."""
    result = _filter_by_intent(
        _MIXED_PRODUCTS, "wild-caught option from Alaska"
    )
    assert len(result) == 2
    assert all(p["wild_or_farmed"] == "wild" for p in result)
    assert all("Alaska" in str(p.get("origin_region", "")) for p in result)


# ── Tests: _sort_key_for_intent ───────────────────────────────────────────


def test_sort_key_empty_intent() -> None:
    assert _sort_key_for_intent("") == "score"


def test_sort_key_aquaculture_practice() -> None:
    assert _sort_key_for_intent("better aquaculture practice score") == "practices"


def test_sort_key_fishing_practice() -> None:
    assert _sort_key_for_intent("find one with better fishing practice") == "practices"


def test_sort_key_management() -> None:
    assert _sort_key_for_intent("better management score") == "management"


def test_sort_key_certification() -> None:
    assert _sort_key_for_intent("one with better certification") == "management"


def test_sort_key_biological() -> None:
    assert _sort_key_for_intent("better biological score") == "biological"


def test_sort_key_ecological() -> None:
    assert _sort_key_for_intent("better ecological impact") == "ecological"


def test_sort_key_bycatch() -> None:
    assert _sort_key_for_intent("lower bycatch") == "ecological"


def test_sort_key_generic_better() -> None:
    assert _sort_key_for_intent("find me a better salmon") == "score"


def test_sort_key_overall() -> None:
    assert _sort_key_for_intent("show me the most sustainable option overall") == "score"
