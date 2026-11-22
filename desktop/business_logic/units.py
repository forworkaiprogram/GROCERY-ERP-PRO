"""Units and conversions with exact rational arithmetic.

Conversions are stored as numerator/denominator integer pairs so that
1 carton = 12 packs and 1 pack = 6 pieces are exact; converting 0.5 packs
to pieces yields exactly 3, and invalid cross-dimension conversions raise.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from .money import D, MoneyError


class ConversionError(ValueError):
    pass


@dataclass(frozen=True)
class Unit:
    uuid: str
    code: str
    name: str
    dimension: str  # COUNT | MASS | VOLUME
    is_base: bool


class UnitConverter:
    """Backed by unit_conversions rows; builds a BFS shortest-path graph."""

    def __init__(self, rows: list[dict]):
        # rows: {from_unit, to_unit, numerator, denominator}
        self.units: dict[str, Unit] = {}
        self.edges: dict[str, list[tuple[str, Fraction]]] = {}
        for r in rows:
            src, dst = r["from_unit"], r["to_unit"]
            factor = Fraction(int(r["numerator"]), int(r["denominator"]))
            self.edges.setdefault(src, []).append((dst, factor))
            self.edges.setdefault(dst, []).append((src, Fraction(1) / factor))

    def add_unit(self, unit: Unit) -> None:
        self.units[unit.uuid] = unit

    def can_convert(self, src: str, dst: str) -> bool:
        return src == dst or self._find_path(src, dst) is not None

    def convert(self, value, src: str, dst: str) -> Decimal:
        """Exact conversion; result quantized to 4dp only at the end."""
        value = D(value)
        if value < 0:
            raise MoneyError("quantity cannot be negative")
        if src == dst:
            return value
        path = self._find_path(src, dst)
        if path is None:
            raise ConversionError(f"no conversion path between {src!r} and {dst!r}")
        factor = Fraction(1)
        for edge_factor in path:
            factor *= edge_factor
        result = Decimal(value) * Decimal(factor.numerator) / Decimal(factor.denominator)
        return result.quantize(Decimal("0.0001"))

    def _find_path(self, src: str, dst: str) -> list[Fraction] | None:
        if src not in self.edges and dst not in self.edges:
            return None
        visited = {src}
        queue: list[tuple[str, list[Fraction]]] = [(src, [])]
        while queue:
            node, path = queue.pop(0)
            for neighbor, factor in self.edges.get(node, []):
                if neighbor == dst:
                    return path + [factor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [factor]))
        return None


def convert_quantity(converter: UnitConverter, value, src: str, dst: str) -> Decimal:
    return converter.convert(value, src, dst)
