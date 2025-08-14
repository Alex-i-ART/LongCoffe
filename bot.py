import logging
import os
import psycopg2
from psycopg2.extras import DictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from dotenv import load_dotenv
import telegram.error

# Загрузка переменных окружения
load_dotenv()

# Настройка логгирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Константы состояний
WAITING_FOR_MESSAGE = 1

# ID группы психологов
PSYCHOLOGIST_GROUP_ID = -1002773179737

# Текстовые константы
TEXTS = {
    "start": (
        "Привет! Это бот для анонимного общения с психологом. "
        "Вы можете отправить свою проблему анонимно, а психолог ответит вам."
    ),
    "about_community": (
        "🔹 *О сообществе*\n\n"
        "Это сообщество создано для того, чтобы помочь людям "
        "в трудных ситуациях. Здесь вы можете получить "
        "анонимную поддержку от профессионального психолога."
    ),
    "about_psychologist": (
        "👩‍⚕️ *О психологе*\n\n"
        "Наш психолог - квалифицированный специалист с "
        "многолетним опытом работы. Специализация: "
        "тревожные расстройства, депрессия, отношения."
    ),
    "write_problem": (
        "✍️ *Написать о проблеме*\n\n"
        "Напишите ваше сообщение или отправьте видео-кружок, "
        "и оно будет анонимно переправлено психологу. "
        "Психолог ответит вам в ближайшее время."
    ),
    "message_sent": (
        "✅ Ваше сообщение было отправлено психологу. "
        "Ожидайте ответа. Вы можете проверить ответы, нажав кнопку "
        "'Ответ психолога' в главном меню."
    ),
    "no_responses": "Пока нет ответов от психолога.",
    "psychologist_response": "📩 Вы получили ответ от психолога:\n\n{}",
    "psychologist_video_response": "📹 Психолог отправил вам видео-ответ"
}

class Database:
    def __init__(self):
        self.conn = None
        
    def connect(self):
        """Устанавливает соединение с базой данных"""
        try:
            self.conn = psycopg2.connect(os.getenv('DATABASE_URL'))
            logger.info("Успешное подключение к базе данных")
        except Exception as e:
            logger.error(f"Ошибка подключения к базе данных: {e}")
            raise

    def init_db(self):
        """Инициализирует таблицы в базе данных"""
        try:
            with self.conn.cursor() as cur:
                # Таблица пользователей
                cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_answer TEXT
                )
                """)
                
                # Таблица сообщений
                cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    user_id BIGINT REFERENCES users(user_id),
                    user_message_id TEXT,
                    message_type TEXT NOT NULL,
                    text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    answered BOOLEAN DEFAULT FALSE,
                    response TEXT,
                    response_type TEXT
                )
                """)
                
                # Добавляем колонку response_type, если она не существует
                cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 
                        FROM information_schema.columns 
                        WHERE table_name='messages' AND column_name='response_type'
                    ) THEN
                        ALTER TABLE messages ADD COLUMN response_type TEXT;
                    END IF;
                END $$;
                """)
                
                self.conn.commit()
                logger.info("Таблицы успешно инициализированы")
        except Exception as e:
            logger.error(f"Ошибка инициализации базы данных: {e}")
            self.conn.rollback()
            raise

    def save_user(self, user_id):
        """Сохраняет пользователя в базу данных"""
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                    (user_id,)
                )
                self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения пользователя: {e}")
            self.conn.rollback()
            raise

    def save_message(self, message_data):
        """Сохраняет сообщение в базу данных"""
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO messages 
                    (message_id, user_id, user_message_id, message_type, text)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        message_data['message_id'],
                        message_data['user_id'],
                        message_data['user_message_id'],
                        message_data['message_type'],
                        message_data.get('text')
                    )
                )
                self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения сообщения: {e}")
            self.conn.rollback()
            raise

    def get_pending_responses(self, user_id):
        """Получает непрочитанные ответы для пользователя"""
        try:
            with self.conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    """
                    SELECT message_id, response, response_type 
                    FROM messages 
                    WHERE user_id = %s AND (response IS NOT NULL OR response_type = 'video_note') AND answered = FALSE
                    ORDER BY created_at
                    """,
                    (user_id,)
                )
                responses = cur.fetchall()
                
                if responses:
                    # Помечаем ответы как прочитанные
                    message_ids = [r['message_id'] for r in responses]
                    cur.execute(
                        "UPDATE messages SET answered = TRUE WHERE message_id = ANY(%s)",
                        (message_ids,)
                    )
                    self.conn.commit()
                
                return responses
        except Exception as e:
            logger.error(f"Ошибка получения ответов: {e}")
            self.conn.rollback()
            return []

    def save_response(self, message_id, response_text, response_type=None):
        """Сохраняет ответ психолога"""
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE messages 
                    SET response = %s, answered = FALSE, response_type = %s
                    WHERE message_id = %s 
                    RETURNING user_id
                    """,
                    (response_text, response_type, message_id)
                )
                result = cur.fetchone()
                if not result:
                    return None
                
                user_id = result[0]
                cur.execute(
                    "UPDATE users SET last_answer = %s WHERE user_id = %s",
                    (response_text, user_id)
                )
                self.conn.commit()
                return user_id
        except Exception as e:
            logger.error(f"Ошибка сохранения ответа: {e}")
            self.conn.rollback()
            return None

