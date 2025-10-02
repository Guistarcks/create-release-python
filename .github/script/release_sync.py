#!/usr/bin/env python3
"""
release_sync.py

Flujo esperado:
  1) Detectar merge a main desde release/X.Y.Z
  2) Quitar -snapshot en main (root package.json + root pom.xml)
  3) Crear tag vX.Y.Z y GitHub Release
  4) Merge directo main -> develop
  5) Bump minor + añadir -snapshot en develop (package.json + pom.xml)
  Autor: Agnaldo Cavaleiro Costa
"""

import argparse, json, os, re, subprocess, sys
from xml.etree import ElementTree as ET
from typing import Optional, Tuple

# ----------------- Helpers -----------------

def run(cmd, capture_output=False, check=True, env=None):
    shell = not isinstance(cmd, (list, tuple))
    return subprocess.run(cmd, shell=shell, capture_output=capture_output, text=True, check=check, env=env)

def git_config(user_name="github-actions[bot]", user_email="github-actions[bot]@users.noreply.github.com"):
    run(["git", "config", "--global", "user.name", user_name])
    run(["git", "config", "--global", "user.email", user_email])

def set_remote_with_token(repo_full_name: str, token: str):
    if not token: raise RuntimeError("GITHUB_TOKEN is required")
    remote = f"https://x-access-token:{token}@github.com/{repo_full_name}.git"
    run(["git", "remote", "set-url", "origin", remote])

def extract_version_from_branch(branch: str) -> Optional[str]:
    m = re.match(r"^(release|hotfix)/(?P<ver>\d+\.\d+\.\d+)$", branch)
    return m.group("ver") if m else None

def split_version_str(v: str) -> Optional[Tuple[str, str, str]]:
    m = re.search(r'(?P<semver>\d+\.\d+\.\d+)', v)
    if not m: return None
    semver = m.group('semver')
    prefix = v[:m.start('semver')]
    suffix = v[m.end('semver'):]
    return prefix, semver, suffix


# Bump la parte de la versión que cambió (major, minor o patch)
def bump_semver(prev: str, new: str) -> str:
    prev_major, prev_minor, prev_patch = map(int, prev.split('.'))
    new_major, new_minor, new_patch = map(int, new.split('.'))
    if new_major > prev_major:
        # Bump major
        return f"{new_major + 1}.0.0"
    elif new_minor > prev_minor:
        # Bump minor
        return f"{new_major}.{new_minor + 1}.0"
    elif new_patch > prev_patch:
        # Bump patch
        return f"{new_major}.{new_minor}.{new_patch + 1}"
    else:
        # Si no hay cambio, default bump minor
        return f"{new_major}.{new_minor + 1}.0"

def root_package_json() -> Optional[str]:
    return "package.json" if os.path.exists("package.json") else None



# Busca todos los pom.xml en el repo (excepto target/ y directorios ocultos)
def find_all_poms() -> list:
    poms = []
    for root, dirs, files in os.walk("."):
        # Ignorar carpetas target y ocultas
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'target']
        if "pom.xml" in files:
            poms.append(os.path.join(root, "pom.xml"))
    return poms

# ----------------- package.json -----------------

def remove_snapshot_from_package_json(path: str, source_semver: str) -> bool:
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    v = data.get("version")
    if not v:
        return False
    parts = split_version_str(v)
    if not parts:
        return False
    prefix, semver, suffix = parts
    # Siempre poner la version de la release (source_semver), quitando cualquier -SNAPSHOT
    new_v = prefix + source_semver
    if v != new_v:
        data["version"] = new_v
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"[package.json] {path}: {v} -> {new_v}")
        return True
    # Si la versión es igual pero tiene -SNAPSHOT, quitarlo
    if v.endswith("-SNAPSHOT") or v.endswith("-snapshot"):
        data["version"] = new_v
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"[package.json] {path}: {v} -> {new_v}")
        return True
    return False

