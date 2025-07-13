
import os
import aiohttp
import aiofiles
import asyncio
import logging
from urllib.parse import urlparse
from pathlib import Path

logger = logging.getLogger(__name__)

class VideoDownloader:
    def __init__(self):
        self.download_dir = Path("downloads")
        self.download_dir.mkdir(exist_ok=True)
    
    def get_filename_from_url(self, url):
        """Extract filename from URL"""
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        
        # If no filename found, create a default one
        if not filename or '.' not in filename:
            filename = "video.mp4"
        
        return filename
    
    async def download_video(self, url, timeout=300, progress_callback=None):
        """Download video from direct link with progress tracking"""
        try:
            # Validate URL format
            if not url or not isinstance(url, str):
                logger.error("Invalid URL provided")
                return None
            
            # Clean the URL
            url = url.strip()
            
            # Check if URL is accessible
            logger.info(f"Validating URL: {url}")
            if progress_callback:
                await progress_callback("🔍 Validating download link...")
            
            filename = self.get_filename_from_url(url)
            # Ensure filename has proper extension for video
            if not any(filename.lower().endswith(ext) for ext in ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm']):
                filename = filename.rsplit('.', 1)[0] + '.mp4' if '.' in filename else filename + '.mp4'
            
            file_path = self.download_dir / filename
            
            logger.info(f"Starting download: {url}")
            
            # Set up headers to mimic a browser request
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'video/mp4,video/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'identity',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            timeout_config = aiohttp.ClientTimeout(total=timeout)
            
            async with aiohttp.ClientSession(timeout=timeout_config, headers=headers) as session:
                async with session.get(url, allow_redirects=True) as response:
                    logger.info(f"Response status: {response.status}")
                    logger.info(f"Content-Type: {response.headers.get('content-type', 'unknown')}")
                    
                    if response.status != 200:
                        logger.error(f"HTTP {response.status} error for URL: {url}")
                        if progress_callback:
                            await progress_callback(f"❌ HTTP {response.status} error - Invalid link or server issue")
                        return None
                    
                    # Check if content is actually a video
                    content_type = response.headers.get('content-type', '').lower()
                    if content_type and not any(vid_type in content_type for vid_type in ['video/', 'application/octet-stream', 'binary/octet-stream']):
                        logger.warning(f"Content-Type '{content_type}' may not be a video file")
                        # Continue anyway as some servers don't set proper content-type
                    
                    # Get file size for progress tracking
                    file_size = response.headers.get('content-length')
                    total_size = int(file_size) if file_size else 0
                    downloaded = 0
                    
                    if total_size > 0:
                        logger.info(f"File size: {total_size / (1024*1024):.2f} MB")
                        if progress_callback:
                            await progress_callback(f"📥 Downloading: 0% (0 MB / {total_size / (1024*1024):.1f} MB)")
                    
                    # Download file with progress tracking
                    async with aiofiles.open(file_path, 'wb') as file:
                        async for chunk in response.content.iter_chunked(8192):
                            await file.write(chunk)
                            downloaded += len(chunk)
                            
                            # Update progress every 100KB to avoid too many updates
                            if progress_callback and total_size > 0 and downloaded % 102400 == 0:
                                percentage = (downloaded / total_size) * 100
                                await progress_callback(f"📥 Downloading: {percentage:.1f}% ({downloaded / (1024*1024):.1f} MB / {total_size / (1024*1024):.1f} MB)")
                    
                    if progress_callback:
                        await progress_callback(f"📥 Download completed! ({downloaded / (1024*1024):.1f} MB)")
            
            logger.info(f"Download completed: {file_path}")
            return str(file_path)
            
        except asyncio.TimeoutError:
            logger.error(f"Download timeout for URL: {url}")
            if progress_callback:
                await progress_callback("❌ Download timeout!")
            return None
        except Exception as e:
            logger.error(f"Download failed for URL {url}: {e}")
            if progress_callback:
                await progress_callback(f"❌ Download failed: {str(e)}")
            return None
    
    def cleanup_file(self, file_path):
        """Delete downloaded file"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Deleted file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to delete file {file_path}: {e}")
        
