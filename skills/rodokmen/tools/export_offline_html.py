#!/usr/bin/env python3
"""Export webu rodokmenu do prenosného offline balíka (čisté relatívne HTML).

Konvertuje statický build (web/dist) do samostatného priečinka bez nutnosti
spúšťať webový server. Všetky odkazy, obrázky, CSS a skripty sú upravené na
relatívne cesty (napr. osoba/meno/index.html, ../../_astro/...).

Použitie:
    python tools/export_offline_html.py
    python tools/export_offline_html.py [cesta_k_projektu] [--output cielovy_adresar] [--no-zip] [--build]
    npm run export-offline (z priečinka web/)
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def detect_project_root(hint=None):
    """Nájde koreňový priečinok projektu rodokmenu."""
    candidates = []
    if hint:
        candidates.append(os.path.abspath(hint))

    cwd = os.getcwd()
    candidates.append(cwd)
    candidates.append(os.path.dirname(cwd))  # napr. ak sa spúšťa z tools/ alebo web/

    # Ak sa spúšťa z rodokmen-skill
    candidates.append(os.path.abspath(os.path.join(cwd, "..", "Rodokmen")))
    candidates.append(os.path.abspath(os.path.join(cwd, "template")))

    for p in candidates:
        if os.path.exists(os.path.join(p, "web", "dist")):
            return p
        if os.path.exists(os.path.join(p, "data", "osoby.py")) and os.path.exists(os.path.join(p, "web")):
            return p

    # Fallback na cwd
    return cwd


def ensure_build(project_root, force_build=False):
    """Zabezpečí, že web/dist existuje. Ak nie alebo je zadané --build, spustí npm run build."""
    dist_dir = os.path.join(project_root, "web", "dist")
    web_dir = os.path.join(project_root, "web")

    if not os.path.exists(dist_dir) or force_build:
        print(f"Pripravujem build webu v {web_dir}...")
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        # Najprv export dát (npm run data)
        try:
            subprocess.run([npm_cmd, "run", "data"], cwd=web_dir, check=True)
            subprocess.run([npm_cmd, "run", "build"], cwd=web_dir, check=True)
        except Exception as e:
            sys.exit(f"CHYBA: Nepodarilo sa zostaviť web pomocou npm: {e}")

    if not os.path.exists(dist_dir):
        sys.exit(f"CHYBA: Priečinok s buildom neexistuje: {dist_dir}")

    return dist_dir


def rel_url(url, current_dir):
    """Prepočíta koreňovú URL (/nieco/) na relatívnu cestu z daného priečinka."""
    if not url or url.startswith(("http://", "https://", "mailto:", "tel:", "data:", "javascript:")):
        return url
    if url.startswith("#"):
        return url

    path_part, _, hash_part = url.partition("#")
    path_part, _, query_part = path_part.partition("?")

    if not path_part.startswith("/"):
        return url

    path = path_part.lstrip("/")

    # Rozlíšenie: má súbor príponu (obrázok, css, js) alebo ide o stránku/priečinok?
    has_ext = bool(re.search(r"\.[a-zA-Z0-9]{2,5}$", path))
    if not has_ext:
        path = path.strip("/")
        target_file = (path + "/index.html") if path else "index.html"
    else:
        target_file = path

    rel = os.path.relpath(target_file, current_dir).replace("\\", "/")
    if hash_part:
        rel += "#" + hash_part
    if query_part:
        rel += "?" + query_part
    return rel


def patch_family_map_js(out_dir):
    """Upraví vygenerovaný JavaScript mapy, aby rešpektoval data-base pre odkazy na rody."""
    patched = False
    for root, _, files in os.walk(out_dir):
        for f in files:
            if f.startswith("FamilyMap") and f.endswith(".js"):
                js_path = os.path.join(root, f)
                with open(js_path, "r", encoding="utf-8") as jf:
                    js_code = jf.read()

                old_str = 'te=h.slug?`<a href="/rod/${l(h.slug)}/">${l(h.name)}</a>`:l(h.name)'
                new_str = 'te=h.slug?`<a href="${(e.dataset.base||"") + "rod/" + l(h.slug) + "/index.html"}">${l(h.name)}</a>`:l(h.name)'
                if old_str in js_code:
                    js_code = js_code.replace(old_str, new_str)
                    patched = True
                with open(js_path, "w", encoding="utf-8") as jf:
                    jf.write(js_code)
    return patched


def convert_offline(project_root, out_dir=None, make_zip=True, force_build=False):
    """Hlavná konverzná funkcia."""
    dist_dir = ensure_build(project_root, force_build=force_build)

    if not out_dir:
        out_dir = os.path.join(project_root, "vystupy", "rodokmen-web-offline")

    out_dir = os.path.abspath(out_dir)
    print(f"Zdroj (build): {dist_dir}")
    print(f"Cieľ (offline HTML): {out_dir}")

    # Vyčistenie cieľového adresára
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    # 1. Skopírovanie všetkých ne-HTML súborov (obrázky, css, js, pagefind, ...)
    asset_count = 0
    for root, _, files in os.walk(dist_dir):
        rel_root = os.path.relpath(root, dist_dir)
        target_root = os.path.join(out_dir, rel_root) if rel_root != "." else out_dir
        os.makedirs(target_root, exist_ok=True)
        for f in files:
            if not f.endswith(".html"):
                asset_count += 1
                shutil.copy2(os.path.join(root, f), os.path.join(target_root, f))

    print(f"Skopírovaných {asset_count} statických assetov (obrázky, štýly, skripty)...")

    # 2. Patch FamilyMap JS bundle
    patch_family_map_js(out_dir)

    # 3. Spracovanie a úprava HTML súborov
    html_count = 0
    for root, _, files in os.walk(dist_dir):
        rel_dir = os.path.relpath(root, dist_dir)
        if rel_dir == ".":
            rel_dir = ""
        target_root = os.path.join(out_dir, rel_dir) if rel_dir else out_dir
        os.makedirs(target_root, exist_ok=True)

        depth = len(rel_dir.split(os.sep)) if rel_dir else 0
        base_prefix = ("../" * depth) if depth > 0 else ""

        for f in files:
            if not f.endswith(".html"):
                continue

            html_count += 1
            src_path = os.path.join(root, f)
            dst_path = os.path.join(target_root, f)

            with open(src_path, "r", encoding="utf-8") as hf:
                html = hf.read()

            # Zrušenie type="module", aby prehliadače neblokovali lokálny JS kvôli CORS v protokole file://
            html = re.sub(r'<script\s+type="module"\s+src=', "<script defer src=", html)
            html = re.sub(r'<script\s+type="module">', "<script>", html)

            # Konverzia href="..."
            def href_repl(m):
                orig = m.group(1)
                return f'href="{rel_url(orig, rel_dir)}"'

            html = re.sub(r'\bhref="([^"]+)"', href_repl, html)

            # Konverzia src="..."
            def src_repl(m):
                orig = m.group(1)
                return f'src="{rel_url(orig, rel_dir)}"'

            html = re.sub(r'\bsrc="([^"]+)"', src_repl, html)

            # Konverzia meta refresh presmerovaní (content="0;url=/...")
            def refresh_repl(m):
                orig = m.group(1)
                return f'content="0;url={rel_url(orig, rel_dir)}"'

            html = re.sub(r'content="0;url=([^"]+)"', refresh_repl, html)

            # Úprava data-map v komponente mapy
            if 'class="fmap"' in html and 'data-map="' in html:
                # Doplnenie data-base atribútu
                html = re.sub(r'(<div class="fmap"[^>]*?)(data-map=)', rf'\1data-base="{base_prefix}" \2', html)

                def map_url_repl(m):
                    u = m.group(0)
                    return rel_url(u, rel_dir)

                html = re.sub(r"/osoba/[a-zA-Z0-9_\-]+/", map_url_repl, html)
                html = re.sub(r"/rod/[a-zA-Z0-9_\-]+/", map_url_repl, html)

            # Na stránke hľadania pridať upozornenie na CORS obmedzenie file:// protokolu
            if f == "index.html" and rel_dir == "hledat":
                notice = (
                    '<div id="file-proto-notice" style="display:none;background:#fef3c7;border:1px solid #f59e0b;'
                    'color:#92400e;padding:1rem 1.25rem;border-radius:8px;margin-bottom:1.5rem;line-height:1.5;">'
                    '<strong>Upozornenie pre lokálny offline režim:</strong><br>'
                    'Prehliadač pri priamom otvorení súboru z disku (<code>file://</code>) z bezpečnostných dôvodov '
                    'blokuje načítanie indexu (CORS). Vyhľadávať môžete pomocou klávesovej skratky <strong>Ctrl+F</strong> '
                    f'na stránkach <a href="{base_prefix}predci/index.html"><strong>Predci</strong></a>, '
                    f'<a href="{base_prefix}zapisy/index.html"><strong>Zápisy</strong></a> alebo '
                    f'<a href="{base_prefix}rody/index.html"><strong>Rody</strong></a>.'
                    '</div>'
                    '<script>if(window.location.protocol==="file:"){var n=document.getElementById("file-proto-notice");if(n)n.style.display="block";}</script>'
                )
                html = html.replace('<div id="search"></div>', notice + '<div id="search"></div>')

            with open(dst_path, "w", encoding="utf-8") as hf:
                hf.write(html)

    print(f"Úspešne skonvertovaných {html_count} HTML súborov do relatívnej štruktúry.")

    # 4. Voliteľné zabalenie do ZIP
    zip_path = None
    if make_zip:
        vystupy_dir = os.path.dirname(out_dir)
        zip_base_name = os.path.join(vystupy_dir, os.path.basename(out_dir))
        print("Vytváram ZIP archív...")
        zip_file = shutil.make_archive(zip_base_name, "zip", out_dir)
        zip_path = os.path.abspath(zip_file)
        zip_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        print(f"ZIP archív pripravený: {zip_path} ({zip_size_mb:.1f} MB)")

    print("\nHOTOVO! Ako použiť export:")
    print(f"1. Otvorte súbor priamo v prehliadači: {os.path.join(out_dir, 'index.html')}")
    if zip_path:
        print(f"2. Alebo pošlite/zazipujte súbor: {zip_path}")
        print("   Na druhom PC stačí ZIP rozbaliť a dvakrát kliknúť na index.html.")


def main():
    parser = argparse.ArgumentParser(description="Export rodokmenu do offline balíka (relatívne HTML).")
    parser.add_argument("project", nargs="?", default=None, help="Cesta k priečinku projektu (voliteľné)")
    parser.add_argument("--output", "-o", default=None, help="Cieľový priečinok exportu")
    parser.add_argument("--no-zip", action="store_true", help="Nevytvárať ZIP archív")
    parser.add_argument("--build", action="store_true", help="Spustiť pred exportom 'npm run build'")

    args = parser.parse_args()

    project_root = detect_project_root(args.project)
    if not os.path.exists(project_root):
        sys.exit(f"CHYBA: Priečinok projektu neexistuje: {project_root}")

    print(f"Projekt rodokmenu: {project_root}")
    convert_offline(
        project_root=project_root,
        out_dir=args.output,
        make_zip=not args.no_zip,
        force_build=args.build,
    )


if __name__ == "__main__":
    main()