def add_snapshot_bump_package_json(path: str, source_semver: str) -> Optional[str]:
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    v = data.get("version")
    if not v:
        return None
    parts = split_version_str(v)
    if not parts:
        return None
    prefix, semver, suffix = parts
    # Detectar versión actual para decidir el tipo de bump
    current_semver = semver
    new_semver = bump_semver(current_semver, source_semver)
    new_v = prefix + new_semver + "-snapshot"
    if new_v != v:
        data["version"] = new_v
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"[package.json] {path}: {v} -> {new_v}")
        return new_v
    return None

# ----------------- pom.xml -----------------

def remove_snapshot_from_pom(path: str, source_semver: str) -> bool:
    tree = ET.parse(path)
    root = tree.getroot()
    parent_map = {c: p for p in root.iter() for c in list(p)}
    changed = False
    # Registrar el namespace vacío para evitar prefijos ns0: en todos los poms
    ET.register_namespace('', "http://maven.apache.org/POM/4.0.0")
    for elem in root.iter():
        tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if tag_local.lower() != "version": continue
        p = parent_map.get(elem)
        skip = False
        while p is not None:
            p_local = p.tag.split('}')[-1] if '}' in p.tag else p.tag
            if p_local in ("dependency","dependencies","dependencyManagement","plugin","plugins"): skip=True; break
            p = parent_map.get(p)
        if skip: continue
        text = (elem.text or "").strip()
        if not text: continue
        parts = split_version_str(text)
        # Siempre poner la version de la release (source_semver), quitando cualquier -SNAPSHOT
        if parts:
            prefix, semver, suffix = parts
            new_text = prefix + source_semver
            if text != new_text:
                elem.text = new_text
                changed = True
                print(f"[pom] {path}: {text} -> {new_text}")
            elif re.search(r'snapshot', suffix, re.IGNORECASE):
                elem.text = new_text
                changed = True
                print(f"[pom] {path}: {text} -> {new_text}")
        else:
            if re.search(r'snapshot', text, re.IGNORECASE):
                new_text = re.sub(r'[-]?snapshot', '', text, flags=re.IGNORECASE)
                if new_text != text:
                    elem.text = new_text
                    changed = True
                    print(f"[pom] {path}: {text} -> {new_text}")
    if changed: tree.write(path, encoding='utf-8', xml_declaration=True)
    return changed

def add_snapshot_bump_pom(path: str, source_semver: str) -> Optional[str]:
    tree = ET.parse(path)
    root = tree.getroot()
    parent_map = {c: p for p in root.iter() for c in list(p)}
    new_version = None
    # Detectar versión actual para decidir el tipo de bump
    # Buscar la versión actual del pom
    version_elem = None
    for elem in root.iter():
        tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if tag_local.lower() == "version":
            version_elem = elem
            break
    current_semver = source_semver
    if version_elem is not None:
        m = re.search(r'(\d+\.\d+\.\d+)', (version_elem.text or ''))
        if m:
            current_semver = m.group(1)
    new_semver = bump_semver(current_semver, source_semver)
    changed = False
    # Registrar el namespace vacío para evitar prefijos ns0: en todos los poms
    ET.register_namespace('', "http://maven.apache.org/POM/4.0.0")
    for elem in root.iter():
        tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if tag_local.lower() != "version": continue
        p = parent_map.get(elem)
        skip = False
        while p is not None:
            p_local = p.tag.split('}')[-1] if '}' in p.tag else p.tag
            if p_local in ("dependency","dependencies","dependencyManagement","plugin","plugins"): skip=True; break
            p = parent_map.get(p)
        if skip: continue
        text = (elem.text or "").strip()
        if not text: continue
        parts = split_version_str(text)
        if parts:
            prefix, semver, suffix = parts
            if semver==source_semver or re.search(r'snapshot', suffix, re.IGNORECASE):
                new_text = prefix + new_semver + "-SNAPSHOT"
                if new_text != text:
                    elem.text = new_text
                    changed = True
                    new_version = new_text
                    print(f"[pom] {path}: {text} -> {new_text}")
        else:
            if re.search(r'snapshot', text, re.IGNORECASE):
                new_text = re.sub(r'(?i)snapshot', new_semver + "-SNAPSHOT", text)
                if new_text != text:
                    elem.text = new_text
                    changed = True
                    new_version = new_text
                    print(f"[pom] {path}: {text} -> {new_text}")
    if changed: tree.write(path, encoding='utf-8', xml_declaration=True)
    return new_version

