import json
import os
import re
import sys
import time
from datetime import datetime
from html import escape

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from seleniumbase import SB


# ============================================================
# TELEGRAM
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")


# ============================================================
# ФАЙЛЫ
# ============================================================

CONFIG_FILE = "products.json"
HISTORY_FILE = "prices_history.json"


# ============================================================
# НАСТРОЙКИ
# ============================================================

UC_RECONNECT_DELAY = 2
BLOCK_IMAGES = True
BLOCK_ADS = True


# ============================================================
# ЗАГРУЗКА КОНФИГА
# ============================================================

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ Файл {CONFIG_FILE} не найден")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    if not cfg.get("products"):
        print("❌ В конфиге нет товаров")
        sys.exit(1)

    return cfg


# ============================================================
# HISTORY
# ============================================================

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print(f"⚠️ Ошибка чтения {HISTORY_FILE}: {e}")
        return {}


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(
            history,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_message(text):
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не задан")
        return False

    if not CHAT_ID:
        print("❌ CHAT_ID не задан")
        return False

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )

        print(f"  📡 Telegram HTTP: {r.status_code}")
        print(f"  📡 Telegram response: {r.text}")

        if not r.ok:
            print("  ❌ Telegram HTTP error")
            return False

        data = r.json()

        if not data.get("ok"):
            print(f"  ❌ Telegram API error: {data}")
            return False

        print("  ✅ Telegram: сообщение отправлено")
        return True

    except Exception as e:
        print(f"  ❌ Telegram exception: {type(e).__name__}: {e}")
        return False


# ============================================================
# PRICE UTILS
# ============================================================

def clean_price(raw_text):
    """
    Примеры:

    18 999 ₽       -> 18999.0
    12.990,50 ₽    -> 12990.5
    $1,299.99      -> 1299.99
    """

    if not raw_text:
        return None

    cleaned = re.sub(r"[^\d.,]", "", raw_text)

    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:

        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "")
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")

    elif "," in cleaned:

        parts = cleaned.split(",")

        if len(parts[-1]) <= 2:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")

    elif cleaned.count(".") > 1:

        parts = cleaned.split(".")

        cleaned = (
            "".join(parts[:-1])
            + "."
            + parts[-1]
        )

    try:
        price = float(cleaned)

        if 10 <= price <= 100_000_000:
            return price

        return None

    except ValueError:
        return None


def format_price(price):
    return f"{price:,.0f}".replace(",", " ") + " ₽"


# ============================================================
# GENERIC PARSER
# ============================================================

def parse_price_generic(
    sb,
    url,
    selector,
    wait=15
):

    t0 = time.time()

    print(f"    🌐 Открываем: {url}")

    sb.uc_open_with_reconnect(
        url,
        UC_RECONNECT_DELAY
    )

    t_open = time.time() - t0

    t1 = time.time()

    try:

        WebDriverWait(
            sb.driver,
            wait
        ).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    selector
                )
            )
        )

    except Exception:

        print(
            f"    ⏱️ '{selector}' "
            f"не появился за {wait} сек"
        )

    t_wait = time.time() - t1

    t2 = time.time()

    try:

        elements = sb.find_elements(
            By.CSS_SELECTOR,
            selector
        )

        for el in elements:

            text = el.text.strip()

            price = clean_price(text)

            if price:

                t_find = time.time() - t2

                print(
                    f"    💰 '{text}' -> {price}"
                )

                print(
                    f"    ⏱️ open={t_open:.1f}s "
                    f"wait={t_wait:.1f}s "
                    f"find={t_find:.1f}s "
                    f"total={time.time()-t0:.1f}s"
                )

                return price

    except Exception as e:

        print(f"    ❌ {e}")

    print("    ⚠️ Fallback-поиск...")

    try:

        for el in sb.find_elements(
            By.XPATH,
            "//*[contains(text(), '₽')]"
        ):

            text = el.text.strip()

            if 3 < len(text) < 30:

                price = clean_price(text)

                if price:

                    print(
                        f"    💰 (fallback) "
                        f"'{text}' -> {price}"
                    )

                    return price

    except Exception:

        pass

    return None


# ============================================================
# SITE PARSERS
# ============================================================

def parse_hoff(sb, product):

    return parse_price_generic(
        sb,
        product["url"],
        product.get(
            "selector",
            ".price-actual"
        ),
        wait=product.get(
            "wait",
            10
        ),
    )


def parse_ozon(sb, product):

    return parse_price_generic(
        sb,
        product["url"],
        product.get(
            "selector",
            "[data-widget='webPrice']"
        ),
        wait=product.get(
            "wait",
            25
        ),
    )


