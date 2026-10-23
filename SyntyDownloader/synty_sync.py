#!/usr/bin/env python3
"""Synchronisation non destructive de la bibliothèque Synty Store (Sky Pilot).

Dépendances : pip install -r synty_requirements.txt
Puis       : python -m playwright install chromium
Exemple    : python synty_sync.py --config config.yaml

IMPORTANT : Synty utilise désormais essentiellement une connexion par code e-mail.
Le compte, le mot de passe facultatif et le répertoire de sortie sont définis
dans config.yaml, à conserver en local (non suivi par Git). Aucun contournement de CAPTCHA / MFA n'est effectué.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass

import yaml
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


# -----------------------------------------------------------------------------
# Configuration : config.yaml (privé, relatif au dossier de ce script)
# -----------------------------------------------------------------------------
BASE_URL = "https://syntystore.com"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


@dataclass(frozen=True)
class SyncConfig:
    output_dir: Path
    email: str
    password: str
    customer_id: str

    @property
    def library_url(self) -> str:
        return (
            f"{BASE_URL}/apps/downloads/orders/{self.customer_id}"
            f"?logged_in_customer_id={self.customer_id}&line_items_page=1"
        )


def load_config(config_path: Path) -> SyncConfig:
    """Load YAML, resolving its output directory relative to the YAML file.

    No credentials are logged; config.yaml should be excluded from Git.
    """
    path = config_path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(
            f"Configuration introuvable : {path}. "
            "Copiez config.example.yaml vers config.yaml et remplissez-le."
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML invalide dans {path} : {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Configuration invalide : {path} doit contenir un objet YAML.")
    login = raw.get("login")
    if not isinstance(login, dict):
        raise ValueError("config.yaml : bloc 'login' obligatoire (email, password, customer_id).")

    output = raw.get("output_dir")
    if not isinstance(output, str) or not output.strip():
        raise ValueError("config.yaml : 'output_dir' doit être un chemin non vide.")
    output_path = Path(output.strip()).expanduser()
    if not output_path.is_absolute():
        output_path = path.parent / output_path
    output_path = output_path.resolve()

    email = login.get("email")
    if not isinstance(email, str) or not email.strip():
        raise ValueError("config.yaml : 'login.email' est obligatoire.")
    password = login.get("password", "")
    if password is None:
        password = ""
    if not isinstance(password, str):
        raise ValueError("config.yaml : 'login.password' doit être une chaîne.")
    customer_id = login.get("customer_id")
    if not isinstance(customer_id, (str, int)) or not str(customer_id).isdigit():
        raise ValueError("config.yaml : 'login.customer_id' doit être un identifiant numérique.")

    return SyncConfig(output_path, email.strip(), password, str(customer_id))


LOGGER = logging.getLogger("synty_sync")
INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class Package:
    name: str
    url: str
    order_item_id: str


@dataclass(frozen=True)
class FileLink:
    url: str
    label: str
    button_index: int


def safe_component(value: str, fallback: str = "unnamed", max_chars: int = 110) -> str:
    """Nom de dossier/fichier valide Windows/Linux, sans traversée de chemins."""
    value = unicodedata.normalize("NFC", value)
    value = INVALID_WINDOWS_CHARS.sub("_", value)
    value = re.sub(r"\s+", " ", value).strip().strip(". ")
    value = value[:max_chars].rstrip(". ") or fallback
    if value.split(".", 1)[0].upper() in RESERVED_WINDOWS_NAMES:
        value = "_" + value
    return value


def safe_filename(raw: str, fallback_id: str) -> str:
    # Ne conserver que le nom : ne jamais interpréter un chemin venant du serveur.
    raw = raw.replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(raw).suffix
    if len(suffix) > 20:
        suffix = ""
    stem = raw[: -len(suffix)] if suffix else raw
    stem = safe_component(stem, fallback=f"file_{fallback_id}", max_chars=105)
    suffix = "." + safe_component(suffix[1:], fallback="bin", max_chars=19) if suffix else ""
    return stem + suffix


def allowed_url(url: str, expected_path_prefix: str) -> bool:
    parts = urlparse(url)
    return (
        parts.scheme == "https"
        and parts.hostname == "syntystore.com"
        and parts.path.startswith(expected_path_prefix)
    )


def parse_library(html: str, page_url: str) -> tuple[list[Package], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    wrapper = soup.select_one(".sky-pilot-files-list")
    if wrapper is None:
        raise ValueError("Liste .sky-pilot-files-list introuvable (connexion expirée ?)")

    packages: list[Package] = []
    for anchor in wrapper.select("a.sky-pilot-list-item[href]"):
        url = urljoin(page_url, anchor["href"])
        if not allowed_url(url, "/apps/downloads/customers/"):
            continue
        title_element = anchor.select_one(".sky-pilot-file-heading")
        title = (title_element or anchor).get_text(" ", strip=True)
        match = re.search(r"/order_items/(\d+)", urlparse(url).path)
        order_item_id = match.group(1) if match else hashlib.sha256(url.encode()).hexdigest()[:12]
        packages.append(Package(title or f"Package_{order_item_id}", url, order_item_id))

    next_url: str | None = None
    next_anchor = soup.select_one(".sky-pilot-pagination .next a[href]")
    if next_anchor:
        candidate = urljoin(page_url, next_anchor["href"])
        if (
            allowed_url(candidate, urlparse(page_url).path)
            and "line_items_page" in parse_qs(urlparse(candidate).query)
        ):
            next_url = candidate
    return packages, next_url


def parse_file_links(html: str, page_url: str) -> list[FileLink]:
    soup = BeautifulSoup(html, "html.parser")
    result: list[FileLink] = []
    for index, a in enumerate(soup.select("a.button.sky-pilot-button")):
        href = a.get("href")
        if not href:
            continue
        url = urljoin(page_url, href)
        if allowed_url(url, "/apps/downloads/downloads/"):
            result.append(FileLink(url, a.get_text(" ", strip=True) or "Download", index))
    return result


def link_key(package: Package, download_url: str) -> str:
    # Le même lien peut éventuellement apparaître sous deux packages distincts.
    identity = f"{package.order_item_id}|{download_url}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def download_id(download_url: str) -> str:
    m = re.search(r"/downloads/(\d+)", urlparse(download_url).path)
    return m.group(1) if m else hashlib.sha256(download_url.encode()).hexdigest()[:10]


def load_history(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "downloads": {}}
    # En cas de JSON corrompu, arrêter plutôt que perdre l'historique.
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("downloads"), dict):
        raise ValueError(f"Format d'historique incorrect : {path}")
    return data


def save_history(path: Path, data: dict) -> None:
    # Écriture atomique : interruption => historique précédent conservé.
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def history_path_exists(root: Path, entry: dict) -> bool:
    relative = entry.get("relative_path")
    if not isinstance(relative, str) or not relative:
        return False
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        return False
    return path.is_file() and path.stat().st_size > 0


def locate_input(context: BrowserContext, selector: str):
    """Localiser les inputs, y compris dans popup/iframe d'authentification."""
    for page in reversed(context.pages):
        for frame in reversed(page.frames):
            try:
                locator = frame.locator(selector).first
                if locator.count() and locator.is_visible():
                    return locator
            except Exception:
                pass
    return None


