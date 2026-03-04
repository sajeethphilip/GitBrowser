#!/usr/bin/env python3
"""
GitHub Repository Browser and Cloner
Supports viewing and downloading specific versions from history
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import requests
from github import Github, GithubException, Auth
from github.GithubException import BadCredentialsException, UnknownObjectException, RateLimitExceededException
import inquirer
from inquirer.themes import GreenPassion
import argparse
from urllib.parse import urlparse
import base64
import time
import datetime

class GitHubRepoManager:
    def __init__(self, token: Optional[str] = None):
        """
        Initialize GitHub manager with optional token
        """
        self.token = token
        self.github = None
        self.authenticated = False
        self.setup_github()

    def setup_github(self):
        """Setup GitHub connection with or without token"""
        try:
            if self.token:
                # Use the new authentication method to avoid deprecation warning
                auth = Auth.Token(self.token)
                self.github = Github(auth=auth)
                # Test authentication
                user = self.github.get_user()
                self.authenticated = True
                print(f"✅ Authenticated as: {user.login}")
            else:
                self.github = Github()
                # Check rate limit
                rate_limit = self.github.get_rate_limit()
                print(f"ℹ️  Using unauthenticated access (Rate limit: {rate_limit.core.remaining}/{rate_limit.core.limit})")
        except BadCredentialsException:
            print("❌ Invalid token. Continuing with unauthenticated access.")
            self.github = Github()
            self.authenticated = False
        except Exception as e:
            print(f"❌ Error setting up GitHub connection: {e}")
            sys.exit(1)

    def parse_github_url(self, url: str) -> Tuple[str, str, str, str]:
        """
        Parse GitHub URL to extract owner, repo, and optional path
        Supports formats:
        - https://github.com/owner/repo
        - https://github.com/owner/repo/tree/branch/path
        - https://github.com/owner/repo/blob/branch/path
        - owner/repo
        """
        # Remove trailing slashes
        url = url.rstrip('/')

        # Handle different URL formats
        if 'github.com' in url:
            # Parse URL
            parsed = urlparse(url)
            path_parts = parsed.path.split('/')

            # Remove empty strings
            path_parts = [p for p in path_parts if p]

            if len(path_parts) >= 2:
                owner = path_parts[0]
                repo = path_parts[1].replace('.git', '')

                # Check for branch and path
                branch = 'main'  # default
                file_path = ''

                if len(path_parts) > 3 and path_parts[2] in ['tree', 'blob']:
                    branch = path_parts[3]
                    if len(path_parts) > 4:
                        file_path = '/'.join(path_parts[4:])

                return owner, repo, branch, file_path
        elif '/' in url and not url.startswith('http'):
            # Handle owner/repo format
            parts = url.split('/')
            if len(parts) >= 2:
                return parts[0], parts[1], 'main', ''

        raise ValueError(f"Invalid GitHub URL/format: {url}")

    def get_repo(self, owner: str, repo_name: str):
        """Get repository object"""
        try:
            repo = self.github.get_repo(f"{owner}/{repo_name}")
            return repo
        except UnknownObjectException:
            print(f"❌ Repository {owner}/{repo_name} not found!")
            return None
        except RateLimitExceededException:
            print("❌ GitHub API rate limit exceeded. Try again later or use authentication.")
            return None
        except Exception as e:
            print(f"❌ Error accessing repository: {e}")
            return None

    def list_contents(self, repo, path: str = "", branch: str = "main") -> List[Dict]:
        """List contents of a directory in the repository"""
        try:
            contents = repo.get_contents(path, ref=branch)
            if not isinstance(contents, list):
                contents = [contents]

            items = []
            for content in contents:
                item = {
                    'name': content.name,
                    'path': content.path,
                    'type': 'dir' if content.type == 'dir' else 'file',
                    'size': getattr(content, 'size', 0),
                    'sha': content.sha,
                    'download_url': getattr(content, 'download_url', None)
                }
                items.append(item)

            # Sort: directories first, then files
            items.sort(key=lambda x: (x['type'] != 'dir', x['name'].lower()))
            return items
        except UnknownObjectException:
            # Path doesn't exist
            return []
        except Exception as e:
            print(f"❌ Error listing contents: {e}")
            return []

    def get_file_history(self, repo, file_path: str, branch: str = "main") -> List[Dict]:
        """Get commit history for a specific file"""
        try:
            commits = repo.get_commits(path=file_path, sha=branch)
            history = []

            for commit in commits[:50]:  # Limit to last 50 commits
                # Get commit details
                commit_data = {
                    'sha': commit.sha,
                    'short_sha': commit.sha[:8],
                    'message': commit.commit.message.split('\n')[0],
                    'full_message': commit.commit.message,
                    'author': commit.commit.author.name,
                    'email': commit.commit.author.email,
                    'date': commit.commit.author.date,
                    'date_str': commit.commit.author.date.strftime('%Y-%m-%d %H:%M:%S'),
                    'url': commit.html_url
                }
                history.append(commit_data)

            return history
        except RateLimitExceededException:
            print("❌ GitHub API rate limit exceeded. Try again later.")
            return []
        except Exception as e:
            print(f"❌ Error getting file history: {e}")
            return []

    def debug_file_content(self, repo, file_path: str, commit_sha: str):
        """Debug method to show what we're getting from GitHub"""
        try:
            print(f"\n🔍 Debug: Getting file at commit {commit_sha[:8]}")

            # Try different methods and show results
            print("\nMethod 1: get_contents with ref")
            try:
                contents = repo.get_contents(file_path, ref=commit_sha)
                print(f"  Type: {type(contents)}")
                print(f"  Encoding: {getattr(contents, 'encoding', 'unknown')}")
                print(f"  Size: {getattr(contents, 'size', 0)} bytes")
                if hasattr(contents, 'content'):
                    print(f"  Content length: {len(contents.content)}")
                    print(f"  Content preview: {str(contents.content)[:100]}")
            except Exception as e:
                print(f"  Error: {e}")

            print("\nMethod 2: Get commit and tree")
            try:
                commit = repo.get_commit(commit_sha)
                tree = repo.get_git_tree(commit.sha, recursive=True)

                for element in tree.tree:
                    if element.path == file_path:
                        print(f"  Found in tree: {element.path}")
                        print(f"  Type: {element.type}")
                        print(f"  SHA: {element.sha}")
                        print(f"  Size: {getattr(element, 'size', 'unknown')}")

                        # Get blob
                        blob = repo.get_git_blob(element.sha)
                        print(f"  Blob encoding: {blob.encoding}")
                        print(f"  Blob size: {blob.size}")
                        print(f"  Blob content length: {len(blob.content) if blob.content else 0}")
                        break
            except Exception as e:
                print(f"  Error: {e}")

            print("\nMethod 3: Raw URL")
            try:
                raw_url = f"https://raw.githubusercontent.com/{repo.full_name}/{commit_sha}/{file_path}"
                print(f"  URL: {raw_url}")

                headers = {}
                if self.authenticated and self.token:
                    headers['Authorization'] = f'token {self.token}'

                response = requests.get(raw_url, headers=headers)
                print(f"  Status: {response.status_code}")
                print(f"  Content length: {len(response.content)} bytes")
                print(f"  Content preview: {str(response.content[:100])}")
            except Exception as e:
                print(f"  Error: {e}")

        except Exception as e:
            print(f"Debug error: {e}")

    def get_file_at_commit(self, repo, file_path: str, commit_sha: str) -> Optional[bytes]:
        """Get file content at a specific commit"""
        try:
            # Method 1: Try to get content directly using the commit SHA
            try:
                contents = repo.get_contents(file_path, ref=commit_sha)

                if isinstance(contents, list):
                    print("❌ Path points to a directory, not a file")
                    return None

                # Handle different encoding types
                if contents.encoding == 'base64':
                    return base64.b64decode(contents.content)
                elif contents.encoding == 'utf-8' or contents.encoding == 'plain':
                    return contents.content.encode('utf-8') if isinstance(contents.content, str) else contents.content
                else:
                    # Try to decode as base64 anyway
                    try:
                        return base64.b64decode(contents.content)
                    except:
                        return contents.content if isinstance(contents.content, bytes) else str(contents.content).encode('utf-8')

            except Exception as e:
                print(f"⚠️  Method 1 failed: {e}")

            # Method 2: Get the commit and blob directly
            try:
                commit = repo.get_commit(commit_sha)

                # Get the tree at that commit
                tree = repo.get_git_tree(commit.sha, recursive=True)

                # Find the file in the tree
                for element in tree.tree:
                    if element.path == file_path:
                        # Get the blob
                        blob = repo.get_git_blob(element.sha)

                        # Decode blob content
                        if blob.encoding == 'base64':
                            return base64.b64decode(blob.content)
                        elif blob.encoding == 'utf-8':
                            return blob.content.encode('utf-8')
                        else:
                            return blob.content.encode('utf-8')

                print(f"❌ File {file_path} not found in commit {commit_sha[:8]}")
                return None

            except Exception as e:
                print(f"⚠️  Method 2 failed: {e}")

            # Method 3: Use the commit to get the raw URL and download
            try:
                # Get the raw content URL
                raw_url = f"https://raw.githubusercontent.com/{repo.full_name}/{commit_sha}/{file_path}"

                # Add token if authenticated
                headers = {}
                if self.authenticated and self.token:
                    headers['Authorization'] = f'token {self.token}'

                # Download the file
                response = requests.get(raw_url, headers=headers)

                if response.status_code == 200:
                    return response.content
                else:
                    print(f"❌ Raw download failed with status: {response.status_code}")
                    return None

            except Exception as e:
                print(f"⚠️  Method 3 failed: {e}")

            print(f"❌ All methods failed to get file at commit {commit_sha[:8]}")
            return None

        except Exception as e:
            print(f"❌ Error getting file at commit {commit_sha[:8]}: {e}")
            return None

    def download_file_version(self, repo, file_path: str, commit_sha: str, destination: Path):
        """Download a specific version of a file"""
        try:
            print(f"\n📥 Downloading {file_path} at commit {commit_sha[:8]}...")

            # Try the raw GitHub URL method first (since that worked for viewing)
            raw_url = f"https://raw.githubusercontent.com/{repo.full_name}/{commit_sha}/{file_path}"
            print(f"   URL: {raw_url}")

            headers = {}
            if self.authenticated and self.token:
                headers['Authorization'] = f'token {self.token}'

            # Download with proper headers
            response = requests.get(raw_url, headers=headers, allow_redirects=True)

            if response.status_code == 200:
                content = response.content
                print(f"   ✅ Downloaded {len(content)} bytes via raw URL")
            else:
                print(f"   ⚠️ Raw URL failed with status {response.status_code}, trying API method...")

                # Fallback to API method
                try:
                    # Get the commit and find the file blob
                    commit = repo.get_commit(commit_sha)
                    tree = repo.get_git_tree(commit.sha, recursive=True)

                    file_blob_sha = None
                    for element in tree.tree:
                        if element.path == file_path:
                            file_blob_sha = element.sha
                            break

                    if not file_blob_sha:
                        print(f"❌ File {file_path} not found in commit {commit_sha[:8]}")
                        return False

                    # Get the blob content
                    blob = repo.get_git_blob(file_blob_sha)

                    if blob.encoding == 'base64':
                        content = base64.b64decode(blob.content)
                    else:
                        content = blob.content.encode('utf-8') if isinstance(blob.content, str) else blob.content

                    print(f"   ✅ Downloaded {len(content)} bytes via API")

                except Exception as e:
                    print(f"   ❌ API method failed: {e}")
                    return False

            # Verify we have content
            if not content or len(content) == 0:
                print("❌ Downloaded content is empty!")

                # Try one more method - get_contents with ref
                try:
                    print("   🔄 Trying get_contents method...")
                    contents = repo.get_contents(file_path, ref=commit_sha)

                    if not isinstance(contents, list):
                        if contents.encoding == 'base64':
                            content = base64.b64decode(contents.content)
                        else:
                            content = contents.content
                        print(f"   ✅ Got {len(content)} bytes via get_contents")
                except Exception as e:
                    print(f"   ❌ get_contents failed: {e}")
                    return False

            # Final verification
            if not content or len(content) == 0:
                print("❌ All methods failed to get non-empty content")
                return False

            # Create destination directory if it doesn't exist
            destination.parent.mkdir(parents=True, exist_ok=True)

            # Write file with explicit binary mode
            with open(destination, 'wb') as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk

            # Verify the file was written correctly
            if destination.exists():
                file_size = destination.stat().st_size
                if file_size > 0:
                    print(f"✅ Successfully saved to: {destination} ({self.format_size(file_size)})")
                    return True
                else:
                    print(f"❌ File was created but is empty (0 bytes)")
                    # Try to remove the empty file
                    destination.unlink(missing_ok=True)
                    return False
            else:
                print("❌ File was not created")
                return False

        except Exception as e:
            print(f"❌ Error downloading file version: {e}")
            import traceback
            traceback.print_exc()
            return False

    def test_download_version(repo_manager, repo, file_path: str, commit_sha: str):
        """Test function to verify download is working"""
        print(f"\n🧪 Testing download of {file_path} at commit {commit_sha[:8]}")

        # Get the content
        content = repo_manager.get_file_at_commit(repo, file_path, commit_sha)

        if content is None:
            print("❌ Failed to get content")
            return False

        print(f"✅ Got content: {len(content)} bytes")

        # Save to temp file for verification
        temp_file = Path(f"/tmp/test_{commit_sha[:8]}_{os.path.basename(file_path)}")
        with open(temp_file, 'wb') as f:
            f.write(content)

        print(f"✅ Saved to: {temp_file}")
        print(f"📊 File size on disk: {temp_file.stat().st_size} bytes")

        # Show first few lines if text file
        try:
            text = content.decode('utf-8')
            lines = text.splitlines()
            print(f"\n📄 First 5 lines:")
            for i, line in enumerate(lines[:5]):
                print(f"  {i+1}: {line[:100]}")
        except UnicodeDecodeError:
            print("📄 Binary file - cannot display as text")

        return True

    def view_file_at_commit(self, repo, file_path: str, commit_sha: str):
        """View file content at a specific commit"""
        try:
            # First try to debug if file is empty
            if os.environ.get('DEBUG'):
                self.debug_file_content(repo, file_path, commit_sha)

            content = self.get_file_at_commit(repo, file_path, commit_sha)

            if content is None:
                print("❌ Could not retrieve file content")
                return

            if len(content) == 0:
                print("⚠️  File content is empty (0 bytes)")

                # Ask if user wants to try alternative method
                try_alt = inquirer.prompt([
                    inquirer.Confirm('alt',
                        message="File is empty. Try alternative download method?",
                        default=True
                    )
                ])

                if try_alt and try_alt['alt']:
                    # Try raw GitHub URL
                    raw_url = f"https://raw.githubusercontent.com/{repo.full_name}/{commit_sha}/{file_path}"
                    print(f"\nTrying raw URL: {raw_url}")

                    headers = {}
                    if self.authenticated and self.token:
                        headers['Authorization'] = f'token {self.token}'

                    response = requests.get(raw_url, headers=headers)
                    if response.status_code == 200:
                        content = response.content
                        print(f"✅ Success! Got {len(content)} bytes")
                    else:
                        print(f"❌ Failed with status: {response.status_code}")
                        return

            # Try to decode as text
            try:
                # Try different encodings
                for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
                    try:
                        text_content = content.decode(encoding)
                        print("\n" + "=" * 80)
                        print(f"📄 File: {file_path}")
                        print(f"📌 Commit: {commit_sha[:8]}")
                        print(f"📊 Size: {len(content)} bytes")
                        print(f"🔤 Encoding: {encoding}")
                        print("=" * 80)
                        print(text_content)
                        print("=" * 80)
                        return
                    except UnicodeDecodeError:
                        continue

                # If all decodings fail, it's binary
                print(f"\n📄 File: {file_path} (binary file)")
                print(f"📌 Commit: {commit_sha[:8]}")
                print(f"📊 Size: {len(content)} bytes")
                print(f"🔤 First 100 bytes (hex): {content[:100].hex()}")
                print("⚠️  Cannot display binary file content as text")

                # Ask if user wants to save it
                save_it = inquirer.prompt([
                    inquirer.Confirm('save',
                        message="Save this binary file?",
                        default=False
                    )
                ])

                if save_it and save_it['save']:
                    default_filename = f"{os.path.basename(file_path)}.{commit_sha[:8]}"
                    dest = input(f"Enter destination [default: ./{default_filename}]: ").strip()
                    if not dest:
                        dest = f"./{default_filename}"

                    with open(dest, 'wb') as f:
                        f.write(content)
                    print(f"✅ Saved to: {dest}")

            except Exception as e:
                print(f"❌ Error displaying file: {e}")

        except Exception as e:
            print(f"❌ Error viewing file: {e}")

    def compare_file_versions(self, repo, file_path: str, commit1: str, commit2: str):
        """Compare two versions of a file"""
        try:
            # Get content at both commits
            content1 = self.get_file_at_commit(repo, file_path, commit1)
            content2 = self.get_file_at_commit(repo, file_path, commit2)

            if content1 is None or content2 is None:
                return

            # Try to decode as text for comparison
            try:
                text1 = content1.decode('utf-8').splitlines()
                text2 = content2.decode('utf-8').splitlines()

                print(f"\n📊 Comparing {file_path}")
                print(f"📌 {commit1[:8]} vs {commit2[:8]}")
                print("-" * 80)

                # Simple diff output
                import difflib
                diff = difflib.unified_diff(
                    text1, text2,
                    fromfile=f'{commit1[:8]}',
                    tofile=f'{commit2[:8]}',
                    lineterm=''
                )

                for line in diff:
                    if line.startswith('+'):
                        print(f"\033[92m{line}\033[0m")  # Green for additions
                    elif line.startswith('-'):
                        print(f"\033[91m{line}\033[0m")  # Red for deletions
                    elif line.startswith('@@'):
                        print(f"\033[94m{line}\033[0m")  # Blue for position
                    else:
                        print(line)

            except UnicodeDecodeError:
                print("⚠️  Cannot compare binary files")

        except Exception as e:
            print(f"❌ Error comparing files: {e}")

    def format_size(self, size_bytes):
        """Format file size in human-readable format"""
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.1f} {size_names[i]}"


