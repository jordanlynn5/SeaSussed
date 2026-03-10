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
from scoring import compute_score

log = logging.getLogger(__name__)

LIVE_MODEL = "gemini-live-2.5-flash-native-audio"
SCREENSHOT_TIMEOUT_S = 8.0
KEEPALIVE_INTERVAL_S = 30.0

def _find_product_url(
    product_name: str, links: list[dict[str, str]]
) -> str | None:
    """Find the best matching URL for a product name from scraped links."""
    if not product_name or not links:
        return None
    name_lower = product_name.lower()
    # Try exact substring match first
    for link in links:
        if name_lower in link.get("name", "").lower():
            return link.get("url")
    # Try matching significant words (3+ chars)
    words = [w for w in name_lower.split() if len(w) >= 3]
    best_url: str | None = None
    best_count = 0
    for link in links:
        link_lower = link.get("name", "").lower()
        count = sum(1 for w in words if w in link_lower)
        if count > best_count:
            best_count = count
            best_url = link.get("url")
    return best_url if best_count >= 2 else None


ANALYZE_CURRENT_PRODUCT_TOOL = types.FunctionDeclaration(
    name="analyze_current_product",
    description=(
        "Capture and analyze the seafood product currently visible on the user's "
        "screen. Returns a sustainability score with grade, explanation, and "
        "alternatives. IMPORTANT: You MUST announce to the user what you are "
        "about to do BEFORE calling this tool. Speak first, then call."
    ),
    parameters=types.Schema(type=types.Type.OBJECT, properties={}, required=[]),
)

SEARCH_STORE_TOOL = types.FunctionDeclaration(
    name="search_store",
    description=(
        "Search the grocery store website the user is currently browsing. "
        "Use this to find sustainable seafood alternatives that are actually "
        "available for purchase on the site. Returns scored results. "
        "IMPORTANT: You MUST announce to the user what you are about to search "
        "for BEFORE calling this tool. Speak first, then call."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "query": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Search query for the grocery store, e.g. 'wild salmon', "
                    "'msc certified shrimp', 'Alaska pollock'"
                ),
            ),
        },
        required=["query"],
    ),
)

NAVIGATE_TO_PRODUCT_TOOL = types.FunctionDeclaration(
    name="navigate_to_product",
    description=(
        "Navigate the user's browser to a specific product page. Use this after "
        "search_store returns results — call it with the URL of the product you "
        "want to show the user. The page will open in their current tab."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "url": types.Schema(
                type=types.Type.STRING,
                description="The full URL of the product page to navigate to",
            ),
        },
        required=["url"],
    ),
)

