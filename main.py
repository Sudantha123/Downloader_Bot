import os
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from downloader import VideoDownloader
from userbot import TelegramUserbot

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self):
        self.bot_token = os.getenv('BOT_TOKEN')
        self.downloader = VideoDownloader()
        self.userbot = TelegramUserbot()
        
        if not self.bot_token:
            raise ValueError("BOT_TOKEN not found in environment variables")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        await update.message.reply_text(
            "🤖 Video Downloader Bot\n\n"
            "Send me a direct download link and I'll download the video and forward it to the target group!\n\n"
            "Supported: Direct video links"
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        await update.message.reply_text(
            "📋 How to use:\n\n"
            "1. Send me a direct download link\n"
            "2. I'll download the video\n"
            "3. The video will be sent to the target group\n"
            "4. File will be deleted after sending\n\n"
            "Commands:\n"
            "/start - Start the bot\n"
            "/help - Show this help message"
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages with download links"""
        message_text = update.message.text
        
        # Check if message contains a URL
        if not (message_text.startswith('http://') or message_text.startswith('https://')):
            await update.message.reply_text("❌ Please send a valid direct download link!")
            return
        
        # Send processing message
        processing_msg = await update.message.reply_text("⏳ Processing your link...")
        
        try:
            # Create progress callback for download
            async def download_progress_callback(message):
                try:
                    await processing_msg.edit_text(message)
                except:
                    pass  # Ignore edit failures due to rate limits
            
            # Download the video with progress
            await processing_msg.edit_text("📥 Starting download...")
            file_path = await self.downloader.download_video(message_text, progress_callback=download_progress_callback)
            
            if not file_path:
                await processing_msg.edit_text("❌ Failed to download video. Please check the link!")
                return
            
            # Create progress callback for upload
            async def upload_progress_callback(message):
                try:
                    await processing_msg.edit_text(message)
                except:
                    pass  # Ignore edit failures due to rate limits
            
            # Send via userbot with progress tracking
            await processing_msg.edit_text("📤 Preparing to send to target group...")
            success = await self.userbot.send_video_to_group(file_path, progress_callback=upload_progress_callback)
            
            if success:
                await processing_msg.edit_text("✅ Video successfully sent to target group!\n📱 The video should be playable and downloadable in the group.")
            else:
                await processing_msg.edit_text("❌ Failed to send video to target group!")
                
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            await processing_msg.edit_text(f"❌ Error: {str(e)}")
    
    def run(self):
        """Start the bot"""
        application = Application.builder().token(self.bot_token).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Run the bot
        logger.info("Starting bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        bot = TelegramBot()
        bot.run()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
