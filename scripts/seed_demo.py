"""Seed demo data: venue, users, modules, quizzes, messages, checklists."""
import asyncio
import sys
import os
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.auth import hash_password
from app.models.user import User, Venue, UserRole
from app.models.onboarding import Module, ModuleStep, ModuleProgress, Quiz, QuizQuestion, QuizOption, QuizAttempt
from app.models.chat import Conversation, ConversationMember, Message, ConversationType
from app.models.checklist import ChecklistTemplate, ChecklistItem, DailyChecklist, ItemCompletion


MODULES_DATA = [
    {
        "title": "Добро пожаловать в команду",
        "description": "Ознакомьтесь с историей ресторана, ценностями и стандартами обслуживания.",
        "steps": [
            {"title": "История ресторана", "content": "Ресторан «Demo» был основан в 2010 году с миссией создавать незабываемые гастрономические впечатления. За 14 лет мы обслужили более 500 000 гостей и получили признание как лучший ресторан города.\n\nНаши ценности:\n• Гостеприимство — каждый гость особенный\n• Качество — только свежие продукты\n• Команда — мы единое целое\n• Развитие — мы всегда учимся"},
            {"title": "Стандарты обслуживания", "content": "Золотые правила сервиса:\n\n1. Встречайте гостя в течение 30 секунд после появления\n2. Улыбайтесь и устанавливайте зрительный контакт\n3. Знайте меню наизусть — состав блюд, аллергены, время приготовления\n4. Проактивно предлагайте помощь\n5. Прощайтесь с каждым гостем"},
            {"title": "Дресс-код и внешний вид", "content": "Форма одежды:\n• Чистая отглаженная форма (выдаётся на складе)\n• Бейдж с именем — обязателен\n• Закрытая обувь тёмного цвета\n• Аккуратная причёска\n• Минимум украшений\n\nПомните: ваш внешний вид — первое впечатление о ресторане."},
        ],
        "quiz": {
            "pass_score": 0.7,
            "questions": [
                {"text": "В каком году основан ресторан?", "options": [("2005", False), ("2010", True), ("2015", False), ("2020", False)]},
                {"text": "Сколько секунд отводится на встречу гостя?", "options": [("10 секунд", False), ("30 секунд", True), ("1 минута", False), ("2 минуты", False)]},
                {"text": "Что обязательно должен носить сотрудник?", "options": [("Галстук", False), ("Бейдж с именем", True), ("Шляпу", False), ("Перчатки", False)]},
            ],
        },
    },
    {
        "title": "Меню и продукты",
        "description": "Изучите состав блюд, аллергены, технику подачи и специальные предложения.",
        "steps": [
            {"title": "Структура меню", "content": "Меню состоит из разделов:\n\n• Закуски и салаты (12 позиций)\n• Супы (5 позиций)\n• Горячие блюда: мясо, рыба, паста (20 позиций)\n• Десерты (8 позиций)\n• Напитки: безалкогольные, алкогольные, горячие (30 позиций)\n\nСезонное меню обновляется ежеквартально. Следите за информационной доской.", "video_url": "https://www.youtube.com/embed/dQw4w9WgXcQ"},
            {"title": "Аллергены", "content": "14 основных аллергенов по EU регламенту:\n\n1. Глютен (пшеница, рожь, ячмень)\n2. Ракообразные\n3. Яйца\n4. Рыба\n5. Арахис\n6. Соя\n7. Молоко\n8. Орехи\n9. Сельдерей\n10. Горчица\n11. Кунжут\n12. Диоксид серы\n13. Люпин\n14. Моллюски\n\nПри вопросах гостя — всегда уточняйте у шеф-повара!"},
            {"title": "Рекомендации и апселлинг", "content": "Техника AIDA в рекомендациях:\n\nA (Attention) — Привлеките внимание: «Сегодня у нас особое блюдо...»\nI (Interest) — Вызовите интерес: «Наш шеф готовит его из...»\nD (Desire) — Создайте желание: «Это блюдо пользуется огромной популярностью»\nA (Action) — Предложите заказать: «Хотели бы попробовать?»\n\nАпселлинг увеличивает средний чек и доход всей команды."},
        ],
        "quiz": {
            "pass_score": 0.7,
            "questions": [
                {"text": "Сколько позиций в разделе горячих блюд?", "options": [("10", False), ("15", False), ("20", True), ("25", False)]},
                {"text": "Что нужно сделать, если гость спрашивает об аллергенах?", "options": [("Ответить по памяти", False), ("Уточнить у шеф-повара", True), ("Дать меню", False), ("Сказать, что не знаете", False)]},
                {"text": "Как расшифровывается AIDA?", "options": [("Attention, Interest, Desire, Action", True), ("Ask, Inform, Deliver, Acknowledge", False), ("Attract, Identify, Demonstrate, Accept", False), ("Answer, Involve, Direct, Approve", False)]},
            ],
        },
    },
    {
        "title": "Работа с кассой и заказами",
        "description": "Система POS, приём заказов, расчёт гостей и работа с возражениями.",
        "steps": [
            {"title": "Система POS", "content": "Порядок работы с кассовой системой:\n\n1. Войдите в систему своим PIN-кодом\n2. Откройте стол (Table → New Order)\n3. Добавляйте позиции из меню\n4. Указывайте модификаторы (без лука, дополнительный соус)\n5. Отправляйте на кухню (Send to Kitchen)\n6. Для расчёта: Payment → выберите способ оплаты\n\nВажно: никогда не оставляйте кассу разблокированной!"},
            {"title": "Приём и ведение заказа", "content": "Этапы работы с заказом:\n\n1. Приём заказа — запишите всё, уточните пожелания\n2. Ввод в систему — не позднее 2 минут\n3. Контроль времени — закуски 10-15 мин, горячее 20-25 мин\n4. Подача — всегда правой рукой справа\n5. Check-back — через 2 минуты после подачи\n6. Расчёт — принесите счёт по просьбе"},
            {"title": "Работа с возражениями", "content": "Если гость недоволен:\n\n1. Выслушайте — не перебивайте\n2. Извинитесь — «Приношу свои извинения»\n3. Признайте проблему — «Я понимаю ваше разочарование»\n4. Предложите решение — замена блюда, скидка\n5. Действуйте быстро\n6. Сообщите менеджеру\n\nПравило: недовольный гость, которому помогли, становится постоянным клиентом."},
        ],
        "quiz": {
            "pass_score": 0.7,
            "questions": [
                {"text": "Как долго можно вводить заказ в систему?", "options": [("5 минут", False), ("2 минуты", True), ("10 минут", False), ("Сразу", False)]},
                {"text": "Как правильно подавать блюда?", "options": [("Левой рукой слева", False), ("Правой рукой справа", True), ("Любой рукой", False), ("Через стол", False)]},
                {"text": "Что делать первым при жалобе гостя?", "options": [("Позвать менеджера", False), ("Выслушать, не перебивая", True), ("Предложить скидку", False), ("Принести новое блюдо", False)]},
            ],
        },
    },
    {
        "title": "Охрана труда и безопасность",
        "description": "Пожарная безопасность, санитарные нормы, правила работы с оборудованием.",
        "steps": [
            {"title": "Санитарные нормы", "content": "Ключевые требования СанПиН:\n\n• Мойте руки каждые 30 минут и после туалета\n• Не работайте при признаках болезни\n• Волосы убраны (сетка или резинка)\n• Ногти коротко острижены, без лака\n• Украшения не допускаются на кухне\n• Спецодежда хранится отдельно от личных вещей\n\nПлановые медосмотры — каждые 6 месяцев."},
            {"title": "Пожарная безопасность", "content": "Действия при пожаре:\n\n1. Нажмите кнопку пожарной сигнализации\n2. Позвоните 101\n3. Спокойно эвакуируйте гостей\n4. Не пользуйтесь лифтом\n5. Точка сбора — парковка перед входом\n6. Проверьте, что все вышли\n\nРасположение огнетушителей: у входа, на кухне (2 шт.), у бара.\nПроверка ежемесячно — первый вторник месяца."},
        ],
        "quiz": {
            "pass_score": 0.7,
            "questions": [
                {"text": "Как часто нужно мыть руки?", "options": [("Раз в час", False), ("Каждые 30 минут", True), ("Раз в смену", False), ("Только перед едой", False)]},
                {"text": "Куда звонить при пожаре?", "options": [("102", False), ("103", False), ("101", True), ("112", False)]},
            ],
        },
    },
    {
        "title": "Командная работа и коммуникация",
        "description": "Эффективное взаимодействие в команде, конфликты, обратная связь.",
        "steps": [
            {"title": "Принципы командной работы", "content": "Эффективная команда строится на:\n\n• Уважении — к коллегам и их труду\n• Коммуникации — говорите открыто\n• Взаимопомощи — поддерживайте друг друга\n• Ответственности — выполняйте обязательства\n• Позитиве — хорошее настроение заразительно\n\nПомните: гость видит, когда в команде разлад. Оставляйте личные конфликты за дверью ресторана."},
            {"title": "Решение конфликтов", "content": "Алгоритм разрешения конфликта в команде:\n\n1. Поговорите наедине — не при гостях и коллегах\n2. Слушайте активно — не перебивайте\n3. Говорите о поведении, не о личности\n4. Ищите компромисс\n5. Если не удаётся — обратитесь к менеджеру\n\nКонфликт при гостях — немедленно к менеджеру."},
            {"title": "Обратная связь", "content": "Как давать обратную связь по модели SBI:\n\nS (Situation) — Опишите ситуацию: «Сегодня в 14:00...»\nB (Behavior) — Опишите поведение: «Ты сделал/не сделал...»\nI (Impact) — Опишите последствия: «Это повлекло за собой...»\n\nКак принимать обратную связь:\n• Не защищайтесь сразу\n• Задавайте уточняющие вопросы\n• Благодарите за честность\n• Делайте выводы"},
        ],
        "quiz": {
            "pass_score": 0.7,
            "questions": [
                {"text": "Что делать при конфликте с коллегой при гостях?", "options": [("Продолжить спор", False), ("Немедленно обратиться к менеджеру", True), ("Замолчать и уйти", False), ("Попросить гостя подождать", False)]},
                {"text": "Как расшифровывается модель SBI?", "options": [("Situation, Behavior, Impact", True), ("Story, Brief, Inform", False), ("Simple, Brief, Important", False), ("Start, Build, Improve", False)]},
                {"text": "Как нужно принимать обратную связь?", "options": [("Сразу защищаться", False), ("Не обращать внимания", False), ("Слушать, задавать вопросы, благодарить", True), ("Давать ответную критику", False)]},
            ],
        },
    },
]

