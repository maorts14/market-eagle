SECTOR_ETFS = [
    ("XLB", "Materials Select Sector SPDR", "Materials"),
    ("XLC", "Communication Services Select Sector SPDR", "Communication Services"),
    ("XLE", "Energy Select Sector SPDR", "Energy"),
    ("XLF", "Financial Select Sector SPDR", "Financials"),
    ("XLI", "Industrial Select Sector SPDR", "Industrials"),
    ("XLK", "Technology Select Sector SPDR", "Information Technology"),
    ("XLP", "Consumer Staples Select Sector SPDR", "Consumer Staples"),
    ("XLRE", "Real Estate Select Sector SPDR", "Real Estate"),
    ("XLU", "Utilities Select Sector SPDR", "Utilities"),
    ("XLV", "Health Care Select Sector SPDR", "Health Care"),
    ("XLY", "Consumer Discretionary Select Sector SPDR", "Consumer Discretionary"),
]

# Curated and auditable classification is used instead of opaque model labels.
# A licensed security-master feed can replace this catalog in a production deployment.
STOCK_UNIVERSE = [
    ("LIN", "Linde plc", "Materials"), ("META", "Meta Platforms", "Communication Services"),
    ("XOM", "Exxon Mobil", "Energy"), ("JPM", "JPMorgan Chase", "Financials"),
    ("CAT", "Caterpillar", "Industrials"), ("NVDA", "NVIDIA", "Information Technology"),
    ("WMT", "Walmart", "Consumer Staples"), ("PLD", "Prologis", "Real Estate"),
    ("NEE", "NextEra Energy", "Utilities"), ("LLY", "Eli Lilly", "Health Care"),
    ("AMZN", "Amazon", "Consumer Discretionary"),
]

TRACKED_INSTRUMENTS = SECTOR_ETFS + STOCK_UNIVERSE
UNIVERSE = SECTOR_ETFS
