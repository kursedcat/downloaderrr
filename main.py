import os
import glob
import hashlib
import logging
import subprocess
import re
import json
import math
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.exceptions import BadRequest
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from moviepy.editor import VideoFileClip

# Загрузка переменных из .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

API_TOKEN = os.getenv("API_TOKEN")
CHANNEL_USERNAME = '@bbacckkeennddtestchannell'
FFMPEG_PATH = r"C:\Users\cursed\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"
DOWNLOAD_PATH = "downloads"

# Инициализация бота и диспетчера с хранилищем
storage = MemoryStorage()
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=storage)

# Создание директории для загрузок, если она не существует
if not os.path.exists(DOWNLOAD_PATH):
    os.makedirs(DOWNLOAD_PATH)

def generate_short_id(url: str) -> str:
    """Генерирует короткий ID для URL"""
    return hashlib.md5(url.encode()).hexdigest()[:8]

async def get_video_info(url: str) -> dict:
    """Получает информацию о видео, включая размеры файлов для разных качеств"""
    try:
        command = [
            "yt-dlp",
            "--no-warnings",
            "--no-check-certificate",
            "--dump-json",
            url
        ]
        
        if "instagram.com" in url:
            command.extend([
                "--add-header", "User-Agent:Instagram 219.0.0.12.117 Android",
            ])
        
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        stdout, stderr = process.communicate()
        if process.returncode == 0:
            info = json.loads(stdout)
            formats = info.get('formats', [])
            
            def find_format_size(height):
                matching_formats = [f for f in formats if f.get('height') == height]
                if matching_formats:
                    with_audio = [f for f in matching_formats if f.get('acodec') != 'none']
                    if with_audio:
                        return with_audio[0].get('filesize', 0)
                    return matching_formats[0].get('filesize', 0)
                return 0

            sizes = {
                '144p': find_format_size(144) or 5 * 1024 * 1024,
                '360p': find_format_size(360) or 15 * 1024 * 1024,
                '480p': find_format_size(480) or 25 * 1024 * 1024,
                '720p': find_format_size(720) or 50 * 1024 * 1024,
                'best': max((f.get('filesize', 0) for f in formats), default=100 * 1024 * 1024)
            }
            
            # Проверка логичности размеров
            prev_size = 0
            for quality in ['144p', '360p', '480p', '720p', 'best']:
                if sizes[quality] < prev_size:
                    sizes[quality] = prev_size * 1.5
                prev_size = sizes[quality]
                
            return sizes
    except Exception as e:
        logger.exception("Ошибка при получении информации о видео")
    return None

async def download_media(url: str, quality: str = 'best') -> str:
    """Загружает медиафайл с указанным качеством"""
    try:
        output_path_template = os.path.join(DOWNLOAD_PATH, "%(title)s.%(ext)s")
        
        quality_formats = {
            '144p': 'bestvideo[height<=144][ext=mp4]+bestaudio[ext=m4a]/worst[ext=mp4]',
            '360p': 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]',
            '480p': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]',
            '720p': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]',
            'best': 'best[ext=mp4]/best'
        }
        
        format_spec = quality_formats.get(quality, quality_formats['best'])

        command = [
            "yt-dlp",
            "-f", format_spec,
            "--no-warnings",
            "--no-check-certificate",
            "--ffmpeg-location", FFMPEG_PATH,
            "--merge-output-format", "mp4",
            "-o", output_path_template,
        ]

        if "instagram.com" in url:
            command.extend([
                "--add-header", "User-Agent:Instagram 219.0.0.12.117 Android",
            ])
        elif "youtube.com" in url or "youtu.be" in url:
            command.extend(["--no-playlist"])

        command.append(url)

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            logger.error(f"Ошибка при скачивании: {stderr}")
            return None

        downloaded_files = glob.glob(os.path.join(DOWNLOAD_PATH, "*.mp4"))
        if downloaded_files:
            return max(downloaded_files, key=os.path.getctime)
        return None
        
    except Exception as e:
        logger.exception("Непредвиденная ошибка при скачивании")
        return None

