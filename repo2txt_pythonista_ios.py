"""
Pythonista-compatible version of repo2txt.

This script recreates the core GitHub-to-text (and local archive) workflow
with a native Pythonista UI. It intentionally avoids external dependencies
so it can run on iOS with the built-in Pythonista modules.
"""

from __future__ import annotations

import io
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

import requests

try:
    import ui  # type: ignore
    import dialogs  # type: ignore
    import clipboard  # type: ignore
except ImportError:  # pragma: no cover - only available in Pythonista
    ui = None
    dialogs = None
    clipboard = None

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    import ui as _ui
    UIBaseView = _ui.View
else:
    UIBaseView = object if ui is None else ui.View


COMMON_EXTENSIONS = {".js", ".py", ".java", ".cpp", ".html", ".css", ".ts", ".jsx", ".tsx"}
TEMP_FILE_CLEANUP_DELAY = 10.0


@dataclass
class FileEntry:
    path: str
    url: str
    url_type: str
    selected: bool = False


def parse_repo_url(url: str) -> Tuple[str, str, str]:
    url = url.rstrip("/")
    pattern = r"^https://github\.com/([^/]+)/([^/]+)(/tree/(.+))?$"
    match = re.match(pattern, url)
    if not match:
        raise ValueError(
            "Invalid GitHub repository URL. Use https://github.com/owner/repo "
            "or https://github.com/owner/repo/tree/branch/path"
        )
    return match.group(1), match.group(2), match.group(4) or ""


def auth_headers(token: str, accept: str) -> Dict[str, str]:
    headers = {"Accept": accept}
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def handle_fetch_error(response: requests.Response) -> None:
    if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
        raise RuntimeError(
            "GitHub API rate limit exceeded. Provide a token or try again later."
        )
    if response.status_code == 404:
        raise RuntimeError(
            "Repository, branch, or path not found. Check the URL, branch/tag, and path."
        )
    raise RuntimeError(f"Failed to fetch repository data. Status: {response.status_code}")


def get_references(owner: str, repo: str, token: str) -> Dict[str, List[str]]:
    headers = auth_headers(token, "application/vnd.github+json")
    branches_resp = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads", headers=headers
    )
    tags_resp = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/git/refs/tags", headers=headers
    )
    if not branches_resp.ok:
        handle_fetch_error(branches_resp)
    if not tags_resp.ok:
        handle_fetch_error(tags_resp)
    branches = [ref["ref"].split("/", 2)[-1] for ref in branches_resp.json()]
    tags = [ref["ref"].split("/", 2)[-1] for ref in tags_resp.json()]
    return {"branches": branches, "tags": tags}


def fetch_repo_sha(owner: str, repo: str, ref: str, path: str, token: str) -> str:
    base = f"https://api.github.com/repos/{owner}/{repo}/contents"
    url = f"{base}/{path}" if path else base
    if ref:
        url = f"{url}?ref={ref}"
    response = requests.get(url, headers=auth_headers(token, "application/vnd.github.object+json"))
    if not response.ok:
        handle_fetch_error(response)
    return response.json()["sha"]


def fetch_repo_tree(owner: str, repo: str, sha: str, token: str) -> List[Dict[str, str]]:
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{sha}?recursive=1"
    response = requests.get(url, headers=auth_headers(token, "application/vnd.github+json"))
    if not response.ok:
        handle_fetch_error(response)
    return response.json().get("tree", [])


def sort_contents(items: List[FileEntry]) -> List[FileEntry]:
    def key(entry: FileEntry) -> Tuple:
        parts = entry.path.strip("/").split("/")
        return (*parts[:-1], parts[-1])

    return sorted(items, key=key)


def is_ignored(file_path: str, gitignore_rules: List[str]) -> bool:
    for rule in gitignore_rules:
        rule = rule.strip()
        if not rule or rule.startswith("#"):
            continue
        try:
            pattern = (
                rule.replace(".", r"\.")
                .replace("*", ".*")
                .replace("?", ".")
                .replace("/$", "(/.*)?$")
            )
            if rule.startswith("/"):
                pattern = f"^{pattern[1:]}"
            else:
                pattern = f"(^|/){pattern}"
            if re.search(pattern, file_path):
                return True
        except re.error:
            continue
    return False


