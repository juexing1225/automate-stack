#!/usr/bin/env python3
"""
AutomateStack Kit Builder & Verification Engine
Validates n8n workflows, checks connections, tests JavaScript syntax in Code nodes,
verifies docs/SETUP.md placeholder coverage, and packages verified kits into dist/kits/*.zip.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PRODUCTS_FILE = BASE_DIR / "products.json"
KITS_DIR = BASE_DIR / "kits"
DIST_KITS_DIR = BASE_DIR / "dist" / "kits"

PLACEHOLDER_REGEX = re.compile(r'\b(YOUR_[A-Z0-9_]+)\b')

def validate_javascript(js_code: str, node_name: str, file_path: str):
    """Checks JavaScript code for syntax errors using node -c."""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tmp:
        # Wrap in async function body to allow return statements and top-level expressions common in n8n
        wrapped_code = f"async function __n8n_test__() {{\n{js_code}\n}}"
        tmp.write(wrapped_code)
        tmp_path = tmp.name

    try:
        proc = subprocess.run(["node", "-c", tmp_path], capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"❌ [Syntax Error] Node '{node_name}' in {file_path} contains invalid JavaScript:")
            print(proc.stderr)
            return False
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return True

def validate_workflow(workflow_path: Path):
    """Validates structure, connections, and JavaScript in an n8n workflow."""
    errors = []
    placeholders = set()

    try:
        with open(workflow_path, "r", encoding="utf-8") as f:
            content = f.read()
            data = json.loads(content)
    except Exception as e:
        return [f"Invalid JSON in {workflow_path.name}: {e}"], set()

    # Find all placeholders in raw content
    for match in PLACEHOLDER_REGEX.finditer(content):
        placeholders.add(match.group(1))

    nodes = data.get("nodes", [])
    if not isinstance(nodes, list):
        errors.append(f"{workflow_path.name}: 'nodes' must be a list.")
        return errors, placeholders

    node_names = set()
    for n in nodes:
        name = n.get("name")
        if not name:
            errors.append(f"{workflow_path.name}: Found a node without a name.")
        else:
            node_names.add(name)

        # Check Code nodes
        if n.get("type") == "n8n-nodes-base.code" or "jsCode" in n.get("parameters", {}):
            js_code = n.get("parameters", {}).get("jsCode", "")
            if not validate_javascript(js_code, name, workflow_path.name):
                errors.append(f"{workflow_path.name}: JavaScript syntax check failed in Code node '{name}'.")

    # Check for dangling connections
    connections = data.get("connections", {})
    for src_node, outputs in connections.items():
        if src_node not in node_names:
            errors.append(f"{workflow_path.name}: Connection source '{src_node}' is not in nodes list.")
            continue
        
        for output_type, targets in outputs.items():
            for target_group in targets:
                for target_item in target_group:
                    tgt = target_item.get("node")
                    if tgt not in node_names:
                        errors.append(f"{workflow_path.name}: Dangling connection: '{src_node}' connects to non-existent node '{tgt}'.")

    return errors, placeholders

def check_setup_placeholders(setup_path: Path, required_placeholders: set):
    """Ensures all placeholders in the workflow are documented in docs/SETUP.md."""
    if not setup_path.exists():
        return [f"Missing required documentation: {setup_path}"]

    with open(setup_path, "r", encoding="utf-8") as f:
        doc_text = f.read()

    missing = []
    for ph in sorted(required_placeholders):
        if ph not in doc_text:
            missing.append(ph)

    if missing:
        return [f"{setup_path.name} missing documentation for placeholders: {', '.join(missing)}"]
    return []

def package_kit(kit_dir: Path, output_zip: Path):
    """Creates a verified zip file of the kit."""
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(kit_dir):
            for file in files:
                if file.startswith(".") or file.endswith(".pyc"):
                    continue
                full_path = Path(root) / file
                rel_path = full_path.relative_to(kit_dir)
                zf.write(full_path, rel_path)

    # Verify integrity of the created zip
    with zipfile.ZipFile(output_zip, "r") as zf:
        bad_file = zf.testzip()
        if bad_file:
            raise RuntimeError(f"Corrupt file in zip: {bad_file}")

def main():
    if not PRODUCTS_FILE.exists():
        print(f"Error: {PRODUCTS_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    products = catalog.get("products", [])
    if not products:
        print("No products found in catalog.", file=sys.stderr)
        sys.exit(1)

    total_errors = []
    built_kits = []

    print(f"=== AutomateStack Kit Verification & Build ===")
    print(f"Discovered {len(products)} products in catalog.\n")

    for prod in products:
        slug = prod.get("slug")
        title = prod.get("title")
        kit_dir = KITS_DIR / slug

        print(f"▶ Validating kit: {title} ({slug})")
        if not kit_dir.exists():
            total_errors.append(f"Directory {kit_dir} does not exist for product {slug}.")
            continue

        n8n_dir = kit_dir / "n8n"
        if not n8n_dir.exists():
            total_errors.append(f"Directory {n8n_dir} does not exist for product {slug}.")
            continue

        kit_placeholders = set()
        workflow_count = 0

        # Validate all n8n workflows in the kit
        for wf_file in sorted(n8n_dir.glob("*.json")):
            workflow_count += 1
            wf_errors, wf_placeholders = validate_workflow(wf_file)
            total_errors.extend(wf_errors)
            kit_placeholders.update(wf_placeholders)

        print(f"  ✓ Checked {workflow_count} workflow(s). Found placeholders: {sorted(kit_placeholders) if kit_placeholders else 'None'}")

        # Validate docs/SETUP.md contains all placeholders
        setup_doc = kit_dir / "docs" / "SETUP.md"
        doc_errors = check_setup_placeholders(setup_doc, kit_placeholders)
        total_errors.extend(doc_errors)

        if not total_errors:
            # Package into dist/kits/<slug>.zip
            zip_dest = DIST_KITS_DIR / f"{slug}.zip"
            try:
                package_kit(kit_dir, zip_dest)
                size_kb = zip_dest.stat().st_size / 1024
                print(f"  ✓ Packaged into {zip_dest.name} ({size_kb:.1f} KB)\n")
                built_kits.append(zip_dest)
            except Exception as e:
                total_errors.append(f"Failed to package {slug}: {e}")

    if total_errors:
        print("\n❌ Build failed with the following errors:", file=sys.stderr)
        for err in total_errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    print(f"🎉 All {len(built_kits)} kits verified and successfully packed into {DIST_KITS_DIR}.")

if __name__ == "__main__":
    main()
