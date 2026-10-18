from urllib.parse import urljoin, urlparse
import psutil
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from pathlib import Path
from fastapi import Query
import base64
import re
import difflib
import hashlib
import secrets
from ai.pc_apps import discover_apps, launch_app
from datetime import datetime, timezone
app = FastAPI(
    title="VANTEX API",
    description="VANTEX Website QA Engine",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class WebsiteTestRequest(BaseModel):
    url: HttpUrl


@app.get("/")
def home():
    return {
        "name": "VANTEX",
        "message": "Backend is running",
        "version": "0.2.0",
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "vantex-api"}

@app.get("/api/agent/system")
def get_system_status():
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return {
        "agent": "VANTEX Local Agent",
        "connected": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "ram_percent": memory.percent,
            "ram_total_gb": round(memory.total / (1024 ** 3), 2),
            "ram_available_gb": round(memory.available / (1024 ** 3), 2),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024 ** 3), 2),
        },
    }


@app.post("/api/qa/test")
async def test_website(request: WebsiteTestRequest):
    from collections import deque
    from urllib.parse import urldefrag, urlunparse
    import xml.etree.ElementTree as ET
    import re

    start_url = str(request.url)
    parsed_start = urlparse(start_url)

    if parsed_start.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail="Only HTTP and HTTPS URLs are supported."
        )

    def normalize_url(raw_url):
        parsed = urlparse(raw_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None
        parsed = parsed._replace(fragment="")
        return urlunparse(parsed)

    def same_origin(first, second):
        a, b = urlparse(first), urlparse(second)
        return (
            a.scheme.lower() == b.scheme.lower()
            and (a.hostname or "").lower() == (b.hostname or "").lower()
            and (a.port or (443 if a.scheme == "https" else 80))
            == (b.port or (443 if b.scheme == "https" else 80))
        )

    start_url = normalize_url(start_url)
    queue = deque([(start_url, 0)])
    queued = {start_url}
    visited = set()
    pages = []
    external_links = {}
    max_pages = 50
    max_depth = 5
    max_links_per_page = 100
    max_external_checks = 50

    discovered_urls = {start_url}

    async def discover_sitemap_urls(request_context, base_url):
        """Discover same-origin URLs through robots.txt and XML sitemaps."""
        origin = urlparse(base_url)
        robots_url = f"{origin.scheme}://{origin.netloc}/robots.txt"
        sitemap_queue = []
        found_pages = set()

        try:
            response = await request_context.get(
                robots_url, timeout=7000, fail_on_status_code=False
            )
            if response.status < 400:
                robots_text = await response.text()
                for line in robots_text.splitlines():
                    key, separator, value = line.partition(":")
                    if separator and key.strip().lower() == "sitemap":
                        candidate = normalize_url(value.strip())
                        if candidate and same_origin(base_url, candidate):
                            sitemap_queue.append(candidate)
        except Exception:
            pass

        # Standard fallback for sites that do not declare a sitemap in robots.txt.
        fallback = normalize_url(urljoin(base_url, "/sitemap.xml"))
        if fallback and fallback not in sitemap_queue:
            sitemap_queue.append(fallback)

        seen_sitemaps = set()
        max_sitemaps = 10

        while sitemap_queue and len(seen_sitemaps) < max_sitemaps:
            sitemap_url = sitemap_queue.pop(0)
            if sitemap_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap_url)

            try:
                response = await request_context.get(
                    sitemap_url, timeout=7000, fail_on_status_code=False
                )
                if response.status >= 400:
                    continue

                body = await response.text()
                if len(body) > 5_000_000:
                    continue

                root = ET.fromstring(body)
                for element in root.iter():
                    if element.tag.rsplit("}", 1)[-1].lower() != "loc":
                        continue

                    value = (element.text or "").strip()
                    candidate = normalize_url(urljoin(sitemap_url, value))
                    if not candidate or not same_origin(base_url, candidate):
                        continue

                    # Sitemap indexes contain sitemap URLs; ordinary sitemaps
                    # contain page URLs. Both are handled without fixed routes.
                    if candidate.lower().endswith(".xml"):
                        if candidate not in seen_sitemaps:
                            sitemap_queue.append(candidate)
                    else:
                        found_pages.add(candidate)

                    if len(found_pages) >= 2000:
                        return found_pages
            except Exception:
                continue

        return found_pages

    async def discover_bundle_routes(page, request_context, base_url):
        """Discover static SPA route candidates from same-origin JS bundles."""
        candidates = set()

        try:
            script_urls = await page.locator("script[src]").evaluate_all(
                "els => els.map(el => el.src).filter(Boolean)"
            )
        except Exception:
            return candidates

        for script_url in script_urls[:20]:
            normalized_script = normalize_url(script_url)
            if not normalized_script or not same_origin(base_url, normalized_script):
                continue

            try:
                response = await request_context.get(
                    normalized_script, timeout=10000, fail_on_status_code=False
                )
                if response.status >= 400:
                    continue

                body = await response.text()
                if len(body) > 5_000_000:
                    continue

                patterns = [
                    r'path\s*:\s*`([^`]+)`',
                    r'path\s*:\s*"([^"]+)"',
                    r"path\s*:\s*'([^']+)'",
                ]

                for pattern in patterns:
                    for match in re.finditer(pattern, body):
                        route = match.group(1).strip()

                        # Keep only literal absolute route paths.
                        if (
                            not route.startswith("/")
                            or route.startswith("//")
                            or len(route) > 150
                            or any(c in route for c in (" ", "\n", "<", ">"))
                            or any(c in route for c in (":", "*", "{", "}"))
                        ):
                            continue

                        candidate = normalize_url(urljoin(base_url, route))
                        if candidate and same_origin(base_url, candidate):
                            candidates.add(candidate)

            except Exception:
                continue

        return candidates

    browser = None

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(ignore_https_errors=False)

            sitemap_urls = await discover_sitemap_urls(
                context.request, start_url
            )
            discovered_urls.update(sitemap_urls)

            for sitemap_url in sorted(sitemap_urls):
                if len(queued) >= max_pages:
                    break
                if sitemap_url not in queued:
                    queued.add(sitemap_url)
                    queue.append((sitemap_url, 1))

            while queue and len(visited) < max_pages:
                current_url, depth = queue.popleft()

                if current_url in visited:
                    continue

                visited.add(current_url)
                page_result = {
                    "url": current_url,
                    "depth": depth,
                    "title": None,
                    "final_url": None,
                    "http_status": None,
                    "success": False,
                    "console_errors": [],
                    "page_errors": [],
                    "failed_requests": [],
                    "broken_links": [],
                    "links_checked": 0,
                    "responsive_checks": [],
                    "ui_audit": [],
                    "summary": {},
                }

                page = await context.new_page()
                page.set_default_timeout(10000)

                page.on(
                    "console",
                    lambda message, result=page_result:
                        result["console_errors"].append(message.text)
                        if message.type == "error"
                        and len(result["console_errors"]) < 30 else None
                )
                page.on(
                    "pageerror",
                    lambda error, result=page_result:
                        result["page_errors"].append(str(error)[:300])
                        if len(result["page_errors"]) < 30 else None
                )
                page.on(
                    "requestfailed",
                    lambda req, result=page_result:
                        result["failed_requests"].append({
                            "url": req.url,
                            "error": req.failure,
                        })
                        if len(result["failed_requests"]) < 30 else None
                )

                discovered_internal = set()

                try:
                    try:
                        response = await page.goto(
                            current_url,
                            wait_until="domcontentloaded",
                            timeout=20000,
                        )
                    except PlaywrightTimeoutError:
                        page_result["navigation_error"] = "Navigation timed out."
                        response = None
                    except Exception as error:
                        page_result["navigation_error"] = str(error)[:300]
                        response = None

                    page_result["final_url"] = page.url
                    page_result["title"] = await page.title()
                    page_result["http_status"] = (
                        response.status if response else None
                    )

                    requested_url = normalize_url(current_url)
                    final_url = normalize_url(page.url)
                    redirected = bool(
                        requested_url and final_url and requested_url != final_url
                    )

                    # A redirected route is authentication-required only when the
                    # destination looks like a login form. The login page itself
                    # is not classified as protected just because it has a password.
                    has_password_field = await page.locator(
                        'input[type="password"]'
                    ).count() > 0
                    has_login_field = await page.locator(
                        'input[type="email"], input[autocomplete="username"], '
                        'input[name*="email" i], input[name*="user" i]'
                    ).count() > 0

                    page_result["auth_required"] = bool(
                        redirected and has_password_field and has_login_field
                    )
                    page_result["status"] = (
                        "AUTH_REQUIRED" if page_result["auth_required"]
                        else "TESTED"
                    )
                    page_result["success"] = bool(
                        response
                        and response.status < 400
                        and not page_result["auth_required"]
                    )

                    # Discover links on this page. Only same-origin links enter
                    # the crawl queue; external links are checked separately.
                    raw_links = await page.locator("a[href]").evaluate_all(
                        """els => els.map(a => a.href).filter(Boolean)"""
                    )

                    for raw_link in raw_links[:max_links_per_page]:
                        normalized = normalize_url(raw_link)
                        if not normalized:
                            continue

                        if same_origin(start_url, normalized):
                            discovered_urls.add(normalized)
                            if normalized not in visited:
                                discovered_internal.add(normalized)
                        else:
                            external_links.setdefault(normalized, None)

                    page_result["links_checked"] = min(
                        len(raw_links), max_links_per_page
                    )

                    # Discover static SPA route candidates from same-origin bundles.
                    # These are candidates, not proof that a page is accessible.
                    bundle_routes = await discover_bundle_routes(
                        page, context.request, start_url
                    )
                    discovered_urls.update(bundle_routes)
                    discovered_internal.update(bundle_routes)

                    # Responsive horizontal-overflow checks.
                    viewports = [
                        {"name": "desktop", "width": 1440, "height": 900},
                        {"name": "tablet", "width": 768, "height": 1024},
                        {"name": "mobile", "width": 390, "height": 844},
                    ]

                    for viewport in viewports:
                        await page.set_viewport_size({
                            "width": viewport["width"],
                            "height": viewport["height"],
                        })
                        await page.wait_for_timeout(250)

                        ui_audit = await page.evaluate("""() => {
                            const issues = [];
                            const seen = new Set();

                            function add(category, severity, el, evidence,
                                         recommendation, confidence = "high") {
                                const key = category + "|" + selector(el) + "|" + evidence;
                                if (seen.has(key) || issues.length >= 60) return;
                                seen.add(key);

                                const text = (el.innerText || el.value || "")
                                    .replace(/\s+/g, " ").trim().slice(0, 100);

                                issues.push({
                                    category,
                                    severity,
                                    element: selector(el),
                                    element_text: text,
                                    evidence,
                                    recommendation,
                                    confidence
                                });
                            }

                            function visible(el) {
                                const r = el.getBoundingClientRect();
                                const s = getComputedStyle(el);
                                return r.width > 0 && r.height > 0 &&
                                    s.display !== "none" &&
                                    s.visibility !== "hidden" &&
                                    Number(s.opacity) > 0;
                            }

                            function selector(el) {
                                const tag = el.tagName.toLowerCase();
                                if (el.id) return tag + "#" + el.id;

                                const classes = typeof el.className === "string"
                                    ? el.className.trim().split(/\s+/)
                                        .filter(Boolean).slice(0, 2)
                                    : [];

                                let result = tag + classes.map(c => "." + c).join("");

                                if (!classes.length && el.parentElement) {
                                    const siblings = [...el.parentElement.children]
                                        .filter(n => n.tagName === el.tagName);
                                    if (siblings.length > 1) {
                                        result += ":nth-of-type(" +
                                            (siblings.indexOf(el) + 1) + ")";
                                    }
                                }

                                return result.slice(0, 160);
                            }

                            function accessibleName(el) {
                                const labelledBy = el.getAttribute("aria-labelledby");
                                const referencedText = labelledBy
                                    ? labelledBy.split(/\s+/)
                                        .map(id => document.getElementById(id)?.innerText || "")
                                        .join(" ")
                                    : "";

                                const label = el.labels
                                    ? [...el.labels].map(x => x.innerText).join(" ")
                                    : "";

                                return (
                                    el.getAttribute("aria-label") ||
                                    referencedText ||
                                    label ||
                                    el.getAttribute("title") ||
                                    el.innerText ||
                                    el.value ||
                                    el.querySelector("img[alt]")?.getAttribute("alt") ||
                                    ""
                                ).trim();
                            }

                            function rgb(value) {
                                if (!value || value === "transparent") return null;
                                const m = value.match(
                                    /rgba?\(\s*(\d+(?:\.\d+)?)\s*[, ]\s*(\d+(?:\.\d+)?)\s*[, ]\s*(\d+(?:\.\d+)?)(?:\s*[,/]\s*([\d.]+))?\s*\)/
                                );
                                if (!m) return null;

                                const alpha = m[4] === undefined ? 1 : Number(m[4]);
                                if (alpha < 0.999) return null;

                                return [+m[1], +m[2], +m[3]];
                            }

                            function luminance(color) {
                                const values = color.map(v => {
                                    v /= 255;
                                    return v <= 0.04045
                                        ? v / 12.92
                                        : Math.pow((v + 0.055) / 1.055, 2.4);
                                });

                                return 0.2126 * values[0] +
                                    0.7152 * values[1] +
                                    0.0722 * values[2];
                            }

                            function solidBackground(el) {
                                let node = el;

                                while (node && node.nodeType === 1) {
                                    const style = getComputedStyle(node);

                                    // Do not guess a color when gradients or background
                                    // images may affect the actual rendered background.
                                    if (style.backgroundImage &&
                                        style.backgroundImage !== "none") {
                                        return null;
                                    }

                                    const value = style.backgroundColor;
                                    const color = rgb(value);

                                    if (color) return color;

                                    if (value && value.startsWith("rgba(")) {
                                        const alpha = Number(
                                            value.match(/,\s*([\d.]+)\s*\)$/)?.[1] ?? 0
                                        );
                                        if (alpha > 0) return null;
                                    }

                                    node = node.parentElement;
                                }

                                return [255, 255, 255];
                            }

                            const elements = [...document.querySelectorAll("body *")]
                                .filter(visible);

                            for (const el of elements) {
                                const tag = el.tagName.toLowerCase();
                                const style = getComputedStyle(el);
                                const text = (el.innerText || "").trim();
                                const fontSize = parseFloat(style.fontSize);

                                // Only flag very small, non-trivial text. Tiny decorative
                                // separators and short metadata labels are often intentional.
                                if (
                                    el.children.length === 0 &&
                                    text.length >= 24 &&
                                    fontSize > 0 &&
                                    fontSize < 10 &&
                                    style.textTransform !== "uppercase"
                                ) {
                                    add(
                                        "Typography", "low", el,
                                        "Text is " + fontSize +
                                            "px and contains " + text.length + " characters.",
                                        "Review this text at the current viewport. If it is important reading content, consider a font size of at least 12px; otherwise mark intentional microcopy as an exception.",
                                        "medium"
                                    );
                                }

                                // Detect measurable horizontal clipping.
                                if (
                                    ["hidden", "clip"].includes(style.overflowX) &&
                                    el.scrollWidth > el.clientWidth + 3 &&
                                    el.clientWidth > 0 &&
                                    text.length > 0
                                ) {
                                    add(
                                        "Typography", "medium", el,
                                        "Content width is " + el.scrollWidth +
                                            "px but visible width is " + el.clientWidth + "px.",
                                        "Check whether text should wrap, the container should grow, or truncation should be explicitly indicated.",
                                        "high"
                                    );
                                }

                                // Estimate contrast only when a solid background can be
                                // identified; skip uncertain backgrounds instead of guessing.
                                if (
                                    el.children.length === 0 &&
                                    text.length > 0 &&
                                    fontSize >= 1
                                ) {
                                    const foreground = rgb(style.color);
                                    const background = solidBackground(el);

                                    if (foreground && background) {
                                        const a = luminance(foreground);
                                        const b = luminance(background);
                                        const ratio = (Math.max(a, b) + 0.05) /
                                            (Math.min(a, b) + 0.05);
                                        const bold = parseInt(style.fontWeight, 10) >= 700;
                                        const large = fontSize >= (bold ? 18.66 : 24);
                                        const required = large ? 3 : 4.5;

                                        if (ratio < required) {
                                            add(
                                                "Color & contrast", "medium", el,
                                                "Estimated contrast is " + ratio.toFixed(2) +
                                                    ":1; WCAG AA target is " + required + ":1.",
                                                "Increase the contrast between this text and its background. Recheck the final rendered colors, especially if opacity or overlays are used.",
                                                "medium"
                                            );
                                        }
                                    }
                                }

                                // Accessible names for interactive controls.
                                if (
                                    (tag === "button" ||
                                     (tag === "a" && el.hasAttribute("href")) ||
                                     (tag === "input" &&
                                      !["hidden", "submit", "button", "reset"].includes(el.type))) &&
                                    !accessibleName(el)
                                ) {
                                    add(
                                        "Accessibility", "high", el,
                                        "No accessible name was detected for this interactive control.",
                                        "Provide visible text, an associated label, or a valid aria-label/aria-labelledby reference.",
                                        "high"
                                    );
                                }

                                if (
                                    tag === "input" &&
                                    !["hidden", "submit", "button", "reset", "image"].includes(el.type) &&
                                    !el.labels?.length &&
                                    !el.getAttribute("aria-label") &&
                                    !el.getAttribute("aria-labelledby")
                                ) {
                                    add(
                                        "Accessibility", "medium", el,
                                        "Input has no associated label or ARIA naming attribute.",
                                        "Associate a visible label with this input, or provide an appropriate accessible name.",
                                        "high"
                                    );
                                }
                            }

                            // Check control consistency only within forms that have
                            // at least two visible controls.
                            for (const form of document.querySelectorAll("form")) {
                                const controls = [...form.querySelectorAll(
                                    "input:not([type=hidden]), select, textarea, button"
                                )].filter(visible);

                                if (controls.length < 2) continue;

                                const heights = controls.map(el =>
                                    el.getBoundingClientRect().height
                                );
                                const spread = Math.max(...heights) - Math.min(...heights);

                                if (spread > 8) {
                                    add(
                                        "Alignment & spacing", "low", form,
                                        "Form control heights vary by " +
                                            Math.round(spread) + "px.",
                                        "Review whether these controls serve similar purposes. If so, align their heights through shared component styles.",
                                        "medium"
                                    );
                                }
                            }

                            return {
                                viewport_width: document.documentElement.clientWidth,
                                viewport_height: window.innerHeight,
                                issues
                            };
                        }""")

                        page_result["ui_audit"].append({
                            **viewport,
                            **ui_audit
                        })

                        layout = await page.evaluate("""() => {
                            const viewportWidth =
                                document.documentElement.clientWidth;
                            const documentWidth = Math.max(
                                document.documentElement.scrollWidth,
                                document.body ? document.body.scrollWidth : 0
                            );
                            const overflowing = [];

                            for (const element of document.querySelectorAll("body *")) {
                                if (overflowing.length >= 20) break;
                                const rect = element.getBoundingClientRect();
                                const style = getComputedStyle(element);

                                if (
                                    rect.width > 0 &&
                                    rect.height > 0 &&
                                    style.position !== "fixed" &&
                                    (rect.left < -1 ||
                                     rect.right > viewportWidth + 1)
                                ) {
                                    overflowing.push({
                                        element: (
                                            element.tagName.toLowerCase() +
                                            (element.id ? "#" + element.id : "")
                                        ).slice(0, 160),
                                        left: Math.round(rect.left),
                                        right: Math.round(rect.right),
                                        width: Math.round(rect.width)
                                    });
                                }
                            }

                            return {
                                viewport_width: viewportWidth,
                                document_width: documentWidth,
                                horizontal_overflow:
                                    documentWidth > viewportWidth + 1,
                                overflowing_elements: overflowing
                            };
                        }""")

                        page_result["responsive_checks"].append({
                            **viewport,
                            **layout,
                            "passed": not layout["horizontal_overflow"],
                        })

                except Exception as error:
                    page_result["page_test_error"] = str(error)[:300]
                finally:
                    await page.close()

                page_result["summary"] = {
                    "console_error_count": len(page_result["console_errors"]),
                    "page_error_count": len(page_result["page_errors"]),
                    "failed_request_count": len(page_result["failed_requests"]),
                    "responsive_viewports_tested":
                        len(page_result["responsive_checks"]),
                    "responsive_viewports_failed": sum(
                        1 for item in page_result["responsive_checks"]
                        if not item["passed"]
                    ),
                    "ui_issue_count": sum(
                        len(item.get("issues", []))
                        for item in page_result["ui_audit"]
                    ),
                }
                pages.append(page_result)

                if depth < max_depth:
                    for discovered_url in sorted(discovered_internal):
                        if discovered_url not in queued and len(queued) < max_pages:
                            queued.add(discovered_url)
                            queue.append((discovered_url, depth + 1))

            await browser.close()
            browser = None

        # Check a bounded number of external links separately. Never crawl
        # their pages or execute their JavaScript.
        external_results = []
        async with async_playwright() as playwright:
            request_context = await playwright.request.new_context(
                timeout=7000,
                ignore_https_errors=False,
            )
            for external_url in list(external_links.keys())[:max_external_checks]:
                result = {"url": external_url, "status": None, "error": None}
                try:
                    response = await request_context.get(
                        external_url,
                        fail_on_status_code=False,
                    )
                    result["status"] = response.status
                    result["broken"] = response.status >= 400
                except Exception as error:
                    result["error"] = str(error)[:180]
                    result["broken"] = True
                external_results.append(result)
            await request_context.dispose()

        total_console_errors = sum(len(p["console_errors"]) for p in pages)
        total_page_errors = sum(len(p["page_errors"]) for p in pages)
        total_failed_requests = sum(len(p["failed_requests"]) for p in pages)
        total_responsive_failed = sum(
            item["summary"].get("responsive_viewports_failed", 0)
            for item in pages
        )
        failed_pages = sum(
            1 for p in pages
            if not p["success"] and not p.get("auth_required")
        )

        # Keep legacy fields for the existing frontend, and provide the
        # detailed per-page report alongside them.
        first = pages[0] if pages else {}
        return {
            "success": bool(pages) and not failed_pages,
            "tested_url": start_url,
            "final_url": first.get("final_url"),
            "title": first.get("title"),
            "http_status": first.get("http_status"),
            "console_errors": first.get("console_errors", []),
            "page_errors": first.get("page_errors", []),
            "failed_requests": first.get("failed_requests", []),
            "broken_links": external_results,
            "links_checked": sum(p["links_checked"] for p in pages),
            "responsive_checks": first.get("responsive_checks", []),
            "pages": pages,
            "external_links": external_results,
            "pages_discovered": len(discovered_urls),
            "pages_tested": len(pages),
            "pages_auth_required": sum(
                1 for p in pages if p.get("auth_required")
            ),
            "pages_failed": failed_pages,
            "crawl_limit": max_pages,
            "summary": {
                "pages_tested": len(pages),
                "pages_failed": failed_pages,
                "pages_auth_required": sum(
                    1 for p in pages if p.get("auth_required")
                ),
                "console_error_count": total_console_errors,
                "page_error_count": total_page_errors,
                "failed_request_count": total_failed_requests,
                "external_links_checked": len(external_results),
                "external_broken_link_count": sum(
                    1 for item in external_results if item.get("broken")
                ),
                "responsive_viewports_tested": sum(
                    len(p["responsive_checks"]) for p in pages
                ),
                "responsive_viewports_failed": total_responsive_failed,
                "ui_issue_count": sum(
                    len(item.get("issues", []))
                    for page in pages
                    for item in page.get("ui_audit", [])
                ),
            },
            "note": (
                "Pages are discovered from rendered same-origin links and "
                "robots.txt/XML sitemaps. Crawl limits are currently 50 pages "
                "and depth 5; up to 50 external links are checked separately. "
                "Hidden routes, login-protected pages and button-only navigation "
                "may require additional discovery or an authorized login session. "
                "Responsive checks detect horizontal overflow, not every visual defect."
            ),
        }

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Website test failed: {str(error)[:250]}",
        ) from error

