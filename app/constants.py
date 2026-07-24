PLANS = {
    "2d": {"label": "2 Days Weekend", "amount": 6.0, "hours": 48},
    "7d": {"label": "1 Week", "amount": 15.0, "hours": 168},
    "30d": {"label": "1 Month", "amount": 50.0, "hours": 720},
    "120d": {"label": "3 Months (+1 Month Free)", "amount": 140.0, "hours": 2880},
}

BULK_POINTS_PACKAGES = {
    "6": {"label": "6 Points", "amount": 6.0, "points": 6},
    "12": {"label": "12 Points", "amount": 11.8, "points": 12},
    "18": {"label": "18 Points", "amount": 17.5, "points": 18},
    "24": {"label": "24 Points", "amount": 23.0, "points": 24},
    "30": {"label": "30 Points", "amount": 28.0, "points": 30},
    "36": {"label": "36 Points", "amount": 32.4, "points": 36},
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
