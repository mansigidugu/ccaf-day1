CATEGORIES = [
    "Internet Outage",
    "Billing",
    "Account",
    "Technical Support",
]

PRIORITIES = [
    "Low",
    "Medium",
    "High",
    "Urgent",
]


def validate(data):
    category = data.get("category")
    priority = data.get("priority")

    if category not in CATEGORIES:
        return (
            False,
            f'category "{category}" not allowed; '
            f'use {", ".join(CATEGORIES)}'
        )

    if priority not in PRIORITIES:
        return (
            False,
            f'priority "{priority}" not allowed; '
            f'use Low/Medium/High/Urgent'
        )

    return True, None


record = {
    "category": "Internet Outage",
    "priority": "Critical",
    "summary": "Customer has no internet connection.",
}

valid, reason = validate(record)

print("Valid:", valid)
print("Reason:", reason)