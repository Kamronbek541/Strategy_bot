import os
import json
import re
import asyncio
import pandas as pd
import requests
import concurrent.futures
import time
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler, CallbackQueryHandler)
from telegram.constants import ParseMode
from telegram.ext import JobQueue
from telegram import InputMediaPhoto
from database import * 
from database import set_copytrading_status 
from database import check_analysis_limit
from chart_analyzer import find_candlesticks, candlesticks_to_ohlc
from core_analyzer import fetch_data, compute_features, generate_decisive_signal, generate_signal
from llm_explainer import get_explanation
import ccxt
from binance.um_futures import UMFutures
from exchange_utils import fetch_exchange_balance_safe

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY")
WALLET_ADDRESS = os.getenv("YOUR_WALLET_ADDRESS")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID")) 
PAYMENT_AMOUNT = 49
# PAYMENT_AMOUNT = 1.5
USDT_CONTRACT_ADDRESS = "0x55d398326f99059fF775485246999027B3197955"
ASK_PROMO_COUNT, ASK_PROMO_DURATION = range(2)
ASK_BROADCAST_MESSAGE, CONFIRM_BROADCAST = range(9, 11)


ASK_AMOUNT, ASK_WALLET = range(2)  
ASK_BALANCE, ASK_RISK_PCT = range(2, 4)  
ASK_PROMO_COUNT, ASK_PROMO_DURATION = range(4, 6)
SELECT_LANG = 12
SELECT_LANG_START = 13
# ASK_STRATEGY, ASK_EXCHANGE, ASK_API_KEY, ASK_SECRET_KEY = range(6, 10)
ASK_STRATEGY, ASK_EXCHANGE, ASK_API_KEY, ASK_SECRET_KEY, ASK_PASSPHRASE, ASK_RESERVE, ASK_EDIT_SELECTION, ASK_EDIT_CAPITAL, ASK_EDIT_RISK, ASK_RISK_FINISH = range(6, 16)


# --- LOCALIZATION HELPER ---


