"""Voice session: manages a Gemini Live API session over WebSocket."""

import asyncio
import base64
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from google.genai import types

from agents.screen_analyzer import analyze_screenshot
from gemini_client import get_genai_client
from models import ProductInfo
from pipeline import run_scoring_pipeline

log = logging.getLogger(__name__)

LIVE_MODEL = "gemini-live-2.5-flash-native-audio"
SCREENSHOT_TIMEOUT_S = 8.0
KEEPALIVE_INTERVAL_S = 30.0

ANALYZE_CURRENT_PRODUCT_TOOL = types.FunctionDeclaration(
    name="analyze_current_product",
    description=(
        "Capture and analyze the seafood product currently visible on the user's screen. "
        "Call this when the user mentions or asks about a specific seafood product. "
        "Returns a sustainability score with grade, explanation, and alternatives."
    ),
    parameters=types.Schema(type=types.Type.OBJECT, properties={}, required=[]),
)

VOICE_SYSTEM_PROMPT = """\
You are SeaSussed, an expert marine biologist and sustainable seafood shopping \
companion — like a knowledgeable friend shopping alongside someone at an online \
grocery store.

GREETING: When you receive "[greet]", say one welcoming sentence only.

RESULT REACTION: When you receive "[RESULT] ...", react immediately in 2–3 sentences:
- Grade A: Lead with "Way to go!" + one-sentence reason. End: "Want a summary or \
have questions?"
- Grade B: Positive tone + note one improvement. End: "Want to talk through it?"
- Grade C: Honest, not preachy + one concern. End: "I can help you find a better \
option."
- Grade D: Clear and direct + one reason. End: "Want me to find a better choice?"
The full score card is already visible — don't read numbers aloud.

WHEN TO ANALYZE A PRODUCT:
Call analyze_current_product() whenever the user mentions a seafood product in a \
shopping context:
- Species mentioned ("this salmon", "the cod", "these shrimp", "that halibut")
- Direct requests ("score this", "is this sustainable?", "what do you think?", \
"check this out")
- Comparative references ("what about this one?", "how about this instead?")
- Casual pointing ("look at this", "what's this fish like?")

Do NOT call analyze_current_product() for general seafood questions \
(e.g., "is farmed salmon ever good?").

Keep spoken responses SHORT: 2–4 sentences. The full score card is visible in the \
panel so don't read numbers aloud.

If the product isn't seafood: "That doesn't look like seafood to me! Let me know \
when you spot something to check out."

GENERAL CONVERSATION:
Answer questions about seafood sustainability, fishing practices, or ocean ecology \
naturally and helpfully.
Gently redirect off-topic conversation: "I'm your seafood expert today — happy to \
check out anything on the page!"

HONESTY RULE (hard):
Never claim certainty about information not visible on the page. If species, origin, \
or fishing method wasn't shown, acknowledge it: "They don't list where it's from, \
so I'm working with limited info here."
"""

LIVE_CONFIG = types.LiveConnectConfig(
    response_modalities=[types.Modality.AUDIO],
    system_instruction=VOICE_SYSTEM_PROMPT,
    tools=[types.Tool(function_declarations=[ANALYZE_CURRENT_PRODUCT_TOOL])],
    output_audio_transcription=types.AudioTranscriptionConfig(),
)