def interactive_file_browser(repo_manager: GitHubRepoManager, repo, branch: str):
    """Interactive file browser for repository"""
    current_path = ""
    breadcrumb = [("Root", "")]

    while True:
        print(f"\n📁 Current location: {'/'.join([b[0] for b in breadcrumb])}")
        print("-" * 50)

        # List contents
        items = repo_manager.list_contents(repo, current_path, branch)

        if not items:
            print("📂 This folder is empty")
            if current_path:
                # Go back option
                choice = inquirer.prompt([
                    inquirer.List('action',
                        message="Choose action",
                        choices=[
                            ('Go back', 'back'),
                            ('Exit browser', 'exit')
                        ],
                        carousel=True
                    )
                ])
                if choice and choice['action'] == 'back':
                    # Go back one level
                    current_path = '/'.join(current_path.split('/')[:-1]) if '/' in current_path else ""
                    breadcrumb.pop()
                elif choice and choice['action'] == 'exit':
                    break
            else:
                break
            continue

        # Prepare choices for inquirer
        choices = []
        for item in items:
            if item['type'] == 'dir':
                prefix = "📁 "
                size_info = ""
            else:
                prefix = "📄 "
                size_info = f" ({repo_manager.format_size(item['size'])})"

            label = f"{prefix}{item['name']}{size_info}"
            choices.append((label, ('item', item)))

        # Add navigation options
        if current_path:
            choices.insert(0, ("🔙 .. (Go back)", ('back', None)))
        choices.append(("🚪 Exit browser", ('exit', None)))

        # Show selection prompt
        questions = [
            inquirer.List('selection',
                message="Select item (use arrow keys, Enter to select)",
                choices=choices,
                carousel=True
            )
        ]

        try:
            answers = inquirer.prompt(questions, theme=GreenPassion())
        except KeyboardInterrupt:
            print("\n\n👋 Operation cancelled")
            return None

        if not answers:
            break

        selected = answers['selection']
        action_type, data = selected

        if action_type == 'exit':
            break
        elif action_type == 'back':
            # Go back one level
            current_path = '/'.join(current_path.split('/')[:-1]) if '/' in current_path else ""
            breadcrumb.pop()
        elif action_type == 'item':
            item = data
            if item['type'] == 'dir':
                # Enter directory
                current_path = item['path']
                breadcrumb.append((item['name'], current_path))
            else:
                # File selected
                return item

    return None


