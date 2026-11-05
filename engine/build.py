#!/usr/bin/env python3
"""
AutomateStack Storefront Generator
Standard library only. Builds dist/index.html, dist/sitemap.xml, dist/robots.txt, dist/products.json
from products.json catalog.
"""

import html
import json
import os
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PRODUCTS_FILE = BASE_DIR / "products.json"
DIST_DIR = BASE_DIR / "dist"
BASE_URL = "https://juexing1225.github.io/automate-stack"

def load_catalog(path=PRODUCTS_FILE):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def render_html(catalog):
    brand = catalog.get("brand", "AutomateStack")
    tagline = catalog.get("tagline", "Production-ready AI automation kits for people who ship alone.")
    subhead = catalog.get("subhead", "Buy once. Import. Ship the same afternoon. No account, no subscription, no support queue.")
    year = catalog.get("year", 2026)
    products = catalog.get("products", [])
    inside_common = catalog.get("inside_common", [])
    steps = catalog.get("steps", [])
    faqs = catalog.get("faq", [])

    # Build Product Cards
    cards_html = []
    ld_products = []
    for p in products:
        title = html.escape(p.get("title", ""))
        subtitle = html.escape(p.get("subtitle", ""))
        price = p.get("price", 0)
        checkout = p.get("checkout", "")
        note = html.escape(p.get("note", ""))
        slug = p.get("slug", "")

        bullets_li = "".join(f"<li>{html.escape(b)}</li>" for b in p.get("bullets", []))

        if checkout:
            cta_button = f'<a class="buy" href="{html.escape(checkout)}">Get the kit</a>'
        else:
            cta_button = '<a class="buy ghost" href="#checkout">Available soon</a>'

        card = f'''<div class="card">
<h3>{title} <span class="price">${price}</span></h3>
<p>{subtitle}</p>
<ul>{bullets_li}</ul>
{cta_button}
<p class="muted" style="margin-top:12px">{note}</p>
</div>'''
        cards_html.append(card)

        ld_products.append({
            "@type": "Product",
            "name": p.get("title", ""),
            "description": p.get("subtitle", ""),
            "url": f"{BASE_URL}/p/{slug}.html",
            "offers": {
                "@type": "Offer",
                "price": str(price),
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock"
            }
        })

    cards_joined = "".join(cards_html)
    common_li = "".join(f"<li>{html.escape(item)}</li>" for item in inside_common)
    steps_li = "".join(f"<li><b>{html.escape(s[0])}</b>{html.escape(s[1])}</li>" for s in steps)
    faq_details = "".join(f"<details><summary>{html.escape(q[0])}</summary><p>{html.escape(q[1])}</p></details>" for q in faqs)

    ld_json = json.dumps({
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": ld_products
    }, ensure_ascii=False)

    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(brand)} — AI automation kits</title>
