"""Old-style unittest checks kept from the Python 2 codebase."""
import unittest

from legacy_app.inventory import Item


class ItemChecks(unittest.TestCase):
    def test_label(self):
        self.assertEquals(Item("A1", "bolt", 3).label(), "bolt (A1) x3")

    def test_qty(self):
        self.assert_(Item("A1", "bolt", 3).qty > 0)