async def split_and_send_video(bot, chat_id, file_path, caption, max_size_mb=50):
    """Разделяет и отправляет видео по частям"""
    try:
        video = VideoFileClip(file_path)
        duration = video.duration
        video.close()
        
        file_size = os.path.getsize(file_path)
        
        if file_size <= max_size_mb * 1024 * 1024:
            with open(file_path, 'rb') as video_file:
                await bot.send_document(
                    chat_id,
                    types.InputFile(video_file),
                    caption=f"{caption}\nЧасть 1/1"
                )
            return True
            
        parts = math.ceil(file_size / (max_size_mb * 1024 * 1024))
        segment_duration = duration / parts
        
        temp_dir = os.path.join(DOWNLOAD_PATH, "temp_parts")
        os.makedirs(temp_dir, exist_ok=True)
        
        for i in range(parts):
            start_time = i * segment_duration
            end_time = min((i + 1) * segment_duration, duration)
            
            output_path = os.path.join(temp_dir, f"part_{i+1}.mp4")
            
            command = [
                FFMPEG_PATH,
                "-i", file_path,
                "-ss", str(start_time),
                "-t", str(end_time - start_time),
                "-c", "copy",
                output_path
            ]
            
            subprocess.run(command)
            
            with open(output_path, 'rb') as part_file:
                await bot.send_document(
                    chat_id,
                    types.InputFile(part_file),
                    caption=f"{caption}\nЧасть {i+1}/{parts}"
                )
            
            os.remove(output_path)
        
        os.rmdir(temp_dir)
        return True
        
    except Exception as e:
        logger.exception("Ошибка при разделении и отправке видео:")
        return False

async def is_subscribed(user_id: int) -> bool:
    """Проверяет, подписан ли пользователь на канал"""
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception:
        return False

@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    """Обработчик команд start и help"""
    if not await is_subscribed(message.from_user.id):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"))
        keyboard.add(InlineKeyboardButton("✅ Проверить подписку", callback_data="check_subscription"))
        await message.reply(
            "👋 Привет! Чтобы использовать бота, подпишитесь на наш канал и нажмите кнопку 'Проверить подписку'.",
            reply_markup=keyboard
        )
    else:
        await message.reply(
            "👋 Привет! Я помогу тебе скачать видео.\n\n"
            "🎥 Поддерживаемые платформы:\n"
            "• YouTube\n"
            "• Instagram (посты и reels)\n\n"
            "Просто отправь мне ссылку на видео!"
        )

@dp.callback_query_handler(lambda c: c.data == 'check_subscription')
async def handle_subscription_check(callback_query: types.CallbackQuery):
    """Обработчик проверки подписки"""
    user_id = callback_query.from_user.id
    if await is_subscribed(user_id):
        await callback_query.answer("✅ Отлично! Теперь вы можете пользоваться ботом!", show_alert=True)
        await bot.send_message(user_id, "📤 Отправьте мне ссылку на видео с YouTube или Instagram.")
    else:
        await callback_query.answer("❌ Вы не подписались на канал. Подпишитесь и попробуйте снова.", show_alert=True)

