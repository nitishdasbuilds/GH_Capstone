#!/usr/bin/env python3
"""
Script to fetch Jira ticket information using REST API with basic authentication.
"""

import argparse
import json
import os
import sys
import getpass
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv


def fetch_jira_ticket(email, api_token, ticket_id, jira_base_url):
    """
    Fetch Jira ticket details using REST API.
    
    Args:
        email: User email for authentication
        api_token: API token for authentication
        ticket_id: Jira ticket ID (e.g., 'EPMCDMETST-62888')
        jira_base_url: Base URL of Jira instance
        
    Returns:
        dict: Ticket data or None if failed
    """
    # Construct API endpoint
    api_url = f"{jira_base_url}/rest/api/2/issue/{ticket_id}"
    
    # Specify fields to retrieve
    params = {
        'fields': 'summary,description,status,priority'
    }
    
    try:
        # Make API request with basic authentication
        response = requests.get(
            api_url,
            auth=HTTPBasicAuth(email, api_token),
            params=params,
            headers={'Accept': 'application/json'},
            timeout=30
        )
        
        # Check if request was successful
        response.raise_for_status()
        
        return response.json()
        
    except requests.exceptions.HTTPError as e:
        if response.status_code == 401:
            print(f"❌ Authentication failed. Please check your email and API token.", file=sys.stderr)
        elif response.status_code == 404:
            print(f"❌ Ticket {ticket_id} not found.", file=sys.stderr)
        else:
            print(f"❌ HTTP error occurred: {e}", file=sys.stderr)
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


def save_ticket_data(ticket_data, output_path):
    """
    Save ticket data to JSON file.
    
    Args:
        ticket_data: Ticket data dictionary
        output_path: Path to output JSON file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Save to JSON file with pretty formatting
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(ticket_data, f, indent=2, ensure_ascii=False)
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to save data to {output_path}: {e}", file=sys.stderr)
        return False


def main():
    """Main function to orchestrate Jira ticket fetching."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Fetch Jira ticket information using REST API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python jira_fetch.py EPMCDMETST-62888
  python jira_fetch.py PROJECT-123
        """
    )
    parser.add_argument(
        'ticket_id',
        help='Jira ticket ID (e.g., EPMCDMETST-62888)'
    )
    parser.add_argument(
        '--output',
        default='artifacts/jira_story.json',
        help='Output JSON file path (default: artifacts/jira_story.json)'
    )
    
    args = parser.parse_args()
    
    # Configuration
    JIRA_BASE_URL = "https://jiraeu.epam.com"
    TICKET_ID = args.ticket_id
    OUTPUT_PATH = args.output
    
    # Load environment variables from .env file
    load_dotenv()
    
    print("=" * 60)
    print("Jira Ticket Fetcher")
    print("=" * 60)
    print(f"Ticket: {TICKET_ID}")
    print(f"Jira URL: {JIRA_BASE_URL}")
    print("=" * 60)
    
    # Get authentication credentials from .env file or prompt
    email = os.environ.get('JIRA_EMAIL')
    api_token = os.environ.get('JIRA_API_TOKEN')
    
    if not email:
        print("\n⚠️  JIRA_EMAIL not found in .env file")
        email = input("Enter your Jira email: ").strip()
        if not email:
            print("❌ Email is required.", file=sys.stderr)
            sys.exit(1)
    
    if not api_token:
        print("\n⚠️  JIRA_API_TOKEN not found in .env file")
        api_token = getpass.getpass("Enter your Jira API token: ").strip()
        if not api_token:
            print("❌ API token is required.", file=sys.stderr)
            sys.exit(1)
    
    # Fetch ticket data
    print(f"\n📥 Fetching ticket {TICKET_ID}...")
    ticket_data = fetch_jira_ticket(email, api_token, TICKET_ID, JIRA_BASE_URL)
    
    if not ticket_data:
        print("\n❌ Failed to fetch ticket data.")
        sys.exit(1)
    
    # Extract and display key information
    fields = ticket_data.get('fields', {})
    print("\n✅ Successfully fetched ticket!")
    print("-" * 60)
    print(f"Summary: {fields.get('summary', 'N/A')}")
    print(f"Status: {fields.get('status', {}).get('name', 'N/A')}")
    print(f"Priority: {fields.get('priority', {}).get('name', 'N/A')}")
    print("-" * 60)
    
    # Save to file
    print(f"\n💾 Saving data to {OUTPUT_PATH}...")
    if save_ticket_data(ticket_data, OUTPUT_PATH):
        print(f"✅ Successfully saved ticket data to {OUTPUT_PATH}")
        print("\n🎉 Process completed successfully!")
    else:
        print("\n❌ Failed to save ticket data.")
        sys.exit(1)


if __name__ == "__main__":
    main()
