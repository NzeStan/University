"""University Marketplace — listings, sellers, inventory, orders with escrow, disputes and reviews.

An optional *level two* module that depends only on University Core::

    pip install university-marketplace

    INSTALLED_APPS = [..., *CORE_APPS, "university.marketplace"]

Orders are sold as Core payables (``marketplace.order``), so any payments
module — such as university-payments — can take the money and hold it in
escrow until the buyer confirms delivery. Cash on pickup works without one.
"""

__version__ = "0.1.0"
