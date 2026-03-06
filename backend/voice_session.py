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

GREETING (on "[greet ...]" messages):
You will receive a greeting prompt that includes the score result the user just saw. \
Respond in 2–3 SHORT sentences:
1. A warm, grade-appropriate opener (see below).
2. A brief one-sentence overview of the result — do NOT read numbers or the full \
breakdown aloud, the score card is already visible in the panel.
3. End with an invitation: "Want to dive deeper into the results, or any questions \
I can answer?"

Grade-appropriate openers:
- Grade A: Enthusiastic. "Way to go, seafood-savvy shopper!"
- Grade B: Positive. "Not a bad pick!"
- Grade C: Gentle. "So, this one's a mixed bag."
- Grade D: Direct but friendly. "Heads up on this one."

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

AFTER RECEIVING A SCORE (from tool call) — respond conversationally:
- Grade A: Warm and affirming. One-sentence reason. "Definitely grab it."
- Grade B: Positive, mention the best alternative. One-sentence reason it isn't an A.
- Grade C: Honest, not preachy. One-sentence concern. Suggest an alternative.
- Grade D: Clear and direct. Brief reason. Suggest an alternative.

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
)


GREETING_TIMEOUT_S = 3.0


class VoiceSession:
    """Manages a single Gemini Live API voice session over a WebSocket."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.screenshot_event = asyncio.Event()
        self.screenshot_data: dict[str, Any] | None = None
        self.greeting_event = asyncio.Event()
        self.greeting_context: dict[str, Any] | None = None

    async def run(self) -> None:
        try:
            client = get_genai_client()
            log.info("Connecting to Gemini Live API (%s)…", LIVE_MODEL)
            await self.ws.send_json({"type": "status", "state": "connecting"})
            async with client.aio.live.connect(
                model=LIVE_MODEL, config=LIVE_CONFIG
            ) as session:
                log.info("Gemini Live session connected")
                await self.ws.send_json({"type": "status", "state": "listening"})
                greeting_task = asyncio.create_task(
                    self._send_greeting(session), name="greeting"
                )
                tasks = [
                    asyncio.create_task(
                        self._relay_audio_to_gemini(session), name="relay-to-gemini"
                    ),
                    asyncio.create_task(
                        self._relay_from_gemini(session), name="relay-from-gemini"
                    ),
                    asyncio.create_task(self._keepalive(), name="keepalive"),
                ]
                try:
                    done, _ = await asyncio.wait(
                        tasks, return_when=asyncio.FIRST_COMPLETED
                    )
                    for t in done:
                        exc = t.exception()
                        if exc:
                            log.error(
                                "Task %s failed: %s", t.get_name(), exc,
                                exc_info=exc,
                            )
                        else:
                            log.info("Task %s completed normally", t.get_name())
                finally:
                    greeting_task.cancel()
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(
                        greeting_task, *tasks, return_exceptions=True
                    )
        except WebSocketDisconnect:
            log.info("Client disconnected")
        except Exception as e:
            log.error("VoiceSession error: %s", e, exc_info=True)
            try:
                await self.ws.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass

    async def _send_greeting(self, session: Any) -> None:
        """Wait for result context from client, then send a greeting to Gemini."""
        try:
            await asyncio.wait_for(
                self.greeting_event.wait(), timeout=GREETING_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            pass  # No context arrived — send a generic greeting

        ctx = self.greeting_context
        if ctx:
            grade = ctx.get("grade", "")
            score = ctx.get("score", 0)
            species = ctx.get("species") or "this product"
            wild_or_farmed = ctx.get("wild_or_farmed", "unknown")
            text = (
                f"[greet] The user just scored {species} ({wild_or_farmed}). "
                f"Grade: {grade}, Score: {score}/100. "
                f"Greet them and give a brief overview."
            )
        else:
            text = (
                "[greet] The user just opened voice mode. "
                "Say hi and ask what they're looking at."
            )

        log.info("Sending greeting to Gemini: %s", text[:80])
        try:
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=text)]),
                turn_complete=True,
            )
        except Exception as e:
            log.error("Failed to send greeting: %s", e, exc_info=True)

    async def _relay_audio_to_gemini(self, session: Any) -> None:
        audio_chunks_sent = 0
        while True:
            try:
                msg = await self.ws.receive_json()
            except WebSocketDisconnect:
                log.info("Client disconnected (relay-to-gemini)")
                break

            msg_type = msg.get("type")
            if msg_type == "audio":
                pcm_bytes = base64.b64decode(msg["data"])
                await session.send_realtime_input(
                    audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
                )
                audio_chunks_sent += 1
                if audio_chunks_sent == 1:
                    log.info("First audio chunk relayed to Gemini")
            elif msg_type == "screenshot":
                self.screenshot_data = msg
                self.screenshot_event.set()
            elif msg_type == "result_context":
                self.greeting_context = msg
                self.greeting_event.set()
            elif msg_type == "stop":
                log.info("Client requested stop")
                break

    async def _relay_from_gemini(self, session: Any) -> None:
        audio_chunks_sent = 0
        try:
            # session.receive() is turn-scoped: it yields messages for ONE
            # model turn, then the iterator ends on turn_complete.  We must
            # loop to keep receiving subsequent turns.
            while True:
                async for response in session.receive():
                    if response.data:
                        audio_b64 = base64.b64encode(response.data).decode()
                        await self.ws.send_json(
                            {"type": "audio", "data": audio_b64}
                        )
                        audio_chunks_sent += 1
                        if audio_chunks_sent == 1:
                            log.info("First audio chunk sent to client")

                    if response.tool_call:
                        await self.ws.send_json(
                            {"type": "status", "state": "thinking"}
                        )
                        tool_responses: list[types.FunctionResponse] = []
                        for fc in response.tool_call.function_calls:
                            if fc.name == "analyze_current_product":
                                result = (
                                    await self._handle_analyze_current_product()
                                )
                                tool_responses.append(
                                    types.FunctionResponse(
                                        id=fc.id,
                                        name=fc.name,
                                        response=result,
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
                        await self.ws.send_json(
                            {"type": "status", "state": "listening"}
                        )

                    if (
                        response.server_content
                        and getattr(
                            response.server_content, "turn_complete", False
                        )
                    ):
                        await self.ws.send_json(
                            {"type": "status", "state": "listening"}
                        )
        except WebSocketDisconnect:
            log.info("Client disconnected during Gemini relay")
        except Exception as e:
            log.error("Gemini receive error: %s", e, exc_info=True)
            try:
                await self.ws.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass

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