# VANTEX Local File Access — initial restricted version


# VANTEX Local File Access — initial restricted version

import os

AGENT_ROOT = (Path.home() / "Desktop" / "VANTEX").resolve()

SELECTED_PROJECT_ROOT = AGENT_ROOT
PROJECT_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".turbo"}
PROJECT_TEXT_EXTENSIONS = {".html", ".css", ".scss", ".sass", ".less", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".json", ".py", ".md", ".yaml", ".yml"}


class ProjectSelectRequest(BaseModel):
    path: str


def _describe_project(root: Path) -> dict:
    if not root.exists() or not root.is_dir() or root.is_symlink():
        raise HTTPException(status_code=400, detail="Choose an existing, non-symlink project folder.")
    root = root.resolve(strict=True)

    # Recognize ordinary projects and monorepo roots; never scan dependencies/build output.
    direct = {
        "package.json": (root / "package.json").is_file(),
        "index.html": (root / "index.html").is_file(),
        "pyproject.toml": (root / "pyproject.toml").is_file(),
        "requirements.txt": (root / "requirements.txt").is_file(),
        "src": (root / "src").is_dir(),
        "app": (root / "app").is_dir(),
        "pages": (root / "pages").is_dir(),
        "main.py": (root / "main.py").is_file(),
        "manage.py": (root / "manage.py").is_file(),
    }
    nested_markers = []
    skip_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".turbo"}
    for base, dirs, files in os.walk(root, followlinks=False):
        relative = Path(base).relative_to(root)
        depth = len(relative.parts)
        dirs[:] = [d for d in dirs if d not in skip_dirs and not (Path(base) / d).is_symlink()]
        if depth >= 3:
            dirs[:] = []
            continue
        if any(name in files for name in ("package.json", "index.html", "pyproject.toml", "requirements.txt", "main.py", "manage.py")):
            nested_markers.append(Path(base))
    has_monorepo_layout = any((root / name).is_dir() for name in ("apps", "packages", "frontend", "backend", "client", "server", "web", "api", "ai"))
    if not any(direct.values()) and not nested_markers and not has_monorepo_layout:
        raise HTTPException(status_code=400, detail="Folder does not look like a source project. Choose a project folder containing source files, or a monorepo root with apps/, packages/, frontend/, backend/, client/, server/, web/, api/, or ai/.")

    package_file = root / "package.json"
    if not package_file.is_file():
        package_file = next((p / "package.json" for p in nested_markers if (p / "package.json").is_file()), None)
    indicators = {**direct, "nested_project_files": bool(nested_markers), "monorepo_layout": has_monorepo_layout}
    framework = "Project / monorepo"
    if package_file and package_file.is_file():
        try:
            import json
            pkg = json.loads(package_file.read_text(encoding="utf-8"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            framework = next((name for key, name in [("vite", "Vite"), ("next", "Next.js"), ("react", "React"), ("vue", "Vue"), ("svelte", "Svelte")] if key in deps), "Node.js project")
            if package_file.parent != root:
                framework += " monorepo"
        except Exception:
            framework = "Node.js project / monorepo"
    elif direct["pyproject.toml"] or direct["requirements.txt"] or direct["main.py"] or direct["manage.py"] or any((p / "main.py").is_file() for p in nested_markers):
        framework = "Python project / monorepo"
    elif direct["index.html"]:
        framework = "Static HTML"
    return {"path": str(root), "name": root.name, "framework": framework, "indicators": indicators}


@app.get("/api/projects/current")
def current_project():
    return {**_describe_project(SELECTED_PROJECT_ROOT), "selected": True}


@app.post("/api/projects/select")
def select_project(request: ProjectSelectRequest):
    global SELECTED_PROJECT_ROOT
    candidate = Path(request.path).expanduser()
    if not candidate.is_absolute():
        raise HTTPException(status_code=400, detail="Enter an absolute project folder path.")
    try:
        candidate = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(status_code=400, detail="Project folder does not exist or cannot be accessed.")
    info = _describe_project(candidate)
    SELECTED_PROJECT_ROOT = candidate
    return {**info, "selected": True, "message": "Project selected. Project-fix operations are scoped to this folder."}


@app.get("/api/projects/browse")
def browse_project():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        chosen = filedialog.askdirectory(title="Choose a project folder", mustexist=True)
        root.destroy()
    except Exception as error:
        raise HTTPException(status_code=501, detail=f"Native folder picker unavailable ({str(error)[:100]}). Enter the absolute path manually.") from error
    if not chosen:
        return {"cancelled": True, "message": "Folder selection cancelled."}
    return {**_describe_project(Path(chosen)), "selected": False}


def resolve_selected_project_path(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = SELECTED_PROJECT_ROOT / candidate
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(SELECTED_PROJECT_ROOT.resolve(strict=True))
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(status_code=403, detail="Access denied: path is outside the selected project or does not exist.")
    return resolved


@app.get("/api/projects/map-source")
def map_project_source(selector: str = Query(min_length=1, max_length=500)):
    root = SELECTED_PROJECT_ROOT.resolve(strict=True)
    tokens = []
    if "#" in selector:
        token = selector.split("#", 1)[1].split(".", 1)[0].split(":", 1)[0].split(" ", 1)[0]
        if token and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", token):
            tokens.append(token)
    tokens.extend(re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", selector))
    tokens = list(dict.fromkeys(tokens))
    if not tokens:
        raise HTTPException(status_code=400, detail="Selector has no safe class or id token to map.")
    matches = []
    scanned = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in PROJECT_SKIP_DIRS and not (Path(current) / d).is_symlink()]
        for filename in files:
            path = Path(current) / filename
            if path.suffix.lower() not in PROJECT_TEXT_EXTENSIONS or path.is_symlink():
                continue
            scanned += 1
            if scanned > 6000:
                break
            try:
                if path.stat().st_size > 1000000:
                    continue
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            found = [token for token in tokens if re.search(r"(?<![A-Za-z0-9_-])" + re.escape(token) + r"(?![A-Za-z0-9_-])", content)]
            if found:
                matches.append({"path": str(path.resolve()), "relative_path": str(path.resolve().relative_to(root)), "type": "style" if path.suffix.lower() in {".css", ".scss", ".sass", ".less"} else "source", "matched_tokens": found})
                if len(matches) >= 40:
                    break
        if scanned > 6000 or len(matches) >= 40:
            break
    return {"project": str(root), "selector": selector, "tokens": tokens, "matches": matches, "message": "These are heuristic source candidates, not guaranteed ownership of the rendered element."}


MAX_READ_BYTES = 1_000_000
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}


def resolve_agent_path(raw_path: str | None = None) -> Path:
    """Allow access only inside the configured VANTEX project directory."""
    candidate = Path(raw_path).expanduser() if raw_path else AGENT_ROOT

    if not candidate.is_absolute():
        candidate = AGENT_ROOT / candidate

    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(AGENT_ROOT)
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(
            status_code=403,
            detail="Access denied: path is outside the approved VANTEX folder or does not exist.",
        )

    return resolved


@app.get("/api/agent/files/list")
def list_agent_files(path: str | None = Query(default=None)):
    directory = resolve_agent_path(path)

    if not directory.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory.")

    entries = []

    try:
        for item in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            try:
                resolved_item = item.resolve(strict=True)
                resolved_item.relative_to(AGENT_ROOT)
                is_dir = resolved_item.is_dir()

                entries.append({
                    "name": item.name,
                    "type": "directory" if is_dir else "file",
                    "path": str(resolved_item),
                    "size_bytes": None if is_dir else resolved_item.stat().st_size,
                })
            except (OSError, ValueError, RuntimeError):
                continue

            if len(entries) >= 200:
                break
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied.")

    return {
        "root": str(AGENT_ROOT),
        "directory": str(directory),
        "entries": entries,
        "count": len(entries),
    }


@app.get("/api/agent/files/search")
def search_agent_files(
    query: str = Query(min_length=1, max_length=200),
):
    needle = query.casefold()
    matches = []
    scanned = 0
    scan_limit = 10000

    for current, dirs, files in os.walk(AGENT_ROOT, followlinks=False):
        dirs[:] = [
            name for name in dirs
            if name not in SKIP_DIRS
            and not (Path(current) / name).is_symlink()
        ]

        for name in files:
            scanned += 1

            if needle in name.casefold():
                candidate = Path(current) / name

                try:
                    resolved = candidate.resolve(strict=True)
                    resolved.relative_to(AGENT_ROOT)

                    matches.append({
                        "name": name,
                        "path": str(resolved),
                    })
                except (OSError, ValueError, RuntimeError):
                    continue

                if len(matches) >= 100:
                    return {
                        "query": query,
                        "matches": matches,
                        "truncated": True,
                    }

            if scanned >= scan_limit:
                return {
                    "query": query,
                    "matches": matches,
                    "truncated": True,
                    "message": "Scan limit reached.",
                }

    return {
        "query": query,
        "matches": matches,
        "truncated": False,
    }


@app.get("/api/agent/files/read")
def read_agent_file(path: str = Query(min_length=1)):
    file_path = resolve_agent_path(path)

    if not file_path.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file.")

    if file_path.stat().st_size > MAX_READ_BYTES:
        raise HTTPException(
            status_code=413,
            detail="File exceeds the 1 MB read limit.",
        )

    try:
        content = file_path.read_bytes()

        if b"\x00" in content:
            raise HTTPException(
                status_code=415,
                detail="Binary files are not supported by this text reader.",
            )

        text_content = content.decode("utf-8")

    except UnicodeDecodeError:
        raise HTTPException(
            status_code=415,
            detail="File is not valid UTF-8 text.",
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied.")

    return {
        "path": str(file_path),
        "size_bytes": len(content),
        "content": text_content,
        "read_only": True,
    }

# VANTEX controlled file editing

from pydantic import Field


class PrepareEditRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    new_content: str = Field(max_length=1_000_000)


class ApplyEditRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=100)
    approve: bool = False


# Prototype storage: pending proposals remain in memory until API restarts.
PENDING_EDITS = {}


@app.post("/api/agent/files/prepare-edit")
def prepare_file_edit(request: PrepareEditRequest):
    try:
        target = resolve_agent_path(request.path)
    except HTTPException:
        target = resolve_selected_project_path(request.path)

    if not target.is_file():
        raise HTTPException(status_code=400, detail="Target must be an existing file.")

    if target.is_symlink():
        raise HTTPException(status_code=403, detail="Symbolic links cannot be edited.")

    if target.stat().st_size > MAX_READ_BYTES:
        raise HTTPException(status_code=413, detail="Original file exceeds 1 MB.")

    try:
        original_content = target.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        raise HTTPException(
            status_code=415,
            detail="Only readable UTF-8 text files can be edited.",
        )

    if "\x00" in original_content or "\x00" in request.new_content:
        raise HTTPException(status_code=415, detail="Binary content is not supported.")

    if original_content == request.new_content:
        return {"changed": False, "message": "File already has this content."}

    proposal_id = secrets.token_urlsafe(24)
    original_hash = hashlib.sha256(
        original_content.encode("utf-8")
    ).hexdigest()

    diff = list(difflib.unified_diff(
        original_content.splitlines(),
        request.new_content.splitlines(),
        fromfile=f"original/{target.name}",
        tofile=f"proposed/{target.name}",
        lineterm="",
    ))

    PENDING_EDITS[proposal_id] = {
        "path": str(target),
        "original_hash": original_hash,
        "new_content": request.new_content,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "proposal_id": proposal_id,
        "path": str(target),
        "changed": True,
        "diff": diff,
        "approval_required": True,
        "message": "Review the diff. The original file has not been changed.",
    }



# VANTEX_MULTI_FIX_V1
class UIFixRequest(BaseModel):
    element: str = Field(min_length=1, max_length=500)
    evidence: str = Field(min_length=1, max_length=300)
    category: str = Field(default="Typography", max_length=80)
    fix_kind: str = Field(default="typography", max_length=30)
    accessibility_label: str = Field(default="", max_length=120)
    contrast_color: str = Field(default="#ffffff", max_length=20)


def _ui_fix_declarations(fix_kind: str, contrast_color: str = "#ffffff") -> dict[str, str]:
    """Only return predefined CSS values; never accept arbitrary CSS from the client."""
    if fix_kind == "typography":
        return {"font-size": "12px"}
    if fix_kind == "overflow":
        return {
            "max-width": "100%",
            "min-width": "0",
            "overflow-wrap": "anywhere",
            "white-space": "normal",
        }
    if fix_kind == "contrast":
        # Only accept one of two predefined high-contrast foreground choices.
        color = contrast_color.lower()
        if color not in {"#ffffff", "#111827"}:
            color = "#ffffff"
        return {"color": color}
    raise HTTPException(status_code=400, detail="Unsupported UI fix type.")


def _prepare_accessibility_input_edit(project_root: Path, selector: str, requested_label: str = ""):
    """Prepare an aria-label proposal only when exactly one matching JSX input is found."""
    tokens = list(dict.fromkeys(re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", selector)))
    if not tokens:
        raise HTTPException(status_code=422, detail="Could not identify input classes from this finding. Use Find source file.")

    matches = []
    scanned = 0
    skip = set(PROJECT_SKIP_DIRS) | {"dist", "build", ".next", ".git", "coverage"}
    for current, dirs, files in os.walk(project_root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in skip and not (Path(current) / d).is_symlink()]
        for filename in files:
            candidate = Path(current) / filename
            if candidate.suffix.lower() not in {".tsx", ".jsx", ".html", ".vue", ".svelte"} or candidate.is_symlink():
                continue
            scanned += 1
            if scanned > 2500:
                break
            try:
                if candidate.stat().st_size > 1_000_000:
                    continue
                content = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for tag_match in re.finditer(r"<input\b[^>]*>", content, flags=re.IGNORECASE | re.DOTALL):
                tag = tag_match.group(0)
                class_match = re.search(r"(?:className|class)\s*=\s*(?:\{\s*)?['\"]([^'\"]*)['\"]", tag)
                if not class_match:
                    continue
                classes = set(class_match.group(1).split())
                if not set(tokens).issubset(classes):
                    continue
                if re.search(r"\b(?:aria-label|aria-labelledby)\s*=", tag):
                    continue
                # An associated explicit label may be outside this tag; the QA report says none,
                # but only propose if the control has a meaningful placeholder/name/type.
                placeholder = re.search(r"\bplaceholder\s*=\s*['\"]([^'\"]+)['\"]", tag, re.I)
                name = re.search(r"\bname\s*=\s*['\"]([^'\"]+)['\"]", tag, re.I)
                input_type = re.search(r"\btype\s*=\s*['\"]([^'\"]+)['\"]", tag, re.I)
                identifier = re.search(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", tag, re.I)
                label = placeholder.group(1).strip() if placeholder else ""
                if not label and name:
                    raw = name.group(1).replace("_", " ").replace("-", " ").strip()
                    label = raw[:1].upper() + raw[1:]
                if not label and identifier:
                    raw = identifier.group(1).replace("_", " ").replace("-", " ").strip()
                    label = raw[:1].upper() + raw[1:]
                if not label and input_type:
                    label = {"email": "Email address", "password": "Password", "search": "Search", "tel": "Phone number", "url": "Website address", "number": "Number"}.get(input_type.group(1).lower(), "")
                if not label:
                    label = requested_label.strip()
                if not label:
                    # Keep this input out of automatic edits unless the user supplies a meaningful label.
                    continue
                matches.append((candidate.resolve(), content, tag_match.start(), tag_match.end(), tag, label))
        if scanned > 2500:
            break

    # De-duplicate the same physical source range and never guess between repeated controls.
    unique = {(str(item[0]), item[2], item[3]): item for item in matches}
    matches = list(unique.values())
    if len(matches) != 1:
        detail = "No safely identifiable input with a meaningful placeholder/name was found." if not matches else f"Found {len(matches)} matching inputs; refusing to guess which one to edit."
        raise HTTPException(status_code=422, detail=detail + " Use Find source file and add a visible label or aria-label manually.")

    target, original, start, end, tag, label = matches[0]
    try:
        target.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Input source is outside the selected project.")
    escaped = label.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    replacement = re.sub(r"\s*/?>$", lambda m: f' aria-label="{escaped}"{m.group(0)}', tag)
    proposed = original[:start] + replacement + original[end:]
    result = prepare_file_edit(PrepareEditRequest(path=str(target), new_content=proposed))
    if not result.get("changed"):
        raise HTTPException(status_code=409, detail="No accessibility change was proposed.")
    result["fix_type"] = "accessibility"
    result["proposed_declarations"] = {"aria-label": label}
    result["caution"] = "Review the source diff. This adds an accessible name based on the input's existing placeholder/name/id; a visible label is preferable when practical."
    return result


# VANTEX_ACCESSIBILITY_FIX_V1
# VANTEX_QA_PROPOSAL_REPAIR_V1

@app.post("/api/agent/qa/prepare-ui-fix")
def prepare_ui_fix(request: UIFixRequest):
    selector = request.element.strip()
    if not selector or len(selector) > 500 or any(char in selector for char in "{};"):
        raise HTTPException(status_code=400, detail="Unsupported CSS selector.")

    fix_kind = request.fix_kind.strip().lower()
    evidence = request.evidence.strip()
    if fix_kind == "typography":
        match = re.fullmatch(
            r"Text is ([0-9]+(?:\.[0-9]+)?)px and contains [0-9]+ characters\.",
            evidence,
        )
        if request.category != "Typography" or not match or float(match.group(1)) >= 10:
            raise HTTPException(status_code=400, detail="Typography fixes require evidence of text smaller than 10px.")
    elif fix_kind == "overflow":
        if request.category != "Typography" or not evidence.startswith("Content width is "):
            raise HTTPException(status_code=400, detail="Overflow fixes require a measured content-width finding.")
    elif fix_kind == "contrast":
        if request.category != "Color & contrast" or not evidence.startswith("Estimated contrast is "):
            raise HTTPException(status_code=400, detail="Contrast fixes require a color-contrast finding.")
    elif fix_kind == "accessibility":
        evidence_lower = evidence.lower()
        if not ("accessible name" in evidence_lower or "associated label" in evidence_lower or "aria naming attribute" in evidence_lower):
            raise HTTPException(status_code=400, detail="Accessibility fixes require a missing input-name/label finding.")
    else:
        raise HTTPException(status_code=400, detail="Unsupported UI fix type.")

    project_root = SELECTED_PROJECT_ROOT.resolve(strict=True)
    if fix_kind == "accessibility":
        return _prepare_accessibility_input_edit(project_root, selector, request.accessibility_label)

    declarations = _ui_fix_declarations(
        fix_kind,
        request.contrast_color if request.contrast_color in {"#ffffff", "#111827"} else "#ffffff",
    )
    tokens = []
    if "#" in selector:
        token = selector.split("#", 1)[1].split(".", 1)[0].split(":", 1)[0].split(" ", 1)[0]
        if token and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", token):
            tokens.append(token)
    tokens.extend(re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", selector))
    tokens = list(dict.fromkeys(tokens))

    style_files = []
    scanned = 0
    for current, dirs, files in os.walk(project_root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in PROJECT_SKIP_DIRS and not (Path(current) / d).is_symlink()]
        for filename in files:
            candidate = Path(current) / filename
            if candidate.suffix.lower() not in {".css", ".scss", ".sass", ".less"} or candidate.is_symlink():
                continue
            scanned += 1
            if scanned > 3000:
                break
            try:
                if candidate.stat().st_size > 1_000_000:
                    continue
                content = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if tokens and any(
                re.search(r"(?<![A-Za-z0-9_-])" + re.escape(token) + r"(?![A-Za-z0-9_-])", content)
                for token in tokens
            ):
                style_files.append(candidate.resolve())
                if len(style_files) >= 20:
                    break
        if scanned > 3000 or len(style_files) >= 20:
            break

    if style_files:
        target = style_files[0]
    else:
        fallbacks = [
            "src/index.css", "src/App.css", "src/globals.css", "src/style.css",
            "app/globals.css", "app/styles.css", "styles/globals.css",
            "index.css", "style.css", "apps/web/src/index.css", "apps/web/src/App.css",
        ]
        target = next((project_root / rel for rel in fallbacks if (project_root / rel).is_file()), None)
        if target is None:
            # Tailwind utility classes usually do not exist as selectors in source CSS.
            # Find an existing source stylesheet recursively; never use dist/build output.
            recursive_css = []
            skip_css_dirs = set(PROJECT_SKIP_DIRS) | {"dist", "build", ".next", ".git", "coverage"}
            for current, dirs, filenames in os.walk(project_root, followlinks=False):
                dirs[:] = [d for d in dirs if d not in skip_css_dirs and not (Path(current) / d).is_symlink()]
                for filename in filenames:
                    candidate = Path(current) / filename
                    if candidate.suffix.lower() not in {".css", ".scss", ".sass", ".less"} or candidate.is_symlink():
                        continue
                    try:
                        if candidate.stat().st_size <= 1_000_000:
                            recursive_css.append(candidate.resolve())
                    except OSError:
                        continue
                if len(recursive_css) >= 80:
                    break
            preferred = {"globals.css": 0, "global.css": 1, "index.css": 2, "app.css": 3, "home.css": 4, "style.css": 5, "styles.css": 6}
            recursive_css.sort(key=lambda p: (preferred.get(p.name.lower(), 20), len(p.parts), str(p)))
            target = recursive_css[0] if recursive_css else None
        if target is None:
            raise HTTPException(status_code=404, detail="No source stylesheet exists in the selected project. Select the actual frontend project folder; no file changed.")
        target = target.resolve(strict=True)

    try:
        target.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Stylesheet is outside selected project.")
    original = target.read_text(encoding="utf-8")
    marker = f"/* VANTEX {fix_kind} proposal: {selector} */"
    declaration_text = "\n".join(f"    {name}: {value} !important;" for name, value in declarations.items())
    # VANTEX_QA_PROPOSAL_REPAIR_V1: escape Tailwind variant colons in class selectors.
    css_selector = re.sub(
        r"\.([A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)+)",
        lambda m: "." + m.group(1).replace(":", r"\:"),
        selector,
    )
    new_block = marker + "\n" + css_selector + " {\n" + declaration_text + "\n}"
    if marker in original:
        # Update the existing VANTEX proposal in-place instead of blocking the user.
        start = original.index(marker)
        close = original.find("\n}", start)
        if close < 0:
            raise HTTPException(status_code=409, detail="Existing VANTEX proposal is malformed; no file changed.")
        end = close + 2
        proposed = original[:start] + new_block + original[end:]
    else:
        proposed = original.rstrip() + "\n\n" + new_block + "\n"
    result = prepare_file_edit(PrepareEditRequest(path=str(target), new_content=proposed))
    if not result.get("changed"):
        raise HTTPException(status_code=409, detail="No CSS change was proposed.")
    result["fix_type"] = fix_kind
    result["project_root"] = str(project_root)
    result["relative_path"] = str(target.relative_to(project_root))
    result["source_mapping"] = "selector-token CSS match" if style_files else "stylesheet fallback"
    result["proposed_declarations"] = declarations
    result["caution"] = (
        "Review the before/after preview and diff. Contrast uses a light mint foreground proposal "
        "that may not suit every background; source remains unchanged until explicit approval."
    )
    return result


class VisualPreviewRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    selector: str = Field(min_length=1, max_length=500)
    font_size: int = Field(default=12, ge=10, le=32)
    fix_kind: str = Field(default="typography", max_length=30)
    candidate_index: int | None = Field(default=None, ge=0, le=9)


@app.post("/api/agent/qa/visual-preview")
async def visual_preview(request: VisualPreviewRequest):
    """Capture a temporary before/after preview; never edit source files."""
    from urllib.parse import urlparse
    import ipaddress

    parsed = urlparse(request.url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Invalid website URL.")
    host = parsed.hostname.lower()
    allowed_local = host in ("localhost", "127.0.0.1", "::1")
    if not allowed_local:
        try:
            allowed_local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed_local = False
    if not allowed_local:
        raise HTTPException(status_code=403, detail="Visual preview currently supports localhost URLs only.")

    selector = request.selector.strip()
    if (not selector or len(selector) > 500 or
        not re.fullmatch(r"[A-Za-z0-9_.*#:\-\[\]=\"' >+~(),]+", selector)):
        raise HTTPException(status_code=400, detail="Unsupported CSS selector.")

    # VANTEX_SELECTOR_ESCAPE_V1: Tailwind variant colons inside class names
    # must be escaped for querySelectorAll (e.g. .md:text-5xl -> .md\:text-5xl).
    # Only escape colons that appear in a dot-prefixed class token, not pseudo-selectors.
    selector = re.sub(
        r"\.([A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)+)",
        lambda match: "." + match.group(1).replace(":", r"\:"),
        selector,
    )

    browser = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
            await page.goto(request.url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(500)
            locator = page.locator(selector)
            count = await locator.count()
            if count == 0:
                raise HTTPException(status_code=404, detail="No element matched this selector.")

            candidates = []
            for index in range(min(count, 10)):
                item = locator.nth(index)
                candidates.append({"index": index, "text": (await item.inner_text())[:120], "visible": await item.is_visible()})
            visible = [item for item in candidates if item["visible"]]

            if request.candidate_index is None and len(visible) != 1:
                return {"needs_selection": True, "message": f"Selector matched {count} elements. Choose the correct visible element.", "candidates": candidates, "source_changed": False}

            if request.candidate_index is None:
                chosen_index = visible[0]["index"]
            else:
                chosen_index = request.candidate_index
                if chosen_index >= count or not await locator.nth(chosen_index).is_visible():
                    raise HTTPException(status_code=400, detail="Selected candidate is no longer visible. Run the preview again.")

            chosen = locator.nth(chosen_index)
            # Build a stable, unique CSS path for this exact DOM node.
            unique_selector = await chosen.evaluate(r"""el => {
              const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/[^a-zA-Z0-9_-]/g, '\\$&');
              if (el.id) {
                const byId = '#' + esc(el.id);
                if (document.querySelectorAll(byId).length === 1) return byId;
              }
              const parts = [];
              let node = el;
              while (node && node.nodeType === 1 && parts.length < 8) {
                let part = node.tagName.toLowerCase();
                if (node.id) {
                  const byId = '#' + esc(node.id);
                  if (document.querySelectorAll(byId).length === 1) { parts.unshift(byId); break; }
                }
                const parent = node.parentElement;
                if (parent) {
                  const sameTag = Array.from(parent.children).filter(x => x.tagName === node.tagName);
                  if (sameTag.length > 1) part += ':nth-of-type(' + (sameTag.indexOf(node) + 1) + ')';
                }
                if (node.classList.length) {
                  const cls = Array.from(node.classList).filter(c => /^[a-zA-Z_][a-zA-Z0-9_-]*$/.test(c)).slice(0, 2);
                  if (cls.length) part += cls.map(c => '.' + esc(c)).join('');
                }
                parts.unshift(part);
                const candidate = parts.join(' > ');
                try { if (document.querySelectorAll(candidate).length === 1) return candidate; } catch (_) {}
                node = parent;
              }
              return parts.join(' > ');
            }""")
            unique_count = await page.locator(unique_selector).count()
            if unique_count != 1:
                raise HTTPException(status_code=409, detail="Could not create a unique selector for this element. No fix was prepared.")

            before_png = await page.screenshot(type="png", full_page=False)
            contrast_color = "#ffffff"
            if request.fix_kind == "contrast":
                contrast_color = await chosen.evaluate("""el => {
                  const lum = rgb => {
                    const c = rgb.map(v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
                    return 0.2126*c[0] + 0.7152*c[1] + 0.0722*c[2];
                  };
                  let node = el, bg = [255,255,255];
                  while (node && node.nodeType === 1) {
                    const s = getComputedStyle(node), m = s.backgroundColor.match(/rgba?\((\d+)[, ]+\s*(\d+)[, ]+\s*(\d+)/i);
                    if (m && !(s.backgroundColor.includes("0)") || s.backgroundColor.includes("/ 0)"))) { bg = [+m[1],+m[2],+m[3]]; break; }
                    node = node.parentElement;
                  }
                  const l = lum(bg), white = 1.05/(l+0.05), dark = (l+0.05)/(0.006+0.05);
                  return white >= dark ? "#ffffff" : "#111827";
                }""")
            if request.fix_kind == "accessibility":
                preview_label = await chosen.evaluate("""el => {
                  const placeholder = (el.getAttribute('placeholder') || '').trim();
                  const name = (el.getAttribute('name') || el.id || '').replace(/[_-]+/g, ' ').trim();
                  const type = (el.getAttribute('type') || '').toLowerCase();
                  const typeNames = {email:'Email address', password:'Password', search:'Search', tel:'Phone number', url:'Website address', number:'Number'};
                  return placeholder || (name ? name.charAt(0).toUpperCase() + name.slice(1) : '') || typeNames[type] || 'Input field';
                }""")
                preview_declarations = {"aria-label": preview_label}
                await chosen.evaluate("(el, label) => el.setAttribute('aria-label', label)", preview_label)
            else:
                preview_declarations = _ui_fix_declarations(request.fix_kind)
                if request.fix_kind == "typography":
                    preview_declarations = {"font-size": f"{request.font_size}px"}
                await chosen.evaluate(
                    """(el, declarations) => {
                        for (const [property, value] of Object.entries(declarations)) {
                            el.style.setProperty(property, value, 'important');
                        }
                    }""",
                    preview_declarations,
                )
            await page.wait_for_timeout(300)
            after_png = await page.screenshot(type="png", full_page=False)
            return {
                "url": page.url,
                "selector": selector,
                "unique_selector": unique_selector,
                "selected_index": chosen_index,
                "font_size": request.font_size,
                "fix_kind": request.fix_kind,
                "preview_declarations": preview_declarations,
                "contrast_color": contrast_color,
                "before_image": "data:image/png;base64," + base64.b64encode(before_png).decode("ascii"),
                "after_image": "data:image/png;base64," + base64.b64encode(after_png).decode("ascii"),
                "source_changed": False,
                "message": "Temporary browser preview created for the selected element; source file unchanged.",
            }
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Visual preview failed: {str(error)[:200]}") from error
    finally:
        if browser is not None:
            await browser.close()


@app.post("/api/agent/files/apply-edit")
def apply_file_edit(request: ApplyEditRequest):
    if not request.approve:
        raise HTTPException(
            status_code=400,
            detail="Explicit approval is required to apply this edit.",
        )

    proposal = PENDING_EDITS.get(request.proposal_id)
    if not proposal:
        raise HTTPException(
            status_code=404,
            detail="Proposal not found or expired after a server restart.",
        )

    try:
        target = resolve_agent_path(proposal["path"])
    except HTTPException:
        target = resolve_selected_project_path(proposal["path"])

    if not target.is_file() or target.is_symlink():
        raise HTTPException(status_code=403, detail="Target is no longer a regular file.")

    current_content = target.read_text(encoding="utf-8")
    current_hash = hashlib.sha256(current_content.encode("utf-8")).hexdigest()

    if current_hash != proposal["original_hash"]:
        PENDING_EDITS.pop(request.proposal_id, None)
        raise HTTPException(
            status_code=409,
            detail="File changed after proposal creation. Prepare a fresh edit.",
        )

    new_content = proposal["new_content"]
    try:
        target.relative_to(AGENT_ROOT)
        backup_root = AGENT_ROOT
    except ValueError:
        target.relative_to(SELECTED_PROJECT_ROOT.resolve(strict=True))
        backup_root = SELECTED_PROJECT_ROOT.resolve(strict=True)
    backup_dir = backup_root / ".vantex_backups"
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"{target.name}.{timestamp}.bak"
    backup_path.write_text(current_content, encoding="utf-8")

    temp_path = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")

    try:
        temp_path.write_text(new_content, encoding="utf-8")
        os.replace(temp_path, target)

        verified_content = target.read_text(encoding="utf-8")
        if verified_content != new_content:
            raise OSError("Post-write verification failed.")

    except Exception as error:
        try:
            if backup_path.exists():
                os.replace(backup_path, target)
        except OSError:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Edit failed or verification failed: {str(error)[:200]}",
        ) from error
    finally:
        if temp_path.exists():
            temp_path.unlink()

    PENDING_EDITS.pop(request.proposal_id, None)

    return {
        "success": True,
        "path": str(target),
        "verified": True,
        "backup_path": str(backup_path),
        "message": "Approved edit applied and verified.",
    }

import re
from pydantic import Field



class LocalChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = []


@app.post("/api/agent/chat")
async def local_agent_chat(request: LocalChatRequest):
    import asyncio
    import json
    import urllib.request
    import urllib.error

    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    if len(message) > 2000:
        raise HTTPException(status_code=400, detail="Message is too long.")

    messages = [{
        "role": "system",
        "content": (
            "You are VANTEX, a friendly local desktop AI assistant. "
            "Speak naturally and conversationally. Understand English, Hindi "
            "and Hinglish. Respond to greetings warmly, answer follow-up "
            "questions using the conversation history, and keep replies concise. "
            "You can explain PC troubleshooting, but you cannot directly inspect "
            "or control the computer through this chat endpoint. Never claim "
            "you performed an action unless a separate tool confirms it. "
            "Do not tell the user to run destructive commands without explaining "
            "the risk and obtaining confirmation."
        ),
    }]

    for item in request.history[-10:]:
        role = item.get("role")
        content = item.get("content", "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:2000]})

    messages.append({"role": "user", "content": message})

    payload = json.dumps({
        "model": "qwen2.5:3b",
        "messages": messages,
        "stream": False,
        "keep_alive": "30s",
        "options": {
            "num_ctx": 2048,
            "num_predict": 180,
        },
    }).encode("utf-8")

    def call_ollama():
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        data = await asyncio.to_thread(call_ollama)
        reply = data.get("message", {}).get("content", "").strip()
        if not reply:
            raise HTTPException(status_code=502, detail="Local AI returned an empty reply.")
        return {"reply": reply, "model": "qwen2.5:3b", "local": True}
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is unavailable. Start Ollama and try again."
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Local AI took too long to respond.") from exc


class AgentCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=2000)


# Controlled desktop application launcher. Uses a fixed allowlist and never a shell.
PC_APP_CANDIDATES = {
    "vscode": ("code",),
    "vs code": ("code",),
    "visual studio code": ("code",),
    "terminal": ("x-terminal-emulator", "xfce4-terminal", "konsole", "gnome-terminal"),
    "browser": ("firefox", "chromium", "google-chrome", "brave-browser"),
    "firefox": ("firefox",),
    "chrome": ("google-chrome", "chromium", "chromium-browser"),
    "file manager": ("thunar", "nautilus", "dolphin", "pcmanfm"),
    "files": ("thunar", "nautilus", "dolphin", "pcmanfm"),
    "text editor": ("mousepad", "gedit", "kate", "xed"),
    "mousepad": ("mousepad",),
    "libreoffice": ("libreoffice",),
    "vlc": ("vlc",),
}
def _available_pc_apps():
    return [
        {
            "label": app["name"],
            "executable": app.get("desktop_file")
            or app.get("shortcut")
            or app.get("app_path"),
        }
        for app in discover_apps()
    ]


@app.get("/api/agent/pc-control/apps")
def list_pc_control_apps():
    apps = _available_pc_apps()
    return {
        "apps": apps,
        "count": len(apps),
        "message": "Applications discovered from this operating system.",
    }


class PCAppLaunchRequest(BaseModel):
    app: str = Field(min_length=1, max_length=160)


@app.post("/api/agent/pc-control/launch")
def launch_pc_control_app(request: PCAppLaunchRequest):
    try:
        return launch_app(request.app)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

def _launch_pc_app(label: str):
    import shutil
    import subprocess
    from fastapi import HTTPException
    candidates = PC_APP_CANDIDATES.get(label)
    if not candidates:
        raise HTTPException(status_code=400, detail="That application is not on VANTEX's allowlist.")
    executable = next((shutil.which(name) for name in candidates if shutil.which(name)), None)
    if not executable:
        raise HTTPException(status_code=404, detail=f"{label} is not installed or its launcher was not found.")
    try:
        subprocess.Popen([executable], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, env=__import__("os").environ.copy())
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not launch {label}: {exc}") from exc
    return {"launched": True, "app": label, "executable": executable,
            "message": f"Launch request sent to {label}."}

@app.post("/api/agent/command")
async def run_agent_command(request: AgentCommandRequest):
    command = request.command.strip()
    lowered = command.casefold()

    # Explicit app-launch commands. This is checked before file-open parsing.
    app_match = re.fullmatch(
        r"\s*(?:please\s+)?(?:open|launch|start|run|kholo|khol|khul)\s+(?:the\s+)?"
        r"(visual studio code|vs code|vscode|terminal|browser|firefox|chrome|file manager|files|text editor|mousepad|libreoffice|vlc)\s*[.!]?\s*",
        lowered,
    )
    if app_match:
        label = app_match.group(1).strip()
        if label == "vscode":
            label = "vscode"
        return {"command": command, "action": "launch_pc_app", "result": _launch_pc_app(label)}

    # Natural-language PC file commands
    open_words = ("open", "open file", "kholo", "khol", "khul")

    # Latest screenshot: show its location or open it.
    if (
        ("screenshot" in lowered or "screen shot" in lowered or " ss " in f" {lowered} ")
        and any(word in lowered for word in ("latest", "last", "newest", "recent", "sabse nayi", "latest wali"))
    ):
        screenshot = latest_pc_screenshot()

        if any(word in lowered for word in ("open", "kholo", "khol", "khul")):
            opened = open_pc_file(OpenPcFileRequest(path=screenshot["path"]))
            return {
                "command": command,
                "action": "open_latest_screenshot",
                "result": opened,
            }

        return {
            "command": command,
            "action": "latest_screenshot",
            "result": screenshot,
        }

    # Hindi/English file search, optionally restricted to one approved folder.
    folder_names = {
        "desktop": "Desktop",
        "downloads": "Downloads",
        "documents": "Documents",
        "pictures": "Pictures",
        "videos": "Videos",
    }

    detected_folder = next(
        (value for key, value in folder_names.items()
         if re.search(rf"\b{key}\b", lowered)),
        None,
    )

    folder_search = re.search(
        r"(.+?)\s+(?:mein|me|par|pe)\s+(.+?)\s+(?:wali|waali)\s+files?\s+(?:de|dikha|dikhao|bata|batao|show)",
        lowered,
    )

    if folder_search:
        folder_from_command = folder_names.get(folder_search.group(1).strip())
        if folder_from_command:
            detected_folder = folder_from_command
            query = folder_search.group(2).strip()
            result = search_pc_files(query, folder=detected_folder)
            return {
                "command": command,
                "action": "search_pc_files",
                "result": result,
            }

    hindi_search = re.fullmatch(
        r"(.+?)\s+(?:wali|waali)\s+(?:(?:saari|sari)\s+)?files?\s+(?:de|dikha|dikhao|bata|batao|show)",
        lowered,
    )

    english_search = re.fullmatch(
        r"(?:find|search|show|list)\s+(?:all\s+)?(?:pc\s+)?files?\s+(?:named|matching|for|about)\s+(.+)",
        command,
        flags=re.IGNORECASE,
    )

    if hindi_search or english_search:
        query = (
            hindi_search.group(1).strip()
            if hindi_search
            else english_search.group(1).strip()
        )
        result = search_pc_files(query, folder=detected_folder)
        return {
            "command": command,
            "action": "search_pc_files",
            "result": result,
        }




    # General PC content search: documents, source code and configuration files.
    content_extensions = {
        ".pdf", ".docx", ".txt", ".md", ".rst", ".csv", ".log",
        ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml",
        ".yml", ".html", ".css", ".xml", ".sql", ".sh", ".toml",
        ".ini", ".cfg", ".conf",
    }

   
    ranking_occurrences = any(term in lowered for term in (
        "sabse zyada baar", "sabse jyada baar",
        "most occurrences", "most times", "appears most",
        "mentioned most", "highest occurrence count",
    ))

    ranking_most = ranking_occurrences or any(term in lowered for term in (
        "sabse zyada content", "most content", "maximum content",
        "longest resume", "sabse detailed", "most words",
        "most text", "longest document",
    ))

    ranking_least = any(term in lowered for term in (
        "sabse kam content", "least content", "least words",
        "shortest resume", "minimum content", "kam content",
        "least text", "shortest document",
    ))

    ranking_largest = any(term in lowered for term in (
        "sabse badi file", "largest file", "biggest file",
        "sabse badi pdf", "largest pdf",
    ))

        # Generic content search: search terms are taken from the user's command.
    content_search_patterns = [
        re.compile(
            r"^\s*(?:please\s+)?(?:search|find|look\s+for)\s+"
            r"(?:all\s+)?files?\s+"
            r"(?:with|containing|that\s+contain|mentioning)\s+(.+?)\s*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:please\s+)?(?:search|find|look\s+for)\s+"
            r"(.+?)\s+files?\s+for\s+(.+?)\s*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:please\s+)?(?:search|find|look\s+for)\s+"
            r"(resume|cv)\s+for\s+(.+?)\s*$",
            re.IGNORECASE,
        ),
    ]

    content_intent = (
        ranking_most or ranking_least or ranking_largest
    )
    query = None
    category_filter = None

    for pattern in content_search_patterns:
        match = pattern.match(command)
        if not match:
            continue

        content_intent = True

        if len(match.groups()) == 2:
            category_filter = match.group(1).strip()
            query = match.group(2).strip()
        else:
            query = match.group(1).strip()

        break

    # Also support commands such as:
    # "Find text Auralink inside files"
    if not content_intent:
        match = re.search(
            r"\b(?:find\s+text|search\s+content|search\s+inside|"
            r"search\s+within|file\s+containing|document\s+containing)"
            r"\s+(.+?)(?:\s+inside\s+files?)?\s*$",
            command,
            re.IGNORECASE,
        )
        if match:
            content_intent = True
            query = match.group(1).strip()

    if query:
        query = re.sub(r"\s+", " ", query).strip(" .,!?:;")

    if not query and not (
        ranking_most or ranking_least or ranking_largest
    ):
        content_intent = False

    if content_intent:
        import zipfile
        import xml.etree.ElementTree as ET
        from pypdf import PdfReader

        extension_filter = None

        wants_open = bool(re.search(
            r"\b(open|kholo|khol|khul)\b", lowered
        ))
 

    if content_intent:
        import zipfile
        import xml.etree.ElementTree as ET
        from pypdf import PdfReader

        extension_filter = None
        for ext, aliases in {
            ".pdf": ("pdf",),
            ".docx": ("docx", "word document"),
            ".txt": ("txt", "text file"),
            ".md": ("markdown", ".md"),
            ".py": ("python file", ".py"),
            ".tsx": ("tsx",),
            ".ts": ("typescript file",),
            ".js": ("javascript file",),
            ".csv": ("csv",),
        }.items():
            if any(alias in lowered for alias in aliases):
                extension_filter = ext
                break

        wants_open = bool(re.search(
            r"\b(open|kholo|khol|khul)\b", lowered
        ))

        
       
        # Generic parsing: separate file category from the text to search.
        query = None
        category_filter = None

        command_text = command.strip()

        # Example: Search resume with Shruti
        match = re.match(
            r"^(?:please\s+)?(?:search|find|look for)\s+"
            r"(?:the\s+)?(resume|resumes|cv|cvs)\s+"
            r"(?:for|with|containing|mentioning)\s+(.+?)\s*$",
            command_text,
            re.IGNORECASE,
        )

        if match:
            category_filter = "resume"
            query = match.group(2).strip()

        # Example: Search operating system file with experiment 2
        if query is None:
            match = re.match(
                r"^(?:please\s+)?(?:search|find|look for)\s+"
                r"(.+?)\s+files?\s+(?:for|with|containing|mentioning)\s+"
                r"(.+?)\s*$",
                command_text,
                re.IGNORECASE,
            )

            if match:
                category_filter = match.group(1).strip()
                query = match.group(2).strip()

        # Example: Search files with Auralink
        if query is None:
            match = re.match(
                r"^(?:please\s+)?(?:search|find|look for)\s+"
                r"(?:all\s+)?files?\s+"
                r"(?:with|containing|that\s+contain|mentioning)\s+"
                r"(.+?)\s*$",
                command_text,
                re.IGNORECASE,
            )

            if match:
                query = match.group(1).strip()

        # Other explicit content-search forms
        if query is None:
            match = re.match(
                r"^(?:please\s+)?(?:find text|search content|"
                r"search inside|search within)\s+(.+?)"
                r"(?:\s+inside files?)?\s*$",
                command_text,
                re.IGNORECASE,
            )

            if match:
                query = match.group(1).strip()

        if query:
            query = re.sub(r"\s+", " ", query).strip(" .,!?:;")

        if not query and not (
            ranking_most or ranking_least or ranking_largest
        ):
            content_intent = False



    if content_intent:
        def extract_searchable_text(path):
            suffix = path.suffix.casefold()
            if suffix == ".pdf":
                reader = PdfReader(str(path))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            if suffix == ".docx":
                with zipfile.ZipFile(path) as archive:
                    xml_data = archive.read("word/document.xml")
                root = ET.fromstring(xml_data)
                return " ".join(
                    element.text or ""
                    for element in root.iter()
                    if element.tag.endswith("}t")
                )
            # Avoid reading very large source/log files into memory.
            if path.stat().st_size > 5 * 1024 * 1024:
                return ""
            return path.read_text(encoding="utf-8", errors="ignore")

        candidates = []
        scanned = 0
       

        for item in scan_pc_files():
            path = Path(item["path"])
            suffix = path.suffix.casefold()

            if suffix not in content_extensions:
                continue
            if extension_filter and suffix != extension_filter:
                continue

            if category_filter:
                category_tokens = re.findall(
                    r"[a-z0-9]+", category_filter.casefold()
                )
                filename_tokens = re.findall(
                    r"[a-z0-9]+", path.stem.casefold()
                )

                if not all(
                    token in filename_tokens
                    for token in category_tokens
                ):
                    continue

         

            scanned += 1
            if scanned > 2000:
                break

            try:
                safe_path = resolve_pc_file(str(path))
                extracted = extract_searchable_text(safe_path)
                normalized = re.sub(r"[^a-z0-9]+", "", extracted.casefold())

                # Ignore empty/unreadable content so it cannot win "least content".
                if not extracted.strip():
                    continue

                
                if query:
                    normalized_query = re.sub(
                        r"[^a-z0-9]+", "", query.casefold()
                    )
                    if not normalized_query or normalized_query not in normalized:
                        continue
                    occurrences = normalized.count(normalized_query)
                else:
                    occurrences = 0

                candidates.append({
                    "name": path.name,
                    "path": str(safe_path),
                    "extension": path.suffix.casefold(),
                    "size_bytes": safe_path.stat().st_size,
                    "words": len(extracted.split()),
                    "characters": len(extracted),
                    "occurrences": occurrences,
                    "preview": " ".join(extracted.split())[:240],
                })

            except Exception:
                continue

        if not candidates:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No supported file matched the content query: {query}"
                    if query else "No readable files matched the requested criteria."
                ),
            )

        
        if ranking_occurrences:
            candidates.sort(
                key=lambda item: item["occurrences"],
                reverse=True,
            )
        elif ranking_most:
            candidates.sort(key=lambda item: item["words"], reverse=True)
        elif ranking_least:
            candidates.sort(key=lambda item: item["words"])
        elif ranking_largest:
            candidates.sort(key=lambda item: item["size_bytes"], reverse=True)
        else:
            candidates.sort(key=lambda item: item["words"], reverse=True)


        if not wants_open:
            return {
                "command": command,
                "action": "search_file_content",
                "query": query,
                "count": len(candidates),
                "scanned_files": scanned,
                "results": candidates[:50],
                "read_only": True,
            }

        if len(candidates) > 1 and not (ranking_most or ranking_least or ranking_largest):
            return {
                "command": command,
                "action": "select_file",
                "selection_required": True,
                "message": "Multiple files match. Review the results before opening one.",
                "query": query,
                "results": candidates[:20],
                "read_only": True,
            }

        selected = candidates[0]
        opened = open_pc_file(OpenPcFileRequest(path=selected["path"]))
        return {
            "command": command,
            "action": "open_file_by_content",
            "query": query,
            "selection": selected,
            "scanned_files": scanned,
            "read_only_search": True,
            "result": opened,
        }

    # Open the latest matching file by modification date.
    latest_resume_request = (
        "resume" in lowered
        and any(word in lowered for word in (
            "latest", "last", "newest", "recent",
            "sabse nayi", "sabse latest"
        ))
        and any(word in lowered for word in (
            "open", "kholo", "khol", "khul"
        ))
    )

    if latest_resume_request:
        result = search_pc_files(query="resume", folder=None)
        matches = [
            item for item in result["matches"]
            if Path(item["name"]).suffix.casefold() in {
                ".pdf", ".doc", ".docx", ".odt"
            }
        ]

        if not matches:
            raise HTTPException(
                status_code=404,
                detail="No resume documents found in approved folders."
            )

        selected = max(
            matches,
            key=lambda item: item.get("modified_at", "")
        )

        opened = open_pc_file(OpenPcFileRequest(path=selected["path"]))
        return {
            "command": command,
            "action": "open_latest_resume",
            "result": opened,
        }

    # Open a named file, optionally restricted to an approved folder.
    folder_open_match = re.fullmatch(
        r"(.+?)\s+(?:mein|me|par|pe)\s+(.+?)\s+(?:open|kholo|khol|khul)(?:\s+kar)?",
        lowered,
    )

    if folder_open_match:
        folder_label = folder_open_match.group(1).strip()
        target = folder_open_match.group(2).strip()

        folder_aliases = {
            "desktop": "Desktop",
            "downloads": "Downloads",
            "documents": "Documents",
            "pictures": "Pictures",
            "videos": "Videos",
        }
        selected_folder = folder_aliases.get(folder_label)

        if selected_folder:
            result = search_pc_files(target, folder=selected_folder)
            matches = result["matches"]

            exact = [
                item for item in matches
                if item["name"].casefold() == target.casefold()
            ]

            if len(exact) == 1:
                selected = exact[0]
            elif len(matches) == 1:
                selected = matches[0]
            else:
                return {
                    "command": command,
                    "action": "select_file",
                    "selection_required": True,
                    "message": (
                        "No matching file found."
                        if not matches
                        else "Multiple files match. Choose the exact file path."
                    ),
                    "result": result,
                }

            opened = open_pc_file(OpenPcFileRequest(path=selected["path"]))
            return {
                "command": command,
                "action": "open_pc_file",
                "result": opened,
            }

    # Launch installed apps before treating "open <target>" as a file request.
    app_match = re.fullmatch(
        r"(?:open|launch|start|run|kholo|khol)\s+(.+)",
        command,
        flags=re.IGNORECASE,
    )
    if app_match:
        app_target = app_match.group(1).strip()
        try:
            app_result = launch_app(app_target)
            if app_result.get("launched") or app_result.get("ambiguous"):
                return {
                    "command": command,
                    "action": "launch_pc_app",
                    "result": app_result,
                }
        except LookupError:
            pass

    # Open a named file only if there is one unambiguous match.
    open_match = re.fullmatch(
        r"(?:open(?:\s+file)?|kholo|khol|khul)\s+(.+)",
        command,
        flags=re.IGNORECASE,
    )

    if open_match:
        target = open_match.group(1).strip()

        if target.casefold() in {
            "latest screenshot", "latest ss", "last screenshot",
            "last ss", "newest screenshot",
        }:
            screenshot = latest_pc_screenshot()
            opened = open_pc_file(OpenPcFileRequest(path=screenshot["path"]))
            return {
                "command": command,
                "action": "open_latest_screenshot",
                "result": opened,
            }

        result = search_pc_files(target)
        matches = result["matches"]

        exact = [
            item for item in matches
            if item["name"].casefold() == target.casefold()
        ]

        if len(exact) == 1:
            selected = exact[0]
        elif len(matches) == 1:
            selected = matches[0]
        else:
            return {
                "command": command,
                "action": "select_file",
                "selection_required": True,
                "message": (
                    "No matching file found."
                    if not matches
                    else "Multiple files match. Choose the exact file path."
                ),
                "result": result,
            }

        opened = open_pc_file(OpenPcFileRequest(path=selected["path"]))
        return {
            "command": command,
            "action": "open_pc_file",
            "result": opened,
        }

    # 1. System status
    if lowered in {"system status", "pc status", "check system"}:
        return {
            "command": command,
            "action": "system_status",
            "result": get_system_status(),
        }

    # 2. List approved project files
    if lowered in {"list files", "show files", "list project files"}:
        return {
            "command": command,
            "action": "list_files",
            "result": list_agent_files(),
        }

    # Generic content search: parse category and query from the command.
    content_match = re.fullmatch(
        r"(?:please\s+)?(?:search|find|look\s+for)\s+"
        r"(?:all\s+)?files?\s+"
        r"(?:with|containing|that\s+contain|mentioning)\s+(.+?)",
        command,
        flags=re.IGNORECASE,
    )

    if content_match:
        content_query = content_match.group(1).strip()
        content_command = f"Search files with {content_query}"
        return await run_agent_command(
            AgentCommandRequest(command=content_command)
        )

    content_match = re.fullmatch(
        r"(?:please\s+)?(?:search|find|look\s+for)\s+"
        r"(.+?)\s+(?:files?\s+)?"
        r"(?:for|with|containing|mentioning)\s+(.+?)",
        command,
        flags=re.IGNORECASE,
    )

    if content_match:
        category = re.sub(
            r"\s+files?$", "", content_match.group(1).strip(),
            flags=re.IGNORECASE,
        ).strip()
        content_query = content_match.group(2).strip()

        if category and content_query:
            content_command = (
                f"Search {category} files for {content_query}"
            )
            return await run_agent_command(
                AgentCommandRequest(command=content_command)
            )

    # 3. Search by filename
    match = re.fullmatch(
        r"(?:find|search)(?: file)?\s+(.+)",
        command,
        flags=re.IGNORECASE,
    )
    if match:
        query = match.group(1).strip()
        return {
            "command": command,
            "action": "search_files",
            "result": search_agent_files(query),
        }

    # 4. Read a text file within the approved project root
    match = re.fullmatch(
        r"read file\s+(.+)",
        command,
        flags=re.IGNORECASE,
    )
    if match:
        path = match.group(1).strip()
        return {
            "command": command,
            "action": "read_file",
            "result": read_agent_file(path),
        }

    # 5. Website QA
    match = re.fullmatch(
        r"test website\s+(https?://\S+)",
        command,
        flags=re.IGNORECASE,
    )
    if match:
        url = match.group(1).strip()
        try:
            request_model = WebsiteTestRequest(url=url)
        except Exception as error:
            raise HTTPException(status_code=422, detail="Invalid website URL.") from error

        return {
            "command": command,
            "action": "website_qa",
            "result": await test_website(request_model),
        }

    
    # Ollama fallback: interpret natural English, Hindi and Hinglish.
    import asyncio
    import json
    import urllib.request
    import urllib.error

    payload = {
        "model": "qwen2.5:3b",
        "stream": False,
        "format": "json",
        "keep_alive": "30s",
        "options": {"num_predict": 120, "temperature": 0},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Classify the user's request into JSON with keys "
                    "action, query, folder, app. "
                    "Allowed actions: search_files, open_file, launch_app, "
                    "system_info, chat, clarify. "
                    "Understand Hindi, English and Hinglish. "
                    "IMPORTANT: Use system_info ONLY when the user explicitly "
                    "asks about their PC/system status, CPU, RAM, disk, or hardware. "
                    "Never classify ordinary conversation, identity questions, "
                    "greetings, or farewells as system_info. "
                    "Use chat for general conversation and questions about VANTEX. "
                    "Never invent paths. "
                    "For search_files, provide a concise filename query. "
                    "For open_file, provide the requested filename. "
                    "For launch_app, use only a supported app name. "
                    "Use clarify only when an actionable request is genuinely ambiguous. "
                    "folder must be Desktop, Downloads, Documents, Pictures, "
                    "Videos or an empty string. Return valid JSON only."
                ),
            },
            {"role": "user", "content": command[:2000]},
        ],
    }

    try:
        encoded_payload = json.dumps(payload).encode("utf-8")

        def call_ollama_intent():
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/chat",
                data=encoded_payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))

        model_response = await asyncio.to_thread(call_ollama_intent)
        raw_intent = model_response.get("message", {}).get("content", "")
        intent = json.loads(raw_intent)

        action = intent.get("action")
        print(
            f"[VANTEX DEBUG] command={command!r} "
            f"classifier_intent={intent!r}",
            flush=True,
        )
        query = intent.get("query", "")
        folder = intent.get("folder", "")
        app = intent.get("app", "")

        if not all(isinstance(value, str) for value in (query, folder, app)):
            raise ValueError("Invalid intent parameters")

        if action == "search_files":
            if not query.strip():
                return {
                    "command": command,
                    "action": "clarify",
                    "message": "Which file should I search for?",
                }

            allowed_folders = {
                "Desktop", "Downloads", "Documents", "Pictures", "Videos"
            }
            selected_folder = folder if folder in allowed_folders else None

            result = search_pc_files(
                query.strip(),
                folder=selected_folder,
            )
            return {
                "command": command,
                "action": "search_pc_files",
                "result": result,
            }

        if action == "open_file":
            if not query.strip():
                return {
                    "command": command,
                    "action": "clarify",
                    "message": "Which file should I open?",
                }

            result = search_pc_files(query.strip())
            matches = result.get("matches", [])

            exact_matches = [
                item for item in matches
                if item.get("name", "").casefold() == query.strip().casefold()
            ]

            if len(exact_matches) == 1:
                selected = exact_matches[0]
            elif len(matches) == 1:
                selected = matches[0]
            else:
                return {
                    "command": command,
                    "action": "select_file",
                    "selection_required": True,
                    "message": (
                        "No matching file found."
                        if not matches
                        else "Multiple files matched. Select the correct file."
                    ),
                    "result": result,
                }

            opened = open_pc_file(
                OpenPcFileRequest(path=selected["path"])
            )
            return {
                "command": command,
                "action": "open_pc_file",
                "result": opened,
            }

        if action == "launch_app":
            allowed_apps = {
                "vscode", "vs code", "visual studio code",
                "terminal", "browser", "firefox", "chrome",
                "file manager", "files", "text editor", "mousepad",
                "libreoffice", "vlc",
            }
            app_name = app.strip().casefold()

            if app_name not in allowed_apps:
                return {
                    "command": command,
                    "action": "clarify",
                    "message": "Which supported application should I launch?",
                }

            return {
                "command": command,
                "action": "launch_pc_app",
                "result": _launch_pc_app(app_name),
            }

        if action == "system_info":
            return {
                "command": command,
                "action": "system_status",
                "result": get_system_status(),
            }

        if action == "chat":
            reply = await local_agent_chat(
                LocalChatRequest(message=command, history=[])
            )
            return {
                "command": command,
                "action": "chat",
                "message": reply.get("reply", ""),
                "result": reply,
            }

        # If intent classification is uncertain, treat the input as
        # natural conversation instead of failing with a generic message.
        reply = await local_agent_chat(
            LocalChatRequest(message=command, history=[])
        )
        return {
            "command": command,
            "action": "chat",
            "message": reply.get("reply", ""),
            "result": reply,
        }

    except HTTPException:
        raise
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is unavailable. Start Ollama and try again.",
        ) from exc
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Ollama returned an invalid intent. Please try again.",
        ) from exc




