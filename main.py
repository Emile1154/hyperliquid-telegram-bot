# Hyperliquid Wallet Monitor → Telegram Bot

import time
from config import Config
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from typing import List, Dict, Optional
from models import Position, Trader
from hyperliquid import HyperliquidAPI
from datetime import datetime, timezone, timedelta
import shlex
import matplotlib.pyplot as plt
from io import BytesIO
import threading
import queue
# -----------------------------
# Event Processor
# -----------------------------
class EventMonitor(threading.Thread):
    def __init__(self, api: HyperliquidAPI, bot: TeleBot, config):
        self.api = api
        self.position_messages = {}  
        self.bot = bot
        self.cfg = config
        self.queue = queue.Queue()
        super().__init__(daemon=True)

    def push_event(self, trader, event_list):
        self.queue.put((trader, event_list))

    def run(self):
        while True:
            trader, event_list = self.queue.get()
            try:
                # отправка данных
                time.sleep(2)
                self.notify_fills(trader, event_list)
            except Exception as e:
                print("SenderThread error:", e)

            finally:
                self.queue.task_done()
                
    @staticmethod
    def get_wallet_name(trader_address, trader_name):
        name = trader_name or ""
        short = trader_address[:6] + "..." + trader_address[-4:]
        return f"{name} [{short}](https://app.hyperliquid.xyz/explorer/address/{trader_address})"
    
    @staticmethod
    def get_direction(pos):
        direction = "🔴 SHORT"        
        if pos.is_long:
            direction = "🟢 LONG"
        if pos.is_long is None:
            direction = "🔫 WAIT ORDER"

        return direction
    
    # " "dir": "Open Long","
    def event_print(self, ev, pos):
        # implement event print
        if "Long" in ev.direction:
            arrow = "🟢 LONG"
        elif "Short" in ev.direction:
            arrow = "🔴 SHORT"
        else:
            arrow = "⚪ ???"

        if "Open" in ev.direction:
            action = "OPEN"
        elif "Close" in ev.direction:
            action = "CLOSE"
        else:
            action = ev.direction.upper()

        if ev.start_position != 0:    
            percents =  ev.size*100/ev.start_position
        else:
            percents = 0
        page = (
            f"{arrow} *{action}* `#{ev.coin}` 💵 *Price*: `${ev.price}`\n"
            f"📏 *Size/PrevSize*: `{ev.size}`/ {ev.start_position} (#{ev.coin})\n"
            f"📊 *Percent Change*: `{percents:.1f}` %\n"
            f"💰 *Closed PnL*: `${ev.closedPnl}`\n"
        )  
        # time
        dt = datetime.fromtimestamp(ev.time / 1000).strftime("%Y-%m-%d %H:%M:%S")
        page += f"\n⏱ *Time:* `{dt}`\n"
        return page
    
    def position_print(self, pos, coin):
        leverage = f"🕹 {pos.leverage}X" 
        if pos.leverage < 2:
            leverage = ""
        main_info = (
            f"📢 *ACTIVE POSITION*\n"
            f"📈 {self.get_direction(pos)} `#{coin}` `{leverage}`\n"
            f"💰 Size: {pos.size} #{coin} ($`{pos.position_value}`) \n"
            f"⚡ Entry Price: {pos.entry} *UnPNL:* ${pos.unpnl:.1f} \n"               
        )
        
        page = main_info + f"📢 *LIMIT ORDERS*\n"
        for order in pos.buy_order:
            act = "ENTER"
            if order.action == "output":
                act = "EXIT"
            page += f"🟢 POS {act}: ${order.limit} VOL:({order.remain_size}/{order.size}) `#{coin}`\n"
        for order in pos.sell_order:
            act = "ENTER"
            if order.action == "output":
                act = "EXIT"
            page += f"🔴 POS {act}: ${order.limit} VOL:({order.remain_size}/{order.size}) `#{coin}`\n"
        page += "⚡ *TP & SL*\n"
        if pos.tp is None:
            page += "⛔️ TP doesn't exist\n"
        if pos.tp is not None:
            page += f"🚩 TP PRICE ${ pos.tp.limit} VOL: ({ pos.tp.remain_size}/{ pos.tp.size}) `#{coin}`\n"
        if pos.sl is None:
            page += f"💀 SL doesn't exist\n"
        if pos.sl is not None:
            page += f"🏁 SL PRICE ${ pos.sl.limit} VOL: ({ pos.sl.remain_size}/{ pos.sl.size}) `#{coin}`\n"
        return page
    
    def notify_active_position_info(self, trader:Trader, only_waits = False):
        if len(trader.positions) == 0:
            return
        
        find_mut = 0
        for pos in trader.positions.values():
            if pos.is_mod == True:
                find_mut = 1
        if find_mut == 0:
            return

        trader_info = (
            f"👤 {self.get_wallet_name(trader.address, trader.name)} 💰 Trader ROI & PnL: `{trader.roi:.1f}% ${trader.pnl:.1f}`"
        )
        try:
            self.bot.send_message(self.cfg.chat_id, trader_info, parse_mode="Markdown")
            time.sleep(2)
        except ApiTelegramException as e:
            if e.result_json and e.result_json.get("error_code") == 429:
                retry_after = e.result_json.get("parameters", {}).get("retry_after", 1)
                print(f"Rate limit hit, sleeping for {retry_after} seconds")
                time.sleep(retry_after)
                self.bot.send_message(self.cfg.chat_id, trader_info, parse_mode="Markdown")
        for coin in trader.positions.keys():
            pos = trader.positions[coin] 
            # if pos.is_mod == 0:
            #     continue
            if only_waits and pos.is_long is not None:
                continue

            page = self.position_print(pos, coin)
            
            try:
                sent = self.bot.send_message(self.cfg.chat_id, page, parse_mode="Markdown")
                self.position_messages[ (trader.address, coin) ] = sent.message_id
                time.sleep(5)
            except ApiTelegramException as e:
                if e.result_json and e.result_json.get("error_code") == 429:
                    retry_after = e.result_json.get("parameters", {}).get("retry_after", 1)
                    print(f"Rate limit hit, sleeping for {retry_after} seconds")
                    time.sleep(retry_after)
                    self.bot.send_message(self.cfg.chat_id, page, parse_mode="Markdown")

    def notify_fills(self, trader, events):
        trader_info = (
            f"👤 {self.get_wallet_name(trader.address, trader.name)} 💰 Trader ROI & PnL: `{trader.roi:.1f}% ${trader.pnl:.1f}`"
        )
        try:
            self.bot.send_message(self.cfg.chat_id, trader_info, parse_mode="Markdown")
            time.sleep(2)
        except ApiTelegramException as e:
            if e.result_json and e.result_json.get("error_code") == 429:
                retry_after = e.result_json.get("parameters", {}).get("retry_after", 1)
                print(f"Rate limit hit, sleeping for {retry_after} seconds")
                time.sleep(retry_after)
                self.bot.send_message(self.cfg.chat_id, trader_info, parse_mode="Markdown")
        
        for event in events:
            coin = event.coin
            pos = trader.positions[coin]
            self.api.position_update_local(pos,event)

            reply_to = self.position_messages.get( (trader.address, coin), None)
            msg = ""    
            page = self.position_print(pos, coin )
            
            event_page = "*UPDATE POSITION!*\n"+ self.event_print(event,pos) 
            if pos.is_long is None:
                event_page = "*POSITION CLOSED!*\n" + self.event_print(event,pos) 

            if reply_to is None or event.start_position == 0:
                try:
                    event_page = "*OPENED NEW POSITION!*\n" + self.event_print(event,pos) 
                    msg = event_page + page
                    sent = self.bot.send_message(self.cfg.chat_id, msg, parse_mode="Markdown")
                    self.position_messages[ (trader.address, coin) ] = sent.message_id
                except ApiTelegramException as e:
                    if e.result_json and e.result_json.get("error_code") == 429:
                        retry_after = e.result_json.get("parameters", {}).get("retry_after", 1)
                        print(f"Rate limit hit, sleeping for {retry_after} seconds")
                        time.sleep(retry_after)
                        self.bot.send_message(self.cfg.chat_id, msg, parse_mode="Markdown")
            else:
                #Position update    
                try:
                    msg = event_page + page
                    self.bot.send_message(self.cfg.chat_id, msg, parse_mode="Markdown", reply_to_message_id=reply_to)
                except ApiTelegramException as e:
                    if e.result_json and e.result_json.get("error_code") == 429:
                        retry_after = e.result_json.get("parameters", {}).get("retry_after", 1 )
                        print(f"Rate limit hit, sleeping for {retry_after} seconds")
                        time.sleep(retry_after)
                        self.bot.send_message(self.cfg.chat_id, msg, parse_mode="Markdown", reply_to_message_id=reply_to)
            time.sleep(4)

    def notify_leader_trades(self, traders):
        if not traders:
            msg = (
                f"Traders with PnL > {self.cfg.pnl_min} USD not found"
            )
            self.bot.send_message(self.cfg.chat_id, msg, parse_mode="Markdown")
            return
        
        
        MAX_LEN = 4000  # оставляем немного запас

        # сортировка: по PnL (убывание)
        traders_sorted = sorted(traders, key=lambda t: t.pnl, reverse=True)

        head = ["🏆 *Top Traders Update*\n"]
        head.append(f"Found {len(traders)} traders matching criteria (`PnL ≥ {self.cfg.pnl_min} USD and ROI ≥ {self.cfg.min_roi:.1f} %`)")
        head.append(f"Period : {self.cfg.period}")
        head_msg = '\n'.join(head)
        self.bot.send_message(
                self.cfg.chat_id,
                head_msg,
                parse_mode="Markdown"
            )
        time.sleep(5)
        lines = []
        for t in traders_sorted:
            # total_size = sum(p.size for p in t.positions) if t.positions else 0
            lines.append(
                f"👤 {self.get_wallet_name(t.address, t.name)}\n💰 *PnL:* {t.pnl:.1f} USD 🎯 *ROI:* {t.roi:.1f}% \n"
            )
        msg_blocks = []
        current_block = ""
        for line in lines:
            if len(current_block) + len(line) + 1 > MAX_LEN:
                msg_blocks.append(current_block)
                current_block = ""
            current_block += line + "\n"

        if current_block:
            msg_blocks.append(current_block)

        # отправка всех блоков
        for block in msg_blocks:
            try:
                self.bot.send_message(
                    self.cfg.chat_id,
                    block,
                    parse_mode="Markdown"
                )
            except ApiTelegramException as e:
                if e.result_json and e.result_json.get("error_code") == 429:
                    retry_after = e.result_json.get("parameters", {}).get("retry_after", 1)
                    print(f"Rate limit hit, sleeping for {retry_after} seconds")
                    time.sleep(retry_after)
                    self.bot.send_message(self.cfg.chat_id, block, parse_mode="Markdown")
            time.sleep(5)