CHAT_MESSAGES = [
    ("manager@demo.com", "Доброе утро, команда! Сегодня ожидаем банкет на 30 человек в 19:00. Просьба всем быть готовы к 18:30."),
    ("staff1@demo.com", "Доброе утро! Поняли, будем готовы."),
    ("staff2@demo.com", "Привет всем! Уже на месте, начинаю подготовку зала."),
    ("manager@demo.com", "Отлично! Не забудьте проверить сервировку по новым стандартам."),
    ("staff1@demo.com", "Кстати, поставка фруктов задерживается — позвонили из «АгроФрутс»."),
    ("manager@demo.com", "Понял, я свяжусь с поставщиком. Спасибо, что сообщил."),
    ("staff2@demo.com", "Зал готов! Столы расставлены, свечи зажжены."),
    ("staff1@demo.com", "Я проверил резервный запас — всё в порядке, на завтра хватит."),
    ("manager@demo.com", "Молодцы! Сегодня был отличный день — выручка выше плана на 15%."),
    ("staff2@demo.com", "Здорово! Работаем дальше в том же духе!"),
]

CHECKLISTS_DATA = [
    {
        "name": "Открытие смены",
        "description": "Ежедневный чек-лист для открытия ресторана",
        "items": [
            "Проверить внешний вид помещения (чистота, освещение, вывеска)",
            "Открыть кассу и провести стартовую инкассацию",
            "Включить оборудование: холодильники, витрины, кофемашина",
            "Проверить наличие товара на баре и в зале",
            "Расставить меню на столах",
            "Проверить чистоту туалетов",
            "Включить фоновую музыку",
            "Провести briefing с командой",
            "Проверить резервации на сегодня",
            "Убедиться в работоспособности POS-системы",
        ],
    },
    {
        "name": "Закрытие смены",
        "description": "Ежедневный чек-лист для закрытия ресторана",
        "items": [
            "Провести Z-отчёт на кассе",
            "Инкассировать выручку",
            "Отключить кофемашину и дать остыть",
            "Укрыть продукты пищевой плёнкой и убрать в холодильник",
            "Протереть все поверхности барной стойки",
            "Вымыть полы в зале",
            "Проверить и закрыть все окна",
            "Сдать ключи охране",
            "Выключить всё освещение",
            "Внести данные в журнал смены",
        ],
    },
    {
        "name": "Уборка зала",
        "description": "Еженедельная генеральная уборка зала",
        "items": [
            "Вымыть окна изнутри",
            "Протереть все светильники",
            "Почистить кондиционеры (фильтры)",
            "Обработать мягкую мебель пятновыводителем",
            "Протереть декоративные элементы",
            "Вымыть плинтусы",
            "Проверить и заменить перегоревшие лампочки",
            "Обработать дверные ручки антисептиком",
        ],
    },
]


