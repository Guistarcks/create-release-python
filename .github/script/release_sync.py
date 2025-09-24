#!/usr/bin/env python3
"""
release_sync.py

Uso esperado (desde GitHub Actions):
  - Evento: pull_request.closed (merge a main desde release/x.y.z)
  - Pasar SOURCE_BRANCH (ej: release/1.0.0) o el workflow lo provee desde GITHUB_EVENT_PATH.
  - Requiere: gh CLI instalado y autenticado, GITHUB_TOKEN, y permisos de push.

Funciones:
  - Quitar -snapshot en main (package.json + pom.xml)
  - Crear tag vX.Y.Z y GitHub Release
  - Crear branch desde develop, merge main -> branch, bump minor + -snapshot en versiones, crear PR y mergearlo.
"""
import argparse
import os
import re
import subprocess
import sys
import json
from glob import glob
import xml.etree.ElementTree as ET
from typing import Tuple, List, Optional

# ---------- Utilities ----------

def run(cmd, capture_output=False, check=True, env=None):
    if isinstance(cmd, str):
        shell = True
    else:
        shell = False
    result = subprocess.run(cmd, shell=shell, capture_output=capture_output, text=True, check=check, env=env)
    return result

def git_config(user_name="github-actions[bot]", user_email="github-actions[bot]@users.noreply.github.com"):
    run(["git", "config", "--global", "user.name", user_name])
    run(["git", "config", "--global", "user.email", user_email])

def set_remote_with_token(repo_full_name: str, token: str):
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to set remote URL")
    remote = f"https://x-access-token:{token}@github.com/{repo_full_name}.git"
    run(["git", "remote", "set-url", "origin", remote])

def extract_version_from_branch(branch: str) -> Optional[str]:
    m = re.match(r"^release\/(?P<ver>\d+\.\d+\.\d+)$", branch)
    if m:
        return m.group("ver")
    return None

def split_version_str(v: str) -> Optional[Tuple[str, str, str]]:
    """
    Split a version-like string into (prefix, semver, suffix).
    Example:
      'cba-1.0.0-snapshot' -> ('cba-', '1.0.0', '-snapshot')
      '1.0.0' -> ('', '1.0.0', '')
    """
    m = re.search(r'(?P<semver>\d+\.\d+\.\d+)', v)
    if not m:
        return None
    semver = m.group('semver')
    prefix = v[:m.start('semver')]
    suffix = v[m.end('semver'):]
    return (prefix, semver, suffix)

def bump_minor_semver(semver: str) -> str:
    major, minor, patch = map(int, semver.split('.'))
    minor += 1
    patch = 0
    return f"{major}.{minor}.{patch}"

def find_package_json_files() -> List[str]:
    return [p for p in glob("**/package.json", recursive=True) if "/node_modules/" not in p and ".github/" not in p]

def find_pom_files() -> List[str]:
    return [p for p in glob("**/pom.xml", recursive=True) if ".github/" not in p]

# ---------- Update package.json ----------

def update_package_json_remove_snapshot(files: List[str], source_semver: str) -> List[str]:
    changed = []
    for f in files:
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        v = data.get("version")
        if not v:
            continue
        parts = split_version_str(v)
        if not parts:
            continue
        prefix, semver, suffix = parts
        # Remove snapshot if semver matches or suffix contains snapshot
        if semver == source_semver or re.search(r'snapshot', suffix, re.IGNORECASE):
            new_v = prefix + semver
            if new_v != v:
                data["version"] = new_v
                with open(f, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, ensure_ascii=False)
                    fh.write("\n")
                changed.append(f)
                print(f"[package.json] updated {f}: {v} -> {new_v}")
    return changed

def update_package_json_add_snapshot_bump(files: List[str], source_semver: str) -> Tuple[List[str], str]:
    changed = []
    bumped_semver = bump_minor_semver(source_semver)
    new_version_global = None
    for f in files:
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        v = data.get("version")
        if not v:
            continue
        parts = split_version_str(v)
        if not parts:
            continue
        prefix, semver, suffix = parts
        # If the current semver equals source_semver (release) OR (no semver but contains snapshot) -> bump
        if semver == source_semver or re.search(r'snapshot', suffix, re.IGNORECASE):
            new_v = prefix + bumped_semver + "-snapshot"
            if new_v != v:
                data["version"] = new_v
                with open(f, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, ensure_ascii=False)
                    fh.write("\n")
                changed.append(f)
                new_version_global = new_v
                print(f"[package.json] updated {f}: {v} -> {new_v}")
    return changed, new_version_global or (("unknown-prefix-" + bumped_semver + "-snapshot"))

# ---------- Update pom.xml ----------