VOICE_SYSTEM_PROMPT = """\
You are SeaSussed, an expert marine biologist and sustainable seafood shopping \
companion — like a knowledgeable friend shopping alongside someone at an online \
grocery store.

GREETING (on "[greet ...]" messages):
You will receive a greeting prompt that includes the score result the user just saw. \
Respond in 3–5 SHORT sentences:
1. A warm, grade-appropriate opener (see below).
2. Briefly explain the 1–2 biggest factors behind the score — help them understand \
WHY this product scored the way it did. Assume the user knows nothing about \
seafood sustainability. Use plain language, not jargon. Examples: \
"Wild-caught Alaska salmon comes from one of the best-managed fisheries in the \
world, with strict catch limits that keep populations healthy." or \
"Imported farmed shrimp loses points because shrimp farming often destroys \
coastal mangrove habitat and can involve heavy antibiotic use."
3. End with an invitation to keep the conversation going: "Want me to explain \
more, or should we look for other options?"

Do NOT read numbers or the full breakdown aloud — the score card is already visible. \
Focus on telling the STORY behind the score.

Grade-appropriate openers:
- Grade A: Enthusiastic. "Great choice!"
- Grade B: Positive. "This one's pretty solid."
- Grade C: Gentle. "So, this one's a mixed bag."
- Grade D: Direct but friendly. "Heads up on this one."

MULTI-PRODUCT GREETING (on "[greet-multi ...]" messages):
You will receive a summary of ALL seafood products scored on the page. \
Respond in 2–3 SHORT sentences:
1. A brief summary of what you found — e.g. "I've looked at all 5 seafood items \
on this page."
2. Highlight the best and worst options by name.
3. Ask which product they'd like to know more about.
Do NOT list every product — the scores are already visible in the panel.

WHEN YOU ALREADY HAVE PRODUCT DATA:
If the greeting included a list of scored products, you already know their scores. \
When the user asks about a specific product by name, answer from that data — \
do NOT call analyze_current_product(). Only call the tool when the user has \
navigated to a NEW page or asks you to re-analyze.

WHEN TO ANALYZE A PRODUCT:
Call analyze_current_product() ONLY when:
- The user has navigated to a new page and asks you to check it
- The user explicitly says "analyze this page" or "score this"
- You do NOT already have score data for the product they're asking about

Do NOT call analyze_current_product() for:
- Products you already have scores for (answer from context instead)
- General seafood questions (e.g., "is farmed salmon ever good?")

SEARCHING THE STORE:
Call search_store(query) to find alternatives on the grocery website the user \
is browsing. Use this when:
- You want to suggest a better alternative and need to check what's available
- The user asks "do they have any wild salmon?" or "what else do they have?"
- A product scored poorly and you want to find a better option on the same site

SEARCH STRATEGY — BROAD CATEGORY, LET SCORING DECIDE (critical):
Search for the BROAD product category, NOT specific sustainability terms. \
The store's search doesn't understand sustainability — and pre-filtering means \
you miss products that might score well. Instead, cast a wide net and let our \
scoring algorithm find the best option from ALL results.
- User wants better shrimp → search "shrimp" (NOT "sustainable shrimp" or "MSC shrimp")
- User wants best salmon → search "salmon" (NOT "wild Alaska sockeye salmon")
- User wants grade A tuna → search "tuna" (NOT "pole caught tuna")
- User asks for "wild cod" specifically → search "wild cod" (honor specific requests)
The scoring system will automatically rank every result by sustainability. \
Your job is to get ALL the options, not to pre-filter them.

AFTER SEARCH RESULTS — TELL THE USER IMMEDIATELY (critical):
The tool response includes a "summary" field — follow its instructions. \
IMMEDIATELY tell the user what you found. Do NOT wait to be asked.

The search tool ONLY auto-navigates when the result scores HIGHER than the \
user's current product. If the result is NOT better, you must ASK the user \
before changing their page: "I found [product name] with a Grade [X] — want \
me to pull it up so you can take a look?"

If the result IS better and the page was already opened, tell the user: \
"I found [product name] with a Grade [X]. I've pulled it up for you — want \
me to analyze it?"

NEVER navigate to a product that scores lower than what the user already has \
without asking first.

NEVER just say "I found some results" or "I searched for tuna" without \
immediately telling the user WHAT you found. The user cannot see your search \
results — you are their only guide.

ANNOUNCE YOUR INTENT BEFORE EVERY TOOL CALL (MANDATORY — highest priority):
You MUST speak a sentence BEFORE calling any tool. This is NON-NEGOTIABLE. \
The user hears silence while tools run (5-15 seconds). If you call a tool \
without speaking first, the user thinks the app is broken.

DO THIS — speak FIRST, THEN call the tool:
- Before search_store: "Let me search this store for all their shrimp options \
and find you the most sustainable one." THEN call search_store.
- Before analyze_current_product: "Let me take a look at what's on your screen." \
THEN call analyze_current_product.
- Before search_store for alternatives: "I'll pull up everything they have and \
score them for you." THEN call search_store.

DO NOT DO THIS — calling the tool and THEN telling the user:
- ❌ [calls search_store] → "I searched for shrimp and here's what I found"
- ❌ [calls analyze_current_product] → "I just analyzed your page"

The correct order is ALWAYS: speak intent → call tool → speak results.

AFTER RECEIVING A SCORE (from tool call) — respond conversationally:
Treat the user as a new learner. Highlight the 1–2 biggest factors in plain \
language so they actually learn something about sustainable seafood.
- Grade A: Warm and affirming. Explain what makes it great — e.g. well-managed \
  fishery, healthy wild population, low bycatch, strong certification. \
  Do NOT suggest searching for something better — they already have a great choice.
- Grade B: Positive. Explain what's good AND the one thing holding it back — \
  e.g. "The species itself is healthy, but the fishing method has higher bycatch \
  than ideal." Ask if they want to explore other options.
- Grade C: Honest, not preachy. Name the main concern in plain terms — e.g. \
  "This species is overfished in this region" or "Farmed without strong \
  environmental certification." Offer to search for a better option.
- Grade D: Clear and direct. Name the key problem. Proactively offer to search: \
  "I can search this store for a better choice — want me to?"

AFTER SEARCH RESULTS — BE HONEST ABOUT WHAT YOU FOUND (critical):
The search tool response includes a comparison to the user's current product. \
Pay close attention to it:
- If the best result scores HIGHER than the current product, recommend it \
  enthusiastically.
- If the best result scores LOWER or the SAME, be honest: "I looked through \
  what they have, and actually your current pick is the best option here." \
  Do NOT suggest searching again or trying different terms — if the store \
  doesn't have something better, just say so and affirm their current choice.
- If no seafood was found at all, say so: "Doesn't look like they have that \
  in stock. Your current choice is still solid."
Never push the user to keep searching when the store simply doesn't carry \
a better option. Respect the results.

IMPORTANT: If the user specifically ASKED you to find the best option (e.g. \
"find me the most sustainable tuna") and the search returned a top result, \
do NOT immediately suggest searching for something even better. They already \
asked for the best and you found it. Instead, share why it scored well and \
ask if they want you to open the page.

Keep spoken responses conversational: 3–5 sentences. The full score card is visible \
in the panel so don't read numbers aloud — focus on the story, not the stats.

If the product isn't seafood: "That doesn't look like seafood to me! Let me know \
when you spot something to check out."

GENERAL CONVERSATION:
Answer questions about seafood sustainability, fishing practices, or ocean ecology \
naturally and helpfully.
Gently redirect off-topic conversation: "I'm your seafood expert today — happy to \
check out anything on the page!"

INTERRUPTION RECOVERY:
If you get interrupted mid-sentence but the user doesn't actually say anything \
(silence, background noise, or unclear audio), acknowledge it briefly and continue \
where you left off. For example: "Oh sorry, thought you wanted to jump in! \
Anyway, as I was saying…" Keep the recovery natural and quick — don't restart \
your whole response, just pick up from roughly where you were cut off.

DO NOT REPEAT YOURSELF:
Never restate information you already said in this conversation. If you already \
greeted the user and summarized the score, don't say it again. If asked the same \
question twice, give a shorter answer or say "like I mentioned…" and add new detail. \
Each response should contain new information, not rehash what was already covered.

HEALTH & CARBON CONTEXT:
The tool response may include health_advisory (FDA mercury tier like "Best Choice", \
"Good Choice", or "Choices to Avoid") and carbon_co2 (kg CO₂ per serving). \
If present, weave them naturally into your response when relevant — don't list them \
robotically. Examples:
- "Plus, sardines are a Best Choice for mercury — safe to eat several times a week."
- "One nice thing about this fish — the carbon footprint is really low compared to \
other proteins."
Only mention these if the user seems interested or if the data is noteworthy \
(e.g., high mercury = always mention).

HONESTY RULE (hard):
Never claim certainty about information not visible on the page. If species, origin, \
or fishing method wasn't shown, acknowledge it: "They don't list where it's from, \
so I'm working with limited info here."
"""