class BotController:

    def __init__(self):
        self.config = Config()
        self.api = HyperliquidAPI(self.config)
        self.bot = TeleBot(self.config.token, parse_mode="Markdown")
        self.monitor = EventMonitor(self.api, self.bot, self.config)
        self.monitor.start()

        self.bot.send_message(self.config.chat_id, "🔄 loading datasets from Hyperliquid...", parse_mode="Markdown")

        self.traders = self.api.get_leaderboard(timeframe=self.config.period)
        # self.monitor.notify_leader_trades(self.traders)

        self.last_trader_load = {}
        for trader in self.traders:
            self.api.position_update(trader)
            self.api.load_limit_orders(trader)
            self.last_trader_load[trader.address] = time.time()
            # self.monitor.notify_active_position_info(trader)

        self.bot.send_message(self.config.chat_id, "🤖 Bot ready! send /help for see avail commands", parse_mode="Markdown")
        threading.Thread(target=self.run, daemon=True).start()
        self.register_handlers()
        self.bot.infinity_polling()

    # --------------------------
    # Universal Argument Parser
    # --------------------------
    def parse_args(self, text: str) -> dict:
        parts = shlex.split(text)
        parts = parts[1:] if parts and parts[0].startswith('/') else parts

        args = {}
        key = None
        for part in parts:
            if part.startswith('--'):
                key = part[2:]
                args[key] = True
            elif part.startswith('-') and len(part) == 2:
                key = part[1:]
                args[key] = True
            else:
                if key is None:
                    continue
                try:
                    if '.' in part:
                        value = float(part)
                    else:
                        value = int(part)
                except:
                    value = part
                args[key] = value
                key = None
        return args


    def text_bar(self, percent: float, size: int = 10) -> str:

        if percent < 0: percent = 0
        if percent > 1: percent = 1
 
        filled = int(percent * size)
        empty  = size - filled

        return "🟩" * filled + "🟥" * empty
    # --------------------------
    # Handlers
    # --------------------------

    def register_handlers(self):

        @self.bot.message_handler(commands=['active'])
        def active(message):
            for trader in self.traders:
                self.api.position_update(trader)
                self.api.load_limit_orders(trader)
                self.monitor.notify_active_position_info(trader)

        @self.bot.message_handler(commands=['help'])
        def help_cmd(message):
            msg = (
                "Available cmds:\n"
                "💬 Update traders\n"
                "/refresh --roi <value> --pnl <usd> --period <period>\n"
                "  --roi / -r : minimal ROI %\n"
                "  --pnl / -p : minimal PnL USD\n"
                "  --per / -t : day/week/month/allTime\n\n"
                "💬 Print active positions of that trader set\n"
                "/active\n\n"
                "💬 Long vs Short overview\n"
                "/longshort --range <arg>\n"
                "  --range / -r : two options: 1 (for each coin together) / 2 (for each coin separately)\n\n"
                "💬 BTC vs Altcoins volume (no leverage)\n"
                "/volume\n\n"

                "💬 Positions with WAIT status\n"
                "/sniper\n\n"

                "💬 Big fills events\n"
                "/events\n"
            )
            self.bot.reply_to(message, msg)

        @self.bot.message_handler(commands=['refresh'])
        def refresh(message):
            args = self.parse_args(message.text)

            step_valid = 0
            self.config.set_attribute("PERIOD", "day")  # default

            # ROI
            if "roi" in args:
                self.config.set_attribute("MIN_ROI", float(args["roi"]))
                step_valid += 1
            if "r" in args:
                self.config.set_attribute("MIN_ROI", float(args["r"]))
                step_valid += 1

            # PNL
            if "pnl" in args:
                self.config.set_attribute("PNL_MIN", int(args["pnl"]))
                step_valid += 1
            if "p" in args:
                self.config.set_attribute("PNL_MIN", int(args["p"]))
                step_valid += 1

            # PERIOD
            if "per" in args:
                per = args["per"]
                if per in ("day", "week", "month", "allTime"):
                    self.config.set_attribute("PERIOD", per)
            if "t" in args:
                per = args["t"]
                if per in ("day", "week", "month", "allTime"):
                    self.config.set_attribute("PERIOD", per)

            if step_valid != 2:
                self.bot.reply_to(message,
                    "/refresh --roi <value> --pnl <value> --period <period>")
                return

            self.config._reload()

            self.traders = self.api.get_leaderboard(timeframe=self.config.period)
            self.monitor.notify_leader_trades(self.traders)

            self.last_trader_load = {}
            for trader in self.traders:
                self.api.position_update(trader)
                self.api.load_limit_orders(trader)
                self.last_trader_load[trader.address] = time.time()
                self.monitor.notify_active_position_info(trader)

            self.bot.reply_to(message, "✔ Traders refreshed")

        @self.bot.message_handler(commands=['sniper'])
        def sniper(message):
            self.bot.reply_to(message, "WAIT positions:")
            for trader in self.traders:
                self.monitor.notify_active_position_info(trader, True)

        @self.bot.message_handler(commands=['volume'])
        def volume(message):
            self.bot.reply_to(message, "📊 Volume calculation in progress…")
            
            btc_volume = 0.0
            altcoin_volume = 0.0
            coin_volumes = {}
            
            for trader in self.traders:
                for coin, pos in trader.positions.items():
                    if pos.is_long is None:
                        continue
                    
                    # Use absolute position value (no leverage)
                    pos_value = abs(pos.position_value)
                    
                    if coin not in coin_volumes:
                        coin_volumes[coin] = 0.0
                    coin_volumes[coin] += pos_value
                    
                    if coin == "BTC":
                        btc_volume += pos_value
                    else:
                        altcoin_volume += pos_value
            
            total_volume = btc_volume + altcoin_volume
            
            if total_volume == 0:
                self.bot.reply_to(message, "❌ No active positions found")
                return
            
            btc_percent = btc_volume / total_volume
            
            # Build response message
            response = "📊 *BTC vs Altcoins Volume*\n\n"
            response += f"💰 *Total Volume:* `${total_volume:,.0f}`\n\n"
            response += f"₿ *BTC Volume:* `${btc_volume:,.0f}` ({btc_percent*100:.1f}%)\n"
            response += f"🔸 *Altcoin Volume:* `${altcoin_volume:,.0f}` ({(1-btc_percent)*100:.1f}%)\n\n"
            response += f"{self.text_bar(btc_percent)}\n\n"
            
            # Top 5 coins by volume
            response += "📈 *Top Coins by Volume:*\n"
            sorted_coins = sorted(coin_volumes.items(), key=lambda x: x[1], reverse=True)[:5]
            for i, (coin, vol) in enumerate(sorted_coins, 1):
                coin_pct = vol / total_volume * 100
                response += f"{i}. `#{coin}`: `${vol:,.0f}` ({coin_pct:.1f}%)\n"
            
            self.bot.reply_to(message, response, parse_mode="Markdown")

        @self.bot.message_handler(commands=['longshort'])
        def longshort(message):
            arg = self.parse_args(message.text)

            value = 1
            if "range" in arg:
                value = int(arg["range"])
            if "r" in arg:
                value = int(arg["r"])

            if value == 1:
                self.bot.reply_to(message, "Long/Short calculation… (for each coin together)")
                
                com_longs  = 0
                com_shorts = 0
                
                # Теперь правильно считаем позиции
                for trader in self.traders:
                    for coin in trader.positions.keys():
                        pos = trader.positions[coin]
                        if pos.is_long:
                            com_longs += 1
                        else:
                            com_shorts += 1

                total = com_longs + com_shorts

                if total == 0:
                    return self.bot.reply_to(message, "No positions")

                longs_percent = com_longs/ total    # число 0..1

                resp = f"All crypto, Longs {int(longs_percent*100.0)} % / Short {int(100.0 - longs_percent*100)} %\n"
                bar = self.text_bar(longs_percent)
                resp += bar
                self.bot.send_message(message.chat.id, resp)
                return

            self.bot.reply_to(message, "Long/Short calculation… (for each coin separately)")
            temp_dict = {}

            for trader in self.traders:
                for coin, pos in trader.positions.items():

                    if coin not in temp_dict:
                        temp_dict[coin] = {"long": 0, "short": 0}

                    if pos.is_long:
                        temp_dict[coin]["long"] += 1
                    else:
                        temp_dict[coin]["short"] += 1
            
            for coin, data in temp_dict.items():
                total = data["long"] + data["short"]
                if total != 0:
                    long_ratio = data["long"] / total
                    resp = f"#{coin} Longs {int(long_ratio*100.0) } % / Shorts {int(100-long_ratio*100.0)} %\n"
                    bar = self.text_bar(long_ratio)
                    resp += bar
                    self.bot.send_message(message.chat.id, resp)                    
                    time.sleep(3)

            self.bot.send_message(message.chat.id, "Finish")           
  

        @self.bot.message_handler(commands=['events'])
        def events(message):
            self.bot.reply_to(message, "Events module in development…")

    # --------------------------
    # Your main loop
    # --------------------------
    def run(self):
        while True:
            for trader in self.traders:
                event_list = []
                try:
                    trader_timestump = self.last_trader_load.get(trader.address, 0)
                    event_list = self.api.position_fills(trader, trader_timestump)
                    self.last_trader_load[trader.address] = time.time()
                    if event_list:
                        self.monitor.push_event(trader, event_list)
                        self.api.load_limit_orders(trader)
                        self.api.position_update(trader)
                    time.sleep(1.5)
                except Exception as e:
                    print("Error:", e)
            time.sleep(self.config.poll_interval)


if __name__ == "__main__":
    controller = BotController()