def build_index(paths: List[str]) -> str:
    tree: Dict[str, dict] = {}
    for path in paths:
        parts = [p for p in path.strip("/").split("/") if p]
        current = tree
        for idx, part in enumerate(parts):
            is_last = idx == len(parts) - 1
            if part not in current:
                current[part] = None if is_last else {}
            if not is_last:
                child = current.get(part)
                if not isinstance(child, dict):
                    child = {}
                    current[part] = child
                current = child

    def walk(node: Dict[str, dict], prefix: str = "") -> str:
        lines = []
        entries = list(node.items())
        for idx, (name, child) in enumerate(entries):
            is_last = idx == len(entries) - 1
            line_prefix = "└── " if is_last else "├── "
            child_prefix = "    " if is_last else "│   "
            lines.append(f"{prefix}{line_prefix}{name}")
            if child is not None:
                lines.append(walk(child, prefix + child_prefix))
        return "\n".join(lines)

    return walk(tree)


def format_repo_contents(contents: List[Tuple[str, str]]) -> str:
    sorted_contents = sorted(contents, key=lambda item: item[0])
    index = build_index([path for path, _ in sorted_contents])
    body_parts = [f"\n\n---\nFile: {path}\n---\n\n{text}" for path, text in sorted_contents]
    return f"Directory Structure:\n\n{index}\n{''.join(body_parts)}"


class FilesDataSource(object):
    def __init__(self, app: "Repo2TxtApp") -> None:
        self.app = app

    def tableview_number_of_rows(self, _tv, _section) -> int:
        return len(self.app.files)

    def tableview_cell_for_row(self, _tv, _section, row: int):
        item = self.app.files[row]
        cell = ui.TableViewCell()
        depth = max(0, item.path.strip("/").count("/"))
        name = item.path.strip("/").split("/")[-1]
        prefix = "    " * depth
        cell.text_label.text = f"{prefix}{name}"
        cell.text_label.text_color = "#1f2937"
        cell.accessory_type = "checkmark" if item.selected else "none"
        cell.selectable = True
        cell.background_color = "#f9fafb" if row % 2 == 0 else "#ffffff"
        return cell

    def tableview_did_select(self, tv, _section, row: int) -> None:
        self.app.toggle_selection(row)
        tv.reload_data()


