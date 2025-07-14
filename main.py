
import os
import asyncio
import logging
import psutil
import time
import shutil
import subprocess
from datetime import datetime, timedelta
from collections import deque
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from downloader import VideoDownloader
from userbot import TelegramUserbot
from keep_alive import keep_alive

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class QueueItem:
    def __init__(self, url, chat_id, message_id, user_id):
        self.url = url
        self.chat_id = chat_id
        self.message_id = message_id
        self.user_id = user_id
        self.status = "queued"  # queued, downloading, uploading, completed, failed
        self.progress_message = None

class TelegramBot:
    def __init__(self):
        self.bot_token = os.getenv('BOT_TOKEN')
        self.downloader = VideoDownloader()
        self.userbot = TelegramUserbot()
        self.download_queue = deque()
        self.is_processing = False
        self.current_item = None
        self.cancelled = False
        
        if not self.bot_token:
            raise ValueError("BOT_TOKEN not found in environment variables")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        await update.message.reply_text(
            "🤖 Video Downloader Bot with Queue System\n\n"
            "Send me direct download links and I'll queue them for processing!\n\n"
            "Features:\n"
            "• Queue multiple downloads\n"
            "• Process files one by one\n"
            "• Real-time progress updates\n"
            "• Cancel all downloads\n"
            "• Storage management\n\n"
            "Commands:\n"
            "/help - Show help message\n"
            "/status - Show system status\n"
            "/queue - Show current queue\n"
            "/cancel - Cancel all downloads\n"
            "/del_storage - Delete all downloaded files"
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        await update.message.reply_text(
            "📋 How to use the Queue System:\n\n"
            "1. Send me direct download links\n"
            "2. Each link will be added to the queue\n"
            "3. Bot processes files one by one\n"
            "4. Get progress updates for each file\n"
            "5. Files are sent to target group automatically\n\n"
            "Commands:\n"
            "/start - Start the bot\n"
            "/help - Show this help message\n"
            "/status - Show system status and resource usage\n"
            "/queue - Show current download queue\n"
            "/cancel - Cancel all pending downloads\n"
            "/del_storage - Delete all downloaded files and free storage"
        )
    
    async def queue_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /queue command - show current queue"""
        if not self.download_queue and not self.current_item:
            await update.message.reply_text("📭 Queue is empty!")
            return
        
        queue_text = "📋 **Download Queue Status**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        # Show current processing item
        if self.current_item:
            queue_text += f"🔄 **Currently Processing:**\n"
            queue_text += f"├─ Status: {self.current_item.status.title()}\n"
            queue_text += f"├─ URL: {self.current_item.url[:50]}...\n"
            queue_text += f"└─ User: {self.current_item.user_id}\n\n"
        
        # Show queued items
        if self.download_queue:
            queue_text += f"⏳ **Queued Items ({len(self.download_queue)}):**\n"
            for i, item in enumerate(list(self.download_queue)[:10], 1):  # Show first 10 items
                queue_text += f"{i}. {item.url[:40]}... (User: {item.user_id})\n"
            
            if len(self.download_queue) > 10:
                queue_text += f"...and {len(self.download_queue) - 10} more items\n"
        
        queue_text += f"\n🎯 **Queue Statistics:**\n"
        queue_text += f"├─ Total in queue: {len(self.download_queue)}\n"
        queue_text += f"├─ Processing: {'Yes' if self.is_processing else 'No'}\n"
        queue_text += f"└─ Cancelled: {'Yes' if self.cancelled else 'No'}"
        
        await update.message.reply_text(queue_text)
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cancel command - cancel all downloads"""
        if not self.download_queue and not self.current_item:
            await update.message.reply_text("📭 No downloads to cancel!")
            return
        
        cancelled_count = len(self.download_queue)
        if self.current_item:
            cancelled_count += 1
        
        # Set cancellation flag
        self.cancelled = True
        
        # Clear the queue
        self.download_queue.clear()
        
        # Update current item status
        if self.current_item:
            self.current_item.status = "cancelled"
        
        await update.message.reply_text(
            f"🚫 **Download Cancellation**\n\n"
            f"✅ Cancelled {cancelled_count} download(s)\n"
            f"🔄 Current download will stop after current operation\n"
            f"📁 Downloaded files are kept (use /del_storage to remove)\n\n"
            f"You can start adding new downloads anytime!"
        )
    
    async def del_storage_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /del_storage command - delete all downloaded files"""
        try:
            downloads_dir = "downloads"
            if not os.path.exists(downloads_dir):
                await update.message.reply_text("📁 Downloads folder doesn't exist!")
                return
            
            # Get storage info before deletion
            total_size = 0
            file_count = 0
            
            for filename in os.listdir(downloads_dir):
                filepath = os.path.join(downloads_dir, filename)
                if os.path.isfile(filepath):
                    total_size += os.path.getsize(filepath)
                    file_count += 1
            
            if file_count == 0:
                await update.message.reply_text("📁 Downloads folder is already empty!")
                return
            
            # Delete all files
            deleted_count = 0
            for filename in os.listdir(downloads_dir):
                filepath = os.path.join(downloads_dir, filename)
                if os.path.isfile(filepath):
                    try:
                        os.remove(filepath)
                        deleted_count += 1
                    except Exception as e:
                        logger.error(f"Error deleting {filepath}: {e}")
            
            # Format size
            def format_bytes(bytes_val):
                for unit in ['B', 'KB', 'MB', 'GB']:
                    if bytes_val < 1024.0:
                        return f"{bytes_val:.2f} {unit}"
                    bytes_val /= 1024.0
                return f"{bytes_val:.2f} TB"
            
            await update.message.reply_text(
                f"🗑️ **Storage Cleanup Complete**\n\n"
                f"✅ Deleted {deleted_count} file(s)\n"
                f"💾 Freed {format_bytes(total_size)} of storage\n"
                f"📁 Downloads folder is now empty\n\n"
                f"Ready for new downloads! 🚀"
            )
            
        except Exception as e:
            logger.error(f"Error in del_storage_command: {e}")
            await update.message.reply_text(f"❌ Error deleting storage: {str(e)}")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command - show system status"""
        status_msg = await update.message.reply_text("🔍 Gathering system information...")
        
        try:
            # Get system information
            status_info = await self.get_system_status()
            await status_msg.edit_text(status_info)
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            await status_msg.edit_text(f"❌ Error getting system status: {str(e)}")
    
    async def get_system_status(self):
        """Get comprehensive system status"""
        try:
            # Basic system info
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.now() - boot_time
            
            # CPU information
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            cpu_freq = psutil.cpu_freq()
            
            # Memory information
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            # Disk information
            disk_usage = psutil.disk_usage('/')
            downloads_usage = 0
            downloads_count = 0
            if os.path.exists('downloads'):
                for f in os.listdir('downloads'):
                    filepath = os.path.join('downloads', f)
                    if os.path.isfile(filepath):
                        downloads_usage += os.path.getsize(filepath)
                        downloads_count += 1
            
            # Network information
            net_io = psutil.net_io_counters()
            
            # Process information
            process = psutil.Process(os.getpid())
            process_memory = process.memory_info()
            process_cpu = process.cpu_percent()
            
            # Get network speed test
            ping_result = await self.get_ping()
            speed_test = await self.get_network_speed()
            
            # Format sizes
            def format_bytes(bytes_val):
                for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                    if bytes_val < 1024.0:
                        return f"{bytes_val:.2f} {unit}"
                    bytes_val /= 1024.0
                return f"{bytes_val:.2f} PB"
            
            def format_uptime(td):
                days, seconds = td.days, td.seconds
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                return f"{days}d {hours}h {minutes}m"
            
            # Build status message
            status_text = f"""🤖 **System Status Report**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏰ **Uptime:** {format_uptime(uptime)}
🔄 **Boot Time:** {boot_time.strftime('%Y-%m-%d %H:%M:%S')}

🧠 **CPU Usage**
├─ Current: {cpu_percent}%
├─ Cores: {cpu_count}
├─ Frequency: {cpu_freq.current:.2f} MHz (max: {cpu_freq.max:.2f} MHz)
└─ Bot Process: {process_cpu}%

💾 **Memory Usage**
├─ Total: {format_bytes(memory.total)}
├─ Used: {format_bytes(memory.used)} ({memory.percent}%)
├─ Available: {format_bytes(memory.available)}
├─ Bot Process: {format_bytes(process_memory.rss)}
└─ Swap: {format_bytes(swap.used)}/{format_bytes(swap.total)} ({swap.percent}%)

💿 **Storage Usage**
├─ Total: {format_bytes(disk_usage.total)}
├─ Used: {format_bytes(disk_usage.used)} ({disk_usage.percent}%)
├─ Free: {format_bytes(disk_usage.free)}
├─ Downloads: {format_bytes(downloads_usage)} ({downloads_count} files)
└─ Queue: {len(self.download_queue)} items

🌐 **Network Statistics**
├─ Bytes Sent: {format_bytes(net_io.bytes_sent)}
├─ Bytes Received: {format_bytes(net_io.bytes_recv)}
├─ Packets Sent: {net_io.packets_sent:,}
├─ Packets Received: {net_io.packets_recv:,}
└─ Ping: {ping_result}

📡 **Network Speed**
{speed_test}

🔧 **Tools Status**
├─ aria2c: {'✅ Available' if shutil.which('aria2c') else '❌ Not found'}
├─ wget: {'✅ Available' if shutil.which('wget') else '❌ Not found'}
└─ Python: {psutil.version_info}

📊 **Bot Status**
├─ PID: {os.getpid()}
├─ Threads: {process.num_threads()}
├─ Open Files: {len(process.open_files())}
├─ Connections: {len(process.connections())}
├─ Queue Processing: {'✅ Active' if self.is_processing else '⏸️ Idle'}
└─ Current Item: {'✅ Yes' if self.current_item else '❌ None'}

📋 **Queue Status**
├─ Items in Queue: {len(self.download_queue)}
├─ Currently Processing: {'✅ Yes' if self.current_item else '❌ No'}
├─ Cancelled: {'✅ Yes' if self.cancelled else '❌ No'}
└─ Processing Status: {'🔄 Running' if self.is_processing else '⏸️ Idle'}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🕐 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            
            return status_text
            
        except Exception as e:
            logger.error(f"Error in get_system_status: {e}")
            return f"❌ Error getting system status: {str(e)}"
    
    async def get_ping(self):
        """Get ping to Google DNS"""
        try:
            result = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    'ping', '-c', '3', '8.8.8.8',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                ),
                timeout=10
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode == 0:
                output = stdout.decode()
                # Extract average ping time
                for line in output.split('\n'):
                    if 'avg' in line or 'min/avg/max' in line:
                        try:
                            avg_time = line.split('/')[-2]
                            return f"{avg_time}ms"
                        except:
                            pass
                return "Connected"
            else:
                return "❌ Failed"
        except asyncio.TimeoutError:
            return "⏱️ Timeout"
        except Exception as e:
            return f"❌ Error: {str(e)[:20]}"
    
    async def get_network_speed(self):
        """Get network speed test"""
        try:
            # Simple speed test using curl to download a small file
            start_time = time.time()
            
            # Test download speed
            result = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    'curl', '-s', '-o', '/dev/null', '-w', '%{speed_download}',
                    'https://httpbin.org/bytes/1048576',  # 1MB file
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                ),
                timeout=15
            )
            
            stdout, stderr = await result.communicate()
            
            if result.returncode == 0:
                download_speed = float(stdout.decode().strip())
                download_speed_mb = download_speed / (1024 * 1024)
                
                # Test upload speed (simplified)
                upload_start = time.time()
                upload_result = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        'curl', '-s', '-o', '/dev/null', '-w', '%{speed_upload}',
                        '-X', 'POST', '--data', 'x' * 10240,  # 10KB test
                        'https://httpbin.org/post',
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    ),
                    timeout=10
                )
                
                upload_stdout, upload_stderr = await upload_result.communicate()
                
                if upload_result.returncode == 0:
                    upload_speed = float(upload_stdout.decode().strip())
                    upload_speed_mb = upload_speed / (1024 * 1024)
                    
                    return f"├─ Download: {download_speed_mb:.2f} MB/s\n└─ Upload: {upload_speed_mb:.2f} MB/s"
                else:
                    return f"├─ Download: {download_speed_mb:.2f} MB/s\n└─ Upload: ❌ Failed"
            else:
                return "❌ Speed test failed"
                
        except asyncio.TimeoutError:
            return "⏱️ Speed test timeout"
        except Exception as e:
            return f"❌ Speed test error: {str(e)[:30]}"
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages with download links"""
        message_text = update.message.text.strip()
        
        # Check if message contains a URL
        if not (message_text.startswith('http://') or message_text.startswith('https://')):
            await update.message.reply_text(
                "❌ Please send a valid direct download link!\n\n"
                "Example: https://example.com/video.mp4\n"
                "Make sure it's a direct link to a video file."
            )
            return
        
        # Basic URL validation
        if len(message_text) < 10 or ' ' in message_text:
            await update.message.reply_text("❌ Invalid URL format. Please send a proper direct download link!")
            return
        
        # Create queue item
        queue_item = QueueItem(
            url=message_text,
            chat_id=update.message.chat_id,
            message_id=update.message.message_id,
            user_id=update.message.from_user.id
        )
        
        # Add to queue
        self.download_queue.append(queue_item)
        
        # Send confirmation
        position = len(self.download_queue)
        confirm_msg = await update.message.reply_text(
            f"✅ **Link Added to Queue!**\n\n"
            f"🔗 URL: {message_text[:50]}...\n"
            f"📍 Position: #{position}\n"
            f"⏳ Status: Queued\n\n"
            f"📋 Use /queue to see full queue\n"
            f"🚫 Use /cancel to cancel all downloads"
        )
        
        # Start processing if not already running
        if not self.is_processing:
            asyncio.create_task(self.process_queue())
    
    async def process_queue(self):
        """Process the download queue"""
        if self.is_processing:
            return
        
        self.is_processing = True
        logger.info("Starting queue processing...")
        
        try:
            while self.download_queue and not self.cancelled:
                # Get next item
                self.current_item = self.download_queue.popleft()
                
                logger.info(f"Processing item: {self.current_item.url}")
                
                # Send processing message
                try:
                    self.current_item.progress_message = await self.application.bot.send_message(
                        chat_id=self.current_item.chat_id,
                        text=f"🔄 **Processing Your Download**\n\n"
                             f"🔗 URL: {self.current_item.url[:50]}...\n"
                             f"📍 Status: Starting download...\n"
                             f"⏳ Please wait..."
                    )
                except Exception as e:
                    logger.error(f"Error sending progress message: {e}")
                    continue
                
                # Check if cancelled
                if self.cancelled:
                    try:
                        await self.current_item.progress_message.edit_text("🚫 Download cancelled!")
                    except:
                        pass
                    break
                
                # Update status
                self.current_item.status = "downloading"
                
                # Create progress callback
                async def progress_callback(message):
                    if self.current_item.progress_message and not self.cancelled:
                        try:
                            await self.current_item.progress_message.edit_text(
                                f"📥 **Downloading**\n\n"
         
