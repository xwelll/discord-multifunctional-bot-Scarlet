import discord
from discord.ext import commands, tasks
import yt_dlp as youtube_dl
import asyncio
from collections import deque
import os
import time
import re
import json
import random
import math
from datetime import datetime
import logging
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot_logs.txt', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Настройки для yt-dlp
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

# Определяем путь к FFmpeg - сначала проверяем локальный, затем системный
FFMPEG_LOCAL = os.path.join(os.getcwd(), 'ffmpeg', 'bin', 'ffmpeg.exe')
FFMPEG_PATH = FFMPEG_LOCAL if os.path.exists(FFMPEG_LOCAL) else 'ffmpeg'

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
    'executable': FFMPEG_PATH
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

# Список матерных слов
BAD_WORDS = [
    'блять', 'бля', 'сука', 'хуй', 'пизд', 'ебать', 'ебан', 'еба',
    'долбоёб', 'мудак', 'говно', 'хер', 'пидор', 'пидар', 'гандон',
    'fuck', 'shit', 'bitch', 'ass', 'dick', 'cock', 'pussy', 'cunt',
]

# Словари
user_warnings = {}
music_queues = {}
moderation_settings = {}
voice_time_tracker = {}

# Файлы данных
ECONOMY_FILE = 'economy.json'
SHOP_FILE = 'shop.json'
USERS_FILE = 'users.json'

# Настройки
DAILY_REWARD = 100
MESSAGE_REWARD = (1, 5)
WORK_REWARD = (50, 150)
WORK_COOLDOWN = 3600
DAILY_COOLDOWN = 86400
XP_PER_MESSAGE = (15, 25)
XP_COOLDOWN = 60
XP_PER_VOICE_MINUTE = 5

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

class MusicQueue:
    def __init__(self):
        self.queue = deque()
        self.current = None

    def add(self, song):
        self.queue.append(song)

    def next(self):
        if self.queue:
            self.current = self.queue.popleft()
            return self.current
        return None

    def clear(self):
        self.queue.clear()
        self.current = None

    def is_empty(self):
        return len(self.queue) == 0