class Repo2TxtApp(UIBaseView):
    def __init__(self) -> None:
        if ui is None:
            raise RuntimeError("This script must be run inside Pythonista.")
        super().__init__(name="repo2txt (Pythonista)", bg_color="#f3f4f6")
        self.files: List[FileEntry] = []
        self.extension_map: Dict[str, List[int]] = {}
        self.zip_bytes: Optional[bytes] = None

        self.repo_field = ui.TextField(placeholder="GitHub URL (https://github.com/owner/repo)", flex="W")
        self.token_field = ui.TextField(placeholder="Personal Access Token (optional)", secure=True, flex="W")
        self.status_label = ui.Label(text="Ready", text_color="#4b5563", flex="W")
        self.ext_scroll = ui.ScrollView(flex="WH", shows_horizontal_scroll_indicator=False)
        self.table = ui.TableView(flex="WH")
        self.output = ui.TextView(editable=False, flex="WH", font=("Menlo", 13))

        self.fetch_button = ui.Button(title="Fetch Directory", bg_color="#3b82f6", tint_color="white")
        self.generate_button = ui.Button(title="Generate Text", bg_color="#10b981", tint_color="white")
        self.zip_button = ui.Button(title="Download Zip", bg_color="#8b5cf6", tint_color="white")
        self.local_button = ui.Button(title="Import Local (zip/file/folder)", bg_color="#6366f1", tint_color="white")
        self.copy_button = ui.Button(title="Copy", bg_color="#6366f1", tint_color="white")
        self.save_button = ui.Button(title="Save Text", bg_color="#ec4899", tint_color="white")

        self._configure_layout()
        self._connect_actions()

    def _configure_layout(self) -> None:
        padding = 10
        width = self.width or 400

        self.repo_field.frame = (padding, padding, width - 2 * padding, 36)
        self.token_field.frame = (padding, self.repo_field.y + 42, width - 2 * padding, 36)

        self.fetch_button.frame = (padding, self.token_field.y + 46, (width - 3 * padding) / 2, 36)
        self.local_button.frame = (
            self.fetch_button.x + self.fetch_button.width + padding,
            self.fetch_button.y,
            (width - 3 * padding) / 2,
            36,
        )

        self.ext_scroll.frame = (padding, self.fetch_button.y + 46, width - 2 * padding, 36)
        self.table.frame = (padding, self.ext_scroll.y + 42, width - 2 * padding, 220)

        self.generate_button.frame = (padding, self.table.y + self.table.height + 10, (width - 3 * padding) / 2, 36)
        self.zip_button.frame = (
            self.generate_button.x + self.generate_button.width + padding,
            self.generate_button.y,
            (width - 3 * padding) / 2,
            36,
        )

        self.copy_button.frame = (padding, self.generate_button.y + 46, (width - 3 * padding) / 2, 36)
        self.save_button.frame = (
            self.copy_button.x + self.copy_button.width + padding,
            self.copy_button.y,
            (width - 3 * padding) / 2,
            36,
        )

        self.output.frame = (padding, self.copy_button.y + 46, width - 2 * padding, 220)
        self.status_label.frame = (padding, self.output.y + self.output.height + 8, width - 2 * padding, 20)

        self.table.data_source = FilesDataSource(self)
        self.table.delegate = self.table.data_source

        for view in [
            self.repo_field,
            self.token_field,
            self.fetch_button,
            self.local_button,
            self.ext_scroll,
            self.table,
            self.generate_button,
            self.zip_button,
            self.copy_button,
            self.save_button,
            self.output,
            self.status_label,
        ]:
            self.add_subview(view)

    def layout(self) -> None:
        self._configure_layout()

    def _connect_actions(self) -> None:
        self.fetch_button.action = self.fetch_repo
        self.local_button.action = self.import_local
        self.generate_button.action = self.generate_text
        self.zip_button.action = self.download_zip
        self.copy_button.action = self.copy_output
        self.save_button.action = self.save_output

    def set_status(self, message: str) -> None:
        self.status_label.text = message

    def refresh_extensions(self) -> None:
        for subview in list(self.ext_scroll.subviews):
            self.ext_scroll.remove_subview(subview)
        x = 0
        sorted_exts = sorted(self.extension_map.items(), key=lambda item: len(item[1]), reverse=True)
        for ext, indexes in sorted_exts:
            container = ui.View(frame=(x, 0, 110, 32))
            switch = ui.Switch(value=self._ext_all_selected(indexes))
            label = ui.Label(text=f".{ext}" if ext else "[no ext]", frame=(52, 0, 56, 32), text_color="#111827")
            switch.action = self._extension_toggle_handler(indexes)
            container.add_subview(switch)
            container.add_subview(label)
            self.ext_scroll.add_subview(container)
            x += 112
        self.ext_scroll.content_size = (x, 32)

    def _ext_all_selected(self, indexes: List[int]) -> bool:
        return all(self.files[i].selected for i in indexes)

    def _extension_toggle_handler(self, indexes: List[int]):
        def handler(sender):
            for idx in indexes:
                self.files[idx].selected = bool(sender.value)
            self.table.reload_data()

        return handler

    def rebuild_extension_map(self) -> None:
        ext_map: Dict[str, List[int]] = {}
        for idx, item in enumerate(self.files):
            ext = os.path.splitext(item.path)[1].lower().lstrip(".")
            ext_map.setdefault(ext, []).append(idx)
        self.extension_map = ext_map
        self.refresh_extensions()

    def toggle_selection(self, row: int) -> None:
        self.files[row].selected = not self.files[row].selected

    def set_files(self, entries: List[FileEntry]) -> None:
        self.files = sort_contents(entries)
        for entry in self.files:
            ext = os.path.splitext(entry.path)[1].lower()
            entry.selected = ext in COMMON_EXTENSIONS
        self.rebuild_extension_map()
        self.table.reload_data()

    @ui.in_background
    def fetch_repo(self, _sender) -> None:
        try:
            self.set_status("Fetching repository...")
            owner, repo, last = parse_repo_url(self.repo_field.text or "")
            token = self.token_field.text or ""
            ref_from_url = ""
            path_from_url = ""
            if last:
                refs = get_references(owner, repo, token)
                all_refs = refs["branches"] + refs["tags"]
                match = next((r for r in all_refs if last.startswith(r)), None)
                if match:
                    ref_from_url = match
                    path_from_url = last[len(match) + 1 :] if last.startswith(f"{match}/") else ""
                else:
                    ref_from_url = last
            sha = fetch_repo_sha(owner, repo, ref_from_url, path_from_url, token)
            tree = fetch_repo_tree(owner, repo, sha, token)
            entries: List[FileEntry] = []
            for item in tree:
                if item.get("type") != "blob":
                    continue
                path = item.get("path", "")
                if not path.startswith("/"):
                    path = f"/{path}"
                entries.append(FileEntry(path=path, url=item.get("url", ""), url_type="github"))
            if not entries:
                raise RuntimeError("Repository has no files to display.")
            self.set_files(entries)
            self.set_status(f"Loaded {len(entries)} files from GitHub.")
        except (ValueError, RuntimeError, requests.RequestException, OSError) as exc:
            if dialogs:
                dialogs.hud_alert(str(exc), "error", 2.5)
            self.set_status(f"Error: {exc}")

    @ui.in_background
    def import_local(self, _sender) -> None:
        if dialogs is None:
            self.set_status("dialogs module unavailable.")
            return
        path = dialogs.pick_document()
        if not path:
            return
        if os.path.isdir(path):
            self._load_directory(path)
            return
        if path.lower().endswith(".zip"):
            self._load_zip(path)
            return
        entries = [
            FileEntry(
                path=f"/{os.path.basename(path)}",
                url=path,
                url_type="local",
            )
        ]
        self.zip_bytes = None
        self.set_files(entries)
        self.set_status("Loaded local file.")

    def _load_zip(self, path: str) -> None:
        try:
            with open(path, "rb") as fh:
                self.zip_bytes = fh.read()
            zf = zipfile.ZipFile(io.BytesIO(self.zip_bytes))
            entries: List[FileEntry] = []
            gitignore_rules = [".git/**"]
            for info in zf.infolist():
                if info.is_dir():
                    continue
                rel_path = info.filename
                if rel_path.endswith(".gitignore"):
                    gitignore_rules.extend(
                        self._read_gitignore(
                            zf.read(info.filename).decode("utf-8", errors="ignore"), rel_path
                        )
                    )
                entries.append(FileEntry(path=f"/{rel_path}", url=rel_path, url_type="zip"))
            filtered = [e for e in entries if not is_ignored(e.path, gitignore_rules)]
            if not filtered:
                raise RuntimeError("No files found after applying .gitignore rules.")
            self.set_files(filtered)
            self.set_status(f"Loaded {len(filtered)} files from zip.")
        except zipfile.BadZipFile as exc:
            if dialogs:
                dialogs.hud_alert(f"Zip error: {exc}", "error", 2.5)
            self.set_status("Zip error: Invalid or corrupted archive.")
        except UnicodeDecodeError as exc:
            if dialogs:
                dialogs.hud_alert(f"Encoding error: {exc}", "error", 2.5)
            self.set_status("Encoding error while reading archive contents.")
        except (OSError, zipfile.LargeZipFile, RuntimeError) as exc:
            if dialogs:
                dialogs.hud_alert(f"Zip error: {exc}", "error", 2.5)
            self.set_status(f"Zip error: {exc}")

    def _load_directory(self, path: str) -> None:
        try:
            entries: List[FileEntry] = []
            gitignore_rules = [".git/**"]
            base_path = path.rstrip("/")
            
            # First pass: collect all files and read .gitignore files
            for root, dirs, files in os.walk(base_path):
                # Skip .git directory
                if ".git" in dirs:
                    dirs.remove(".git")
                
                for filename in files:
                    file_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(file_path, base_path)
                    
                    # Read .gitignore files to collect rules
                    if filename == ".gitignore":
                        try:
                            with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                                gitignore_rules.extend(
                                    self._read_gitignore(fh.read(), rel_path)
                                )
                        except OSError:
                            pass  # Skip if we can't read the .gitignore file
                    
                    entries.append(
                        FileEntry(
                            path=f"/{rel_path}",
                            url=file_path,
                            url_type="local",
                        )
                    )
            
            # Filter out ignored files
            filtered = [e for e in entries if not is_ignored(e.path, gitignore_rules)]
            if not filtered:
                raise RuntimeError("No files found after applying .gitignore rules.")
            
            self.zip_bytes = None
            self.set_files(filtered)
            self.set_status(f"Loaded {len(filtered)} files from directory.")
        except OSError as exc:
            if dialogs:
                dialogs.hud_alert(f"Directory error: {exc}", "error", 2.5)
            self.set_status(f"Directory error: {exc}")
        except RuntimeError as exc:
            if dialogs:
                dialogs.hud_alert(str(exc), "error", 2.5)
            self.set_status(f"Error: {exc}")

    def _read_gitignore(self, content: str, rel_path: str) -> List[str]:
        rules: List[str] = []
        base = "/".join(rel_path.split("/")[:-1])
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rules.append(f"{base}/{line}" if base else line)
        return rules

    def _get_selected(self) -> List[FileEntry]:
        return [item for item in self.files if item.selected]

    def _fetch_file_contents(self, items: List[FileEntry]) -> List[Tuple[str, str]]:
        results: List[Tuple[str, str]] = []
        token = self.token_field.text or ""
        for item in items:
            if item.url_type == "github":
                resp = requests.get(item.url, headers=auth_headers(token, "application/vnd.github.v3.raw"))
                if not resp.ok:
                    handle_fetch_error(resp)
                results.append((item.path, resp.text))
            elif item.url_type == "local":
                with open(item.url, "r", encoding="utf-8", errors="ignore") as fh:
                    results.append((item.path, fh.read()))
            elif item.url_type == "zip" and self.zip_bytes:
                with zipfile.ZipFile(io.BytesIO(self.zip_bytes)) as zf:
                    with zf.open(item.url) as fh:
                        results.append((item.path, fh.read().decode("utf-8", errors="ignore")))
        return results

    @ui.in_background
    def generate_text(self, _sender) -> None:
        try:
            selected = self._get_selected()
            if not selected:
                raise RuntimeError("No files selected.")
            self.set_status("Fetching file contents...")
            contents = self._fetch_file_contents(selected)
            formatted = format_repo_contents(contents)
            self.output.text = formatted
            approx_tokens = len(formatted.split())
            self.set_status(f"Generated text (~{approx_tokens} tokens).")
        except (RuntimeError, requests.RequestException, OSError, zipfile.BadZipFile) as exc:
            if dialogs:
                dialogs.hud_alert(str(exc), "error", 2.5)
            self.set_status(f"Error: {exc}")

    @ui.in_background
    def download_zip(self, _sender) -> None:
        try:
            selected = self._get_selected()
            if not selected:
                raise RuntimeError("No files selected.")
            contents = self._fetch_file_contents(selected)
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temp:
                    temp_path = temp.name
                    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                        for path, text in contents:
                            zf.writestr(path.lstrip("/"), text)
                if dialogs:
                    dialogs.share_file(temp_path)
                    ui.delay(lambda: self._safe_unlink(temp_path), TEMP_FILE_CLEANUP_DELAY)
            finally:
                if temp_path and not dialogs:
                    self._safe_unlink(temp_path)
            self.set_status("Zip ready to share.")
        except (RuntimeError, requests.RequestException, OSError, zipfile.BadZipFile) as exc:
            if dialogs:
                dialogs.hud_alert(str(exc), "error", 2.5)
            self.set_status(f"Error: {exc}")

    @ui.in_background
    def copy_output(self, _sender) -> None:
        if not self.output.text.strip():
            self.set_status("Nothing to copy.")
            return
        if clipboard is None:
            self.set_status("Clipboard unavailable.")
            return
        clipboard.set(self.output.text)
        self.set_status("Copied to clipboard.")

    @ui.in_background
    def save_output(self, _sender) -> None:
        if not self.output.text.strip():
            self.set_status("Nothing to save.")
            return
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as temp:
                temp_path = temp.name
                temp.write(self.output.text.encode("utf-8"))
            if dialogs:
                dialogs.share_file(temp_path)
                ui.delay(lambda: self._safe_unlink(temp_path), TEMP_FILE_CLEANUP_DELAY)
        finally:
            if temp_path and not dialogs:
                self._safe_unlink(temp_path)
        self.set_status("Text file ready to share.")

    @staticmethod
    def _safe_unlink(path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass


def main() -> None:
    if ui is None:
        print("This script must be run inside Pythonista on iOS.")
        return
    app = Repo2TxtApp()
    app.present("fullscreen")


if __name__ == "__main__":
    main()
