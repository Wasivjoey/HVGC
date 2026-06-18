"""Generate a polished HVGC LINEUP user manual as MANUAL.pdf.

Run:  python3 generate_manual_pdf.py
Produces MANUAL.pdf next to this script, with the logo on the cover.
"""

import os

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak,
    ListFlowable, ListItem, Table, TableStyle, HRFlowable,
)

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, "static", "logo.png")
OUT = os.path.join(HERE, "MANUAL.pdf")
OUT_VOLUNTEER = os.path.join(HERE, "MANUAL-volunteer.pdf")

GOLD = colors.HexColor("#E8B12E")
BRAND = colors.HexColor("#4453d8")
INK = colors.HexColor("#1c2333")
MUTED = colors.HexColor("#6b7488")
GREEN = colors.HexColor("#138046")
LINE = colors.HexColor("#e6e9f0")

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], textColor=INK, fontSize=17,
                    spaceBefore=14, spaceAfter=7, leading=21)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], textColor=BRAND, fontSize=12.5,
                    spaceBefore=12, spaceAfter=4, leading=16)
BODY = ParagraphStyle("Body", parent=styles["BodyText"], textColor=INK, fontSize=10,
                      leading=15, spaceAfter=5)
BULLET = ParagraphStyle("Bullet", parent=BODY, spaceAfter=2)
NOTE = ParagraphStyle("Note", parent=BODY, textColor=MUTED, fontSize=9.5,
                      leftIndent=8, leading=14)
SECTION = ParagraphStyle("Section", parent=styles["Heading1"], textColor=GOLD,
                         fontSize=13, spaceBefore=6, spaceAfter=2)
TOC = ParagraphStyle("Toc", parent=BODY, fontSize=9.5, leading=14, spaceAfter=1)


def b(text):
    return Paragraph(text, BODY)


def ul(items):
    return ListFlowable(
        [ListItem(Paragraph(i, BULLET), leftIndent=12, value="•") for i in items],
        bulletType="bullet", start="•", leftIndent=14, bulletColor=BRAND,
        spaceAfter=6,
    )


def ol(items):
    return ListFlowable(
        [ListItem(Paragraph(i, BULLET), leftIndent=12) for i in items],
        bulletType="1", leftIndent=16, spaceAfter=6,
    )