def xml_namespace_of(root_tag: str) -> Optional[str]:
    m = re.match(r'\{(.+)\}', root_tag)
    return m.group(1) if m else None

def update_pom_remove_snapshot(files: List[str], source_semver: str) -> List[str]:
    changed = []
    for f in files:
        tree = ET.parse(f)
        root = tree.getroot()
        ns = xml_namespace_of(root.tag)
        parent_map = {c: p for p in root.iter() for c in list(p)}

        modified = False
        for elem in root.iter():
            tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_local.lower() != "version":
                continue
            # Skip if inside dependency or dependencyManagement
            p = parent_map.get(elem)
            skip = False
            while p is not None:
                p_local = p.tag.split('}')[-1] if '}' in p.tag else p.tag
                if p_local in ("dependency", "dependencies", "dependencyManagement", "plugin", "plugins"):
                    skip = True
                    break
                p = parent_map.get(p)
            if skip:
                continue
            text = elem.text.strip() if elem.text else ""
            if not text:
                continue
            sp = split_version_str(text)
            if not sp:
                # Could be something else, check snapshot suffix
                if re.search(r'snapshot', text, re.IGNORECASE):
                    new_text = re.sub(r'[-]?snapshot', '', text, flags=re.IGNORECASE)
                    elem.text = new_text
                    modified = True
                    print(f"[pom] {f}: {text} -> {new_text}")
                continue
            prefix, semver, suffix = sp
            if semver == source_semver or re.search(r'snapshot', suffix, re.IGNORECASE) or re.search(r'snapshot', text, re.IGNORECASE):
                new_text = prefix + semver
                if new_text != text:
                    elem.text = new_text
                    modified = True
                    print(f"[pom] {f}: {text} -> {new_text}")
        if modified:
            tree.write(f, encoding='utf-8', xml_declaration=True)
            changed.append(f)
    return changed

def update_pom_add_snapshot_bump(files: List[str], source_semver: str) -> Tuple[List[str], str]:
    changed = []
    bumped_semver = bump_minor_semver(source_semver)
    new_version_global = None
    for f in files:
        tree = ET.parse(f)
        root = tree.getroot()
        ns = xml_namespace_of(root.tag)
        parent_map = {c: p for p in root.iter() for c in list(p)}

        modified = False
        for elem in root.iter():
            tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_local.lower() != "version":
                continue
            # Skip dependency versions
            p = parent_map.get(elem)
            skip = False
            while p is not None:
                p_local = p.tag.split('}')[-1] if '}' in p.tag else p.tag
                if p_local in ("dependency", "dependencies", "dependencyManagement", "plugin", "plugins"):
                    skip = True
                    break
                p = parent_map.get(p)
            if skip:
                continue
            text = elem.text.strip() if elem.text else ""
            if not text:
                continue
            sp = split_version_str(text)
            if not sp:
                # if contains snapshot replace with bumped
                if re.search(r'snapshot', text, re.IGNORECASE):
                    new_text = re.sub(r'(?i)snapshot', bumped_semver + "-SNAPSHOT", text)
                    elem.text = new_text
                    modified = True
                    print(f"[pom] {f}: {text} -> {new_text}")
                    new_version_global = new_text
                continue
            prefix, semver, suffix = sp
            if semver == source_semver or re.search(r'snapshot', suffix, re.IGNORECASE):
                new_text = prefix + bumped_semver + "-SNAPSHOT"
                if new_text != text:
                    elem.text = new_text
                    modified = True
                    new_version_global = new_text
                    print(f"[pom] {f}: {text} -> {new_text}")
        if modified:
            tree.write(f, encoding='utf-8', xml_declaration=True)
            changed.append(f)
    return changed, new_version_global or (("unknown-" + bumped_semver + "-SNAPSHOT"))

# ---------- Git / GH helpers ----------

def git_has_changes() -> bool:
    r = run(["git", "status", "--porcelain"], capture_output=True)
    return bool(r.stdout.strip())

def git_commits_ahead(base: str = "origin/develop") -> int:
    # count commits HEAD..base difference
    r = run(["git", "rev-list", f"{base}..HEAD", "--count"], capture_output=True)
    return int(r.stdout.strip())

