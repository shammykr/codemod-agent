"""Smoke entry point for the legacy app: exercises the main code paths."""
from legacy_app.inventory import Item, PerishableItem, backup_name, has_data, stamp

items = [Item("A1", "bolt", 3), PerishableItem("B2", "glue", 1, "2027-01-01")]
for item in items:
    print(item.label())
print(backup_name("data", "stock.csv"))
print(has_data("."))
print(stamp())
