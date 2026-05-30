// Sample Stripe Checkout document content — realistic engineering content
// matching the V2Document shape (main_body: paragraphs of segments,
// details_markdown_sections: anchored markdown).

window.SAMPLE_DOC = {
  title: "Stripe checkout wiring",
  description: "How Taskforce wires Stripe Checkout for new subscribers, including tax, B2B, and EU-no-VAT fallback.",
  author: { name: "Alex Mendes", handle: "@alex" },
  org: "Ender",
  updated_at: "2026-05-19T14:14:00Z",
  reuse: { count: 14, tokens_saved: 142000, last_reuse_ago: "2h" },
  visibility: "Organization",
  shared_with: [
    { initials: "A", color: "#8447ff" },
    { initials: "J", color: "#1f8a5b" },
    { initials: "M", color: "#c97b2e" },
    { initials: "N", color: "#2a6fdb" },
  ],

  // Summary: paragraphs of segments. Segments with anchor_id are citations
  // that point to a section in details_markdown_sections.
  main_body: [
    {
      kind: "h1",
      segments: [{ text: "Stripe checkout wiring" }],
    },
    {
      kind: "p",
      segments: [
        { text: "On signup we attach " },
        { text: "automatic_tax: { enabled: true }", code: true },
        { text: " to every subscription, then check " },
        { text: "tax_id_collection", code: true },
        { text: " for B2B customers — see ", anchor_id: "sec-tax-flow", anchor_short: "§1" },
        { text: ".", anchor_id: "sec-tax-flow" },
      ],
    },
    {
      kind: "p",
      segments: [
        { text: "For the first 90 days we recommend " },
        { text: "stricter price-ID validation", bold: true, anchor_id: "sec-price-ids", anchor_short: "§2" },
        { text: " — the validator must reject any price not present in our env-scoped allowlist. This blocked a near-miss in March where a draft price was almost shipped to prod." },
      ],
    },
    {
      kind: "p",
      segments: [
        { text: "Edge case: " },
        { text: "EU customers with no VAT", bold: true },
        { text: " get blocked at confirm. The fallback is documented in ", anchor_id: "sec-eu-no-vat", anchor_short: "§3" },
        { text: " and we route them to a non-tax-collected B2C plan automatically.", anchor_id: "sec-eu-no-vat" },
      ],
    },
    {
      kind: "p",
      segments: [
        { text: "Webhooks: we listen to " },
        { text: "checkout.session.completed", code: true },
        { text: " and " },
        { text: "customer.subscription.updated", code: true },
        { text: ". Idempotency keys are derived from " },
        { text: "session_id + event.id", code: true },
        { text: " so retries are safe. ", },
        { text: "See webhook table", anchor_id: "sec-webhooks", anchor_short: "§4", italic: true },
        { text: "." },
      ],
    },
    {
      kind: "h2",
      segments: [{ text: "What we deliberately did NOT do" }],
    },
    {
      kind: "p",
      segments: [
        { text: "We did not build a custom tax engine. We trust Stripe's tax service for the EU/UK/CA jurisdictions we ship to. The full rationale and the 2-page review with @ana is in " },
        { text: "the tax decision", anchor_id: "sec-tax-decision", anchor_short: "§5", italic: true },
        { text: "." },
      ],
    },
  ],

  details_markdown_sections: [
    {
      anchor_id: "sec-tax-flow",
      title: "§1 · Tax flow on signup",
      markdown: [
        "## Tax flow on signup",
        "",
        "When a checkout session is created we always pass `automatic_tax: { enabled: true }`. Stripe computes tax based on the customer's billing address.",
        "",
        "For accounts marked `account_type === 'business'`, we additionally pass `tax_id_collection: { enabled: true }` so the customer can input a VAT ID at checkout.",
        "",
        "```ts",
        "const session = await stripe.checkout.sessions.create({",
        "  mode: 'subscription',",
        "  automatic_tax: { enabled: true },",
        "  tax_id_collection: { enabled: account.type === 'business' },",
        "  line_items: [{ price: priceId, quantity: 1 }],",
        "})",
        "```",
        "",
        "Result: B2C customers see prices with tax inline; B2B customers see net price + a VAT ID input that, if valid, removes tax at confirm.",
      ].join("\n"),
    },
    {
      anchor_id: "sec-price-ids",
      title: "§2 · Price-ID validation",
      markdown: [
        "## Price-ID validation",
        "",
        "Every `priceId` accepted by our checkout endpoint must:",
        "",
        "1. Match the regex `/^price_[A-Za-z0-9]+$/`",
        "2. Exist in the environment-scoped allowlist (`config/stripe/prices.{env}.json`)",
        "3. Be `active === true` according to Stripe's API at request time",
        "",
        "The allowlist is checked in *before* hitting Stripe to keep noisy errors out of our logs and to prevent draft prices from being used in production by accident.",
        "",
        "**Near-miss, Mar 2026:** a draft annual price was almost shipped after a copy-paste from the staging dashboard. The allowlist check caught it.",
      ].join("\n"),
    },
    {
      anchor_id: "sec-eu-no-vat",
      title: "§3 · EU customer, no VAT",
      markdown: [
        "## EU customer, no VAT",
        "",
        "When a customer in an EU country selects the business plan but does not provide a valid VAT ID, Stripe blocks the confirm with a tax-validation error.",
        "",
        "Our fallback:",
        "",
        "- Catch `tax_id_invalid` from Stripe's confirm response",
        "- Switch the customer to the B2C plan price (which has gross-of-tax pricing)",
        "- Surface a non-blocking notice: \"Switched to consumer plan — add a VAT ID later to switch back.\"",
        "",
        "This avoids an empty-cart moment and meets our 'no dead-end checkout' rule.",
      ].join("\n"),
    },
    {
      anchor_id: "sec-webhooks",
      title: "§4 · Webhook handlers",
      markdown: [
        "## Webhook handlers",
        "",
        "| Event | Handler | Idempotency key |",
        "|---|---|---|",
        "| `checkout.session.completed` | `onCheckoutComplete` | `${session.id}:${event.id}` |",
        "| `customer.subscription.updated` | `onSubscriptionUpdate` | `${subscription.id}:${event.id}` |",
        "| `customer.subscription.deleted` | `onSubscriptionDelete` | `${subscription.id}:${event.id}` |",
        "| `invoice.payment_failed` | `onPaymentFailed` | `${invoice.id}:${event.id}` |",
        "",
        "Retries are safe — handlers `INSERT ... ON CONFLICT DO NOTHING` on the idempotency key before any side effect.",
      ].join("\n"),
    },
    {
      anchor_id: "sec-tax-decision",
      title: "§5 · Tax engine decision",
      markdown: [
        "## Why we did not build a tax engine",
        "",
        "Reviewed with @ana on 2026-03-04. We considered three options:",
        "",
        "1. **Use Stripe Tax** (chosen) — covers EU/UK/CA, includes registration support, $0 extra for our volume",
        "2. **Use Avalara** — overkill, $30k/yr minimum",
        "3. **Build our own** — ~6 engineer-months, recurring maintenance burden",
        "",
        "The math is clear: Stripe Tax buys us months of engineering at zero extra cost.",
      ].join("\n"),
    },
  ],
}
