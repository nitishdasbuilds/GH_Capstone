#!/usr/bin/env python3
"""
Script to open a GitHub pull request using the GitHub REST API.
"""

import argparse
import os
import re
import subprocess
import sys

import requests
from dotenv import load_dotenv


def get_owner_repo_from_remote():
    """
    Derive (owner, repo) from the 'origin' git remote URL.

    Returns:
        tuple[str, str] | None: (owner, repo) or None if it could not be derived.
    """
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    match = re.search(r"github\.com[:/]{1}([^/]+)/([^/.]+?)(?:\.git)?$", url)
    if not match:
        return None
    return match.group(1), match.group(2)


def create_pull_request(token, owner, repo, title, body, base, head):
    """
    Create a pull request via the GitHub REST API.

    Args:
        token: GitHub personal access token
        owner: Repository owner (user or org)
        repo: Repository name
        title: PR title
        body: PR body/description text
        base: Base branch (merge target)
        head: Head branch (source of changes)

    Returns:
        dict: PR data or None if failed
    """
    api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"

    payload = {
        "title": title,
        "body": body,
        "base": base,
        "head": head,
    }

    try:
        response = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.HTTPError as e:
        if response.status_code == 401:
            print("❌ Authentication failed. Please check your GITHUB_TOKEN.", file=sys.stderr)
        elif response.status_code == 403:
            print(f"❌ Permission denied. You don't have permission to open a PR on {owner}/{repo}.", file=sys.stderr)
        elif response.status_code == 404:
            print(f"❌ Repository {owner}/{repo} not found (or token lacks access).", file=sys.stderr)
        elif response.status_code == 422:
            print(f"❌ Unprocessable request (e.g. PR already exists, or branch not found): {response.text}", file=sys.stderr)
        else:
            print(f"❌ HTTP error occurred: {e}", file=sys.stderr)
            print(f"Response: {response.text}", file=sys.stderr)
        return None

    except requests.exceptions.ConnectionError:
        print("❌ Failed to connect to api.github.com. Please check your network connection.", file=sys.stderr)
        return None

    except requests.exceptions.Timeout:
        print("❌ Request timed out. Please try again.", file=sys.stderr)
        return None

    except Exception as e:
        print(f"❌ An error occurred: {e}", file=sys.stderr)
        return None


def main():
    """Main function to open a GitHub pull request."""
    parser = argparse.ArgumentParser(description="Create a GitHub pull request using the REST API")
    parser.add_argument("--title", required=True, help="Pull request title")
    parser.add_argument("--body-file", required=True, help="Path to a file whose contents will be used as the PR body")
    parser.add_argument("--base", required=True, help="Base branch (merge target), e.g. main")
    parser.add_argument("--head", required=True, help="Head branch (source of changes)")
    parser.add_argument("--owner", help="Repository owner override (derived from git remote if omitted)")
    parser.add_argument("--repo", help="Repository name override (derived from git remote if omitted)")
    args = parser.parse_args()

    load_dotenv()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("❌ GITHUB_TOKEN not found in .env file.", file=sys.stderr)
        print("Please add GITHUB_TOKEN to your .env file.", file=sys.stderr)
        sys.exit(1)

    if args.owner and args.repo:
        owner, repo = args.owner, args.repo
    else:
        derived = get_owner_repo_from_remote()
        if not derived:
            print("❌ Could not derive owner/repo from 'origin' remote. Pass --owner and --repo explicitly.", file=sys.stderr)
            sys.exit(1)
        owner, repo = derived

    with open(args.body_file, "r", encoding="utf-8") as f:
        body = f.read()

    print("=" * 70)
    print("GitHub Pull Request Creator")
    print("=" * 70)
    print(f"Repository: {owner}/{repo}")
    print(f"Base: {args.base}  <-  Head: {args.head}")
    print("=" * 70)

    pr_data = create_pull_request(token, owner, repo, args.title, body, args.base, args.head)

    if pr_data is None:
        print("\n❌ Failed to create pull request.", file=sys.stderr)
        sys.exit(1)

    print(f"\n✅ Pull request created: {pr_data.get('html_url')}")
    print(f"PR number: #{pr_data.get('number')}")


if __name__ == "__main__":
    main()