from fastapi import HTTPException

MONITOR_STATUS_PATH = (
    Path.home() / ".local" / "state" / "vantex" / "status.json"
)


@app.get("/api/agent/monitor/status")
def get_monitor_status():
    if not MONITOR_STATUS_PATH.is_file():
        raise HTTPException(
            status_code=503,
            detail="VANTEX monitor status is not available yet.",
        )

    try:
        import json

        with MONITOR_STATUS_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError):
        raise HTTPException(
            status_code=503,
            detail="Could not read VANTEX monitor status.",
        )


# VANTEX File Operator — separate read/search/open permissions
import subprocess
from datetime import datetime
from pydantic import BaseModel, Field

# File Operator roots: standard folders plus user-approved folders.
import json

PC_APPROVED_FOLDERS_FILE = Path.home() / ".config" / "vantex" / "approved_folders.json"

PC_FULL_ACCESS_FILE = Path.home() / ".config" / "vantex" / "full_pc_access.json"

def load_pc_file_roots():
    try:
        access_state = json.loads(PC_FULL_ACCESS_FILE.read_text(encoding="utf-8"))
        if isinstance(access_state, dict) and access_state.get("enabled") is True:
            return [Path.home().resolve()]
    except (OSError, ValueError, TypeError):
        pass

    roots = [
        (Path.home() / name).resolve()
        for name in ("Desktop", "Documents", "Downloads", "Pictures", "Videos")
        if (Path.home() / name).is_dir()
    ]
    try:
        saved = json.loads(PC_APPROVED_FOLDERS_FILE.read_text(encoding="utf-8"))
        if isinstance(saved, list):
            for raw in saved:
                if not isinstance(raw, str):
                    continue
                try:
                    candidate = Path(raw).expanduser().resolve(strict=True)
                    if (candidate.is_dir()
                            and candidate != Path(candidate.anchor)
                            and candidate != Path.home().resolve()
                            and candidate not in roots):
                        roots.append(candidate)
                except (OSError, RuntimeError):
                    continue
    except (OSError, ValueError, TypeError):
        pass
    return roots

