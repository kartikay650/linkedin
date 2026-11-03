# Backlog — deferred until they've had more thought

Raised in Maria's feedback (3 Nov 2026) and the five-reviewer audit that followed. Parked on
purpose: each needs a decision or more design before it can be built without recreating an old
failure. The items being built now (Phases 0, 1, 3 and 4) are in the git history, not here.

## Blocked on an answer

- **Learn from published comments (Maria #3).** The plan was to rotate up to five human-edited,
  posted comments into the prompt as examples. Blocked: many "human" edits look pasted from
  ChatGPT. Posted edits ending in a trailing space or newline, which generated text never has:
  Noah 98/187, Silvana 94/161, Nikolina 168/454. Ask Maria whether she rewrites in ChatGPT.
  If she does, exclude paste-marked edits and whole replacements (compare against
  `original_text`) before any of them become examples. Add a `, Name.` sign-off detector first:
  56 of Silvana's 161 posted edits end that way.
  Phase 1 already shows the drafter up to five human-edited comments per client, but skips
  paste-marked ones and anything with a `, Name.` sign-off. Two things wait on the same answer:
  whether paste-marked edits can be used, and whether comments written with "Write my own"
  (`drafts.source = 'manual'`) should be used. Today they are excluded from both the examples
  and the repetition stats.
- **Narrow the stacked-statement gate.** It fires on 12% of posted human edits and on 2 of Lara
  Hemeryck's own GOOD benchmark lines. It encodes Lara's diagnosis, so narrowing it is her call.
- **Alejandro Bataller and Alex Brogan.** Both were moved to `kind='prospect'`, which stops
  fetching them for every client. Bataller posts weekly and was assigned to 7 clients. Decide
  whether either should be fetched again. (Alex Zhavoronkov was re-enabled: he is one of the
  seven priority accounts Lara asked us to give Dr. Joe Raffaele.)

## Needs design

- **Spoken material over polished documents (Maria #4).** `client_documents.kind`
  (spoken / own_comments / client_feedback / strategy / reference), `spoken_samples` and
  `own_comments` fields on `clients`, onboarding that keeps the document category it already
  asks for, extraction budgets per kind, and provenance grounding for the new material. Unused
  today: Lara's Loom transcripts (doc 19, 21k chars), Noah's and Nikolina's podcast transcripts
  (67k and 86k). The keyword check that flags samples as speech misses Nikolina's.
- **Relationship groups (Maria #5).** Per client-pair on `creator_clients.relationship`
  (space / peer / client / potential_client, default space). A note in the uncached prompt
  block, a `has_claimed_history` gate ("great to see you last week" must never be invented), a
  filter chip rather than feed exemptions. First ask Maria what "current client" means for each
  client: their customers, fellow agency clients, never patients.
- **Topic overlap (Maria #6).** Ranking only, from posts already scraped: a `client_own_posts`
  table keyed on LinkedIn member ID, a per-client batch matcher, a feed chip, and an
  off-by-default "mention her recent post" Tweak with the timing computed from the real post
  date. Lara's, Silvana's and Joanna's own posts are never fetched today. No keyword discovery of
  untracked accounts yet (~$35/month, 10-26 MB/month). "Upcoming content" has no data source in
  `public`; a calendar in the portal schema would need Kartikay's explicit OK.
- **Thin queues.** Nikolina, Noah and Silvana each have about 4 fresh posts. That's a short
  tracked-creator list, not a ranking problem.
- **Fact-check badge conflates opinion with fact.** 23% of "grounded" spans are grounded in a
  client's stated belief, and the card shows them as "Nothing to verify". Split the badge (from
  the post vs from their stated view), and consider a `contested` provenance level.
- **Per-author cap.** A post reaches at most 2 client feeds, but a prolific author still sees
  most of the roster across different posts.

## Housekeeping

- **Database growth.** `posts` stores each scraped post about 4.2x (6.5x for Oct-Nov), with full
  text, and nothing prunes it: ~21 MB/month against a 500 MB limit shared with the portal. A
  retention job must exempt the ~3,430 posts that have drafts.
- Dead paths: the "Synthesize from documents" save writes `tone_profile`, which `voice_guide`
  always overrides. `personal_story` reaches no prompt.
- Gordan Lauc has two creator rows (13 and 336, the second on `hr.linkedin.com`) because
  `add_creator` doesn't normalise the host. `watch_creators` id 45 is labelled
  "Dr Lara Hemeryck" but points at Marwan's URL.
