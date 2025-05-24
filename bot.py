import os
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, PreCheckoutQueryHandler, filters, CallbackQueryHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
import requests
import sqlite3
from database import init_db, get_user, create_user, update_generations, add_points, log_transaction

load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CLOTHOFF_API_KEY = os.getenv('CLOTHOFF_API_KEY')
CLOTHOFF_API_URL = "https://api.clothoff.net/v1/undress"  # Hypothetical endpoint

async def start(update: Update, context):
    user_id = update.effective_user.id
    args = context.args
    referred_by = int(args[0].split('_')[1]) if args and args[0].startswith('referral_') else None
    create_user(user_id, referred_by)
    await update.message.reply_text(
        "Welcome to ClothOffBot! You have 2 free image generations. Use /generate to process an image, /buy to purchase more points with Telegram Stars, or /referral to share your link and earn points."
    )

async def referral(update: Update, context):
    user_id = update.effective_user.id
    referral_link = f"https://t.me/{context.bot.username}?start=referral_{user_id}"
    await update.message.reply_text(f"Share this referral link to earn 1 point per new user: {referral_link}")

async def balance(update: Update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if user:
        await update.message.reply_text(f"Your balance: {user[1]} points. Generations used: {user[2]}.")
    else:
        await update.message.reply_text("Please use /start to initialize your account.")

async def buy(update: Update, context):
    user_id = update.effective_user.id
    keyboard = [
        [InlineKeyboardButton("Buy 10 points (100 Stars)", callback_data="buy_100")],
        [InlineKeyboardButton("Buy 50 points (400 Stars)", callback_data="buy_400")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a points package:", reply_markup=reply_markup)

async def button_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    stars = int(query.data.split('_')[1])
    points = 10 if stars == 100 else 50
    invoice = await context.bot.send_invoice(
        chat_id=user_id,
        title=f"Purchase {points} Points",
        description=f"Buy {points} points for {stars} Telegram Stars to generate more images.",
        payload=f"points_{points}_{user_id}",
        currency="XTR",
        prices=[{"label": f"{points} Points", "amount": stars}]
    )

async def pre_checkout(update: Update, context):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment(update: Update, context):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    stars_spent = payment.total_amount
    payload = payment.invoice_payload.split('_')
    points = int(payload[1])
    add_points(user_id, points)
    log_transaction(user_id, stars_spent, points)
    await update.message.reply_text(f"Payment successful! You received {points} points.")

async def generate(update: Update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Please use /start to initialize your account.")
        return
    if user[1] < 1:
        await update.message.reply_text("Insufficient points. Use /buy to purchase more or /referral to earn points.")
        return
    await update.message.reply_text("Please send an image to process.")

async def handle_image(update: Update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user or user[1] < 1:
        await update.message.reply_text("Insufficient points. Use /buy to purchase more or /referral to earn points.")
        return
    
    # Get the largest photo
    file = await update.message.photo[-1].get_file()
    file_path = f"input_{user_id}.jpg"
    await file.download_to_drive(file_path)
    
    try:
        with open(file_path, "rb") as image_file:
            response = requests.post(
                CLOTHOFF_API_URL,
                headers={"Authorization": f"Bearer {CLOTHOFF_API_KEY}"},
                files={"image": image_file}
            )
        os.remove(file_path)
        
        if response.status_code == 200:
            result_image_url = response.json().get("image_url")  # Adjust based on actual API response
            update_generations(user_id)
            remaining_points = user[1] - 1
            await update.message.reply_photo(result_image_url, caption=f"Image processed! You have {remaining_points} points left.")
        else:
            await update.message.reply_text("Error processing image. Try again.")
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        await update.message.reply_text(f"Error: {str(e)}")

async def terms(update: Update, context):
    await update.message.reply_text(
        "Terms of Service: Use this bot responsibly. Only upload images with consent. Misuse may result in a ban. Contact /support for issues."
    )

async def support(update: Update, context):
    await update.message.reply_text("Contact @YourSupportHandle for help or to report issues.")

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("terms", terms))
    app.add_handler(CommandHandler("support", support))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    
    print("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()