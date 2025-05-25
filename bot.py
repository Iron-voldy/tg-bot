import os
import asyncio
import uuid
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, PreCheckoutQueryHandler, filters, CallbackQueryHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
import requests
import sqlite3
from database import init_db, get_user, create_user, update_generations, add_points, log_transaction
import logging
import json
from io import BytesIO
from PIL import Image
import base64

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CLOTHOFF_API_KEY = os.getenv('CLOTHOFF_API_KEY')
CLOTHOFF_API_URL = "https://public-api.clothoff.net/undress"

# Mock mode for testing (set to False to use real API)
MOCK_MODE = False

def mock_api_response():
    """Mock API response for testing purposes"""
    return {
        "success": True,
        "image_url": "https://picsum.photos/512/512",  # Random placeholder image
        "processing_time": 2.5,
        "credits_used": 1
    }

async def start(update: Update, context):
    user_id = update.effective_user.id
    args = context.args
    referred_by = None
    
    if args and args[0].startswith('referral_'):
        try:
            referred_by = int(args[0].split('_')[1])
        except (ValueError, IndexError):
            logger.warning(f"Invalid referral code: {args[0]}")
    
    create_user(user_id, referred_by)
    
    welcome_msg = (
        "🎨 Welcome to ClothOffBot! 🎨\n\n"
        "You have 2 free image generations.\n\n"
        "Commands:\n"
        "• /generate - Process an image\n"
        "• /balance - Check your points\n"
        "• /buy - Purchase more points\n"
        "• /referral - Get your referral link\n"
        "• /terms - Terms of service\n"
        "• /support - Get support\n\n"
        "Send me a photo to get started!"
    )
    
    await update.message.reply_text(welcome_msg)

