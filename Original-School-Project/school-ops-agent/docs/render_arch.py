"""Render the School Ops architecture diagram to PNG using Pillow only."""
from PIL import Image, ImageDraw, ImageFont

W, H, S = 1180, 760, 2  # supersample 2x for crispness
img = Image.new("RGB", (W * S, H * S), "white")
d = ImageDraw.Draw(img)

BLUE = (31, 78, 140)
INK = (32, 48, 63)
GREY = (90, 107, 120)
AMBER = (138, 94, 16)
AMBER_BG = (255, 246, 230)
GREY_BG = (240, 240, 240)
GREY_LINE = (154, 166, 176)
LIGHT = (243, 247, 253)


def font(sz, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, sz * S)
        except OSError:
            continue
    return ImageFont.load_default()


def box(x, y, w, h, fill="white", outline=BLUE, width=2, dash=False):
    d.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S],
                        radius=8 * S, fill=fill, outline=outline, width=width * S)


def text(x, y, s, fnt, fill=INK, anchor="la"):
    d.text((x * S, y * S), s, font=fnt, fill=fill, anchor=anchor)


def num_badge(x, y, n, color=BLUE):
    r = 9
    d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=color)
    text(x, y, str(n), font(11, True), "white", "mm")


def arrow(x1, y1, x2, y2, color=BLUE, dash=False):
    d.line([x1 * S, y1 * S, x2 * S, y2 * S], fill=color, width=2 * S)
    # arrowhead
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    for da in (math.radians(150), math.radians(-150)):
        d.line([x2 * S, y2 * S,
                (x2 + 8 * math.cos(ang + da)) * S, (y2 + 8 * math.sin(ang + da)) * S],
               fill=color, width=2 * S)


F_TITLE = font(24, True)
F_FLOW = font(12, True)
F_HDR = font(11, True)
F_ITEM = font(9)
F_LEG = font(10)
F_NOTE = font(9)

# Title
text(590, 24, "School Operations Agent Platform — Architecture", F_TITLE, BLUE, "ma")
text(590, 52, "Chat / Web  →  Auth & Scope  →  Intent / Parse  →  Validate & Approve  "
              "→  Deterministic Action  →  Audited Response", F_FLOW, BLUE, "ma")

# Legend
d.rounded_rectangle([40 * S, 74 * S, 54 * S, 88 * S], radius=3 * S, fill="white",
                    outline=BLUE, width=2 * S)
text(60, 81, "Built & verified", F_LEG, INK, "lm")
d.rounded_rectangle([190 * S, 74 * S, 204 * S, 88 * S], radius=3 * S, fill=AMBER_BG,
                    outline=AMBER, width=2 * S)
text(210, 81, "Partial (scoped)", F_LEG, INK, "lm")
d.rounded_rectangle([340 * S, 74 * S, 354 * S, 88 * S], radius=3 * S, fill=GREY_BG,
                    outline=GREY_LINE, width=2 * S)
text(360, 81, "Future / bonus (not built)", F_LEG, INK, "lm")

# ---- Top row ----
def layer(x, n, hdr_lines, items, w=150, h=180, fill="white", outline=BLUE,
          badge=BLUE, dash=False):
    box(x, 108, w, h, fill=fill, outline=outline, dash=dash)
    num_badge(x + 16, 126, n, badge)
    hy = 122
    for ln in hdr_lines:
        text(x + 32, hy, ln, F_HDR, BLUE if outline == BLUE else outline, "lm")
        hy += 14
    iy = 160
    for it in items:
        text(x + 12, iy, it, F_ITEM, INK if outline == BLUE else outline, "lm")
        iy += 18


layer(40, 1, ["USER", "EXPERIENCE"],
      ["• Web app (Next.js)", "• Admin/Teacher/", "  Student dashboards",
       "• Telegram chatbot", "• Document upload", "• Image upload (OCR)"])
layer(208, 2, ["API & SECURITY", "(FastAPI)"],
      ["• Auth (JWT, expiry)", "• Authz / RBAC", "  (policy engine)",
       "• Tenancy scope", "• Rate limiting", "• Correlation-id"])
layer(376, 3, ["AGENT", "ORCHESTRATOR"],
      ["• Channel dispatcher", "• Intent router", "• Context builder",
       "  (AuthContext)", "• Prompt builder", "  (injection-guard)"])
layer(544, 4, ["LLM LAYER"],
      ["• Provider-agnostic", "  client", "• Anthropic / OpenAI",
       "• Deterministic mock", "  fallback (offline)", "• Classify + extract"])
layer(712, 7, ["TOOL / ACTION", "LAYER"],
      ["• Service handlers", "  (the \"tools\")", "• State machines",
       "• Reminder engine", "• DB SQLite/Postgres", ""], w=158)
# amber sub-note in tool layer
d.rounded_rectangle([720 * S, 264 * S, 862 * S, 282 * S], radius=4 * S,
                    fill=AMBER_BG, outline=AMBER, width=S)