def submit_login_if_possible(context: BrowserContext, config: SyncConfig) -> None:
    email = locate_input(
        context,
        'input[type="email"], input[autocomplete="email"], '
        'input[name="customer[email]"], input[name="email"]',
    )
    if email is not None:
        LOGGER.info("Saisie automatique de l'identifiant.")
        email.fill(config.email)
        password = locate_input(context, 'input[type="password"]')
        if password is not None:
            password.fill(config.password)
            password.press("Enter")
        else:
            email.press("Enter")
        time.sleep(2)

    # Certains anciens formulaires affichent le mot de passe après l'e-mail.
    password = locate_input(context, 'input[type="password"]')
    if password is not None:
        password.fill(config.password)
        password.press("Enter")
        time.sleep(1)


def submit_email_code(context: BrowserContext, code: str) -> bool:
    """Essayer de saisir le code ; retour False si l'UI n'est pas reconnue."""
    if not re.fullmatch(r"\d{4,10}", code):
        LOGGER.warning("Code attendu : 4 à 10 chiffres.")
        return False

    # Composant classique : une seule zone OTP.
    one = locate_input(
        context,
        'input[autocomplete="one-time-code"], '
        'input[name="code"], input[name="otp"], '
        'input[name="verification_code"], input[id*="verification-code"], '
        'input[inputmode="numeric"]:not([maxlength="1"])',
    )
    if one is not None:
        one.fill(code)
        one.press("Enter")
        return True

    # Composant à cases distinctes, chacune recevant un chiffre.
    for page in reversed(context.pages):
        for frame in reversed(page.frames):
            candidates = frame.locator(
                'input[maxlength="1"][inputmode="numeric"], '
                'input[maxlength="1"][type="text"]'
            )
            if candidates.count() == len(code):
                for index, digit in enumerate(code):
                    candidates.nth(index).fill(digit)
                candidates.last.press("Enter")
                return True
    return False


