import json
import os
from sqlite3 import Connection, connect

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common import NoSuchElementException
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import telebot
import time


def foo(course_ids: list[int], db: Connection) -> dict:
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    print("Запускаю браузер")
    driver = webdriver.Chrome(options=options)
    print("Браузер запущен")

    page_sources = {}
    try:
        print("Начинаю парсинг")
        for course_id in course_ids:
            print(f"Парсинг курса {course_id}")
            url = f'{os.environ.get("VSTUP_URL")}/offer/{course_id}/'
            driver.get(url)
            time.sleep(1)

            while True:
                try:
                    button = driver.find_element(By.CSS_SELECTOR, 'button#requests-load')
                    button.click()

                    time.sleep(0.5)
                except NoSuchElementException:
                    break

            page_source = driver.page_source
            page_sources[course_id] = page_source
    finally:
        driver.quit()
    print("Парсинг завершен. Начинаю обработку данных")

    return_arr = {}
    for course_id, page_source in page_sources.items():
        print(f"Обработка данных курса {course_id}")

        soup = BeautifulSoup(page_source, 'html.parser')

        if db.execute(f'SELECT * FROM courses WHERE id = {course_id}').fetchone() is None:
            db.execute(f'INSERT INTO courses (id, last_update) VALUES ({course_id}, "0")')
            db.commit()

        print("Проверяю наличие обновлений")
        last_update = db.execute(f'SELECT last_update FROM courses WHERE id = {course_id}').fetchone()[0]
        footer = soup.select_one('footer')
        page_last_update = footer.find('b').text if footer else '0'
        if last_update == page_last_update:
            print("Курс не обновлен")
            continue
        else:
            print("Курс обновлен")
            db.execute(f'UPDATE courses SET last_update = "{page_last_update}" WHERE id = {course_id}')
            db.commit()

        print("Получаю данные")
        university_tag = soup.select_one('h5.text-primary.text-uppercase')
        university_name = university_tag.text if university_tag else 'Неизвестно'
        faculty_tag = soup.select_one('dl.row.offer-university-facultet-name')
        faculty_name = "🎓 " + faculty_tag.find('dd').text if faculty_tag else 'Неизвестно'
        speciality_tags = soup.select_one('dl.row.offer-university-specialities-name').find_all('span')

        smiles = {
            1: "1️⃣",
            2: "2️⃣",
            3: "3️⃣",
            4: "4️⃣",
            5: "5️⃣",
            6: "6️⃣",
            7: "7️⃣",
            8: "8️⃣",
            9: "9️⃣",
            0: "0️⃣"
        }

        if len(speciality_tags) > 1:
            spec_code = speciality_tags[0].text
            spec_code = ''.join([smiles[int(i)] for i in spec_code])
            speciality_name = spec_code + ' ' + speciality_tags[1].text
        elif len(speciality_tags) == 1:
            spec_code = speciality_tags[0].text
            spec_code = ''.join([smiles[int(i)] for i in spec_code])
            speciality_name = spec_code
        else:
            speciality_name = 'Неизвестно'
        study_prog = soup.select_one('dl.row.offer-study-programs')
        op = study_prog.find('dd').text if study_prog else 'Неизвестно'
        is_magistracy = soup.select('dl.row.offer-master-program-type-name') != []
        if is_magistracy:
            op_type = soup.select_one('dl.row.offer-master-program-type-name').find('dd').text
            op += f' ({op_type})'
        order_license = soup.select_one('dl.row.offer-order-license')
        license_amount = int(order_license.find('dd').text) if order_license else 0
        max_order = soup.select_one('dl.row.offer-max-order')
        budget_amount = int(max_order.find('dd').text) if max_order else 0

        offer_requests_body = soup.select_one('div#offer-requests-body')

        if offer_requests_body:
            div_elements_all = offer_requests_body.select('div.offer-request:not(.request-status-4)')
            div_elements_approved = offer_requests_body.select('div.offer-request.request-status-6')
        else:
            div_elements_all = []
            div_elements_approved = []

        values_approved = []
        values_all = []

        print("Обрабатываю заявки")
        for div in div_elements_all:
            if div.find(class_='indicator-q'):
                continue
            if div.find(class_='offer-request-contract') and budget_amount:
                continue

            found_value = float(div.find(class_='offer-request-kv')
                                .find('div')
                                .text
                                .replace(',', '.'))

            values_all.append(found_value)
            if div in div_elements_approved:
                values_approved.append(found_value)

        print("Сортирую данные")

        values_all.sort(reverse=True)
        values_all = values_all[:budget_amount or license_amount]
        values_approved.sort(reverse=True)
        values_approved = values_approved[:budget_amount or license_amount]

        return_arr[course_id] = {
            'university_name': university_name,
            'faculty_name': faculty_name,
            'speciality_name': speciality_name,
            'op': op,
            'license_amount': license_amount,
            'budget_amount': budget_amount,
            'all_requests': len(div_elements_all),
            'approved_requests': len(div_elements_approved),
            'min_value': values_all[-1] if values_all else 0,
            'min_value_approved': values_approved[-1] if values_approved else 0
        }

    print("Обработка данных завершена")

    return return_arr


def read_config() -> dict:
    with open('config.json', 'r') as f:
        return json.load(f)


def main() -> None:
    load_dotenv()

    TOKEN = os.environ.get('TOKEN')
    bot = telebot.TeleBot(TOKEN)

    config = read_config()
    users = config['users']

    CHAT_IDS = users.keys()
    course_ids = list({course_id for user in users.values() for course_id in user['course_ids']})

    if not os.path.exists(config['db']):
        os.makedirs(config['db'].rsplit('/', 1)[0], exist_ok=True)

    db = connect(config['db'])
    db.execute('''
    CREATE TABLE IF NOT EXISTS courses (
        id INT PRIMARY KEY,
        last_update TEXT
    );
    ''')
    db.commit()

    results = foo(course_ids, db)

    results = dict(sorted(results.items(), key=lambda x: x[1].get('min_value_approved', 0), reverse=True))

    formatted_results = {}
    for idx, (course_id, result) in enumerate(results.items()):
        str_to_print = f"<b>{result['university_name'].upper()}</b>\n" \
                       f"{result['faculty_name']}\n\n" \
                       f"{result['speciality_name']}\n" \
                       f"<i>{result['op']}</i>\n\n" \
                       f"<b>Количество бюджетных мест</b>: {result['budget_amount']}/{result['license_amount']}\n" \
                       f"<b>Одобрено заявок</b>: {result['approved_requests']}/{result['all_requests']}\n" \
                       f"<b>Минимальный балл на {'бюджет' if result['budget_amount'] else 'контракт'}</b>: " \
                       f"{result['min_value_approved']} " \
                       f"({result['min_value']} по всем)"
        formatted_results[course_id] = str_to_print

    sep = "\n\n" + "-" * 50 + "\n\n"

    for chat_id in CHAT_IDS:
        out_arr = [formatted_results[course_id] for course_id in users[str(chat_id)]['course_ids']
                   if course_id in formatted_results]
        if out_arr:
            bot.send_message(chat_id, sep.join(out_arr),
                             parse_mode='HTML')


if __name__ == '__main__':
    main()
