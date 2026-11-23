# Client knowledge: comments that bring in the client's own experiences

Status: design, 24 Nov 2026. Waiting for Kartikay's answers to the two questions at the end.

## Why

Maria, 23 Nov 2026 (#aitools-linkedin-account-managers, Baba's 10 Nov thread):

- Lara's and Joanna's comments improved most, because the tool has detailed examples and personal
  details for them (Joanna's morning walks with her dogs).
- Nikolina's comments "rarely reflect her own experiences, either professionally or personally";
  they just react to the post.
- Example: if a client has written a book and someone announces their first publication, the
  comment should draw on the client's own publishing experience, not give a generic
  congratulations. "Only when that experience is real and documented."
- Use what the agency already has, so clients aren't asked for more:
  - the clients' answers to the weekly questions;
  - their previous posts;
  - their approved content.

This also covers her earlier item 4 (spoken material should count more than polished documents).

Production check, 23 Nov 2026: Nikolina's "personal story" field is empty (0 characters). Lara has
4,500 characters of example comments, 5 feedback notes and the longest profile.

## Goals

- Keep, per client, a list of real experiences, facts and opinions. Each one is taken from what
  the client said or approved, with its source.
- When a post touches one of them, the drafter may use it, naturally and briefly.
- Keep the list fresh as new answers and posts come in, with nobody retyping anything.

## Non-goals

- The client portal. Some weekly answers are given in the portal and never reach the Question Doc.
  CLAUDE.md forbids reading schema `portal`, so those answers are missed unless Kartikay decides
  otherwise.
- Writing to any Google Doc.
- Topic matching and post discovery (item 6, parked).

## Anti-goals

- Any fact the client didn't state or approve. That means no inference ("she has a dog" from a
  photo caption) and no embellishment.
- Personal details in every comment. The drafter applies its newest rule to every post (memory:
  prompt fixes need boundaries), so use has to be rare and bounded by design.
- Private details the client shared for content planning but wouldn't post. Health, family
  conflict and money are excluded unless they already appear in a Live post.

## Sources (read-only, via the existing service account)

1. **Question Docs.** Example name: "2. [Nikolina Lauc] Question Doc".
   - The "OLD … Question Doc" copies are read too, because they hold earlier answers.
   - Questions and answers come either as "Round N" sections or as one tab per week, with answers
     on "→" lines. The tracker's parser (`Aaron-automations/src/lib/sources/question-doc.ts`)
     shows the layouts.
   - Checked 24 Nov: the service account can read all of them. One is misspelled "[Nicolina Lauc]",
     so matching has to tolerate that or use a manual override.
2. **Posting docs.** Only posts with status Live or Approved: the client has published or signed off
   on them. Personal stories count here.
   - Same doc lookup as the parked item 6 design, sections 1–2: two newest quarter docs, HTML export.
3. **Existing client-page fields.** Personal story, viewpoints and voice samples stay as they are.
   Account managers can still type facts there.

## Extraction

For each new or changed answer or post, one call to gpt-5-mini. It returns 0–5 "experience cards":

- `kind`: personal / professional / opinion
- `fact`: one plain sentence in third person, e.g. "Walks her two dogs every morning before work"
- `source`: document name and round, week or post title
- `quote`: the client's own words it came from (at most 300 characters)
- Rules for the model: stated by the client, not inferred; skip the sensitive categories above
  unless the source is a Live post; when unsure, skip.

Cards are stored in a small `public` table:
- client
- kind
- fact
- quote
- source label
- source doc id
- content hash
- active
- created

Expected size is tens of KB per client, far below the shared 500 MB limit.

A doc is re-read only when its Drive `modifiedTime` changes, and an answer or post is re-extracted
only when its text changes. The first full backfill runs as a local script, not on Vercel, because
of the 60-second limit.

## Use in drafting

- When drafting, the tool picks at most 3 cards related to the post: word overlap first, then the
  planning step decides.
- They are given as "experiences {name} has actually had; use one ONLY if this post is about the
  same thing, and most comments use none".
- **Bounds:**
  - at most one card per comment;
  - never on a condolence post;
  - if more than 1 in 4 of the client's recent comments already used a card, the block is left out
    for that draft.
- The fact-check pass treats cards as the client's own material, so a card's content isn't
  stripped as untraceable.

## On the client page

A "What the tool knows about her" list: each card with its source and a delete button, plus a
"Refresh from docs" button.

## Open questions for Kartikay

1. **Should a new card be used straight away (account managers can delete it on the client page),
   or only after an account manager ticks it?** My recommendation: straight away with delete. The
   sources are the client's own answers and approved posts, and a review queue nobody empties
   would leave the feature off.
2. **When should docs be re-read?** Sync is manual since 19 Jul. My recommendation: on every
   "Sync now", plus the "Refresh from docs" button. Unchanged docs cost one Drive listing and no
   model calls.

## Left to the builder

- Table names
- The parser details for each Question Doc layout
- Prompt wording within the rules above
- How cards are scored for relevance
- Page layout