def main():
    parser = argparse.ArgumentParser(description="Sync release -> main -> develop (remove snapshots, create tag/release, bump develop).")
    parser.add_argument("--source-branch", help="Branch source (ej: release/1.0.0). Si no se pasa, se intentará leer GITHUB_EVENT_PATH.")
    args = parser.parse_args()

    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    event_path = os.environ.get("GITHUB_EVENT_PATH")

    # determine source branch
    source_branch = args.source_branch
    if not source_branch and event_path and os.path.exists(event_path):
        try:
            import json as _json
            ev = _json.load(open(event_path, "r"))
            # pull_request events have head.ref
            if "pull_request" in ev:
                source_branch = ev["pull_request"]["head"]["ref"]
        except Exception as e:
            print("No se pudo leer GITHUB_EVENT_PATH:", e)

    if not source_branch:
        print("ERROR: no se proporcionó --source-branch ni se pudo inferir desde GITHUB_EVENT_PATH.")
        sys.exit(1)

    source_semver = extract_version_from_branch(source_branch)
    if not source_semver:
        print(f"ERROR: la branch '{source_branch}' no tiene formato release/X.Y.Z")
        sys.exit(1)

    if not token:
        print("ERROR: GITHUB_TOKEN no encontrado en entorno.")
        sys.exit(1)

    print(f"Source branch: {source_branch} -> version {source_semver}")

    # Set git config and remote
    git_config()
    set_remote_with_token(repo, token)

    # Ensure up-to-date
    run(["git", "fetch", "origin"])
    run(["git", "checkout", "main"])
    run(["git", "pull", "origin", "main"])

    # ---------- 1) Remove snapshots in main ----------
    pkg_files = find_package_json_files()
    pom_files = find_pom_files()
    print("package.json encontrados:", pkg_files)
    print("pom.xml encontrados:", pom_files)

    changed_pkg = update_package_json_remove_snapshot(pkg_files, source_semver)
    changed_pom = update_pom_remove_snapshot(pom_files, source_semver)

    if changed_pkg or changed_pom:
        run(["git", "add"] + changed_pkg + changed_pom)
        run(["git", "commit", "-m", f"chore(release): remove -snapshot for v{source_semver}"])
        run(["git", "push", "origin", "main"])
        print("Commited and pushed snapshot removals to main.")
    else:
        print("No hubo cambios (snapshots ya habian sido removidos).")

    # ---------- 2) Create tag + release ----------
    tag = f"v{source_semver}"
    try:
        run(["git", "tag", "-a", tag, "-m", f"Release {tag}"])
    except subprocess.CalledProcessError:
        print(f"Tag {tag} ya existe localmente, continuar.")
    # push tag
    run(["git", "push", "origin", tag])

    # create GH release
    print("Creating GitHub release", tag)
    run(["gh", "release", "create", tag, "--title", f"Release {tag}", "--generate-notes"], env={**os.environ, "GITHUB_TOKEN": token})
    print("Release creada:", tag)

    # ---------- 3) Sync main -> develop (branch -> PR -> merge) ----------
    sync_branch = f"release-sync/{source_semver}"
    run(["git", "fetch", "origin"])
    # create branch from origin/develop
    # delete local branch if exists
    try:
        run(["git", "branch", "-D", sync_branch], check=False)
    except Exception:
        pass
    run(["git", "checkout", "-b", sync_branch, "origin/develop"])

    # merge main into this branch
    try:
        run(["git", "merge", "origin/main", "--no-edit"])
    except subprocess.CalledProcessError:
        print("ERROR: merge conflict when merging origin/main into sync branch.")
        sys.exit(1)

    # After merge, bump versions and add -snapshot on develop branch
    ch_pkg_dev, new_pkg_version = update_package_json_add_snapshot_bump(pkg_files, source_semver)
    ch_pom_dev, new_pom_version = update_pom_add_snapshot_bump(pom_files, source_semver)
    all_changed = ch_pkg_dev + ch_pom_dev

    # If there are changes or if branch contains extra commits (from merge), push and create PR
    commits_ahead = git_commits_ahead("origin/develop")
    if commits_ahead > 0 or all_changed:
        if all_changed:
            run(["git", "add"] + all_changed)
            new_version_display = new_pkg_version if new_pkg_version else new_pom_version
            run(["git", "commit", "-m", f"chore: bump dev version to {new_version_display}"])
        # push branch
        run(["git", "push", "-u", "origin", sync_branch])
        # create PR
        pr_create = run(["gh", "pr", "create", "--base", "develop", "--head", sync_branch,
                         "--title", f"Sync main -> develop for v{source_semver}",
                         "--body", f"Auto-sync main into develop after release v{source_semver}"],
                        capture_output=True, env={**os.environ, "GITHUB_TOKEN": token})
        pr_url = pr_create.stdout.strip()
        print("PR creado:", pr_url)
        # merge PR
        try:
            run(["gh", "pr", "merge", pr_url, "--merge", "--admin", "--delete-branch"], env={**os.environ, "GITHUB_TOKEN": token})
            print("PR mergeado y branch eliminado.")
        except subprocess.CalledProcessError as e:
            print("ERROR mergeando PR automáticamente:", e)
            sys.exit(1)
    else:
        print("Nada que sincronizar: develop ya contiene los cambios.")

    print("Proceso completado con éxito.")

if __name__ == "__main__":
    main()
