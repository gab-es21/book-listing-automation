from pathlib import Path
from time import sleep
from typing import Optional, List

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from tempfile import TemporaryDirectory

from .config import settings
from .storage import _resize_to_jpeg_bytes  # exporta JPEG otimizado (usa Pillow)
from .heic_convert import convert_folder as convert_heic_folder


IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
MAX_PHOTOS = 10  # limite defensivo

# ------------------------- WebDriver ------------------------- #
def _driver(headless: bool = False):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

def _wait(driver, timeout=20) -> WebDriverWait:
    return WebDriverWait(driver, timeout)

def _click_if_present(driver, by, sel) -> bool:
    try:
        el = _wait(driver, 5).until(EC.element_to_be_clickable((by, sel)))
        el.click()
        return True
    except Exception:
        return False

# ---------------------- Image handling ----------------------- #
def _temp_jpegs_from_folder(folder: Path) -> List[Path]:
    """
    Converte todas as imagens suportadas (inclui .HEIC/.HEIF) para JPEGs temporários,
    redimensionadas e otimizadas para upload. Devolve a lista de Paths temporários.

    Mantém a referência ao TemporaryDirectory anexada à lista para evitar GC precoce.
    """
    paths = sorted([p for p in folder.glob("*") if p.suffix.lower() in IMG_EXTS])[:MAX_PHOTOS]
    if not paths:
        raise FileNotFoundError(f"Sem imagens em {folder} para publicar no Vinted.")

    tmpdir = TemporaryDirectory()
    out_paths: List[Path] = []
    for i, p in enumerate(paths, start=1):
        data = _resize_to_jpeg_bytes(p)  # bytes JPEG (resize + quality)
        tmp = Path(tmpdir.name) / f"{i:02d}.jpg"
        tmp.write_bytes(data)
        out_paths.append(tmp)

    # manter referência viva até fazermos upload (truque simples)
    setattr(out_paths, "_tmpdir", tmpdir)  # type: ignore[attr-defined]
    return out_paths

# ------------------------- Vinted ---------------------------- #
def login_vinted(driver):
    driver.get("https://www.vinted.pt/")
    w = _wait(driver)

    # aceitar cookies (várias possíveis variantes)
    _click_if_present(driver, By.CSS_SELECTOR, 'button[data-testid="onetrust-accept-btn-handler"]')
    _click_if_present(driver, By.ID, "onetrust-accept-btn-handler")
    _click_if_present(driver, By.XPATH, "//button[contains(., 'Aceitar')]")

    # abrir login
    # pode estar em diferentes data-testids/labels, tentamos alguns
    if not _click_if_present(driver, By.CSS_SELECTOR, 'a[data-testid="header--login-button"]'):
        _click_if_present(driver, By.XPATH, "//a[contains(., 'Iniciar sessão') or contains(., 'Entrar')]")

    # form login
    w.until(EC.presence_of_element_located((By.NAME, "email")))
    email = driver.find_element(By.NAME, "email")
    pw = driver.find_element(By.NAME, "password")
    email.clear(); email.send_keys(settings.VINTED_EMAIL or "")
    pw.clear(); pw.send_keys(settings.VINTED_PASSWORD or "")

    # submit
    _click_if_present(driver, By.CSS_SELECTOR, 'button[type="submit"]')
    # aguardar header autenticado (ícone/username) ou redireção
    sleep(2)

def _upload_photos(driver, folder: Path):
    """
    Faz upload de JPEGs temporários para o formulário do Vinted.
    Reprocura o input a cada ficheiro (algumas UIs recriam o input).
    """
    tmp_jpegs = _temp_jpegs_from_folder(folder)
    try:
        for p in tmp_jpegs:
            # alguns formulários recriam o input após cada upload → reprocura sempre
            file_input = None
            selectors = [
                'input[type="file"]',
                'input[data-testid="photos-uploader"]',
            ]
            for sel in selectors:
                try:
                    file_input = _wait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                    if file_input.is_enabled():
                        break
                except Exception:
                    continue
            if not file_input:
                raise RuntimeError("Elemento de upload de fotos não encontrado.")

            file_input.send_keys(str(p.resolve()))
            # dar tempo para processar a miniatura
            sleep(1.2)
    finally:
        # cleanup temporários
        try:
            getattr(tmp_jpegs, "_tmpdir").cleanup()  # type: ignore[attr-defined]
        except Exception:
            pass

def create_listing(driver, folder: Path, title: str, description: str, price: float) -> Optional[str]:
    driver.get("https://www.vinted.pt/items/new")
    w = _wait(driver)

    # ⬇️ Ensure the folder only contains JPEGs (converts HEIC to JPEG, deletes originals)
    try:
        convert_heic_folder(folder, recursive=False, delete_src=True, quality=90)
    except Exception:
        pass

    # aguarda o carregamento da página de criação
    try:
        w.until(EC.presence_of_element_located((By.TAG_NAME, "form")))
    except Exception:
        sleep(2)

    # upload fotos (sempre usando JPEGs temporários)
    _upload_photos(driver, folder)

    # título e descrição
    try:
        w.until(EC.presence_of_element_located((By.NAME, "title"))).send_keys(title[:80])
    except Exception:
        pass
    try:
        w.until(EC.presence_of_element_located((By.NAME, "description"))).send_keys(description)
    except Exception:
        pass

    # categoria (Livros) — tenta uma sequência de rótulos
    opened = (
        _click_if_present(driver, By.XPATH, "//button[contains(., 'Escolher categoria')]")
        or _click_if_present(driver, By.XPATH, "//button[contains(., 'Selecionar categoria')]")
        or _click_if_present(driver, By.XPATH, "//button[contains(., 'Categoria')]")
    )
    if opened:
        sleep(1)
        _click_if_present(driver, By.XPATH, "//*[contains(., 'Livros')]")

    # preço
    try:
        price_input = w.until(EC.presence_of_element_located((By.NAME, "price")))
        price_input.clear()
        price_input.send_keys(str(int(price)))
    except Exception:
        pass

    # publicar
    published = (
        _click_if_present(driver, By.XPATH, "//button[contains(., 'Publicar')]")
        or _click_if_present(driver, By.XPATH, "//button[contains(., 'Listar')]")
        or _click_if_present(driver, By.XPATH, "//button[contains(., 'Colocar à venda')]")
    )
    if not published:
        # como fallback, tenta um submit do form
        try:
            driver.find_element(By.TAG_NAME, "form").submit()
        except Exception:
            pass

    # aguarda possível redireção para o anúncio
    sleep(4)
    try:
        return driver.current_url
    except Exception:
        return None

def post_vinted(folder: Path, meta: dict, headless: bool = False) -> Optional[str]:
    drv = _driver(headless=headless)
    try:
        login_vinted(drv)
        url = create_listing(drv, folder, meta["title"], meta["description"], meta["price"])
        return url
    finally:
        drv.quit()
