# university-marketplace

A campus marketplace for the [University platform](https://github.com/NzeStan/University):
listings, sellers, inventory, orders with escrow, disputes and reviews. This is an optional
*level two* module that depends only on `university-core`.

- **Listings** have categories (with subcategories), conditions, stock, images (content-checked)
  and pickup or delivery options. They can be limited to a campus or community audience.
- **Stock can't oversell or go negative.** It's reserved when an order is placed and returned
  when the order is cancelled or expires unpaid.
- **Buyer protection.**
  - Online orders are paid through any payments module (via Core's payable contract) and held in
    escrow.
  - The money is released when the buyer confirms delivery, or automatically after a dispute
    window.
  - Mediators resolve disputes: a full or partial refund, or release to the seller.
- **Cash on pickup** for everyday campus trades (clearly without protection).
- **Reviews** are tied to completed orders, with seller replies and moderated ratings.
- **Trust and safety:**
  - Listings and reviews are moderatable with an explicit policy; removed scam listings refund
    their buyers.
  - Blocks, spam screening and content-creation restrictions all apply.
  - Delivery addresses are visible only to the two parties and erased after the order closes.

```bash
pip install university-marketplace university-payments
```

```python
INSTALLED_APPS += ["university.marketplace", "university.payments"]
```

See [the module documentation](../../docs/modules/marketplace.md).
