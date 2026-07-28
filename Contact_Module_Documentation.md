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

**In simple words:** when someone fills the form on the website, the email that arrives in the inbox is just one plain block of text, like this:
```
Name: ...
Email: ...
Phone: ...
Message: ...
Submitted at: ...
```
If nobody separated this out, staff would see this whole messy block as "the email" — hard to read, and impossible to search by just a name or phone number. So the code reads this text and picks out each piece on its own:

- **Name** — takes the text after `Name:` and uses it as the person's name. If that's missing for some reason, it just keeps whatever name was already on the email.
- **Email** — takes the text after `Email:`, but only uses it if it looks like a real email address (has an "@" in it). If not, it keeps the original email address the message actually came from.
- **Phone** — takes the text after `Phone:`. If it's missing, the phone field is just left blank — nothing breaks.
- **Message** — this is the actual question the person typed. The code grabs everything between `Message:` and `Submitted at:` and shows *only that* as the message — not the Name/Email/Phone clutter around it. If `Submitted at:` happens to be missing, that's fine too — it just grabs everything from `Message:` onward instead, so nothing is lost. The only real problem case is if the word `Message:` itself is missing — then the code gives up trying to be clever and just shows the whole raw email instead, so nothing silently disappears.

**Worth knowing:** the website's own contact form requires Name, Email, Phone, and Message to be filled in before it lets someone submit at all — so in normal, everyday use, none of these "what if it's missing" situations should actually happen. They're documented here because that's genuinely what the code does if something unexpected ever comes through (a form change on the website's side, a broken email, etc.) — not because they're expected to happen day to day.

### Where the Data Lives (`database.py`)

- Contact name and phone are stored in their own dedicated columns on the `messages` table.
- The dashboard query specifically excludes Coral Academy's own internal addresses, so only real visitor enquiries show up.


---

## 📋 File Reference

| File | Role |
|---|---|
| `email_filter.py` | Recognizes an incoming email as a contact-form enquiry |
| `process_email.py` | Extracts name/email/phone/message from the form email |
| `database.py` | Stores and queries contact-form entries |
| `templates/contact_dashboard.html` | The dedicated dashboard |
| `main.py` — `/contact-dashboard`, `/contact-dashboard/sent` | Routes powering the dashboard and its sent-history view |
| `main.py` — `/submit-enquiry` | **Dead code, not part of the live pipeline** — looks like an earlier attempt at letting the website POST enquiries directly into this app, superseded by the actual email-based flow above. Nothing calls it (confirmed — no code or external system references this app's own `/submit-enquiry`). It's also buggy: it never sets `mailbox="contact_form"` on save, so if it were ever triggered, the enquiry would incorrectly land in the regular inbox instead of the Contact Form dashboard. Safe to delete. |
| `contactform.py` | Manual test script that hits Coral Academy's own separate `api.preprod.coralacademy.com/submit-enquiry` — unrelated to this app's dead route above, not part of the live pipeline |

---

*Documentation — Contact Form module.*
