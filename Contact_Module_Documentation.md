# 📮 Contact Form Module — Full Documentation

*How a website enquiry quietly becomes a reply-ready message in its own dashboard.*

---

## 🌟 What This Module Does (Simple Version)

When someone fills out the contact form on Coral Academy's website, it doesn't need a separate system — it arrives as a normal email, gets automatically recognized, and has its name, email, phone, and message **neatly pulled apart** from the raw form text. It then shows up in its own dedicated dashboard, completely separate from the regular inbox, ready for a staff member to reply to directly.

---

## 🎬 Features

1. **Automatic Recognition** — enquiry emails from the website are recognized the moment they arrive.
2. **Clean Field Extraction** — name, email, phone, and the actual message are separated from the form's plain-text layout; the raw template text never shows up in the reply thread.
3. **Its Own Dashboard** — a dedicated view, entirely separate from the main inbox, with search across name/email/phone/message.
4. **Reply Like Any Email** — replying goes straight to the visitor's real email address, same as any normal reply.
5. **Sent History** — a filtered view shows only the enquiries already replied to.

---

## 🛠️ Technical Details

### Detection Rule (`email_filter.py`)

An email is recognized as a contact-form enquiry when **both** are true:
- The sender is `no-reply@coralacademy.com`
- The subject starts with `"New Contact Form Enquiry"` (not case-sensitive)

When matched, it's tagged category `"Contact Form Enquiry"` and mailbox `"contact_form"` — which routes it to its own dashboard instead of the main inbox.

### Field Extraction (`process_email.py`)

The raw form email is a simple labeled template:
```
Name: ...
Email: ...
Phone: ...
Message: ...
Submitted at: ...
```
- **Name** — replaces the sender's display name if found; otherwise keeps the original.
- **Email** — replaces the sender address only if a valid-looking value (contains "@") is found; otherwise the original envelope address is kept.
- **Phone** — stored if present, left blank otherwise.
- **Message** — everything between "Message:" and "Submitted at:" becomes the body shown to staff; if this pattern isn't found, the whole raw email is shown as a fallback.

### Where the Data Lives (`database.py`)

- Contact name and phone are stored in their own dedicated columns on the `messages` table.
- The dashboard query specifically excludes Coral Academy's own internal addresses, so only real visitor enquiries show up.

### Known Issue Worth Flagging

There's a second, more direct API endpoint (`POST /submit-enquiry`) that was clearly meant to save a contact-form submission straight to the database without going through email at all. As it stands, it doesn't work — it's missing two required pieces of information the save step needs, causing an error, and even if fixed it still wouldn't set the flag needed to show up on the dashboard. The email-based flow above is the one that actually works end to end.

---

## 📋 File Reference

| File | Role |
|---|---|
| `email_filter.py` | Recognizes an incoming email as a contact-form enquiry |
| `process_email.py` | Extracts name/email/phone/message from the form email |
| `database.py` | Stores and queries contact-form entries |
| `templates/contact_dashboard.html` | The dedicated dashboard |
| `main.py` — `/contact-dashboard`, `/contact-dashboard/sent` | Routes powering the dashboard and its sent-history view |
| `main.py` — `/submit-enquiry` | Direct-save endpoint, currently non-functional |
| `contactform.py` | Manual test script for the preprod enquiry API — not part of the live pipeline |

---

*Documentation — Contact Form module.*
