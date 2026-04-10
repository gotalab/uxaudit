# Category baselines — journey templates per app type

When the Scout cannot find e2e tests, scenario docs, or explicit journey definitions, it falls back on these category-aware templates. Each template lists the journeys that **users expect to complete** in apps of that category, based on the canonical examples (Spotify, YouTube, Stripe, Linear, etc.).

The Scout matches the project's purpose to a category using keywords from README/docs, then adapts the template to the project's specific domain language.

## How to use

1. Scout reads README, package.json description, and docs to identify the category.
2. Scout pulls the matching template from this file.
3. Scout adapts each template journey to the project's specific nouns (e.g., for a recipe app, "track" becomes "recipe", "playlist" becomes "cookbook").
4. Scout writes the adapted journeys into `project-context.json`.
5. Orchestrator dispatches a Judge per journey + an end-to-end Judge for any chain.

The category list below is extensible — when you encounter a new category, append it here.

---

## Music / audio streaming (Spotify, Apple Music, SoundCloud, Bandcamp)

**Core experiences** — what users come here to do.

```yaml
journey_chain:
  - id: discover
    name: Discover something new to listen to
    starting_url: /
    steps_hint:
      - Browse the home / explore page
      - Open at least one recommendation
      - Find a track that interests you
    success_criteria: A track detail page is open
    next_journey: play

  - id: play
    name: Play the discovered track
    starting_url: "@discover.success_state"
    previous_journey: discover
    steps_hint:
      - Click the play button
      - Verify audio starts (visual playback indicator)
      - See the track in the persistent player
    success_criteria: The persistent player shows the track name and a moving progress bar
    next_journey: save

  - id: save
    name: Save the track for later
    starting_url: "@play.success_state"
    previous_journey: play
    steps_hint:
      - Find the save / like / add-to-library control
      - Save the track
      - Navigate to the library
      - Verify the track is there
    success_criteria: The track appears in the user's library / saved list
    next_journey: organize

  - id: organize
    name: Add the saved track to a custom collection (playlist)
    starting_url: "@save.success_state"
    previous_journey: save
    steps_hint:
      - Create a new playlist OR pick an existing one
      - Add the track to it
      - Open the playlist and confirm the track is in it
    success_criteria: A playlist exists containing the track

standalone_journeys:
  - id: search-by-name
    name: Search for a known artist or track
    starting_url: /
    steps_hint:
      - Open the search input
      - Type a known artist name
      - Click the artist result
    success_criteria: The artist's page is visible with at least one track listed

  - id: queue-and-skip
    name: Queue multiple tracks and skip between them
    success_criteria: Three tracks queued, two skipped, current player shows the third

  - id: download-offline
    name: Download a track for offline listening
    success_criteria: The track shows a "downloaded" indicator

  - id: cold-start-onboarding
    name: New-user onboarding to first listen
    context: cold-start
    starting_url: /
    success_criteria: A first track plays without requiring account creation OR onboarding feels brief and skippable
```

**Friction red flags specific to this category:**
- Audio doesn't start within 1 second of pressing play
- "Add to playlist" requires more than 3 clicks
- Search results don't surface exact-match artists in top 3
- The persistent player disappears or resets when navigating
- Recommendations feel stale or irrelevant after 2 sessions

---

## Video streaming (YouTube, Netflix, Vimeo, Twitch)

```yaml
journey_chain:
  - id: discover
    name: Find a video worth watching
    success_criteria: A video detail / player page is open
    next_journey: watch

  - id: watch
    name: Start playback and watch a meaningful portion
    success_criteria: Player shows playback past 10 seconds
    next_journey: act-after

  - id: act-after
    name: Take an action after watching (like, save, share, subscribe)
    success_criteria: The user has performed at least one of like / save / share / subscribe

standalone_journeys:
  - id: search-by-topic
    name: Search for a topic and find relevant videos
  - id: continue-watching
    name: Resume a partially-watched video at the right timestamp
    context: returning
  - id: discover-next
    name: After a video ends, find the next thing to watch
  - id: fullscreen-and-controls
    name: Enter fullscreen, adjust quality, use captions
```

**Friction red flags:**
- Player controls hide while user is reaching for them
- Buffering with no indication of progress
- "Up next" panel pushes content the user just watched
- Subscribe button is harder to find than the like button
- Search returns clickbait over relevance

---

## E-commerce / marketplace (Amazon, Etsy, Shopify storefronts)

```yaml
journey_chain:
  - id: browse
    name: Browse a category of products
    success_criteria: A product listing page is open

  - id: filter
    name: Narrow the listing by price / size / rating
    success_criteria: Listing shows filtered results matching the criteria
    next_journey: detail

  - id: detail
    name: Open a product and read the details
    success_criteria: Product page shows price, images, description, reviews
    next_journey: cart

  - id: cart
    name: Add to cart and view the cart
    success_criteria: Cart shows the product with correct quantity and price
    next_journey: checkout

  - id: checkout
    name: Complete purchase as a guest
    success_criteria: Order confirmation page with order number
    context: cold-start

standalone_journeys:
  - id: search-direct
    name: Search for a known product by name
  - id: read-reviews
    name: Read product reviews and answers
  - id: track-order
    name: Track a previous order
    context: returning
  - id: return-item
    name: Initiate a return for a delivered item
```

**Friction red flags:**
- Required account creation before checkout
- Hidden shipping cost until step 4
- No price-per-unit on bulk items
- Reviews require pagination instead of inline scrolling
- Cart loses items on session timeout

---

## Productivity / SaaS (Linear, Notion, Asana, Trello)

