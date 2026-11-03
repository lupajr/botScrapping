"""Esquema de dados padronizado: toda loja devolve exatamente estes campos."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProductOffer(BaseModel):
    store_name: str
    title: str
    price: float = Field(gt=0)
    currency: str = "BRL"
    url: str
    rating: float = Field(default=0.0, ge=0, le=5)  # Ex.: 4.7
    reviews_count: int = Field(default=0, ge=0)  # Ex.: 1250
    reliability_score: float = 0.0  # Média bayesiana, calculada no scorer


class StoreResult(BaseModel):
    """Resultado de uma loja: as ofertas encontradas ou o erro que ocorreu."""

    store_name: str
    offers: list[ProductOffer] = Field(default_factory=list)
    error: str | None = None
    elapsed_seconds: float = 0.0