def file_history_menu(repo_manager: GitHubRepoManager, repo, file_path: str, branch: str):
    """Interactive menu for file history"""
    print(f"\n📜 Fetching history for: {file_path}")
    history = repo_manager.get_file_history(repo, file_path, branch)

    if not history:
        print("No history found for this file")
        return

    while True:
        print(f"\n📜 File History - {os.path.basename(file_path)}")
        print("=" * 80)

        # Display history with numbers
        for i, commit in enumerate(history, 1):
            date_str = commit['date'].strftime('%Y-%m-%d %H:%M') if hasattr(commit['date'], 'strftime') else str(commit['date'])
            print(f"{i:2}. [{commit['short_sha']}] {date_str}")
            print(f"     👤 {commit['author']}")
            print(f"     📝 {commit['message'][:80]}{'...' if len(commit['message']) > 80 else ''}")
            print()

        print("\nOptions:")
        print("  [number] - Select commit to view")
        print("  d[number] - Download that version (e.g., d5)")
        print("  c[1]-[2] - Compare two versions (e.g., c1-3)")
        print("  s - Search commits")
        print("  b - Go back")
        print("  q - Quit")

        choice = input("\nEnter choice: ").strip().lower()

        if choice == 'q':
            break
        elif choice == 'b':
            break
        elif choice == 's':
            search_term = input("Enter search term: ").strip()
            if search_term:
                filtered = [c for c in history if
                          search_term.lower() in c['message'].lower() or
                          search_term.lower() in c['author'].lower()]
                if filtered:
                    history = filtered
                    print(f"Found {len(filtered)} matching commits")
                else:
                    print("No matches found")

        elif choice.startswith('c'):
            # Compare versions
            try:
                parts = choice[1:].split('-')
                if len(parts) == 2:
                    idx1 = int(parts[0]) - 1
                    idx2 = int(parts[1]) - 1

                    if 0 <= idx1 < len(history) and 0 <= idx2 < len(history):
                        repo_manager.compare_file_versions(
                            repo, file_path,
                            history[idx1]['sha'],
                            history[idx2]['sha']
                        )
                    else:
                        print("❌ Invalid commit numbers")
                else:
                    print("❌ Use format: c1-2")
            except ValueError:
                print("❌ Invalid format")

        elif choice.startswith('d'):
            # Download version
            try:
                idx = int(choice[1:]) - 1
                if 0 <= idx < len(history):
                    commit = history[idx]

                    # Create a meaningful filename with date and commit hash
                    date_str = commit['date'].strftime('%Y%m%d_%H%M%S') if hasattr(commit['date'], 'strftime') else 'unknown'
                    base_name = os.path.basename(file_path)
                    name_without_ext, ext = os.path.splitext(base_name)
                    default_filename = f"{name_without_ext}_{date_str}_{commit['short_sha']}{ext}"

                    print(f"\nSelected version: {commit['short_sha']} from {commit['date_str']}")
                    dest = input(f"Enter destination [default: ./{default_filename}]: ").strip()

                    if not dest:
                        dest = f"./{default_filename}"

                    # Ensure directory exists
                    dest_path = Path(dest)
                    dest_path.parent.mkdir(parents=True, exist_ok=True)

                    # Download the file
                    success = repo_manager.download_file_version(
                        repo, file_path, commit['sha'], dest_path
                    )

                    if success:
                        print(f"\n✅ Version downloaded successfully!")
                    else:
                        print(f"\n❌ Failed to download version")

                else:
                    print("❌ Invalid commit number")
            except ValueError:
                print("❌ Invalid format. Use d[number] (e.g., d5)")
            except Exception as e:
                print(f"❌ Error: {e}")

        else:
            # Try to view as number
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(history):
                    commit = history[idx]

                    print(f"\n📌 Commit: {commit['short_sha']}")
                    print(f"Author: {commit['author']} <{commit['email']}>")
                    print(f"Date: {commit['date_str']}")
                    print(f"Message: {commit['full_message']}")
                    print()

                    actions = [
                        ('View file at this version', 'view'),
                        ('Download this version', 'download'),
                        ('Go back', 'back')
                    ]

                    action = inquirer.prompt([
                        inquirer.List('action',
                            message="What would you like to do?",
                            choices=actions
                        )
                    ])

                    if action and action['action'] == 'view':
                        repo_manager.view_file_at_commit(repo, file_path, commit['sha'])
                        input("\nPress Enter to continue...")
                    elif action and action['action'] == 'download':
                        # Create default filename
                        date_str = commit['date'].strftime('%Y%m%d_%H%M%S') if hasattr(commit['date'], 'strftime') else 'unknown'
                        base_name = os.path.basename(file_path)
                        name_without_ext, ext = os.path.splitext(base_name)
                        default_filename = f"{name_without_ext}_{date_str}_{commit['short_sha']}{ext}"

                        dest = input(f"Enter destination [default: ./{default_filename}]: ").strip()
                        if not dest:
                            dest = f"./{default_filename}"

                        repo_manager.download_file_version(repo, file_path, commit['sha'], Path(dest))
                else:
                    print("❌ Invalid selection")
            except ValueError:
                print("❌ Invalid input. Enter a number, d[number], c[1]-[2], s, b, or q")

