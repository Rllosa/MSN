# SCOPE.md — MSN Unified Messaging Dashboard

## In Scope

### P0 — Core
- Unified inbox: all messages from Airbnb, Booking.com, and WhatsApp in a single threaded view
- Platform tagging per message (source badge)
- Reply from dashboard: Airbnb (SMTP), WhatsApp (Meta Cloud API), Booking.com (manual redirect)
- Real-time updates via WebSocket push
- JWT authentication with admin-managed user accounts (no self-registration)
- Properties table (7 properties), single and multi-property filter view

### P1 — Productivity
- Message templates (name, content, platform scope)
- Optional trigger keywords per template (keyword field stored; used by auto-reply engine in P2)
- Browser notifications for new messages (via WebSocket)

### P2 — Nice to Have
- Auto-reply dispatch — keyword match → template send, globally disableable, per-template opt-in
- Guest profiles (aggregated info: name, booking dates, property, platform)
- Full-text search across messages and conversations
- Analytics (response time tracking, message volume per platform)

## Out of Scope (Non-Goals)

- Booking.com automated reply — requires Connectivity Partner certification (v2 candidate)
- Browser automation via Playwright for Booking.com (v2 candidate)
- Airbnb or Booking.com official API access (not available without platform partner status)
- Mobile app (web only)
- Multi-tenant SaaS (single self-hosted instance only)
- SMS integration
- Email-based notifications (browser + optional webhook only)

## Accepted Constraints

- Airbnb messages read via IMAP email parsing only — no official API available
- Booking.com messages read via IMAP email parsing only; replies are manual via Extranet (v1)
- WhatsApp integration via Meta Cloud API (dedicated business number, not personal)
- Single OVH VPS deployment — no horizontal scaling requirement
- Single shared inbox `info@blackpalm-sxm.com` receives both Airbnb and Booking.com notifications

## Architecture Decisions

| Decision | Choice | Reason |
|---|---|---|
| Email ingestion | IMAP polling (30–60s interval, configurable) | No official Airbnb/Booking.com message API available |
| Airbnb replies | SMTP to `Reply-To` header address | Airbnb embeds `reply+TOKEN@airbnb.com` in every notification email |
| Booking.com replies | Manual redirect to Extranet URL (v1) | No email reply threading; API requires Connectivity Partner status |
| WhatsApp | Meta Cloud API | Dedicated business number available; official channel; no ban risk |
| Auth | JWT + httpOnly refresh cookie | Stateless, simple, no third-party identity provider needed |
| Real-time | WebSocket + Redis pub/sub | Single connection per client; works across background workers |
| Deployment | Docker Compose, OVH VPS | Self-hosted, single-node, cost-effective |
| Auto-reply control | Global toggle + per-template opt-in | Safety first — must be explicitly enabled, can be killed instantly |
