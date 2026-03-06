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


@patch("voice_session.run_scoring_pipeline", new_callable=AsyncMock, return_value=MOCK_SCORE)
@patch("voice_session.analyze_screenshot", new_callable=AsyncMock)
@patch("voice_session.get_genai_client")
def test_voice_analyze_tool_call(
    mock_get_client: MagicMock,
    mock_analyze: AsyncMock,
    mock_pipeline: MagicMock,
) -> None:
    mock_analyze.return_value = PageAnalysis(
        page_type="single_product", products=[MOCK_PRODUCT_INFO]
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

            # 3. thinking status (from tool_call handler)
            msg = ws.receive_json()
            assert msg == {"type": "status", "state": "thinking"}

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
    mock_pipeline.assert_called_once()


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

            # 3. thinking
            msg = ws.receive_json()
            assert msg["type"] == "status"

            # 4. request_screenshot — but we never respond
            msg = ws.receive_json()
            assert msg["type"] == "request_screenshot"

            # 5. After timeout, Gemini gets error response and sends speaking status
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