def test_download_specific_version(repo_manager, repo, file_path: str, commit_sha: str):
    """Test function to debug download issues"""
    print(f"\n🔧 Debug: Testing download of {file_path} at {commit_sha[:8]}")

    # Method 1: Raw URL
    print("\nMethod 1: Raw GitHub URL")
    raw_url = f"https://raw.githubusercontent.com/{repo.full_name}/{commit_sha}/{file_path}"
    headers = {'Authorization': f'token {repo_manager.token}'} if repo_manager.token else {}

    response = requests.get(raw_url, headers=headers)
    print(f"  Status: {response.status_code}")
    print(f"  Headers: {dict(response.headers)}")
    print(f"  Content length: {len(response.content)} bytes")

    # Method 2: API get_contents
    print("\nMethod 2: API get_contents")
    try:
        contents = repo.get_contents(file_path, ref=commit_sha)
        if not isinstance(contents, list):
            print(f"  Type: {type(contents)}")
            print(f"  Encoding: {contents.encoding}")
            print(f"  Size: {contents.size}")
            print(f"  Content length: {len(contents.content)}")
            if contents.encoding == 'base64':
                decoded = base64.b64decode(contents.content)
                print(f"  Decoded length: {len(decoded)} bytes")
    except Exception as e:
        print(f"  Error: {e}")

    # Method 3: Git tree and blob
    print("\nMethod 3: Git Tree/Blob")
    try:
        commit = repo.get_commit(commit_sha)
        tree = repo.get_git_tree(commit.sha, recursive=True)
        for element in tree.tree:
            if element.path == file_path:
                print(f"  Found in tree: {element.path}")
                print(f"  SHA: {element.sha}")
                print(f"  Size: {element.size if hasattr(element, 'size') else 'unknown'}")

                blob = repo.get_git_blob(element.sha)
                print(f"  Blob encoding: {blob.encoding}")
                print(f"  Blob size: {blob.size}")
                print(f"  Blob content length: {len(blob.content) if blob.content else 0}")
                if blob.encoding == 'base64':
                    decoded = base64.b64decode(blob.content)
                    print(f"  Decoded length: {len(decoded)} bytes")
                break
    except Exception as e:
        print(f"  Error: {e}")

    return True