async def seed():
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(Venue))
        if existing.scalar_one_or_none():
            print("Database already seeded, skipping.")
            return

        venue = Venue(name="Ресторан Demo", created_at=datetime.utcnow())
        db.add(venue)
        await db.flush()

        colors = ["#C8A84B", "#4B7EC8", "#4BC87E"]
        users_data = [
            ("Алексей Иванов", "manager@demo.com", "demo123", UserRole.manager),
            ("Мария Петрова", "staff1@demo.com", "demo123", UserRole.staff),
            ("Дмитрий Сидоров", "staff2@demo.com", "demo123", UserRole.staff),
        ]
        users = []
        for i, (name, email, pwd, role) in enumerate(users_data):
            u = User(
                name=name, email=email, password_hash=hash_password(pwd),
                role=role, venue_id=venue.id, avatar_color=colors[i],
                created_at=datetime.utcnow(),
            )
            db.add(u)
            users.append(u)
        await db.flush()

        email_to_user = {u.email: u for u in users}

        modules = []
        for order, mdata in enumerate(MODULES_DATA):
            m = Module(
                title=mdata["title"], description=mdata["description"],
                order=order, created_at=datetime.utcnow(),
            )
            db.add(m)
            await db.flush()

            for step_order, sdata in enumerate(mdata["steps"]):
                s = ModuleStep(
                    module_id=m.id, title=sdata["title"], content=sdata["content"],
                    video_url=sdata.get("video_url"), order=step_order,
                )
                db.add(s)

            quiz = Quiz(module_id=m.id, pass_score=mdata["quiz"]["pass_score"])
            db.add(quiz)
            await db.flush()

            for qdata in mdata["quiz"]["questions"]:
                q = QuizQuestion(quiz_id=quiz.id, text=qdata["text"])
                db.add(q)
                await db.flush()
                for opt_text, is_correct in qdata["options"]:
                    db.add(QuizOption(question_id=q.id, text=opt_text, is_correct=is_correct))

            modules.append(m)

        staff_user = email_to_user["staff1@demo.com"]
        if modules:
            prog = ModuleProgress(
                user_id=staff_user.id, module_id=modules[0].id,
                current_step=2, completed=False, started_at=datetime.utcnow(),
            )
            db.add(prog)
            prog2 = ModuleProgress(
                user_id=staff_user.id, module_id=modules[1].id,
                current_step=3, completed=True,
                completed_at=datetime.utcnow() - timedelta(days=2),
                started_at=datetime.utcnow() - timedelta(days=5),
            )
            db.add(prog2)

        general = Conversation(
            type=ConversationType.general, name="Общий чат",
            venue_id=venue.id, created_at=datetime.utcnow(),
        )
        db.add(general)
        await db.flush()

        for u in users:
            db.add(ConversationMember(
                conversation_id=general.id, user_id=u.id, last_read_at=datetime.utcnow(),
            ))

        for i, (email, text) in enumerate(CHAT_MESSAGES):
            sender = email_to_user[email]
            msg = Message(
                conversation_id=general.id, sender_id=sender.id, text=text,
                created_at=datetime.utcnow() - timedelta(hours=len(CHAT_MESSAGES) - i),
            )
            db.add(msg)

        for cldata in CHECKLISTS_DATA:
            tpl = ChecklistTemplate(
                name=cldata["name"], description=cldata["description"],
                venue_id=venue.id, created_at=datetime.utcnow(),
            )
            db.add(tpl)
            await db.flush()
            for item_order, item_text in enumerate(cldata["items"]):
                db.add(ChecklistItem(template_id=tpl.id, text=item_text, order=item_order))

        await db.commit()
        print("Demo data seeded successfully!")
        print("Users:")
        for name, email, pwd, role in users_data:
            print(f"  {role.value}: {email} / {pwd}")


if __name__ == "__main__":
    asyncio.run(seed())
