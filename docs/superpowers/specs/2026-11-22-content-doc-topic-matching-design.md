# Posts that match what the client is posting about (Maria's item 6)

Status: PARKED by Kartikay on 24 Nov 2026 ("requires a lot of effort and credits to build").
Nothing here is built. Kept for when it comes back. The content-doc reader (sections 1–2) is
reused by the client-knowledge work, so that part may be built first for that reason.
Date: 22 Nov 2026

## Why

Our clients are high-profile scientists and founders, so who they comment under reflects on them.
Today the queue only shows posts from the ~290 profiles the account managers chose to track, and
it scores them against a fixed list of topics on the client page.

Maria (item 6 of her feedback) asked for the queue to also surface conversations on what the
client is *currently* posting about. Then the account manager can join them naturally: "I was just
writing about this". Some of these conversations will be on accounts we don't track yet.

Kartikay's framing: use the content doc we already keep for each client. Learn from the posts
that went out (and the ones about to). Find posts on the same subjects, but only from accounts and
posts that are good enough. These accounts are high-profile, so we can't engage with every account
we see. Be very, very careful.

## Goals

- For each client, know the subjects of their recent and upcoming LinkedIn posts by reading their
  posting doc. No one has to type anything in.
- Put a small number of posts on those subjects into the client's normal queue. These can come
  from accounts the client doesn't track yet. Each one carries a clear label saying which of the
  client's posts it matches.
- Only accounts with **more followers than the client** qualify (Kartikay, 22 Nov).
- Spend as few Apify credits as possible (Kartikay, 22 Nov).

## Non-goals

- LinkedIn keyword search for new accounts. It costs credit on every search, so it stays off. It
  could be added later behind a weekly cap if the free sources prove too thin.
