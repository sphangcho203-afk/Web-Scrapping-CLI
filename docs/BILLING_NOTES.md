# Billing safety notes

The production Razorpay credentials may be live-mode credentials. Internet Hands therefore follows these rules:

1. Never create a live payment merely to verify configuration.
2. Never grant credits or a subscription for `created` or `authorized` payments.
3. Fulfillment requires a Razorpay payment whose status is `captured`.
4. The payment must belong to the locally-created Razorpay order.
5. Amount and currency must match the server-priced local order.
6. Checkout signatures use `RAZORPAY_KEY_SECRET`.
7. Webhook signatures use `RAZORPAY_WEBHOOK_SECRET`.
8. Webhook events are persisted idempotently before fulfillment.
9. Secrets never appear in API responses, documentation examples, Git history, or MCP tool output.
10. A real charge may only be initiated when an operator intentionally chooses a paid checkout.
