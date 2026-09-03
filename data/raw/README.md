# Put your CSVs here

Expected filenames (case-insensitive is fine — the ingester will match):

- `customers.csv`
- `orders.csv`
- `order_items.csv`
- `shipments.csv`
- `refund_cases.csv`
- `approval_requests.csv`

After adding files, run:

```bash
make ingest
```

This produces `data/aura.db` (SQLite) which the agent tools read from.