LIVE_CONFIG = types.LiveConnectConfig(
    response_modalities=[types.Modality.AUDIO],
    system_instruction=VOICE_SYSTEM_PROMPT,
    tools=[types.Tool(function_declarations=[
        ANALYZE_CURRENT_PRODUCT_TOOL, SEARCH_STORE_TOOL,
        NAVIGATE_TO_PRODUCT_TOOL,
    ])],
)


GREETING_TIMEOUT_S = 3.0


class VoiceSession:
    """Manages a single Gemini Live API voice session over a WebSocket."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.screenshot_event = asyncio.Event()
        self.screenshot_data: dict[str, Any] | None = None
        self.search_event = asyncio.Event()
        self.search_data: dict[str, Any] | None = None
        self.greeting_event = asyncio.Event()
        self.greeting_context: dict[str, Any] | None = None
        self.product_links: list[dict[str, str]] = []
        self.current_grade: str = ""
        self.current_score: int = 0

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
        all_products = ctx.get("all_products") if ctx else None

        if all_products and len(all_products) > 1:
            # Multi-product page — send all scored products as context
            lines = []
            for p in all_products:
                name = p.get("product_name") or p.get("species") or "unknown"
                lines.append(
                    f"- {name}: Grade {p.get('grade')}, "
                    f"Score {p.get('score')}/100 "
                    f"({p.get('wild_or_farmed', 'unknown')})"
                )
            product_list = "\n".join(lines)
            text = (
                f"[greet-multi] The user just scored {len(all_products)} "
                f"seafood products on this page:\n{product_list}\n"
                f"Greet them and give a brief overview of the best and "
                f"worst options."
            )
        elif ctx:
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
            elif msg_type == "search_results":
                self.search_data = msg
                self.search_event.set()
            elif msg_type == "result_context":
                self.greeting_context = msg
                self.greeting_event.set()
                # Track current product grade for search comparisons
                if msg.get("grade"):
                    self.current_grade = msg["grade"]
                    self.current_score = msg.get("score", 0)
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
                        # Send specific status so client can show feedback
                        tool_names = [
                            fc.name
                            for fc in response.tool_call.function_calls
                        ]
                        if "search_store" in tool_names:
                            await self.ws.send_json(
                                {"type": "status", "state": "searching"}
                            )
                        elif "analyze_current_product" in tool_names:
                            await self.ws.send_json(
                                {"type": "status", "state": "analyzing"}
                            )
                        elif "navigate_to_product" in tool_names:
                            await self.ws.send_json(
                                {"type": "status", "state": "navigating"}
                            )
                        else:
                            await self.ws.send_json(
                                {"type": "status", "state": "thinking"}
                            )
                        tool_responses: list[types.FunctionResponse] = []
                        for fc in response.tool_call.function_calls:
                            if fc.name == "analyze_current_product":
                                result = (
                                    await self._handle_analyze_current_product()
                                )
                            elif fc.name == "search_store":
                                query = (fc.args or {}).get("query", "")
                                result = await self._handle_search_store(
                                    query
                                )
                            elif fc.name == "navigate_to_product":
                                url = (fc.args or {}).get("url", "")
                                result = (
                                    await self._handle_navigate_to_product(url)
                                )
                            else:
                                result = {"error": f"Unknown tool: {fc.name}"}
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

        # Track current product for search comparisons
        self.current_grade = score_result.grade
        self.current_score = score_result.score

        await self.ws.send_json({
            "type": "score_result",
            "score": score_result.model_dump(),
        })

        return {
            "score": score_result.score,
            "grade": score_result.grade,
            "species": score_result.product_info.species,
            "wild_or_farmed": score_result.product_info.wild_or_farmed,
            "origin_region": score_result.product_info.origin_region,
            "certifications": score_result.product_info.certifications,
            "fishing_method": score_result.product_info.fishing_method,
            "explanation": score_result.explanation,
            "alternatives": [
                {"species": a.species, "score": a.score, "grade": a.grade}
                for a in score_result.alternatives[:2]
            ],
            "not_seafood": not score_result.product_info.is_seafood,
            "health_advisory": (
                score_result.health.mercury_category if score_result.health else None
            ),
            "carbon_co2": (
                score_result.carbon.co2_kg_per_serving if score_result.carbon else None
            ),
        }

    async def _handle_search_store(self, query: str) -> dict[str, Any]:
        """Search the grocery store and return scored products."""
        log.info("Searching store for: %s", query)
        self.search_event.clear()
        self.search_data = None

        await self.ws.send_json({"type": "search_store", "query": query})

        try:
            await asyncio.wait_for(
                self.search_event.wait(), timeout=SCREENSHOT_TIMEOUT_S + 5.0
            )
        except asyncio.TimeoutError:
            log.warning("Store search timed out")
            return {"error": "Store search timed out", "products": []}

        msg = self.search_data
        if msg is None or (not msg.get("data") and not msg.get("page_text")):
            return {"error": "No search results received", "products": []}

        page_analysis = await analyze_screenshot(
            msg["data"], msg.get("url", ""), msg.get("page_title", ""),
            page_text=msg.get("page_text", ""),
        )

        seafood = [p for p in page_analysis.products if p.is_seafood]
        if not seafood:
            return {"query": query, "products": [], "message": "No seafood found"}

        # Match scraped product URLs to extracted products by name overlap
        product_links: list[dict[str, str]] = msg.get("product_links", [])
        self.product_links = product_links  # store for navigate_to_product

        scored_products = []
        for p in seafood[:6]:
            breakdown, total, grade = compute_score(p)
            name = p.product_name or p.species or "unknown"
            # Find matching URL from scraped links
            url = _find_product_url(name, product_links)
            entry: dict[str, Any] = {
                "product_name": name,
                "species": p.species,
                "wild_or_farmed": p.wild_or_farmed,
                "score": total,
                "grade": grade,
            }
            if url:
                entry["url"] = url
            scored_products.append(entry)

        scored_products.sort(key=lambda x: x["score"], reverse=True)
        log.info("Store search returned %d products", len(scored_products))

        # Filter: only recommend products that score higher than current
        better_products = [
            p for p in scored_products
            if p["score"] > self.current_score
        ] if self.current_score > 0 else scored_products

        # Use the better list for navigation, but keep full list for context
        nav_target = better_products[0] if better_products else (
            scored_products[0] if scored_products else None
        )

        # Only auto-navigate if the result is BETTER than current product
        navigated = False
        is_better = (
            nav_target is not None
            and nav_target["score"] > self.current_score
            and self.current_score > 0
        )
        if is_better and nav_target and "url" in nav_target:
            await self.ws.send_json(
                {"type": "status", "state": "navigating"}
            )
            await self.ws.send_json(
                {"type": "navigate", "url": nav_target["url"]}
            )
            navigated = True
            log.info("Auto-navigated to better product: %s", nav_target["url"])

        # Build explicit summary so Gemini clearly presents results
        if nav_target:
            best = nav_target
            best_name = best["product_name"]
            is_better = best["score"] > self.current_score
            comparison = ""
            if self.current_grade and is_better:
                comparison = (
                    f" That's better than the current product "
                    f"(Grade {self.current_grade}, {self.current_score}/100)."
                )
            elif self.current_grade and not is_better:
                comparison = (
                    f" NOTE: This is NOT better than the current product "
                    f"(Grade {self.current_grade}, {self.current_score}/100). "
                    f"Be honest — tell the user the best you found doesn't "
                    f"beat what they have. Their current product is the "
                    f"better choice."
                )
            if navigated:
                summary = (
                    f"Found {len(scored_products)} seafood products. "
                    f"Best option: \"{best_name}\" (Grade {best['grade']}, "
                    f"score {best['score']}/100).{comparison} "
                    f"I've opened this page for you since it scores higher. "
                    f"Tell them what you found and offer to analyze it."
                )
            elif is_better and "url" not in best:
                summary = (
                    f"Found {len(scored_products)} seafood products. "
                    f"Best option: \"{best_name}\" (Grade {best['grade']}, "
                    f"score {best['score']}/100).{comparison} "
                    f"Tell the user to search this site for "
                    f"\"{best_name}\" and click on it."
                )
            else:
                summary = (
                    f"Found {len(scored_products)} seafood products. "
                    f"Best option: \"{best_name}\" (Grade {best['grade']}, "
                    f"score {best['score']}/100).{comparison} "
                    f"Do NOT navigate automatically. Ask the user if they "
                    f"want you to open this product page."
                )
        else:
            summary = (
                f"No seafood found for \"{query}\". Suggest the user "
                f"try a different search term."
            )

        return {
            "query": query,
            "products": scored_products,
            "summary": summary,
        }

    async def _handle_navigate_to_product(self, url: str) -> dict[str, Any]:
        """Navigate the user's browser to a product page."""
        if not url:
            return {"error": "No URL provided"}
        log.info("Navigating user to: %s", url)
        await self.ws.send_json({"type": "navigate", "url": url})
        return {
            "success": True,
            "url": url,
            "instruction": (
                "The page is loading now. Tell the user you've opened the "
                "product page and offer to analyze it: 'I've pulled that up "
                "for you. Want me to analyze it?'"
            ),
        }

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(KEEPALIVE_INTERVAL_S)
            try:
                await self.ws.send_json({"type": "ping"})
            except Exception:
                break
