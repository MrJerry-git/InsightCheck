"""体检验项目录的费用管理：金额、币种、来源、适用机构或地区、生效日期、演示价标记。

金额一律使用最小货币单位（整数分）保存，全流程不做浮点累加。
测试价格必须标记 ``is_demo_price=True``；真实价格必须记录可核验来源。
"""

from collections.abc import Iterable
from datetime import date
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_CURRENCY = "CNY"
DEMO_CATALOG_VERSION = "demo-price-catalog-v1"
DEMO_PRICE_SOURCE = "DEMO PRICE：工程演示固定价格，不代表任何机构的真实收费"
DEMO_EFFECTIVE_FROM = date(2020, 1, 1)

DEMO_PRICE_CENTS_BY_COST_LEVEL: dict[str, int] = {
    "low": 12_000,
    "medium": 45_000,
    "high": 128_000,
}


def format_amount(amount_cents: int, currency: str) -> str:
    """把整数分格式化为可读金额，不使用浮点。"""

    sign = "-" if amount_cents < 0 else ""
    units, cents = divmod(abs(amount_cents), 100)
    return f"{sign}{units}.{cents:02d} {currency}"


def normalize_currency_code(value: str) -> str:
    """统一币种写法：去掉首尾空白并转大写，只接受三字母代码。

    预算与价格共用同一个函数，保证 ``cny`` 与 ``CNY`` 不会绕过同币种比较。
    """

    cleaned = value.strip().upper()
    if len(cleaned) != 3 or not cleaned.isascii() or not cleaned.isalpha():
        raise ValueError("币种必须是三字母代码，例如 CNY")
    return cleaned


class ExamItemPrice(BaseModel):
    """一条可追溯的项目价格记录。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exam_item_code: str = Field(min_length=1, max_length=64)
    amount_cents: int = Field(ge=0)
    # 长度校验交给 normalize_currency_code，先允许空白再统一清理。
    currency: str = Field(default=DEFAULT_CURRENCY, max_length=16)
    source: str = Field(min_length=1, max_length=300)
    source_url: str | None = Field(default=None, max_length=500)
    institution: str | None = Field(default=None, max_length=200)
    region: str | None = Field(default=None, max_length=100)
    effective_from: date
    effective_to: date | None = None
    is_demo_price: bool = True
    note: str | None = Field(default=None, max_length=300)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return normalize_currency_code(value)

    @field_validator("exam_item_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip()

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("价格来源不能为空白")
        return cleaned

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        """来源链接必须非空白且是 http/https 地址，避免用空格绕过来源校验。"""

        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("来源链接不能为空白；真实价格必须记录可核验来源")
        parsed = urlsplit(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("来源链接必须是 http 或 https 地址")
        return cleaned

    @field_validator("institution", "region", "note")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_provenance(self) -> "ExamItemPrice":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("价格失效日期不能早于生效日期")
        if not self.is_demo_price and not self.source_url:
            raise ValueError("真实价格必须记录可核验来源（source_url）")
        return self


class PriceCatalog(BaseModel):
    """一次方案构建所使用的价格目录快照，只做查询，不写数据库。

    ``institution`` / ``region`` 是目录自身的适用范围；查询时未显式指定的范围沿用目录范围，
    因此「按机构加载的目录」不会在后续查询里悄悄退回通用价格。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog_version: str = Field(default="unspecified", min_length=1, max_length=64)
    prices: tuple[ExamItemPrice, ...] = ()
    institution: str | None = Field(default=None, max_length=200)
    region: str | None = Field(default=None, max_length=100)

    def lookup(
        self,
        exam_item_code: str,
        as_of_date: date,
        *,
        institution: str | None = None,
        region: str | None = None,
        currency: str | None = None,
    ) -> ExamItemPrice | None:
        """按项目编码与截止日期取价格，优先机构/地区更具体、生效更晚的记录。"""

        target_code = exam_item_code.strip().upper()
        target_currency = currency.strip().upper() if currency else None
        scope_institution = self.institution if institution is None else institution
        scope_region = self.region if region is None else region
        matches = [
            price
            for price in self.prices
            if price.exam_item_code.upper() == target_code
            and price.effective_from <= as_of_date
            and (price.effective_to is None or as_of_date <= price.effective_to)
            and (target_currency is None or price.currency == target_currency)
            and price.institution in (None, scope_institution)
            and price.region in (None, scope_region)
        ]
        if not matches:
            return None
        matches.sort(
            key=lambda price: (
                price.institution is not None,
                price.region is not None,
                price.effective_from,
                price.source,
            ),
            reverse=True,
        )
        return matches[0]

    def currencies(self) -> tuple[str, ...]:
        return tuple(sorted({price.currency for price in self.prices}))

    def has_demo_price(self) -> bool:
        return any(price.is_demo_price for price in self.prices)


def build_demo_catalog(
    entries: Iterable[tuple[str, str]],
    *,
    catalog_version: str = DEMO_CATALOG_VERSION,
    currency: str = DEFAULT_CURRENCY,
    effective_from: date = DEMO_EFFECTIVE_FROM,
) -> PriceCatalog:
    """按 ``(项目编码, 费用等级)`` 生成演示价格目录，所有价格都标记为演示价。

    该函数只用于工程演示与测试，不能替代真实价格来源。
    """

    prices: list[ExamItemPrice] = []
    seen: set[str] = set()
    for code, cost_level in entries:
        normalized_code = code.strip()
        key = normalized_code.upper()
        if key in seen:
            continue
        seen.add(key)
        level = cost_level.strip().lower()
        if level not in DEMO_PRICE_CENTS_BY_COST_LEVEL:
            raise ValueError(f"未知费用等级：{cost_level}")
        prices.append(
            ExamItemPrice(
                exam_item_code=normalized_code,
                amount_cents=DEMO_PRICE_CENTS_BY_COST_LEVEL[level],
                currency=currency,
                source=DEMO_PRICE_SOURCE,
                effective_from=effective_from,
                is_demo_price=True,
                note=f"费用等级 {level}",
            )
        )
    return PriceCatalog(catalog_version=catalog_version, prices=tuple(prices))