def parse_wb(sb, product):

    return parse_price_generic(
        sb,
        product["url"],
        product.get(
            "selector",
            "ins.price__lower-price"
        ),
        wait=product.get(
            "wait",
            20
        ),
    )


def parse_dns(sb, product):

    return parse_price_generic(
        sb,
        product["url"],
        product.get(
            "selector",
            ".product-buy__price"
        ),
        wait=product.get(
            "wait",
            15
        ),
    )


def parse_default(sb, product):

    return parse_price_generic(
        sb,
        product["url"],
        product["selector"],
        wait=product.get(
            "wait",
            15
        ),
    )


PARSERS = {
    "hoff": parse_hoff,
    "ozon": parse_ozon,
    "wb": parse_wb,
    "dns": parse_dns,
    "default": parse_default,
}


# ============================================================
# PRODUCT
# ============================================================

def parse_product(sb, product):

    site = product.get(
        "site",
        "default"
    ).lower()

    parser = PARSERS.get(
        site,
        parse_default
    )

    try:

        return parser(
            sb,
            product
        )

    except Exception as e:

        print(
            f"    ❌ Ошибка парсинга: {e}"
        )

        return None


# ============================================================
# ОДНА ПРОВЕРКА
# ============================================================

def monitor_once():

    cfg = load_config()

    products = cfg["products"]

    history = load_history()

    print(
        f"🚀 Проверка: "
        f"{len(products)} товаров"
    )

    print(
        f"🕐 Время: "
        f"{datetime.now().isoformat()}"
    )

    print(
        f"⚡ UC delay: "
        f"{UC_RECONNECT_DELAY}s"
    )

    with SB(
        uc=True,
        headless2=True,
        locale="ru-RU",
        block_images=BLOCK_IMAGES,
        ad_block_on=BLOCK_ADS,
    ) as sb:

        for product in products:

            name = product.get(
                "name",
                product["url"]
            )

            url = product["url"]

            safe_name = escape(name)

            safe_url = escape(
                url,
                quote=True
            )

            print()
            print(
                f"📦 {name}"
            )

            price = parse_product(
                sb,
                product
            )

            if price is None:

                print(
                    "   ❌ Цена не найдена"
                )

                continue

            old_price = history.get(
                url,
                {}
            ).get(
                "last_price"
            )

            # ------------------------------------------------
            # ПЕРВАЯ ЦЕНА
            # ------------------------------------------------

            if old_price is None:

                print(
                    f"   🆕 Первая цена: "
                    f"{format_price(price)}"
                )

                send_telegram_message(
                    f"🆕 <b>Начало отслеживания</b>\n"
                    f"<b>{safe_name}</b>\n"
                    f"Цена: <b>{format_price(price)}</b>\n"
                    f"<a href='{safe_url}'>"
                    f"Открыть товар"
                    f"</a>"
                )

            # ------------------------------------------------
            # ЦЕНА ИЗМЕНИЛАСЬ
            # ------------------------------------------------

            elif price != old_price:

                diff = price - old_price

                if diff < 0:

                    emoji = "🎉📉"
                    direction = "упала"

                else:

                    emoji = "😢📈"
                    direction = "выросла"

                print(
                    f"   {emoji} "
                    f"{format_price(old_price)} "
                    f"-> "
                    f"{format_price(price)}"
                )

                send_telegram_message(
                    f"{emoji} <b>"
                    f"Цена {direction}!"
                    f"</b>\n"
                    f"<b>{safe_name}</b>\n"
                    f"Было: "
                    f"{format_price(old_price)}\n"
                    f"Стало: "
                    f"<b>{format_price(price)}</b>\n"
                    f"Разница: "
                    f"{format_price(abs(diff))}\n"
                    f"<a href='{safe_url}'>"
                    f"Открыть товар"
                    f"</a>"
                )

            # ------------------------------------------------
            # БЕЗ ИЗМЕНЕНИЙ
            # ------------------------------------------------

            else:

                print(
                    f"   ⏸️ Без изменений: "
                    f"{format_price(price)}"
                    send_telegram_message("Без изменений")
                )

            # ------------------------------------------------
            # HISTORY
            # ------------------------------------------------

            history[url] = {
                "last_price": price,
                "last_checked": datetime.now().isoformat(),
                "name": name,
            }

    save_history(history)

    print()
    print("💾 История сохранена")


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        monitor_once()

        print()
        print("✅ Проверка завершена")

    except KeyboardInterrupt:

        print()
        print("👋 Остановлено")

        sys.exit(0)

    except Exception as e:

        print()
        print(
            f"💥 Критическая ошибка: {e}"
        )

        sys.exit(1)
