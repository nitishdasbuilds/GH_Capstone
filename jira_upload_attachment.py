#!/usr/bin/env python3
"""
Script to upload a file as an attachment to a Jira ticket using REST API.
"""

import argparse
import os
import sys

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv


def upload_jira_attachment(email, api_token, ticket_id, file_path, jira_base_url):
    """
    Upload a file as an attachment to a Jira ticket using REST API.

    Args:
        email: User email for authentication
        api_token: API token for authentication
        ticket_id: Jira ticket ID (e.g., 'EPMCDMETST-62888')
        file_path: Path to the local file to upload
        jira_base_url: Base URL of Jira instance

    Returns:
        list: Attachment metadata from Jira, or None if failed
    """
    api_url = f"{jira_base_url}/rest/api/2/issue/{ticket_id}/attachments"

    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f)}
            response = requests.post(
                api_url,
                auth=HTTPBasicAuth(email, api_token),
                files=files,
                # Jira requires this header for attachment uploads to skip XSRF checks.
                headers={"X-Atlassian-Token": "no-check", "Accept": "application/json"},
                timeout=60,
            )

        response.raise_for_status()
        return response.json()

    except FileNotFoundError:
        print(f"❌ File not found: {file_path}", file=sys.stderr)
        return None

    except requests.exceptions.HTTPError as e:
        if response.status_code == 401:
            print("❌ Authentication failed. Please check your email and API token.", file=sys.stderr)
        elif response.status_code == 403:
            print(f"❌ Permission denied. You don't have permission to attach files to {ticket_id}.", file=sys.stderr)
        elif response.status_code == 404:
            print(f"❌ Ticket {ticket_id} not found.", file=sys.stderr)
        else:
            print(f"❌ HTTP error occurred: {e}", file=sys.stderr)
            print(f"Response: {response.text}", file=sys.stderr)
        return None

    except requests.exceptions.ConnectionError:
        print(f"❌ Failed to connect to {jira_base_url}. Please check the URL and your network connection.", file=sys.stderr)
        return None

    except requests.exceptions.Timeout:
        print("❌ Request timed out. Please try again.", file=sys.stderr)
        return None

    except Exception as e:
        print(f"❌ An error occurred: {e}", file=sys.stderr)
        return None


def main():
    """Main function to upload a file as a Jira attachment."""
    parser = argparse.ArgumentParser(
        description="Upload a file as an attachment to a Jira ticket using REST API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python jira_upload_attachment.py EPMCDMETST-62888 artifacts/manual-test-cases.md
        """,
    )
    parser.add_argument("ticket_id", help="Jira ticket ID (e.g., EPMCDMETST-62888)")
    parser.add_argument("file_path", help="Path to the local file to upload as an attachment")
    args = parser.parse_args()

    JIRA_BASE_URL = "https://jiraeu.epam.com"
    TICKET_ID = args.ticket_id
    FILE_PATH = args.file_path

    load_dotenv()

    print("=" * 70)
    print("Jira Attachment Uploader")
    print("=" * 70)
    print(f"Ticket: {TICKET_ID}")
    print(f"File: {FILE_PATH}")
    print(f"Jira URL: {JIRA_BASE_URL}")
    print("=" * 70)

    email = os.environ.get("JIRA_EMAIL")
    api_token = os.environ.get("JIRA_API_TOKEN")

    if not email:
        print("❌ JIRA_EMAIL not found in .env file.", file=sys.stderr)
        sys.exit(1)

    if not api_token:
        print("❌ JIRA_API_TOKEN not found in .env file.", file=sys.stderr)
        sys.exit(1)

    print(f"\n📎 Uploading {FILE_PATH} to {TICKET_ID}...")
    result = upload_jira_attachment(email, api_token, TICKET_ID, FILE_PATH, JIRA_BASE_URL)

    if result:
        attachment = result[0] if isinstance(result, list) and result else {}
        print("\n✅ Attachment uploaded successfully!")
        print(f"Attachment ID: {attachment.get('id')}")
        print(f"Filename: {attachment.get('filename')}")
        print(f"\n🔗 View ticket: {JIRA_BASE_URL}/browse/{TICKET_ID}")
        return 0
    else:
        print("\n❌ Failed to upload attachment.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
