"""Planner config, Gemini prompts, recommendation logic and fallback."""
import os, re, json
from urllib.parse import quote_plus
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
# Configured model first, then backups if it is unavailable for your key.
MODELS = list(dict.fromkeys([os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip(), "gemini-flash-latest", "gemini-3.6-flash"]))
_client = None


def client():
    global _client
    if _client is None:
        key = os.getenv("GEMINI_API_KEY", "").strip().strip("\"'")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is empty. Check the .env file next to main.py.")
        _client = genai.Client(api_key=key)
    return _client


def call_gemini(contents):
    """Try each model in MODELS until one answers. Returns parsed JSON."""
    last = None
    for m in MODELS:
        try:
            resp = client().models.generate_content(
                model=m, contents=contents,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.4))
            text = re.sub(r"^```(?:json)?|```$", "", resp.text.strip()).strip()
            return json.loads(text)
        except Exception as e:
            print(f"Gemini model {m} failed: {type(e).__name__}: {e}")
            last = e
    raise last


LINKS = {
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "ikea": "https://www.ikea.com/in/en/search/?q={q}",
    "swiggy": "https://www.swiggy.com",
    "zomato": "https://www.zomato.com",
    "oyo": "https://www.oyorooms.com",
}


def F(name, label, type="text", options=None, default=""):
    return dict(name=name, label=label, type=type, options=options or [], default=default)


# split = fallback budget shares: (category, share, platform)
PLANNERS = {
    "home": dict(
        title="Home Interior Planner", blurb="Lights, fans and furniture for each room, within your budget.",
        platforms=["Amazon", "Flipkart", "IKEA"],
        fields=[F("budget", "Total budget (₹)", "number"),
                F("room", "Room", "select", ["Living Room", "Kitchen", "Bedroom", "Dining Room"]),
                F("lights", "Lights needed", "number", default=4), F("fans", "Ceiling fans", "number", default=1),
                F("dining_tables", "Dining tables", "number", default=1),
                F("style", "Style", "select", ["Modern", "Minimal", "Traditional", "Scandinavian"])],
        split=[("Lighting", .20, "IKEA"), ("Ceiling fans", .25, "Amazon"), ("Furniture", .35, "IKEA"), ("Decor", .20, "Flipkart")]),
    "party": dict(
        title="Party Planner", blurb="Catering, venue, decoration and entertainment split for your event.",
        platforms=["Swiggy", "Zomato", "OYO", "Amazon"],
        fields=[F("budget", "Total budget (₹)", "number"), F("guests", "Number of guests", "number", default=20),
                F("event_type", "Event type", "select", ["Birthday", "Corporate", "Wedding", "Anniversary", "Get-together"]),
                F("venue", "Venue details", "text", default="Home")],
        split=[("Catering", .45, "Swiggy"), ("Venue or stay", .20, "OYO"), ("Decoration", .20, "Amazon"), ("Entertainment", .15, "Amazon")]),
    "jewelry": dict(
        title="Jewelry Planner", blurb="Jewelry that suits the occasion and your outfit. Add a photo for colour matching.",
        platforms=["Amazon", "Flipkart"],
        fields=[F("budget", "Total budget (₹)", "number"),
                F("occasion", "Occasion", "select", ["Wedding", "Festival", "Party", "Office", "Casual"]),
                F("style", "Style", "select", ["Traditional", "Modern", "Minimal", "Statement"]),
                F("outfit_image", "Outfit photo (optional)", "file")],
        split=[("Necklace", .40, "Amazon"), ("Earrings", .25, "Flipkart"), ("Bangles", .25, "Amazon"), ("Rings", .10, "Flipkart")]),
}

SCHEMA = '{"summary":"1-2 sentence overview","items":[{"category":"","name":"","platform":"","price":0,"reason":""}],"tips":["",""]}'


def build_prompt(kind, data, has_image):
    p = PLANNERS[kind]
    details = "\n".join(f"- {k}: {str(v)[:200]}" for k, v in data.items())
    extra = " An outfit photo is attached: match its colours and style." if has_image else ""
    return (f"You are PocketSmart AI, a budget planner for shoppers in India. Task: {p['title']}.\nUser inputs:\n{details}\n"
            f"Recommend products or services only from: {', '.join(p['platforms'])}. Prices in INR, realistic. "
            f"The sum of all prices must not exceed the budget.{extra}\nReturn ONLY JSON in this shape: " + SCHEMA)


def num(v):
    try:
        return float(re.sub(r"[^\d.]", "", str(v)) or 0)
    except ValueError:
        return 0.0


def link(platform, name):
    return LINKS.get(platform.lower().strip(), "https://www.google.com/search?q={q}").format(q=quote_plus(name))


def fallback(kind, budget):
    items = [dict(category=c, name=f"Best-value {c.lower()} option", platform=pl, price=round(budget * s),
                  reason="Standard budget share, used because the AI answer was unavailable.")
             for c, s, pl in PLANNERS[kind]["split"]]
    return dict(summary="Here is a standard split of your budget across the main categories.", items=items,
                tips=["Compare prices on each platform before you buy."], source="fallback")


def recommend(kind, data, image=None):
    budget = num(data["budget"])
    try:
        contents = [build_prompt(kind, data, image is not None)] + ([image] if image else [])
        res = call_gemini(contents)
        res["items"] = [i for i in res["items"] if isinstance(i, dict)]
        assert res["items"], "Gemini returned no items"
        res["source"] = "gemini"
    except Exception as e:  # missing key, quota, bad JSON, etc.
        print("Gemini failed, using fallback:", e)
        res = fallback(kind, budget)
        res["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    for i in res["items"]:
        i["price"] = num(i.get("price"))
        i["name"] = str(i.get("name", "Item"))
        i["platform"] = str(i.get("platform", ""))
        i["link"] = link(i["platform"], i["name"])
    res.setdefault("tips", [])
    res["budget"] = budget
    res["total"] = sum(i["price"] for i in res["items"])
    res["remaining"] = budget - res["total"]
    res["pct"] = min(100, round(res["total"] / budget * 100))
    return res
