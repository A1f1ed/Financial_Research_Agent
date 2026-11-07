"""Decimal arithmetic on explicitly reviewed source figures, never model math.

Code checks source tokens, units and compatibility. Column/metric/period meaning
is explicitly confirmed by a human; arithmetic is not independent financial
statement reconciliation or semantic verification.
"""
from datetime import date
from decimal import Decimal, localcontext
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Unit = Literal["ones", "thousands", "ten_thousands", "millions", "hundred_millions", "percent"]
Currency = Literal["CNY", "HKD", "USD", "EUR", "GBP", "JPY"]
Operation = Literal["convert", "sum", "difference", "ratio_percent", "percentage_change", "year_over_year_change"]
FACTORS = {"ones": Decimal(1), "thousands": Decimal(1000), "ten_thousands": Decimal(10000),
           "millions": Decimal(1000000), "hundred_millions": Decimal(100000000), "percent": Decimal(1)}
NUMBER = re.compile(r"(?<![\w.,(+\-])(?:[+\-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\))%?(?![\w.,%)])")


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FigureInput(StrictInput):
    search_id: UUID
    citation_id: str = Field(pattern=r"^K[1-9][0-9]*$")
    value_start: int = Field(ge=0, le=20000)
    value_text: str = Field(min_length=1, max_length=45)
    metric: str = Field(min_length=1, max_length=160)
    unit: Unit
    currency: Currency | None = None
    unit_page_number: int = Field(ge=1, le=5000)
    unit_start: int = Field(ge=0, le=1000000)
    unit_quote: str = Field(min_length=1, max_length=100)
    period_type: Literal["duration", "as_at"]
    period_start: date
    period_end: date
    basis: str = Field(min_length=1, max_length=160)
    confirmation: Literal["source_and_column_checked"]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("metric", "basis", "reason")
    @classmethod
    def readable(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value): raise ValueError("Provide readable review details")
        return value.strip()

    @model_validator(mode="after")
    def meaning(self):
        if self.period_start > self.period_end: raise ValueError("Reporting period is reversed")
        if self.period_type == "as_at" and self.period_start != self.period_end: raise ValueError("A balance-date figure needs one date")
        if self.period_type == "duration" and self.period_start == self.period_end: raise ValueError("A duration figure needs a period")
        if (self.unit == "percent") != (self.currency is None): raise ValueError("Choose currency for monetary figures; percentages have no currency")
        return self


class FigureAction(StrictInput):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def readable(cls, value): return FigureInput.readable(value)


class CalculationInput(StrictInput):
    operation: Operation
    figure_ids: list[UUID] = Field(min_length=1, max_length=8)
    target_unit: Unit | None = None
    signs: list[Literal[-1, 1]] | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def arity(self):
        count = len(self.figure_ids)
        if len(set(self.figure_ids)) != count: raise ValueError("Choose each reviewed input once")
        if self.operation == "convert" and (count != 1 or not self.target_unit): raise ValueError("Conversion needs one input and a target unit")
        if self.operation == "sum" and count < 2: raise ValueError("Sum needs at least two inputs")
        if self.operation not in {"convert", "sum"} and count != 2: raise ValueError("This operation needs two ordered inputs")
        if self.operation != "convert" and self.target_unit: raise ValueError("Target unit applies only to conversion")
        if self.signs is not None and (self.operation!="sum" or len(self.signs)!=count): raise ValueError("Signed sums need one explicit +1/-1 sign per input")
        return self


def numeric_tokens(text):
    return [{"start": m.start(), "text": m.group()} for m in NUMBER.finditer(text)]


def numeric_value(text):
    if not NUMBER.fullmatch(text): raise ValueError("Select a complete numeric source token")
    clean = text.removesuffix("%").replace(",", "")
    if clean.startswith("("): clean = "-" + clean[1:-1]
    value = Decimal(clean)
    if not value.is_finite() or abs(value) > Decimal("1e24"): raise ValueError("Numeric input exceeds the supported range")
    return value


def unit_aliases():
    result = {"%": (None, "percent"), "％": (None, "percent")}
    zh = {"CNY": ["人民币", "人民幣"], "HKD": ["港币", "港幣"]}
    suffixes = {"ones": ["元"], "thousands": ["千元"], "ten_thousands": ["万元", "萬元"],
                "millions": ["百万元", "百萬元"], "hundred_millions": ["亿元", "億元"]}
    for currency, prefixes in zh.items():
        for prefix in prefixes:
            for unit, endings in suffixes.items():
                for ending in endings:
                    result[prefix + ending] = (currency, unit)
                    result[ending + prefix] = (currency, unit)
    en = {"CNY": ["RMB", "CNY"], "HKD": ["HK$", "HKD"], "USD": ["US$", "USD"],
          "EUR": ["EUR", "€"], "GBP": ["GBP", "£"], "JPY": ["JPY"]}
    for currency, prefixes in en.items():
        for prefix in prefixes:
            for unit, endings in {"ones": ["units"], "thousands": ["'000", "thousand", "thousands"],
                                  "millions": ["million", "millions"], "ten_thousands": ["ten thousand"],
                                  "hundred_millions": ["hundred million"]}.items():
                for ending in endings: result[prefix + " " + ending] = (currency, unit)
    return result


