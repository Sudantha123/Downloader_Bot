import os
import asyncio
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import DocumentAttributeVideo
from pathlib import Path
from downloader import VideoDownloader

logger = logging.getLogger(__name__)

class TelegramUserbot:
    def __init__(self):
        self.api_id = os.getenv('API_ID')
        self.api_hash = os.getenv('API_HASH')
        self.session_string = os.getenv('SESSION_STRING')
        self.group_id = os.getenv('GROUP_ID')
        self.downloader = VideoDownloader()

        # Validate required environment variables
        if not all([self.api_id, self.api_hash, self.group_id]):
            raise ValueError("Missing required environment variables: API_ID, API_HASH, GROUP_ID")

        try:
            self.api_id = int(self.api_id)
            self.group_id = int(self.group_id)
        except ValueError:
            raise ValueError("API_ID and GROUP_ID must be integers")

        self.client = None

    async def initialize_client(self):
        """Initialize Telegram client"""
        try:
            # Create sessions directory if it doesn't exist and set permissions
            sessions_dir = Path("sessions")
            sessions_dir.mkdir(mode=0o755, exist_ok=True)

            if self.session_string and self.session_string.strip():
                # Use session string if available and not empty
                logger.info("Using provided SESSION_STRING")
                self.client = TelegramClient(
                    session=StringSession(self.session_string),
                    api_id=self.api_id,
                    api_hash=self.api_hash
                )
            else:
                # Use in-memory session to avoid file permission issues
                logger.info("No SESSION_STRING provided, using temporary session")
                self.client = TelegramClient(
                    session=StringSession(),
                    api_id=self.api_id,
                    api_hash=self.api_hash
                )

            # Set proper timeout for connection with optimizations
            logger.info("Connecting to Telegram...")
            
            # Configure client for faster uploads before connecting
            self.client.flood_sleep_threshold = 60  # Handle flood waits better
            
            await asyncio.wait_for(self.client.connect(), timeout=30)
            
            # Optimize connection for uploads after connecting
            if hasattr(self.client, '_sender') and self.client._sender:
                # Increase concurrent requests for faster uploads
                self.client._sender._request_retries = 3
                self.client._sender._connection_retries = 2

            if not await self.client.is_user_authorized():
                if self.session_string:
                    logger.error("SESSION_STRING is invalid or expired. Please generate a new one.")
                else:
                    logger.error("No valid SESSION_STRING provided. Please add it to environment variables.")
                logger.error("To generate SESSION_STRING, use: https://replit.com/@username/telegram-session-generator")
                return False

            logger.info("Userbot initialized successfully")
            return True

        except asyncio.TimeoutError:
            logger.error("Connection timeout. Please check your internet connection.")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize userbot: {e}")
            if "database" in str(e).lower():
                logger.error("Database file error. Using SESSION_STRING is recommended.")
            return False

    async def send_video_to_group(self, file_path, progress_callback=None, max_retries=3):
        """Send video file to specified group with progress tracking and retry mechanism"""
        for attempt in range(max_retries):
            try:
                # Initialize client if not already done
                if not self.client:
                    if not await self.initialize_client():
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)  # Wait before retry
                            continue
                        return False

                # Check if file exists
                if not os.path.exists(file_path):
                    logger.error(f"File not found: {file_path}")
                    return False

                # Get file info
                file_size = os.path.getsize(file_path)
                file_name = os.path.basename(file_path)

                logger.info(f"Sending file: {file_name} ({file_size / (1024*1024):.2f} MB)")

                if progress_callback:
                    await progress_callback("📤 Starting video upload...")

                # Create video attributes for proper display
                video_attributes = {
                    'duration': await self._get_video_duration(file_path),
                    'w': 1280,  # Default width
                    'h': 720,   # Default height
                    'supports_streaming': True
                }

                # Progress callback for upload with optimized throttling
                last_upload_update = 0
                last_percentage = 0
                import time

                def format_size(bytes_size):
                    """Format bytes to human readable format"""
                    for unit in ['B', 'KB', 'MB', 'GB']:
                        if bytes_size < 1024.0:
                            return f"{bytes_size:.1f}{unit}"
                        bytes_size /= 1024.0
                    return f"{bytes_size:.1f}TB"

                def calculate_speed(current, total, start_time):
                    """Calculate upload speed"""
                    elapsed = time.time() - start_time
                    if elapsed > 0:
                        speed = current / elapsed
                        return format_size(speed) + "/s"
                    return "0B/s"

                upload_start_time = time.time()

                async def upload_progress(current, total):
                    nonlocal last_upload_update, last_percentage, upload_start_time
                    current_time = time.time()
                    percentage = (current / total) * 100

                    # Update every 2 seconds OR every 5% progress for better feedback
                    if progress_callback and (
                        (current_time - last_upload_update) >= 2 or 
                        (percentage - last_percentage) >= 5 or 
                        current == total
                    ):
                        current_str = format_size(current)
                        total_str = format_size(total)
                        speed = calculate_speed(current, total, upload_start_time)

                        progress_msg = f"📤 Uploading: {percentage:.1f}%\n💾 Data: {current_str} / {total_str}\n🚄 Speed: {speed}"
                        
                        # Use asyncio.create_task to avoid blocking the upload
                        asyncio.create_task(progress_callback(progress_msg))
                        last_upload_update = current_time
                        last_percentage = percentage

                # Send video to group with optimized upload settings
                from telethon.tl.types import DocumentAttributeVideo

                # Optimize upload with larger chunks and multiple connections
                await self.client.send_file(
                    entity=self.group_id,
                    file=file_path,
                    caption=f"📹 {file_name}\n💾 Size: {file_size / (1024*1024):.2f} MB",
                    supports_streaming=True,
                    attributes=[
                        DocumentAttributeVideo(
                            duration=video_attributes['duration'],
                            w=video_attributes['w'],
                            h=video_attributes['h'],
                            supports_streaming=True
                        )
                    ],
                    progress_callback=upload_progress,
                    thumb=None,  # Let Telegram generate thumbnail
                    # Optimization parameters for faster uploads
                    file_size=file_size,
                    part_size_kb=512,  # Use 512KB chunks (max allowed)
                    use_cache=False,   # Don't cache for large files
                    allow_cache=False, # Disable caching to save memory
                    max_file_size=2000 * 1024 * 1024,  # 2GB max file size
                    # Force chunked upload for better speed
                    force_file=True
                )

                logger.info(f"Video sent successfully to group {self.group_id}")

                if progress_callback:
                    await progress_callback("✅ Upload completed!")

                # Clean up the file after sending
                self.downloader.cleanup_file(file_path)

                return True

            except Exception as e:
                logger.error(f"Upload attempt {attempt + 1} failed: {e}")
                
                # Check if it's a temporary error worth retrying
                if attempt < max_retries - 1:
                    if any(error in str(e).lower() for error in ['timeout', 'connection', 'network', 'temporary']):
                        if progress_callback:
                            await progress_callback(f"🔄 Upload failed, retrying... (attempt {attempt + 2}/{max_retries})")
                        await asyncio.sleep(3)  # Wait before retry
                        
                        # Try to reconnect the client for network issues
                        try:
                            if self.client:
                                await self.client.disconnect()
                                self.client = None
                        except:
                            pass
                        continue
                
                # Final failure after all retries
                if progress_callback:
                    await progress_callback(f"❌ Upload failed after {max_retries} attempts: {str(e)}")
                
                # Still try to clean up the file even if sending failed
                self.downloader.cleanup_file(file_path)
                return False
        
        # If we reach here, all retries failed
        self.downloader.cleanup_file(file_path)
        return False

    async def _get_video_duration(self, file_path):
        """Get video duration in seconds (fallback method)"""
        try:
            # Simple duration detection based on file size (rough estimate)
            file_size = os.path.getsize(file_path)
            # Assume average bitrate of 1 Mbps for estimation
            estimated_duration = max(10, min(3600, file_size // (125000)))  # 10 sec to 1 hour
            return int(estimated_duration)
        except:
            return 60  # Default 1 minute

    async def disconnect(self):
        """Disconnect the client"""
        if self.client:
            await self.client.disconnect()
            logger.info("Userbot disconnected")
