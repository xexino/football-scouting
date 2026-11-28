# Billing provider options — proposal for the founder (decision required)

**Status:** no paid billing provider is integrated. The platform runs on the `manual`
provider (invoices / bank transfer; payment recorded by a platform operator). The
`BillingProvider` interface (`backend/app/billing/base.py`) lets one provider be added later
without touching subscription logic.

> ⚠️ **Fees and availability below are indicative list prices recalled from public pricing
> pages, not verified for this document.** Providers change terms often and eligibility
> depends on where *your company* is incorporated. Confirm each figure on the provider's
> current pricing page and with a Moroccan accountant/lawyer before deciding.

## Context that drives the choice

* Customers are **clubs (B2B)**, contracts typically annual, often paid by **bank transfer
  against an invoice**; many North African clubs do not pay SaaS by card.
* Moroccan foreign-exchange rules (Office des Changes) and invoicing obligations apply to a
  Moroccan-incorporated seller; cross-border collection may need a foreign entity or a
  merchant of record.
* Recurring revenue at the start is a small number of high-value contracts — integration cost
  matters more than per-transaction fees.

## Options

| Option | What it is | Indicative cost* | Fit / caveats |
|---|---|---|---|
| **1. Manual invoicing + bank transfer (implemented)** | Invoice per season/year; operator sets status & paid-until date in the platform console | Bank transfer fees only; no integration cost | Best fit for the first clubs. Manual follow-up of late payments; grace period and read-only mode are already automated. |
| **2. CMI (Centre Monétique Interbancaire, Morocco)** | Moroccan card acquiring via a local bank | Commission negotiated with the acquiring bank (commonly low single-digit %), plus setup/monthly fees | Requires a Moroccan entity and bank contract; MAD card payments; recurring billing support is limited — mostly one-off payments. |
| **3. Stripe (Billing)** | Card payments + subscription engine + webhooks | Roughly 1.5 % + €0.25 (EEA cards) to ~3 %+ (international cards), plus ~0.5–0.7 % for Billing | Historically **not available to Morocco-incorporated businesses**; would require a company in a supported country (e.g. EU/UK/UAE/US). Best developer experience. |
| **4. Paddle / similar merchant of record** | Sells on your behalf, handles VAT/sales tax and invoicing | Roughly 5 % + $0.50 per transaction | Removes tax compliance burden internationally; check payout support for your entity's country. Expensive at high contract values. |
| **5. Flutterwave / Paystack (for wider Africa)** | Pan-African payment gateways (cards, mobile money, bank) | Roughly 1.4–4 % depending on country/method | Useful when expanding to Sub-Saharan Africa (Nigeria, Ghana, Kenya…); limited Maghreb coverage. |

\* Indicative only — see warning above.

## Recommendation

1. **Now:** stay on **manual invoicing** (already implemented): 30-day trials, annual
   invoices, operator records payment → `active` + paid-until date. Zero integration risk.
2. **When card payments are needed:** decide the **legal structure first** (Moroccan entity
   only vs. an additional foreign entity), because it determines which providers are even
   available. Then implement **one** provider behind `BillingProvider`:
   * Moroccan entity only → CMI for MAD card payments, manual for transfers.
   * Foreign entity available → Stripe Billing (or Paddle if you want a merchant of record).
3. **Wider Africa expansion:** add Flutterwave/Paystack as a second provider for local methods.

## What adding a provider requires (estimate)

* Implement `checkout_url`, `cancel`, `parse_webhook` (signature verification mandatory) and
  register it in `billing/base.py`; set `BILLING_PROVIDER`.
* Map provider events → `BillingEvent(status, plan, current_period_end)`; idempotent handling.
* Add the provider's host to the deployment's network/secret configuration (API key via the
  hosting provider's secret store — never in the repository).
* Tests with recorded webhook fixtures. Typical effort: 3–5 developer-days per provider.

## Plans (implemented limits; prices to be set by the founder)

| Plan | Seats | Private players | Features |
|---|---|---|---|
| Scout | 3 | 300 | pipeline, reports, video, comparison, CSV import, export |
| Club Pro | 15 | 5,000 | + JSON/API import |
| Enterprise | unlimited | unlimited | + priority support; custom terms |

Per-organization overrides (`seats_override`, `players_override`) support negotiated deals.