@dp.message_handler(content_types=['text'])
async def handle_link(message: types.Message):
    """Обработчик текстовых сообщений с ссылками"""
    if not await is_subscribed(message.from_user.id):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"))
        keyboard.add(InlineKeyboardButton("✅ Проверить подписку", callback_data="check_subscription"))
        await message.reply(
            "Чтобы использовать бота, подпишитесь на наш канал и нажмите 'Проверить подписку'.",
            reply_markup=keyboard
        )
        return

    url = message.text.strip()

    if not (url.startswith("http://") or url.startswith("https://")):
        await message.reply("❌ Пожалуйста, отправьте корректную ссылку.")
        return

    youtube_regex = r"(?:https?://)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v\/|e\/|watch\?v=))|youtu\.be\/)([a-zA-Z0-9_-]{11})"
    instagram_regex = r"(?:https?://)?(?:www\.)?instagram\.com/(?:p/|reel/|reels/)([A-Za-z0-9_-]+)"

    if re.match(youtube_regex, url) or re.match(instagram_regex, url):
        try:
            processing_message = await message.reply("🔍 Получаю информацию о видео...")
            
            short_id = generate_short_id(url)
            keyboard = InlineKeyboardMarkup(row_width=2)
            
            sizes = await get_video_info(url) or {
                '144p': 5 * 1024 * 1024,
                '360p': 15 * 1024 * 1024,
                '480p': 25 * 1024 * 1024,
                '720p': 50 * 1024 * 1024,
                'best': 100 * 1024 * 1024
            }
            
            buttons = []
            for quality, size in sizes.items():
                if size < 2 * 1024 * 1024 * 1024:  # меньше 2GB
                    size_mb = size / (1024 * 1024)
                    button_text = f"📱 {quality} ({size_mb:.1f}MB)"
                    if quality == 'best':
                        button_text = f"🎥 Макс. ({size_mb:.1f}MB)"
                    buttons.append(InlineKeyboardButton(
                        button_text,
                        callback_data=f"download_{short_id}_{quality}"
                    ))
            
            keyboard.add(*buttons)
            
            await processing_message.edit_text(
                "🎬 Выберите качество видео:",
                reply_markup=keyboard
            )
            
            await dp.storage.set_data(
                chat=message.chat.id,
                user=message.from_user.id,
                data={short_id: url}
            )
            
        except Exception as e:
            logger.exception("Ошибка при обработке ссылки:")
            await message.reply(
                "❌ Произошла ошибка при обработке ссылки. Пожалуйста, попробуйте позже."
            )
    else:
        await message.reply(
            "❌ Неподдерживаемая ссылка!\n\n"
            "Поддерживаемые форматы:\n"
            "• YouTube: youtube.com/watch?v=... или youtu.be/...\n"
            "• Instagram: instagram.com/p/... или instagram.com/reel/..."
        )

@dp.callback_query_handler(lambda c: c.data.startswith('download_'))
async def handle_download(callback_query: types.CallbackQuery):
    """Обработчик загрузки видео"""
    try:
        _, short_id, quality = callback_query.data.split("_")
        data = await dp.storage.get_data(chat=callback_query.message.chat.id, user=callback_query.from_user.id)
        url = data.get(short_id)

        if not url:
            await callback_query.answer("❌ Ссылка устарела. Отправьте её снова.", show_alert=True)
            return

        status_message = await bot.edit_message_text(
            "⏳ Загружаю видео... Пожалуйста, подождите.",
            callback_query.message.chat.id,
            callback_query.message.message_id
        )

        file_path = await download_media(url, quality)

        if file_path:
            try:
                await status_message.edit_text("📤 Отправляю видео...")
                
                file_size = os.path.getsize(file_path)
                is_youtube = 'youtube' in url or 'youtu.be' in url
                
                if file_size > 50 * 1024 * 1024:
                    await status_message.edit_text("📤 Разделяю и отправляю видео по частям...")
                    caption = f"🎥 Качество: {quality}\n🔗 Источник: {'YouTube' if is_youtube else 'Instagram'}"
                    success = await split_and_send_video(bot, callback_query.from_user.id, file_path, caption)
                    
                    if success:
                        await status_message.edit_text("✅ Видео успешно отправлено по частям!")
                    else:
                        await status_message.edit_text("❌ Ошибка при отправке видео по частям.")
                else:
                    with open(file_path, 'rb') as video:
                        await bot.send_video(
                            callback_query.from_user.id,
                            video,
                            caption=f"🎥 Качество: {quality}\n🔗 Источник: {'YouTube' if is_youtube else 'Instagram'}",
                            supports_streaming=True
                        )
                    await status_message.edit_text("✅ Видео успешно отправлено!")
                
                os.remove(file_path)
                
            except Exception as e:
                logger.exception("Ошибка при отправке видео:")
                error_msg = (
                    "❌ Ошибка при отправке. "
                    f"Размер файла: {file_size / (1024*1024):.1f} МБ\n"
                    "Попробуйте меньшее качество или другое видео."
                )
                await status_message.edit_text(error_msg)
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        else:
            await status_message.edit_text(
                "❌ Не удалось загрузить видео. Возможные причины:\n"
                "• Видео недоступно\n"
                "• Видео защищено\n"
                "• Ошибка при скачивании\n\n"
                "Попробуйте другое качество или видео."
            )
    except Exception as e:
        logger.exception("Ошибка обработки callback_query:")
        await bot.send_message(
            callback_query.from_user.id,
            "❌ Произошла ошибка. Попробуйте снова или выберите другое качество."
        )

if __name__ == '__main__':
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)