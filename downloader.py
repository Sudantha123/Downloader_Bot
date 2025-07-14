
import os
import asyncio
import logging
import subprocess
import shutil
import requests
import aiohttp
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
    
    async def download_with_aria2c(self, url, file_path, progress_callback=None):
        """Download using aria2c with progress tracking"""
        try:
            if progress_callback:
                await progress_callback("🚀 Starting aria2c download...")
            
            # aria2c command with optimized settings for large files
            cmd = [
                'aria2c',
                '--continue=true',  # Resume downloads
                '--max-tries=5',    # Retry failed downloads
                '--retry-wait=3',   # Wait between retries
                '--timeout=60',     # Connection timeout
                '--split=8',        # Use 8 connections
                '--max-connection-per-server=8',
                '--min-split-size=1M',  # Minimum split size
                '--file-allocation=none',  # Faster start
                '--check-certificate=false',  # Skip SSL cert check
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                '--header=Accept: video/mp4,video/*,*/*;q=0.8',
                '--dir=' + str(self.download_dir),
                '--out=' + os.path.basename(file_path),
                '--summary-interval=3',  # Progress update interval (reduced frequency)
                url
            ]
            
            logger.info(f"Running aria2c command: {' '.join(cmd)}")
            
            # Run aria2c with real-time progress tracking and timeout
            try:
                process = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    ),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.error("aria2c process creation timed out")
                return False
            
            # Track progress with timeout and throttling
            last_progress = ""
            last_update_time = 0
            import time
            
            try:
                while True:
                    try:
                        line = await asyncio.wait_for(process.stderr.readline(), timeout=2.0)
                        if not line:
                            break
                        
                        line = line.decode('utf-8', errors='ignore').strip()
                        current_time = time.time()
                        
                        # Only update progress every 3 seconds to avoid rate limits
                        if line and progress_callback and (current_time - last_update_time) >= 3:
                            # Parse aria2c progress output
                            if '[#' in line and '%]' in line:
                                try:
                                    # Extract detailed progress info
                                    percentage = "0"
                                    downloaded_size = "0B"
                                    total_size = "Unknown"
                                    speed = "0B/s"
                                    
                                    # Extract percentage
                                    if '(' in line and '%)' in line:
                                        start = line.find('(') + 1
                                        end = line.find('%)')
                                        if end > start:
                                            percentage = line[start:end]
                                    
                                    # Extract downloaded/total size
                                    if 'MiB' in line or 'GiB' in line or 'KiB' in line:
                                        parts = line.split()
                                        for i, part in enumerate(parts):
                                            if 'MiB' in part or 'GiB' in part or 'KiB' in part:
                                                if i > 0:
                                                    downloaded_size = parts[i-1] + part
                                                if '/' in part and i < len(parts) - 1:
                                                    total_size = parts[i+1] if i+1 < len(parts) else "Unknown"
                                                break
                                    
                                    # Extract speed
                                    if 'DL:' in line:
                                        speed_start = line.find('DL:') + 3
                                        speed_parts = line[speed_start:].split()
                                        if speed_parts:
                                            speed = speed_parts[0]
                                    
                                    progress_msg = f"📥 Downloading: {percentage}%\n💾 Data: {downloaded_size} / {total_size}\n🚄 Speed: {speed}"
                                    
                                    if progress_msg != last_progress:
                                        await progress_callback(progress_msg)
                                        last_progress = progress_msg
                                        last_update_time = current_time
                                except Exception as parse_error:
                                    logger.debug(f"Progress parse error: {parse_error}")
                                    pass
                    except asyncio.TimeoutError:
                        # Continue if readline times out
                        continue
            except Exception as e:
                logger.error(f"Error reading aria2c output: {e}")
            
            # Wait for process to complete with timeout
            try:
                await asyncio.wait_for(process.wait(), timeout=300)  # 5 minute timeout
            except asyncio.TimeoutError:
                logger.error("aria2c process timed out")
                try:
                    process.kill()
                except:
                    pass
                return False
            
            if process.returncode == 0:
                logger.info("aria2c download completed successfully")
                return True
            else:
                stderr_output = await process.stderr.read()
                logger.error(f"aria2c failed with code {process.returncode}: {stderr_output.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"aria2c download failed: {e}")
            return False
    
    async def download_with_wget(self, url, file_path, progress_callback=None):
        """Download using wget as fallback"""
        try:
            if progress_callback:
                await progress_callback("🔄 Trying with wget...")
            
            cmd = [
                'wget',
                '--continue',  # Resume downloads
                '--tries=3',   # Reduce retry attempts
                '--timeout=30',  # Reduce timeout
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                '--header=Accept: video/mp4,video/*,*/*;q=0.8',
                '--no-check-certificate',  # Skip SSL cert check
                '--progress=bar:force',  # Force progress bar
                '-O', str(file_path),
                url
            ]
            
            logger.info(f"Running wget command: {' '.join(cmd)}")
            
            # Add timeout to prevent hanging
            try:
                process = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    ),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.error("wget process creation timed out")
                return False
            
            # Track wget progress with timeout and throttling
            last_progress = ""
            last_update_time = 0
            import time
            
            try:
                while True:
                    try:
                        line = await asyncio.wait_for(process.stderr.readline(), timeout=2.0)
                        if not line:
                            break
                        
                        line = line.decode('utf-8', errors='ignore').strip()
                        current_time = time.time()
                        
                        # Only update progress every 3 seconds to avoid rate limits
                        if line and progress_callback and '%' in line and (current_time - last_update_time) >= 3:
                            try:
                                # Parse wget detailed progress
                                percentage = "0"
                                downloaded_size = "0K"
                                speed = "0K/s"
                                
                                parts = line.split()
                                for i, part in enumerate(parts):
                                    if '%' in part:
                                        percentage = part.replace('%', '')
                                    elif 'K' in part or 'M' in part or 'G' in part:
                                        if i > 0 and not '%' in parts[i-1]:
                                            downloaded_size = part
                                    elif '/s' in part:
                                        speed = part
                                
                                progress_msg = f"📥 Downloading: {percentage}%\n💾 Downloaded: {downloaded_size}\n🚄 Speed: {speed}"
                                
                                if progress_msg != last_progress:
                                    await progress_callback(progress_msg)
                                    last_progress = progress_msg
                                    last_update_time = current_time
                            except Exception as parse_error:
                                logger.debug(f"Progress parse error: {parse_error}")
                                pass
                    except asyncio.TimeoutError:
                        # Continue if readline times out
                        continue
            except Exception as e:
                logger.error(f"Error reading wget output: {e}")
            
            try:
                await asyncio.wait_for(process.wait(), timeout=300)  # 5 minute timeout
                
                if process.returncode == 0:
                    logger.info("wget download completed successfully")
                    return True
                else:
                    stderr_output = await process.stderr.read()
                    logger.error(f"wget failed with code {process.returncode}: {stderr_output.decode()}")
                    return False
            except asyncio.TimeoutError:
                logger.error("wget process timed out")
                try:
                    process.kill()
                except:
                    pass
                return False
                
        except Exception as e:
            logger.error(f"wget download failed: {e}")
            return False
    
    async def download_with_requests(self, url, file_path, progress_callback=None):
        """Download using Python requests library as final fallback"""
        try:
            if progress_callback:
                await progress_callback("🔄 Trying with Python requests...")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'video/mp4,video/*,*/*;q=0.8'
            }
            
            logger.info(f"Downloading with requests: {url}")
            
            # Use aiohttp for async download
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=1800),  # 30 minute timeout
                headers=headers
            ) as session:
                async with session.get(url, ssl=False) as response:
                    if response.status != 200:
                        logger.error(f"HTTP {response.status}: {response.reason}")
                        return False
                    
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded = 0
                    last_update_time = 0
                    import time
                    
                    def format_size(bytes_size):
                        """Format bytes to human readable format"""
                        for unit in ['B', 'KB', 'MB', 'GB']:
                            if bytes_size < 1024.0:
                                return f"{bytes_size:.1f}{unit}"
                            bytes_size /= 1024.0
                        return f"{bytes_size:.1f}TB"
                    
                    with open(file_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                            downloaded += len(chunk)
                            current_time = time.time()
                            
                            # Only update progress every 3 seconds to avoid rate limits
                            if progress_callback and total_size > 0 and (current_time - last_update_time) >= 3:
                                progress = (downloaded / total_size) * 100
                                downloaded_str = format_size(downloaded)
                                total_str = format_size(total_size)
                                
                                progress_msg = f"📥 Downloading: {progress:.1f}%\n💾 Data: {downloaded_str} / {total_str}"
                                await progress_callback(progress_msg)
                                last_update_time = current_time
                    
                    logger.info("Python requests download completed successfully")
                    return True
                    
        except Exception as e:
            logger.error(f"Python requests download failed: {e}")
            return False
    
    def check_tools_availability(self):
        """Check if aria2c and wget are available"""
        aria2c_available = shutil.which('aria2c') is not None
        wget_available = shutil.which('wget') is not None
        
        logger.info(f"aria2c available: {aria2c_available}")
        logger.info(f"wget available: {wget_available}")
        
        return aria2c_available, wget_available
    
    async def download_video(self, url, timeout=1800, progress_callback=None):
        """Download video using aria2c with wget fallback"""
        try:
            # Validate URL format
            if not url or not isinstance(url, str):
                logger.error("Invalid URL provided")
                return None
            
            # Clean the URL
            url = url.strip()
            
            # Check tools availability
            aria2c_available, wget_available = self.check_tools_availability()
            
            if not aria2c_available and not wget_available:
                logger.info("aria2c and wget not available, using Python requests fallback")
                if progress_callback:
                    await progress_callback("🔄 Using Python requests for download...")
            
            logger.info(f"Starting download: {url}")
            if progress_callback:
                await progress_callback("🔍 Validating download link...")
            
            filename = self.get_filename_from_url(url)
            file_path = self.download_dir / filename
            
            # Remove existing file if present to start fresh
            if file_path.exists():
                file_path.unlink()
            
            # Try aria2c first (preferred for large files)
            if aria2c_available:
                logger.info("Attempting download with aria2c")
                success = await self.download_with_aria2c(url, file_path, progress_callback)
                
                if success and file_path.exists():
                    file_size = file_path.stat().st_size
                    logger.info(f"Download completed with aria2c: {file_path} ({file_size / (1024*1024):.2f} MB)")
                    if progress_callback:
                        await progress_callback(f"✅ Download completed! ({file_size / (1024*1024):.1f} MB)")
                    return str(file_path)
            
            # Fallback to wget if aria2c failed or not available
            if wget_available:
                logger.info("Attempting download with wget")
                if progress_callback:
                    await progress_callback("🔄 Retrying with wget...")
                
                success = await self.download_with_wget(url, file_path, progress_callback)
                
                if success and file_path.exists():
                    file_size = file_path.stat().st_size
                    logger.info(f"Download completed with wget: {file_path} ({file_size / (1024*1024):.2f} MB)")
                    if progress_callback:
                        await progress_callback(f"✅ Download completed! ({file_size / (1024*1024):.1f} MB)")
                    return str(file_path)
            
            # Final fallback to Python requests
            logger.info("Attempting download with Python requests")
            if progress_callback:
                await progress_callback("🔄 Trying with Python requests...")
            
            success = await self.download_with_requests(url, file_path, progress_callback)
            
            if success and file_path.exists():
                file_size = file_path.stat().st_size
                logger.info(f"Download completed with Python requests: {file_path} ({file_size / (1024*1024):.2f} MB)")
                if progress_callback:
                    await progress_callback(f"✅ Download completed! ({file_size / (1024*1024):.1f} MB)")
                return str(file_path)
            
            # If we reach here, all methods failed
            logger.error("All download methods failed")
            if progress_callback:
                await progress_callback("❌ All download methods failed!")
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
                
