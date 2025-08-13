import logging
import json
import os
import httpx
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
from telegram.request import HTTPXRequest

# Настройка логгирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы состояний
WAITING_FOR_MESSAGE = 1

# ID группы психологов
PSYCHOLOGIST_GROUP_ID = -4855005984

# Пути к файлам данных
USER_MESSAGES_FILE = "user_messages.json"
USER_DATA_FILE = "user_data.json"

# Загрузка токена бота
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '7830341197:AAGo6uWmeg5xumOOLa9CKxzjTLsB06Yb8KU')

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
        "Ваше сообщение было отправлено психологу. "
        "Ожидайте ответа. Вы можете проверить ответы, нажав кнопку "
        "'Ответ психолога' в главном меню."
    ),
    "no_responses": "Пока нет ответов от психолога.",
    "psychologist_response": "Вы получили ответ от психолога:\n\n{}"
}

# Загрузка и сохранение данных
def load_data(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data, filename):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Инициализация данных
user_messages = load_data(USER_MESSAGES_FILE)
user_data = load_data(USER_DATA_FILE)

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
        keyboard = [[InlineKeyboardButton("Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(TEXTS["write_problem"], reply_markup=reply_markup, parse_mode="Markdown")
        return WAITING_FOR_MESSAGE
    
    elif query.data == "check_response":
        user_id = query.from_user.id
        responses = [k for k, v in user_messages.items() if str(v.get("user_id")) == str(user_id) and "response" in v]
        
        if not responses:
            await query.edit_message_text(TEXTS["no_responses"], reply_markup=None)
            await start(update, context)
        else:
            for message_id in responses:
                response_data = user_messages[message_id]
                await context.bot.send_message(
                    chat_id=user_id,
                    text=TEXTS["psychologist_response"].format(response_data['response']),
                )
                # Помечаем ответ как прочитанный
                user_messages[message_id]["answered"] = True
                save_data(user_messages, USER_MESSAGES_FILE)
            await start(update, context)
    
    elif query.data == "back_to_main":
        await start(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat_id = update.message.chat_id
    
    try:
        if update.message.video_note:
            sent_message = await context.bot.send_video_note(
                chat_id=PSYCHOLOGIST_GROUP_ID,
                video_note=update.message.video_note.file_id,
            )
            message_type = "video_note"
        elif update.message.text:
            sent_message = await context.bot.send_message(
                chat_id=PSYCHOLOGIST_GROUP_ID,
                text=f"Анонимное сообщение:\n\n{update.message.text}",
            )
            message_type = "text"
        else:
            await update.message.reply_text("Пожалуйста, отправьте только текст или видео-кружок.")
            return WAITING_FOR_MESSAGE
        
        # Сохраняем информацию о сообщении
        user_messages[str(sent_message.message_id)] = {
            "user_id": user.id,
            "user_message_id": update.message.message_id,
            "message_type": message_type,
            "answered": False
        }
        save_data(user_messages, USER_MESSAGES_FILE)
        
        # Сохраняем информацию о пользователе
        if str(user.id) not in user_data:
            user_data[str(user.id)] = {"messages": {}, "last_answer": None}
        
        user_data[str(user.id)]["messages"][str(update.message.message_id)] = {
            "text": update.message.text or "video_note",
            "answered": False
        }
        save_data(user_data, USER_DATA_FILE)
        
        await update.message.reply_text(TEXTS["message_sent"])
        
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")
        await update.message.reply_text("Произошла ошибка при отправке сообщения. Пожалуйста, попробуйте позже.")
    
    await start(update, context)
    return ConversationHandler.END

async def handle_psychologist_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.id != PSYCHOLOGIST_GROUP_ID:
        return
    
    if not update.message.reply_to_message:
        return
    
    replied_message_id = str(update.message.reply_to_message.message_id)
    
    if replied_message_id not in user_messages:
        return
    
    user_data = user_messages[replied_message_id]
    user_id = user_data["user_id"]
    
    # Получаем текст или подпись медиа-файла
    response_text = update.message.text or update.message.caption or "Психолог отправил медиа-сообщение"
    
    # Обновляем данные
    user_messages[replied_message_id]["response"] = response_text
    user_messages[replied_message_id]["answered"] = True
    save_data(user_messages, USER_MESSAGES_FILE)
    
    # Обновляем user_data
    if str(user_id) in user_data:
        for msg_id, msg_data in user_data[str(user_id)]["messages"].items():
            if msg_data.get("user_message_id") == replied_message_id:
                msg_data["answered"] = True
                user_data[str(user_id)]["last_answer"] = response_text
                break
        save_data(user_data, USER_DATA_FILE)
    
    # Отправляем ответ пользователю
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
    if not BOT_TOKEN:
        logger.error("Не указан токен бота!")
        return
    
    # Создаем Application с кастомным HTTP-клиентом
    application = Application.builder() \
        .token(BOT_TOKEN) \
        .request(HTTPXRequest(http_version="1.1")) \
        .build()
    
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
            filters.TEXT & ~filters.COMMAND & filters.Chat(PSYCHOLOGIST_GROUP_ID),
            handle_psychologist_response
        )
    )
    
    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()