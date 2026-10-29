def revenue_growth(previous: float, current: float) -> float:
    """Returns the revenue growth rate, where 0.2 represents a 20% increase."""
    if previous <= 0:
        raise ValueError("previous must be greater than 0")

    return (current - previous) / previous

def gross_margin(revenue: float, cost_of_revenue: float) -> float:
    """Returns the gross margin, where 0.4 represents 40%."""
    if revenue <= 0:
        raise ValueError("revenue must be greater than 0")

    if cost_of_revenue < 0:
        raise ValueError("cost of revenue cannot be negative")

    return (revenue - cost_of_revenue) / revenue


if __name__ == "__main__":
    growth = revenue_growth(previous=100.0, current=120.0)
    margin = gross_margin(revenue=100.0, cost_of_revenue=120.0)
    print(f"Revenue growth: {growth:.1%}")
    print(f"Gross margin: {margin:.1%}")