PC_FILE_ROOTS = load_pc_file_roots()

class AllowAllPcFilesRequest(BaseModel):
    confirm: bool = False

@app.post("/api/agent/pc-files/allow-all")
def allow_all_pc_files(request: AllowAllPcFilesRequest):
    global PC_FILE_ROOTS
    if request.confirm is not True:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required.")

    try:
        PC_FULL_ACCESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PC_FULL_ACCESS_FILE.write_text(
            json.dumps({"enabled": True, "enabled_at": datetime.now().astimezone().isoformat()}, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not save access setting: {exc}") from exc

    PC_FILE_ROOTS = [Path.home().resolve()]
    return {
        "enabled": True,
        "mode": "user-home",
        "roots": [str(PC_FILE_ROOTS[0])],
        "message": "Full user-folder search/read access enabled. Restart is not required.",
    }


class ApproveFolderRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2000)

@app.post("/api/agent/pc-files/approve-folder")
def approve_pc_folder(request: ApproveFolderRequest):
    global PC_FILE_ROOTS
    candidate = Path(request.path).expanduser()
    try:
        if candidate.is_symlink():
            raise ValueError("Symlink folders cannot be approved.")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("Selected path is not a folder.")
        if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
            raise ValueError("Choose a specific folder, not the filesystem root or entire home folder.")
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Folder does not exist.") from exc

    if resolved not in PC_FILE_ROOTS:
        PC_FILE_ROOTS.append(resolved)

    try:
        PC_APPROVED_FOLDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        defaults = {
            (Path.home() / name).resolve()
            for name in ("Desktop", "Documents", "Downloads", "Pictures", "Videos")
            if (Path.home() / name).is_dir()
        }
        custom_roots = [str(root) for root in PC_FILE_ROOTS if root not in defaults]
        PC_APPROVED_FOLDERS_FILE.write_text(
            json.dumps(sorted(set(custom_roots)), indent=2), encoding="utf-8"
        )
    except OSError as exc:
        PC_FILE_ROOTS = load_pc_file_roots()
        raise HTTPException(status_code=500, detail=f"Could not save folder approval: {exc}") from exc

    return {"approved": True, "path": str(resolved),
            "message": f"Folder approved for file search and read: {resolved}",
            "approved_roots": [str(root) for root in PC_FILE_ROOTS]}

# Keep wl-copy alive while it owns the Wayland clipboard.


# Keep this variable at module level, outside the endpoint.
_CLIPBOARD_PROCESS = None


@app.post("/api/agent/pc-files/copy")
def copy_pc_file(request: ApproveFolderRequest):
    import os
    import shutil
    import subprocess
    import time
    from fastapi import HTTPException

    global _CLIPBOARD_PROCESS

    # Resolve and validate the original file.
    try:
        safe_path = resolve_pc_file(request.path)
        if not safe_path.is_file():
            raise HTTPException(status_code=404, detail="File not found.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file path: {exc}",
        ) from exc

    # Ensure this backend can access the current Wayland session.
    wl_copy = shutil.which("wl-copy")
    wl_paste = shutil.which("wl-paste")

    if not wl_copy or not wl_paste:
        raise HTTPException(
            status_code=503,
            detail="Clipboard tools missing. Install them with: sudo apt install wl-clipboard",
        )

    if not os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("XDG_RUNTIME_DIR"):
        raise HTTPException(
            status_code=503,
            detail=(
                "The backend cannot access the Wayland desktop session. "
                "Start VANTEX from your logged-in desktop terminal."
            ),
        )

    # Standard URI-list format for file managers.
    expected_uri = safe_path.as_uri()
    payload = (expected_uri + "\r\n").encode("utf-8")

    try:
        # Release the clipboard held by the previous VANTEX copy operation.
        if (
            _CLIPBOARD_PROCESS is not None
            and _CLIPBOARD_PROCESS.poll() is None
        ):
            _CLIPBOARD_PROCESS.terminate()
            try:
                _CLIPBOARD_PROCESS.wait(timeout=1)
            except subprocess.TimeoutExpired:
                _CLIPBOARD_PROCESS.kill()
                _CLIPBOARD_PROCESS.wait(timeout=2)

        # Keep wl-copy running so it continues to own the clipboard.
        process = subprocess.Popen(
            [
                wl_copy,
                "--foreground",
                "--type",
                "text/uri-list",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
        _CLIPBOARD_PROCESS = process

        if process.stdin is None:
            raise RuntimeError("Could not open clipboard input.")

        try:
            process.stdin.write(payload)
            process.stdin.close()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(
                "wl-copy stopped before receiving the file URI."
            ) from exc

        # Allow Wayland to register the new clipboard owner.
        time.sleep(0.25)

        if process.poll() is not None:
            _CLIPBOARD_PROCESS = None
            raise RuntimeError(
                "wl-copy exited early. Check that the Wayland session is accessible."
            )

        # Verify the clipboard really contains the expected file URI.
        check = subprocess.run(
            [
                wl_paste,
                "--type",
                "text/uri-list",
                "--no-newline",
            ],
            capture_output=True,
            timeout=3,
            env=os.environ.copy(),
        )

        actual_uri = check.stdout.decode("utf-8", errors="replace").strip()

        if check.returncode != 0 or actual_uri != expected_uri:
            raise RuntimeError(
                "Clipboard verification failed: the expected file URI "
                "was not found. Another application may have replaced it, "
                "or the desktop clipboard is inaccessible."
            )

        return {
            "copied": True,
            "path": str(safe_path),
            "message": (
                "File URI verified on the system clipboard. "
                "Try Ctrl+V in your file manager."
            ),
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"File clipboard copy failed: {exc}",
        ) from exc


@app.get("/api/agent/pc-files/read")
def read_pc_file(path: str = Query(min_length=1, max_length=2000)):
    safe_path = resolve_pc_file(path)
    if safe_path.stat().st_size > MAX_READ_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 1 MB read limit.")
    try:
        content = safe_path.read_bytes()
        if b"\x00" in content:
            raise HTTPException(status_code=415, detail="Binary files cannot be copied as text.")
        text_content = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="File is not valid UTF-8 text; use a file attachment instead.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Permission denied.") from exc
    return {"path": str(safe_path), "size_bytes": len(content),
            "content": text_content, "read_only": True}

PC_SKIP_DIRS = {"venv", "env", ".tox", 
    ".git", ".venv", "node_modules", "__pycache__",
    "dist", "build", ".cache", ".local"
}

PC_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
PC_SCAN_LIMIT = 20000


def resolve_pc_file(raw_path: str) -> Path:
    """Resolve a file only inside approved personal folders."""
    candidate = Path(raw_path).expanduser()

    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError("Not a regular file")

        if not any(
            resolved.is_relative_to(root)
            for root in PC_FILE_ROOTS
        ):
            raise ValueError("Outside approved folders")

        return resolved
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(
            status_code=403,
            detail="File is missing or outside VANTEX approved folders."
        )


def scan_pc_files():
    """Scan approved folders with an independent limit per top-level folder."""
    home = Path.home().resolve()
    skip_dirs = PC_SKIP_DIRS | {".config"}

    targets = []
    seen_targets = set()

    def add_target(path, direct_only=False):
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_dir() or resolved.is_symlink():
                return
            key = (str(resolved), direct_only)
            if key not in seen_targets:
                seen_targets.add(key)
                targets.append((resolved, direct_only))
        except (OSError, RuntimeError):
            return

    for approved_root in PC_FILE_ROOTS:
        try:
            root = approved_root.resolve(strict=True)
        except (OSError, RuntimeError):
            continue

        if root == home:
            # Scan files directly in the home folder separately.
            add_target(root, direct_only=True)

            # Give each top-level folder its own scan budget.
            try:
                children = sorted(root.iterdir(), key=lambda p: p.name.casefold())
            except OSError:
                children = []

            for child in children:
                if (
                    child.name.startswith(".")
                    or child.name in skip_dirs
                    or child.is_symlink()
                ):
                    continue
                add_target(child)
        else:
            add_target(root)

    for root, direct_only in targets:
        scanned = 0

        for current, dirs, files in os.walk(root, followlinks=False):
            current_path = Path(current)

            if direct_only and current_path == root:
                dirs[:] = []
            else:
                dirs[:] = [
                    name for name in dirs
                    if name not in skip_dirs
                    and not name.startswith(".")
                    and not (current_path / name).is_symlink()
                ]

            for name in files:
                candidate = current_path / name

                if name.startswith(".") or candidate.is_symlink():
                    continue

                scanned += 1
                if scanned > PC_SCAN_LIMIT:
                    dirs[:] = []
                    break

                try:
                    resolved = candidate.resolve(strict=True)

                    if not any(
                        resolved.is_relative_to(approved_root)
                        for approved_root in PC_FILE_ROOTS
                    ):
                        continue

                    stat = resolved.stat()
                    if not resolved.is_file():
                        continue

                    yield {
                        "name": resolved.name,
                        "path": str(resolved),
                        "size_bytes": stat.st_size,
                        "modified_at": datetime.fromtimestamp(
                            stat.st_mtime
                        ).astimezone().isoformat(),
                        "_mtime": stat.st_mtime,
                    }
                except (OSError, ValueError, RuntimeError):
                    continue


def calculate_file_sha256(file_path: str) -> str:
    """Read a file in chunks and return its SHA-256 hash."""
    digest = hashlib.sha256()

    with open(file_path, "rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


@app.get("/api/agent/pc-files/duplicates")
def find_pc_file_duplicates(
    min_size_bytes: int = Query(default=1, ge=1),
):
    """
    Read-only duplicate scan.
    Files are considered duplicates only when size and SHA-256 match.
    No files are moved, edited, or deleted.
    """
    candidates_by_size = {}

    for item in scan_pc_files():
        size = item["size_bytes"]

        if size < min_size_bytes:
            continue

        candidates_by_size.setdefault(size, []).append(item)

    duplicate_groups = []
    files_hashed = 0
    bytes_hashed = 0

    for size, items in candidates_by_size.items():
        if len(items) < 2:
            continue

        candidates_by_hash = {}

        for item in items:
            try:
                current_path = resolve_pc_file(item["path"])

                # Avoid hashing a file that changed after the scan.
                if current_path.stat().st_size != size:
                    continue

                file_hash = calculate_file_sha256(str(current_path))
                files_hashed += 1
                bytes_hashed += size

                candidates_by_hash.setdefault(file_hash, []).append(item)

            except (OSError, ValueError, RuntimeError, HTTPException):
                continue

        for file_hash, group in candidates_by_hash.items():
            if len(group) < 2:
                continue

            for item in group:
                item.pop("_mtime", None)

            duplicate_groups.append({
                "sha256": file_hash,
                "size_bytes": size,
                "copies": len(group),
                "files": sorted(group, key=lambda item: item["path"]),
            })

    duplicate_groups.sort(
        key=lambda group: (
            group["size_bytes"] * (group["copies"] - 1),
            group["size_bytes"],
        ),
        reverse=True,
    )

    return {
        "read_only": True,
        "files_hashed": files_hashed,
        "bytes_hashed": bytes_hashed,
        "duplicate_groups": duplicate_groups,
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_copy_count": sum(
            group["copies"] for group in duplicate_groups
        ),
        "potential_reclaimable_bytes": sum(
            group["size_bytes"] * (group["copies"] - 1)
            for group in duplicate_groups
        ),
        "note": "No files were modified or deleted.",
    }



@app.get("/api/agent/pc-files/search-content")
def search_pc_pdf_content(
    query: str = Query(min_length=1, max_length=200),
    folder: str | None = Query(default=None, max_length=50),
):
    """Read-only search inside text-based PDF files in approved PC folders."""
    from pypdf import PdfReader

    needle = re.sub(r"[^a-z0-9]", "", query.casefold())
    if not needle:
        raise HTTPException(status_code=400, detail="Search query is empty.")

    allowed = {
        "desktop": "Desktop",
        "downloads": "Downloads",
        "documents": "Documents",
        "pictures": "Pictures",
        "videos": "Videos",
    }
    selected_folder = None
    if folder:
        selected_folder = allowed.get(folder.strip().casefold())
        if selected_folder is None:
            raise HTTPException(status_code=400, detail="Unsupported folder.")

    matches = []
    scanned = 0

    for item in scan_pc_files():
        path = Path(item["path"])
        if path.suffix.casefold() != ".pdf":
            continue

        if selected_folder and path.parts[len(Path.home().parts)] != selected_folder:
            continue

        scanned += 1
        if scanned > 500:
            break

        try:
            safe_path = resolve_pc_file(str(path))
            reader = PdfReader(str(safe_path))
            extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
            normalized = re.sub(r"[^a-z0-9]", "", extracted.casefold())

            if needle in normalized:
                matches.append({
                    "name": path.name,
                    "path": str(path),
                    "pages": len(reader.pages),
                    "characters": len(extracted),
                    "words": len(extracted.split()),
                })
        except Exception:
            continue

    return {
        "query": query,
        "folder": selected_folder,
        "scanned_pdfs": scanned,
        "count": len(matches),
        "matches": matches,
        "read_only": True,
    }


@app.get("/api/agent/pc-files/search")
def search_pc_files(
    query: str = Query(min_length=1, max_length=200),
    folder: str | None = Query(default=None, max_length=50),
):
    needle = query.strip().casefold()
    if not needle:
        raise HTTPException(status_code=400, detail="Search query is empty.")

    query_tokens = re.findall(r"[a-z0-9]+", needle)
    matches = []

        # Recognize natural-language file-type searches.
   
    extension_aliases = {
        "python": {".py"},
        "javascript": {".js", ".jsx", ".mjs", ".cjs"},
        "typescript": {".ts", ".tsx", ".mts", ".cts"},
        "css": {".css"},
        "html": {".html", ".htm"},
        "json": {".json"},
        "pdf": {".pdf"},
        "markdown": {".md", ".markdown"},
        "text": {".txt"},
        "docs": {
            ".pdf", ".doc", ".docx", ".odt", ".rtf",
            ".txt", ".md", ".markdown", ".rst",
        },
        "document": {
            ".pdf", ".doc", ".docx", ".odt", ".rtf",
            ".txt", ".md", ".markdown", ".rst",
        },
        "documents": {
            ".pdf", ".doc", ".docx", ".odt", ".rtf",
            ".txt", ".md", ".markdown", ".rst",
        },
        "image": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"},
        "images": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"},
        "png": {".png"},
        "jpg": {".jpg", ".jpeg"},
        "jpeg": {".jpeg", ".jpg"},
        "webp": {".webp"},
        "gif": {".gif"},
        "bmp": {".bmp"},
        "svg": {".svg"},
    }

    requested_extensions = None

    type_match = re.fullmatch(
        r"(?:all\s+)?\.?"
        r"(python|javascript|typescript|css|html|json|pdf|markdown|text|"
        r"docs|documents|document|images|image|png|jpg|jpeg|webp|gif|bmp|svg)"
        r"(?:\s+(?:source\s+)?files?)?",
        needle,
    )

    if type_match:
        requested_extensions = extension_aliases[type_match.group(1)]


    requested_extensions = None
    type_match = re.fullmatch(
        r"(?:all\s+)?(python|javascript|typescript|css|html|json|pdf|markdown|text)"
        r"(?:\s+(?:source\s+)?files?)?",
        needle,
    )

    if type_match:
        requested_extensions = extension_aliases[type_match.group(1)]

    allowed_folder_names = {
        "desktop": "Desktop",
        "downloads": "Downloads",
        "documents": "Documents",
        "pictures": "Pictures",
        "videos": "Videos",
    }

    selected_folder = None
    if folder:
        selected_folder = allowed_folder_names.get(folder.strip().casefold())
        if selected_folder is None:
            raise HTTPException(
                status_code=400,
                detail="Unsupported folder. Use Desktop, Downloads, Documents, Pictures, or Videos."
            )

    for item in scan_pc_files():
        if selected_folder and Path(item["path"]).parts[
            len(Path.home().parts)
        ] != selected_folder:
            continue

        if requested_extensions is not None:
            if Path(item["name"]).suffix.casefold() not in requested_extensions:
                continue

        filename = item["name"].casefold()
        filename_tokens = re.findall(r"[a-z0-9]+", filename)
        stem = Path(filename).stem
        stem_tokens = re.findall(r"[a-z0-9]+", stem)

        if not query_tokens:
            continue

        matched_tokens = sum(
            1 for token in query_tokens
            if token in filename_tokens
        )

        if requested_extensions is None:
            if matched_tokens != len(query_tokens):
                continue

        if needle in filename:
            score = 100
        else:
            score = 80

        # Prefer matching the main filename over an extension-only match.
        if all(token in stem_tokens for token in query_tokens):
            score += 10

        # Small boost for common document types.
        if Path(filename).suffix in {".pdf", ".doc", ".docx", ".odt"}:
            score += 2

        item["_score"] = score
        matches.append(item)

    # Relevance first; newer files break ties.
    matches.sort(
        key=lambda item: (item["_score"], item.get("_mtime", 0)),
        reverse=True,
    )

    for item in matches:
        item.pop("_mtime", None)
        item.pop("_score", None)

    return {
        "query": query,
        "folder": selected_folder,
        "roots": (
            [str(root) for root in PC_FILE_ROOTS
             if not selected_folder or root.name == selected_folder]
        ),
        "matches": matches[:100],
        "count": min(len(matches), 100),
        "scan_limit": PC_SCAN_LIMIT,
        "sorted_by": "relevance_then_modified_date",
    }


@app.get("/api/agent/pc-files/latest-screenshot")
def latest_pc_screenshot():
    screenshots = []

    for item in scan_pc_files():
        name = item["name"].casefold()
        path = item["path"].casefold()

        is_screenshot = (
            item["name"].lower().endswith(tuple(PC_IMAGE_EXTENSIONS))
            and (
                "screenshot" in name
                or "screen shot" in name
                or "screenshots" in path
            )
        )

        if is_screenshot:
            screenshots.append(item)

    if not screenshots:
        raise HTTPException(
            status_code=404,
            detail="No screenshots found in approved folders."
        )

    latest = max(screenshots, key=lambda item: item["_mtime"])
    latest.pop("_mtime", None)
    return latest


class OpenPcFileRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2000)


@app.post("/api/agent/pc-files/open")
def open_pc_file(request: OpenPcFileRequest):
    file_path = resolve_pc_file(request.path)

    try:
        subprocess.Popen(
            ["xdg-open", str(file_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not launch the default application: {error}"
        ) from error

    return {
        "opened": True,
        "name": file_path.name,
        "path": str(file_path),
        "message": "Open request sent to the default desktop application."
    }
