import logging
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

# Настройка логгирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы состояний
WAITING_FOR_MESSAGE = 1

# ID группы психологов (замените на реальный)
PSYCHOLOGIST_GROUP_ID = -4855005984  # Пример: -1001234567890

# Тексты
START_MESSAGE = (
    "Привет! Это бот для анонимного общения с психологом. "
    "Вы можете отправить свою проблему анонимно, а психолог ответит вам."
)

ABOUT_COMMUNITY = (
    "🔹 *О сообществе*\n\n"
    "Это сообщество создано для того, чтобы помочь людям "
    "в трудных ситуациях. Здесь вы можете получить "
    "анонимную поддержку от профессионального психолога."
)

ABOUT_PSYCHOLOGIST = (
    "👩‍⚕️ *О психологе*\n\n"
    "Наш психолог - квалифицированный специалист с "
    "многолетним опытом работы. Специализация: "
    "тревожные расстройства, депрессия, отношения."
)

WRITE_PROBLEM_TEXT = (
    "✍️ *Написать о проблеме*\n\n"
    "Напишите ваше сообщение или отправьте видео-кружок, "
    "и оно будет анонимно переправлено психологу. "
    "Психолог ответит вам в ближайшее время."
)

# Глобальный словарь для хранения соответствия между сообщениями пользователей и ответами
user_messages = {}  # {message_id_in_group: {"user_id": user_id, "user_message_id": message_id}}

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
        await update.message.reply_text(START_MESSAGE, reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(START_MESSAGE, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "about_community":
        keyboard = [[InlineKeyboardButton("Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(ABOUT_COMMUNITY, reply_markup=reply_markup, parse_mode="Markdown")
    
    elif query.data == "about_psychologist":
        keyboard = [[InlineKeyboardButton("Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(ABOUT_PSYCHOLOGIST, reply_markup=reply_markup, parse_mode="Markdown")
    
    elif query.data == "write_problem":
        keyboard = [[InlineKeyboardButton("Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(WRITE_PROBLEM_TEXT, reply_markup=reply_markup, parse_mode="Markdown")
        return WAITING_FOR_MESSAGE
    
    elif query.data == "check_response":
        user_id = query.from_user.id
        responses = [k for k, v in user_messages.items() if v["user_id"] == user_id and "response" in v]
        
        if not responses:
            await query.edit_message_text("Пока нет ответов от психолога.", reply_markup=None)
            await start(update, context)
        else:
            for message_id in responses:
                response_data = user_messages[message_id]
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Ответ психолога:\n\n{response_data['response']}",
                )
            await start(update, context)
    
    elif query.data == "back_to_main":
        await start(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat_id = update.message.chat_id
    
    if update.message.video_note:  # Видео-кружок
        # Пересылаем видео-кружок в группу психолога
        sent_message = await context.bot.send_video_note(
            chat_id=PSYCHOLOGIST_GROUP_ID,
            video_note=update.message.video_note.file_id,
        )
        
        # Сохраняем информацию о сообщении
        user_messages[sent_message.message_id] = {
            "user_id": user.id,
            "user_message_id": update.message.message_id,
        }
        
        await update.message.reply_text(
            "Ваше видео-сообщение было отправлено психологу. "
            "Ожидайте ответа. Вы можете проверить ответы, нажав кнопку "
            "'Ответ психолога' в главном меню."
        )
    
    elif update.message.text:  # Текстовое сообщение
        # Пересылаем текст в группу психолога
        sent_message = await context.bot.send_message(
            chat_id=PSYCHOLOGIST_GROUP_ID,
            text=f"Анонимное сообщение:\n\n{update.message.text}",
        )
        
        # Сохраняем информацию о сообщении
        user_messages[sent_message.message_id] = {
            "user_id": user.id,
            "user_message_id": update.message.message_id,
        }
        
        await update.message.reply_text(
            "Ваше сообщение было отправлено психологу. "
            "Ожидайте ответа. Вы можете проверить ответы, нажав кнопку "
            "'Ответ психолога' в главном меню."
        )
    
    await start(update, context)
    return ConversationHandler.END

async def handle_psychologist_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.id != PSYCHOLOGIST_GROUP_ID:
        return
    
    # Проверяем, является ли сообщение ответом на другое сообщение
    if not update.message.reply_to_message:
        return
    
    replied_message_id = update.message.reply_to_message.message_id
    
    # Проверяем, есть ли это сообщение в нашем словаре
    if replied_message_id not in user_messages:
        return
    
    user_data = user_messages[replied_message_id]
    user_id = user_data["user_id"]
    
    # Сохраняем ответ
    user_messages[replied_message_id]["response"] = update.message.text
    
    # Отправляем ответ пользователю
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Вы получили ответ от психолога:\n\n{update.message.text}",
        )
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)
    return ConversationHandler.END

def main():
    # Замените 'YOUR_BOT_TOKEN' на токен вашего бота
    application = Application.builder().token("7830341197:AAGo6uWmeg5xumOOLa9CKxzjTLsB06Yb8KU").build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), CallbackQueryHandler(button_handler)],
        states={
            WAITING_FOR_MESSAGE: [MessageHandler(filters.TEXT | filters.VIDEO_NOTE, handle_message)],
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern="back_to_main")],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Chat(PSYCHOLOGIST_GROUP_ID), handle_psychologist_response))
    
    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()


    #https://api.telegram.org/bot7830341197:AAGo6uWmeg5xumOOLa9CKxzjTLsB06Yb8KU/getUpdates