def library_visible(page: Page) -> bool:
    try:
        return page.locator(".sky-pilot-files-list").first.is_visible(timeout=4_000)
    except Exception:
        return False


def ensure_authenticated(context: BrowserContext, page: Page, headless: bool, config: SyncConfig) -> None:
    page.goto(config.library_url, wait_until="domcontentloaded", timeout=60_000)
    if library_visible(page):
        return
    if headless:
        raise RuntimeError("Session expirée : relancer sans --headless pour le code e-mail.")

    LOGGER.info("Aucune bibliothèque visible. Ouverture du formulaire de connexion.")
    page.goto(urljoin(BASE_URL, "/account/login"), wait_until="domcontentloaded", timeout=60_000)
    submit_login_if_possible(context, config)

    print("\nLa connexion Synty/Shopify est ouverte dans Chromium.")
    print("Vérifiez l'e-mail reçu. Si nécessaire, terminez manuellement l'étape de connexion.")
    code = input("Code reçu par e-mail (ou Entrée pour le saisir dans le navigateur) : ").strip()
    if code:
        if not submit_email_code(context, code):
            print("Saisie automatique non reconnue : entrez le code dans Chromium.")
        else:
            time.sleep(2)

    input("Quand la connexion est terminée dans Chromium, appuyez sur Entrée ici... ")
    page.goto(config.library_url, wait_until="domcontentloaded", timeout=60_000)
    if not library_visible(page):
        raise RuntimeError(
            "Impossible d'accéder à la bibliothèque. "
            "Vérifiez la connexion et l'identifiant CUSTOMER_ID."
        )
    LOGGER.info("Connexion confirmée. Le profil Chromium sera réutilisé.")


def gather_packages(page: Page, max_pages: int, library_url: str) -> list[Package]:
    url = library_url
    visited_pages: set[str] = set()
    unique: dict[str, Package] = {}

    for page_number in range(1, max_pages + 1):
        if url in visited_pages:
            raise RuntimeError(f"Pagination circulaire détectée à la page {page_number}.")
        visited_pages.add(url)

        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.locator(".sky-pilot-files-list").first.wait_for(timeout=30_000)
        found, next_url = parse_library(page.content(), page.url)
        LOGGER.info("Bibliothèque page %d : %d packages", page_number, len(found))
        for package in found:
            unique[package.url.split("?", 1)[0]] = package
        if not next_url:
            LOGGER.info("Fin de pagination : %d packages uniques.", len(unique))
            return list(unique.values())
        url = next_url

    raise RuntimeError(
        f"Plus de {max_pages} pages détectées. "
        "Augmenter --max-pages (aucune page n'est volontairement ignorée)."
    )


def assign_folders(packages: list[Package]) -> dict[str, str]:
    """Éviter les collisions de noms invalides/identiques sous Windows."""
    dirs: dict[str, str] = {}
    already: dict[str, str] = {}
    for package in packages:
        suggested = safe_component(package.name, f"Package_{package.order_item_id}", max_chars=85)
        folder = suggested
        if folder.casefold() in already and already[folder.casefold()] != package.name:
            folder = safe_component(f"{suggested}__{package.order_item_id}", max_chars=105)
        already[folder.casefold()] = package.name
        dirs[package.url] = folder
    return dirs


def get_destination(root: Path, package_dir: Path, filename: str, key: str,
                    dl_id: str, history: dict) -> tuple[Path, bool]:
    """Trouver destination. bool => fichier manuel pré-existant à réutiliser."""
    initial = package_dir / filename
    if not initial.exists():
        return initial, False

    # Même nom, lien différent déjà archivé : conserver les deux versions.
    rel = initial.relative_to(root).as_posix()
    other_owner = any(
        item_key != key and entry.get("relative_path") == rel
        for item_key, entry in history["downloads"].items()
    )
    if other_owner or initial.stat().st_size == 0:
        p = Path(filename)
        alternative = package_dir / f"{p.stem}__{dl_id}{p.suffix}"
        counter = 2
        while alternative.exists():
            alternative = package_dir / f"{p.stem}__{dl_id}_{counter}{p.suffix}"
            counter += 1
        return alternative, False

    # Fichier présent sans historique : on le conserve et on évite de le dupliquer.
    return initial, True