# Функции работы с файлами
def load_economy():
    if os.path.exists(ECONOMY_FILE):
        with open(ECONOMY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_economy(data):
    with open(ECONOMY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_shop():
    if os.path.exists(SHOP_FILE):
        with open(SHOP_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_shop(data):
    with open(SHOP_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_users(data):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def calculate_level(xp):
    return math.floor(math.sqrt(xp / 100))

def xp_for_next_level(level):
    return ((level + 1) ** 2) * 100

def get_user_data(guild_id: str, user_id: str):
    users = load_users()
    
    if guild_id not in users:
        users[guild_id] = {}
    
    if user_id not in users[guild_id]:
        users[guild_id][user_id] = {
            'messages': 0,
            'voice_time': 0,
            'joins': 0,
            'first_join': None,
            'last_seen': None,
            'voice_joins': 0,
            'commands_used': 0,
            'reactions_added': 0,
            'xp': 0,
            'level': 0,
            'last_xp_time': 0
        }
        save_users(users)
    else:
        # Добавляем отсутствующие поля
        updated = False
        if 'xp' not in users[guild_id][user_id]:
            users[guild_id][user_id]['xp'] = 0
            updated = True
        if 'level' not in users[guild_id][user_id]:
            users[guild_id][user_id]['level'] = 0
            updated = True
        if 'last_xp_time' not in users[guild_id][user_id]:
            users[guild_id][user_id]['last_xp_time'] = 0
            updated = True
        if updated:
            save_users(users)
    
    return users[guild_id][user_id]

def update_user_data(guild_id: str, user_id: str, **kwargs):
    users = load_users()
    
    if guild_id not in users:
        users[guild_id] = {}
    
    if user_id not in users[guild_id]:
        get_user_data(guild_id, user_id)
        users = load_users()
    
    for key, value in kwargs.items():
        if key in users[guild_id][user_id]:
            if isinstance(value, (int, float)) and key not in ['first_join', 'last_seen', 'last_xp_time']:
                users[guild_id][user_id][key] += value
            else:
                users[guild_id][user_id][key] = value
    
    users[guild_id][user_id]['last_seen'] = datetime.now().isoformat()
    save_users(users)
    
    return users[guild_id][user_id]

def add_xp(guild_id: str, user_id: str, xp_amount: int):
    data = update_user_data(guild_id, user_id, xp=xp_amount)
    
    old_level = data['level']
    new_level = calculate_level(data['xp'])
    
    if new_level > old_level:
        update_user_data(guild_id, user_id, level=new_level - old_level)
        return True, new_level
    
    return False, new_level

def get_user_balance(user_id: str):
    economy = load_economy()
    if user_id not in economy:
        economy[user_id] = {
            'balance': 0,
            'last_daily': 0,
            'last_work': 0,
            'total_earned': 0,
            'total_spent': 0
        }
        save_economy(economy)
    return economy[user_id]

def update_balance(user_id: str, amount: int):
    economy = load_economy()
    if user_id not in economy:
        get_user_balance(user_id)
        economy = load_economy()
    
    economy[user_id]['balance'] += amount
    if amount > 0:
        economy[user_id]['total_earned'] += amount
    else:
        economy[user_id]['total_spent'] += abs(amount)
    
    save_economy(economy)
    return economy[user_id]['balance']

# Настройка бота
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    help_command=None
)

@bot.event
async def on_ready():
    print(f'✓ Бот {bot.user} запущен!')
    print(f'✓ ID: {bot.user.id}')
    print(f'✓ Серверов: {len(bot.guilds)}')
    
    # Проверяем FFmpeg
    if FFMPEG_PATH == 'ffmpeg':
        print(f'✓ Используется системный FFmpeg')
        logger.info(f'✓ Используется системный FFmpeg')
    elif os.path.exists(FFMPEG_LOCAL):
        print(f'✓ FFmpeg найден: {FFMPEG_LOCAL}')
        logger.info(f'✓ FFmpeg найден: {FFMPEG_LOCAL}')
    else:
        print(f'⚠️ FFmpeg не найден: {FFMPEG_LOCAL}')
        print(f'⚠️ Используется системный FFmpeg (если установлен)')
        logger.warning(f'⚠️ Локальный FFmpeg не найден, используется системный')
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="!help"
        )
    )
    
    update_voice_time.start()

@tasks.loop(minutes=1)
async def update_voice_time():
    for guild in bot.guilds:
        for member in guild.members:
            if member.voice and not member.bot:
                guild_id = str(guild.id)
                user_id = str(member.id)
                
                update_user_data(guild_id, user_id, voice_time=1)
                level_up, new_level = add_xp(guild_id, user_id, XP_PER_VOICE_MINUTE)
                
                if level_up:
                    try:
                        for channel in guild.text_channels:
                            if channel.permissions_for(guild.me).send_messages:
                                embed = discord.Embed(
                                    title="🎉 Повышение уровня!",
                                    description=f"{member.mention} достиг уровня **{new_level}**!",
                                    color=discord.Color.gold()
                                )
                                await channel.send(embed=embed, delete_after=10)
                                break
                    except:
                        pass

@bot.event
async def on_member_join(member):
    if member.bot:
        return
    
    guild_id = str(member.guild.id)
    user_id = str(member.id)
    
    data = get_user_data(guild_id, user_id)
    
    if data['first_join'] is None:
        update_user_data(guild_id, user_id, first_join=datetime.now().isoformat(), joins=1)
    else:
        update_user_data(guild_id, user_id, joins=1)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    
    guild_id = str(member.guild.id)
    user_id = str(member.id)
    
    if before.channel is None and after.channel is not None:
        update_user_data(guild_id, user_id, voice_joins=1)
        voice_time_tracker[user_id] = time.time()
    
    elif before.channel is not None and after.channel is None:
        if user_id in voice_time_tracker:
            session_time = int((time.time() - voice_time_tracker[user_id]) / 60)
            update_user_data(guild_id, user_id, voice_time=session_time)
            
            xp_earned = session_time * XP_PER_VOICE_MINUTE
            add_xp(guild_id, user_id, xp_earned)
            
            del voice_time_tracker[user_id]

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    
    if reaction.message.guild:
        guild_id = str(reaction.message.guild.id)
        user_id = str(user.id)
        update_user_data(guild_id, user_id, reactions_added=1)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Статистика
    if message.guild:
        guild_id = str(message.guild.id)
        user_id = str(message.author.id)
        
        data = get_user_data(guild_id, user_id)
        update_user_data(guild_id, user_id, messages=1)
        
        current_time = time.time()
        
        if current_time - data.get('last_xp_time', 0) >= XP_COOLDOWN:
            xp_earned = random.randint(*XP_PER_MESSAGE)
            level_up, new_level = add_xp(guild_id, user_id, xp_earned)
            
            update_user_data(guild_id, user_id, last_xp_time=current_time)
            
            if level_up:
                embed = discord.Embed(
                    title="🎉 Повышение уровня!",
                    description=f"{message.author.mention} достиг уровня **{new_level}**!",
                    color=discord.Color.gold()
                )
                
                reward = new_level * 50
                update_balance(user_id, reward)
                embed.add_field(name="Награда", value=f"🪙 {reward} монет", inline=False)
                
                await message.channel.send(embed=embed, delete_after=10)
    
    # Монеты
    if message.guild and random.randint(1, 10) == 1:
        user_id = str(message.author.id)
        coins = random.randint(*MESSAGE_REWARD)
        update_balance(user_id, coins)
    
    # Модерация
    guild_id = message.guild.id if message.guild else None
    if guild_id and moderation_settings.get(guild_id, False):
        content_lower = message.content.lower()
        
        for bad_word in BAD_WORDS:
            if re.search(r'\b' + re.escape(bad_word), content_lower):
                try:
                    await message.delete()
                    
                    user_id = message.author.id
                    if user_id not in user_warnings:
                        user_warnings[user_id] = []
                    
                    user_warnings[user_id].append(time.time())
                    warnings_count = len(user_warnings[user_id])
                    
                    await message.channel.send(
                        f"⚠️ {message.author.mention}, следите за языком! "
                        f"Предупреждение {warnings_count}/3",
                        delete_after=5
                    )
                    
                    if warnings_count >= 3:
                        try:
                            timeout_duration = discord.utils.utcnow() + discord.timedelta(minutes=10)
                            await message.author.timeout(timeout_duration, reason="3 предупреждения")
                            await message.channel.send(
                                f"🔇 {message.author.mention} получил тайм-аут на 10 минут!",
                                delete_after=10
                            )
                            user_warnings[user_id] = []
                        except:
                            pass
                except:
                    pass
                return
    
    await bot.process_commands(message)

@bot.event
async def on_command(ctx):
    if ctx.guild:
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        update_user_data(guild_id, user_id, commands_used=1)
        
        logger.info(f'✓ КОМАНДА ВЫПОЛНЕНА | Пользователь: {ctx.author} ({user_id}) | Сервер: {ctx.guild.name} | Команда: {ctx.command.name}')

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        logger.error(f'❌ КОМАНДА НЕ НАЙДЕНА | Пользователь: {ctx.author} ({ctx.author.id}) | Сервер: {ctx.guild.name if ctx.guild else "DM"} | Введено: {ctx.message.content}')
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        logger.error(f'❌ ОТСУТСТВУЮТ ПАРАМЕТРЫ | Пользователь: {ctx.author} ({ctx.author.id}) | Сервер: {ctx.guild.name if ctx.guild else "DM"} | Команда: {ctx.command.name} | Требуемый параметр: {error.param.name}')
        await ctx.send(f"❌ Не указаны параметры", delete_after=5)
    elif isinstance(error, commands.MissingPermissions):
        logger.warning(f'⚠️ НЕДОСТАТОЧНО ПРАВ | Пользователь: {ctx.author} ({ctx.author.id}) | Сервер: {ctx.guild.name if ctx.guild else "DM"} | Команда: {ctx.command.name} | Требуется: {error.missing_permissions}')
        await ctx.send(f"❌ Недостаточно прав!", delete_after=5)
    elif isinstance(error, commands.BotMissingPermissions):
        logger.error(f'❌ БОТ НЕ ИМЕЕТ ПРАВ | Сервер: {ctx.guild.name if ctx.guild else "DM"} | Команда: {ctx.command.name} | Требуется: {error.missing_permissions}')
        await ctx.send(f"❌ У бота недостаточно прав!", delete_after=5)
    elif isinstance(error, commands.BadArgument):
        logger.error(f'❌ НЕВЕРНЫЙ АРГУМЕНТ | Пользователь: {ctx.author} ({ctx.author.id}) | Команда: {ctx.command.name} | Ошибка: {str(error)}')
        await ctx.send(f"❌ Неверный формат аргумента!", delete_after=5)
    else:
        logger.error(f'❌ НЕПРЕДВИДЕННАЯ ОШИБКА | Пользователь: {ctx.author} ({ctx.author.id}) | Сервер: {ctx.guild.name if ctx.guild else "DM"} | Команда: {ctx.command.name if ctx.command else "N/A"} | Ошибка: {type(error).__name__}: {str(error)}')

# ==================== УРОВНИ ====================

@bot.command(name='level', aliases=['lvl', 'уровень'])
async def level(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author
    
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    
    data = get_user_data(guild_id, user_id)
    
    current_level = calculate_level(data['xp'])
    current_xp = data['xp']
    xp_needed = xp_for_next_level(current_level)
    xp_progress = current_xp - (current_level ** 2 * 100)
    xp_for_level = xp_needed - (current_level ** 2 * 100)
    
    progress_percent = int((xp_progress / xp_for_level) * 100) if xp_for_level > 0 else 0
    progress_bar_length = 20
    filled = int(progress_bar_length * progress_percent / 100)
    bar = "█" * filled + "░" * (progress_bar_length - filled)
    
    embed = discord.Embed(
        title=f"⭐ Уровень {member.display_name}",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    
    embed.add_field(name="Уровень", value=f"**{current_level}**", inline=True)
    embed.add_field(name="Опыт", value=f"**{current_xp}** XP", inline=True)
    embed.add_field(name="Прогресс", value=f"{progress_percent}%", inline=True)
    embed.add_field(
        name="До следующего уровня",
        value=f"`{bar}`\n{xp_progress}/{xp_for_level} XP",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name='rank', aliases=['ранг'])
async def rank(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author
    
    guild_id = str(ctx.guild.id)
    users = load_users()
    
    if guild_id not in users:
        await ctx.send("❌ Нет данных!")
        return
    
    sorted_users = sorted(users[guild_id].items(), key=lambda x: x[1]['xp'], reverse=True)
    
    rank = 0
    for idx, (uid, data) in enumerate(sorted_users, 1):
        if uid == str(member.id):
            rank = idx
            break
    
    if rank == 0:
        await ctx.send("❌ Не найден!")
        return
    
    data = get_user_data(guild_id, str(member.id))
    level = calculate_level(data['xp'])
    
    embed = discord.Embed(
        title=f"🏆 Ранг {member.display_name}",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    
    embed.add_field(name="Место", value=f"**#{rank}**", inline=True)
    embed.add_field(name="Уровень", value=f"**{level}**", inline=True)
    embed.add_field(name="Опыт", value=f"**{data['xp']}** XP", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='leaderboard', aliases=['lb', 'топ', 'лидеры'])
async def leaderboard(ctx, category: str = "xp"):
    guild_id = str(ctx.guild.id)
    
    if category.lower() in ['xp', 'level', 'уровень']:
        users = load_users()
        
        if guild_id not in users or not users[guild_id]:
            await ctx.send("❌ Нет данных!")
            return
        
        sorted_users = sorted(users[guild_id].items(), key=lambda x: x[1]['xp'], reverse=True)[:10]
        
        embed = discord.Embed(
            title="🏆 Топ-10 по уровням",
            color=discord.Color.gold()
        )
        
        medals = ["🥇", "🥈", "🥉"]
        
        for idx, (user_id, data) in enumerate(sorted_users, 1):
            try:
                member = await ctx.guild.fetch_member(int(user_id))
                medal = medals[idx-1] if idx <= 3 else f"{idx}."
                level = calculate_level(data['xp'])
                embed.add_field(
                    name=f"{medal} {member.display_name}",
                    value=f"⭐ Уровень {level} | 💎 {data['xp']} XP",
                    inline=False
                )
            except:
                pass
        
        await ctx.send(embed=embed)
    
    elif category.lower() in ['money', 'монеты']:
        economy = load_economy()
        
        sorted_users = sorted(economy.items(), key=lambda x: x[1]['balance'], reverse=True)[:10]
        
        if not sorted_users:
            await ctx.send("❌ Пусто!")
            return
        
        embed = discord.Embed(
            title="🏆 Топ-10 богатых",
            color=discord.Color.gold()
        )
        
        medals = ["🥇", "🥈", "🥉"]
        
        for idx, (user_id, data) in enumerate(sorted_users, 1):
            try:
                user = await bot.fetch_user(int(user_id))
                medal = medals[idx-1] if idx <= 3 else f"{idx}."
                embed.add_field(
                    name=f"{medal} {user.display_name}",
                    value=f"🪙 {data['balance']}",
                    inline=False
                )
            except:
                pass
        
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Используйте: `!lb xp` или `!lb money`")

# ==================== СТАТИСТИКА ====================

@bot.command(name='stats', aliases=['статистика', 'профиль'])
async def stats(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author
    
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    
    data = get_user_data(guild_id, user_id)
    level = calculate_level(data['xp'])
    
    hours = data['voice_time'] // 60
    minutes = data['voice_time'] % 60
    
    if data['first_join']:
        first_join = datetime.fromisoformat(data['first_join'])
        days_on_server = (datetime.now() - first_join).days
    else:
        days_on_server = 0
    
    embed = discord.Embed(
        title=f"📊 Профиль {member.display_name}",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    
    embed.add_field(name="⭐ Уровень", value=level, inline=True)
    embed.add_field(name="💎 XP", value=data['xp'], inline=True)
    embed.add_field(name="💬 Сообщений", value=data['messages'], inline=True)
    embed.add_field(name="🎤 Войс", value=f"{hours}ч {minutes}м", inline=True)
    embed.add_field(name="🎮 Подключений", value=data['voice_joins'], inline=True)
    embed.add_field(name="⚡ Команд", value=data['commands_used'], inline=True)
    embed.add_field(name="😄 Реакций", value=data['reactions_added'], inline=True)
    embed.add_field(name="📅 Дней на сервере", value=days_on_server, inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='oldest', aliases=['старейший', 'самыйстарый'])
async def oldest(ctx):
    guild_id = str(ctx.guild.id)
    users = load_users()
    
    if guild_id not in users or not users[guild_id]:
        await ctx.send("❌ Нет данных!")
        return
    
    oldest_user = None
    oldest_date = None
    
    for user_id, data in users[guild_id].items():
        if data['first_join']:
            join_date = datetime.fromisoformat(data['first_join'])
            if oldest_date is None or join_date < oldest_date:
                oldest_date = join_date
                oldest_user = user_id
    
    if oldest_user is None:
        await ctx.send("❌ Не найдено!")
        return
    
    try:
        member = await ctx.guild.fetch_member(int(oldest_user))
        days = (datetime.now() - oldest_date).days
        
        embed = discord.Embed(
            title="👴 Старейший участник",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Пользователь", value=member.mention, inline=False)
        embed.add_field(name="Дата", value=oldest_date.strftime("%d.%m.%Y"), inline=True)
        embed.add_field(name="Дней", value=f"{days}", inline=True)
        
        await ctx.send(embed=embed)
    except:
        await ctx.send("❌ Ошибка!")

@bot.command(name='mostactive', aliases=['самыйактивный', 'топактивность'])
async def mostactive(ctx):
    guild_id = str(ctx.guild.id)
    users = load_users()
    
    if guild_id not in users or not users[guild_id]:
        await ctx.send("❌ Нет данных!")
        return
    
    sorted_users = sorted(users[guild_id].items(), key=lambda x: x[1]['messages'], reverse=True)
    
    if not sorted_users:
        await ctx.send("❌ Нет данных!")
        return
    
    user_id, data = sorted_users[0]
    
    try:
        member = await ctx.guild.fetch_member(int(user_id))
        
        embed = discord.Embed(
            title="⚡ Самый активный",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Пользователь", value=member.mention, inline=False)
        embed.add_field(name="💬 Сообщений", value=data['messages'], inline=True)
        embed.add_field(name="⚡ Команд", value=data['commands_used'], inline=True)
        
        await ctx.send(embed=embed)
    except:
        await ctx.send("❌ Ошибка!")

@bot.command(name='voiceleader', aliases=['лидерпоголосу', 'топголос'])
async def voiceleader(ctx):
    guild_id = str(ctx.guild.id)
    users = load_users()
    
    if guild_id not in users or not users[guild_id]:
        await ctx.send("❌ Нет данных!")
        return
    
    sorted_users = sorted(users[guild_id].items(), key=lambda x: x[1]['voice_time'], reverse=True)
    
    if not sorted_users or sorted_users[0][1]['voice_time'] == 0:
        await ctx.send("❌ Нет данных!")
        return
    
    user_id, data = sorted_users[0]
    
    try:
        member = await ctx.guild.fetch_member(int(user_id))
        
        hours = data['voice_time'] // 60
        minutes = data['voice_time'] % 60
        
        embed = discord.Embed(
            title="🎤 Лидер по времени в войсе",
            color=discord.Color.purple()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Пользователь", value=member.mention, inline=False)
        embed.add_field(name="⏱️ Время", value=f"{hours}ч {minutes}м", inline=True)
        embed.add_field(name="🎮 Подключений", value=data['voice_joins'], inline=True)
        
        await ctx.send(embed=embed)
    except:
        await ctx.send("❌ Ошибка!")

@bot.command(name='topmessages', aliases=['топсообщения', 'топактивные'])
async def topmessages(ctx):
    guild_id = str(ctx.guild.id)
    users = load_users()
    
    if guild_id not in users or not users[guild_id]:
        await ctx.send("❌ Нет данных!")
        return
    
    sorted_users = sorted(users[guild_id].items(), key=lambda x: x[1]['messages'], reverse=True)[:10]
    
    if not sorted_users:
        await ctx.send("❌ Нет данных!")
        return
    
    embed = discord.Embed(
        title="💬 Топ-10 по сообщениям",
        color=discord.Color.blue()
    )
    
    medals = ["🥇", "🥈", "🥉"]
    
    for idx, (user_id, data) in enumerate(sorted_users, 1):
        try:
            member = await ctx.guild.fetch_member(int(user_id))
            medal = medals[idx-1] if idx <= 3 else f"{idx}."
            embed.add_field(
                name=f"{medal} {member.display_name}",
                value=f"💬 {data['messages']}",
                inline=False
            )
        except:
            pass
    
    await ctx.send(embed=embed)

@bot.command(name='serverinfo', aliases=['инфосервера', 'сервер'])
async def serverinfo(ctx):
    guild = ctx.guild
    guild_id = str(guild.id)
    users_data = load_users()
    
    total_messages = 0
    total_voice_time = 0
    total_commands = 0
    
    if guild_id in users_data:
        for data in users_data[guild_id].values():
            total_messages += data['messages']
            total_voice_time += data['voice_time']
            total_commands += data['commands_used']
    
    hours = total_voice_time // 60
    
    embed = discord.Embed(
        title=f"ℹ️ {guild.name}",
        color=discord.Color.blue()
    )
    
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    
    embed.add_field(name="👥 Участников", value=guild.member_count, inline=True)
    embed.add_field(name="💬 Сообщений", value=total_messages, inline=True)
    embed.add_field(name="⚡ Команд", value=total_commands, inline=True)
    embed.add_field(name="🎤 Часов в войсе", value=f"{hours}ч", inline=True)
    embed.add_field(name="📅 Создан", value=guild.created_at.strftime("%d.%m.%Y"), inline=True)
    embed.add_field(name="👑 Владелец", value=guild.owner.mention, inline=True)
    
    await ctx.send(embed=embed)

# ==================== ЭКОНОМИКА ====================

@bot.command(name='balance', aliases=['bal', 'баланс', 'б'])
async def balance(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author
    
    user_id = str(member.id)
    data = get_user_balance(user_id)
    
    embed = discord.Embed(
        title=f"💰 Баланс {member.display_name}",
        color=discord.Color.gold()
    )
    embed.add_field(name="Монеты", value=f"🪙 **{data['balance']}**", inline=False)
    embed.add_field(name="Заработано", value=f"📈 {data['total_earned']}", inline=True)
    embed.add_field(name="Потрачено", value=f"📉 {data['total_spent']}", inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    await ctx.send(embed=embed)

@bot.command(name='daily', aliases=['ежедневка'])
async def daily(ctx):
    user_id = str(ctx.author.id)
    data = get_user_balance(user_id)
    
    current_time = time.time()
    last_daily = data['last_daily']
    
    if current_time - last_daily < DAILY_COOLDOWN:
        remaining = DAILY_COOLDOWN - (current_time - last_daily)
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        await ctx.send(f"⏰ Через {hours}ч {minutes}м")
        return
    
    economy = load_economy()
    economy[user_id]['last_daily'] = current_time
    save_economy(economy)
    
    new_balance = update_balance(user_id, DAILY_REWARD)
    
    embed = discord.Embed(
        title="🎁 Ежедневная награда",
        description=f"Получено **{DAILY_REWARD}** 🪙!",
        color=discord.Color.green()
    )
    embed.add_field(name="Баланс", value=f"🪙 {new_balance}", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='work', aliases=['работа'])
async def work(ctx):
    user_id = str(ctx.author.id)
    data = get_user_balance(user_id)
    
    current_time = time.time()
    last_work = data['last_work']
    
    if current_time - last_work < WORK_COOLDOWN:
        remaining = WORK_COOLDOWN - (current_time - last_work)
        minutes = int(remaining // 60)
        logger.warning(f'⏰ КУЛДАУН РАБОТЫ | Пользователь: {ctx.author} ({user_id}) | Осталось: {minutes} мин')
        await ctx.send(f"⏰ Отдохните {minutes} мин")
        return
    
    jobs = ["доставили пиццу", "помыли машину", "написали код", "выгуляли собаку"]
    job = random.choice(jobs)
    earned = random.randint(*WORK_REWARD)
    
    economy = load_economy()
    economy[user_id]['last_work'] = current_time
    save_economy(economy)
    
    new_balance = update_balance(user_id, earned)
    logger.info(f'💼 РАБОТА | Пользователь: {ctx.author} ({user_id}) | Работа: {job} | Заработок: {earned} 🪙 | Баланс: {new_balance}')
    
    embed = discord.Embed(
        title="💼 Работа",
        description=f"Вы {job} и заработали **{earned}** 🪙!",
        color=discord.Color.blue()
    )
    embed.add_field(name="Баланс", value=f"🪙 {new_balance}", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='give', aliases=['передать'])
async def give(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        await ctx.send("❌ Сумма > 0!")
        return
    
    if member.bot or member == ctx.author:
        await ctx.send("❌ Нельзя!")
        return
    
    sender_id = str(ctx.author.id)
    receiver_id = str(member.id)
    
    sender_data = get_user_balance(sender_id)
    
    if sender_data['balance'] < amount:
        await ctx.send(f"❌ Недостаточно! У вас: {sender_data['balance']} 🪙")
        return
    
    update_balance(sender_id, -amount)
    update_balance(receiver_id, amount)
    
    await ctx.send(f"✅ Передано {member.mention} **{amount}** 🪙!")

# ==================== МАГАЗИН ====================

@bot.command(name='shop', aliases=['магазин'])
async def shop(ctx):
    guild_id = str(ctx.guild.id)
    shop_data = load_shop()
    
    if guild_id not in shop_data or not shop_data[guild_id]:
        await ctx.send("🛒 Магазин пуст!")
        return
    
    embed = discord.Embed(
        title="🛒 Магазин ролей",
        description="`!buy <номер>`",
        color=discord.Color.purple()
    )
    
    for idx, item in enumerate(shop_data[guild_id], 1):
        role = ctx.guild.get_role(int(item['role_id']))
        if role:
            embed.add_field(
                name=f"{idx}. {role.name}",
                value=f"💰 {item['price']} 🪙\n📝 {item.get('description', '')}",
                inline=False
            )
    
    await ctx.send(embed=embed)

@bot.command(name='addshop', aliases=['добавитьвмагазин'])
@commands.has_permissions(administrator=True)
async def addshop(ctx, role: discord.Role, price: int, *, description: str = ""):
    if price <= 0:
        await ctx.send("❌ Цена > 0!")
        return
    
    guild_id = str(ctx.guild.id)
    shop_data = load_shop()
    
    if guild_id not in shop_data:
        shop_data[guild_id] = []
    
    shop_data[guild_id].append({
        'role_id': str(role.id),
        'price': price,
        'description': description
    })
    
    save_shop(shop_data)
    await ctx.send(f"✅ Роль {role.mention} добавлена за {price} 🪙!")

@bot.command(name='removeshop', aliases=['удалитьизмагазина'])
@commands.has_permissions(administrator=True)
async def removeshop(ctx, role: discord.Role):
    guild_id = str(ctx.guild.id)
    shop_data = load_shop()
    
    if guild_id not in shop_data:
        await ctx.send("❌ Пусто!")
        return
    
    for idx, item in enumerate(shop_data[guild_id]):
        if item['role_id'] == str(role.id):
            shop_data[guild_id].pop(idx)
            save_shop(shop_data)
            await ctx.send(f"✅ Удалено!")
            return
    
    await ctx.send(f"❌ Не найдено!")

@bot.command(name='buy', aliases=['купить'])
async def buy(ctx, item_number: int):
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)
    
    shop_data = load_shop()
    
    if guild_id not in shop_data or not shop_data[guild_id]:
        logger.warning(f'🛒 ПОПЫТКА ПОКУПКИ | Пользователь: {ctx.author} ({user_id}) | Магазин пуст')
        await ctx.send("❌ Пусто!")
        return
    
    if item_number < 1 or item_number > len(shop_data[guild_id]):
        logger.warning(f'🛒 НЕВЕРНЫЙ НОМЕР | Пользователь: {ctx.author} ({user_id}) | Номер: {item_number}')
        await ctx.send(f"❌ Неверный номер!")
        return
    
    item = shop_data[guild_id][item_number - 1]
    role = ctx.guild.get_role(int(item['role_id']))
    
    if not role:
        logger.error(f'🛒 РОЛЬ НЕ НАЙДЕНА | Пользователь: {ctx.author} ({user_id}) | Товар #{item_number}')
        await ctx.send("❌ Роль не найдена!")
        return
    
    if role in ctx.author.roles:
        logger.warning(f'🛒 УЖЕ ЕСТЬ РОЛЬ | Пользователь: {ctx.author} ({user_id}) | Роль: {role.name}')
        await ctx.send(f"❌ Уже есть!")
        return
    
    user_data = get_user_balance(user_id)
    
    if user_data['balance'] < item['price']:
        logger.warning(f'🛒 НЕДОСТАТОЧНО ДЕНЕГ | Пользователь: {ctx.author} ({user_id}) | Имеет: {user_data["balance"]} | Нужно: {item["price"]}')
        await ctx.send(f"❌ Недостаточно! Нужно: {item['price']} 🪙")
        return
    
    try:
        await ctx.author.add_roles(role)
        update_balance(user_id, -item['price'])
        logger.info(f'🛒 УСПЕШНАЯ ПОКУПКА | Пользователь: {ctx.author} ({user_id}) | Товар: {role.name} | Цена: {item["price"]} 🪙')
        await ctx.send(f"✅ Куплено {role.mention}!")
    except Exception as e:
        logger.error(f'❌ ОШИБКА ПОКУПКИ | Пользователь: {ctx.author} ({user_id}) | Ошибка: {str(e)}')
        await ctx.send("❌ Ошибка!")

# ==================== МОДЕРАЦИЯ ====================

@bot.command(name='moderation', aliases=['automod', 'автомод'])
@commands.has_permissions(manage_messages=True)
async def moderation(ctx, action: str = None):
    guild_id = ctx.guild.id
    
    if action is None:
        status = "✅ включена" if moderation_settings.get(guild_id, False) else "❌ выключена"
        await ctx.send(f"🛡️ Автомодерация: {status}")
        return
    
    if action.lower() in ['on', 'вкл']:
        moderation_settings[guild_id] = True
        await ctx.send("✅ Включена!")
    elif action.lower() in ['off', 'выкл']:
        moderation_settings[guild_id] = False
        await ctx.send("✅ Выключена!")

@bot.command(name='warnings', aliases=['предупреждения'])
@commands.has_permissions(manage_messages=True)
async def warnings(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author
    
    user_id = member.id
    warns = len(user_warnings.get(user_id, []))
    
    await ctx.send(f"⚠️ У {member.mention} **{warns}/3** предупреждений")

@bot.command(name='clearwarnings', aliases=['очиститьпредупреждения'])
@commands.has_permissions(manage_messages=True)
async def clearwarnings(ctx, member: discord.Member):
    user_id = member.id
    if user_id in user_warnings:
        del user_warnings[user_id]
    await ctx.send(f"✅ Очищено!")

@bot.command(name='timeout', aliases=['мут', 'тайм-аут'])
@commands.has_permissions(moderate_members=True)
async def timeout_cmd(ctx, member: discord.Member, minutes: int, *, reason: str = "Не указана"):
    try:
        timeout_duration = discord.utils.utcnow() + discord.timedelta(minutes=minutes)
        await member.timeout(timeout_duration, reason=reason)
        logger.info(f'🔇 ТАЙМ-АУТ ВЫДАН | Модератор: {ctx.author} ({ctx.author.id}) | Пользователь: {member} ({member.id}) | Время: {minutes} мин | Причина: {reason}')
        await ctx.send(f"✅ {member.mention} в тайм-ауте на {minutes} мин!")
    except Exception as e:
        logger.error(f'❌ ОШИБКА TIMEOUT | Модератор: {ctx.author} ({ctx.author.id}) | Пользователь: {member} ({member.id}) | Ошибка: {str(e)}')
        await ctx.send("❌ Ошибка!")

@bot.command(name='untimeout', aliases=['размут', 'снятьтаймаут'])
@commands.has_permissions(moderate_members=True)
async def untimeout(ctx, member: discord.Member):
    try:
        await member.timeout(None)
        logger.info(f'✅ ТАЙМ-АУТ СНЯТ | Модератор: {ctx.author} ({ctx.author.id}) | Пользователь: {member} ({member.id})')
        await ctx.send(f"✅ Тайм-аут снят с {member.mention}!")
    except Exception as e:
        logger.error(f'❌ ОШИБКА UNTIMEOUT | Модератор: {ctx.author} ({ctx.author.id}) | Пользователь: {member} ({member.id}) | Ошибка: {str(e)}')
        await ctx.send("❌ Ошибка!")

@bot.command(name='clear', aliases=['purge', 'очистить'])
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 10):
    try:
        deleted = await ctx.channel.purge(limit=amount + 1)
        logger.info(f'🗑️ ОЧИСТКА ЧАТА | Модератор: {ctx.author} ({ctx.author.id}) | Канал: {ctx.channel.name} | Удалено сообщений: {len(deleted) - 1}')
        msg = await ctx.send(f"✅ Удалено **{len(deleted) - 1}**")
        await asyncio.sleep(3)
        await msg.delete()
    except Exception as e:
        logger.error(f'❌ ОШИБКА CLEAR | Модератор: {ctx.author} ({ctx.author.id}) | Канал: {ctx.channel.name} | Ошибка: {str(e)}')
        await ctx.send("❌ Ошибка!")

# ==================== МУЗЫКА ====================

@bot.command(name='join', aliases=['j', 'подключиться'])
async def join(ctx):
    if not ctx.author.voice:
        logger.warning(f'🎵 БОТ НЕ В ВОЙСЕ | Пользователь: {ctx.author} ({ctx.author.id}) | Сервер: {ctx.guild.name}')
        await ctx.send("❌ Подключитесь к войсу!")
        return
    
    channel = ctx.author.voice.channel
    
    if ctx.voice_client:
        await ctx.voice_client.move_to(channel)
    else:
        await channel.connect()
    
    logger.info(f'🎵 БОТ ПОДКЛЮЧЕН | Пользователь: {ctx.author} ({ctx.author.id}) | Канал: {channel.name} | Сервер: {ctx.guild.name}')
    await ctx.send(f"✓ Подключился к **{channel}**")

@bot.command(name='leave', aliases=['l', 'disconnect', 'отключиться'])
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        if ctx.guild.id in music_queues:
            music_queues[ctx.guild.id].clear()
        logger.info(f'🎵 БОТ ОТКЛЮЧЕН | Пользователь: {ctx.author} ({ctx.author.id}) | Сервер: {ctx.guild.name}')
        await ctx.send("✓ Отключился")
    else:
        logger.warning(f'🎵 БОТ НЕ ПОДКЛЮЧЕН | Пользователь: {ctx.author} ({ctx.author.id}) | Сервер: {ctx.guild.name}')
        await ctx.send("❌ Не подключен!")

@bot.command(name='play', aliases=['p', 'играть'])
async def play(ctx, *, url):
    if not ctx.author.voice:
        logger.warning(f'🎵 PLAY БЕЗ ВОЙСА | Пользователь: {ctx.author} ({ctx.author.id}) | URL: {url}')
        await ctx.send("❌ Подключитесь к войсу!")
        return

    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()

    if ctx.guild.id not in music_queues:
        music_queues[ctx.guild.id] = MusicQueue()

    async with ctx.typing():
        try:
            logger.info(f'🎵 ПОПЫТКА ЗАГРУЗИТЬ | Пользователь: {ctx.author} ({ctx.author.id}) | URL: {url}')
            player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
            music_queues[ctx.guild.id].add(player)
            
            logger.info(f'🎵 ТРЕК ЗАГРУЖЕН | Пользователь: {ctx.author} ({ctx.author.id}) | Трек: {player.title}')
            if not ctx.voice_client.is_playing():
                await play_next(ctx)
            else:
                await ctx.send(f'✓ Добавлено: **{player.title}**')
        except Exception as e:
            logger.error(f'❌ ОШИБКА ЗАГРУЗКИ | Пользователь: {ctx.author} ({ctx.author.id}) | URL: {url} | Ошибка: {str(e)}')
            await ctx.send(f"❌ Ошибка! Проверьте ссылку или убедитесь, что FFmpeg установлен.")

async def play_next(ctx):
    voice_client = ctx.voice_client
    queue = music_queues.get(ctx.guild.id)
    
    if queue and not queue.is_empty():
        player = queue.next()
        
        def after_playing(error):
            if error:
                logger.error(f'❌ ОШИБКА ВОСПРОИЗВЕДЕНИЯ | Гильдия: {ctx.guild.name} | Ошибка: {str(error)}')
            coro = play_next(ctx)
            asyncio.run_coroutine_threadsafe(coro, bot.loop)
        
        try:
            voice_client.play(player, after=after_playing)
            logger.info(f'🎵 ВОСПРОИЗВЕДЕНИЕ | Гильдия: {ctx.guild.name} | Трек: {player.title}')
            await ctx.send(f'🎵 **{player.title}**')
        except Exception as e:
            logger.error(f'❌ ОШИБКА PLAY | Гильдия: {ctx.guild.name} | Ошибка: {str(e)}')

@bot.command(name='pause', aliases=['пауза'])
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        logger.info(f'🎵 ПАУЗА | Пользователь: {ctx.author} ({ctx.author.id}) | Сервер: {ctx.guild.name}')
        await ctx.send("⏸ Пауза")

@bot.command(name='resume', aliases=['продолжить'])
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        logger.info(f'🎵 ВОСПРОИЗВЕДЕНИЕ | Пользователь: {ctx.author} ({ctx.author.id}) | Сервер: {ctx.guild.name}')
        await ctx.send("▶ Продолжаю")

@bot.command(name='stop', aliases=['стоп'])
async def stop(ctx):
    if ctx.voice_client:
        ctx.voice_client.stop()
        if ctx.guild.id in music_queues:
            music_queues[ctx.guild.id].clear()
        logger.info(f'🎵 ОСТАНОВКА | Пользователь: {ctx.author} ({ctx.author.id}) | Сервер: {ctx.guild.name}')
        await ctx.send("⏹ Остановлено")

@bot.command(name='skip', aliases=['s', 'пропустить'])
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        logger.info(f'🎵 ПРОПУСК | Пользователь: {ctx.author} ({ctx.author.id}) | Сервер: {ctx.guild.name}')
        await ctx.send("⏭ Пропущено")

@bot.command(name='queue', aliases=['q', 'очередь'])
async def queue_cmd(ctx):
    if ctx.guild.id not in music_queues:
        await ctx.send("📝 Очередь пуста")
        return
    
    queue = music_queues[ctx.guild.id]
    if queue.is_empty():
        await ctx.send("📝 Очередь пуста")
    else:
        queue_list = "\n".join([f"{i+1}. {song.title}" for i, song in enumerate(list(queue.queue))])
        await ctx.send(f"📝 **Очередь:**\n{queue_list}")

@bot.command(name='volume', aliases=['v', 'громкость'])
async def volume(ctx, volume: int):
    if not ctx.voice_client:
        await ctx.send("❌ Не подключен!")
        return
    
    if 0 <= volume <= 100:
        if ctx.voice_client.source:
            ctx.voice_client.source.volume = volume / 100
        await ctx.send(f"🔊 Громкость: {volume}%")

# ==================== УТИЛИТЫ ====================

@bot.command(name='ping', aliases=['пинг'])
async def ping(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Понг! **{latency}мс**")

@bot.command(name='uptime', aliases=['аптайм'])
async def uptime(ctx):
    if hasattr(bot, 'start_time'):
        uptime_seconds = int(time.time() - bot.start_time)
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        await ctx.send(f"⏱️ Работает: **{days}д {hours}ч {minutes}м**")

@bot.command(name='help', aliases=['помощь'])
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🤖 Все команды",
        color=discord.Color.purple()
    )
    
    embed.add_field(
        name="⭐ Уровни",
        value="`!level` `!rank` `!lb xp`",
        inline=False
    )
    
    embed.add_field(
        name="📊 Статистика",
        value="`!stats` `!oldest` `!mostactive` `!voiceleader` `!topmessages` `!serverinfo`",
        inline=False
    )
    
    embed.add_field(
        name="💰 Экономика",
        value="`!balance` `!daily` `!work` `!give` `!lb money`",
        inline=False
    )
    
    embed.add_field(
        name="🛒 Магазин",
        value="`!shop` `!buy` `!addshop` `!removeshop` 🔒",
        inline=False
    )
    
    embed.add_field(
        name="🎵 Музыка",
        value="`!play` `!join` `!leave` `!pause` `!resume` `!stop` `!skip` `!queue` `!volume`",
        inline=False
    )
    
    embed.add_field(
        name="🛡️ Модерация",
        value="`!moderation` `!warnings` `!clearwarnings` `!timeout` `!untimeout` `!clear` 🔒",
        inline=False
    )
    
    embed.add_field(
        name="🛠️ Утилиты",
        value="`!ping` `!uptime` `!help`",
        inline=False
    )
    
    embed.set_footer(text="🔒 - требует прав модератора/администратора")
    
    await ctx.send(embed=embed)

# Админ команды
@bot.command(name='givexp', hidden=True)
@commands.has_permissions(administrator=True)
async def givexp(ctx, member: discord.Member, amount: int):
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    
    level_up, new_level = add_xp(guild_id, user_id, amount)
    
    if level_up:
        await ctx.send(f"✅ +{amount} XP. Уровень: **{new_level}**!")
    else:
        await ctx.send(f"✅ +{amount} XP")

@bot.command(name='addmoney', aliases=['добавитьденьги'], hidden=True)
@commands.has_permissions(administrator=True)
async def addmoney(ctx, member: discord.Member, amount: int):
    user_id = str(member.id)
    new_balance = update_balance(user_id, amount)
    await ctx.send(f"✅ +{amount} 🪙. Баланс: {new_balance}")

@bot.command(name='removemoney', aliases=['удалитьденьги'], hidden=True)
@commands.has_permissions(administrator=True)
async def removemoney(ctx, member: discord.Member, amount: int):
    user_id = str(member.id)
    new_balance = update_balance(user_id, -amount)
    await ctx.send(f"✅ -{amount} 🪙. Баланс: {new_balance}")

@bot.command(name='resetbalance', aliases=['сброситьбаланс'], hidden=True)
@commands.has_permissions(administrator=True)
async def resetbalance(ctx, member: discord.Member):
    user_id = str(member.id)
    economy = load_economy()
    if user_id in economy:
        economy[user_id] = {
            'balance': 0,
            'last_daily': 0,
            'last_work': 0,
            'total_earned': 0,
            'total_spent': 0
        }
        save_economy(economy)
    await ctx.send(f"✅ Баланс {member.mention} сброшен!")

bot.start_time = time.time()

# Запуск
if __name__ == '__main__':
    # Получаем токен из переменных окружения
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    
    if not TOKEN:
        logger.error('❌ DISCORD_BOT_TOKEN не найден! Добавьте его в переменные окружения или в файл .env')
        print('❌ ОШИБКА: DISCORD_BOT_TOKEN не найден!')
        print('Пожалуйста, установите DISCORD_BOT_TOKEN в:')
        print('  1. Переменные окружения системы, или')
        print('  2. Файл .env в корне проекта')
        exit(1)
    
    try:
        logger.info('✓ Запуск бота...')
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f'❌ Ошибка запуска бота: {e}')
        print(f"❌ Ошибка: {e}")