<meta name="description" content="{html.escape(subhead)}">
<link rel="canonical" href="{BASE_URL}/">
<meta property="og:type" content="website">
<meta property="og:title" content="{html.escape(brand)} — AI automation kits">
<meta property="og:description" content="{html.escape(subhead)}">
<meta property="og:url" content="{BASE_URL}/">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{html.escape(brand)} — AI automation kits">
<meta name="twitter:description" content="{html.escape(subhead)}">
<style>
:root{{--bg:#0b0b0f;--fg:#f4f4f5;--muted:#9a9aa5;--line:#26262e;--acc:#c8ff3d}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
-webkit-font-smoothing:antialiased}}
.wrap{{max-width:820px;margin:0 auto;padding:0 24px}}
header{{padding:72px 0 44px;border-bottom:1px solid var(--line)}}
h1{{font-size:44px;line-height:1.12;margin:0 0 18px;letter-spacing:-.025em}}
h2{{font-size:22px;margin:56px 0 8px;letter-spacing:-.01em}}
h3{{font-size:19px;margin:0 0 6px;letter-spacing:-.01em}}
p.lead{{color:var(--muted);font-size:19px;margin:0}}
.tag{{display:inline-block;font-size:12px;letter-spacing:.12em;text-transform:uppercase;
color:var(--acc);border:1px solid var(--line);padding:6px 10px;border-radius:999px;margin-bottom:24px}}
.card{{border:1px solid var(--line);border-radius:14px;padding:26px;margin:16px 0;transition:border-color .2s}}
.card:hover{{border-color:#3a3a45}}
.price{{color:var(--acc);font-weight:600;font-size:15px;white-space:nowrap}}
.card p{{margin:10px 0 0;color:var(--muted);font-size:15px}}
ul{{padding-left:20px;margin:14px 0 0}}
li{{margin:7px 0;color:#d4d4d8;font-size:15px}}
.buy{{display:inline-block;margin-top:20px;background:var(--acc);color:#0b0b0f;
font-weight:700;padding:12px 22px;border-radius:10px;text-decoration:none}}
.buy.ghost{{background:transparent;color:var(--acc);border:1px solid var(--line);font-weight:600}}
.muted{{color:var(--muted);font-size:14px}}
.inside{{border:1px solid var(--line);border-radius:14px;padding:22px 26px;margin:16px 0;background:#0e0e13}}
.inside code{{display:block;font:13px/1.9 ui-monospace,SFMono-Regular,Menlo,monospace;
color:#c7c7d1;padding:2px 0}}
.steps{{counter-reset:s;list-style:none;padding:0;margin:16px 0}}
.steps li{{counter-increment:s;position:relative;padding-left:44px;margin:14px 0;color:#d4d4d8}}
.steps li::before{{content:counter(s);position:absolute;left:0;top:1px;width:26px;height:26px;
border-radius:50%;border:1px solid var(--line);color:var(--acc);font-size:13px;font-weight:700;
display:flex;align-items:center;justify-content:center}}
.steps b{{color:var(--fg);display:block;font-size:15px}}
details{{border-top:1px solid var(--line);padding:16px 0}}
details summary{{cursor:pointer;font-weight:600;font-size:15px;list-style:none}}
details summary::-webkit-details-marker{{display:none}}
details summary::before{{content:"+ ";color:var(--acc);font-weight:700}}
details[open] summary::before{{content:"\\2212 "}}
details p{{color:var(--muted);font-size:15px;margin:10px 0 0}}
.note{{margin-top:44px;padding-top:24px;border-top:1px solid var(--line);
color:var(--muted);font-size:14px}}
footer{{padding:48px 0;color:var(--muted);font-size:13px;border-top:1px solid var(--line);margin-top:56px}}
a.plain{{color:var(--acc);text-decoration:none}}
a.plain:hover{{text-decoration:underline}}
</style></head>
<body><div class="wrap"><header>
<div class="tag">Instant download</div>
<h1>{html.escape(tagline)}</h1>
<p class="lead">{html.escape(subhead)}</p></header>

<h2>Kits</h2>
{cards_joined}
<div class="note" id="checkout">
<a class="plain" href="#faq">How delivery works</a> — files are delivered instantly by the
checkout provider. No account required on this site.</div>

<h2>What is in every kit</h2>
<ul>{common_li}</ul>

<h2>How you go live</h2>
<ol class="steps">{steps_li}</ol>

<h2>Questions</h2>
{faq_details}

<footer>&copy; {year} {html.escape(brand)}. <a class="plain" href="sitemap.xml">Sitemap</a>.
Built and maintained by an automated pipeline.</footer>
<script type="application/ld+json">{ld_json}</script></div></body></html>
'''

def render_sitemap(catalog):
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{BASE_URL}/</loc></url>
</urlset>
'''

def render_robots():
    return f'''User-agent: *
Allow: /
Sitemap: {BASE_URL}/sitemap.xml
'''

def build():
    catalog = load_catalog()
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 1. index.html
    html_content = render_html(catalog)
    with open(DIST_DIR / "index.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    # Also keep root index.html synchronized for root Pages deployment
    with open(BASE_DIR / "index.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    # 2. sitemap.xml
    sitemap_content = render_sitemap(catalog)
    with open(DIST_DIR / "sitemap.xml", "w", encoding="utf-8") as f:
        f.write(sitemap_content)
    with open(BASE_DIR / "sitemap.xml", "w", encoding="utf-8") as f:
        f.write(sitemap_content)

    # 3. robots.txt
    robots_content = render_robots()
    with open(DIST_DIR / "robots.txt", "w", encoding="utf-8") as f:
        f.write(robots_content)
    with open(BASE_DIR / "robots.txt", "w", encoding="utf-8") as f:
        f.write(robots_content)

    # 4. products.json
    shutil.copyfile(PRODUCTS_FILE, DIST_DIR / "products.json")

    print(f"✓ Successfully built storefront in {DIST_DIR} and updated root static files.")

if __name__ == "__main__":
    build()