def is_html_error_file(path: Path) -> bool:
    with path.open("rb") as stream:
        beginning = stream.read(300).lstrip().lower()
    return beginning.startswith((b"<!doctype html", b"<html", b"<head", b"<body"))


def same_content(first: Path, second: Path) -> bool:
    """Comparer sans charger les archives volumineuses en mémoire."""
    if first.stat().st_size != second.stat().st_size:
        return False
    with first.open("rb") as a, second.open("rb") as b:
        while True:
            block_a = a.read(4 * 1024 * 1024)
            block_b = b.read(4 * 1024 * 1024)
            if block_a != block_b:
                return False
            if not block_a:
                return True


def versioned_destination(folder: Path, filename: str, dl_id: str) -> Path:
    name = Path(filename)
    candidate = folder / f"{name.stem}__{dl_id}{name.suffix}"
    number = 2
    while candidate.exists():
        candidate = folder / f"{name.stem}__{dl_id}_{number}{name.suffix}"
        number += 1
    return candidate


def synchronize_package(page: Page, package: Package, folder_name: str, root: Path,
                        history: dict, dry_run: bool, delay: float,
                        stats: dict[str, int]) -> None:
    page.goto(package.url, wait_until="domcontentloaded", timeout=60_000)
    # La page "package" n'était pas fournie : on s'appuie sur le sélecteur
    # confirmé par l'utilisateur, et on signale explicitement son absence.
    try:
        page.locator("a.button.sky-pilot-button").first.wait_for(timeout=20_000)
    except PlaywrightTimeoutError:
        LOGGER.warning("Aucun bouton de téléchargement : %s", package.name)
        stats["empty"] += 1
        return

    links = parse_file_links(page.content(), page.url)
    LOGGER.info("Package '%s' : %d liens", package.name, len(links))
    if not links:
        stats["empty"] += 1
        return

    package_dir = root / folder_name
    for index, link in enumerate(links, start=1):
        key = link_key(package, link.url)
        old_entry = history["downloads"].get(key)
        if old_entry and history_path_exists(root, old_entry):
            LOGGER.info("  [%d/%d] Déjà présent : %s", index, len(links), link.label)
            stats["skipped"] += 1
            continue

        if dry_run:
            LOGGER.info("  [%d/%d] [DRY RUN] %s", index, len(links), link.label)
            stats["planned"] += 1
            continue

        package_dir.mkdir(parents=True, exist_ok=True)
        try:
            # Un téléchargement peut changer l'URL de la page ; la recharger.
            if page.url.split("?", 1)[0] != package.url.split("?", 1)[0]:
                page.goto(package.url, wait_until="domcontentloaded", timeout=60_000)
            # Il faut écouter AVANT le clic (Playwright).
            with page.expect_download(timeout=90_000) as event:
                page.locator("a.button.sky-pilot-button").nth(link.button_index).click(
                    timeout=30_000
                )
            downloaded = event.value
            failure = downloaded.failure()
            if failure:
                raise RuntimeError(f"Échec navigateur : {failure}")

            real_filename = safe_filename(downloaded.suggested_filename, download_id(link.url))
            candidate = package_dir / real_filename
            # Le navigateur a déjà téléchargé le fichier. Si un fichier du même
            # nom existe sans historique, vérifier qu'il est vraiment identique.
            # Cela évite d'ignorer par erreur une nouvelle version différente.
            browser_file = downloaded.path()
            if browser_file.stat().st_size == 0 or is_html_error_file(browser_file):
                raise RuntimeError(f"Contenu vide ou HTML au lieu d'un fichier : {link.label}")
            same_existing = candidate.is_file() and same_content(candidate, browser_file)
            if same_existing:
                destination = candidate
                LOGGER.info("  [%d/%d] Fichier identique conservé : %s", index, len(links), destination.name)
                stats["skipped"] += 1
                status = "already_present"
            else:
                destination, _ = get_destination(
                    root, package_dir, real_filename, key, download_id(link.url), history
                )
                if destination.exists():
                    destination = versioned_destination(package_dir, real_filename, download_id(link.url))
                # Sauvegarde vers fichier temporaire PUIS déplacement (pas de fichier final incomplet).
                temp_dir = root / ".synty-partials"
                temp_dir.mkdir(exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    prefix="synty_", suffix=".part", dir=temp_dir, delete=False
                ) as temp:
                    temp_path = Path(temp.name)
                downloaded.save_as(temp_path)
                if temp_path.stat().st_size == 0 or is_html_error_file(temp_path):
                    raise RuntimeError(f"Contenu vide ou HTML au lieu d'un fichier : {link.label}")
                if destination.exists():
                    raise RuntimeError(f"Destination apparue pendant le transfert : {destination}")
                temp_path.rename(destination)
                LOGGER.info("  [%d/%d] Téléchargé : %s (%s octets)",
                            index, len(links), destination.name, destination.stat().st_size)
                stats["downloaded"] += 1
                status = "downloaded"

            history["downloads"][key] = {
                "url": link.url,
                "package": package.name,
                "order_item_id": package.order_item_id,
                "label": link.label,
                "relative_path": destination.relative_to(root).as_posix(),
                "size": destination.stat().st_size,
                "status": status,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            save_history(root / ".synty_history.json", history)
        except (Exception, KeyboardInterrupt) as error:
            if isinstance(error, KeyboardInterrupt):
                LOGGER.warning("Interruption clavier : historique déjà sauvé jusque-là.")
                raise
            LOGGER.error("  [%d/%d] Échec '%s' : %s", index, len(links), link.label, error)
            stats["failed"] += 1
        finally:
            if delay:
                time.sleep(delay)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchroniser les packages Synty Store")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH,
                        help="Fichier YAML (défaut : config.yaml à côté du script)")
    parser.add_argument("--output", type=Path,
                        help="Override manuel facultatif de output_dir (compatibilité CLI)")
    parser.add_argument("--check-config", action="store_true",
                        help="Valider le YAML et afficher le répertoire sans lancer Chromium")
    parser.add_argument("--headless", action="store_true",
                        help="Sans navigateur visible (nécessite une session valide)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Lister sans télécharger ni compléter l'historique")
    parser.add_argument("--max-pages", type=int, default=500,
                        help="Protection contre une pagination infinie (défaut : 500)")
    parser.add_argument("--limit-packages", type=int, default=0,
                        help="Tester sur les N premiers packages (0=tous)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Délai entre téléchargements en secondes (défaut : 1)")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.max_pages < 1 or args.limit_packages < 0 or args.delay < 0:
        raise ValueError("Les options numériques doivent être positives.")
    config = load_config(args.config)
    root: Path = args.output.expanduser().resolve() if args.output else config.output_dir
    if args.check_config:
        # Do not print credentials or create directories when validating.
        print(f"Configuration valide : {args.config.expanduser().resolve()}")
        print(f"Bibliothèque : {root}")
        print("Compte : configuré (identifiants masqués)")
        return 0
    root.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(root / ".synty_sync.log", encoding="utf-8")],
    )
    history = load_history(root / ".synty_history.json")
    stats = {"downloaded": 0, "skipped": 0, "failed": 0, "empty": 0, "planned": 0}

    # Le profil Chromium contient les cookies de session et doit rester privé.
    profile = root / ".synty_browser_profile"
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=args.headless,
            accept_downloads=True,
            viewport={"width": 1350, "height": 900},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            ensure_authenticated(context, page, args.headless, config)
            packages = gather_packages(page, args.max_pages, config.library_url)
            folders = assign_folders(packages)
            if args.limit_packages:
                packages = packages[:args.limit_packages]
                LOGGER.info("Mode test : %d premiers packages seulement", len(packages))

            LOGGER.info("%d packages à synchroniser -> %s", len(packages), root)
            for index, package in enumerate(packages, start=1):
                LOGGER.info("=== Package %d/%d : %s ===", index, len(packages), package.name)
                try:
                    synchronize_package(
                        page, package, folders[package.url], root, history,
                        args.dry_run, args.delay, stats,
                    )
                except (Exception, KeyboardInterrupt) as error:
                    if isinstance(error, KeyboardInterrupt):
                        raise
                    LOGGER.error("Erreur package '%s' : %s", package.name, error)
                    stats["failed"] += 1
        finally:
            context.close()

    LOGGER.info("Bilan : %s", stats)
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterruption : fichiers enregistrés et historique conservés.")
        sys.exit(130)
    except Exception as exc:
        print(f"Erreur fatale : {exc}", file=sys.stderr)
        sys.exit(1)
