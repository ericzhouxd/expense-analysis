"""Local student plans and cent-exact, UI-independent reserve accounting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date


def month_after(start: date, offset: int) -> date:
    index = start.year * 12 + start.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def split_cents(amount: int, count: int) -> list[int]:
    base, remainder = divmod(amount, count)
    return [base + (index < remainder) for index in range(count)]


@dataclass(frozen=True)
class Commitment:
    name: str
    amount_cents: int
    categories: tuple[str, ...]
    cadence: str = "Monthly"
    first_month: int = 0
    months: int = 9


@dataclass(frozen=True)
class SpendingPlan:
    name: str
    start: date
    months: int
    academic_target_cents: int
    summer_target_cents: int
    buffer_cents: int
    commitments: tuple[Commitment, ...]
    reference: dict
    # Per-transaction budget month, not an edit to the bank transaction date.
    allocations: dict[str, str] = field(default_factory=dict)

    @property
    def month_keys(self) -> list[str]:
        return [month_after(self.start, i).strftime("%Y-%m") for i in range(self.months)]

    @property
    def total_target_cents(self) -> int:
        return self.academic_target_cents + self.summer_target_cents

    def validate(self) -> SpendingPlan:
        if not self.name.strip() or self.start.day != 1 or self.months not in (9, 12):
            raise ValueError("Choose a name, a month-start date, and a 9- or 12-month plan.")
        amounts = [self.academic_target_cents, self.summer_target_cents, self.buffer_cents]
        if any(type(value) is not int or value < 0 for value in amounts):
            raise ValueError("Plan amounts must be nonnegative integer cents.")
        if self.academic_target_cents == 0:
            raise ValueError("The academic-year spending target must be positive.")
        if self.months == 9 and self.summer_target_cents:
            raise ValueError("Summer funding requires a 12-month plan.")
        names: set[str] = set()
        occupied: set[tuple[str, int]] = set()
        for cost in self.commitments:
            if not cost.name.strip() or cost.name in names:
                raise ValueError("Give every committed cost a unique, nonempty name.")
            names.add(cost.name)
            if type(cost.amount_cents) is not int or cost.amount_cents < 0:
                raise ValueError(f"{cost.name}: enter a nonnegative amount.")
            if cost.cadence not in ("Monthly", "Quarterly", "Coverage total"):
                raise ValueError(f"{cost.name}: choose a supported reserve cycle.")
            if (
                type(cost.first_month) is not int
                or type(cost.months) is not int
                or cost.first_month < 0
                or cost.months < 1
                or cost.first_month + cost.months > self.months
            ):
                raise ValueError(f"{cost.name}: coverage must stay within the plan.")
            if cost.cadence == "Quarterly" and cost.months % 3:
                raise ValueError(f"{cost.name}: quarterly coverage must be a multiple of 3 months.")
            for category in cost.categories:
                if not category.strip():
                    raise ValueError("Category names cannot be empty.")
                for index in range(cost.first_month, cost.first_month + cost.months):
                    key = (category, index)
                    if key in occupied:
                        raise ValueError(f"{category} matches overlapping bills. Map it only once.")
                    occupied.add(key)
        if any(value not in self.month_keys for value in self.allocations.values()):
            raise ValueError("Payment allocations must refer to months inside this plan.")
        return self

    def to_dict(self) -> dict:
        self.validate()
        return {**asdict(self), "start": self.start.isoformat(), "schema_version": 1}

    @classmethod
    def from_dict(cls, payload: dict) -> SpendingPlan:
        values = dict(payload)
        if values.pop("schema_version", None) != 1:
            raise ValueError("Unsupported spending-plan version.")
        values["start"] = date.fromisoformat(values["start"])
        values["commitments"] = tuple(
            Commitment(**{**item, "categories": tuple(item["categories"])})
            for item in values["commitments"]
        )
        return cls(**values).validate()


def calculate_plan(plan: SpendingPlan, transactions: list[dict]) -> dict:
    """Reserve max(planned, net paid) per bill cycle, spread over its coverage.

    Actuals replace reserves, never add a second deduction. Refunds reduce net
    spending; unspent bill reserves stay protected until the plan is edited.
    Every expense/refund is either matched once or counted as flexible spending.
    """
    plan.validate()
    keys = plan.month_keys
    targets = split_cents(plan.academic_target_cents, 9)
    if plan.months == 12:
        targets += split_cents(plan.summer_target_cents, 3)
    buffers = split_cents(plan.buffer_cents, plan.months)
    months = [
        {
            "month": key,
            "target": targets[i],
            "buffer": buffers[i],
            "reserved": 0,
            "flexible_spent": 0,
            "committed_paid": 0,
            "categories": {},
        }
        for i, key in enumerate(keys)
    ]
    months_by_key = dict(zip(keys, months, strict=True))
    obligations = []
    mapping = {}
    for cost in plan.commitments:
        length = {"Monthly": 1, "Quarterly": 3, "Coverage total": cost.months}[cost.cadence]
        for start in range(cost.first_month, cost.first_month + cost.months, length):
            coverage = list(range(start, start + length))
            obligation = {
                "name": cost.name,
                "coverage": coverage,
                "planned": cost.amount_cents,
                "paid": 0,
            }
            obligations.append(obligation)
            for i in coverage:
                for category in cost.categories:
                    mapping[category, keys[i]] = obligation
    classified = []
    for transaction in transactions:
        kind = transaction["transaction_type"]
        if kind not in ("expense", "refund"):
            continue
        month_key = plan.allocations.get(
            transaction["id"], str(transaction["transaction_date"])[:7]
        )
        month = months_by_key.get(month_key)
        if month is None:
            continue
        amount = int(transaction["amount_cents"]) * (-1 if kind == "refund" else 1)
        category = transaction["category"]
        obligation = mapping.get((category, month_key))
        if obligation is not None:
            obligation["paid"] += amount
            month["committed_paid"] += amount
        else:
            month["flexible_spent"] += amount
            month["categories"][category] = month["categories"].get(category, 0) + amount
        classified.append(
            {
                **transaction,
                "budget_month": month_key,
                "net_cents": amount,
                "budget_bucket": obligation["name"] if obligation else "Everyday",
            }
        )
    for obligation in obligations:
        obligation["reserved"] = max(obligation["planned"], obligation["paid"])
        obligation["unpaid"] = max(0, obligation["planned"] - obligation["paid"])
        for i, amount in zip(
            obligation["coverage"],
            split_cents(obligation["reserved"], len(obligation["coverage"])),
            strict=True,
        ):
            months[i]["reserved"] += amount
    quarters = []
    for first in range(0, plan.months, 3):
        quarter_months = months[first : first + 3]
        quarter = {
            field: sum(month[field] for month in quarter_months)
            for field in ("target", "buffer", "reserved", "flexible_spent", "committed_paid")
        }
        quarter["allowance"] = quarter["target"] - quarter["buffer"] - quarter["reserved"]
        quarter["remaining"] = quarter["allowance"] - quarter["flexible_spent"]
        quarter["months"] = [month["month"] for month in quarter_months]
        rollover = 0
        for month, allowance in zip(
            quarter_months, split_cents(quarter["allowance"], 3), strict=True
        ):
            month["allowance"] = allowance
            month["rollover"] = rollover
            month["remaining"] = allowance + rollover - month["flexible_spent"]
            rollover = month["remaining"]
        quarters.append(quarter)
    return {
        "months": months,
        "quarters": quarters,
        "obligations": obligations,
        "transactions": classified,
    }
