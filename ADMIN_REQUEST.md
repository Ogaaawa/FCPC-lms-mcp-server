# Request: issue Moodle web service tokens for students

**Site:** https://lms.fcpc.edu.ph (Moodle 4.5)
**Requested by:** [your name] (`[your Moodle username]`)

We need web service tokens for students. Students cannot obtain them
themselves on this site, so we are asking you to issue them.

Pick **Option A** or **Option B** below. Both are read-only. Neither requires a
code change or a plugin.

---

## Current state

| | |
|---|---|
| `enablewebservices` | on |
| `moodle_mobile_app` service | enabled, responding |
| Student authentication | Google only |
| `moodle/webservice:createmobiletoken` | granted to all users (Moodle default) |
| `moodle/webservice:createtoken` | manager only (Moodle default) |

## Problem

Students cannot get a token by any route available to them.

| Route | Result |
|---|---|
| `/login/token.php` | `invalidlogin` — Google accounts have no Moodle password |
| `/admin/tool/mobile/launch.php` | Returns `moodlemobile://token=...`. Moodle validates the scheme against `^[a-zA-Z][a-zA-Z0-9-+.]*$`, so it cannot be redirected to a web application. Only a native app can receive it. |
| `/user/managetoken.php` | Shows nothing — requires `moodle/webservice:createtoken`, which students do not have |

Verified against the live site on 2026-08-25.

---

## Option A — Issue one token per student

**Change:** Site administration → Server → Web services → **Manage tokens** →
Create token, once per participating student.

- User: the student
- Service: Moodle mobile web service
- Valid until: end of the pilot

Send each student their own token string.

**Result:** Each token carries that student's own permissions and nothing more.
One student's token cannot read another student's data. Revoking a student is
one delete on the same page.

**Cost:** one manual creation per student. Practical for a class, not for the
whole institution.

---

## Option B — Issue one token to a service account

**Change:**

1. Create an account `svc-ai-assistant`, not used for interactive login.
2. Site administration → Users → Permissions → **Define roles** → new role,
   assignable at system level, allowing:

   | Capability | Needed for |
   |---|---|
   | `moodle/site:readallmessages` | reading a student's conversations |
   | `moodle/user:viewdetails` | resolving a student's courses |
   | `moodle/course:view` | listing course membership |
   | `mod/assign:view` | assignment due dates |
   | `mod/quiz:viewreports` | quiz attempt state |

3. Assign that role to `svc-ai-assistant` at system level.
4. Create a token for it under Manage tokens.
5. Restrict the token by IP and set an expiry date.

**Result:** Students never handle a token; they sign in with Google as they
already do, and each request is scoped to that student's `userid`.

**Understand before choosing this:** the resulting token can read **every**
student's messages, courses, assignments and quiz state. It is a privileged
secret held on a server. If that is not acceptable, use Option A.

---

## Functions called

Read-only, all of them. Nothing writes, enrols, grades, or sends messages.

| Function | Used for |
|---|---|
| `core_webservice_get_site_info` | confirming the token works |
| `core_enrol_get_users_courses` | enrolled courses |
| `mod_assign_get_assignments` | assignment due dates |
| `core_message_get_conversations` | unread messages |
| `mod_quiz_get_quizzes_by_courses` | quiz list |
| `mod_quiz_get_user_attempts` | which quizzes are still pending |

## Verifying the token works

```
https://lms.fcpc.edu.ph/webservice/rest/server.php
    ?wstoken=<TOKEN>
    &wsfunction=core_webservice_get_site_info
    &moodlewsrestformat=json
```

JSON containing `sitename` and `userid` means it is working.

## What we need back

- **Option A:** the token string for each student
- **Option B:** confirmation that `svc-ai-assistant` exists, plus its token

Please send tokens through whatever channel your policy allows for credentials.

---

*Context: the tokens feed an assistant that answers a student's questions about
their own Moodle data — what is due, what is unread, which quizzes are pending.*
