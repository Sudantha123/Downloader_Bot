
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
            
            # Set proper timeout for connection
            logger.info("Connecting to Telegram...")
            await asyncio.wait_for(self.client.connect(), timeout=30)
            
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
    
    async def send_video_to_group(self, file_path, progress_callback=None):
        """Send video file to specified group with progress tracking"""
        try:
            # Initialize client if not already done
            if not self.client:
                if not await self.initialize_client():
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
            
            # Progress tracking function
            def upload_progress(current, total):
                if progress_callback:
                    percentage = (current / total) * 100
                    asyncio.create_task(progress_callback(f"📤 Uploading: {percentage:.1f}% ({current / (1024*1024):.1f} MB / {total / (1024*1024):.1f} MB)"))
            
            # Send video to group with proper attributes
            from telethon.tl.types import DocumentAttributeVideo
            
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
                thumb=None  # Let Telegram generate thumbnail
            )
            
            logger.info(f"Video sent successfully to group {self.group_id}")
            
            if progress_callback:
                await progress_callback("✅ Upload completed!")
            
            # Clean up the file after sending
            self.downloader.cleanup_file(file_path)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to send video: {e}")
            if progress_callback:
                await progress_callback(f"❌ Upload failed: {str(e)}")
            # Still try to clean up the file even if sending failed
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
