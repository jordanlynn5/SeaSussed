"""Voice session: manages a Gemini Live API session over WebSocket."""

import asyncio
import base64
import logging
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from google.genai import types

from agents.screen_analyzer import analyze_screenshot
from explanation import generate_template_content
from gemini_client import get_genai_client
from health import get_health_info
from models import ProductInfo, SustainabilityScore
from scoring import compute_score

log = logging.getLogger(__name__)

LIVE_MODEL = "gemini-live-2.5-flash-native-audio"
SCREENSHOT_TIMEOUT_S = 8.0
KEEPALIVE_INTERVAL_S = 30.0
TOOL_COOLDOWN_S = 30.0

_GENERIC_WORDS = frozenset({
    "amazon", "grocery", "fresh", "brand", "oz",
    "fillets", "fillet", "skinless", "boneless", "portions",
    "portion", "previously", "packaging", "vary", "may",
    "frozen", "caught", "wild", "farmed", "product",
    "organic", "natural", "premium", "select", "choice",
})

# Words that appear in generic "best overall" requests but are NOT species names.
# If every meaningful word in the user's intent is in this set, no species
# constraint is applied and the highest-scored product wins regardless of species.
_NON_SPECIES_INTENT_WORDS = frozenset({
    # request verbs / phrases
    "find", "get", "give", "show", "bring", "look", "search", "fetch",
    # adjectives / qualifiers
    "best", "better", "good", "great", "most", "sustainable", "highest",
    "top", "any", "some", "another", "different", "other",
    # generic nouns (not species names)
    "fish", "seafood", "shellfish", "option", "options", "something",
    "anything", "one", "item", "product", "choice",
    # score/grade language
    "score", "grade", "rated", "ranking",
    # function words
    "me", "you", "the", "a", "an", "for", "with", "what", "have",
    "they", "do", "can", "please", "want", "like",
})


def _filter_by_intent(
    products: list[dict[str, Any]], intent: str
) -> list[dict[str, Any]]:
    """Filter scored products by user intent constraints.

    Applies apples-to-apples filtering so that e.g. "better aquaculture
    practices" only returns farmed products (wild products don't have
    aquaculture scores).  Falls back to the full list when the filter
    would empty it.
    """
    if not intent:
        return products

    low = intent.lower()
    filtered = list(products)

    # Wild vs farmed constraint
    _FARMED_KW = ("aquaculture", "farmed", "farm-raised", "farm raised")
    _WILD_KW = ("wild-caught", "wild caught", "fishing practice", "fishing method")
    if any(k in low for k in _FARMED_KW):
        filtered = [p for p in filtered if p.get("wild_or_farmed") == "farmed"]
    elif any(k in low for k in _WILD_KW):
        filtered = [p for p in filtered if p.get("wild_or_farmed") == "wild"]

    # Origin constraint
    _ORIGINS = [
        "alaska", "norway", "chile", "canada", "iceland", "japan",
        "china", "vietnam", "thailand", "indonesia", "india", "ecuador",
        "scotland", "atlantic", "pacific", "gulf",
    ]
    for origin in _ORIGINS:
        if origin in low:
            filtered = [
                p for p in filtered
                if p.get("origin_region") and origin in p["origin_region"].lower()
            ]
            break

    # Fishing method constraint
    # Order matters: longer/more-specific keywords first to avoid
    # substring false positives (e.g. "longline" contains "line").
    _METHODS: list[tuple[str, str]] = [
        ("longline", "longline"), ("long line", "longline"),
        ("line-caught", "line"), ("line caught", "line"),
        ("hook and line", "line"),
        ("pole-caught", "pole"), ("pole caught", "pole"),
        ("trawl", "trawl"),
        ("gillnet", "gillnet"), ("gill net", "gillnet"),
        ("purse seine", "seine"),
    ]
    for keyword, match in _METHODS:
        if keyword in low:
            filtered = [
                p for p in filtered
                if p.get("fishing_method") and match in p["fishing_method"].lower()
            ]
            break

    # Product form constraint
    _FORMS = ["canned", "frozen", "fresh", "fillet", "smoked", "dried"]
    for form in _FORMS:
        if form in low:
            filtered = [
                p for p in filtered
                if p.get("product_name") and form in p["product_name"].lower()
            ]
            break

    # Fall back to unfiltered if every product was excluded
    return filtered if filtered else products


