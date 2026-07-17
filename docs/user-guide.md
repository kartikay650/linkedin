# Engagement Dashboard — Team Guide

## What this tool does

It finds recent LinkedIn posts worth commenting on for each client, drafts a comment in that client's voice, and lets you review it before anything goes out.

You post the comment yourself, by hand, from the client's own account. The tool never logs into a client's LinkedIn and never posts on its own. Every reply is reviewed by a person first.

[Screenshot: the dashboard home with a client selected]

## Logging in

1. Open the dashboard link.
2. Sign in with your email and password.

Tip: after we push an update, do a hard refresh so you see the latest version. On Mac press Cmd+Shift+R, on Windows press Ctrl+Shift+R.

## Finding your way around

The left sidebar has two parts:

- **Workspace** at the top: the shared Creators & prospects list, and Analytics. These cover all clients.
- **Clients** below: your client list, with a search box and a "+" to add a new client.

Click a client to open their Queue.

[Screenshot: sidebar with Workspace and Clients sections]

## The daily workflow

This is the loop you'll repeat for each client.

### 1. Open the Queue

Pick a client. The Queue shows their recent relevant posts, newest first. Each post has a relevance score out of 10, so you know what's worth your time. Higher is more relevant to that client.

[Screenshot: a client Queue with a few posts]

### 2. Read the post

Each card shows a one-line summary and the post text. Use "Open post" to see it on LinkedIn, or "Copy link" to grab the link. If a post isn't worth engaging, click "Dismiss" to clear it.

### 3. Draft a reply

Click **Draft reply**. The tool writes one comment in the client's voice.

[Screenshot: a post card with the Draft reply button]

### 4. Review and adjust

You can edit the text directly, or use the quick buttons to reshape it: Shorter, More personal, More neutral, More scientific, More authoritative, Remove opinion. You can also type your own instruction and press Tweak. Not happy with it at all? Click **Regenerate** for a fresh one.

[Screenshot: the reply box with the tweak buttons]

### 5. Check the sources

Under the reply is a short safety line. If the reply makes a claim worth checking, it flags it and pulls a source (a study or a reputable page). Green means it's grounded and there's nothing to verify.

[Screenshot: the safety and sources line under a reply]

### 6. Approve it

When the reply is good, click **Approve**. The post moves out of the Queue and into the **Approved** tab, ready to post.

### 7. Post it, then mark it

Approved comments are posted by hand:

1. Click **Copy** to copy the reply.
2. Open the post on LinkedIn while logged into the client's account.
3. Paste the comment and post it.
4. Back in the dashboard, click **Mark posted**. It moves to the **Posted** tab.

The tabs at the top let you move between Queue, Approved, Posted, and All.

## Making replies sound right

This is the part that matters most. The more you feed the tool, the more it sounds like the client.

- **Give feedback:** on any reply, click **Give feedback** and write a short note, for example "keep it under two sentences" or "never mention supplements." The note applies to every future reply for that client. This is how you correct the AI over time.
- **Example replies:** in Manage profile, paste a few ideal replies in the client's voice (and ones to avoid). New drafts are anchored to these.
- **Voice samples:** the client's real writing, added in their profile, is the strongest signal of all.

[Screenshot: the Give feedback box on a reply]

## Managing a client

Open a client and click **Manage profile**. Here you can edit:

- **Client details:** name, specialty, LinkedIn, topics.
- **Brand profile:** their voice, viewpoints, audience, key messages, guardrails.
- **Example replies:** the tone benchmark described above.
- **AI guidance notes:** the feedback notes, where you can review and remove old ones.
- **Tracked profiles:** the people whose posts we pull for this client.
- **Documents:** upload a strategy doc or add a YouTube link to teach the tool their voice.

To add a new client, click the "+" in the sidebar and follow the steps.

[Screenshot: Manage profile panel]

## Creators & prospects

Open **Creators & prospects** from the Workspace section. This is the shared master list every client draws from.

- **Tracked creators:** their posts get pulled into feeds. Use the client picker on each one to choose which clients should see their posts.
- **Prospects:** people to consider engaging later. Promote one to start tracking their posts.
- Add your own with the box at the top.

[Screenshot: Creators & prospects page with the client picker open]

## Analytics

Open **Analytics** from the Workspace section for a quick read on activity: how many replies are drafted, approved, and posted, who you're engaging with most, and the pipeline per client.

## Syncing

"Sync now" on a client pulls their latest posts. It runs in the background and new posts appear within a minute or so. There's also an automatic sync every morning, so fresh posts are waiting for you.

The Queue only shows posts from the last few days, so you're always looking at current conversations.

## Good practice

- Quality over quantity. These clients are well established, so only comment where it adds something.
- Keep the feedback coming. Every note and example makes the next reply better.
- One reply per post. Regenerate if you don't like it, don't stack drafts.

---

# Part 2 — For Lara (admin and handover)

This section is for you and anyone who administers the account. It covers access and running costs, so you may want to keep it in a separate doc from the team guide above.

## Access and who can do what

- Everyone signs in with a login. Right now the team shares one login. If you'd like, we can give each person their own so you can add or remove access one at a time.
- Sign-ups are closed on purpose. Only people we invite can get in. To add or remove someone, message [your contact].
- Anyone signed in can see and manage every client. There's no per-person client limit yet. If you want each manager to see only their own clients, that's a small piece of work we can add.
- Keep the login details private and stored somewhere safe, not in this shared doc.

## What runs it, and what it costs

In plain terms: the dashboard lives on cloud hosting. It uses one service to fetch LinkedIn posts and an AI service to draft the comments and score how relevant each post is.

Running cost is usage-based, so it tracks how heavily the team uses it:

- **Fetching posts:** a small pay-as-you-go amount, currently on a low monthly budget with a backup account for safety. You can see the fetching credit used at the bottom of any client page.
- **AI drafting and scoring:** pay per use. It grows with how many replies the team generates.
- **Hosting:** on free plans for now.

If the team or the client list grows a lot, the fetching budget is the first thing we'd raise.

## What's done, and what's next

Live now:

- A feed per client, with each post scored for relevance
- Reply drafting in each client's voice, with review, tweaks, and feedback that teaches the AI
- Safety and source checking on claims
- A shared creator list you assign to specific clients
- Approve and posted workflow, plus analytics

Planned, as separate pieces of work:

- Reporting. This is the next project, once you send sample reports you'd like to produce.
- Automatic prospect discovery. Finding new, high-quality people worth engaging.
- Optional: individual team logins and per-person client access.

## Support

- Point of contact for anything broken or any change: [your name and preferred contact].
- If something looks off, first try a hard refresh (Cmd+Shift+R on Mac, Ctrl+Shift+R on Windows). If it's still wrong, send a short note on what you clicked and what happened.
- Commercial terms and the invoice are handled separately.