```yaml
journey_chain:
  - id: onboard
    name: Set up the workspace as a first-time user
    context: cold-start
    success_criteria: A workspace exists and the user is on the main view
    next_journey: create

  - id: create
    name: Create the primary entity (task / doc / project)
    success_criteria: The entity exists in the main list
    next_journey: edit

  - id: edit
    name: Edit and save the entity
    success_criteria: Edits persist after navigation
    next_journey: organize

  - id: organize
    name: Move, label, or group the entity
    success_criteria: Organization is visible in the list view

  - id: collaborate
    name: Invite a teammate and share access
    success_criteria: Team member appears in the workspace member list

standalone_journeys:
  - id: search-existing
    name: Find an existing entity by name
    context: returning
  - id: keyboard-power-user
    name: Use keyboard shortcuts to create + navigate
    context: power-user
  - id: bulk-action
    name: Select multiple items and perform a bulk action
  - id: integrate
    name: Connect an external service (Slack, GitHub, Calendar)
  - id: export
    name: Export data to CSV / PDF
```

**Friction red flags:**
- "Are you sure?" on every delete (excise)
- Required setup steps before any value
- Bulk select is keyboard-only or hidden
- Search doesn't index newly created items quickly
- Export is paywalled or rate-limited

---

## Communication / messaging (Slack, Discord, Telegram, WhatsApp Web)

```yaml
journey_chain:
  - id: read
    name: Read messages in a channel / thread
    success_criteria: Messages are visible and scrollable

  - id: respond
    name: Send a reply
    success_criteria: Sent message appears in the thread with timestamp
    next_journey: react

  - id: react
    name: React or reply with emoji to a message
    success_criteria: Reaction is visible on the message

standalone_journeys:
  - id: search-history
    name: Find a past message by content
  - id: switch-context
    name: Switch between channels / DMs / workspaces
  - id: notification-settings
    name: Mute a channel
  - id: file-share
    name: Send a file or image
  - id: voice-call
    name: Start a voice/video call (if applicable)
```

**Friction red flags:**
- Unread state doesn't survive page reload
- @-mentions are buried (no notification badge)
- Message edit history is hidden
- Cannot scroll to past messages without losing scroll position
- Notification permission is requested before any value

---

## Booking / scheduling (Calendly, OpenTable, Airbnb)

```yaml
journey_chain:
  - id: search
    name: Search by date / location / criteria
    success_criteria: A list of available slots / properties is visible
    next_journey: select

  - id: select
    name: Pick one option and view its details
    success_criteria: Detail page shows the price, availability, and reviews
    next_journey: book

  - id: book
    name: Confirm the booking
    success_criteria: Confirmation page with booking ID and details
    context: cold-start

standalone_journeys:
  - id: change-booking
    name: Modify or cancel an existing booking
    context: returning
  - id: contact-host
    name: Message the host / restaurant / provider
  - id: filter-narrow
    name: Apply 3+ filters and find an exact match
```

**Friction red flags:**
- Date picker doesn't work on mobile
- "Continue" without showing total price
- Hidden fees revealed at the last step
- Confirmation email arrives without a calendar invite
- Cancellation policy hidden until after booking

---

## Content publishing (Substack, Medium, Ghost, personal blogs)

```yaml
journey_chain:
  - id: discover
    name: Find an article to read
    success_criteria: An article page is open
    next_journey: read

  - id: read
    name: Read the full article without friction
    success_criteria: Reached the end of the article
    next_journey: subscribe

  - id: subscribe
    name: Subscribe / follow / save
    success_criteria: Confirmation that the user is subscribed

standalone_journeys:
  - id: archive-browse
    name: Browse the archive by tag or date
  - id: comment
    name: Leave a comment on an article
  - id: share-article
    name: Share an article externally
  - id: author-page
    name: Visit the author's profile
```

**Friction red flags:**
- Newsletter modal pops up before reading
- Cookie banner blocks the article body
- Paywall at sentence 1
- Comments are paginated 5 per page
- Share buttons hijack the URL with tracking junk

---

## Banking / fintech (Wise, Revolut, Chime, neobank)

```yaml
journey_chain:
  - id: balance
    name: View account balance
    success_criteria: Current balance is visible immediately on home
    context: returning

  - id: transactions
    name: View recent transactions
    success_criteria: Last N transactions visible with merchant name + amount
    next_journey: detail

  - id: detail
    name: Open a transaction for details
    success_criteria: Detail page shows merchant, date, amount, category
    next_journey: dispute

  - id: dispute
    name: Initiate a dispute on a charge
    success_criteria: Dispute case is opened with a reference ID

standalone_journeys:
  - id: send-money
    name: Send money to a contact
  - id: deposit-cheque
    name: Deposit a cheque (mobile only)
  - id: change-card-pin
    name: Change card PIN
  - id: lost-card
    name: Report a lost card
```

**Friction red flags:**
- Balance is hidden until biometric auth (excise — already authenticated)
- Transaction descriptions are gibberish ("MCD#3145 NORTH AVE")
- "Send money" requires 5 steps
- Lost-card flow buried 4 levels deep in settings
- Disputes require phone call

---

## Adding a new category

Append the category here using the same shape:

```yaml
category: <name>
canonical_examples: [<known good examples>]
journey_chain: [...]
standalone_journeys: [...]
friction_red_flags: [...]
```

Then update the Scout agent definition at `${CLAUDE_PLUGIN_ROOT}/agents/uxaudit-scout.md` to mention the new category in the matching keywords.

---

## What if my app spans multiple categories?

Many apps do (e.g., Notion is productivity + content publishing + collaboration). The Scout picks the **dominant** category from README keywords and uses its template, then merges 1–2 standalone journeys from secondary categories.

You can override by manually editing `project-context.json` after the Scout writes it.