def get_user_input(prompt_text, default=None, required=False):
    """Get user input with error handling"""
    while True:
        try:
            value = input(prompt_text).strip()
            if not value and required:
                print("❌ This field is required")
                continue
            return value if value else default
        except KeyboardInterrupt:
            print("\n\n👋 Operation cancelled")
            sys.exit(0)
        except EOFError:
            print("\n\n👋 Goodbye!")
            sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description='GitHub Repository Browser and Cloner')
    parser.add_argument('--token', '-t', help='GitHub personal access token (optional)')
    parser.add_argument('--repo', '-r', help='GitHub repository URL or owner/repo')
    args = parser.parse_args()

    print("=" * 60)
    print("🚀 GitHub Repository Manager")
    print("=" * 60)
    print()

    # Get token if not provided
    token = args.token
    if not token:
        token = get_user_input("Enter GitHub token (optional, press Enter to skip): ")

    # Initialize GitHub manager
    repo_manager = GitHubRepoManager(token if token else None)

    # Get repository URL
    repo_input = args.repo
    if not repo_input:
        repo_input = get_user_input("Enter GitHub repository (URL or owner/repo): ", required=True)

    try:
        # Parse repository information
        owner, repo_name, branch, initial_path = repo_manager.parse_github_url(repo_input)
        print(f"\n📊 Repository: {owner}/{repo_name}")
        print(f"🌿 Branch: {branch}")
        if initial_path:
            print(f"📁 Initial path: {initial_path}")

        # Get repository
        repo = repo_manager.get_repo(owner, repo_name)
        if not repo:
            return 1

        # Main menu
        while True:
            print(f"\n📋 Repository Menu - {owner}/{repo_name}")
            print("-" * 50)

            menu_choices = [
                ('📁 Browse files', 'browse'),
                ('📂 Download file/folder', 'download'),
                ('📜 View file history', 'history'),
                ('🔧 Clone entire repository', 'clone'),
                ('🚪 Exit', 'exit')
            ]

            try:
                menu = inquirer.prompt([
                    inquirer.List('action',
                        message="What would you like to do?",
                        choices=menu_choices,
                        carousel=True
                    )
                ], theme=GreenPassion())
            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                break

            if not menu:
                break

            action = menu['action']

            if action == 'exit':
                print("\n👋 Goodbye!")
                break

            elif action == 'browse':
                print("\n🔍 Browsing repository files...")
                selected = interactive_file_browser(repo_manager, repo, branch)
                if selected:
                    print(f"\n✅ Selected: {selected['name']}")
                    print(f"   Path: {selected['path']}")
                    print(f"   Type: {selected['type']}")
                    if selected['type'] == 'file':
                        print(f"   Size: {repo_manager.format_size(selected['size'])}")

                        # Ask if they want to see history
                        see_history = inquirer.prompt([
                            inquirer.Confirm('history',
                                message="View history for this file?",
                                default=False
                            )
                        ])
                        if see_history and see_history['history']:
                            file_history_menu(repo_manager, repo, selected['path'], branch)

            elif action == 'download':
                # Browse to select file/folder
                print("\n🔍 Select file/folder to download...")
                selected = interactive_file_browser(repo_manager, repo, branch)
                if selected:
                    # Get download destination
                    default_dest = f"./downloads/{selected['name']}"
                    dest = get_user_input(f"Enter destination path [default: {default_dest}]: ", default_dest)

                    if dest:
                        dest_path = Path(dest)

                        if selected['type'] == 'file':
                            repo_manager.download_file(repo, selected['path'], branch, dest_path)
                        else:
                            # For directories, use sparse checkout
                            print("⚠️  Downloading folders requires git and might take a moment...")
                            success = repo_manager.sparse_checkout_folder(
                                repo,
                                selected['path'],
                                branch,
                                dest_path.parent
                            )
                            if success:
                                print(f"✅ Folder downloaded successfully")

            elif action == 'history':
                # Browse to select file
                print("\n🔍 Select a file to view its history...")
                selected = interactive_file_browser(repo_manager, repo, branch)
                if selected and selected['type'] == 'file':
                    file_history_menu(repo_manager, repo, selected['path'], branch)

            elif action == 'clone':
                # Clone entire repository
                default_dest = f"./{repo_name}"
                dest = get_user_input(f"Enter destination directory [default: {default_dest}]: ", default_dest)

                if dest:
                    dest_path = Path(dest)
                    repo_manager.clone_repository(repo, branch, dest_path)

    except ValueError as e:
        print(f"❌ Error: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n\n👋 Operation cancelled by user")
        return 0
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    print("pip install PyGithub requests inquirer")
    main()
