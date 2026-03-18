#!/usr/bin/env python3
"""
Ergate API Demo CLI

Interactive command-line tool demonstrating every Ergate API endpoint.
Supports the full proposal lifecycle: create, analyze, generate, score, export.
Also covers webhooks management, usage tracking, and file operations.

Usage:
    python scripts/ergate-api-demo.py

Environment variables (or set interactively):
    ERGATE_API_URL      Base URL (default: https://ergate.ai/api/v1)
    ERGATE_API_KEY      Your API key (ek_live_...)
    ERGATE_API_SECRET   Your API secret (es_live_...)
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Optional
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_URL = os.environ.get("ERGATE_API_URL", "https://ergate.ai/api/v1")
API_KEY = os.environ.get("ERGATE_API_KEY", "")
API_SECRET = os.environ.get("ERGATE_API_SECRET", "")


def configure():
    """Prompt for credentials if not set via environment."""
    global API_URL, API_KEY, API_SECRET

    if not API_KEY:
        API_KEY = input("API Key (X-API-Key): ").strip()
    if not API_SECRET:
        API_SECRET = input("API Secret (X-API-Secret): ").strip()

    # Only prompt for URL if credentials were also missing (fully interactive mode)
    if not os.environ.get("ERGATE_API_KEY"):
        url = input(f"API Base URL [{API_URL}]: ").strip()
        if url:
            API_URL = url.rstrip("/")

    print(f"\n  Base URL : {API_URL}")
    print(f"  API Key  : {API_KEY[:12]}...")
    print()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def api(
    method: str,
    path: str,
    body: Optional[dict] = None,
    query: Optional[dict] = None,
) -> dict:
    """Make an authenticated API request and return the parsed JSON response."""
    url = f"{API_URL}{path}"
    if query:
        filtered = {k: v for k, v in query.items() if v is not None}
        if filtered:
            url += "?" + urlencode(filtered)

    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-API-Key", API_KEY)
    req.add_header("X-API-Secret", API_SECRET)

    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        raw = e.read().decode()
        try:
            err = json.loads(raw)
        except json.JSONDecodeError:
            err = {"raw": raw}
        print(f"\n  ERROR {e.code}: {json.dumps(err, indent=2)}")
        return err


def pp(data: Any) -> None:
    """Pretty-print JSON data."""
    print(json.dumps(data, indent=2, default=str))


def wait_for_status(
    proposal_id: str, target: str, timeout: int = 120,
    check_field: Optional[str] = None,
) -> Optional[dict]:
    """Poll a proposal until it reaches the target status.

    If check_field is set, waits for that field to be non-null on the proposal
    (used when status returns to 'draft' but a result field gets populated).
    """
    label = f"field '{check_field}'" if check_field else f"status '{target}'"
    print(f"  Waiting for {label}", end="", flush=True)
    start = time.time()
    prev_status = None
    while time.time() - start < timeout:
        result = api("GET", f"/proposals/{proposal_id}")
        data = result.get("data", {})
        status = data.get("status")

        if check_field:
            # Wait for the field to become non-null (status may return to draft)
            if data.get(check_field) is not None and status != "analyzing":
                print(f" done ({int(time.time() - start)}s)")
                return data
        else:
            if status == target:
                print(f" done ({int(time.time() - start)}s)")
                return data
            if status == "draft" and prev_status and prev_status != "draft":
                print(f" FAILED (reset to draft)")
                return None

        prev_status = status
        print(".", end="", flush=True)
        time.sleep(3)
    print(f" TIMEOUT after {timeout}s")
    return None


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def cmd_usage():
    """GET /usage — Show current plan and usage."""
    print("\n--- Usage ---")
    result = api("GET", "/usage")
    if "data" in result:
        d = result["data"]
        print(f"  Plan           : {d.get('plan', '?')}")
        print(f"  Proposals used : {d.get('proposalsUsed', '?')} / {d.get('proposalsLimit', '?')}")
        print(f"  Addon credits  : {d.get('addonCredits', 0)}")
        print(f"  Period start   : {d.get('periodStart', '—')}")
        print(f"  Period end     : {d.get('periodEnd', '—')}")
    return result


def cmd_list_proposals():
    """GET /proposals — List proposals with pagination."""
    print("\n--- List Proposals ---")
    page = input("  Page [1]: ").strip() or "1"
    limit = input("  Limit [10]: ").strip() or "10"
    status = input("  Status filter (blank for all): ").strip() or None

    result = api("GET", "/proposals", query={
        "page": page,
        "limit": limit,
        "status": status,
    })
    if "data" in result:
        proposals = result["data"]
        meta = result.get("meta", {})
        print(f"\n  Showing {len(proposals)} of {meta.get('total', '?')} proposals (page {meta.get('page', page)})\n")
        for p in proposals:
            print(f"  [{p['status']:12s}] {p['id'][:8]}...  {p.get('title', 'Untitled')}")
        if not proposals:
            print("  (no proposals found)")
    return result


def cmd_create_proposal():
    """POST /proposals — Create a new draft proposal."""
    print("\n--- Create Proposal ---")
    title = input("  Title [Demo Proposal]: ").strip() or "Demo Proposal"
    print("  Enter the client brief (press Enter twice to finish):")
    lines = []
    while True:
        line = input("  > ")
        if line == "":
            if lines:
                break
            continue
        lines.append(line)

    if not lines:
        brief = (
            "We need a complete redesign of our e-commerce website. "
            "Current site has 50k monthly visitors, built on WordPress. "
            "Budget range: $10,000-$20,000. Timeline: 6-8 weeks. "
            "Must include mobile-first responsive design, Stripe integration, "
            "and a new product catalog with filtering and search."
        )
        print(f"  (using default brief)")
    else:
        brief = "\n".join(lines)

    client_id = input("  Client ID (blank to skip): ").strip() or None

    body = {
        "title": title,
        "rawInputText": brief,
        "rawInputMethod": "paste",
    }
    if client_id:
        body["clientId"] = client_id

    result = api("POST", "/proposals", body)
    if "data" in result:
        p = result["data"]
        print(f"\n  Created proposal: {p['id']}")
        print(f"  Status: {p['status']}")
    return result


def cmd_get_proposal():
    """GET /proposals/:id — Get full proposal detail."""
    print("\n--- Get Proposal ---")
    pid = input("  Proposal ID: ").strip()
    if not pid:
        print("  Cancelled.")
        return None

    result = api("GET", f"/proposals/{pid}")
    if "data" in result:
        d = result["data"]
        print(f"\n  Title    : {d.get('title', '—')}")
        print(f"  Status   : {d.get('status', '—')}")
        print(f"  Score    : {d.get('proposalScore', '—')}")
        print(f"  Pricing  : {d.get('pricingModel', '—')}  |  "
              f"Low: {d.get('totalPriceLow', '—')}  "
              f"Mid: {d.get('totalPriceMid', '—')}  "
              f"High: {d.get('totalPriceHigh', '—')}")
        print(f"  Duration : {d.get('estimatedDurationDays', '—')} days")
        print(f"  Outcome  : {d.get('outcome', '—')}")
        md = d.get("generatedProposalMarkdown")
        if md:
            preview = md[:200].replace("\n", " ")
            print(f"  Preview  : {preview}...")
    return result


def cmd_update_proposal():
    """PATCH /proposals/:id — Update a proposal."""
    print("\n--- Update Proposal ---")
    pid = input("  Proposal ID: ").strip()
    if not pid:
        print("  Cancelled.")
        return None

    print("  Fields to update (leave blank to skip):")
    title = input("    New title: ").strip() or None
    pricing_model = input("    Pricing model (hourly/fixed/milestone/retainer): ").strip() or None
    final_price = input("    Final price (cents): ").strip() or None
    outcome = input("    Outcome (won/lost/no_response/cancelled): ").strip() or None

    body = {}
    if title:
        body["title"] = title
    if pricing_model:
        body["pricingModel"] = pricing_model
    if final_price:
        body["finalPrice"] = int(final_price)
    if outcome:
        body["outcome"] = outcome

    if not body:
        print("  Nothing to update.")
        return None

    result = api("PATCH", f"/proposals/{pid}", body)
    if "data" in result:
        print(f"  Updated. Status: {result['data'].get('status')}")
    return result


def cmd_archive_proposal():
    """DELETE /proposals/:id — Archive a proposal."""
    print("\n--- Archive Proposal ---")
    pid = input("  Proposal ID: ").strip()
    if not pid:
        print("  Cancelled.")
        return None

    result = api("DELETE", f"/proposals/{pid}")
    if "data" in result:
        print(f"  Archived: {result['data'].get('id')}")
    return result


def cmd_analyze():
    """POST /proposals/:id/analyze — Trigger AI analysis."""
    print("\n--- Analyze Proposal ---")
    pid = input("  Proposal ID: ").strip()
    if not pid:
        print("  Cancelled.")
        return None

    result = api("POST", f"/proposals/{pid}/analyze")
    if "data" in result:
        print(f"  Status: {result['data'].get('status')} (202 Accepted)")
        wait = input("  Wait for completion? [y/N]: ").strip().lower()
        if wait == "y":
            wait_for_status(pid, "draft", check_field="analysisSummary")
    return result


def cmd_generate():
    """POST /proposals/:id/generate — Trigger proposal generation."""
    print("\n--- Generate Proposal ---")
    pid = input("  Proposal ID: ").strip()
    if not pid:
        print("  Cancelled.")
        return None

    result = api("POST", f"/proposals/{pid}/generate")
    if "data" in result:
        print(f"  Status: {result['data'].get('status')} (202 Accepted)")
        wait = input("  Wait for completion? [y/N]: ").strip().lower()
        if wait == "y":
            wait_for_status(pid, "ready")
    return result


def cmd_score():
    """POST /proposals/:id/score — Trigger proposal scoring."""
    print("\n--- Score Proposal ---")
    pid = input("  Proposal ID: ").strip()
    if not pid:
        print("  Cancelled.")
        return None

    result = api("POST", f"/proposals/{pid}/score")
    if "data" in result:
        print(f"  Status: {result['data'].get('status')} (202 Accepted)")
        wait = input("  Wait for completion? [y/N]: ").strip().lower()
        if wait == "y":
            time.sleep(5)
            detail = api("GET", f"/proposals/{pid}")
            if "data" in detail:
                score = detail["data"].get("proposalScore")
                print(f"  Score: {score}/100" if score else "  Score: not yet available")
    return result


def cmd_export():
    """POST /proposals/:id/export — Export to PDF/DOCX/PPTX."""
    print("\n--- Export Proposal ---")
    pid = input("  Proposal ID: ").strip()
    if not pid:
        print("  Cancelled.")
        return None

    fmt = input("  Format (pdf/docx/pptx) [pdf]: ").strip() or "pdf"

    result = api("POST", f"/proposals/{pid}/export", {"format": fmt})
    if "data" in result:
        d = result["data"]
        print(f"\n  Format      : {d.get('format')}")
        print(f"  Download URL: {d.get('downloadUrl')}")
        print(f"  Expires at  : {d.get('expiresAt')}")
    return result


def cmd_full_pipeline():
    """Run the full pipeline: create -> analyze -> generate -> score -> export."""
    print("\n--- Full Pipeline Demo ---")
    print("  This will create a proposal with a sample brief and run all stages.\n")

    # Create
    body = {
        "title": "E-Commerce Platform Redesign",
        "rawInputText": (
            "We need a complete redesign of our e-commerce platform. "
            "The current site runs on WordPress with WooCommerce and serves "
            "approximately 50,000 monthly visitors. We want to migrate to a "
            "modern tech stack with Next.js frontend and headless CMS. "
            "Key requirements: mobile-first responsive design, Stripe payment "
            "integration, product catalog with faceted search and filtering, "
            "user accounts with order history, admin dashboard for inventory. "
            "Budget range is $10,000 to $20,000. Timeline: 6-8 weeks. "
            "We need the site to handle Black Friday traffic (3x normal load)."
        ),
        "rawInputMethod": "paste",
    }

    print("  [1/5] Creating proposal...")
    result = api("POST", "/proposals", body)
    if "data" not in result:
        print("  Failed to create proposal.")
        return
    pid = result["data"]["id"]
    print(f"        ID: {pid}")

    # Analyze (status goes: draft -> analyzing -> draft, with analysisResult populated)
    print("  [2/5] Starting analysis...")
    api("POST", f"/proposals/{pid}/analyze")
    proposal = wait_for_status(pid, "draft", timeout=180, check_field="analysisSummary")
    if not proposal:
        print("  Analysis failed or timed out.")
        return

    # Generate
    print("  [3/5] Starting generation...")
    api("POST", f"/proposals/{pid}/generate")
    proposal = wait_for_status(pid, "ready", timeout=180)
    if not proposal:
        print("  Generation failed or timed out.")
        return

    # Score
    print("  [4/5] Starting scoring...")
    api("POST", f"/proposals/{pid}/score")
    time.sleep(8)
    detail = api("GET", f"/proposals/{pid}")
    if "data" in detail:
        d = detail["data"]
        print(f"        Score: {d.get('proposalScore', 'pending')}/100")

    # Export
    print("  [5/5] Exporting to PDF...")
    export = api("POST", f"/proposals/{pid}/export", {"format": "pdf"})
    if "data" in export:
        print(f"        Download: {export['data'].get('downloadUrl')}")

    print(f"\n  Pipeline complete! Proposal ID: {pid}")
    return pid


# ---------------------------------------------------------------------------
# Webhook commands
# ---------------------------------------------------------------------------


def cmd_list_webhooks():
    """GET /webhooks — List webhook endpoints."""
    print("\n--- Webhook Endpoints ---")
    result = api("GET", "/webhooks")
    if "data" in result:
        endpoints = result["data"]
        print(f"  {len(endpoints)} endpoint(s)\n")
        for ep in endpoints:
            status = "active" if ep.get("isActive") else "disabled"
            print(f"  [{status:8s}] {ep['id'][:8]}...  {ep.get('url', '—')}")
            print(f"             Events: {', '.join(ep.get('events', []))}")
            print(f"             Failures: {ep.get('failureCount', 0)}")
            print()
        if not endpoints:
            print("  (no endpoints registered)")
    return result


def cmd_create_webhook():
    """POST /webhooks — Register a new webhook endpoint."""
    print("\n--- Create Webhook Endpoint ---")
    url = input("  URL (must be HTTPS): ").strip()
    if not url:
        print("  Cancelled.")
        return None

    print("  Available events:")
    all_events = [
        "proposal.created", "proposal.updated",
        "proposal.analysis_completed", "proposal.analysis_failed",
        "proposal.generation_completed", "proposal.generation_failed",
        "proposal.scoring_completed", "proposal.scoring_failed",
        "proposal.exported", "proposal.outcome_recorded",
    ]
    for i, evt in enumerate(all_events, 1):
        print(f"    {i:2d}. {evt}")

    selected = input("  Select events (comma-separated numbers, or 'all'): ").strip()
    if selected.lower() == "all":
        events = all_events
    else:
        indices = [int(x.strip()) - 1 for x in selected.split(",") if x.strip().isdigit()]
        events = [all_events[i] for i in indices if 0 <= i < len(all_events)]

    if not events:
        print("  No events selected.")
        return None

    sources_input = input("  Sources (ui/api/both) [both]: ").strip().lower() or "both"
    if sources_input == "ui":
        sources = ["ui"]
    elif sources_input == "api":
        sources = ["api"]
    else:
        sources = ["ui", "api"]

    result = api("POST", "/webhooks", {
        "url": url,
        "events": events,
        "sources": sources,
    })
    if "data" in result:
        d = result["data"]
        print(f"\n  Created endpoint: {d['id']}")
        print(f"  Secret: {d.get('secret', '—')}")
        print(f"  IMPORTANT: Save the secret above — it won't be shown again!")
    return result


def cmd_update_webhook():
    """PATCH /webhooks/:id — Update a webhook endpoint."""
    print("\n--- Update Webhook Endpoint ---")
    eid = input("  Endpoint ID: ").strip()
    if not eid:
        print("  Cancelled.")
        return None

    print("  Fields to update (leave blank to skip):")
    url = input("    New URL: ").strip() or None
    active = input("    Set active (true/false): ").strip() or None

    body = {}
    if url:
        body["url"] = url
    if active:
        body["isActive"] = active.lower() == "true"

    if not body:
        print("  Nothing to update.")
        return None

    result = api("PATCH", f"/webhooks/{eid}", body)
    if "data" in result:
        print(f"  Updated endpoint: {result['data'].get('id')}")
    return result


def cmd_delete_webhook():
    """DELETE /webhooks/:id — Delete a webhook endpoint."""
    print("\n--- Delete Webhook Endpoint ---")
    eid = input("  Endpoint ID: ").strip()
    if not eid:
        print("  Cancelled.")
        return None

    result = api("DELETE", f"/webhooks/{eid}")
    if "data" in result:
        print(f"  Deleted: {result['data'].get('id')}")
    return result


def cmd_test_webhook():
    """POST /webhooks/:id/test — Send a test ping."""
    print("\n--- Test Webhook ---")
    eid = input("  Endpoint ID: ").strip()
    if not eid:
        print("  Cancelled.")
        return None

    result = api("POST", f"/webhooks/{eid}/test")
    if "data" in result:
        d = result["data"]
        status = "SUCCESS" if d.get("success") else "FAILED"
        print(f"  Result     : {status}")
        print(f"  HTTP Status: {d.get('httpStatus', '—')}")
        if d.get("error"):
            print(f"  Error      : {d['error']}")
    return result


def cmd_webhook_events():
    """GET /webhooks/events — Query the webhook event log."""
    print("\n--- Webhook Event Log ---")
    endpoint_id = input("  Endpoint ID (blank for all): ").strip() or None
    status = input("  Status filter (pending/delivered/failed/expired, blank for all): ").strip() or None
    limit = input("  Limit [10]: ").strip() or "10"

    result = api("GET", "/webhooks/events", query={
        "endpointId": endpoint_id,
        "status": status,
        "limit": limit,
    })
    if "data" in result:
        events = result["data"]
        meta = result.get("meta", {})
        print(f"\n  Showing {len(events)} of {meta.get('total', '?')} events\n")
        for evt in events:
            print(f"  [{evt.get('status', '?'):10s}] {evt['id'][:8]}...  "
                  f"{evt.get('eventType', '—')}  "
                  f"attempts={evt.get('attempts', 0)}  "
                  f"http={evt.get('httpStatus', '—')}")
        if not events:
            print("  (no events found)")
    return result


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

COMMANDS = {
    # Proposals
    "1":  ("List proposals",          cmd_list_proposals),
    "2":  ("Create proposal",         cmd_create_proposal),
    "3":  ("Get proposal detail",     cmd_get_proposal),
    "4":  ("Update proposal",         cmd_update_proposal),
    "5":  ("Archive proposal",        cmd_archive_proposal),
    # Pipeline
    "6":  ("Analyze proposal",        cmd_analyze),
    "7":  ("Generate proposal",       cmd_generate),
    "8":  ("Score proposal",          cmd_score),
    "9":  ("Export proposal",         cmd_export),
    "10": ("Full pipeline demo",      cmd_full_pipeline),
    # Webhooks
    "11": ("List webhook endpoints",  cmd_list_webhooks),
    "12": ("Create webhook endpoint", cmd_create_webhook),
    "13": ("Update webhook endpoint", cmd_update_webhook),
    "14": ("Delete webhook endpoint", cmd_delete_webhook),
    "15": ("Test webhook",            cmd_test_webhook),
    "16": ("Webhook event log",       cmd_webhook_events),
    # Usage
    "17": ("Check usage",             cmd_usage),
}


def print_menu():
    print("\n╔══════════════════════════════════════╗")
    print("║       Ergate API Demo CLI            ║")
    print("╠══════════════════════════════════════╣")
    print("║  PROPOSALS                           ║")
    print("║   1. List proposals                  ║")
    print("║   2. Create proposal                 ║")
    print("║   3. Get proposal detail             ║")
    print("║   4. Update proposal                 ║")
    print("║   5. Archive proposal                ║")
    print("║  PIPELINE                            ║")
    print("║   6. Analyze proposal                ║")
    print("║   7. Generate proposal               ║")
    print("║   8. Score proposal                  ║")
    print("║   9. Export proposal (PDF/DOCX/PPTX) ║")
    print("║  10. Full pipeline demo              ║")
    print("║  WEBHOOKS                            ║")
    print("║  11. List webhook endpoints          ║")
    print("║  12. Create webhook endpoint         ║")
    print("║  13. Update webhook endpoint         ║")
    print("║  14. Delete webhook endpoint         ║")
    print("║  15. Test webhook                    ║")
    print("║  16. Webhook event log               ║")
    print("║  ACCOUNT                             ║")
    print("║  17. Check usage                     ║")
    print("║                                      ║")
    print("║   r. Show raw JSON of last response  ║")
    print("║   q. Quit                            ║")
    print("╚══════════════════════════════════════╝")


def main():
    print("\nErgate API Demo CLI")
    print("=" * 40)
    configure()

    # Quick connectivity check
    print("  Checking connection...")
    result = api("GET", "/usage")
    if "error" in result:
        code = result.get("error", {}).get("code", "")
        if code == "UNAUTHORIZED":
            print("  Invalid API credentials. Check your key and secret.")
            sys.exit(1)
        print(f"  Warning: {result.get('error', {}).get('message', 'Unknown error')}")
    else:
        plan = result.get("data", {}).get("plan", "?")
        print(f"  Connected! Plan: {plan}\n")

    last_result = None

    while True:
        print_menu()
        choice = input("\n  Select [1-17, r, q]: ").strip().lower()

        if choice == "q":
            print("\n  Bye!\n")
            break
        elif choice == "r":
            if last_result:
                print("\n--- Raw JSON ---")
                pp(last_result)
            else:
                print("  No previous result.")
        elif choice in COMMANDS:
            label, fn = COMMANDS[choice]
            try:
                last_result = fn()
            except KeyboardInterrupt:
                print("\n  Interrupted.")
            except Exception as e:
                print(f"\n  Unexpected error: {e}")
        else:
            print("  Invalid choice.")


if __name__ == "__main__":
    main()