- Relationship groups (Maria's item 5): parked.
- Spoken-voice weighting (Maria's item 4): a separate design.
- Adding accounts to the tracked creator list automatically. Matched accounts never become tracked
  creators.
- Writing anything to the posting docs or to the sprint tracker's own store (Aaron-automations).
  We only read the docs.

## Anti-goals (would be a failure even if it technically works)

- Putting a client's comment under an account smaller than the client, or under a low-quality
  post: giveaways, engagement bait, sales pitches, generic motivation.
- Flooding the queue with generic founder or mindset posts because the client wrote a personal
  story. (This is why personal posts are skipped, see below.)
- Spending Apify credit per post, or per client per day, in a way that grows with the size of the
  pool.
- A stale doc: still reading last quarter's doc after the client has moved on.

## What Kartikay decided

1. **Source:** the client's posting doc (Google Doc, "[Name]_Q#_YYYY_Content_LinkedIn").
   - Posts with status **Live** (published) and **Approved** (about to go out) are learned.
   - Other statuses are ignored: For Client Review, Editorial Review, Needs Revision, and the
     template placeholder "Status".
2. **Only posts with a clear subject are learned:** science, the industry, or a professional point
   of view (e.g. how to communicate longevity science).
   - Personal stories (travel, family visit, hiring lessons) and agency news ("Scicomwiz just went
     global") are skipped.
   - Example from Lara's doc: "Your Biological Age Is 9 Years Younger" counts; "My mom came to
     visit" doesn't.
3. **Quality bar for an account:** more LinkedIn followers than the client.
   - Follower counts come from Apify.
   - The client's own count refreshes weekly.
4. **No approval step.** Matched posts go straight into the normal queue. They carry a badge, and
   a post from an account the client doesn't track gets a **different card colour**.
5. **Access:** use the existing Google service account from Aaron-automations
   (`sprint-tracker@scicomwiz-tracker.iam.gserviceaccount.com`).
   - Checked 22 Nov: it can already list and read every client's posting doc.
6. **Quarter changes are handled automatically:** when a client's doc changes at the end of a
   quarter, the tool moves to the new doc by itself.
7. **Least credits:** build the cheapest system that works.

## How it works

### 1. Finding each client's posting doc (and the quarter rollover)

The service account lists Google Docs whose name contains `Content_LinkedIn` (or
`LinkedInContentDoc`, Noah's naming).

**Matching a doc to a client.** It uses the same rule as the sprint tracker's
`src/lib/doc-resolver.ts`:
- The doc name must contain every word of the client's name that is longer than 2 letters.
- Ignore names matching `NOT IN USE|DO NOT USE|CLIENT-NAME|Copy of|template|[DO`.
- Ignore docs with no `Q<n>_<year>` in the name. The old "Shared_Content" docs fall out this way.

**Picking the quarter.** `Q<n>_<year>` gives the order, and higher is newer.
- The tool reads the client's **two newest** quarter docs and treats them as one source.
- This covers the rollover with no switching logic. The last few weeks of Live posts sit at the
  bottom of the old doc, and upcoming ones sit in the new doc.
- On 22 Nov this applies right away: Eric, Nikolina, Gordan and Joe each have a fresh Q4 doc dated
  20 Nov next to their Q3 doc.

**Manual override.** A client page field holds a doc id, for when a doc is named outside the
convention. Empty by default.

**What a failed read shows.** If the tool finds no doc for a client, or a read fails, it records
why. The client page shows "Content doc: not found" or "Content doc: can't read". The feature then
does nothing for that client. It never guesses.

### 2. Reading the doc

**Export format.** Export the doc through Drive as **HTML**.
- Status, Funnel and Phase are dropdown chips. The Docs API returns those chips empty; the export
  renders them as text. This was verified by the tracker team; see `src/lib/sources/gdoc.ts`.
- HTML also keeps the links to tagged LinkedIn profiles, which plain text loses.

**Doc layout** (seen in Lara's Q1 doc):
- `# Week of October 26 - W3 B2` headings.
- Under each heading, posts headed `LinkedIn Post #n`.
- Each post has the fields Status, Title, Funnel, Type, Goal, Audience, Message (sometimes) and
  Caption, plus internal To Do's.
- Empty template slots have Status "Status" and no Title. Skip them.

**Dates.**
- A post's date is its "Week of" heading.
- The year comes from the doc's "First Post Date" line, rolling over at January.
- There is no per-post date.

**Scope.**
- Keep Live and Approved posts whose week falls in the **last 6 weeks or later**.
  - *My call:* this keeps the subjects current, and Approved posts dated in the future are
    included, so the account manager can warm up the conversation before the client's post goes
    out.

**Changes.**
- Re-read each doc once a day.
- A post is re-processed only when its caption changes (hash of the caption).

### 3. Deciding which posts count, and what they're about

For each new or changed post, one call to the relevance model (gpt-5-mini on Azure, as used for
scoring today). It returns:
- `has_subject`: true for science, industry or a professional point of view; false for personal
  stories and agency or company news.
  - When unsure, false. Precision first.
- `subject`: a 3–8 word description, e.g. "biological age clocks vs. real aging".
- `keywords`: 3–6 terms used to pre-filter posts cheaply (see step 5).

**Tagged people.** The LinkedIn `/in/` profiles tagged in the caption are kept alongside the
subject. *My call:* people only; company pages are left out for now.

Store the result: one row per doc post. Fields:
- client
- doc id
- week
- title
- status
- has_subject, subject, keywords
- tagged profiles
- caption hash
- the first ~500 characters of the caption

**Size.** Roughly 8 clients × 60 posts × 1 KB, well under 1 MB. That's safe for the 500 MB
database shared with the portal.

### 4. Follower counts

A small table of LinkedIn accounts:
- profile slug
- URL
- name
- follower count
- when it was checked

**Clients.**
- Each client's own count is fetched weekly from their `linkedin_url`.
- If a client has no URL or no count, **the feature is off for that client**.

**Authors.**
- An author's count is fetched the first time they pass the topic check (step 5). It is
  re-checked monthly (*my call*).
- An author whose count can't be fetched is treated as not qualifying.

**Where the count comes from.** First check whether the post scraper we already run
(`harvestapi/linkedin-profile-posts`) includes the author's follower count in its results.
- If it does, it's free: save it whenever posts are fetched.
- If not, use a profile scraper on Apify, sending **all pending profiles in one run** so each run's
  fixed cost is paid once. Which actor to use is left to the builder (see "Left to the builder").

**The rule.** `author_followers > client_followers`. A company page as author doesn't qualify for
now: no count, so it fails closed.

### 5. Finding matching posts, cheapest first

**Source A (free):** the pool of posts already fetched for **any** client in the last 14 days, from
the ~290 tracked profiles.
- A post fetched for Joe can match Lara's subject.
- This costs no Apify credit at all.

**Source B (small cost):** profiles tagged in the client's in-window Live and Approved posts.
- They're fetched with the same post scraper, at the "sometimes" cadence.
- They're fetched only while the post that tagged them is in the 6-week window.
- Their posts go into the pool. They reach a client's queue **only** through matching; they don't
  become tracked creators.

**Steps for each client:**
1. **Cheap pre-filter.** Keep pool posts that:
   - are in English;
   - aren't reposts;
   - aren't the client's own or a colleague's (existing rules);
   - aren't already in this client's feed as a matched post;
   - contain at least one of the client's subject keywords.
2. **Model check** (gpt-5-mini, one call per remaining post). The question: does this post
   genuinely discuss *this* subject, and is it a substantive post (not promotion, a giveaway,
   engagement bait or generic motivation)?
   - It returns a 0–10 score and which doc post it matches.
   - Keep 8 and above (*my call*, strict on purpose).
3. **Follower check** on the authors that remain. This is the only step that can cost Apify credit,
   so it runs last, on the fewest accounts.
4. **Daily limit.** At most **5 new matched posts per client per day** (*my call*), highest score
   first.

**What a surviving post becomes.**
- **New to this client** (from another client's pool or a tagged profile): it's added to the
  client's posts with `source_type = "content_match"`.
- **Already in the client's feed** (from their own tracked creators): it isn't duplicated. It just
  gets the match label.

**Rules that still apply.** Everything that applies to the queue today still applies to matched
posts:
- 14-day window
- English only
- dismiss
- the "other clients already commented" label
- the relevance floor is replaced by the step-2 score for matched posts

### 6. How it looks in the queue

- **From an account the client doesn't track:** the card has a different background colour.
  - Badge: "New account · matches her post 'Your Biological Age Is 9 Years Younger' (wk of 26 Oct)".
  - It also shows the author's follower count, e.g. "52k followers".
- **From an account the client already tracks:** the usual colour, plus a smaller
  "Matches her post '…'" badge.
- The pronoun in labels follows the client (use the client's first name if unsure).
- No new tab or filter (*my call*). Matched posts mix into the normal queue by date, like
  everything else.

### 7. Schedule

OPEN (waiting for Kartikay). There is no daily trigger today: commit 44612c2 (19 Jul 2026)
removed the Vercel cron at someone's request, so sync runs only when someone presses "Sync now".
The schedule depends on his answer:
- doc read
- matching
- client follower counts weekly
- tagged-profile fetches

## Constraints

- Read-only on Google Drive (`drive.readonly` scope).
- The service-account key goes into the `linkedin-api` Vercel env as a secret, never into the repo.
- Database: `public` schema only; nothing in `portal` or `scicomwiz`. The new tables are small
  (under ~2 MB total).
- No mass benchmarking on paid APIs. Test with fixtures and one tiny live smoke test per paid call
  type.
- Every verified change ships the same session: migrated, pushed, deployed to both Vercel projects,
  confirmed live.

## Success looks like

- Each active client with a readable doc gets a few matched posts a week. Fewer is fine; zero for a
  week is acceptable.
- The account managers find most of them worth commenting on.
- Lara's doc today would produce subjects such as:
  - biological age claims
  - AI models of cells
  - lab-grown meat
  - communicating early-stage science
- It would produce none for her travel or family posts.
- Apify spend for this feature stays a small, flat amount per week. It doesn't grow with the number
  of posts scanned.

## Calls made after the builder check (Claude's, for Kartikay to check)

**Tracked creators and the follower rule.**
- The "more followers than the client" rule applies only to accounts the client does **not**
  already track. The account managers chose the tracked ones themselves.
- So a post from a tracked creator:
  - gets only the small "Matches her post" badge;
  - needs no follower lookup;
  - doesn't count toward the 5-per-day limit;
  - keeps the normal relevance floor.
- The step-2 score never makes a hidden tracked post visible, so queues people already know don't
  change.

**Google key.**
- Reuse the tracker's existing service-account key (`~/.config/scicomwiz-tracker/sa.json`) rather
  than creating a second one, which would need GCP project access.
- Risk: rotating that key for the tracker breaks this feature too. The "Content doc: can't read"
  status on the client page is how that shows up.

## Left to the builder

- Table and column names, the migration, and where the parsing code lives.
- The Apify actor for follower counts, and whether the existing post scraper already returns
  them. Check with one small run.
- Exact model prompts, provided they keep "when unsure, say no".
- Colours and exact badge wording within the description above.
- How the tagged-profile fetch hooks into the existing fetch code.
