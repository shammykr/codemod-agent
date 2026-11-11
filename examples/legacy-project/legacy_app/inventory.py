# -*- coding: utf-8 -*-
"""Warehouse inventory helpers, originally written for Python 2.7."""
from __future__ import print_function, unicode_literals

import os
from datetime import datetime


class Item(object):
    def __init__(self, sku, name, qty):
        self.sku = sku
        self.name = name
        self.qty = qty

    def label(self):
        return "%s (%s) x%d" % (self.name, self.sku, self.qty)


class PerishableItem(Item):
    def __init__(self, sku, name, qty, expires):
        super(PerishableItem, self).__init__(sku, name, qty)
        self.expires = expires


def data_file(base_dir, name):
    return os.path.join(base_dir, name)


def backup_name(base_dir, name):
    # Relies on data_file() returning a str.
    return data_file(base_dir, name) + ".bak"


def has_data(base_dir):
    return os.path.exists(base_dir)


def stamp():
    return "generated at %s" % datetime.utcnow().strftime("%Y-%m-%d")


def legacy_lookup(table, key):
    if table.has_key(key):
        return table[key]
    return None


def legacy_batches(n):
    return [i for i in xrange(n)]
