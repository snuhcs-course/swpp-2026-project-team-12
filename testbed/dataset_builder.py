from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime, time as clock, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image


ROOT = Path(__file__).resolve().parent
OPENVERSE_API = "https://api.openverse.org/v1/images/"
PEXELS_API = "https://api.pexels.com/v1/search"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
SUPPORTED_IMAGE_PROVIDERS = {"curated", "openverse", "pexels", "commons"}
SUPPORTED_AUTHOR_POLICIES = {"round_robin", "thread_owner_weighted"}
SEARCH_FALLBACKS = {
    "lemonade": ("friends drinking lemonade cafe", "people drinking at cafe"),
    "smartphone": ("person taking photo with smartphone", "people smartphone photography"),
    "basil": ("person caring for basil plant at home", "person gardening at home"),
    "pot": ("person holding houseplant pot", "person shopping for houseplant"),
    "camera": ("person using compact camera", "family photography outdoors"),
    "cafe": ("friends together at cafe", "people at cafe table"),
    "dog": ("person with dog outdoors", "family walking dog"),
}
LICENSE_PREFIXES = ("cc0", "cc by", "cc-by", "public domain", "pd", "gfdl")
HUMAN_TERMS = (
    "person", "people", "family", "friend", "woman", "women", "man", "men",
    "girl", "boy", "adult", "mother", "father", "hand", "walking", "cooking",
    "drinking", "playing", "teaching", "photographer",
)
BENCHMARK_ORDER = {
    "basil": ("basil-gift", "basil-distractor", "basil-water", "basil-cooking", "basil-move"),
    "dog": ("dog-weekday", "dog-update", "dog-distractor", "dog-reinforce", "dog-weekend"),
    "cafe": ("cafe-drink", "cafe-distractor", "cafe-pet", "cafe-family", "cafe-walk"),
    "camera": ("camera-return", "camera-again", "camera-distractor", "camera-lesson", "camera-photo"),
}
# Use the application's tree search without initializing Django for dataset builds.
sys.path.insert(0, str(ROOT.parent / "backend"))
from apps.families.utils import find_relationship


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_html(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", value or ""))).strip()


def metadata_value(metadata, key):
    return clean_html(metadata.get(key, {}).get("value", ""))


def family_tree(config):
    return {
        "owner_id": config["owner_username"],
        "people": [{**member, "id": member["username"], "gender": member.get("gender", "unknown")} for member in config["members"]],
        "parents": config.get("parents", []), "partnerships": config.get("partnerships", []),
    }


def validate_config(config, catalog):
    members = config.get("members", [])
    if len(members) < 2:
        raise ValueError("members는 2명 이상이어야 합니다.")
    usernames = [member.get("username") for member in members]
    if any(not value for value in usernames) or len(usernames) != len(set(usernames)):
        raise ValueError("각 구성원의 username은 비어 있지 않고 고유해야 합니다.")
    if config.get("owner_username") not in usernames:
        raise ValueError("owner_username은 members 안의 사용자여야 합니다.")
    if any(type(member.get("generation")) is not int for member in members):
        raise ValueError("구성원의 generation은 정수여야 합니다.")
    for links, keys in ((config.get("parents", []), ("parent_id", "child_id")),
                        (config.get("partnerships", []), ("first_id", "second_id"))):
        for link in links:
            first, second = (link.get(key) for key in keys)
            if first not in usernames or second not in usernames or first == second:
                raise ValueError("가계도 연결에는 서로 다른 구성원의 username이 필요합니다.")
    if any(member.get("gender", "unknown") not in {"female", "male", "unknown"} for member in members):
        raise ValueError("gender는 female, male, unknown 중 하나여야 합니다.")
    thread_ids = config.get("thread_ids") or [thread["id"] for thread in catalog["threads"]]
    known = {thread["id"] for thread in catalog["threads"]}
    if not thread_ids or any(thread_id not in known for thread_id in thread_ids):
        raise ValueError("thread_ids에 알 수 없는 사건 줄기가 있습니다.")
    selected = [thread for thread in catalog["threads"] if thread["id"] in thread_ids]
    count = int(config.get("post_count", 20))
    available = sum(len(thread["events"]) for thread in selected)
    if count < len(selected) * 2 or count > available:
        raise ValueError(f"post_count는 선택한 사건 줄기에서 {len(selected) * 2}~{available}여야 합니다.")
    date.fromisoformat(config["start_date"])
    providers = config.get("image_providers", ["openverse"])
    if not providers or any(provider not in SUPPORTED_IMAGE_PROVIDERS for provider in providers):
        raise ValueError("image_providers에는 curated, openverse, commons 또는 pexels만 사용할 수 있습니다.")
    if config.get("download_images", True) and not config.get("user_agent"):
        raise ValueError("이미지 API 요청에는 식별 가능한 user_agent가 필요합니다.")
    author_policy = config.get("author_policy", {})
    mode = author_policy.get("mode", "round_robin")
    if mode not in SUPPORTED_AUTHOR_POLICIES:
        raise ValueError("author_policy.mode은 round_robin 또는 thread_owner_weighted여야 합니다.")
    if mode == "thread_owner_weighted":
        ratio = float(author_policy.get("primary_author_ratio", 0.6))
        if not 0.5 <= ratio <= 1.0:
            raise ValueError("primary_author_ratio는 0.5~1.0이어야 합니다.")
        if author_policy.get("probe_author", "mixed") not in {"mixed", "primary", "secondary"}:
            raise ValueError("probe_author는 mixed, primary, secondary 중 하나여야 합니다.")
    for thread in selected:
        probes = [event for event in thread["events"] if event.get("kind") == "probe"]
        if len(probes) != 1:
            raise ValueError(f"{thread['id']} 사건 줄기에는 probe가 정확히 하나 있어야 합니다.")
        if not isinstance(probes[0].get("evaluation_question"), str) or not probes[0]["evaluation_question"].strip():
            raise ValueError(f"{probes[0].get('id', thread['id'])}에 evaluation_question이 필요합니다.")
    return selected


def select_events(threads, post_count):
    history, branches, probes = [], [], []
    for thread in threads:
        history.append((thread, next(e for e in thread["events"] if e["kind"] == "core")))
        probes.append((thread, next(e for e in thread["events"] if e["kind"] == "probe")))
        choices = [e for e in thread["events"] if e["kind"] not in {"core", "probe"}]
        order = {event_id: index for index, event_id in enumerate(BENCHMARK_ORDER.get(thread["id"], ())) }
        branches.append(sorted(choices, key=lambda event: order.get(event["id"], len(order))))
    remaining = post_count - len(history) - len(probes)
    depth = 0
    while remaining:
        for thread, choices in zip(threads, branches):
            if remaining and depth < len(choices):
                history.append((thread, choices[depth]))
                remaining -= 1
        depth += 1
    return history + probes


def make_event(event, thread, author, names, occurred, sequence):
    result = {
        "sequence": sequence, "feed_key": event["id"], "thread_id": thread["id"],
        "thread_title": thread["title"], "kind": event["kind"],
        "author_username": author["username"], "author_name": author["name"],
        "created_at": occurred.isoformat(), "caption": event["caption"].format(**names),
        "image_query": event["image_query"],
    }
    labels = (
        "establishes", "invalidates", "distractor_for", "required_memories",
        "optional_memories", "must_filter", "evaluation_question", "prior_dialogue",
    )
    result.update({key: event[key] for key in labels if key in event})
    if "evaluation_question" in result:
        result["evaluation_question"] = result["evaluation_question"].format(**names)
    return result


def owner_weighted_authors(config, threads, chosen):
    """Assign a stable primary author per story while retaining cross-family posts."""
    members = config["members"]
    policy = config.get("author_policy", {})
    ratio = float(policy.get("primary_author_ratio", 0.6))
    probe_policy = policy.get("probe_author", "mixed")
    seed = int(policy.get("seed", 0))
    assignments = {}

    for thread_index, thread in enumerate(threads):
        thread_events = [event for selected_thread, event in chosen if selected_thread["id"] == thread["id"]]
        primary = thread_index % len(members)
        secondary = (primary + 1) % len(members)
        distractor_author = (primary + 2) % len(members)
        primary_target = max(1, min(len(thread_events), round(len(thread_events) * ratio)))

        primary_events = {next(event["id"] for event in thread_events if event["kind"] == "core")}
        probe = next(event for event in thread_events if event["kind"] == "probe")
        probe_is_primary = (
            probe_policy == "primary"
            or (probe_policy == "mixed" and (thread_index + seed) % 2 == 0)
        )
        if probe_is_primary and len(primary_events) < primary_target:
            primary_events.add(probe["id"])

        narrative_events = [
            event for event in thread_events
            if event["kind"] not in {"core", "probe", "distractor"}
        ]
        distractor_events = [event for event in thread_events if event["kind"] == "distractor"]
        for event in narrative_events + distractor_events:
            if len(primary_events) >= primary_target:
                break
            primary_events.add(event["id"])

        for event in thread_events:
            if event["id"] in primary_events:
                author_index = primary
            elif event["kind"] == "distractor":
                author_index = distractor_author
            else:
                author_index = secondary
            assignments[event["id"]] = author_index
    return assignments


def build_plan(config, threads):
    members = config["members"]
    names = {f"m{i}": members[i % len(members)]["name"] for i in range(max(4, len(members)))}
    chosen = select_events(threads, int(config["post_count"]))
    history = [(thread, event) for thread, event in chosen if event["kind"] != "probe"]
    probes = [(thread, event) for thread, event in chosen if event["kind"] == "probe"]
    start = date.fromisoformat(config["start_date"])
    thread_index = {thread["id"]: i for i, thread in enumerate(threads)}
    branch_number = {thread["id"]: 0 for thread in threads}
    author_mode = config.get("author_policy", {}).get("mode", "round_robin")
    weighted_authors = (
        owner_weighted_authors(config, threads, chosen)
        if author_mode == "thread_owner_weighted" else {}
    )
    events = []
    for sequence, (thread, event) in enumerate(history):
        ti, bi = thread_index[thread["id"]], branch_number[thread["id"]]
        author_index = weighted_authors.get(
            event["id"],
            ti % len(members) if event["kind"] == "core" else (ti + bi + 1) % len(members),
        )
        branch_number[thread["id"]] += 1
        day_offset = min(5, sequence * 6 // max(1, len(history)))
        occurred = datetime.combine(start + timedelta(days=day_offset), clock(9 + sequence % 10, sequence * 7 % 60), timezone(timedelta(hours=9)))
        events.append(make_event(event, thread, members[author_index], names, occurred, sequence + 1))
    for offset, (thread, event) in enumerate(probes):
        author_index = weighted_authors.get(
            event["id"], (thread_index[thread["id"]] + 1) % len(members)
        )
        author = members[author_index]
        occurred = datetime.combine(start + timedelta(days=6), clock(10 + offset * 2), timezone(timedelta(hours=9)))
        events.append(make_event(event, thread, author, names, occurred, len(events) + 1))
    return {
        "schema_version": 2, "dataset_name": config["dataset_name"],
        "family": {
            "name": config["family_name"], "invite_code": config["invite_code"],
            "members": members, "tree": family_tree(config),
            "relationship_matrix": {
                viewer["username"]: {author["username"]: find_relationship(family_tree(config), viewer["username"], author["username"]) for author in members}
                for viewer in members
            },
        },
        "credentials": {
            "default_password": config.get("default_password", "Member-Test-2026!"),
            "room_password": config.get("room_password", "Family-Test-2026!"),
        },
        "generation": {
            "start_date": config["start_date"], "days": 7, "post_count": len(events),
            "probe_policy": "seed after Graphiti construction",
            "author_policy": config.get("author_policy", {"mode": "round_robin"}),
        },
        "events": events,
    }


class PhotoCrawler:
    def __init__(self, user_agent, width=1200, delay=0.3):
        self.user_agent = user_agent
        self.width = int(width)
        self.delay = float(delay)
        self.used_pages = set()

    def request_json(self, endpoint, params, headers=None):
        request_headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        request_headers.update(headers or {})
        request = Request(endpoint + "?" + urlencode(params), headers=request_headers)
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"{endpoint} returned HTTP {error.code}: {detail}") from error

    def download_file(self, urls, destination, headers=None):
        last_error = None
        for url in dict.fromkeys(url for url in urls if url):
            try:
                request_headers = {"User-Agent": self.user_agent}
                request_headers.update(headers or {})
                request = Request(url, headers=request_headers)
                with urlopen(request, timeout=45) as response:
                    destination.write_bytes(response.read())
                with Image.open(destination) as source:
                    image = source.convert("RGB")
                    if min(image.size) < 400:
                        raise ValueError("짧은 변이 400px보다 작은 이미지는 제외합니다.")
                    image.thumbnail((1600, 1600))
                    image.save(destination, "JPEG", quality=88)
                time.sleep(self.delay)
                return url
            except Exception as error:
                last_error = error
                destination.unlink(missing_ok=True)
        raise RuntimeError(f"이미지를 내려받지 못했습니다: {last_error}")

    @staticmethod
    def search_queries(query):
        lowered = query.lower()
        required_term = next((term for term in SEARCH_FALLBACKS if term in lowered), None)
        return list(dict.fromkeys([query, *SEARCH_FALLBACKS.get(required_term, ())]))


class OpenverseCrawler(PhotoCrawler):
    def __init__(self, user_agent, width=1200, delay=0.3, source="flickr", licenses=None, api_token=None):
        super().__init__(user_agent, width, delay)
        self.source = source
        self.licenses = licenses or ["cc0", "pdm", "by", "by-sa"]
        self.api_token = api_token

    def candidates(self, query):
        params = {
            "q": query,
            "page_size": 20,
            "category": "photograph",
            "license": ",".join(self.licenses),
            "mature": "false",
            "filter_dead": "true",
            "size": "large,medium",
        }
        if self.source:
            params["source"] = self.source
        headers = {"Authorization": f"Bearer {self.api_token}"} if self.api_token else None
        payload = self.request_json(OPENVERSE_API, params, headers)
        for item in payload.get("results", []):
            image_id = item.get("id")
            if not image_id or image_id in self.used_pages:
                continue
            if item.get("width", 0) and item.get("height", 0) and min(item["width"], item["height"]) < 400:
                continue
            yield item

    def download(self, query, destination, feed_key=None):
        last_error = None
        for search_query in self.search_queries(query):
            for item in self.candidates(search_query):
                try:
                    downloaded_url = self.download_file([item.get("thumbnail"), item.get("url")], destination)
                    self.used_pages.add(item["id"])
                    license_name = item.get("license", "").upper()
                    if item.get("license_version"):
                        license_name += f" {item['license_version']}"
                    return {
                        "provider": "Openverse", "provider_source": item.get("source"),
                        "query": query, "matched_query": search_query,
                        "title": item.get("title"), "page_id": item["id"],
                        "artist": item.get("creator"), "artist_url": item.get("creator_url"),
                        "license": license_name, "license_url": item.get("license_url"),
                        "credit": item.get("attribution"),
                        "description_url": item.get("foreign_landing_url"),
                        "original_url": item.get("url"), "download_url": downloaded_url,
                    }
                except Exception as error:
                    last_error = error
                    destination.unlink(missing_ok=True)
        raise RuntimeError(f"Openverse에서 '{query}' 사진을 내려받지 못했습니다. {last_error}")


class CommonsCrawler(PhotoCrawler):
    def candidates(self, query):
        payload = self.request_json(COMMONS_API, {
            "action": "query", "format": "json", "formatversion": 2,
            "generator": "search",
            "gsrsearch": query + " filetype:bitmap -incategory:Paintings -incategory:Drawings",
            "gsrnamespace": 6, "gsrlimit": 30,
            "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata", "iiurlwidth": self.width,
            "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|Credit|ImageDescription|Categories",
            "iiextmetadatalanguage": "en",
        })
        for page in payload.get("query", {}).get("pages", []):
            info = (page.get("imageinfo") or [{}])[0]
            metadata = info.get("extmetadata", {})
            license_name = metadata_value(metadata, "LicenseShortName")
            searchable = " ".join((
                page.get("title", ""),
                metadata_value(metadata, "ImageDescription"),
                metadata_value(metadata, "Categories"),
            )).lower()
            if page.get("pageid") in self.used_pages:
                continue
            if not any(term in searchable for term in HUMAN_TERMS):
                continue
            if any(term in searchable for term in ("painting", "drawing", "illustration", "engraving", "printmaking")):
                continue
            if info.get("mime") not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            if license_name.lower().startswith(LICENSE_PREFIXES):
                yield page, info, metadata, license_name

    def download(self, query, destination, feed_key=None):
        last_error = None
        for search_query in self.search_queries(query):
            for page, info, metadata, license_name in self.candidates(search_query):
                try:
                    downloaded_url = self.download_file([info.get("thumburl"), info.get("url")], destination)
                    self.used_pages.add(page["pageid"])
                    return {
                        "provider": "Wikimedia Commons", "query": query,
                        "matched_query": search_query, "title": page.get("title"),
                        "page_id": page["pageid"], "artist": metadata_value(metadata, "Artist"),
                        "license": license_name, "license_url": metadata_value(metadata, "LicenseUrl"),
                        "credit": metadata_value(metadata, "Credit"),
                        "description": metadata_value(metadata, "ImageDescription"),
                        "description_url": info.get("descriptionurl"), "original_url": info.get("url"),
                        "download_url": downloaded_url,
                    }
                except Exception as error:
                    last_error = error
                    destination.unlink(missing_ok=True)
        raise RuntimeError(f"Wikimedia Commons에서 '{query}' 인물 사진을 내려받지 못했습니다. {last_error}")


class PexelsCrawler(PhotoCrawler):
    def __init__(self, user_agent, api_key, width=1200, delay=0.3):
        super().__init__(user_agent, width, delay)
        self.api_key = api_key

    def candidates(self, query):
        payload = self.request_json(
            PEXELS_API,
            {"query": query, "per_page": 30, "orientation": "landscape"},
            {"Authorization": self.api_key},
        )
        for item in payload.get("photos", []):
            if item.get("id") not in self.used_pages:
                yield item

    def download(self, query, destination, feed_key=None):
        last_error = None
        for search_query in self.search_queries(query):
            for item in self.candidates(search_query):
                try:
                    sources = item.get("src", {})
                    downloaded_url = self.download_file(
                        [sources.get("large2x"), sources.get("large"), sources.get("original")], destination
                    )
                    self.used_pages.add(item["id"])
                    return {
                        "provider": "Pexels", "query": query, "matched_query": search_query,
                        "title": item.get("alt"), "page_id": item["id"],
                        "artist": item.get("photographer"), "artist_url": item.get("photographer_url"),
                        "license": "Pexels License", "license_url": "https://www.pexels.com/license/",
                        "credit": f"Photo by {item.get('photographer', 'unknown')} on Pexels",
                        "description_url": item.get("url"), "original_url": sources.get("original"),
                        "download_url": downloaded_url,
                    }
                except Exception as error:
                    last_error = error
                    destination.unlink(missing_ok=True)
        raise RuntimeError(f"Pexels에서 '{query}' 사진을 내려받지 못했습니다. {last_error}")


class CompositeCrawler:
    def __init__(self, crawlers):
        self.crawlers = crawlers
        self.disabled = set()

    def download(self, query, destination, feed_key=None):
        errors = []
        for index, crawler in enumerate(self.crawlers):
            if index in self.disabled:
                continue
            try:
                return crawler.download(query, destination, feed_key)
            except Exception as error:
                message = str(error)
                errors.append(message)
                if "HTTP 401" in message or "HTTP 403" in message or "challenges.cloudflare.com" in message:
                    self.disabled.add(index)
                destination.unlink(missing_ok=True)
        raise RuntimeError(" / ".join(errors))


class CuratedCrawler(PhotoCrawler):
    def __init__(self, user_agent, sources_path, width=1200, delay=0.3):
        super().__init__(user_agent, width, delay)
        self.sources = {item["feed_key"]: item for item in read_json(sources_path)}

    def download(self, query, destination, feed_key=None):
        if feed_key not in self.sources:
            raise RuntimeError(f"curated source가 없는 feed입니다: {feed_key}")
        source = self.sources[feed_key]
        downloaded_url = self.download_file([source["image_url"]], destination)
        return {
            "provider": "Pexels (manually curated)", "query": query,
            "matched_query": "manual web selection", "title": source["title"],
            "page_id": source["page_id"], "artist": source["artist"],
            "license": "Pexels License", "license_url": "https://www.pexels.com/license/",
            "credit": f"Photo by {source['artist']} on Pexels",
            "description_url": source["page_url"], "original_url": source["image_url"],
            "download_url": downloaded_url,
        }


def make_crawler(config):
    common = (
        config["user_agent"],
        config.get("image_width", 1200),
        config.get("request_delay_seconds", 0.3),
    )
    crawlers = []
    for provider in config.get("image_providers", ["openverse"]):
        if provider == "curated":
            sources_path = Path(config.get("curated_sources", ROOT / "input" / "curated_sources.example.json"))
            if not sources_path.is_absolute():
                sources_path = ROOT / sources_path
            crawlers.append(CuratedCrawler(common[0], sources_path, common[1], common[2]))
        elif provider == "openverse":
            crawlers.append(OpenverseCrawler(
                *common,
                source=config.get("openverse_source", "flickr"),
                licenses=config.get("openverse_licenses"),
                api_token=os.getenv(config.get("openverse_api_token_env", "OPENVERSE_API_TOKEN")),
            ))
        elif provider == "commons":
            crawlers.append(CommonsCrawler(*common))
        elif provider == "pexels":
            api_key = os.getenv(config.get("pexels_api_key_env", "PEXELS_API_KEY"))
            if api_key:
                crawlers.append(PexelsCrawler(common[0], api_key, common[1], common[2]))
    if not crawlers:
        raise ValueError("활성화된 이미지 공급자가 없습니다. Pexels를 사용하려면 API 키 환경변수를 설정하세요.")
    return CompositeCrawler(crawlers)


def generate(config_path, output_path=None, skip_images=False):
    config_path = Path(config_path).resolve()
    config = read_json(config_path)
    catalog_path = Path(config.get("event_catalog", ROOT / "input" / "event_catalog.example.json"))
    if not catalog_path.is_absolute():
        catalog_path = ROOT / catalog_path
    catalog = read_json(catalog_path)
    threads = validate_config(config, catalog)
    plan = build_plan(config, threads)
    output = Path(output_path or ROOT / "output" / config["dataset_name"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    previous_images = set()
    if manifest_path.exists():
        previous_images = {
            (output / event["image_path"]).resolve()
            for event in read_json(manifest_path).get("events", []) if event.get("image_path")
        }
    # The event plan survives even when a later image request fails.
    write_json(output / "dataset_plan.json", plan)
    crawler = None
    if config.get("download_images", True) and not skip_images:
        crawler = make_crawler(config)
        (output / "images").mkdir(exist_ok=True)
    for event in plan["events"]:
        event["image_path"] = None
        event["image_source"] = None
    if crawler:
        image_root = (output / "images").resolve()
        with tempfile.TemporaryDirectory(prefix=".images-", dir=output) as staging_directory:
            staging = Path(staging_directory)
            for event in plan["events"]:
                filename = f"{event['sequence']:02d}_{event['feed_key']}.jpg"
                staged_image = staging / filename
                event["image_source"] = crawler.download(event["image_query"], staged_image, event["feed_key"])
                event["image_path"] = f"images/{filename}"
            for event in plan["events"]:
                (staging / Path(event["image_path"]).name).replace(output / event["image_path"])
        current_images = {(output / event["image_path"]).resolve() for event in plan["events"]}
        for stale in previous_images - current_images:
            if stale.parent == image_root and stale.is_file():
                stale.unlink()
    write_json(manifest_path, plan)
    return output, plan


def main():
    parser = argparse.ArgumentParser(description="Graphiti 가족 피드 벤치마크를 생성합니다.")
    parser.add_argument("--config", default=str(ROOT / "input" / "config.example.json"))
    parser.add_argument("--output")
    parser.add_argument("--skip-images", action="store_true", help="사건과 정답표만 생성합니다.")
    args = parser.parse_args()
    output, plan = generate(args.config, args.output, args.skip_images)
    print(f"{len(plan['events'])}개 피드 계획 생성: {output}")


if __name__ == "__main__":
    main()