def _sort_key_for_intent(intent: str) -> str:
    """Return the scored_products field to sort by for a given user intent.

    Returns one of: "practices", "management", "biological", "ecological",
    or "score" (default — overall total).
    """
    if not intent:
        return "score"
    low = intent.lower()
    if any(k in low for k in ("practice", "aquaculture", "fishing method", "gear")):
        return "practices"
    if any(k in low for k in ("management", "certification", "regulated", "regulation")):
        return "management"
    if any(k in low for k in ("biological", "population", "species health", "resilience")):
        return "biological"
    if any(k in low for k in ("ecological", "environment", "bycatch", "habitat")):
        return "ecological"
    return "score"


def _find_product_url(
    product_name: str,
    links: list[dict[str, str]],
    species: str | None = None,
) -> str | None:
    """Match a product name to a scraped URL.

    Three-tier matching:
    1. Bidirectional substring — either name contains the other
    2. Species-gated fuzzy — require species word match, then count remaining
    3. Fallback fuzzy — word-overlap with generic word exclusion
    """
    if not product_name or not links:
        return None

    name_lower = product_name.lower()

    # Tier 1: Bidirectional exact substring
    for link in links:
        link_name = link.get("name", "").lower()
        if not link_name:
            continue
        if name_lower in link_name or link_name in name_lower:
            return link.get("url")

    # Extract species words for gating
    species_words: set[str] = set()
    if species:
        species_words = {
            w.lower() for w in species.split() if len(w) >= 3
        } - _GENERIC_WORDS

    # Significant words from product name, excluding generic
    all_words = [w for w in name_lower.split() if len(w) >= 3]
    meaningful_words = [w for w in all_words if w not in _GENERIC_WORDS]
    if not meaningful_words:
        return None

    # Tier 2: Species-gated fuzzy matching
    if species_words:
        best_url, best_score = _fuzzy_match(
            meaningful_words, links, species_gate=species_words,
        )
        if best_url and best_score >= 0.3:
            return best_url

    # Tier 3: Fallback without species gate
    best_url, best_score = _fuzzy_match(meaningful_words, links)
    if best_url and best_score >= 0.3:
        return best_url

    return None