# ----------------- Main -----------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-branch", help="release/X.Y.Z")
    args = parser.parse_args()

    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    event_path = os.environ.get("GITHUB_EVENT_PATH")

    source_branch = args.source_branch
    if not source_branch and event_path and os.path.exists(event_path):
        try:
            ev = json.load(open(event_path))
            if "pull_request" in ev: source_branch = ev["pull_request"]["head"]["ref"]
        except: pass

    if not source_branch: sys.exit("ERROR: debe pasar --source-branch o tener GITHUB_EVENT_PATH")

    source_semver = extract_version_from_branch(source_branch)
    if not source_semver: sys.exit(f"ERROR: branch '{source_branch}' no tiene formato release/X.Y.Z")

    if not token: sys.exit("ERROR: GITHUB_TOKEN no presente")

    print(f"Source branch: {source_branch} -> version {source_semver}")

    # git setup
    git_config()
    if repo: set_remote_with_token(repo, token)
    run(["git", "fetch", "origin"])
    run(["git", "checkout", "main"])
    run(["git", "pull", "origin", "main"])

    # root files
    pkg = root_package_json()
    poms = find_all_poms()

    # 1) Remove snapshot in main
    changed_files = []
    if pkg and remove_snapshot_from_package_json(pkg, source_semver): changed_files.append(pkg)
    for pom in poms:
        if remove_snapshot_from_pom(pom, source_semver): changed_files.append(pom)
    if changed_files:
        run(["git","add"] + changed_files)
        run(["git","commit","-m",f"chore(release): remove -snapshot for v{source_semver}"])
        run(["git","push","origin","main"])

    # 2) Tag + release
    tag = f"v{source_semver}"
    try: run(["git","tag","-a",tag,"-m",f"Release {tag}"])
    except: pass
    run(["git","push","origin",tag])
    try:
        run(["gh","release","create",tag,"--title",f"Release {tag}","--generate-notes"], env={**os.environ,"GITHUB_TOKEN":token})
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr if hasattr(e, 'stderr') and e.stderr else str(e)
        if "Release.tag_name ya existe en GitHub" in err_msg or f"tag '{tag}' ya existe" in err_msg:
            sys.exit(f"ERROR: La release con el tag {tag} ya existe en GitHub.")
        else:
            sys.exit(f"ERROR al crear la release: {err_msg}")

    # 3) Merge main -> develop
    run(["git","checkout","develop"])
    run(["git","pull","origin","develop"])
    try: run(["git","merge","origin/main","--no-edit"])
    except subprocess.CalledProcessError: sys.exit("ERROR merge origin/main -> develop")

    # 4) Bump minor + snapshot in develop
    changed_dev = []
    new_versions = []
    if pkg:
        v = add_snapshot_bump_package_json(pkg, source_semver)
        if v: changed_dev.append(pkg); new_versions.append(v)
    for pom in poms:
        v = add_snapshot_bump_pom(pom, source_semver)
        if v: changed_dev.append(pom); new_versions.append(v)
    if changed_dev:
        run(["git","add"] + changed_dev)
        msg_ver = new_versions[0] if new_versions else "bumped"
        run(["git","commit","-m",f"chore: bump develop versions to {msg_ver}"])
        run(["git","push","origin","develop"])

    print("Proceso completado con éxito.")

if __name__ == "__main__": main()