async def get_main_menu_keyboard(user_id):
    keyboard = [
        [get_text(user_id, "btn_top_up"), get_text(user_id, "btn_withdraw")],
        [get_text(user_id, "btn_my_exchanges")],
        [get_text(user_id, "btn_language"), get_text(user_id, "btn_back")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_all_translations(key: str) -> list:
    """Returns all possible translations for a key (used for button matching)."""
    variants = []
    for lang in ['en', 'ru', 'uk']:
        try:
            file_path = os.path.join("locales", f"{lang}.json")
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    translations = json.load(f)
                    val = translations.get(key)
                    if val: variants.append(val)
        except:
            pass
    return list(set(variants))

async def verify_payment_and_activate(tx_hash: str, user_id: int, context: ContextTypes.DEFAULT_TYPE):

    if is_tx_hash_used(tx_hash):
        await context.bot.send_message(user_id, get_text(user_id, "err_tx_used"))
        return

    url = f"https://api.etherscan.io/v2/api?chainid=56&module=proxy&action=eth_getTransactionByHash&txhash={tx_hash}&apikey={BSCSCAN_API_KEY}"
    
    try:
        print(f"DEBUG: Requesting TxInfo from Etherscan V2 for {tx_hash}")
        response = requests.get(url, timeout=15)
        data = response.json()
        
        print(f"DEBUG: Etherscan V2 API Response: {data}")

        if "result" not in data:
            await context.bot.send_message(user_id, get_text(user_id, "err_invalid_api"))
            return
            
        tx = data.get("result")
        
        if not isinstance(tx, dict) or not tx:
            error_message = data.get('message', 'Transaction not found or API error.')
            if 'Invalid API Key' in str(data):
                await context.bot.send_message(user_id, get_text(user_id, "err_api_key_invalid"))
            else:
                await context.bot.send_message(user_id, get_text(user_id, "msg_verification_pending"))
            return
        
        contract_address = tx.get('to', '').lower()
        tx_input = tx.get('input', '')
        if contract_address != USDT_CONTRACT_ADDRESS.lower() or len(tx_input) < 138:
            await context.bot.send_message(user_id, get_text(user_id, "err_not_usdt")); return
        to_address_in_data = tx_input[34:74]
        if WALLET_ADDRESS[2:].lower() not in to_address_in_data.lower():
            await context.bot.send_message(user_id, get_text(user_id, "err_wrong_address")); return
        amount_token = int(tx_input[74:138], 16) / (10**18)
        if not (PAYMENT_AMOUNT <= amount_token < PAYMENT_AMOUNT + 0.1):
            await context.bot.send_message(user_id, get_text(user_id, "err_incorrect_amount", expected=PAYMENT_AMOUNT, received=amount_token)); return
            
        activate_user_subscription(user_id)
        mark_tx_hash_as_used(tx_hash)
        
        # main_keyboard = [["Analyze Chart 📈", "View Chart 📊"], ["Profile 👤", "Risk Settings ⚙️"]]
        main_keyboard = [
        ["Analyze Chart 📈", "Copy Trade 🚀"], # Copy Trade теперь здесь
        ["View Chart 📊", "Profile 👤"],
        ["Risk Settings ⚙️"]
    ]
        main_reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
        
        await context.bot.send_message(user_id, get_text(user_id, "msg_payment_success"), reply_markup=main_reply_markup)
        # REFERRAL REWARD LOGIC REMOVED (Handled by MLM profit sharing now)
        referrer_id = get_referrer(user_id)
        if referrer_id:
            try:
                # Optional: notify referrer about new referral, but no reward 
                pass
            except Exception:
                pass
                
    except Exception as e:
        print(f"Error in verify_payment: {e}")
        await context.bot.send_message(user_id, get_text(user_id, "err_unexpected"))

async def simulate_thinking(duration=2):
    """Задержка для естественности"""
    await asyncio.sleep(duration)


def format_plan_to_message(plan, user_id: int):
    view = plan.get('view')
    symbol = plan.get('symbol', 'UNKNOWN')
    timeframe = plan.get('timeframe', '15m')
    notes = plan.get('notes', '')

    if view == 'long': 
        icon = "🟢"
        title = get_text(user_id, "report_long_title", symbol=symbol, timeframe=timeframe)
    elif view == 'short': 
        icon = "🔴"
        title = get_text(user_id, "report_short_title", symbol=symbol, timeframe=timeframe)
    else: # neutral
        icon = "⚪️"; title = get_text(user_id, "report_neutral_title", symbol=symbol, timeframe=timeframe)
        
        message = f"{icon} {title}\n\n<b>{get_text(user_id, 'report_rationale')}</b>\n<i>{notes}</i>"
        
        metrics = plan.get('metrics')
        if metrics:
            metrics_text = f"\n\n<b>{get_text(user_id, 'report_metrics')}</b>\n"
            for key, value in metrics.items():
                metrics_text += f"— {key}: <code>{value}</code>\n"
            message += metrics_text
        
        message += f"\n<i>{get_text(user_id, 'report_waiting')}</i>"
        return message

    entry_zone = plan.get('entry_zone', ['N/A']); stop_loss = plan.get('stop', 'N/A'); targets = plan.get('targets', ['N/A'])
    
    message = (f"{icon} {title}\n\n"
               f"<b>🔹 {get_text(user_id, 'report_entry')}</b> <code>{entry_zone[0]} - {entry_zone[1]}</code>\n"
               f"<b>🔸 {get_text(user_id, 'report_stop')}</b> <code>{stop_loss}</code>\n"
               f"<b>🎯 {get_text(user_id, 'report_targets')}</b> <code>{', '.join(map(str, targets))}</code>\n\n"
               f"📝 <b>{get_text(user_id, 'report_rationale')}</b>\n<i>{notes}</i>")
               
    if plan.get('position_size_asset'):
        pos_size_asset = plan.get('position_size_asset', 'N/A')
        symbol_base = plan.get('symbol', 'ASSET').replace('USDT', '')
        pos_size_usd = plan.get('position_size_usd', 'N/A')
        potential_loss = plan.get('potential_loss_usd', 'N/A')
        potential_profit = plan.get('potential_profit_usd', 'N/A')
        rr_ratio = plan.get('risk_reward_ratio', 'N/A')
        message += (f"\n\n<b>{get_text(user_id, 'report_risk_profile')}</b>\n"
                    f"  - {get_text(user_id, 'report_pos_size')} <code>{pos_size_asset} {symbol_base}</code> ({pos_size_usd})\n"
                    f"  - {get_text(user_id, 'report_max_loss')} <code>{potential_loss}</code>\n"
                    f"  - {get_text(user_id, 'report_max_profit')} <code>{potential_profit}</code>\n"
                    f"  - {get_text(user_id, 'report_rr_ratio')} <code>{rr_ratio}</code>" )
    return message


def blocking_chart_analysis(file_path: str, risk_settings: dict, progress_callback, user_id: int) -> tuple:
    try:
        print(f"\n--- [START] BLOCKING ANALYSIS in thread for {file_path} ---")
        if progress_callback:
            progress_callback(get_text(user_id, "msg_analyzing_chart"))
        time.sleep(5)
        
        candlesticks, chart_info = find_candlesticks(file_path)
        
        print(f"LOG: GPT Vision Raw Info: {chart_info}")
        
        df = None; trade_plan = None; analysis_context = None
        ticker = chart_info.get('ticker') if chart_info else None
        
        if ticker:
            display_timeframe = chart_info.get('timeframe', '15m')
            fetch_timeframe = '15m'
            
            print(f"LOG: Ticker '{ticker}' and Timeframe '{display_timeframe}' identified.")
            if progress_callback:
                progress_callback(get_text(user_id, "msg_ai_identified", ticker=ticker, display_timeframe=display_timeframe))
            time.sleep(2)
            
            base_currency = None; known_quotes = ["USDT", "BUSD", "TUSD", "USDC", "USD"]
            for quote in known_quotes:
                if ticker.endswith(quote):
                    base_currency = ticker[:-len(quote)]; break
            
            if base_currency:
                symbol_for_api = f"{base_currency}/USDT"
                print(f"LOG: Formatted symbol for API: {symbol_for_api}, requesting timeframe: {fetch_timeframe}")
                
                df = fetch_data(symbol=symbol_for_api, timeframe=fetch_timeframe)
                
                if df is not None and not df.empty:
                    print(f"LOG: Successfully fetched {len(df)} candles for {symbol_for_api}.")
                    if progress_callback:
                        progress_callback(get_text(user_id, "msg_running_tech_analysis"))
                    time.sleep(4)
                    features = compute_features(df)
                    trade_plan, analysis_context = generate_decisive_signal(
                        features, symbol_ccxt=symbol_for_api, risk_settings=risk_settings, display_timeframe=display_timeframe
                    )
                else:
                    print(f"LOG: FAILED to fetch data for {symbol_for_api}.")
                    return None, None, get_text(user_id, "err_fetch_failed", ticker=ticker)
            else:
                print(f"LOG: Ticker '{ticker}' was identified, but not recognized as a valid pair.")
                ticker = None 

        if ticker is None:
            print("LOG: Ticker not identified by AI.")
            return None, None, get_text(user_id, "err_ticker_not_found")

        if not trade_plan:
            print("LOG: Analysis engine did not produce a valid trade plan.")
            return None, None, get_text(user_id, "err_no_trade_plan")

        print(f"LOG: Trade plan generated successfully: {trade_plan.get('view')}")
        if progress_callback:
            progress_callback(get_text(user_id, "msg_generating_report"))
        time.sleep(1)
        print(f"--- [END] BLOCKING ANALYSIS for {file_path} ---")
        return trade_plan, analysis_context, None

    except Exception as e:
        print(f"FATAL ERROR in blocking_chart_analysis for {file_path}: {e}")
        return None, None, get_text(user_id, "err_unexpected_analysis")

async def run_analysis_in_background(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, processing_message: object, file_path: str, risk_settings: dict):
    try:
        progress_queue = asyncio.Queue()
        async def progress_updater():
            while True:
                message_text = await progress_queue.get()
                if message_text is None:  
                    break
                try:
                    await processing_message.edit_text(message_text, parse_mode=ParseMode.HTML)
                except Exception as e:
                    print(f"Progress update failed (this might be normal on the final step): {e}")
        
        progress_task = asyncio.create_task(progress_updater())
        def progress_callback(message_text):
            try:
                asyncio.get_running_loop().call_soon_threadsafe(
                    progress_queue.put_nowait, message_text
                )
            except Exception as e:
                print(f"Error putting message in progress queue: {e}")
        
        trade_plan, analysis_context, error_message = await asyncio.to_thread(
            blocking_chart_analysis, file_path, risk_settings, progress_callback, user_id
        )
        
        await progress_queue.put(None)
        await progress_task
        
        if error_message:
            await processing_message.edit_text(error_message)
            return
            
        context.user_data['last_analysis_context'] = analysis_context
        
        message_text = format_plan_to_message(trade_plan, user_id)
        
        profile = get_user_profile(user_id)
        referral_link = None
        if profile and profile.get('ref_code'):
            bot_username = (await context.bot.get_me()).username
            referral_link = f"https://t.me/{bot_username}?start={profile['ref_code']}"
        
        inline_keyboard = []
        if referral_link:
            inline_keyboard.append([InlineKeyboardButton("Click here to subscribe", url=referral_link)])
        reply_markup_inline = InlineKeyboardMarkup(inline_keyboard) if inline_keyboard else None
        
        await processing_message.delete()
        await update.message.reply_text(
            text=message_text, 
            parse_mode=ParseMode.HTML, 
            reply_markup=reply_markup_inline
        )
        
        reply_keyboard = [[get_text(user_id, "btn_explain"), get_text(user_id, "btn_back")]]
        reply_markup_reply = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(get_text(user_id, "msg_next_steps"), reply_markup=reply_markup_reply)

    except Exception as e:
        print(f"FATAL Error in background analysis task for user {user_id}: {e}")
        try:
            await processing_message.edit_text(get_text(user_id, "err_unexpected_analysis"))
        except Exception as edit_e:
            print(f"Could not even inform user {user_id} about the error: {edit_e}")
    finally:
        # Важнейшее улучшение: удаляем временный файл после использования
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Cleaned up temporary file: {file_path}")

# --- (BROADCAST) ---

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает диалог создания рассылки."""
    await update.message.reply_text(
        "Please type the message you want to broadcast to all active users.\n\n"
        "You can use HTML tags for formatting (e.g., <b>bold</b>, <i>italic</i>).\n\n"
        "Type /cancel to abort.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ASK_BROADCAST_MESSAGE

async def broadcast_ask_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает текст, показывает превью и просит подтверждения."""
    message_text = update.message.text
    context.user_data['broadcast_message'] = message_text
    
    # Считаем, скольким пользователям будет отправлено сообщение
    active_users_count = len(get_all_active_user_ids())
    
    # Показываем админу превью
    await update.message.reply_text("--- PREVIEW ---")
    await update.message.reply_text(message_text, parse_mode=ParseMode.HTML)
    await update.message.reply_text("--- END PREVIEW ---")
    
    keyboard = [["SEND NOW ✅", "Cancel ❌"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        f"This message will be sent to <b>{active_users_count}</b> active users. "
        f"Are you sure you want to proceed?",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )
    return CONFIRM_BROADCAST

async def broadcast_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет сообщение всем активным пользователям."""
    message_text = context.user_data.get('broadcast_message')
    if not message_text:
        await update.message.reply_text("Error: Message not found. Please start over.")
        return ConversationHandler.END
        
    user_ids = get_all_active_user_ids()
    
    await update.message.reply_text(f"Starting broadcast to {len(user_ids)} users... This may take a while.", reply_markup=ReplyKeyboardRemove())
    
    success_count = 0
    fail_count = 0
    
    for user_id in user_ids:
        try:
            await context.bot.send_message(user_id, text=message_text, parse_mode=ParseMode.HTML)
            success_count += 1
        except Exception as e:
            print(f"Failed to send broadcast to user {user_id}: {e}")
            fail_count += 1
        await asyncio.sleep(0.1) # Важная задержка, чтобы не попасть под rate-limit
    
    # Возвращаем админ-клавиатуру
    admin_keyboard = [["User Stats 👥", "Withdrawals 🏧"], ["Generate Promos 🎟️", "Broadcast 📢"], ["Back to Main Menu ⬅️"]]
    reply_markup = ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"✅ Broadcast complete!\n\n"
        f"Successfully sent: {success_count}\n"
        f"Failed to send: {fail_count}",
        reply_markup=reply_markup
    )
    
    context.user_data.clear()
    return ConversationHandler.END


# async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.effective_user.id
#     if not has_access(user_id):
#         await update.message.reply_text("❌ Access Required. Please use /start to activate.")
#         return
        
#     risk_settings = get_user_risk_settings(user_id)
#     # Создаем уникальное имя файла, чтобы избежать конфликтов при одновременной обработке
#     timestamp = int(time.time())
#     file_path = f'chart_{user_id}_{timestamp}.jpg'
    
#     try:
#         photo_file = await update.message.photo[-1].get_file()
#         await photo_file.download_to_drive(file_path)
        
#         # 1. Отправляем пользователю моментальный ответ
#         processing_message = await update.message.reply_text("📨 Chart received! Your request is in the queue...")
        
#         # 2. Запускаем "тяжелую" задачу в ФОНЕ, не дожидаясь ее завершения
#         asyncio.create_task(
#             run_analysis_in_background(
#                 update=update,
#                 context=context,
#                 user_id=user_id,
#                 processing_message=processing_message,
#                 file_path=file_path,
#                 risk_settings=risk_settings
#             )
#         )
#         # `photo_handler` завершает свою работу здесь, и бот готов принимать новые команды

#     except Exception as e:
#         print(f"Error in initial photo_handler for user {user_id}: {e}")
#         await update.message.reply_text("❌ An error occurred while receiving your chart.")
#         # Если файл был создан, но задача не запустилась, удаляем его
#         if os.path.exists(file_path):
#             os.remove(file_path)


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    НОВЫЙ ОБРАБОТЧИК: Неблокирующий анализ + Проверка лимитов (5 раз в день).
    """
    user_id = update.effective_user.id
    
    # 1. ПРОВЕРКА ЛИМИТА (ГЛАВНОЕ ИЗМЕНЕНИЕ)
    # Если лимит исчерпан, check_analysis_limit вернет False
    if not check_analysis_limit(user_id, limit=5):
        await update.message.reply_text(get_text(user_id, "err_daily_limit"), parse_mode=ParseMode.HTML)
        return

    # 2. Получаем настройки риска
    risk_settings = get_user_risk_settings(user_id)
    
    # 3. Создаем уникальное имя файла
    timestamp = int(time.time())
    file_path = f'chart_{user_id}_{timestamp}.jpg'
    
    try:
        photo_file = await update.message.photo[-1].get_file()
        await photo_file.download_to_drive(file_path)
        
        # 4. Отправляем пользователю моментальный ответ
        processing_message = await update.message.reply_text(get_text(user_id, "msg_chart_received"))
        
        # 5. Запускаем "тяжелую" задачу в ФОНЕ через create_task
        # Это гарантирует, что бот не зависнет для других юзеров
        asyncio.create_task(
            run_analysis_in_background(
                update=update,
                context=context,
                user_id=user_id,
                processing_message=processing_message,
                file_path=file_path,
                risk_settings=risk_settings
            )
        )

    except Exception as e:
        print(f"Error in initial photo_handler for user {user_id}: {e}")
        await update.message.reply_text("❌ An error occurred while receiving your chart.")
        # Если файл был создан, но задача не запустилась, удаляем его
        if os.path.exists(file_path):
            os.remove(file_path)



# --- ФУНКЦИЯ ПРОВЕРКИ ДОСТУПА С УЧЕТОМ АДМИНА ---
def has_access(user_id: int) -> bool:
    """Проверяет, активна ли подписка ИЛИ является ли пользователь админом."""
    if user_id == ADMIN_USER_ID:
        return True # "Режим Бога" для админа
    
    status = get_user_status(user_id)
    return status == 'active'

# --- Enhanced Bot Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Check for referral code in start parameter
    referrer_id = None
    if context.args and context.args[0].startswith('ref_'):
        code = context.args[0]
        referrer_id = get_user_by_referral_code(code)
    
    is_new_user = add_user(user.id, user.username, referrer_id)
    
    if is_new_user:
        keyboard = [["🇬🇧 English", "🇷🇺 Русский"], ["🇺🇦 Українська"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        # Initial prompt in English/Russian as we don't know the language yet
        await update.message.reply_text("Please select your language / Пожалуйста, выберите язык:", reply_markup=reply_markup)
        return SELECT_LANG_START

    await send_welcome(update, context)
    return ConversationHandler.END

async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    main_keyboard = [
        [get_text(user.id, "btn_copytrade")],
        [get_text(user.id, "btn_viewchart"), get_text(user.id, "btn_profile")]
    ]
    reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
    welcome_text = get_text(user.id, "welcome_back")
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from database import get_user_exchanges
    user_id = update.effective_user.id
    profile = get_user_profile(user_id)
    confirm_exchanges = get_user_exchanges(user_id)
    
    if not profile:
        await update.message.reply_text("Couldn't find your profile. Please /start the bot.")
        return

    # Calculate Total Trading Capital from all active connections
    total_capital = sum(ex['reserved_amount'] for ex in confirm_exchanges if ex['is_active'])

        
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={profile['ref_code']}"
    referral_counts = get_referral_counts(user_id)
    
    status_emoji = get_text(user_id, "status_active") if profile['status'] == 'active' else get_text(user_id, "status_pending")
    expiry_text = f"{get_text(user_id, 'expires_on')} {profile['expiry']}" if profile['expiry'] else "N/A"
    
    profile_text = (
        f"{get_text(user_id, 'profile_title')}\n\n"
        f"{get_text(user_id, 'status')} {status_emoji}\n"
        f"{get_text(user_id, 'subscription')} {expiry_text}\n"
        f"{get_text(user_id, 'token_balance')} {profile['balance']:.2f} 🪙\n"
        f"{get_text(user_id, 'trading_balance')} ${total_capital:,.2f}\n\n"
        f"{get_text(user_id, 'referral_link')}\n"
        f"<code>{referral_link}</code>\n\n"
        f"{get_text(user_id, 'invite_earn')}\n"
        f"{get_text(user_id, 'referral_levels')}\n"
        f"{get_text(user_id, 'referrals_title')}\n"
        f"{get_text(user_id, 'level_1_count', count=referral_counts['l1'])}\n"
    )
    
    # Разные кнопки для активных и неактивных
    # Always show full keyboard for everyone
    keyboard = [
        [get_text(user_id, "btn_top_up"), get_text(user_id, "btn_withdraw")],
        [get_text(user_id, "btn_my_exchanges")],
        [get_text(user_id, "btn_language"),get_text(user_id, "btn_back")],
    ]
        
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(profile_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def my_exchanges_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список подключенных бирж и их статус."""
    from database import get_user_exchanges
    
    user_id = update.effective_user.id
    exchanges = get_user_exchanges(user_id)
    
    if not exchanges:
        await update.message.reply_text(get_text(user_id, "msg_no_exchanges"))
        return

    msg_list = ""
    keyboard = []
    
    # Send "Checking balances..." message first
    status_msg = await update.message.reply_text(get_text(user_id, "msg_checking_balances"))

    for ex in exchanges:
        # Decrypt keys
        keys = get_user_decrypted_keys(user_id, ex['exchange_name'])
        
        # Check connection & Fetch Balance
        real_usdt_bal = None
        is_connected = False
        
        if keys:
            try:
                # Run sync CCXT/Binance calls in thread
                real_usdt_bal = await fetch_exchange_balance_safe(
                    ex['exchange_name'], keys['apiKey'], keys['secret'], keys['password']
                )
                if real_usdt_bal is not None: is_connected = True
            except Exception as e:
                print(f"Check failed for {ex['exchange_name']}: {e}")

        # Combine Flags
        db_active = ex['is_active']
        
        if db_active and is_connected:
            status_icon = f"🟢 {get_text(user_id, 'status_connected')}"
            balance_str = f"${real_usdt_bal:,.2f}"
        elif db_active and not is_connected:
            status_icon = f"🔴 {get_text(user_id, 'status_error')}"
            balance_str = "N/A"
        else:
            status_icon = f"🔴 {get_text(user_id, 'status_disconnected')}"
            balance_str = "N/A"

        # Strategy Display Name
        strat_disp = "TradeMax" if ex['strategy'] == 'cgt' else ex['strategy'].upper()

        risk_line = ""
        btn_key = "btn_edit_reserve"
        
        if ex['strategy'] == 'cgt': # TradeMax
            risk_val = ex.get('risk_pct', 1.0)
            risk_line = f"   • {get_text(user_id, 'lbl_risk')}: <b>{risk_val}%</b>\n"
            btn_key = "btn_edit_settings"


        # Localized Item
        msg_list += (
            f"🔹 <b>{ex['exchange_name'].capitalize()}</b>\n"
            f"   • {get_text(user_id, 'lbl_strategy')}: {strat_disp}\n"
            f"   • {get_text(user_id, 'lbl_reserve')}: <b>${ex['reserved_amount']}</b>\n"
            f"{risk_line}"
            f"   • {get_text(user_id, 'lbl_status')}: {status_icon}\n"
            f"   • {get_text(user_id, 'lbl_wallet_balance')}: <b>{balance_str}</b>\n\n"
        )
        
        # Add 'Edit Reserve' button for this exchange
        btn_text = get_text(user_id, btn_key, exchange=ex['exchange_name'].capitalize())
        keyboard.append([btn_text])

    keyboard.append([get_text(user_id, "btn_back")])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await status_msg.delete() # Remove "Checking..."
    
    await update.message.reply_text(
        get_text(user_id, "msg_my_exchanges", exchanges_list=msg_list),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

# fetch_exchange_balance_safe moved to exchange_utils.py

# --- LANGUAGE SELECTION FLOW ---

# --- LANGUAGE SELECTION FLOW ---
async def change_language_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [["🇬🇧 English", "🇷🇺 Русский"], ["🇺🇦 Українська"], [get_text(user_id, "btn_back")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(get_text(user_id, "select_language"), reply_markup=reply_markup)
    return SELECT_LANG

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    choice = update.message.text
    
    lang_map = {
        "🇬🇧 English": "en",
        "🇷🇺 Русский": "ru",
        "🇺🇦 Українська": "uk"
    }
    
    lang_code = lang_map.get(choice)
    
    if lang_code:
        from database import save_user_language
        save_user_language(user_id, lang_code)
        # We need to get the text IN THE NEW LANGUAGE
        # But our get_text fetches from DB, so it should work immediately
        await update.message.reply_text(get_text(user_id, "language_set"))
    else:
        await update.message.reply_text(get_text(user_id, "invalid_selection"))
        
    # Return to profile
    await profile_command(update, context)
    return ConversationHandler.END

    await update.message.reply_text(
        get_text(user_id, "msg_my_exchanges", exchanges_list=msg_list),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def edit_reserve_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает редактирование торгового капитала."""
    text = update.message.text
    user_id = update.effective_user.id
    
    # Парсим имя биржи из текста кнопки: Edit Capital (Binance) 💰
    match = re.search(r"\((.+)\)", text)
    if not match:
        await update.message.reply_text("Error identifying exchange.")
        return ConversationHandler.END
        
    exchange_name = match.group(1).lower() # binance/okx
    
    # Fetch API Keys to check Status & Balance
    msg_checking = await update.message.reply_text(get_text(user_id, "msg_checking_balances"))
    
    keys = get_user_decrypted_keys(user_id, exchange_name)
    if not keys:
         await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_checking.message_id)
         await update.message.reply_text("Error: Exchange keys not found.")
         return ConversationHandler.END

    # Strategy Check
    from database import get_user_exchanges
    user_exs = get_user_exchanges(user_id)
    target_ex = next((x for x in user_exs if x['exchange_name'] == exchange_name), None)
    strategy = target_ex['strategy'] if target_ex else 'bro-bot'
    context.user_data['editing_strategy'] = strategy

    # Live Balance Check
    balance = await fetch_exchange_balance_safe(exchange_name, keys['apiKey'], keys['secret'], keys.get('password'))
    
    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_checking.message_id)
    
    if balance is None:
        await update.message.reply_text("⚠️ <b>Warning</b>\nCould not fetch live balance. Capital check will be disabled.", parse_mode=ParseMode.HTML)
        balance = 99999999.0 # Disable check if fetch fails
    
    context.user_data['editing_exchange'] = exchange_name
    context.user_data['editing_balance'] = balance
    
    # BRANCHING
    # BRANCHING
    if strategy == 'cgt': # TradeMax
        keyboard = [
            [get_text(user_id, "btn_change_capital"), get_text(user_id, "btn_change_risk")], 
            [get_text(user_id, "btn_back")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        msg_title = get_text(user_id, "msg_edit_settings_title", exchange=exchange_name.capitalize(), strategy="TradeMax", balance=f"{balance:.2f}")
        msg_prompt = get_text(user_id, "msg_what_to_change")
        
        await update.message.reply_text(
            f"{msg_title}\n\n{msg_prompt}",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return ASK_EDIT_SELECTION

    # Bro-Bot (Standard)
    await update.message.reply_text(
        get_text(user_id, "msg_edit_reserve_prompt", exchange=exchange_name.capitalize(), balance=f"{balance:.2f}"),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode=ParseMode.HTML
    )
    return ASK_EDIT_CAPITAL

async def edit_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    exchange = context.user_data.get('editing_exchange')
    balance = context.user_data.get('editing_balance')
    
    # Handle Back
    if text in get_all_translations("btn_back"):
        context.user_data.pop('editing_exchange', None)
        await my_exchanges_command(update, context) # Show list again
        return ConversationHandler.END
    
    if text in get_all_translations("btn_change_capital"):
        await update.message.reply_text(
            get_text(user_id, "msg_edit_reserve_prompt", exchange=exchange.capitalize(), balance=f"{balance:.2f}"),
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=ParseMode.HTML
        )
        return ASK_EDIT_CAPITAL
        
    elif text in get_all_translations("btn_change_risk"):
        await update.message.reply_text(
             get_text(user_id, "msg_edit_risk_prompt", exchange=exchange.capitalize()),
             parse_mode=ParseMode.HTML,
             reply_markup=ReplyKeyboardRemove()
        )
        return ASK_EDIT_RISK
        
    await update.message.reply_text(get_text(user_id, "err_unknown_command"))
    return ASK_EDIT_SELECTION

async def edit_capital_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет новый торговый капитал."""
    user_id = update.effective_user.id
    text = update.message.text
    exchange_name = context.user_data.get('editing_exchange')
    balance = context.user_data.get('editing_balance', 99999999.0)
    
    # Check for Back/Cancel
    if text in get_all_translations("btn_back") or "Back to Main Menu" in text or "/cancel" in text:
        return await cancel_edit_reserve(update, context)
    
    if not exchange_name:
        await update.message.reply_text("Session expired. Please select exchange again.")
        return await my_exchanges_command(update, context)
    
    # --- NAVIGATION CHECK ---
    if "Skip" in text or text == "0":
        # Skip = Balance
        new_capital = balance if balance != 99999999.0 else 0.0 
    else:
        try:
            val = float(text)
            if val < 0: raise ValueError
            
            if val > balance:
                await update.message.reply_text(
                     f"❌ <b>Invalid Amount</b>\n",
                     parse_mode=ParseMode.HTML
                 )
                return ASK_EDIT_CAPITAL
                
            new_capital = val
        except ValueError:
            await update.message.reply_text(get_text(user_id, "err_invalid_amount"))
            return ASK_EDIT_CAPITAL
    
    # Save
    update_exchange_reserve(user_id, exchange_name, new_capital)
    
    await update.message.reply_text(
        get_text(user_id, "msg_reserve_updated", exchange=exchange_name.capitalize(), reserve=f"{new_capital:.2f}"),
        reply_markup=await get_main_menu_keyboard(user_id),
        parse_mode=ParseMode.HTML
    )
    context.user_data.clear()
    return ConversationHandler.END

async def edit_risk_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    exchange = context.user_data.get('editing_exchange')
    
    # Check for Back/Cancel
    if text in get_all_translations("btn_back") or "Back to Main Menu" in text or "/cancel" in text:
        return await cancel_edit_reserve(update, context)
    
    try:
        val = float(text)
        if val <= 0 or val > 100: raise ValueError
        new_risk = val
    except ValueError:
        await update.message.reply_text(f"❌ Invalid Percentage. Enter 0.1 - 100.")
        return ASK_EDIT_RISK
        
    update_exchange_risk(user_id, exchange, new_risk)
    
    await update.message.reply_text(
        f"✅ <b>Risk Updated!</b>\n\nExchange: {exchange.capitalize()}\nNew Risk: <b>{new_risk}%</b>",
        reply_markup=await get_main_menu_keyboard(user_id),
        parse_mode=ParseMode.HTML
    )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_edit_reserve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels edit and returns to My Exchanges."""
    context.user_data.pop('editing_exchange', None)
    context.user_data.pop('editing_balance', None)
    context.user_data.pop('editing_strategy', None)
    await my_exchanges_command(update, context)
    return ConversationHandler.END

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This might duplicates existing logic, but ensures clean exit
    context.user_data.pop('editing_exchange', None)
    return await start(update, context) # Or end_conversation depending on flow



async def set_initial_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    choice = update.message.text
    
    lang_map = {
        "🇬🇧 English": "en",
        "🇷🇺 Русский": "ru",
        "🇺🇦 Українська": "uk"
    }
    
    lang_code = lang_map.get(choice)
    
    if lang_code:
        from database import save_user_language
        save_user_language(user_id, lang_code)
        await update.message.reply_text(get_text(user_id, "language_set"))
        await send_welcome(update, context)
    else:
        # If invalid (e.g. random text), ask again properly or default to EN
        await update.message.reply_text("Invalid selection. Please use the buttons.")
        return SELECT_LANG_START
        
    return ConversationHandler.END

async def top_up_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает инструкцию по пополнению баланса."""
    user_id = update.effective_user.id
    await update.message.reply_text(get_text(user_id, "msg_how_to_top_up", address=WALLET_ADDRESS), parse_mode=ParseMode.HTML)

# --- НОВАЯ ФУНКЦИЯ ДЛЯ ПРОВЕРКИ ПЛАТЕЖА ЗА ПОПОЛНЕНИЕ ---
async def verify_top_up_payment(tx_hash: str, user_id: int) -> tuple[bool, str, float]:
    """Проверяет транзакцию пополнения и возвращает сумму."""
    if is_tx_hash_used(tx_hash):
        return False, get_text(user_id, "err_tx_used"), 0
    
    url = f"https://api.etherscan.io/v2/api?chainid=56&module=proxy&action=eth_getTransactionByHash&txhash={tx_hash}&apikey={BSCSCAN_API_KEY}"
    
    try:
        print(f"DEBUG: Requesting TxInfo from Etherscan V2 for {tx_hash}")
        response = requests.get(url, timeout=15)
        data = response.json()
        
        print(f"DEBUG: Etherscan V2 API Response: {data}")

        if "result" not in data:
            return False, get_text(user_id, "err_invalid_api"), 0
            
        tx = data.get("result")
        
        if not isinstance(tx, dict) or not tx:
            error_message = data.get('message', 'Transaction not found or API error.')
            if 'Invalid API Key' in str(data):
                return False, "API Key is invalid. Please contact support.", 0
            else:
                return False, "Please wait a few minutes and try again.", 0
        
        contract_address = tx.get('to', '').lower()
        tx_input = tx.get('input', '')
        if contract_address != USDT_CONTRACT_ADDRESS.lower() or len(tx_input) < 138:
            return False, get_text(user_id, "err_not_usdt"), 0
            
        to_address_in_data = tx_input[34:74]
        if WALLET_ADDRESS[2:].lower() not in to_address_in_data.lower():
            return False, get_text(user_id, "err_wrong_address"), 0
            
        amount_token = int(tx_input[74:138], 16) / (10**18)
        if amount_token <= 0:
            return False, "Invalid payment amount.", 0
            
        return True, "Payment verified successfully!", amount_token
        
    except Exception as e:
        print(f"Error in verify_top_up_payment: {e}")
        return False, "An unexpected error occurred during verification.", 0

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced help command with risk management info."""
    user_id = update.effective_user.id
    status = get_user_status(user_id)
    
    if status == 'active':
        help_text = get_text(user_id, "msg_help_active")
    else:
        help_text = get_text(user_id, "msg_help_inactive", amount=PAYMENT_AMOUNT)
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

# --- Withdrawal Conversation Handlers ---

# async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     await update.message.reply_text("Please enter the amount of tokens you wish to withdraw:", reply_markup=ReplyKeyboardRemove())
#     return ASK_AMOUNT
async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [[get_text(user_id, "btn_cancel")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        get_text(user_id, "msg_withdraw_amount"), 
        reply_markup=reply_markup
    )
    return ASK_AMOUNT


async def ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if text == get_text(user_id, "btn_cancel"):
        return await cancel(update, context)

    keyboard = [[get_text(user_id, "btn_cancel")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    try:
        amount = float(text)
        if amount <= 0: raise ValueError
        
        profile = get_user_profile(user_id)
        if amount > profile['balance']:
            await update.message.reply_text(get_text(user_id, "err_insufficient_balance", balance=profile['balance']), reply_markup=reply_markup)
            return ASK_AMOUNT
            
        context.user_data['withdraw_amount'] = amount
        await update.message.reply_text(get_text(user_id, "msg_withdraw_wallet"), reply_markup=reply_markup)
        return ASK_WALLET
    except ValueError:
        await update.message.reply_text(get_text(user_id, "err_invalid_amount"), reply_markup=reply_markup)
        return ASK_AMOUNT

async def ask_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallet_address = update.message.text
    user_id = update.effective_user.id
    if not (wallet_address.startswith("0x") and len(wallet_address) == 42):
        keyboard = [[get_text(user_id, "btn_cancel")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(get_text(user_id, "err_invalid_wallet"), reply_markup=reply_markup )
        return ASK_WALLET
        
    amount = context.user_data['withdraw_amount']
    user_id = update.effective_user.id
    
    # Create request in DB
    success = create_withdrawal_request(user_id, amount, wallet_address)
    
    if not success:
        await update.message.reply_text("An error occurred. Please try again.")
        return ConversationHandler.END

    # Notify admin
    if ADMIN_USER_ID:
        admin_message = (
            f"⚠️ New Withdrawal Request ⚠️\n\n"
            f"User ID: {user_id}\n"
            f"Username: @{update.effective_user.username}\n"
            f"Amount: {amount} USDT\n"
            f"Wallet: <code>{wallet_address}</code>"
        )
        await context.bot.send_message(ADMIN_USER_ID, admin_message, parse_mode=ParseMode.HTML)
    
    # Возвращаем к основной клавиатуре
    keyboard = [
        [get_text(user_id, "btn_copytrade")],
        [get_text(user_id, "btn_viewchart"), get_text(user_id, "btn_profile")]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(get_text(user_id, "msg_withdraw_submitted"), reply_markup=reply_markup)
    
    return ConversationHandler.END


# async def connect_exchange_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Начинает диалог подключения к бирже."""
#     if not has_access(update.effective_user.id):
#         await update.message.reply_text("❌ Access Required. Please use /start to activate.")
#         return ConversationHandler.END

#     keyboard = [["Binance", "Bybit"], ["MEXC", "BingX"], ["Back to Main Menu ⬅️"]]
#     reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
#     await update.message.reply_text(
#         "⚙️ <b>Exchange Setup</b>\n\n"
#         "Select the exchange you want to connect.\n"
#         "Make sure your API keys have <b>Futures Trading</b> permissions enabled.",
#         reply_markup=reply_markup,
#         parse_mode=ParseMode.HTML
#     )
#     return ASK_EXCHANGE

async def connect_exchange_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сразу спрашиваем стратегию
    user_id = update.effective_user.id
    keyboard = [["Bro-Bot (Futures)", "TradeMax (Spot)"], [get_text(user_id, "btn_cancel")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        get_text(user_id, "msg_select_strategy"),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return ASK_STRATEGY

async def ask_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    user_id = update.effective_user.id
    
    if choice in ["Cancel", get_text(user_id, "btn_cancel")]:
        return await cancel(update, context) # Вызываем функцию отмены
    if choice == "Bro-Bot (Futures)":
        context.user_data['strategy'] = 'bro-bot'
        # Показываем биржи для Ратнера (Localized & No MEXC)
        keyboard = [
            [get_text(user_id, "btn_strat_binance"), get_text(user_id, "btn_strat_bybit")], 
            [get_text(user_id, "btn_strat_bingx")], 
            [get_text(user_id, "btn_back")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(get_text(user_id, "msg_select_futures_exchange"), reply_markup=reply_markup)
        return ASK_EXCHANGE

    elif choice == "TradeMax (Spot)":
        context.user_data['strategy'] = 'cgt'
        # Показываем ТОЛЬКО OKX
        keyboard = [["OKX"], [get_text(user_id, "btn_back")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(get_text(user_id, "msg_select_spot_exchange"), reply_markup=reply_markup)
        return ASK_EXCHANGE

    else:
        await update.message.reply_text(get_text(user_id, "err_invalid_strategy"))
        return ASK_STRATEGY

# async def ask_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Сохраняет биржу, отправляет инструкцию (ссылка + фото) и просит API Key."""
#     exchange_name = update.message.text
#     # Добавляем OKX или другие, если нужно
#     supported_exchanges = ["Binance", "Bybit", "BingX", "MEXC"]
    
#     if exchange_name not in supported_exchanges:
#         await update.message.reply_text("Invalid selection. Please choose an exchange from the list.")
#         return ASK_EXCHANGE
    
#     context.user_data['exchange_name'] = exchange_name.lower()
    
#     # 1. Отправляем ссылку на API Management
#     links = {
#         "Binance": "https://www.binance.com/en/my/settings/api-management",
#         "Bybit": "https://www.bybit.com/app/user/api-management",
#         "BingX": "https://www.bingx.com/en-us/account/api/",
#         "MEXC": "https://www.mexc.com/user/openapi" 
#     }
    
#     link = links.get(exchange_name, "")
    
#     msg_text = (
#         f"🔶 <b>{exchange_name} Configuration</b>\n\n"
#         f"👉 <b>Step 1:</b> Go to API Management:\n{link}\n"
#         f"<i>(Login if required)</i>\n\n"
#         f"👉 <b>Step 2:</b> Create new API Keys.\n"
#         f"⚠️ <b>IMPORTANT:</b> Enable <b>'Futures Trading'</b> permission.\n"
#         f"❌ <b>DO NOT</b> enable 'Withdrawals'.\n\n"
#         f"👉 <b>Step 3:</b> See the screenshots below for guidance 👇"
#     )
    
#     await update.message.reply_text(msg_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    
#     try:
#         folder_path = os.path.join("instructions", f"{exchange_name.lower()}_pic")
#         if os.path.exists(folder_path):
#             files = [f for f in os.listdir(folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
#             files.sort()
#             if files:
#                 media_group = []
#                 for file_name in files[:10]:
#                     file_path_img = os.path.join(folder_path, file_name)
#                     media_group.append(InputMediaPhoto(open(file_path_img, "rb")))
#                 if media_group:
#                     await update.message.reply_media_group(media=media_group)
#     except Exception as e:
#         print(f"Error sending instructions: {e}")

#     # --- ВАЖНОЕ ИЗМЕНЕНИЕ: Клавиатура с кнопкой "Назад" для следующего шага ---
#     keyboard = [["Back to Main Menu ⬅️"]]
#     reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
#     await update.message.reply_text(
#         "🔑 <b>Enter API Key</b>\n\n"
#         "Please paste your <b>API Key</b> below:",
#         reply_markup=reply_markup,
#         parse_mode=ParseMode.HTML
#     )
#     return ASK_API_KEY

# async def ask_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Сохраняет API Key и запрашивает Secret Key."""
#     api_key = update.message.text.strip()
    
#     # Валидация (Красивая ошибка)
#     if len(api_key) < 10: 
#         await update.message.reply_text(
#             "❌ <b>Invalid API Key</b>\n\n"
#             "The key you entered seems too short. Please check and try again.",
#             parse_mode=ParseMode.HTML
#         )
#         return ASK_API_KEY

#     context.user_data['api_key'] = api_key
    
#     # Клавиатура с кнопкой "Назад"
#     keyboard = [["Back to Main Menu ⬅️"]]
#     reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
#     await update.message.reply_text(
#         "🔒 <b>Enter Secret Key</b>\n\n"
#         "Great! Now please paste your <b>Secret Key</b>:",
#         reply_markup=reply_markup,
#         parse_mode=ParseMode.HTML
#     )
#     return ASK_SECRET_KEY


# async def ask_secret_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Сохраняет ключи в базу данных и завершает диалог."""
#     secret_key = update.message.text.strip()
    
#     # Валидация (Красивая ошибка)
#     if len(secret_key) < 10:
#         await update.message.reply_text(
#             "❌ <b>Invalid Secret Key</b>\n\n"
#             "The secret key seems too short. Please check and try again.",
#             parse_mode=ParseMode.HTML
#         )
#         return ASK_SECRET_KEY

#     user_id = update.effective_user.id
#     exchange = context.user_data['exchange_name']
#     api_key = context.user_data['api_key']
    
#     # Сохраняем
#     save_user_api_keys(user_id, exchange, api_key, secret_key)
    
#     context.user_data.clear()
    
#     # Возвращаем основное меню
#     main_keyboard = [
#         ["Analyze Chart 📈", "Copy Trade 🚀"],
#         ["View Chart 📊", "Profile 👤"],
#         ["Risk Settings ⚙️"]
#     ]
#     reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
    
#     await update.message.reply_text(
#         f"✅ <b>Connected Successfully!</b>\n\n"
#         f"Your <b>{exchange.capitalize()}</b> account is now linked.\n"
#         "Aladdin will now automatically copy trades to your account according to your risk settings.",
#         reply_markup=reply_markup,
#         parse_mode=ParseMode.HTML
#     )
#     return ConversationHandler.END



async def ask_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 3: Проверка биржи, Инструкции (Фото + Ссылка) и запрос API Key."""
    exchange_name = update.message.text
    strategy = context.user_data.get('strategy', 'bro-bot')
    user_id = update.effective_user.id
    
    if exchange_name in ["Back to Main Menu ⬅️", get_text(user_id, "btn_back")]:
        return await cancel(update, context)

    # --- MAPPING DISPLAY NAME TO CANONICAL NAME ---
    # We check all possible localized strings for each exchange
    canonical_exchange = None
    
    if exchange_name in get_all_translations("btn_strat_binance") + ["Binance"]: canonical_exchange = "Binance"
    elif exchange_name in get_all_translations("btn_strat_bybit") + ["Bybit"]: canonical_exchange = "Bybit"
    elif exchange_name in get_all_translations("btn_strat_bingx") + ["BingX"]: canonical_exchange = "BingX"
    elif exchange_name == "OKX": canonical_exchange = "OKX" # TradeMax only
    
    if not canonical_exchange:
         await update.message.reply_text("Invalid selection. Please choose from the buttons.")
         return ASK_EXCHANGE

    # Валидация бирж
    valid_bro_bot = ["Binance", "Bybit", "BingX"] # Removed MEXC
    valid_cgt = ["OKX"]
    
    if strategy == 'bro-bot' and canonical_exchange not in valid_bro_bot:
        await update.message.reply_text(get_text(user_id, "err_mismatch_strategy_exchange", strategy=strategy, valid_exchanges=', '.join(valid_bro_bot)))
        return ASK_EXCHANGE
        
    if strategy == 'cgt' and canonical_exchange not in valid_cgt:
        await update.message.reply_text(get_text(user_id, "err_mismatch_strategy_exchange", strategy='TradeMax', valid_exchanges='OKX'))
        return ASK_EXCHANGE
    
    context.user_data['exchange_name'] = canonical_exchange.lower()
    
    # Ссылки (добавил OKX)
    links = {
        "Binance": "https://www.binance.com/en/my/settings/api-management",
        "Bybit": "https://www.bybit.com/app/user/api-management",
        "BingX": "https://www.bingx.com/en-us/account/api/",
        "OKX": "https://www.okx.com/account/my-api" 
    }
    
    link = links.get(canonical_exchange, "")
    
    
    server_ip = "167.99.130.80" # Твой статический IP с DigitalOcean
    
    perm = 'Spot' if strategy == 'cgt' else 'Futures'
    
    # Use canonical_exchange for the message
    msg_text = get_text(user_id, "msg_exchange_config", exchange=canonical_exchange, link=link, perm=perm, ip=server_ip)
    
    await update.message.reply_text(msg_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    
    # Отправка ФОТО (Твой код)
    try:
        # Для OKX убедись, что папка называется okx_pic
        folder_path = os.path.join("instructions", f"{canonical_exchange.lower()}_pic")
        if os.path.exists(folder_path):
            files = [f for f in os.listdir(folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            files.sort()
            if files:
                media_group = []
                for file_name in files[:10]:
                    file_path_img = os.path.join(folder_path, file_name)
                    media_group.append(InputMediaPhoto(open(file_path_img, "rb")))
                if media_group:
                    await update.message.reply_media_group(media=media_group)
    except Exception as e:
        print(f"Error sending instructions: {e}")

    # Клавиатура "Назад"
    keyboard = [[get_text(user_id, "btn_back")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        get_text(user_id, "msg_enter_api_key"),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return ASK_API_KEY

async def ask_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 4: Получение API Key."""
    api_key = update.message.text.strip()
    user_id = update.effective_user.id
    
    if api_key in ["Back to Main Menu ⬅️", get_text(user_id, "btn_back")]:
        return await cancel(update, context)
        
    if len(api_key) < 10: 
        await update.message.reply_text(get_text(user_id, "err_api_key_short"), parse_mode=ParseMode.HTML)
        return ASK_API_KEY

    context.user_data['api_key'] = api_key
    
    keyboard = [[get_text(user_id, "btn_back")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        get_text(user_id, "msg_enter_secret_key"),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return ASK_SECRET_KEY

# async def ask_secret_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Шаг 5: Сохранение всего (Ключи + Стратегия)."""
#     secret_key = update.message.text.strip()
    
#     if secret_key == "Back to Main Menu ⬅️":
#         return await cancel(update, context)

#     if len(secret_key) < 10:
#         await update.message.reply_text("❌ <b>Invalid Secret Key</b>\nTry again.", parse_mode=ParseMode.HTML)
#         return ASK_SECRET_KEY

#     user_id = update.effective_user.id
#     exchange = context.user_data['exchange_name']
#     api_key = context.user_data['api_key']
#     strategy = context.user_data.get('strategy', 'ratner') # Получаем стратегию
    
#     # 1. Сохраняем ключи
#     save_user_api_keys(user_id, exchange, api_key, secret_key)
#     # 2. Сохраняем стратегию
#     set_user_strategy(user_id, strategy)
    
#     context.user_data.clear()
    
#     main_keyboard = [
#         ["Analyze Chart 📈", "Copy Trade 🚀"],
#         ["View Chart 📊", "Profile 👤"],
#         ["Risk Settings ⚙️"]
#     ]
#     reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
    
#     await update.message.reply_text(
#         f"✅ <b>Connected Successfully!</b>\n\n"
#         f"Exchange: <b>{exchange.capitalize()}</b>\n"
#         f"Strategy: <b>{strategy.upper()}</b>\n\n"
#         "Aladdin is now ready to copy trades according to your strategy.",
#         reply_markup=reply_markup,
#         parse_mode=ParseMode.HTML
#     )
#     return ConversationHandler.END

async def ask_secret_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Получает Secret Key. 
    Если биржа OKX -> запрашивает Passphrase. 
    Если другая -> сохраняет и завершает.
    """
    secret_key = update.message.text.strip()
    user_id = update.effective_user.id
    
    if secret_key in ["Back to Main Menu ⬅️", get_text(user_id, "btn_back")]:
        return await cancel(update, context)

    if len(secret_key) < 10:
        await update.message.reply_text(get_text(user_id, "err_secret_key_short"), parse_mode=ParseMode.HTML)
        return ASK_SECRET_KEY

    # Сохраняем секрет во временное хранилище
    context.user_data['secret_key'] = secret_key
    exchange = context.user_data['exchange_name']
    
    # --- IF OKX -> ASK PASSPHRASE --- #
    if exchange == 'okx':
        keyboard = [[get_text(user_id, "btn_back")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            get_text(user_id, "msg_enter_passphrase"),
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return ASK_PASSPHRASE
    
    # --- IF OTHERS (Binance, Bybit..) -> VALIDATE & ASK CAPITAL --- #
    # Validate keys immediately
    msg_checking = await update.message.reply_text(get_text(user_id, "msg_checking_balances"))
    
    api_key = context.user_data['api_key']
    
    # Check connection & fetch balance
    balance = await fetch_exchange_balance_safe(exchange, api_key, secret_key)
    
    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_checking.message_id)
    
    if balance is None:
        await update.message.reply_text(get_text(user_id, "status_error"))
        return ASK_SECRET_KEY
        
    context.user_data['balance'] = balance
    return await ask_reserve_start(update, context)

async def ask_passphrase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает Passphrase (только для OKX) и сохраняет."""
    passphrase = update.message.text.strip()
    user_id = update.effective_user.id
    
    if passphrase in ["Back to Main Menu ⬅️", get_text(user_id, "btn_back")]:
        return await cancel(update, context)
    
    context.user_data['passphrase'] = passphrase
    
    # Validate OKX keys & Fetch Balance
    msg_checking = await update.message.reply_text(get_text(user_id, "msg_checking_balances"))
    
    exchange = context.user_data['exchange_name'] # okx
    api_key = context.user_data['api_key']
    secret_key = context.user_data['secret_key']
    
    balance = await fetch_exchange_balance_safe(exchange, api_key, secret_key, passphrase)
    
    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_checking.message_id)
    
    if balance is None:
        await update.message.reply_text(get_text(user_id, "status_error"))
        return ASK_PASSPHRASE
        
    context.user_data['balance'] = balance
    return await ask_reserve_start(update, context)

async def ask_reserve_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 5 (или 6 для OKX): Спрашиваем про резерв."""
    user_id = update.effective_user.id
    
    keyboard = [[get_text(user_id, "btn_skip")], [get_text(user_id, "btn_cancel")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    # Show Balance and Ask for Trading Capital
    balance = context.user_data.get('balance', 0.0)
    
    await update.message.reply_text(
        get_text(user_id, "msg_ask_reserve", balance=f"{balance:.2f}"),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return ASK_RESERVE

async def ask_reserve_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Финальный шаг: Сохраняем все данные вместе с резервом."""
    user_id = update.effective_user.id
    text = update.message.text
    
    # Default: Use ALL available balance if skipped (Capital = Balance)
    balance = context.user_data.get('balance', 0.0)
    capital_amount = balance # Default if skipped
    
    if text not in ["Skip ⏩", "Пропустить ⏩", "Пропустити ⏩", get_text(user_id, "btn_skip")]:
        # Parse entered Capital Amount
        try:
            val = float(text)
            if val < 0: raise ValueError
            
            # Validation: Capital cannot exceed Balance
            if val > balance:
                 await update.message.reply_text(
                     f"❌ <b>Invalid Amount</b>\n"
                     f"Trading Capital cannot exceed your balance (${balance:.2f}).\n"
                     f"Please enter a valid amount.",
                     parse_mode=ParseMode.HTML
                 )
                 return ASK_RESERVE
                 
            capital_amount = val
        except ValueError:
            await update.message.reply_text(get_text(user_id, "err_invalid_reserve"))
            return ASK_RESERVE

    # Достаем все данные из контекста
    exchange = context.user_data['exchange_name']
    api_key = context.user_data['api_key']
    secret_key = context.user_data['secret_key']
    passphrase = context.user_data.get('passphrase')
    strategy = context.user_data.get('strategy', 'bro-bot')

    # 1. Save Exchange Connection + Trading Capital
    save_user_exchange(user_id, exchange, api_key, secret_key, passphrase, strategy)
    update_exchange_reserve(user_id, exchange, capital_amount)
    
    # 2. IF TRADEMAX (OKX) -> ASK FOR RISK %
    if strategy == 'cgt': # TradeMax
        # Default risk in DB is 1.0 via migration
        await update.message.reply_text(
            f"⚖️ <b>Risk Settings ({exchange.capitalize()})</b>\n\n"
            f"How much of your Trading Capital do you want to risk per trade?\n"
            f"Enter a number (e.g., <b>1</b> for 1%).\n\n"
            f"<i>Calculated Entry Size: ${capital_amount * 0.01:.2f} (at 1% risk)</i>",
            parse_mode=ParseMode.HTML
        )
        return ASK_RISK_FINISH

    # Bro-Bot -> Finish
    context.user_data.clear()
    
    main_keyboard = [
        [get_text(user_id, "btn_copytrade")],
        [get_text(user_id, "btn_viewchart"), get_text(user_id, "btn_profile")]
    ]
    reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
    
    display_strategy = "TradeMax" if strategy.lower() == 'cgt' else strategy.upper()
    await update.message.reply_text(
        get_text(user_id, "msg_reserve_saved", exchange=exchange.capitalize(), strategy=display_strategy, reserve=f"{capital_amount:.2f}"),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

async def ask_risk_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Saves the risk percentage for the new connection."""
    user_id = update.effective_user.id
    text = update.message.text
    
    # Parse Risk
    risk_pct = 1.0
    try:
        val = float(text)
        if val <= 0 or val > 100: raise ValueError
        risk_pct = val
    except ValueError:
        await update.message.reply_text("❌ Invalid Percentage. Please enter a number between 0.1 and 100.")
        return ASK_RISK_FINISH
        
    exchange = context.user_data['exchange_name']
    capital = context.user_data.get('balance', 0.0) # Actually stored in DB already, but for display
    # Better: fetch from DB or assume passed logic
    # We just updated DB with capital_amount in ask_reserve_finish
    
    update_exchange_risk(user_id, exchange, risk_pct)
    
    context.user_data.clear()
    
    main_keyboard = [
        [get_text(user_id, "btn_copytrade")],
        [get_text(user_id, "btn_viewchart"), get_text(user_id, "btn_profile")]
    ]
    reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
    
    strategy_disp = "TradeMax" # We know it is TradeMax here
    # Re-fetch capital just for display if needed, or rely on msg
    # Use generic success msg
    
    await update.message.reply_text(
        f"✅ <b>Setup Complete!</b>\n\n"
        f"Strategy: <b>{strategy_disp}</b>\n"
        f"Risk per Trade: <b>{risk_pct}%</b>\n\n"
        f"Aladdin is now ready to trade.",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [get_text(user_id, "btn_copytrade")],
        [get_text(user_id, "btn_viewchart"), get_text(user_id, "btn_profile")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(get_text(user_id, "msg_operation_cancelled"), reply_markup=reply_markup)
    context.user_data.clear()
    return ConversationHandler.END


# --- RISK MANAGEMENT CONVERSATION ---

async def risk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the risk settings conversation."""
    user_id = update.effective_user.id
    settings = get_user_risk_settings(user_id)
    await update.message.reply_text(
        get_text(user_id, "msg_risk_setup_start", balance=settings['balance']),
        reply_markup=ReplyKeyboardRemove()
    )
    return ASK_BALANCE

async def ask_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    user_id = update.effective_user.id
    if text != 'skip':
        try:
            balance = float(text)
            if balance <= 0: raise ValueError
            context.user_data['risk_balance'] = balance
        except ValueError:
            await update.message.reply_text(get_text(user_id, "err_invalid_balance"))
            return ASK_BALANCE
    
    settings = get_user_risk_settings(user_id)
    await update.message.reply_text(
        get_text(user_id, "msg_risk_pct_current", risk_pct=settings['risk_pct'])
    )
    return ASK_RISK_PCT

async def ask_risk_pct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = get_user_risk_settings(user_id)
    
    # Get balance from previous step or DB
    balance = context.user_data.get('risk_balance', settings['balance'])
    risk_pct = settings['risk_pct']
    
    text = update.message.text.lower()
    if text != 'skip':
        try:
            risk_pct_new = float(text)
            if not (0 < risk_pct_new <= 100): raise ValueError
            risk_pct = risk_pct_new
        except ValueError:
            await update.message.reply_text(get_text(user_id, "err_invalid_risk_pct"))
            return ASK_RISK_PCT
            
    # Save to DB
    update_user_risk_settings(user_id, balance, risk_pct)
    
    keyboard = [
        [get_text(user_id, "btn_copytrade")],
        [get_text(user_id, "btn_viewchart"), get_text(user_id, "btn_profile")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        get_text(user_id, "msg_risk_updated", balance=balance, risk_pct=risk_pct),
        reply_markup=reply_markup
    )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the risk setup process."""
    user_id = update.effective_user.id
    keyboard = [
        [get_text(user_id, "btn_copytrade")],
        [get_text(user_id, "btn_viewchart"), get_text(user_id, "btn_profile")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(get_text(user_id, "msg_risk_cancelled"), reply_markup=reply_markup)
    context.user_data.clear()
    return ConversationHandler.END

# --- VIEW CHART FUNCTION ---

async def view_chart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открывает TradingView для просмотра графиков"""
    user_id = update.effective_user.id
    # Создаем Inline-кнопку, которая ведет на TradingView
    inline_keyboard = [[
        InlineKeyboardButton(get_text(user_id, "btn_view_tradingview"), url="https://www.tradingview.com/chart/")
    ]]
    inline_reply_markup = InlineKeyboardMarkup(inline_keyboard)
    
    await update.message.reply_text(get_text(user_id, "msg_view_chart"), parse_mode=ParseMode.HTML, reply_markup=inline_reply_markup)

# --- ADMIN PANEL FUNCTIONS WITH PROMOCODES ---

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в админ-панель."""
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return
    keyboard = [
        ["User Stats 👥", "Withdrawals 🏧"], 
        ["Generate Promos 🎟️", "Broadcast 📢"], 
        ["Back to Main Menu ⬅️"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("👑 Welcome to the Admin Panel!", reply_markup=reply_markup)

async def handle_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает общую статистику и отчет по пользователям."""
    stats = get_admin_stats()
    users_report = get_active_users_report()
    
    stats_text = (
        f"📊 <b>Overall Statistics</b> 📊\n\n"
        f"Total Users: <b>{stats['total_users']}</b>\n"
        f"Active Subscribers: <b>{stats['active_users']}</b>\n"
        f"Pending Payment: <b>{stats['pending_payment']}</b>\n\n"
        f"Total Token Balance (all users): <b>{stats['total_tokens']:.2f}</b>\n"
        f"Pending Withdrawals: <b>{stats['pending_withdrawals_count']}</b> requests for <b>{stats['pending_withdrawals_sum']:.2f}</b> USDT.\n\n"
        f"🎟️ <b>Promo Codes Stats:</b>\n"
        f"Total Codes: <b>{stats['total_promo_codes']}</b>\n"
        f"Used Codes: <b>{stats['used_promo_codes']}</b>\n"
        f"Available Codes: <b>{stats['available_promo_codes']}</b>"
    )
    await update.message.reply_text(stats_text, parse_mode=ParseMode.HTML)

    if not users_report:
        await update.message.reply_text("No active users found.")
        return

    report_text = "👥 <b>Active Users Report (Recent 20)</b> 👥\n\n"
    for user in users_report:
        report_text += (
            f"👤 <b>User:</b> <code>{user['user_id']}</code> (@{user['username']})\n"
            f"   - Balance: <b>{user['balance']:.2f}</b> USDT\n"
            f"   - Referrals: L1: <b>{user['referrals']['l1']}</b>\n"
            f"--------------------\n"
        )
    
    await update.message.reply_text(report_text, parse_mode=ParseMode.HTML)

async def handle_admin_withdrawals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список заявок на вывод."""
    withdrawals = get_pending_withdrawals()
    
    if not withdrawals:
        await update.message.reply_text("✅ No pending withdrawal requests.")
        return

    report_text = "🏧 <b>Pending Withdrawal Requests</b> 🏧\n\n"
    for req in withdrawals:
        req_id, user_id, amount, wallet, date = req
        report_text += (
            f"<b>Request ID: #{req_id}</b>\n"
            f"  - User ID: <code>{user_id}</code>\n"
            f"  - Amount: <b>{amount:.2f}</b> USDT\n"
            f"  - Wallet (BEP-20): <code>{wallet}</code>\n"
            f"  - Date: {date}\n"
            f"--------------------\n"
        )
    
    await update.message.reply_text(report_text, parse_mode=ParseMode.HTML)

# --- PROMO CODE GENERATION CONVERSATION ---

# async def generate_promos_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Начинает диалог генерации промокодов."""
#     await update.message.reply_text("How many promo codes do you want to generate? (e.g., 10)", reply_markup=ReplyKeyboardRemove())
#     return ASK_PROMO_COUNT

# async def generate_promos_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Получает количество, генерирует и отправляет промокоды."""
#     try:
#         count = int(update.message.text)
#         if not (0 < count <= 100): # Ограничим до 100 за раз
#             raise ValueError
#     except ValueError:
#         await update.message.reply_text("Please enter a valid number between 1 and 100.")
#         return ASK_PROMO_COUNT

#     await update.message.reply_text(f"Generating {count} promo codes, please wait...")
    
#     new_codes = generate_promo_codes(count)
    
#     # Отправляем коды в текстовом файле, чтобы их было удобно копировать
#     codes_text = "\n".join(new_codes)
#     file_path = "promo_codes.txt"
#     with open(file_path, "w") as f:
#         f.write(codes_text)
    
#     await context.bot.send_document(
#         chat_id=update.effective_chat.id,
#         document=open(file_path, "rb"),
#         caption=f"✅ Here are your {count} new promo codes."
#     )
#     os.remove(file_path) # Удаляем временный файл
    
#     # Возвращаем админ-клавиатуру
#     keyboard = [["User Stats 👥", "Withdrawals 🏧"], ["Generate Promos 🎟️"], ["Back to Main Menu ⬅️"]]
#     reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
#     await update.message.reply_text("What would you like to do next?", reply_markup=reply_markup)
    
#     return ConversationHandler.END


# --- НОВЫЙ ДИАЛОГ ГЕНЕРАЦИИ ПРОМОКОДОВ ---
async def generate_promos_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("How many promo codes do you want to generate? (e.g., 10)")
    return ASK_PROMO_COUNT

async def generate_promos_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        count = int(update.message.text)
        if not (0 < count <= 100): raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a valid number between 1 and 100."); return ASK_PROMO_COUNT

    context.user_data['promo_count'] = count
    
    # Создаем кнопки для выбора срока действия
    keyboard = [
        ["1 day", "7 days"],
        ["15 days", "30 days"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Great. Now select the duration for these codes:", reply_markup=reply_markup)
    return ASK_PROMO_DURATION


async def generate_promos_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    duration_map = {"1 day": 1, "7 days": 7, "15 days": 15, "30 days": 30}
    duration_text = update.message.text
    
    if duration_text not in duration_map:
        await update.message.reply_text("Please select a valid duration from the buttons."); return ASK_PROMO_DURATION

    duration_days = duration_map[duration_text]
    count = context.user_data['promo_count']
    
    await update.message.reply_text(f"Generating {count} promo codes for {duration_days} days...", reply_markup=ReplyKeyboardRemove())
    
    new_codes = generate_promo_codes(count, duration_days)
    
    codes_text = "\n".join(new_codes)
    file_path = f"promo_codes_{count}_{duration_days}d.txt"
    with open(file_path, "w") as f:
        f.write(codes_text)
    
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=open(file_path, "rb"),
        caption=f"✅ Here are your {count} new promo codes, each valid for {duration_days} days."
    )
    os.remove(file_path)
    
    # Возвращаем админ-клавиатуру
    keyboard = [["User Stats 👥", "Withdrawals 🏧"], ["Generate Promos 🎟️"], ["Back to Main Menu ⬅️"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Promo codes generated. What would you like to do next?", reply_markup=reply_markup)
    
    context.user_data.clear()
    return ConversationHandler.END

# --- ОБНОВЛЕННЫЙ text_handler для активации по промокоду ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    # --- Админ-панель ---
    if user_id == ADMIN_USER_ID:
        if text == "User Stats 👥": await handle_admin_stats(update, context); return
        elif text == "Withdrawals 🏧": await handle_admin_withdrawals(update, context); return
        # Кнопка Generate Promos теперь запускает диалог, поэтому ее здесь нет
        elif text in ["Back to Main Menu ⬅️", get_text(user_id, "btn_back")]:
            keyboard = [
                [get_text(user_id, "btn_copytrade")],
                [get_text(user_id, "btn_viewchart"), get_text(user_id, "btn_profile")]
            ]
            
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(get_text(user_id, "msg_returned_main"), reply_markup=reply_markup)
            return
            
    # --- ПРОВЕРКА НА ПРОМОКОД ---
    # --- ПРОВЕРКА НА ПРОМОКОД ---
    if text.upper().startswith("ALADDIN-"):
        if get_user_status(user_id) == 'active':
            await update.message.reply_text(get_text(user_id, "err_account_already_active")); return

        await update.message.reply_text(get_text(user_id, "msg_checking_promo"))
        
        # validate_and_use... теперь возвращает срок действия или None
        duration_days = validate_and_use_promo_code(text, user_id)
        
        if duration_days:
            activate_user_subscription(user_id, duration_days=duration_days)
            
            keyboard = [
                [get_text(user_id, "btn_copytrade")],
                [get_text(user_id, "btn_viewchart"), get_text(user_id, "btn_profile")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(get_text(user_id, "msg_promo_success", duration=duration_days), reply_markup=reply_markup)
        else:
            await update.message.reply_text(get_text(user_id, "err_promo_invalid"))
        return

    # --- Основные кнопки ---
    # if text in get_all_translations("btn_analyze"): await analyze_chart_start(update, context)
    elif text in get_all_translations("btn_viewchart"): await view_chart_command(update, context)
    elif text in get_all_translations("btn_profile"): await profile_command(update, context)
    elif text in get_all_translations("btn_my_exchanges"): await my_exchanges_command(update, context)
    elif text in get_all_translations("btn_top_up"): await top_up_balance_command(update, context)
    elif text in get_all_translations("btn_copytrade"):
        await connect_exchange_start(update, context)
    # elif text in get_all_translations("btn_risk"):
    #     await risk_command(update, context)
    elif text in get_all_translations("btn_withdraw"):  
        await withdraw_start(update, context)
    elif text in get_all_translations("btn_language"):
        await change_language_start(update, context)
    elif text in get_all_translations("btn_cancel"):
        await cancel(update, context)
    elif text in ["Back to Menu ↩️", "Back to Main Menu ⬅️"] or text in get_all_translations("btn_back"):
        keyboard = [
            [get_text(user_id, "btn_copytrade")],
            [get_text(user_id, "btn_viewchart"), get_text(user_id, "btn_profile")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(get_text(user_id, "msg_main_menu"), reply_markup=reply_markup)
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
    # Кнопки Risk, Withdraw, Back to Menu обрабатываются своими диалогами или как здесь
        # --- НОВЫЙ БЛОК ДЛЯ КНОПКИ EXPLAIN ---
    elif text in get_all_translations("btn_explain"):
        # Возвращаем пользователя в основное меню
        keyboard = [
            [get_text(user_id, "btn_copytrade")],
            [get_text(user_id, "btn_viewchart"), get_text(user_id, "btn_profile")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(get_text(user_id, "msg_getting_explanation"), reply_markup=reply_markup)

        # Вызываем тот же код, что был в explain_analysis_handler
        analysis_context = context.user_data.get('last_analysis_context')
        if not analysis_context:
            await update.message.reply_text(get_text(user_id, "err_context_expired"))
            return

        thinking_message = await update.message.reply_text(get_text(user_id, "msg_aladdin_thinking"), parse_mode=ParseMode.HTML)
        lang = get_user_language(user_id)
        explanation = get_explanation(analysis_context, lang=lang)
        await thinking_message.edit_text(explanation, parse_mode=ParseMode.MARKDOWN)
    # --- Проверка на TxHash ---
    # elif text.startswith("0x") and len(text) == 66:
    #     if get_user_status(user_id) == 'active':
    #         await update.message.reply_text("Your account is already active."); return
    #     await update.message.reply_text("Verifying transaction, please wait...")
    #     await verify_payment_and_activate(text, user_id, context)
    # else:
    #     pass
        # --- ОБНОВЛЕННАЯ ПРОВЕРКА НА ХЭШ ТРАНЗАКЦИИ ---
    elif text.startswith("0x") and len(text) == 66:
        status = get_user_status(user_id)
        
        # Если юзер еще не активен, это оплата подписки
        if status != 'active':
            await update.message.reply_text(get_text(user_id, "msg_verifying_payment"))
            await verify_payment_and_activate(text, user_id, context)
        
        # Если юзер уже активен, это пополнение баланса
        # else:
        #     await update.message.reply_text("Verifying your balance top-up...")
        #     is_valid, message, amount = await verify_top_up_payment(text, user_id)
        #     if is_valid:
        #         credit_tokens_from_payment(user_id, amount)
        #         mark_tx_hash_as_used(text)
        #         await update.message.reply_text(f"✅ Success! Your balance has been topped up with {amount:.2f} tokens.")
        #     else:
        #         await update.message.reply_text(f"❌ Top-up failed.\nReason: {message}")
        # return
        # Сценарий 2: Пополнение баланса
        else:
            await update.message.reply_text(get_text(user_id, "msg_verifying_top_up"))
            # is_valid, message, amount = await verify_top_up_payment(text)
            is_valid, message, amount = await verify_top_up_payment(text, user_id)
            
            if is_valid:
                # --- НОВАЯ ЛОГИКА РАЗБЛОКИРОВКИ ---
                profile_before_topup = get_user_profile(user_id)
                
                credit_tokens_from_payment(user_id, amount)
                mark_tx_hash_as_used(text)
                
                profile_after_topup = get_user_profile(user_id)
                new_balance = profile_after_topup['balance']
                
                await update.message.reply_text(get_text(user_id, "msg_topup_success", amount=amount, new_balance=new_balance))

                # ПРОВЕРКА НА РАЗБЛОКИРОВКУ
                # Если баланс был <= 0, а стал > 0, включаем копи-трейдинг
                if profile_before_topup['balance'] <= 0 and new_balance > 0:
                    set_copytrading_status(user_id, is_enabled=True)
                    await update.message.reply_text(get_text(user_id, "msg_copy_trading_reenabled"))
            else:
                await update.message.reply_text(get_text(user_id, "err_top_up_failed", reason=message))
        return
    


# --- Enhanced Text & Button Handler ---

# async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     text = update.message.text
#     user_id = update.effective_user.id

#     # --- Сначала проверяем, не админ ли это и не в админ-панели ли он ---
#     if user_id == ADMIN_USER_ID:
#         if text == "User Stats 👥":
#             await handle_admin_stats(update, context)
#             return
#         elif text == "Withdrawals 🏧":
#             await handle_admin_withdrawals(update, context)
#             return
#         elif text == "Generate Promos 🎟️":
#             await generate_promos_start(update, context)
#             return
#         elif text == "Back to Main Menu ⬅️":
#             # Возвращаем обычную клавиатуру
#             keyboard = [
#                 ["Analyze Chart 📈", "View Chart 📊"],
#                 ["Profile 👤", "Risk Settings ⚙️"]
#             ]
#             reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
#             await update.message.reply_text("Returned to main menu.", reply_markup=reply_markup)
#             return
            
#     # --- ТЕПЕРЬ ПРОВЕРЯЕМ НА ПРОМОКОД ---
#     if text.upper().startswith("ALADDIN-"):
#         if get_user_status(user_id) == 'active':
#             await update.message.reply_text("Your account is already active.")
#             return

#         await update.message.reply_text("Checking your promo code...")
        
#         is_valid = validate_and_use_promo_code(text, user_id)
        
#         if is_valid:
#             # Активируем подписку и делаем все то же, что и при оплате
#             referrer_id = activate_user_subscription(user_id)
            
#             # Начисляем реферальные бонусы, если есть реферер
#             if referrer_id:
#                 referral_chain = get_referrer_chain(user_id, levels=3)
#                 rewards = [15, 10, 5]
                
#                 for i, referrer_user_id in enumerate(referral_chain):
#                     if i < len(rewards):
#                         reward_amount = rewards[i]
#                         credit_referral_tokens(referrer_user_id, reward_amount)
#                         try:
#                             await context.bot.send_message(
#                                 referrer_user_id, 
#                                 f"🎉 Congratulations! You received {reward_amount} tokens from a level {i+1} referral."
#                             )
#                         except Exception as e:
#                             print(f"Could not notify referrer {referrer_user_id}: {e}")
            
#             keyboard = [
#                 ["Analyze Chart 📈", "View Chart 📊"],
#                 ["Profile 👤", "Risk Settings ⚙️"]
#             ]
#             reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
#             await update.message.reply_text("✅ Promo code accepted! Welcome to Aladdin. You now have full access.", reply_markup=reply_markup)
#         else:
#             await update.message.reply_text("❌ This promo code is invalid or has already been used.")
#         return

#     # Handle main menu buttons
#     if text == "Analyze Chart 📈": 
#         await analyze_chart_start(update, context)
#     elif text == "View Chart 📊":
#         await view_chart_command(update, context)
#     elif text == "Profile 👤": 
#         await profile_command(update, context)
#     elif text == "Risk Settings ⚙️":
#         await risk_command(update, context)
#     elif text == "Withdraw Tokens 💵":
#         await withdraw_start(update, context)
#     elif text == "Back to Menu ↩️":
#         keyboard = [
#             ["Analyze Chart 📈", "View Chart 📊"],
#             ["Profile 👤", "Risk Settings ⚙️"]
#         ]
#         reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
#         await update.message.reply_text("Main menu:", reply_markup=reply_markup)
    
#     # Handle TxHash for payment
#     elif text.startswith("0x") and len(text) == 66:
#         if get_user_status(update.effective_user.id) == 'active':
#             await update.message.reply_text("Your account is already active.")
#             return
#         await update.message.reply_text("Verifying transaction, please wait...")
#         await verify_payment_and_activate(text, update.effective_user.id, context)
#     else:
#         await update.message.reply_text("Unknown command. Please use the buttons below.")

# async def analyze_chart_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Enhanced chart analysis with subscription check"""
#     if not has_access(update.effective_user.id):
#         await update.message.reply_text("❌ Access Required. Please use /start to activate your subscription.")
#         return
#     await update.message.reply_text("I'm ready! Please send a clear screenshot of a candlestick chart.")

async def analyze_chart_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Remove strict check here. The daily limit check is handled inside photo_handler -> check_request_limit
    # if get_user_status(user_id) != 'active':
    #     await update.message.reply_text(get_text(user_id, "err_access_required"))
    #     return
    await update.message.reply_text(
        get_text(user_id, "msg_send_chart"),
        parse_mode=ParseMode.HTML
    )


# --- НОВЫЙ ОБРАБОТЧИК ДЛЯ КНОПКИ "EXPLAIN" ---
# async def explain_analysis_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     query = update.callback_query
#     await query.answer()

#     # Убираем все кнопки с исходного сообщения, чтобы избежать повторных нажатий
#     try:
#         await query.edit_message_reply_markup(reply_markup=None)
#     except Exception as e:
#         print(f"Could not remove keyboard: {e}") # Игнорируем ошибку, если не удалось
    
#     analysis_context = context.user_data.get('last_analysis_context')
#     if not analysis_context:
#         await query.message.reply_text("Sorry, the context for this analysis has expired. Please run a new analysis.")
#         return

#     # Отправляем новое сообщение "думаю..."
#     thinking_message = await query.message.reply_text("<i>Aladdin is thinking... 🧞‍♂️</i>", parse_mode=ParseMode.HTML)
    
#     # Получаем объяснение от LLM
#     explanation = get_explanation(analysis_context)
    
#     # Редактируем сообщение "думаю..." на финальный ответ
#     await thinking_message.edit_text(explanation, parse_mode=ParseMode.MARKDOWN)

# bot.py

async def explain_analysis_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass 
    
    analysis_context = context.user_data.get('last_analysis_context')
    if not analysis_context:
        await query.message.reply_text("Sorry, the context for this analysis has expired. Please run a new analysis.")
        return

    user_id = update.effective_user.id
    thinking_message = await query.message.reply_text(get_text(user_id, "msg_aladdin_thinking"), parse_mode=ParseMode.HTML)
    
    lang = get_user_language(user_id)
    explanation = await asyncio.to_thread(get_explanation, analysis_context, lang=lang)
    
    await thinking_message.edit_text(explanation, parse_mode=ParseMode.MARKDOWN)


async def daily_subscription_check(context: ContextTypes.DEFAULT_TYPE):
    """Каждый день проверяет, деактивирует истекшие подписки и отключает копи-трейдинг."""
    print("--- [SCHEDULER] Running daily subscription check ---")
    
    # 1. Эта функция меняет статус юзера в БД на 'expired' и возвращает ID
    expired_user_ids = check_and_expire_subscriptions()
    
    for user_id in expired_user_ids:
        # 2. !!! ВАЖНОЕ ДОБАВЛЕНИЕ !!!
        # Мы физически отключаем копирование сделок для этого юзера
        set_copytrading_status(user_id, is_enabled=False)
        
        try:
            # 3. Отправляем уведомление
            await context.bot.send_message(
                user_id,
                get_text(user_id, "msg_subscription_expired"),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            print(f"Failed to notify expired user {user_id}: {e}")

def main():
    print("Starting bot with Enhanced Subscription & Referral System & Admin Panel & View Chart & Promocodes...")
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    job_queue = application.job_queue
    # Запускать каждый день в 00:05 по UTC
    job_queue.run_daily(daily_subscription_check, time=datetime.strptime("00:05", "%H:%M").time())
    # Withdrawal conversation handler
    withdraw_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Withdraw Tokens 💰$|' + '|'.join([f"^{v}$" for v in get_all_translations("btn_withdraw")])), withdraw_start)],  
        states={
            ASK_AMOUNT: [MessageHandler(filters.Regex('^Cancel$'), cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, ask_amount)],
            ASK_WALLET: [ MessageHandler(filters.Regex('^Cancel$'), cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, ask_wallet)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Risk management conversation handler
    risk_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('risk', risk_command)],
        states={
            ASK_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_balance)],
            ASK_RISK_PCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_risk_pct)],
        },
        fallbacks=[CommandHandler('cancel', cancel_risk)]
    )
    
    # Promo code generation conversation handler
    promo_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Generate Promos 🎟️$'), generate_promos_start)],
        states={
            ASK_PROMO_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, generate_promos_count)],
            ASK_PROMO_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, generate_promos_duration)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Edit Reserve conversation handler
    # Catch buttons like "Edit Reserve (Binance) 🛡️", "Изм. Резерв (Binance) 🛡️"
    edit_reserve_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r".*(Reserve|Резерв|Capital|Капитал|Капітал|Settings|Настройки|Налаштування).*"), edit_reserve_start)],
        states={
            ASK_EDIT_SELECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_selection_handler)],
            ASK_EDIT_CAPITAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_capital_save)],
            ASK_EDIT_RISK: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_risk_save)]
        },
        fallbacks=[
            CommandHandler('cancel', cancel_edit_reserve),
            MessageHandler(filters.Regex('^Back to Main Menu ⬅️$|' + '|'.join([f"^{v}$" for v in get_all_translations("btn_back")])), cancel_edit_reserve)
        ]
    )
    broadcast_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Broadcast 📢$'), broadcast_start)],
        states={
            ASK_BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_ask_confirmation)],
            CONFIRM_BROADCAST: [
                MessageHandler(filters.Regex('^SEND NOW ✅$'), broadcast_send_message),
                MessageHandler(filters.Regex('^Cancel ❌$'), cancel) # Используем общую отмену
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    lang_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Language 🌍$|' + '|'.join([f"^{v}$" for v in get_all_translations("btn_language")])), change_language_start)],
        states={
            SELECT_LANG: [
                MessageHandler(filters.Regex('^(' + '|'.join([f"^{v}$" for v in get_all_translations("btn_back")]) + ')$'), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_language)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    connect_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Copy Trade 🚀$|' + '|'.join([f"^{v}$" for v in get_all_translations("btn_copytrade")])), connect_exchange_start)],
        states={
            ASK_EXCHANGE: [
                MessageHandler(filters.Regex('^Back to Main Menu ⬅️$|' + '|'.join([f"^{v}$" for v in get_all_translations("btn_back")])), cancel), # Обработка кнопки Назад
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_exchange)
            ],
            ASK_API_KEY: [
                MessageHandler(filters.Regex('^Back to Main Menu ⬅️$|' + '|'.join([f"^{v}$" for v in get_all_translations("btn_back")])), cancel), # Обработка кнопки Назад
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_api_key)
            ],
            ASK_SECRET_KEY: [
                MessageHandler(filters.Regex('^Back to Main Menu ⬅️$|' + '|'.join([f"^{v}$" for v in get_all_translations("btn_back")])), cancel), # Обработка кнопки Назад
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_secret_key)
            ],
            ASK_STRATEGY: [
                MessageHandler(filters.Regex('^Cancel$|' + '|'.join([f"^{v}$" for v in get_all_translations("btn_cancel")])), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_strategy)
            ],
            ASK_PASSPHRASE: [
                MessageHandler(filters.Regex('^Back to Main Menu ⬅️$|' + '|'.join([f"^{v}$" for v in get_all_translations("btn_back")])), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_passphrase)
            ],
            ASK_RESERVE: [
                MessageHandler(filters.Regex('^Cancel$|' + '|'.join([f"^{v}$" for v in get_all_translations("btn_cancel")])), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_reserve_finish)
            ],
            ASK_RISK_FINISH: [
                MessageHandler(filters.Regex('^Cancel$|' + '|'.join([f"^{v}$" for v in get_all_translations("btn_cancel")])), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_risk_finish)
            ]
        },
        # fallbacks обрабатывают команды типа /cancel, но лучше добавить кнопку и сюда
        fallbacks=[
            CommandHandler('cancel', cancel),
            MessageHandler(filters.Regex('^Back to Main Menu ⬅️$|' + '|'.join([f"^{v}$" for v in get_all_translations("btn_back")])), cancel)
        ]
    )
    
    start_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            SELECT_LANG_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_initial_language)]
        },
        fallbacks=[CommandHandler("start", start_command)] # Allow restarting start if needed
    )
    
    application.add_handler(start_conv_handler)
    # application.add_handler(CommandHandler("start", start_command)) # Removed simple handler
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("admin", admin_command))  # Новая админ-команда
    application.add_handler(connect_conv_handler)
    application.add_handler(withdraw_conv_handler)
    application.add_handler(lang_conv_handler)
    application.add_handler(risk_conv_handler)
    application.add_handler(promo_conv_handler)
    application.add_handler(edit_reserve_conv_handler) # NEW
    application.add_handler(broadcast_conv_handler)
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    # --- НОВЫЙ ОБРАБОТЧИК ДЛЯ КНОПКИ ОБЪЯСНЕНИЯ ---
    application.add_handler(CallbackQueryHandler(explain_analysis_handler, pattern="^explain_analysis$"))
    
    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
