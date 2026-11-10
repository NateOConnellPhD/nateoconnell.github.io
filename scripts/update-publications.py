#!/usr/bin/env python3
"""Refresh public OpenAlex metadata. Standard library only; keep old data on failure."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "_data/publications.json"
MAX_RESPONSE = 8 * 1024 * 1024


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value).casefold() if c.isalnum())


def get_json(endpoint, **params):
    key = os.environ.get("OPENALEX_API_KEY", "")
    if key:
        params["api_key"] = key
    url = "https://api.openalex.org/" + endpoint + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "nateoconnell.com publication updater"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as error:
        # Do not print the URL: it may contain an API key.
        raise RuntimeError("OpenAlex returned HTTP %s; existing data were kept. Check API access/quota." % error.code) from None
    except urllib.error.URLError:
        raise RuntimeError("Cannot reach OpenAlex; existing data were kept.") from None
    if len(body) > MAX_RESPONSE:
        raise ValueError("OpenAlex response exceeded the size limit.")
    return json.loads(body)


def author_id(config):
    """Require the same named author on three known publications, not a name search."""
    names = {normalized(name) for name in config["author_names"]}
    candidates = None
    for doi in config["identity_dois"]:
        data = get_json("works", filter="doi:" + doi, select="id,authorships", per_page=10)
        matches = {
            a["author"]["id"]
            for work in data["results"] for a in work["authorships"]
            if normalized(a["author"].get("display_name", "")) in names
        }
        candidates = matches if candidates is None else candidates & matches
    if not candidates or len(candidates) != 1:
        raise ValueError("Could not verify one author across the known papers; existing data were kept.")
    result = candidates.pop()
    if not re.fullmatch(r"https://openalex.org/A\d+", result):
        raise ValueError("Invalid OpenAlex author ID.")
    return result


def fetch_works(author):
    records = {}
    expected = None
    for page in range(1, 21):
        data = get_json("works", filter="authorships.author.id:" + author.rsplit("/", 1)[-1],
                        select="id,doi,title,publication_date,publication_year,cited_by_count,authorships,primary_location,type",
                        sort="publication_date:desc", per_page=100, page=page)
        count = data["meta"]["count"]
        if expected is None:
            expected = count
        if count != expected or not isinstance(count, int) or not 1 <= count <= 2000:
            raise ValueError("Unexpected or changing result count; existing data were kept.")
        batch = data["results"]
        if not batch:
            raise ValueError("Incomplete OpenAlex response; existing data were kept.")
        for work in batch:
            if author not in {a["author"]["id"] for a in work["authorships"]}:
                raise ValueError("A returned publication does not belong to the verified author.")
            records[work["id"]] = work
        if len(records) == expected:
            return list(records.values())
    raise ValueError("Incomplete publication list; existing data were kept.")


def publication(work):
    title = work["title"]
    ident = work["id"]
    count = work["cited_by_count"]
    date = work["publication_date"]
    dt.date.fromisoformat(date)
    if not isinstance(title, str) or not title.strip() or not re.fullmatch(r"https://openalex.org/W\d+", ident):
        raise ValueError("Invalid publication metadata.")
    if type(count) is not int or count < 0:
        raise ValueError("Invalid citation count.")
    doi = work.get("doi") or ""
    if not doi.startswith("https://doi.org/"):
        doi = ""
    source = (work.get("primary_location") or {}).get("source") or {}
    return {"id": ident, "title": title.strip(), "date": date, "year": int(date[:4]),
            "citations": count, "url": doi or ident, "type": work.get("type", ""),
            "authors": ", ".join(a["author"]["display_name"] for a in work["authorships"]),
            "venue": source.get("display_name") or ""}


def refresh():
    config = json.loads((ROOT / "scripts/publications-config.json").read_text())
    author = author_id(config)
    works = fetch_works(author)
    items = []
    for work in works:
        if work["id"] in config["excluded_ids"] or any(
                re.search(pattern, work.get("title") or "", re.I)
                for pattern in config["excluded_title_patterns"]):
            continue
        items.append(publication(work))
    if not items:
        raise ValueError("No displayable publications; existing data were kept.")
    items.sort(key=lambda item: (item["date"], item["citations"], item["id"]), reverse=True)
    snapshot = {"source": "OpenAlex", "author_url": author, "updated": dt.date.today().isoformat(), "items": items}
    # No output is written until every page and record has passed validation.
    OUTPUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Updated %d publications for %s." % (len(items), author))


if __name__ == "__main__":
    try:
        refresh()
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as error:
        print("Publication refresh failed: %s" % error, file=sys.stderr)
        sys.exit(1)