# Инициализация базы данных
db = Database()
db.connect()
db.init_db()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("О сообществе", callback_data="about_community"),
            InlineKeyboardButton("О психологе", callback_data="about_psychologist"),
        ],
        [
            InlineKeyboardButton("Ответ психолога", callback_data="check_response"),
            InlineKeyboardButton("Написать о проблеме", callback_data="write_problem"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(TEXTS["start"], reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(TEXTS["start"], reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "about_community":
        keyboard = [[InlineKeyboardButton("Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(TEXTS["about_community"], reply_markup=reply_markup, parse_mode="Markdown")
    
    elif query.data == "about_psychologist":
        keyboard = [[InlineKeyboardButton("Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(TEXTS["about_psychologist"], reply_markup=reply_markup, parse_mode="Markdown")
    
    elif query.data == "write_problem":
        keyboard = [[InlineKeyboardButton("Отмена", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(TEXTS["write_problem"], reply_markup=reply_markup, parse_mode="Markdown")
        return WAITING_FOR_MESSAGE
    
    elif query.data == "check_response":
        user_id = query.from_user.id
        responses = db.get_pending_responses(user_id)
        
        if not responses:
            await query.edit_message_text(TEXTS["no_responses"])
        else:
            for response in responses:
                if response['response_type'] == 'video_note':
                    await context.bot.send_video_note(
                        chat_id=user_id,
                        video_note=response['response']
                    )
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=TEXTS["psychologist_video_response"]
                    )
                else:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=TEXTS["psychologist_response"].format(response['response']),
                    )
        
        keyboard = [
            [
                InlineKeyboardButton("О сообществе", callback_data="about_community"),
                InlineKeyboardButton("О психологе", callback_data="about_psychologist"),
            ],
            [
                InlineKeyboardButton("Ответ психолога", callback_data="check_response"),
                InlineKeyboardButton("Написать о проблеме", callback_data="write_problem"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Что вас интересует?", reply_markup=reply_markup)
    
    elif query.data == "back_to_main":
        await start(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    
    try:
        if update.message.video_note:
            sent_message = await context.bot.send_video_note(
                chat_id=PSYCHOLOGIST_GROUP_ID,
                video_note=update.message.video_note.file_id,
            )
            message_type = "video_note"
            text = None
        elif update.message.text:
            sent_message = await context.bot.send_message(
                chat_id=PSYCHOLOGIST_GROUP_ID,
                text=f"Анонимное сообщение:\n\n{update.message.text}",
            )
            message_type = "text"
            text = update.message.text
        else:
            await update.message.reply_text("Пожалуйста, отправьте только текст или видео-кружок.")
            return WAITING_FOR_MESSAGE
        
        db.save_user(user.id)
        message_data = {
            'message_id': str(sent_message.message_id),
            'user_id': user.id,
            'user_message_id': str(update.message.message_id),
            'message_type': message_type,
            'text': text
        }
        db.save_message(message_data)
        
        keyboard = [[InlineKeyboardButton("В меню", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(TEXTS["message_sent"], reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")
        await update.message.reply_text("Произошла ошибка при отправке сообщения. Пожалуйста, попробуйте позже.")
        return WAITING_FOR_MESSAGE
    
    return ConversationHandler.END

async def handle_psychologist_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.id != PSYCHOLOGIST_GROUP_ID or not update.message.reply_to_message:
        return
    
    replied_message_id = str(update.message.reply_to_message.message_id)
    
    if update.message.video_note:
        user_id = db.save_response(
            replied_message_id, 
            update.message.video_note.file_id,
            response_type="video_note"
        )
        if user_id:
            try:
                await context.bot.send_video_note(
                    chat_id=user_id,
                    video_note=update.message.video_note.file_id
                )
                await context.bot.send_message(
                    chat_id=user_id,
                    text=TEXTS["psychologist_video_response"]
                )
            except Exception as e:
                logger.error(f"Не удалось отправить видео-ответ пользователю {user_id}: {e}")
    else:
        response_text = update.message.text or update.message.caption or "Психолог отправил медиа-сообщение"
        user_id = db.save_response(replied_message_id, response_text)
        if user_id:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=TEXTS["psychologist_response"].format(response_text),
                )
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)
    return ConversationHandler.END

def main():
    if not os.getenv('TELEGRAM_BOT_TOKEN'):
        logger.error("Не указан токен бота!")
        return
    
    if not os.getenv('DATABASE_URL'):
        logger.error("Не указана строка подключения к БД!")
        return
    
    try:
        application = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()
        
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start), CallbackQueryHandler(button_handler)],
            states={
                WAITING_FOR_MESSAGE: [
                    MessageHandler(filters.TEXT | filters.VIDEO_NOTE, handle_message)
                ],
            },
            fallbacks=[CallbackQueryHandler(cancel, pattern="back_to_main")],
        )
        
        application.add_handler(conv_handler)
        application.add_handler(
            MessageHandler(
                (filters.TEXT | filters.VIDEO_NOTE) & ~filters.COMMAND & filters.Chat(PSYCHOLOGIST_GROUP_ID),
                handle_psychologist_response
            )
        )
        
        if os.getenv('WEBHOOK_URL'):
            PORT = int(os.environ.get('PORT', 5000))
            application.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                webhook_url=os.getenv('WEBHOOK_URL')
            )
        else:
            application.run_polling()
            
    except telegram.error.Conflict as e:
        logger.error(f"Бот уже запущен: {e}")
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")

if __name__ == "__main__":
    main()