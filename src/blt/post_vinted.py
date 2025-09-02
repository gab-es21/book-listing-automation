from pathlib import Path
from time import sleep
from typing import Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from .config import settings

def _driver(headless: bool = False):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

def login_vinted(driver):
    driver.get("https://www.vinted.pt/")
    # aceitar cookies se aparecer
    try:
        btn = driver.find_element(By.CSS_SELECTOR, 'button[data-testid="onetrust-accept-btn-handler"]')
        btn.click()
        sleep(1)
    except Exception: pass

    driver.find_element(By.CSS_SELECTOR, 'a[data-testid="header--login-button"]').click()
    sleep(1)
    email = driver.find_element(By.NAME, "email")
    pw = driver.find_element(By.NAME, "password")
    email.send_keys(settings.VINTED_EMAIL)
    pw.send_keys(settings.VINTED_PASSWORD)
    driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
    sleep(3)

def create_listing(driver, folder: Path, title: str, description: str, price: float) -> Optional[str]:
    driver.get("https://www.vinted.pt/items/new")
    sleep(3)
    # upload fotos
    imgs = sorted(folder.glob("*.*"))
    for p in imgs:
        try:
            file_input = driver.find_element(By.CSS_SELECTOR, 'input[type="file"]')
            file_input.send_keys(str(p.resolve()))
            sleep(1)
        except Exception: pass

    # título e descrição
    driver.find_element(By.NAME, "title").send_keys(title)
    driver.find_element(By.NAME, "description").send_keys(description)

    # categoria (Livros)
    try:
        driver.find_element(By.XPATH, "//button[contains(., 'Escolher categoria')]").click()
        sleep(1)
        driver.find_element(By.XPATH, "//span[contains(., 'Livros')]").click()
        sleep(1)
    except Exception: pass

    # preço
    price_input = driver.find_element(By.NAME, "price")
    price_input.clear()
    price_input.send_keys(str(int(price)))

    # publicar
    publish_btn = driver.find_element(By.XPATH, "//button[contains(., 'Publicar')]")
    publish_btn.click()
    sleep(4)

    # obter URL final
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