async def referral(update: Update, context):
    user_id = update.effective_user.id
    bot_username = context.bot.username or "YourBotUsername"
    referral_link = f"https://t.me/{bot_username}?start=referral_{user_id}"
    
    msg = (
        f"🔗 Your Referral Link:\n"
        f"`{referral_link}`\n\n"
        f"Share this link to earn 1 point per new user!\n"
        f"Each referral gives you 1 free generation."
    )
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def balance(update: Update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if user:
        points, generations_used = user[1], user[2]
        msg = (
            f"💰 Your Balance: {points} points\n"
            f"📊 Generations used: {generations_used}\n\n"
            f"{'✅ You can generate images!' if points > 0 else '❌ No points left. Use /buy to purchase more.'}"
        )
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("Please use /start to initialize your account.")

async def buy(update: Update, context):
    keyboard = [
        [InlineKeyboardButton("💎 Buy 10 points (100 Stars)", callback_data="buy_100")],
        [InlineKeyboardButton("💎 Buy 50 points (400 Stars)", callback_data="buy_400")],
        [InlineKeyboardButton("💎 Buy 100 points (750 Stars)", callback_data="buy_750")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = (
        "💳 Purchase Points\n\n"
        "Select a package to buy more generations:\n"
        "• 10 points = 100 Stars\n"
        "• 50 points = 400 Stars (Best Value!)\n"
        "• 100 points = 750 Stars (Premium)"
    )
    
    await update.message.reply_text(msg, reply_markup=reply_markup)

async def button_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    stars = int(query.data.split('_')[1])
    
    # Define points mapping
    points_mapping = {100: 10, 400: 50, 750: 100}
    points = points_mapping.get(stars, 10)
    
    try:
        await context.bot.send_invoice(
            chat_id=user_id,
            title=f"Purchase {points} Points",
            description=f"Buy {points} points for {stars} Telegram Stars to generate more images.",
            payload=f"points_{points}_{user_id}",
            currency="XTR",
            prices=[{"label": f"{points} Points", "amount": stars}]
        )
    except Exception as e:
        logger.error(f"Error sending invoice: {e}")
        await query.edit_message_text("❌ Error creating payment. Please try again later.")

async def pre_checkout(update: Update, context):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment(update: Update, context):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    stars_spent = payment.total_amount
    
    try:
        payload = payment.invoice_payload.split('_')
        points = int(payload[1])
        
        add_points(user_id, points)
        log_transaction(user_id, stars_spent, points)
        
        msg = (
            f"✅ Payment Successful!\n\n"
            f"💎 You received {points} points\n"
            f"⭐ Stars spent: {stars_spent}\n\n"
            f"Use /balance to check your updated balance!"
        )
        
        await update.message.reply_text(msg)
        
    except Exception as e:
        logger.error(f"Error processing payment: {e}")
        await update.message.reply_text("❌ Error processing payment. Contact support.")

async def generate(update: Update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not user:
        await update.message.reply_text("Please use /start to initialize your account.")
        return
        
    if user[1] < 1:
        msg = (
            "❌ Insufficient points!\n\n"
            "Use /buy to purchase more points or\n"
            "/referral to earn points by inviting friends."
        )
        await update.message.reply_text(msg)
        return
        
    await update.message.reply_text(
        "📸 Please send an image to process.\n\n"
        "Make sure the image is clear and well-lit for best results!"
    )

async def handle_image(update: Update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not user or user[1] < 1:
        msg = (
            "❌ Insufficient points!\n\n"
            "Use /buy to purchase more points or\n"
            "/referral to earn points by inviting friends."
        )
        await update.message.reply_text(msg)
        return
    
    # Send processing message
    processing_msg = await update.message.reply_text("🔄 Processing your image... Please wait.")
    
    file_path = None
    try:
        # Get the largest photo
        file = await update.message.photo[-1].get_file()
        file_path = f"input_{user_id}.jpg"
        
        # Download the file
        await file.download_to_drive(file_path)
        logger.info(f"Downloaded image for user {user_id}")
        
        # Process the image
        if MOCK_MODE:
            # Mock processing delay
            await asyncio.sleep(2)
            result = mock_api_response()
            success = True
            result_image_url = result["image_url"]
        else:
            # Real API call to ClothOff
            with open(file_path, "rb") as image_file:
                # Generate a unique ID for this generation request
                generation_id = str(uuid.uuid4())
                
                # Create a temporary webhook URL using webhook.site or similar service
                # In production, you should use your own webhook endpoint
                webhook_url = f"https://webhook.site/{generation_id}"
                
                # Prepare the files and data for multipart/form-data
                files = {
                    'image': (f'image_{user_id}.jpg', image_file, 'image/jpeg')
                }
                
                data = {
                    'cloth': 'naked',
                    'id_gen': generation_id,
                    'webhook': webhook_url  # Add the required webhook field
                }
                
                headers = {
                    "accept": "application/json",
                    "x-api-key": CLOTHOFF_API_KEY
                }
                
                logger.info(f"Making ClothOff API request for user {user_id}")
                logger.info(f"Generation ID: {generation_id}")
                logger.info(f"Webhook URL: {webhook_url}")
                logger.info(f"API Key (first 10 chars): {CLOTHOFF_API_KEY[:10]}...")
                
                response = requests.post(
                    CLOTHOFF_API_URL,
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=60  # Increased timeout for image processing
                )
                
                logger.info(f"ClothOff API response status: {response.status_code}")
                logger.info(f"ClothOff API response: {response.text}")
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # Since ClothOff uses async processing with webhooks, 
                    # we need to handle this differently
                    if result.get("status") == "processing" or result.get("message") == "processing":
                        # The API accepted the request and will process it
                        await processing_msg.edit_text(
                            f"🔄 Your image is being processed!\n\n"
                            f"📋 Generation ID: `{generation_id}`\n"
                            f"🌐 Webhook URL: {webhook_url}\n\n"
                            f"⏱️ Processing may take 1-3 minutes.\n"
                            f"💡 Check the webhook URL above to see the result when ready.\n\n"
                            f"Note: This is a temporary solution. In production, results would be sent back to you automatically."
                        )
                        
                        # Deduct points since the request was accepted
                        update_generations(user_id)
                        success = True
                        result_image_url = None  # No immediate result
                    else:
                        # Check for immediate result (less likely with webhook model)
                        result_image_url = (
                            result.get("image_url") or 
                            result.get("output_url") or 
                            result.get("result_url") or
                            result.get("url") or
                            result.get("image") or
                            result.get("output") or
                            result.get("result")
                        )
                        
                        if result_image_url:
                            success = True
                        else:
                            success = False
                            logger.error(f"No image URL in response: {result}")
                            
                elif response.status_code == 400:
                    success = False
                    error_data = response.json() if response.text else {}
                    error_msg = f"ClothOff API Error: {response.status_code} - {error_data.get('error', response.text)}"
                    logger.error(error_msg)
                elif response.status_code == 401:
                    success = False
                    error_msg = f"ClothOff API Authentication Error: Invalid API key"
                    logger.error(error_msg)
                else:
                    success = False
                    error_msg = f"ClothOff API Error: {response.status_code} - {response.text}"
                    logger.error(error_msg)
        
        # Clean up the downloaded file
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            file_path = None
        
        if success and result_image_url:
            # Update user stats
            update_generations(user_id)
            remaining_points = user[1] - 1
            
            # Send result
            caption = (
                f"✅ Image processed successfully!\n\n"
                f"💎 Points remaining: {remaining_points}\n"
                f"🎨 Use /generate to process another image"
            )
            
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=result_image_url,
                caption=caption
            )
            
            # Delete processing message
            await processing_msg.delete()
            
        elif success and not result_image_url:
            # This handles the webhook/async processing case
            # The processing message was already updated with webhook info
            pass
            
        else:
            error_msg = (
                "❌ Error processing image.\n\n"
                "This could be due to:\n"
                "• API service unavailable\n"
                "• Invalid image format\n"
                "• Server overload\n\n"
                "Please try again later or contact /support"
            )
            await processing_msg.edit_text(error_msg)
            
    except requests.exceptions.Timeout:
        logger.error(f"API timeout for user {user_id}")
        await processing_msg.edit_text(
            "⏰ Request timed out. The server is taking too long to respond.\n"
            "Please try again in a few minutes."
        )
        
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error for user {user_id}")
        await processing_msg.edit_text(
            "🌐 Connection error. Please check your internet connection and try again."
        )
        
    except Exception as e:
        logger.error(f"Unexpected error for user {user_id}: {str(e)}")
        await processing_msg.edit_text(
            f"❌ Unexpected error occurred:\n`{str(e)}`\n\n"
            f"Please contact /support with this error message."
        )
        
    finally:
        # Always clean up the file
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

async def terms(update: Update, context):
    terms_text = (
        "📋 Terms of Service\n\n"
        "1. Use this bot responsibly and ethically\n"
        "2. Only upload images with proper consent\n"
        "3. No illegal, harmful, or inappropriate content\n"
        "4. Bot usage is monitored for safety\n"
        "5. We reserve the right to ban misuse\n"
        "6. No refunds for purchased points\n"
        "7. Service availability not guaranteed\n\n"
        "By using this bot, you agree to these terms.\n"
        "Contact /support for questions."
    )
    await update.message.reply_text(terms_text)

async def support(update: Update, context):
    support_text = (
        "🆘 Support & Help\n\n"
        "For technical issues, questions, or reports:\n\n"
        "📧 Contact: @YourSupportHandle\n"
        "🕐 Response time: 24-48 hours\n\n"
        "Common issues:\n"
        "• Payment problems: Include transaction ID\n"
        "• Processing errors: Send error screenshot\n"
        "• Account issues: Provide your user ID\n\n"
        f"Your User ID: `{update.effective_user.id}`"
    )
    await update.message.reply_text(support_text, parse_mode='Markdown')

async def stats(update: Update, context):
    """Admin command to get bot statistics"""
    user_id = update.effective_user.id
    
    # Add your admin user IDs here
    ADMIN_IDS = [123456789]  # Replace with actual admin IDs
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Access denied.")
        return
    
    try:
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        
        # Get statistics
        total_users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_generations = cursor.execute("SELECT SUM(generations_used) FROM users").fetchone()[0]
        total_transactions = cursor.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        total_stars = cursor.execute("SELECT SUM(stars_spent) FROM transactions").fetchone()[0]
        
        conn.close()
        
        stats_text = (
            f"📊 Bot Statistics\n\n"
            f"👥 Total Users: {total_users}\n"
            f"🎨 Total Generations: {total_generations or 0}\n"
            f"💳 Total Transactions: {total_transactions}\n"
            f"⭐ Total Stars Earned: {total_stars or 0}\n"
        )
        
        await update.message.reply_text(stats_text)
        
    except Exception as e:
        await update.message.reply_text(f"Error getting stats: {str(e)}")

async def test_api(update: Update, context):
    """Test command to check ClothOff API connectivity"""
    user_id = update.effective_user.id
    
    # Only allow specific users to test (for security)
    ALLOWED_TESTERS = [user_id]  # Add your user ID here
    
    if user_id not in ALLOWED_TESTERS:
        await update.message.reply_text("❌ Access denied.")
        return
    
    await update.message.reply_text("🧪 Testing ClothOff API connectivity...")
    
    try:
        # Test with the correct headers and required fields
        headers = {
            "accept": "application/json",
            "x-api-key": CLOTHOFF_API_KEY
        }
        
        # Test the actual undress endpoint with required data including webhook
        test_generation_id = str(uuid.uuid4())
        test_webhook_url = f"https://webhook.site/{test_generation_id}"
        
        test_data = {
            'cloth': 'naked',
            'id_gen': test_generation_id,
            'webhook': test_webhook_url  # Add required webhook field
        }
        
        test_response = requests.post(
            CLOTHOFF_API_URL,
            data=test_data,
            headers=headers,
            timeout=10
        )
        
        result_msg = (
            f"🔍 API Test Results:\n\n"
            f"📡 Endpoint: {CLOTHOFF_API_URL}\n"
            f"🔑 API Key: {'✅ Set' if CLOTHOFF_API_KEY else '❌ Missing'}\n"
            f"📊 Status: {test_response.status_code}\n"
            f"🆔 Test ID: `{test_generation_id}`\n"
            f"🌐 Test Webhook: {test_webhook_url}\n"
            f"📝 Response: ```{test_response.text[:500]}```"
        )
        
        await update.message.reply_text(result_msg, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"❌ API Test Failed: {str(e)}")

def test_clothoff_api_standalone():
    """Standalone function to test ClothOff API"""
    print("🧪 Testing ClothOff API...")
    
    # Load environment variables
    load_dotenv()
    api_key = os.getenv('CLOTHOFF_API_KEY')
    
    if not api_key:
        print("❌ No API key found in environment variables")
        return
    
    # Test basic connectivity with correct headers
    headers = {
        "accept": "application/json",
        "x-api-key": api_key
    }
    
    try:
        # Test the actual undress endpoint with required data
        test_generation_id = str(uuid.uuid4())
        test_webhook_url = f"https://webhook.site/{test_generation_id}"
        
        test_data = {
            'cloth': 'naked',
            'id_gen': test_generation_id,
            'webhook': test_webhook_url  # Add required webhook field
        }
        
        response = requests.post(
            "https://public-api.clothoff.net/undress",
            data=test_data,
            headers=headers,
            timeout=10
        )
        
        print(f"📊 Status Code: {response.status_code}")
        print(f"📝 Response Headers: {dict(response.headers)}")
        print(f"📄 Response Body: {response.text}")
        print(f"🆔 Generation ID: {test_generation_id}")
        print(f"🌐 Webhook URL: {test_webhook_url}")
        
        if response.status_code == 401:
            print("❌ Authentication failed - check your API key")
        elif response.status_code == 400:
            error_data = response.json() if response.text else {}
            error_message = error_data.get('error', 'Unknown error')
            print(f"⚠️ Bad request: {error_message}")
            if 'missing field' in error_message:
                print("💡 Tip: This error suggests we're missing a required field")
        elif response.status_code == 200:
            print("✅ API is working!")
            print("💡 Check the webhook URL above for results (if processing)")
        else:
            print(f"⚠️ Unexpected status code: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Connection error: {str(e)}")

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
    app.add_handler(CommandHandler("stats", stats))  # Admin command
    app.add_handler(CommandHandler("test", test_api))  # Test API command
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    
    print("🤖 Bot is starting...")
    print(f"📊 Mock mode: {'ON' if MOCK_MODE else 'OFF'}")
    app.run_polling()

if __name__ == "__main__":
    # Uncomment the line below to test API before running the bot
    # test_clothoff_api_standalone()
    main()