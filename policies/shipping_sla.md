# Shipping SLAs — v2.1

## 1. Delivery targets by shipping method
| Method    | Business-day target | Cutoff (order created before) |
|-----------|---------------------|-------------------------------|
| Standard  | 5–7                 | 6:00 PM local warehouse time  |
| Express   | 2–3                 | 4:00 PM local warehouse time  |
| Overnight | 1                   | 2:00 PM local warehouse time  |

## 2. Delay classification
An order is considered **delayed** when:
- `now() - shipment.shipped_at` exceeds `1.5x` the upper SLA for its method, OR
- Its `shipment.status` has been `IN_TRANSIT` for more than 10 calendar days.

## 3. Agent actions for delayed shipments
- Acknowledge the delay explicitly.
- Provide the latest tracking status and best-effort revised ETA (upper SLA + 3 business days if no carrier update).
- For Express/Overnight delays exceeding SLA, offer a shipping-cost refund (this is a refund and follows the Refund Policy auto-approval thresholds).
- Do NOT promise reshipment without human approval.

## 4. Lost shipments
A shipment is treated as **lost** when its status has been `IN_TRANSIT` for more than 21 calendar days without carrier updates. Lost shipments always require a human approval before any refund or reshipment.
