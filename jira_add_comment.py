#!/usr/bin/env python3
"""
Script to add a comment to a Jira ticket using REST API.
"""

import argparse
import os
import sys
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv


def add_jira_comment(email, api_token, ticket_id, comment_text, jira_base_url):
    """
    Add a comment to a Jira ticket using REST API.
    
    Args:
        email: User email for authentication
        api_token: API token for authentication
        ticket_id: Jira ticket ID (e.g., 'EPMCDMETST-62888')
        comment_text: Comment text to add
        jira_base_url: Base URL of Jira instance
        
    Returns:
        dict: Comment data or None if failed
    """
    # Construct API endpoint for adding comments
    api_url = f"{jira_base_url}/rest/api/2/issue/{ticket_id}/comment"
    
    # Comment payload
    payload = {
        "body": comment_text
    }
    
    try:
        # Make API request with basic authentication
        response = requests.post(
            api_url,
            auth=HTTPBasicAuth(email, api_token),
            json=payload,
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            timeout=30
        )
        
        # Check if request was successful
        response.raise_for_status()
        
        return response.json()
        
    except requests.exceptions.HTTPError as e:
        if response.status_code == 401:
            print(f"❌ Authentication failed. Please check your email and API token.", file=sys.stderr)
        elif response.status_code == 403:
            print(f"❌ Permission denied. You don't have permission to add comments to {ticket_id}.", file=sys.stderr)
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
        print(f"❌ Request timed out. Please try again.", file=sys.stderr)
        return None
        
    except Exception as e:
        print(f"❌ An error occurred: {e}", file=sys.stderr)
        return None


def main():
    """Main function to add a comment to a Jira ticket."""
    parser = argparse.ArgumentParser(description="Add a comment to a Jira ticket using REST API")
    parser.add_argument("ticket_id", nargs="?", default="EPMCDMETST-62888", help="Jira ticket ID (e.g., EPMCDMETST-62888)")
    parser.add_argument("--comment", help="Comment text to post")
    parser.add_argument("--comment-file", help="Path to a file whose contents will be used as the comment text")
    args = parser.parse_args()

    # Configuration
    JIRA_BASE_URL = "https://jiraeu.epam.com"
    TICKET_ID = args.ticket_id

    if args.comment_file:
        with open(args.comment_file, "r", encoding="utf-8") as f:
            COMMENT_TEXT = f.read()
    elif args.comment:
        COMMENT_TEXT = args.comment
    else:
        COMMENT_TEXT = """Agentic SDLC Pipeline Progress Update:
✅ Phase 1 - Requirements: Complete
✅ Phase 2 - Architecture: Complete  
✅ Phase 3 - Design Review: Complete (Approved with Conditions)
✅ Phase 4 - Implementation Plan: Complete (33 tasks defined)
⏳ Phase 5 - Implementation: In Progress
All artifacts saved in project repository."""
    
    # Load environment variables from .env file
    load_dotenv()
    
    print("=" * 70)
    print("Jira Comment Poster")
    print("=" * 70)
    print(f"Ticket: {TICKET_ID}")
    print(f"Jira URL: {JIRA_BASE_URL}")
    print("=" * 70)
    
    # Get authentication credentials from .env file
    email = os.environ.get('JIRA_EMAIL')
    api_token = os.environ.get('JIRA_API_TOKEN')
    
    if not email:
        print("❌ JIRA_EMAIL not found in .env file.", file=sys.stderr)
        print("Please add JIRA_EMAIL to your .env file.", file=sys.stderr)
        sys.exit(1)
    
    if not api_token:
        print("❌ JIRA_API_TOKEN not found in .env file.", file=sys.stderr)
        print("Please add JIRA_API_TOKEN to your .env file.", file=sys.stderr)
        sys.exit(1)
    
    print(f"\n📝 Adding comment to {TICKET_ID}...")
    print(f"\nComment text:")
    print("-" * 70)
    print(COMMENT_TEXT)
    print("-" * 70)
    
    # Add comment to Jira ticket
    result = add_jira_comment(email, api_token, TICKET_ID, COMMENT_TEXT, JIRA_BASE_URL)
    
    if result:
        print(f"\n✅ Comment added successfully!")
        print(f"Comment ID: {result.get('id')}")
        print(f"Author: {result.get('author', {}).get('displayName')}")
        print(f"Created: {result.get('created')}")
        print(f"\n🔗 View ticket: {JIRA_BASE_URL}/browse/{TICKET_ID}")
        return 0
    else:
        print(f"\n❌ Failed to add comment.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
