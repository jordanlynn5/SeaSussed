from typing import Literal

from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    screenshot: str  # base64-encoded PNG
    url: str  # current page URL
    page_title: str = ""
    related_products: list[str] = []  # product titles scraped from DOM


class ScoreRequest(BaseModel):
    product_info: "ProductInfo"  # corrected by user; no vision step


class ProductInfo(BaseModel):
    is_seafood: bool
    species: str | None
    wild_or_farmed: Literal["wild", "farmed", "unknown"]
    fishing_method: str | None
    origin_region: str | None
    certifications: list[str]  # ["MSC", "ASC", "BAP", "ASMI", ...]
    product_name: str | None = None


class ScoreBreakdown(BaseModel):
    biological: float  # 0–20
    practices: float  # 0–25
    management: float  # 0–30
    ecological: float  # 0–25


class ScoreFactor(BaseModel):
    category: str  # "Biological & Population", "Fishing Practices", etc.
    score: float
    max_score: int
    explanation: str  # product-specific WHY: what was found + why it scored this way
    tip: str | None  # actionable shopping tip — only for C/D grade products


class Alternative(BaseModel):
    species: str
    score: int
    grade: str
    reason: str
    from_page: bool  # True = scraped from page DOM; False = seed DB


class PageAnalysis(BaseModel):
    page_type: Literal["single_product", "product_listing", "no_seafood"]
    products: list[ProductInfo]


class PageProduct(BaseModel):
    product_name: str
    species: str | None
    wild_or_farmed: Literal["wild", "farmed", "unknown"]
    certifications: list[str]
    score: int
    grade: Literal["A", "B", "C", "D"]
    breakdown: ScoreBreakdown


class SustainabilityScore(BaseModel):
    score: int
    grade: Literal["A", "B", "C", "D"]
    breakdown: ScoreBreakdown
    alternatives: list[Alternative]  # 1–3 items
    alternatives_label: str  # "Similar great choices" or "Better alternatives"
    explanation: str  # 2–3 sentences mentioning visible vs unknown fields
    score_factors: list[ScoreFactor]  # per-category educational content
    product_info: ProductInfo


class AnalyzeResponse(BaseModel):
    page_type: Literal["single_product", "product_listing", "no_seafood"]
    result: SustainabilityScore | None = None  # single_product or no_seafood
    products: list[PageProduct] = []  # product_listing
