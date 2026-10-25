"""Minor-unit helpers. Amounts are always integers in the currency's minor unit."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

#: ISO 4217 currencies without a minor unit.
ZERO_DECIMAL = frozenset({"XOF", "XAF", "RWF", "UGX", "BIF", "DJF", "GNF", "KMF", "JPY", "KRW", "VND"})


def exponent(currency: str) -> int:
    return 0 if currency.upper() in ZERO_DECIMAL else 2


def to_major(amount_minor: int, currency: str) -> Decimal:
    return (Decimal(amount_minor) / (Decimal(10) ** exponent(currency))).quantize(
        Decimal(1).scaleb(-exponent(currency))
    )


def to_minor(amount_major: object, currency: str) -> int:
    value = Decimal(str(amount_major)) * (Decimal(10) ** exponent(currency))
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
