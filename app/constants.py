PLANS = {
    "2d": {"label": "2 Days Weekend", "amount": 6.0, "hours": 48},
    "7d": {"label": "1 Week", "amount": 15.0, "hours": 168},
    "30d": {"label": "1 Month", "amount": 50.0, "hours": 720},
    "120d": {"label": "3 Months (+1 Month Free)", "amount": 140.0, "hours": 2880},
}

BULK_POINTS_PACKAGES = {
    "5": {"label": "5 Points", "amount": 5.0, "points": 5},
    "10": {"label": "10 Points", "amount": 9.5, "points": 10},
    "25": {"label": "25 Points", "amount": 22.5, "points": 25},
    "50": {"label": "50 Points", "amount": 42.5, "points": 50},
    "100": {"label": "100 Points", "amount": 80.0, "points": 100},
}

PRODUCT_TYPES = ("code_claimer", "api_claimer")

REFERRAL_REWARD_RATE = 0.10

# API Claimer deploy-time / manageable container settings (ported from the
# bot's currency/vault/process_all/drops configuration feature).
API_CLAIMER_CURRENCY_OPTIONS = ("usdt", "btc", "eth", "ltc", "trx", "doge")

API_CLAIMER_DROP_OPTIONS = (
    "Daily1",
    "Daily2",
    "Daily3",
    "DailyOther",
    "HighRollers",
    "PlaySmarter",
    "WeeklyStream",
    "OtherDrops",
)

API_CLAIMER_DEFAULT_SETTINGS = {
    "currency": None,
    "vault": None,
    "process_all": None,
    "drops": None,
}