def section_bar(title):
    """A coloured section divider band."""
    t = Table([[Paragraph(f'<font color="white"><b>{title}</b></font>',
                          ParagraphStyle("sb", parent=BODY, textColor=colors.white,
                                         fontSize=11))]],
              colWidths=[6.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def build(out_path=OUT, include_admin=True):
    doc = SimpleDocTemplate(
        out_path, pagesize=LETTER,
        leftMargin=0.85 * inch, rightMargin=0.85 * inch,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
        title="HVGC LINEUP — User Manual", author="HVGC LINEUP",
    )
    e = []

    # ---------------------------------------------------------------- cover
    e.append(Spacer(1, 1.6 * inch))
    if os.path.exists(LOGO):
        img = Image(LOGO, width=1.8 * inch, height=1.8 * inch)
        img.hAlign = "CENTER"
        e.append(img)
    e.append(Spacer(1, 0.3 * inch))
    e.append(Paragraph("HVGC LINEUP", ParagraphStyle(
        "cover", parent=H1, fontSize=34, alignment=TA_CENTER, textColor=INK, leading=38)))
    e.append(Paragraph("User Manual", ParagraphStyle(
        "cover2", parent=H1, fontSize=18, alignment=TA_CENTER, textColor=GOLD)))
    e.append(Spacer(1, 0.15 * inch))
    e.append(Paragraph("How to navigate the website and use every feature", ParagraphStyle(
        "cover3", parent=BODY, fontSize=11, alignment=TA_CENTER, textColor=MUTED)))
    e.append(Spacer(1, 0.5 * inch))
    e.append(Paragraph("Audio / Visual Team Scheduling System", ParagraphStyle(
        "cover4", parent=BODY, fontSize=10, alignment=TA_CENTER, textColor=MUTED)))
    e.append(PageBreak())

    # ---------------------------------------------------------------- contents
    e.append(Paragraph("Contents", H1))
    e.append(HRFlowable(width="100%", color=LINE, spaceAfter=8))
    toc = [
        ("Getting started", [
            "1. What is HVGC LINEUP?", "2. Creating an account & signing in",
            "3. Finding your way around"]),
        ("For volunteers", [
            "4. Your dashboard", "5. Setting your availability",
            "6. Services & the roster", "7. Confirming / declining",
            "8. Role swaps", "9. Service notes", "10. Training & videos",
            "11. Your profile"]),
        ("Reference", ["20. The qualification rule", "21. Quick FAQ"]),
    ]
    if include_admin:
        toc.insert(2, ("For administrators", [
            "12. Admin home", "13. Managing people", "14. Roles",
            "15. Building training", "16. Services & documents",
            "17. The scheduling board", "18. Availability grid",
            "19. Swap approvals"]))
    for group, items in toc:
        e.append(Paragraph(f"<b>{group}</b>", ParagraphStyle(
            "tg", parent=BODY, fontSize=10.5, textColor=BRAND, spaceBefore=8, spaceAfter=2)))
        for it in items:
            e.append(Paragraph(it, TOC))
    e.append(PageBreak())

    # ---------------------------------------------------------------- body
    def H(text):
        e.append(Paragraph(text, H2))

    e.append(section_bar("GETTING STARTED"))
    H("1. What is HVGC LINEUP?")
    e.append(b("HVGC LINEUP is the scheduling system for the audio / visual (AV) team. "
               "Volunteers say when they're available, see which services they're on, swap "
               "roles when they can't make it, and complete the training required to serve. "
               "Administrators build the team, assign roles and training, create services, "
               "and schedule people."))
    e.append(b("There are two sides: the <b>Volunteer</b> side (everyone has this) and the "
               "<b>Administration</b> side (admins only). Both are reached from the left-hand menu."))

    H("2. Creating an account &amp; signing in")
    e.append(b("New accounts go through two checks before they can be used:"))
    e.append(ol([
        "On the sign-in page, click <b>“Create an account.”</b>",
        "Enter your name, a <b>username</b>, email, optional phone, and a password (6+ "
        "characters), then click <b>Create account</b>.",
        "<b>Verify your email</b> by opening the link sent to your address (if email isn't "
        "set up on the server, the link is shown on screen and on the admin's page).",
        "<b>Wait for approval</b> — an administrator approves new accounts. You can sign in "
        "once your email is verified and an admin has approved you.",
        "Sign in with your <b>username or email</b> plus your password. Use <b>Sign out</b> "
        "(bottom-left) when finished.",
    ]))
    e.append(b("Forgot your password? Click <b>“Forgot your password?”</b> on the sign-in "
               "page, enter your username or email, and follow the reset link (emailed, or "
               "shown on screen when email isn't configured). The link expires after one hour."))
    e.append(Paragraph("Note: the very first account on a brand-new system becomes an approved "
                       "administrator automatically, so the team can get set up.", NOTE))

    H("3. Finding your way around")
    e.append(b("The dark menu on the left is always visible and split into:"))
    e.append(ul([
        "<b>Volunteer</b> — Dashboard, My Availability, Services, Role Swaps, Training, My "
        "Profile, and this Manual.",
        "<b>Administration</b> (admins only) — Admin Home, People, Roles, Trainings, Schedule, "
        "Availability Grid, Swap Approvals.",
    ]))
    e.append(b("Your name and account type show at the bottom with <b>Sign out</b>. Coloured "
               "banners at the top of the page confirm actions or warn you."))

    e.append(Spacer(1, 6))
    e.append(section_bar("FOR VOLUNTEERS"))
    H("4. Your dashboard")
    e.append(b("Your home base shows:"))
    e.append(ul([
        "<b>Training to complete</b> — required training you must finish before serving.",
        "<b>Your upcoming assignments</b> — services you're on, with a status badge "
        "(Scheduled / Confirmed / Declined).",
        "<b>Your roles &amp; qualification</b> — each role and whether you're qualified or "
        "still in training.",
        "<b>Swaps you can cover</b> — open requests you're qualified to pick up.",
    ]))

    H("5. Setting your availability")
    e.append(b("Open <b>My Availability</b>."))
    e.append(ol([
        "Choose <b>Available</b> or <b>Unavailable</b>.",
        "Pick a <b>From date</b>. Leave <b>To date</b> blank for a single day, or set it to "
        "mark a whole range at once (every day in the range is saved).",
        "Add an optional note and click <b>Save availability</b>.",
    ]))
    e.append(b("Use <b>Quick mark upcoming Sundays</b> to flag the next eight Sundays in one "
               "click each. Your marked dates are listed on the right; <b>Remove</b> clears any entry."))

    H("6. Services &amp; the roster")
    e.append(b("Open <b>Services</b> to see upcoming and recent services. Click <b>Open</b> on "
               "one to view its date, time, location, any <b>service notes</b>, the "
               "<b>programme flow document</b> (if attached), and the full <b>roster</b> "
               "(who serves in each role)."))

    H("7. Confirming or declining an assignment")
    e.append(b("On a service you're scheduled for, under <b>“Your role this service”</b> you can "
               "<b>Confirm</b>, <b>Decline</b>, or <b>Request swap</b>."))

    H("8. Role swaps")
    e.append(b("Can't make a service?"))
    e.append(ol([
        "On the service page, open <b>Request swap</b> under your role, add an optional reason, "
        "and post it.",
        "Qualified teammates see it under <b>Role Swaps</b> and click <b>Volunteer</b> to cover.",
        "An administrator <b>approves</b> the swap, reassigning the slot. The status becomes "
        "<b>Approved</b>.",
    ]))
    e.append(b("The <b>Role Swaps</b> page lists <b>Swaps you can cover</b> (only roles you're "
               "qualified for) and <b>Your swap requests</b> (with status; cancel one that's "
               "still open)."))

    H("9. Service notes")
    e.append(b("On any service page, the <b>Notes</b> panel lets anyone leave a note about that "
               "service. You can delete notes you wrote."))

    H("10. Training &amp; videos")
    e.append(b("Open <b>Training</b> to see what's assigned and whether it's <b>To do</b> or "
               "<b>Completed</b>. Click <b>Start</b> to open a training, which may include:"))
    e.append(ul([
        "A <b>training video</b> that <b>automatically pauses the moment you switch tabs or "
        "leave the window</b> — so you actually watch it.",
        "Written content.",
        "A <b>“Mark this training complete”</b> button.",
    ]))
    e.append(b("You must complete every required training for a role before you can be scheduled "
               "in it (see section 20)."))

    H("11. Your profile")
    e.append(b("<b>My Profile</b> lets you update your name and phone, and shows your roles with "
               "their qualification status. Email and account type are managed by an administrator."))

    e.append(Spacer(1, 6))
    if include_admin:
        e.append(section_bar("FOR ADMINISTRATORS (admins only)"))
        H("12. Admin home")
        e.append(b("<b>Admin Home</b> gives an overview: counts of people, roles, services, "
                   "trainings, open swaps, and training in progress, plus next services and swaps "
                   "needing attention."))

        H("13. Managing people")
        e.append(b("New sign-ups appear on <b>Admin Home</b> and on <b>People</b> with a "
                   "<b>Pending</b> badge — click <b>Approve</b> to let them sign in. Open "
                   "<b>People</b>, then <b>Manage</b> on anyone to:"))
        e.append(ul([
            "<b>Approve / revoke approval</b>, and <b>mark email verified</b> manually (or copy "
            "the verification link to send them).",
            "<b>Assign / remove roles</b> (assigning a role auto-queues its required training).",
            "<b>Assign, complete, reset, or remove training.</b>",
            "<b>Make / revoke admin</b> and <b>activate / deactivate</b> the account. (You can't "
            "change your own admin/approval status.)",
        ]))

        H("14. Roles")
        e.append(b("Open <b>Roles</b> to create serving positions (Audio Engineer, Lighting, "
                   "Camera, …). Edit a role's name/description or delete it. Each shows how many "
                   "people are assigned and how many are fully qualified."))

        H("15. Building training")
        e.append(b("Open <b>Trainings</b> to create modules. For each set:"))
        e.append(ul([
            "<b>Title</b> and short description.",
            "<b>Video link</b> — a YouTube, Vimeo, or direct .mp4 URL; it embeds for the volunteer "
            "and auto-pauses when they leave the window.",
            "<b>Linked role</b>.",
            "<b>Content / instructions</b>.",
            "<b>Required to serve</b> — tick if it must be completed before serving in that role.",
        ]))
        e.append(b("Edit or delete trainings; each shows completion counts."))

        H("16. Services &amp; documents")
        e.append(b("Open <b>Schedule</b>. <b>+ New service</b> creates a service with <b>title, "
                   "date, start time, location, notes</b>, and an optional <b>programme flow "
                   "document</b> (PDF, Word, PowerPoint, Excel, images). Later you can edit any of "
                   "these — including the time and location — and attach, replace, or remove the "
                   "document from the service's page."))

        H("17. The scheduling board")
        e.append(b("Click <b>Schedule</b> on a service to build its team. For each role, every "
                   "candidate shows an availability dot for that date (green = available, red = "
                   "unavailable, grey = not marked) and a badge: <b>Qualified</b> or <b>Not "
                   "trained</b>."))
        e.append(b("Click <b>Assign</b> for a qualified person. Untrained people are blocked, but "
                   "<b>Override</b> assigns them anyway. The <b>current roster</b> at the top lets "
                   "you <b>Remove</b> anyone."))

        H("18. Availability grid")
        e.append(b("<b>Availability Grid</b> is a matrix of every volunteer against each upcoming "
                   "service date, using the same green / red / grey dots — the fastest way to see "
                   "who's free."))

        H("19. Swap approvals")
        e.append(b("<b>Swap Approvals</b> lists all swap requests. When someone has volunteered, the "
                   "request shows <b>Ready to approve</b> — <b>Approve</b> reassigns the slot to "
                   "them, or <b>Reject</b> declines it."))

    e.append(Spacer(1, 6))
    e.append(section_bar("REFERENCE"))
    e.append(Paragraph("20. The qualification rule", ParagraphStyle(
        "qh", parent=H2, textColor=GREEN)))
    e.append(b("The heart of the system: <b>a volunteer can only be scheduled for a role once "
               "they have completed every required training linked to that role.</b>"))
    e.append(ul([
        "Assigning a role auto-queues its required training.",
        "Until it's done, the person shows <b>“Training X/Y”</b> and can't be assigned (admins "
        "may override).",
        "The same rule decides which open swaps a volunteer may cover.",
    ]))

    H("21. Quick FAQ")
    e.append(ul([
        "<b>I just registered but can't sign in.</b> Open the email verification link, then "
        "wait for an administrator to approve your account — both are required.",
        "<b>I can't be assigned to a role.</b> You likely haven't finished its required "
        "training — check <b>Training</b>.",
        "<b>The training video stopped.</b> Intentional — it pauses when you leave the window. "
        "Return to the tab and press play.",
        "<b>A week off shows many rows.</b> A range is stored as one entry per day; that's "
        "normal and lets schedulers see each day.",
        "<b>I can't see the admin menu.</b> Those tools are for administrators; ask an admin to "
        "grant access from <b>People</b>.",
        "<b>I forgot to confirm and the service passed.</b> Confirming is a courtesy so the "
        "team knows you're coming; it doesn't remove you from the roster.",
    ]))

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(0.85 * inch, 0.45 * inch, "HVGC LINEUP — User Manual")
        canvas.drawRightString(7.65 * inch, 0.45 * inch, "Page %d" % doc_.page)
        canvas.setStrokeColor(LINE)
        canvas.line(0.85 * inch, 0.6 * inch, 7.65 * inch, 0.6 * inch)
        canvas.restoreState()

    def cover_bg(canvas, doc_):
        # Plain on the cover (page 1); footer on later pages.
        if doc_.page > 1:
            footer(canvas, doc_)

    doc.build(e, onFirstPage=cover_bg, onLaterPages=cover_bg)
    print("Wrote", out_path)


if __name__ == "__main__":
    build(OUT, include_admin=True)              # full manual (admins)
    build(OUT_VOLUNTEER, include_admin=False)   # volunteer-only manual