def normalize_unit(text): return re.sub(r"[\s()（）\[\]:'’]", "", text).casefold()


def check_unit(quote, currency, unit):
    aliases = {normalize_unit(label): meaning for label, meaning in unit_aliases().items()}
    if aliases.get(normalize_unit(quote)) != (currency, unit):
        raise ValueError("The exact unit/currency phrase does not match the chosen scale; verify the original header")


def unit_spans(text):
    """Whole recognized expressions only: 元人民币 inside 千元人民币 is invalid."""
    found=[]
    for phrase,(currency,unit) in sorted(unit_aliases().items(),key=lambda item:-len(item[0])):
        pattern=re.compile(re.escape(phrase).replace(r"\ ",r"\s*").replace("'","['’]"),re.I)
        for match in pattern.finditer(text[:20000]):
            before=text[match.start()-1] if match.start() else ""
            after=text[match.end():match.end()+1]
            if before and before in "十百千万亿億萬兆":continue
            if phrase[0].isascii() and phrase[0].isalpha() and before and before.isascii() and before.isalpha():continue
            if after and after.isascii() and after.isalpha():continue
            item={"start":match.start(),"quote":match.group(),"currency":currency,"unit":unit}
            if item not in found:found.append(item)
            if len(found)>=500:break
        if len(found)>=500:break
    return sorted([item for item in found if not any(other["start"]<=item["start"]
        and other["start"]+len(other["quote"])>=item["start"]+len(item["quote"])
        and len(other["quote"])>len(item["quote"]) for other in found)],key=lambda item:item["start"])


def arithmetic(inputs, figures):
    """Inputs are immutable reviewed body snapshots in the requested order."""
    first = figures[0]
    if any((f["currency"], f["subject"], f["basis"].casefold(), f["period_type"]) !=
           (first["currency"], first["subject"], first["basis"].casefold(), first["period_type"]) for f in figures):
        raise ValueError("Currency, company, consolidation basis and period type must align; no FX or scope assumptions are made")
    if any((f["unit"] == "percent") != (first["unit"] == "percent") for f in figures):
        raise ValueError("Percentages and monetary figures cannot be mixed")
    change = inputs.operation in {"percentage_change", "year_over_year_change"}
    different_periods=any((f["period_start"],f["period_end"])!=(first["period_start"],first["period_end"]) for f in figures)
    compare_periods=change or inputs.operation=="difference" and different_periods
    if not compare_periods and different_periods:
        raise ValueError("These inputs cover different reporting periods")
    if compare_periods:
        current, baseline = figures
        starts = [date.fromisoformat(f["period_start"]) for f in figures]
        ends = [date.fromisoformat(f["period_end"]) for f in figures]
        if current["metric"].casefold() != baseline["metric"].casefold(): raise ValueError("Change requires the same reviewed metric")
        if ends[1] >= starts[0]: raise ValueError("Baseline must precede the current period; overlapping or cumulative periods need separate review")
        if abs((ends[0]-starts[0]).days-(ends[1]-starts[1]).days) > 3:
            raise ValueError("Different period lengths cannot be treated as comparable growth")
        if inputs.operation == "year_over_year_change" and not all(
                a.year == b.year+1 and (a.month,a.day)==(b.month,b.day) for a,b in ((starts[0],starts[1]),(ends[0],ends[1]))):
            raise ValueError("Year-over-year requires aligned prior-year start and end dates")
    with localcontext() as context:
        context.prec = 40
        values = [Decimal(f["value"]) * FACTORS[f["unit"]] for f in figures]
        result_unit = first["unit"]; currency = first["currency"]
        if inputs.operation == "convert":
            if (first["unit"] == "percent") != (inputs.target_unit == "percent"): raise ValueError("Conversion cannot change the measurement dimension")
            result_unit = inputs.target_unit
            result = values[0] / FACTORS[result_unit]; formula = "value × source scale / target scale"
        elif inputs.operation == "sum":
            signs=inputs.signs or [1]*len(values)
            result = sum(value*sign for value,sign in zip(values,signs)) / FACTORS[result_unit]
            formula = "sum of explicit signs × normalized inputs / output scale"
        elif inputs.operation == "difference":
            result = (values[0]-values[1]) / FACTORS[result_unit]; formula = "(first − second) / output scale"
            if result_unit == "percent": result_unit = "percentage_points"
        else:
            if values[1] == 0 or change and values[1] < 0: raise ValueError("Zero or negative change baseline does not support this percentage calculation")
            result = ((values[0]-values[1]) if change else values[0]) / values[1] * 100
            formula = "(current − baseline) / baseline × 100" if change else "numerator / denominator × 100"
            result_unit = "percent"; currency = None
        return {"value": format(result.normalize(), "f"), "unit": result_unit, "currency": currency,"calculation_version":"decimal-reviewed-v1",
                "formula": formula, "precision": 40, "operation": inputs.operation,
                "verification": "Exact source tokens and units checked by code; column, period and consolidation interpretation confirmed by the user; arithmetic computed with Decimal. This is not independent statement reconciliation."}