text(726, 273, "no MCP / agent gateway", F_ITEM, AMBER, "lm")

# Validation checkpoint (shield-ish)
cx = 918
d.polygon([(cx) * S, 158 * S, (cx + 28) * S, 170 * S, (cx + 28) * S, 202 * S,
           (cx) * S, 246 * S, (cx - 28) * S, 202 * S, (cx - 28) * S, 170 * S],
          fill=LIGHT, outline=BLUE, width=2 * S)
text(cx, 188, "CHECK", F_HDR, BLUE, "mm")
text(cx, 204, "Validate", F_ITEM, INK, "mm")
text(cx, 216, "+ Approve", F_ITEM, INK, "mm")
text(cx, 262, "Pydantic + human", F_NOTE, GREY, "mm")
text(cx, 274, "gate + state rules", F_NOTE, GREY, "mm")

layer(978, 8, ["RESPONSE &", "ACTION"],
      ["• Assignment created", "• Feedback / revision", "• Reminder sent",
       "• Roster imported", "• Live dash (SSE)", "• Chat reply"], w=160)

# top flow arrows
for x1, x2 in [(190, 206), (358, 374), (526, 542), (694, 710)]:
    arrow(x1, 198, x2, 198)
arrow(870, 198, 888, 198)
arrow(948, 198, 976, 198)

# ---- Middle row ----
# 5 RAG future
box(208, 320, 230, 120, fill=GREY_BG, outline=GREY_LINE, dash=True)
num_badge(224, 338, 5, GREY_LINE)
text(240, 342, "RAG & KNOWLEDGE (future/bonus)", F_HDR, GREY, "lm")
for i, t in enumerate(["• Document store ✓ (built)", "• Embeddings / vector DB ✗",
                       "• Retrieval / re-ranking ✗", "• Q&A over policy docs ✗"]):
    text(220, 368 + i * 20, t, F_ITEM, GREY, "lm")

# 6 Memory partial
box(456, 320, 238, 120, fill=AMBER_BG, outline=AMBER)
num_badge(472, 338, 6, AMBER)
text(488, 342, "MEMORY / STATE (partial)", F_HDR, AMBER, "lm")
for i, t in enumerate(["• Session (JWT) ✓", "• Workflow state (machines) ✓",
                       "• User/resource context ✓", "• Long-term memory ✗"]):
    text(468, 368 + i * 20, t, F_ITEM, AMBER, "lm")

# Audit log
box(978, 320, 160, 120)
text(990, 342, "AUDIT LOG", F_HDR, BLUE, "lm")
for i, t in enumerate(["Append-only,", "PII-screened log of",
                       "every request, action,", "decision — tied by",
                       "correlation id."]):
    text(990, 366 + i * 16, t, F_ITEM, INK, "lm")

# arrows down to rag/memory + action->audit
arrow(451, 288, 410, 318, dash=True)
arrow(600, 288, 585, 318, dash=True)
arrow(1058, 288, 1058, 318)

# ---- Governance band ----
box(40, 470, 1098, 92)
num_badge(60, 492, 9, BLUE)
text(80, 497, "GOVERNANCE, GUARDRAILS & OBSERVABILITY (cross-cutting)", F_HDR, BLUE, "lm")
row1 = [("✓ Authz guardrails", 40), ("✓ PII screening", 200), ("✓ Audit log", 340),
        ("✓ Human approval", 460), ("✓ Correlation tracing", 620),
        ("✓ Structured logs", 820)]
for t, x in row1:
    text(40 + x, 526, t, F_ITEM, INK, "lm")
row2 = [("✓ Injection defense", 40, INK), ("✓ Idempotency", 200, INK),
        ("✓ Rate limiting", 340, INK), ("◐ Tests/evals (no live metrics)", 460, AMBER),
        ("✗ Cost monitoring", 700, AMBER), ("✗ Live eval / OTel traces", 850, AMBER)]
for t, x, c in row2:
    text(40 + x, 548, t, F_ITEM, c, "lm")

# governance ties
for x in (115, 590, 1058):
    y0 = 440 if x != 115 else 288
    for yy in range(int(y0), 470, 8):
        d.line([x * S, yy * S, x * S, (yy + 4) * S], fill=BLUE, width=S)

# footer note
box(40, 580, 1098, 58, fill=LIGHT, outline=BLUE, width=1)
text(56, 600, "Scope note:", F_NOTE, BLUE, "lm")
text(140, 600, "The LLM is one part. This take-home builds the production-shaped SLICE "
               "— orchestration, auth, parsing, validation, governance — fully.",
     F_NOTE, GREY, "lm")
text(56, 620, "Dashed/amber items (RAG, long-term memory, MCP, cost/eval metrics) are the "
              "assignment's explicit bonuses or out-of-scope, deliberately deferred & documented.",
     F_NOTE, GREY, "lm")

img = img.resize((W, H), Image.LANCZOS)
img.save("architecture-diagram.png", "PNG")
print("saved architecture-diagram.png", img.size)