def _fuzzy_match(
    meaningful_words: list[str],
    links: list[dict[str, str]],
    species_gate: set[str] | None = None,
) -> tuple[str | None, float]:
    """Score links by meaningful word overlap, optionally gated by species."""
    best_url: str | None = None
    best_score: float = 0.0
    for link in links:
        link_lower = link.get("name", "").lower()
        if not link_lower:
            continue
        if species_gate:
            if not any(sw in link_lower for sw in species_gate):
                continue
        matched = sum(1 for w in meaningful_words if w in link_lower)
        score = matched / len(meaningful_words)
        if score > best_score:
            best_score = score
            best_url = link.get("url")
    return best_url, best_score


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
            "intent": types.Schema(
                type=types.Type.STRING,
                description=(
                    "The user's original request that triggered this search, "
                    "e.g. 'find me one with better aquaculture practices' or "
                    "'show me a frozen wild-caught option from Alaska'"
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

ANALYZING GREETING (on "[greet-analyzing]" messages):
The user just clicked Analyze and the score is still loading. You know NOTHING \
yet — no species, no score, no grade, no data. You also don't know if it's \
one product or many. Your ONLY job is to say ONE short sentence acknowledging \
you're looking, then STOP TALKING. Do not add a second sentence. Do not give \
any preview, opinion, warning, caution, advice, or commentary of any kind. \
You will get the data later — wait for it.
Good: "Hey! Let me take a look — I'll let you know what I find!"
Good: "Alright, checking this out for you — I'll have results in just a sec."
Good: "Taking a look now, I'll update you in a moment!"
BAD: "Alright, taking this one..." — you don't know if it's one product or many.
BAD: "Let me score this product for you." — you don't know it's a single product.
ABSOLUTELY FORBIDDEN in analyzing greeting: "heads up", "be careful", "watch out", \
"let's talk about", "interesting", "this one", "this product", or ANY phrase \
that assumes a single product or sounds like an assessment. \
You literally have no information yet. One neutral sentence, then silence.

GREETING (on "[greet ...]" messages):
You will receive a greeting prompt that includes the score result the user just saw. \
Respond in 5–8 sentences:
1. A warm, grade-appropriate opener (see below).
2. Explain the 2–3 KEY factors behind the score — help the user genuinely \
UNDERSTAND why this product scored the way it did. Assume they know nothing \
about seafood sustainability. Teach them something real — go beyond the card. \
Use plain language, not jargon. Examples: \
"Wild-caught Alaska salmon comes from one of the best-managed fisheries in the \
world — they actually count the fish returning to rivers every year and adjust \
catch limits to keep populations healthy. Plus, the gill net method used here \
has relatively low bycatch compared to trawling." or \
"Imported farmed shrimp loses points for a few reasons — shrimp farming in \
Southeast Asia often involves clearing coastal mangrove forests, which are \
critical nursery habitat for wild fish. There's also heavy antibiotic use in \
many farms, and without ASC certification there's no independent verification \
of their environmental practices."
3. After giving substance, end with: "I can go deeper on any of that, or I can \
search this store for other options — what sounds good?"

Do NOT read numbers or the full breakdown aloud — the score card is already visible. \
Focus on telling the STORY behind the score. Give the user real knowledge they \
didn't have before, not a summary they can already see on screen.

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
Do NOT proactively call search_store after a multi-product greeting. The user \
already has multiple options on the page — only search if they ASK you to.

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
- User wants best option overall / best fish / best score → search "fish" \
  (NOT a specific species — cast the widest net so scoring can pick the true best)
- User wants better shrimp → search "shrimp" (NOT "sustainable shrimp" or "MSC shrimp")
- User wants best salmon → search "salmon" (NOT "wild Alaska sockeye salmon")
- User wants grade A tuna → search "tuna" (NOT "pole caught tuna")
- User asks for "wild cod" specifically → search "wild cod" (honor specific requests)
The scoring system will automatically rank every result by sustainability. \
Your job is to get ALL the options, not to pre-filter them.

INTENT FIELD — ALWAYS REQUIRED (critical):
You MUST always pass the `intent` field when calling search_store. \
Set it to the user's verbatim request that triggered the search. \
The backend uses this to filter and rank results correctly — without it, \
results will be ranked by overall score instead of what the user asked for. \
Examples:
- User: "find me one with better aquaculture practices" \
  → search_store(query="salmon", intent="find me one with better aquaculture practices")
- User: "show me a wild-caught option from Alaska" \
  → search_store(query="salmon", intent="show me a wild-caught option from Alaska")
- User: "what's the most sustainable shrimp they have?" \
  → search_store(query="shrimp", intent="what's the most sustainable shrimp they have?")

AFTER SEARCH RESULTS — NAVIGATE IMMEDIATELY (critical):
The tool response includes scored products with names, scores, grades, prices, \
and URLs. Selection rules are in the tool response — follow them strictly. \
The user's requested species MUST match — never substitute a different fish. \
If the user asked for a "better" option, pick the highest-scored match. \
Call navigate_to_product IMMEDIATELY, then briefly explain your pick.

The page will auto-analyze once loaded — you'll get a context update with \
the real score. Wait for that before discussing the score.

WAIT FOR COMPLETE REQUESTS (critical): \
Never call a tool until you are certain the user has finished their sentence. \
If a request sounds partial — they've named a category but haven't said what \
they want, or the sentence feels unfinished — wait silently for them to \
continue. Only act on requests that are clearly complete.

TOOL CALLS — DO NOT NARRATE (critical): \
The UI shows a visual status bar ("Searching...", "Analyzing...", "Navigating...") \
so the user already knows what's happening. Do NOT announce tool calls. \
Just call the tool silently. Speak AFTER you have results, not before. \
Never narrate your process — no "Let me search", "I'm going to look", \
"Okay searching now", etc. Just do it.

ANTI-REPETITION RULE (critical): \
Never say the same thing twice in a turn. Never restate what you just said \
in different words. One thought, one sentence, move on.

AFTER RECEIVING A SCORE (from tool call) — respond conversationally:
Treat the user as a new learner. Explain the 2–3 biggest factors in plain \
language so they actually LEARN something about sustainable seafood. Give real \
context — why does this factor matter for the ocean? What's the story behind \
the score? Respond in 5–8 sentences, not a quick summary.
- Grade A: Warm and affirming. Explain what makes it great with real detail — \
  e.g. the fishery management approach, why the population is healthy, what the \
  certification actually verifies. \
  Do NOT suggest searching for something better — they already have a great choice. \
  End with: "Happy to go deeper on any of that, or we can keep shopping."
- Grade B: Positive. Explain what's good AND the one thing holding it back with \
  context — e.g. "The species itself is healthy and well-managed, but the fishing \
  method — bottom trawling — drags heavy nets along the seafloor, which can \
  damage habitat for other marine life." \
  End with: "I can tell you more about that, or search for other options here."
- Grade C: Honest, not preachy. Explain the main concerns with real-world context \
  — e.g. "This species is overfished in this region — catches have declined \
  significantly over the last decade" or "Without ASC certification, there's no \
  independent check on antibiotic use or environmental impact at the farm." \
  End with: "I can dig into that or search alternatives. Let me know, I'll be here."
- Grade D: Clear and direct. Explain the key problems so the user understands \
  the real impact. Proactively offer to search: \
  "Let me know if you'd like me to search for alternatives — I'll be here."

AFTER SEARCH RESULTS — HOW SCORING WORKS (critical):
Search results include rough ESTIMATE scores from listing text only (product \
names, no images or detail). Use these to compare options against EACH OTHER \
and pick the best match for the user's request — but do NOT quote these \
scores to the user. The real score comes after navigating to the product \
page for full analysis. Tell the user the full score is loading.

If no seafood was found at all, say so: "Doesn't look like they have that \
in stock."

Keep spoken responses conversational: 5–8 sentences for score explanations, \
3–5 sentences for follow-ups. The full score card is visible in the panel so \
don't read numbers aloud — focus on the story, not the stats. Teach the user \
something they wouldn't know from reading the card.

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

HEALTH & FOOD MILES CONTEXT:
The tool response may include health_advisory (FDA mercury tier like "Best Choice", \
"Good Choice", or "Choices to Avoid") and food_miles (distance in miles from origin \
to the user's location). If present, weave them naturally into your response when \
relevant — don't list them robotically. Examples:
- "Plus, sardines are a Best Choice for mercury — safe to eat several times a week."
- "Interesting — this salmon traveled about 4,200 miles from Norway to get to you."
Only mention food_miles if the distance is notable (over 1000 miles) or the user \
seems interested in where their food comes from. Always mention high mercury.

LIVE UPDATES (two phases):
You will receive updates as the analysis progresses:

1. [context-update-identified] — The product has been identified but the score is \
   still being calculated. Say a brief acknowledgment like "I'll have the full \
   results for you in just a moment" then STOP. Do NOT share species background \
   or facts — just let the user know results are coming.

2. [context-update-final] — The full results including score and alternatives are in. \
   THIS is when you announce the score. Transition naturally: "OK, the results are \
   in!" or "Alright, so here's how it scored..." Then give your grade-appropriate \
   assessment (see guidelines above). ONLY share NEW information — the score, what \
   drove it, and alternatives. Do NOT re-explain species facts, health info, or \
   background you already covered in the identified phase.

For both: finish your current sentence naturally before transitioning — don't cut \
yourself off mid-word.

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
        self.client_ip = ws.client.host if ws.client else ""
        self.screenshot_event = asyncio.Event()
        self.screenshot_data: dict[str, Any] | None = None
        self.search_event = asyncio.Event()
        self.search_data: dict[str, Any] | None = None
        self.greeting_event = asyncio.Event()
        self.greeting_context: dict[str, Any] | None = None
        self.product_links: list[dict[str, str]] = []
        self.current_grade: str = ""
        self.current_score: int = 0
        self.current_breakdown: dict[str, int] = {}
        self._awaiting_search_result: bool = False
        self._last_search_query: str = ""
        self._last_search_time: float = 0.0
        self._last_navigate_url: str = ""
        self._last_navigate_time: float = 0.0

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

        if ctx and ctx.get("analyzing"):
            text = (
                "[greet-analyzing] The user just clicked Analyze. "
                "Say ONE short, casual acknowledgement — like 'On it!' or "
                "'Let me take a look.' then STOP immediately. "
                "Do NOT say 'in a moment', 'shortly', 'results coming', "
                "or anything about waiting. No second sentence."
            )
            log.info("Sending analyzing greeting to Gemini")
            try:
                await session.send_client_content(
                    turns=types.Content(
                        role="user", parts=[types.Part(text=text)]
                    ),
                    turn_complete=True,
                )
            except Exception as e:
                log.error("Failed to send greeting: %s", e, exc_info=True)
            return

        listing_summary = ctx.get("listing_summary") if ctx else None

        if all_products and len(all_products) > 1:
            # Multi-product page — send scored products + written summary
            lines = []
            for p in all_products:
                name = p.get("product_name") or p.get("species") or "unknown"
                lines.append(
                    f"- {name}: Grade {p.get('grade')}, "
                    f"Score {p.get('score')}/100 "
                    f"({p.get('wild_or_farmed', 'unknown')})"
                )
            product_list = "\n".join(lines)
            if listing_summary:
                text = (
                    f"[greet-multi] The user just scored "
                    f"{len(all_products)} seafood products on this "
                    f"page:\n{product_list}\n\n"
                    f"Here is the written summary already shown in "
                    f"the panel:\n{listing_summary}\n\n"
                    f"Speak this summary to the user in a natural, "
                    f"conversational way. Don't read it word-for-word "
                    f"— paraphrase it as spoken advice. Then ask which "
                    f"product they'd like to know more about. "
                    f"Do NOT call search_store — they already have "
                    f"multiple options on this page."
                )
            else:
                text = (
                    f"[greet-multi] The user just scored "
                    f"{len(all_products)} seafood products on this "
                    f"page:\n{product_list}\n"
                    f"Greet them and give a brief overview of the "
                    f"best and worst options."
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
                    bd = msg.get("breakdown") or {}
                    if bd:
                        self.current_breakdown = {
                            "biological": int(bd.get("biological", 0)),
                            "practices": int(bd.get("practices", 0)),
                            "management": int(bd.get("management", 0)),
                            "ecological": int(bd.get("ecological", 0)),
                        }
            elif msg_type == "context_update":
                update_text = self._format_context_update(msg)
                if not update_text:
                    continue
                try:
                    await session.send_client_content(
                        turns=types.Content(
                            role="user",
                            parts=[types.Part(text=update_text)],
                        ),
                        turn_complete=True,
                    )
                    log.info("Sent context update to Gemini")
                except Exception as e:
                    log.warning("Failed to send context update: %s", e)
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
                        tool_names = [
                            fc.name
                            for fc in response.tool_call.function_calls
                        ]
                        for fc in response.tool_call.function_calls:
                            log.info(
                                "GEMINI TOOL CALL: %s(%s)",
                                fc.name,
                                fc.args,
                            )
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
                            try:
                                if fc.name == "analyze_current_product":
                                    result = (
                                        await self._handle_analyze_current_product()
                                    )
                                elif fc.name == "search_store":
                                    query = (fc.args or {}).get("query", "")
                                    intent = (fc.args or {}).get("intent", "")
                                    now = time.monotonic()
                                    if (
                                        query == self._last_search_query
                                        and now - self._last_search_time
                                        < TOOL_COOLDOWN_S
                                    ):
                                        log.warning(
                                            "Suppressed duplicate "
                                            "search_store('%s')",
                                            query,
                                        )
                                        result = {
                                            "query": query,
                                            "products": [],
                                            "summary": (
                                                "Search already performed "
                                                "— use the results above."
                                            ),
                                        }
                                    else:
                                        self._last_search_query = query
                                        self._last_search_time = now
                                        result = (
                                            await self._handle_search_store(
                                                query, intent,
                                            )
                                        )
                                elif fc.name == "navigate_to_product":
                                    url = (fc.args or {}).get("url", "")
                                    now = time.monotonic()
                                    if (
                                        url == self._last_navigate_url
                                        and now - self._last_navigate_time
                                        < TOOL_COOLDOWN_S
                                    ):
                                        log.warning(
                                            "Suppressed duplicate "
                                            "navigate_to_product"
                                        )
                                        result = {
                                            "success": True,
                                            "url": url,
                                            "instruction": (
                                                "Already navigating to "
                                                "this page."
                                            ),
                                        }
                                    else:
                                        self._last_navigate_url = url
                                        self._last_navigate_time = now
                                        result = (
                                            await self._handle_navigate_to_product(
                                                url
                                            )
                                        )
                                else:
                                    result = {"error": f"Unknown tool: {fc.name}"}
                            except Exception as tool_err:
                                log.error(
                                    "Tool %s failed: %s", fc.name, tool_err,
                                    exc_info=True,
                                )
                                result = {"error": str(tool_err)}
                            tool_responses.append(
                                types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response=result,
                                )
                            )
                        try:
                            if tool_responses:
                                await session.send_tool_response(
                                    function_responses=tool_responses
                                )
                                await self.ws.send_json(
                                    {"type": "status", "state": "speaking"}
                                )
                        except Exception as send_err:
                            log.error(
                                "send_tool_response failed: %s", send_err,
                                exc_info=True,
                            )
                            # Tell client we're back to listening
                            try:
                                await self.ws.send_json(
                                    {"type": "status", "state": "listening"}
                                )
                            except Exception:
                                pass
                            return  # session is broken, exit cleanly

                    # Log transcript text from Gemini's response
                    if (
                        response.server_content
                        and getattr(
                            response.server_content, "model_turn", None
                        )
                    ):
                        for part in (
                            response.server_content.model_turn.parts or []
                        ):
                            if hasattr(part, "text") and part.text:
                                log.info(
                                    "GEMINI TRANSCRIPT: %s", part.text
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
        """Capture screenshot → Gemini vision → instant Python scoring.

        Uses a fast path: only one Gemini call (vision), then pure Python
        scoring + template explanation.  Skips web research, Gemini
        explanation, and Gemini-based alternative identification to stay
        within the Gemini Live tool-response timeout (~15 s).
        """
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

        # Non-seafood: skip scoring entirely, tell Gemini immediately
        if not product_info.is_seafood:
            return {"not_seafood": True}

        # Fast path: pure Python scoring + template explanation (no extra
        # Gemini calls) — keeps total tool time under ~8 s.
        breakdown, score, grade = compute_score(product_info)
        explanation, score_factors = generate_template_content(
            product_info, breakdown, score, grade
        )
        health = get_health_info(product_info.species)

        score_result = SustainabilityScore(
            score=score,
            grade=grade,
            breakdown=breakdown,
            alternatives=[],
            alternatives_label="",
            explanation=explanation,
            score_factors=score_factors,
            product_info=product_info,
            health=health,
        )

        # Track current product for search comparisons
        self.current_grade = score_result.grade
        self.current_score = score_result.score
        self.current_breakdown = {
            "biological": int(score_result.breakdown.biological),
            "practices": int(score_result.breakdown.practices),
            "management": int(score_result.breakdown.management),
            "ecological": int(score_result.breakdown.ecological),
        }

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
            "not_seafood": False,
            "health_advisory": (
                score_result.health.mercury_category if score_result.health else None
            ),
        }

    async def _handle_search_store(
        self,
        query: str,
        intent: str = "",
    ) -> dict[str, Any]:
        """Search the grocery store and return scored products."""
        log.info("Searching store for: %s (intent: %s)", query, intent or "none")
        self.search_event.clear()
        self.search_data = None

        await self.ws.send_json({"type": "search_store", "query": query})

        try:
            await asyncio.wait_for(
                self.search_event.wait(), timeout=SCREENSHOT_TIMEOUT_S + 15.0
            )
        except asyncio.TimeoutError:
            log.warning("Store search timed out")
            return {"error": "Store search timed out", "products": []}

        msg = self.search_data
        page_text = msg.get("page_text", "") if msg else ""
        log.info(
            "Search results received: %d chars page_text, %d product_links",
            len(page_text),
            len(msg.get("product_links", [])) if msg else 0,
        )
        if page_text:
            log.info("Search page_text preview: %s", page_text[:300])

        if msg is None or (not msg.get("data") and not page_text):
            return {"error": "No search results received", "products": []}

        page_analysis = await analyze_screenshot(
            msg["data"], msg.get("url", ""), msg.get("page_title", ""),
            page_text=page_text,
        )

        seafood = [p for p in page_analysis.products if p.is_seafood]
        log.info(
            "Search analysis: %d total products, %d seafood (page_type=%s)",
            len(page_analysis.products),
            len(seafood),
            page_analysis.page_type,
        )
        if not seafood:
            log.warning(
                "No seafood found in search for '%s' — "
                "page_text was %d chars, %d products extracted (all non-seafood)",
                query,
                len(page_text),
                len(page_analysis.products),
            )
            return {"query": query, "products": [], "message": "No seafood found"}

        # Match scraped product URLs to extracted products by name overlap
        product_links: list[dict[str, str]] = msg.get("product_links", [])
        self.product_links = product_links  # store for navigate_to_product

        scored_products = []
        for p in seafood[:6]:
            breakdown, total, grade = compute_score(p)
            name = p.product_name or p.species or "unknown"
            # Find matching URL from scraped links
            url = _find_product_url(name, product_links, species=p.species)
            entry: dict[str, Any] = {
                "product_name": name,
                "species": p.species,
                "wild_or_farmed": p.wild_or_farmed,
                "score": total,
                "grade": grade,
                "biological": int(breakdown.biological),
                "practices": int(breakdown.practices),
                "management": int(breakdown.management),
                "ecological": int(breakdown.ecological),
            }
            if p.origin_region:
                entry["origin_region"] = p.origin_region
            if p.fishing_method:
                entry["fishing_method"] = p.fishing_method
            if p.price:
                entry["price"] = p.price
            if url:
                entry["url"] = url
            scored_products.append(entry)

        # Filter by user intent (apples-to-apples comparison)
        pre_filter_count = len(scored_products)
        scored_products = _filter_by_intent(scored_products, intent)
        if len(scored_products) < pre_filter_count:
            log.info(
                "Intent filter '%s' narrowed %d → %d products",
                intent, pre_filter_count, len(scored_products),
            )

        sort_field = _sort_key_for_intent(intent)
        scored_products.sort(key=lambda x: x[sort_field], reverse=True)
        log.info(
            "Store search returned %d products (sorted by %s)",
            len(scored_products), sort_field,
        )
        for sp in scored_products:
            log.info(
                "  [search result] %s — total:%d bio:%d prac:%d mgmt:%d eco:%d",
                sp["product_name"], sp["score"],
                sp["biological"], sp["practices"], sp["management"], sp["ecological"],
            )

        # Flag so context_update knows the next navigation is search-triggered
        if scored_products:
            self._awaiting_search_result = True

        # Build a product list so Gemini can choose based on user intent
        # (price, sustainability, similarity, etc.).  Scores are rough
        # estimates from listing text — the real score comes after
        # navigating to the detail page.
        if scored_products:
            product_lines = []
            for i, p in enumerate(scored_products[:6], 1):
                wf = p.get("wild_or_farmed", "unknown")
                prac_label = (
                    "aquaculture_practices"
                    if wf == "farmed"
                    else "fishing_practices"
                )
                line = (
                    f"{i}. {p['product_name']} ({wf}) — "
                    f"score {p['score']}/100 (grade {p['grade']}) — "
                    f"biological: {p['biological']}/20, "
                    f"{prac_label}: {p['practices']}/25, "
                    f"management: {p['management']}/30, "
                    f"ecological: {p['ecological']}/25"
                )
                if p.get("origin_region"):
                    line += f" — origin: {p['origin_region']}"
                if p.get("fishing_method"):
                    line += f" — method: {p['fishing_method']}"
                if p.get("price"):
                    line += f" — {p['price']}"
                if p.get("url"):
                    line += f" [url: {p['url']}]"
                product_lines.append(line)
            product_list = "\n".join(product_lines)

            if sort_field != "score":
                # List is pre-filtered AND pre-sorted by the requested factor.
                ranking_note = (
                    f"IMPORTANT: This list has been pre-filtered and pre-sorted "
                    f"by \"{sort_field}\" to match the user's request "
                    f"(\"{intent}\"). The #1 product has the highest "
                    f"{sort_field} score among comparable options. "
                    f"Pick product #1 whose species matches \"{query}\". "
                    f"Do NOT re-sort by total score.\n\n"
                )
                selection_rules = (
                    f"SELECTION RULES:\n"
                    f"1. Pick product #1 from the list whose species matches "
                    f"\"{query}\". The ranking has already been done for you.\n"
                    f"2. If the user asked for cheapest instead, pick the "
                    f"cheapest matching-species product.\n\n"
                )
            else:
                ranking_note = ""
                # Determine whether the user specified a particular species.
                # Check intent first (user's actual words); fall back to query.
                # If every meaningful word is a generic non-species word →
                # pick the highest-scored product regardless of species.
                _intent_words = {
                    w.strip("?!.,'-")
                    for w in (intent or query).lower().split()
                    if len(w) >= 3
                }
                is_generic = not bool(_intent_words - _NON_SPECIES_INTENT_WORDS)
                if is_generic:
                    selection_rules = (
                        "SELECTION RULES (follow in order):\n"
                        "1. Pick the product with the HIGHEST overall score "
                        "from this list, regardless of species.\n"
                        "2. If the user asked for a DIFFERENT option, pick "
                        "a different product than the one they were just viewing.\n"
                        "3. If the user asked for cheapest, pick the "
                        "cheapest product.\n\n"
                    )
                else:
                    selection_rules = (
                        f"SELECTION RULES (follow in order):\n"
                        f"1. SPECIES MATCH IS MANDATORY — only pick a product "
                        f"whose species matches what the user searched for "
                        f"(\"{query}\"). Never pick a different species.\n"
                        f"2. Pick the matching-species product with the HIGHEST score.\n"
                        f"3. If the user asked for a DIFFERENT option, pick a "
                        f"different product than the one they were just viewing.\n"
                        f"4. If the user asked for cheapest, pick the cheapest "
                        f"matching-species product.\n\n"
                    )

            summary = (
                f"Found {len(scored_products)} seafood products "
                f"for query \"{query}\":\n"
                f"{product_list}\n\n"
                f"{ranking_note}"
                f"{selection_rules}"
                f"IMMEDIATELY call navigate_to_product with the chosen "
                f"product's URL. Do NOT repeat your intent multiple "
                f"times — say ONE brief sentence, then call the tool."
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
                "Say ONE brief sentence — like 'Ok, found something for you.' "
                "or 'Got one, loading it now.' "
                "Do NOT mention the species or product name. "
                "Then STOP completely and wait silently for the score."
            ),
        }

    def _format_context_update(self, msg: dict[str, Any]) -> str:
        """Format a context_update message as text for Gemini."""
        phase = msg.get("phase", "")

        # Error or 404 page — screen analyzer found no seafood after navigation
        if msg.get("page_type") == "no_seafood":
            was_search = self._awaiting_search_result
            self._awaiting_search_result = False
            if was_search:
                return (
                    "[context-update-error] The product page failed to load — "
                    "it appears to be a 404 or error page. "
                    "Say ONE sentence: 'That link didn't work.' "
                    "Then immediately call search_store with the same species "
                    "query to find a working alternative. "
                    "Do NOT ask the user anything — just search again silently."
                )
            return (
                "[context-update-no-seafood] No seafood product was found on "
                "this page. Tell the user in one sentence. "
                "Offer to check something else when they're ready."
            )

        if phase == "scored":
            # Search flow: navigate_to_product already spoke; stay silent until
            # the complete phase arrives with the real score.
            if self._awaiting_search_result:
                return ""

            return (
                "[context-update-identified] "
                "The sustainability assessment is now building. "
                "Say ONE short sentence — like 'Ok, building the assessment.' "
                "Do NOT say 'in a moment', 'shortly', 'results coming', "
                "or anything implying a wait. Do NOT mention the species "
                "or product name. Then STOP."
            )

        # Product listing: multiple products scored
        if msg.get("page_type") == "product_listing":
            all_products = msg.get("all_products") or []
            listing_summary = msg.get("listing_summary") or ""
            lines = []
            for p in all_products:
                name = (
                    p.get("product_name")
                    or p.get("species")
                    or "unknown"
                )
                lines.append(
                    f"- {name}: Grade {p.get('grade')}, "
                    f"Score {p.get('score')}/100 "
                    f"({p.get('wild_or_farmed', 'unknown')})"
                )
            product_list = "\n".join(lines)

            closing = (
                "End by telling them: tap a product card from this list "
                "to go to that product page, or select another product "
                "from the website to score."
            )
            if listing_summary:
                return (
                    f"[context-update-listing] The results are in! "
                    f"We scored {len(all_products)} seafood products "
                    f"on this page:\n{product_list}\n\n"
                    f"Written summary shown in the panel:\n"
                    f"{listing_summary}\n\n"
                    f"Speak this summary naturally — paraphrase it as "
                    f"spoken advice, don't read it word-for-word. "
                    f"{closing}"
                )
            return (
                f"[context-update-listing] The results are in! "
                f"We scored {len(all_products)} seafood products "
                f"on this page:\n{product_list}\n"
                f"Give a brief overview of the best and worst options. "
                f"{closing}"
            )

        # Complete phase: final score + alternatives (single product)
        grade = msg.get("grade", "?")
        score_val = msg.get("score", 0)
        # Track current product for search comparisons
        if grade != "?":
            self.current_grade = str(grade)
            self.current_score = int(score_val)
            bd = msg.get("breakdown") or {}
            if bd:
                self.current_breakdown = {
                    "biological": int(bd.get("biological", 0)),
                    "practices": int(bd.get("practices", 0)),
                    "management": int(bd.get("management", 0)),
                    "ecological": int(bd.get("ecological", 0)),
                }

        from_search = ""
        if self._awaiting_search_result:
            from_search = (
                "This is the product from your search — "
                "now you have the full, accurate score. "
            )
            self._awaiting_search_result = False

        parts = [
            f"[context-update-final] {from_search}"
            f"RESPOND NOW — tell the user the results are in. "
            f"Grade {grade}, {score_val}/100. "
            f"Give your grade-appropriate assessment (see guidelines)."
        ]

        alts = msg.get("alternatives") or []
        if alts:
            alt_lines = []
            for a in alts[:3]:
                alt_species = a.get("species", "unknown")
                alt_grade = a.get("grade", "?")
                reason = a.get("reason", "")
                alt_lines.append(
                    f"- {alt_species}: Grade {alt_grade} — {reason}"
                )
            parts.append("Alternatives:\n" + "\n".join(alt_lines))

        explanation = msg.get("explanation")
        if explanation:
            parts.append(f"Explanation: {explanation}")

        return "\n".join(parts)

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(KEEPALIVE_INTERVAL_S)
            try:
                await self.ws.send_json({"type": "ping"})
            except Exception:
                break