class VoiceSession:
    """Manages a single Gemini Live API voice session over a WebSocket."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.screenshot_event = asyncio.Event()
        self.screenshot_data: dict[str, Any] | None = None

    async def run(self) -> None:
        client = get_genai_client()
        try:
            async with client.aio.live.connect(
                model=LIVE_MODEL, config=LIVE_CONFIG
            ) as session:
                await self.ws.send_json({"type": "status", "state": "listening"})
                tasks = [
                    asyncio.create_task(self._relay_audio_to_gemini(session)),
                    asyncio.create_task(self._relay_from_gemini(session)),
                    asyncio.create_task(self._keepalive()),
                ]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except WebSocketDisconnect:
            log.info("Client disconnected")
        except Exception as e:
            log.error("VoiceSession error: %s", e)
            try:
                await self.ws.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass

    async def _relay_audio_to_gemini(self, session: Any) -> None:
        while True:
            try:
                msg = await self.ws.receive_json()
            except WebSocketDisconnect:
                break

            if msg["type"] == "audio":
                pcm_bytes = base64.b64decode(msg["data"])
                await session.send_realtime_input(
                    audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
                )
            elif msg["type"] == "screenshot":
                self.screenshot_data = msg
                self.screenshot_event.set()
            elif msg["type"] == "result_context":
                grade = msg.get("grade", "")
                score = msg.get("score", 0)
                species = msg.get("species") or "this seafood product"
                wild_or_farmed = msg.get("wild_or_farmed", "unknown")
                list_count = msg.get("list_count", 0)
                if list_count > 1:
                    text = (
                        f"[RESULT] The user found {list_count} seafood products on this page. "
                        f"Best: {species} ({wild_or_farmed}), "
                        f"Grade: {grade}, Score: {score}/100. React to this result now."
                    )
                else:
                    text = (
                        f"[RESULT] The user just scored {species} ({wild_or_farmed}). "
                        f"Grade: {grade}, Score: {score}/100. React to this result now."
                    )
                await session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text=text)]),
                    turn_complete=True,
                )
            elif msg["type"] == "stop":
                break

    async def _relay_from_gemini(self, session: Any) -> None:
        async for response in session.receive():
            if response.data:
                audio_b64 = base64.b64encode(response.data).decode()
                await self.ws.send_json({"type": "audio", "data": audio_b64})

            if response.tool_call:
                await self.ws.send_json({"type": "status", "state": "thinking"})
                tool_responses: list[types.FunctionResponse] = []
                for fc in response.tool_call.function_calls:
                    if fc.name == "analyze_current_product":
                        result = await self._handle_analyze_current_product()
                        tool_responses.append(
                            types.FunctionResponse(
                                id=fc.id, name=fc.name, response=result
                            )
                        )
                if tool_responses:
                    await session.send_tool_response(
                        function_responses=tool_responses
                    )
                    await self.ws.send_json(
                        {"type": "status", "state": "speaking"}
                    )

            if (
                response.server_content
                and response.server_content.interrupted
            ):
                await self.ws.send_json({"type": "status", "state": "listening"})

    async def _handle_analyze_current_product(self) -> dict[str, Any]:
        self.screenshot_event.clear()
        self.screenshot_data = None

        await self.ws.send_json({"type": "request_screenshot"})

        try:
            await asyncio.wait_for(
                self.screenshot_event.wait(), timeout=SCREENSHOT_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            log.warning("Screenshot capture timed out")
            return {"error": "Screenshot capture timed out", "not_seafood": True}

        msg = self.screenshot_data
        if msg is None:
            return {"error": "No screenshot received", "not_seafood": True}

        page_analysis = await analyze_screenshot(
            msg["data"], msg.get("url", ""), msg.get("page_title", "")
        )
        if page_analysis.products:
            product_info = page_analysis.products[0]
        else:
            product_info = ProductInfo(
                is_seafood=False,
                species=None,
                wild_or_farmed="unknown",
                fishing_method=None,
                origin_region=None,
                certifications=[],
            )
        score_result = await run_scoring_pipeline(
            product_info, msg.get("related_products", [])
        )

        await self.ws.send_json({
            "type": "score_result",
            "score": score_result.model_dump(),
        })

        return {
            "score": score_result.score,
            "grade": score_result.grade,
            "species": product_info.species,
            "wild_or_farmed": product_info.wild_or_farmed,
            "origin_region": product_info.origin_region,
            "certifications": product_info.certifications,
            "explanation": score_result.explanation,
            "alternatives": [
                {"species": a.species, "score": a.score, "grade": a.grade}
                for a in score_result.alternatives[:2]
            ],
            "not_seafood": not product_info.is_seafood,
        }

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(KEEPALIVE_INTERVAL_S)
            try:
                await self.ws.send_json({"type": "ping"})
            except Exception:
                break
