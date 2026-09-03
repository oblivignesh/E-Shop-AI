# Refund Policy — v3.2 (effective 2025-01-01)

All monetary amounts are in **Indian Rupees (INR, ₹)**.

## 1. Eligibility windows
- **Standard goods** (Apparel, Home, Kitchen, Accessories, Office, Stationery, Footwear, Fitness): refund requests must be submitted within **30 calendar days** of the shipment's `actual_delivery_date`.
- **Electronics**: **15 calendar days** from delivery.
- **Beauty** (opened): **non-refundable**. Beauty (unopened) follows the 30-day window.
- **Refund reasons that always qualify regardless of category** (subject to evidence): `Defective product`, `Item damaged on arrival`, `Wrong item shipped`, `Item not as described`, `Missing parts`.

## 2. Refund amount calculation
- Full item price is refunded when the item is defective, damaged in transit, wrong item shipped, or materially different from the listing.
- For change-of-mind reasons (`Changed my mind`, `Better price found elsewhere`, `Size/fit issue`), refund equals `item_subtotal - restocking_fee` where the restocking fee is 10% of item subtotal (capped at ₹500 per item).
- Original shipping cost is refunded **only** when the return reason is a seller error (wrong item, damaged in transit, defective, missing parts).
- Return shipping is paid by the customer for change-of-mind reasons; by AURA for seller error.

## 3. Auto-approval thresholds
- Refund requests **strictly less than ₹5,000** for eligible orders may be auto-approved by the agent without human review.
- Requests **greater than or equal to ₹5,000** MUST be escalated to a human via an `approval_request` (`request_type = "Refund Approval"`) and MUST NOT be marked `Completed` until an approver resolves the request as `Approved`.
- A single customer with **three or more refund_cases in the trailing 90 days** is escalated regardless of amount (see Fraud Rules).

## 4. Required evidence
- For `Item damaged on arrival` or `Defective product` claims above ₹2,000, the agent should ask for a photo before recommending approval. In the current MVP, absence of a photo alone does not block approval but must be surfaced in the reasoning.

## 5. Disallowed actions
- The agent MUST NOT recommend a refund for an order whose `order_status` is `Cancelled` or `Returned` (already handled).
- The agent MUST NOT recommend a refund when a `refund_case` for the same `order_id` already exists with status in {`Requested`, `Under Review`, `Approved`, `Completed`}.
- The agent MUST NOT modify order totals, apply store credit, or promise expedited replacements without approval.

## 6. Communication
- Every refund decision must be communicated to the customer with: refund amount (INR), method (original payment), expected timeline (5–10 business days), and the `refund_id` case reference.
