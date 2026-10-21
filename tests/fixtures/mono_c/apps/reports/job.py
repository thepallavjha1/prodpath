# Nightly report job; writes to local disk (local-state hint for the extractor).
import datetime

with open("/tmp/report.csv", "w") as handle:
    handle.write(f"generated,{datetime.date.today()}\n")
