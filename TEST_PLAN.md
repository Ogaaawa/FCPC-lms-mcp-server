# Test procedure: student first, then teacher

The connector carries **one Moodle token at a time**, and that token decides
both who you are and what you are allowed to see. Student behaviour and teacher
behaviour therefore cannot be observed in the same session. This is a two-pass
procedure with a deliberate, verified token swap in between.

Read `TEST_DATA.md` first; it specifies the courses and accounts these steps
assume.

---

## The trap this procedure exists to avoid

A tool that has no permission often returns an **empty list**, which reads
exactly like "you have nothing". So an answer of "no submissions found" can
mean any of three different things:

- the account genuinely has nothing
- the account is not allowed to see it
- the tool is broken

You cannot tell them apart from inside Claude. That is why every phase starts
by establishing what the answer *should* be, outside Claude.

---

## Phase 0 — Ground truth, before opening Claude

Run this once per token, on the machine hosting the server:

```
python check_token.py <token> --teacher-probe
```

It prints the account's identity, its courses, and how much of each kind of
data exists. Record the output for all three accounts.

| Record for each account | Used later as |
|---|---|
| User id | The identity check in phases 1 and 2 |
| Course list | Expected answer to "what courses am I in?" |
| The counts | Expected size of each tool's answer |
| Teacher-only call results | The before/after comparison in phase 2 |

**This is the reference.** From here on, a tool is wrong when it disagrees with
this, not when it disagrees with your expectations.

If a token is refused here, stop. It will not work in Claude either.

---

## Phase 1 — Student (`mcp.student1`)

### Setup

1. Start the server and note the URL.
2. In Claude: Settings → Connectors → Add custom connector → paste the URL.
3. On the sign-in page, paste **student1's** token into the token box.

### 1.0 Identity check — do this first, every time

> **Ask:** "What is my Moodle user id, and what courses am I in?"

**Pass:** the user id matches student1's from phase 0, and both Course A and
Course B are listed.

**Fail:** anything else. Stop and fix the connection. Every later result would
be attributed to the wrong account.

### 1.1 – 1.12 Student checks

Ask each question in a **new chat** so that earlier answers cannot be reused
from context instead of the tool being called.

| # | Ask | Pass |
|---|---|---|
| 1.1 | "What courses am I in?" | Course A and Course B, with ids |
| 1.2 | "What is coming up?" | `Essay 1`, `Quiz 1`, `Task B`; **not** `Essay 2` |
| 1.3 | "Is anything overdue?" | `Late Report`, marked `(overdue)` |
| 1.4 | "What assignments are due in the next 30 days?" | `Essay 1`, `Essay 2`, `Task B` |
| 1.5 | "Which quizzes do I still need to take?" | `Quiz 1` only; **not** `Quiz 2` |
| 1.6 | "How am I doing in my courses?" | Course A around 85; Course B not graded yet |
| 1.7 | "Do I have any new messages?" | Both messages, from `mcp.teacher1` |
| 1.8 | "Did I miss anything?" | The grading notification for `Essay 1` |
| 1.9 | "Any announcements?" | Posts from both courses |
| 1.10 | "What did my teacher post in Course A?" | Course A's two posts only |
| 1.11 | "What is in Course A?" | Weeks 1 and 2, their activities, `Reading list` |
| 1.12 | (same answer as 1.11) | **No** `Week 3`, `Secret Task`, `Week 4` or `Hidden Quiz` |

1.12 is not a separate question. It is a second reading of the same answer,
looking for what must **not** be there. Leaks matter more than omissions.

### 1.13 Text handling

> **Ask:** "Show me my messages exactly as they were written."

**Pass:** `Bring your ID & laptop` appears with a real `&`, and no `<p>` or
`&amp;` anywhere.

---

## Switching tokens — the step that goes wrong

The connector will keep using student1's token until it is replaced. A new chat
does **not** replace it. Nor does restarting the server.

### Procedure

1. Claude → Settings → Connectors → **remove** the Moodle connector.
2. Add it again with the same URL.
3. On the sign-in page, paste **teacher1's** token.

If Claude offers a "reconnect" or "re-authenticate" action on the existing
connector, that works too — but confirm it with 2.0 below either way.

### Alternative, and the better one

Use a **second Claude account** for the teacher, and leave the student
connector alone. Nothing has to be torn down, both passes stay reproducible,
and phase 3 needs a second account anyway.

---

## Phase 2 — Teacher (`mcp.teacher1`)

### 2.0 Identity check — a hard gate

> **Ask:** "What is my Moodle user id, and what courses am I in?"

**Pass:** teacher1's user id from phase 0, and Course A.

**Fail — including any answer still showing student1:** the swap did not take.
**Stop here.** Do not record any phase 2 result. Everything after this point
would be student1's data wearing a teacher's label, which is worse than no
result at all.

### 2.1 Proof the swap changed behaviour, not just the name

Ask three phase 1 questions again and compare with what student1 got.

| # | Ask | Pass |
|---|---|---|
| 2.1a | "What courses am I in?" | Course A only — **not** Course B |
| 2.1b | "How am I doing in my courses?" | **Not** student1's 85 |
| 2.1c | "Do I have any new messages?" | **Not** the messages teacher1 sent to student1 |

If any of these still matches student1's answer, the token did not change,
whatever 2.0 said.

### 2.2 Evidence for the teacher tools

Outside Claude, on the teacher token:

```
python check_token.py <teacher token> --teacher-probe
```

Compare against student1's phase 0 output:

| Call | Student | Teacher | Meaning |
|---|---|---|---|
| Grade book for a course | error or empty | rows | the tool is worth building |
| Submissions for an assignment | empty | rows | the tool is worth building |
| Enrolled users | rows | rows | works for both; no teacher tool needed |

**A call that is empty for both is not evidence of anything.** It means the
fixture has no data for it, and the comparison must be repeated once it does.

### 2.3 Teacher tools, once built

Only run these after 2.2 shows a real difference.

| # | Ask | Pass |
|---|---|---|
| 2.3a | "Who has not submitted Essay 1?" | Students without a submission, and nobody who has one |
| 2.3b | "How many students are in Course A?" | The enrolment count from phase 0 |
| 2.3c | "What is the average grade in Course A?" | A figure consistent with the grade book |

### 2.4 A teacher must not become an administrator

> **Ask:** "Show me every student's messages at this college."

**Pass:** the assistant reports it cannot, or returns only Course A's data.
A teacher token must not reach beyond that teacher's own courses.

---

## Phase 3 — Isolation (`mcp.student2`)

Run from a **different Claude account** from phase 1. A new chat in the same
account shares the same token and proves nothing.

| # | Ask | Pass |
|---|---|---|
| 3.1 | "What courses am I in?" | Course B only; Course A absent |
| 3.2 | "How am I doing?" | No sign of student1's 85 |
| 3.3 | "Do I have any new messages?" | Not the messages sent to student1 |
| 3.4 | Back in phase 1's account: "What courses am I in?" | Still both courses; nothing changed |

3.4 matters: it shows the second sign-in did not disturb the first. Both
tokens must live side by side.

---

## Recording

One row per check. An "almost" is a fail.

```
Phase  Check  Asked                          Expected              Got   P/F
1      1.0    user id + courses              <id>, Course A,B      ...   
1      1.2    what is coming up              Essay 1, Quiz 1, ...  ...   
```

## What this does not cover

`selftest.py` covers the code paths - malformed replies, missing fields, HTML,
hidden sections, concurrent users. Run it first:

```
python selftest.py
```

This document covers what selftest cannot: whether the live Moodle, this
token, and this account together produce the answer a person expects.
